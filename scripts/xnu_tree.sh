#!/bin/sh
# Local XNU tree built like kernel.yml + darwin-xnu-build, for writing and
# checking G54 kernel patches without a CI round trip (macOS, Linux, Git Bash).
#
#   sh scripts/xnu_tree.sh setup [0210-g54-foo.patch]
#       out/base (ruby prepare-baseline), out/xnu (Apple XNU at APPLE_XNU_TAG,
#       LF line endings) with the whole series applied in build.sh order and
#       committed. With a patch name, that patch and every later G54 patch are
#       left out of the commit and the named one is applied as working changes
#       (edit it in place).
#   sh scripts/xnu_tree.sh diff patches/02NN-g54-foo.patch "Header line" [more lines...]
#       write the working changes of out/xnu (new files included) as that patch
#       (header kept if the file exists and no header is given)
#   sh scripts/xnu_tree.sh gate [patches/02NN-…patch]
#       CI's checks: apply the patch to a clean copy of the committed tree, then
#       reverse-check every patches/02*.patch ("G54 patches applied")
#   sh scripts/xnu_tree.sh hash
#       G54_PATCHSET_SHA256 for config/kernel.env (ruby ci/patchset_hash.py)
#
# Needs git, python3 (PYTHON=python on Windows), network for the first setup.
# The .sh staging scripts (libpthread, BearSSL, HFS) are run when possible;
# without them the HFS patches 0031/0041 are skipped, which does not affect
# G54 patches.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
PY=${PYTHON:-python3}
command -v "$PY" >/dev/null 2>&1 || PY=python
pin() { sed -n "s/^$1=//p" config/kernel.env; }
lf() { tr -d '\r' < "$1" > "$2"; }

fetch_pin() {   # dir repo sha
    if [ ! -d "$1/.git" ] || [ "$(git -C "$1" rev-parse HEAD 2>/dev/null)" != "$3" ]; then
        rm -rf "$1"
        git -c core.autocrlf=false init -q "$1"
        git -C "$1" config core.autocrlf false
        git -C "$1" fetch -q --depth 1 "$2" "$3"
        git -C "$1" -c advice.detachedHead=false checkout -q FETCH_HEAD
    fi
}

cmd=${1:-}
[ $# -gt 0 ] && shift
case "$cmd" in
setup)
    until=${1:-}
    fetch_pin out/ruby "$(pin RUBY_REPO)" "$(pin RUBY_SHA)"
    fetch_pin out/dxb "$(pin DXB_REPO)" "$(pin DXB_SHA)"
    rm -rf out/base
    ALLOW_PUBLIC_UPSTREAM=1 PYTHON="$PY" PATCHSET_SHA256="$(pin RUBY_PATCHSET_SHA256)" \
        BASE_REPO="$(pin BASE_REPO)" BASE_SHA="$(pin BASE_SHA)" \
        BASELINE_MANIFEST_SHA256="$(pin BASELINE_MANIFEST_SHA256)" \
        sh out/ruby/ci/prepare-baseline.sh out/base
    rm -rf out/xnu out/lfpatches
    mkdir -p out/lfpatches
    git -c core.autocrlf=false clone -q --depth 1 --branch "$(pin APPLE_XNU_TAG)" \
        https://github.com/apple-oss-distributions/xnu.git out/xnu
    git -C out/xnu config core.autocrlf false
    for p in patches/02*.patch; do lf "$p" "out/lfpatches/$(basename "$p")"; done
    for p in out/dxb/patches/*.patch; do lf "$p" "out/lfpatches/dxb-$(basename "$p")"; done
    (cd out/xnu && for s in ../base/xnu/patches/*.sh; do
        MACHINE_CONFIG=SWEET MACOS_VERSION=13.5 KDKROOT= bash "$s" >/dev/null 2>&1 || echo "staging script skipped: $(basename "$s")"
    done)
    # build.sh order: our patches by name (base set + G54), then darwin-xnu-build's own
    list=$( (ls out/base/xnu/patches/*.patch | grep -v '/02[0-9][0-9]-g54-'; ls out/lfpatches/02*.patch) |
        awk -F/ '{print $NF"\t"$0}' | LC_ALL=C sort | cut -f2; ls out/lfpatches/dxb-*.patch)
    applied=0 skipped=0
    for p in $list; do
        b=$(basename "$p")
        if [ -n "$until" ] && case "$b" in 02*) [ "$(printf '%s\n%s\n' "$b" "$until" | LC_ALL=C sort | head -1)" != "$b" ] || [ "$b" = "$until" ];; *) false;; esac; then
            continue
        fi
        if git -C out/xnu apply --check "$ROOT/$p" 2>/dev/null; then
            git -C out/xnu apply "$ROOT/$p" && applied=$((applied + 1))
        else
            skipped=$((skipped + 1))
            echo "skipped (as build.sh would): $b"
        fi
    done
    git -C out/xnu add -A
    git -C out/xnu -c user.name=local -c user.email=local@localhost commit -qm "series up to ${until:-end} (local)"
    echo "applied $applied, skipped $skipped"
    if [ -n "$until" ] && [ -f "patches/$until" ]; then
        git -C out/xnu apply "$ROOT/out/lfpatches/$until" && echo "$until applied as working changes in out/xnu"
    fi
    ;;
diff)
    out=$1
    shift
    git -C out/xnu add -N -A
    {
        if [ $# -gt 0 ]; then
            for l in "$@"; do printf '%s\n' "$l"; done
            printf '\n'
        elif [ -f "$out" ]; then
            tr -d '\r' < "$out" | sed -n '1,/^diff --git/p' | sed '$d'
        fi
        git -C out/xnu diff --no-color
    } | tr -d '\r' > "$out.tmp"
    mv "$out.tmp" "$out"
    echo "$out: $(grep -c '^diff --git' "$out") file(s)"
    ;;
gate)
    rm -rf out/xnu-check
    git -C out/xnu worktree prune
    git -C out/xnu worktree add -q "$ROOT/out/xnu-check" HEAD
    if [ $# -gt 0 ]; then
        lf "$1" out/lfpatches/gate.patch
        git -C out/xnu-check apply "$ROOT/out/lfpatches/gate.patch" && echo "forward apply: OK $1"
    fi
    fail=0
    for p in patches/02*.patch; do
        lf "$p" "out/lfpatches/$(basename "$p")"
        if git -C out/xnu-check apply --reverse --check "$ROOT/out/lfpatches/$(basename "$p")" 2>/dev/null; then
            echo "applied: $p"
        else
            echo "NOT APPLIED: $p"
            fail=1
        fi
    done
    [ $fail = 0 ] && echo "gate: PASS" || { echo "gate: FAIL"; exit 1; }
    ;;
hash)
    [ -d out/base/xnu/patches ] || { echo "run setup first"; exit 2; }
    rm -f out/base/xnu/patches/02*-g54-*.patch
    cp patches/02*.patch out/base/xnu/patches/
    h=$("$PY" out/ruby/ci/patchset_hash.py out/base/xnu/patches 2>/dev/null)
    echo "G54_PATCHSET_SHA256=$h"
    [ "$h" = "$(pin G54_PATCHSET_SHA256)" ] && echo "(matches config/kernel.env)" || echo "(config/kernel.env has $(pin G54_PATCHSET_SHA256))"
    ;;
*)
    sed -n '2,25p' "$0"
    exit 2
    ;;
esac
