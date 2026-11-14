#!/bin/sh
# Build Apple's open-source LZFSE decoder as a small shared library for
# scripts/fw_tools.py (im4p / ipsw-dt) on hosts without libcompression
# (Windows, Linux). macOS does not need this.
#
#   sh scripts/build_lzfse.sh out/tools/lzfse      # -> lzfse.dll (Windows) or liblzfse.so
#
# Windows: clang + lld-link from LLVM (winget install LLVM.LLVM), run from Git
# Bash; no Visual Studio needed: the library is freestanding (decoder only,
# memcpy/memset/memmove provided here, no C runtime). Linux: cc -shared.
set -eu
OUT=${1:-out/tools/lzfse}
LZFSE_REPO=https://github.com/lzfse/lzfse.git
LZFSE_SHA=e634ca58b4821d9f3d560cdc6df5dec02ffc93fd   # Apple, 2017-05-22
mkdir -p "$OUT"
SRC="$OUT/src"
if [ ! -d "$SRC/.git" ]; then
    git init -q "$SRC"
    git -C "$SRC" fetch -q --depth 1 "$LZFSE_REPO" "$LZFSE_SHA"
    git -C "$SRC" -c advice.detachedHead=false checkout -q FETCH_HEAD
fi
test "$(git -C "$SRC" rev-parse HEAD)" = "$LZFSE_SHA"
FILES="lzfse_decode lzfse_decode_base lzfse_fse lzvn_decode_base"

case "$(uname -s)" in
MINGW*|MSYS*|CYGWIN*)
    SHIM="$OUT/shim"
    mkdir -p "$SHIM"
    printf '#pragma once\n#define assert(x) ((void)0)\n' > "$SHIM/assert.h"
    printf '#pragma once\n#include <stddef.h>\nvoid *memcpy(void *, const void *, size_t);\nvoid *memset(void *, int, size_t);\nvoid *memmove(void *, const void *, size_t);\n' > "$SHIM/string.h"
    printf '#pragma once\n#include <stddef.h>\nstatic inline void *malloc(size_t n) { (void)n; return 0; }\nstatic inline void free(void *p) { (void)p; }\n' > "$SHIM/stdlib.h"
    : > "$SHIM/intrin.h"
    cat > "$SHIM/shim.c" <<'EOF'
#include <stddef.h>
void *memcpy(void *d, const void *s, size_t n) { unsigned char *a = d; const unsigned char *b = s; while (n--) *a++ = *b++; return d; }
void *memset(void *d, int c, size_t n) { unsigned char *a = d; while (n--) *a++ = (unsigned char)c; return d; }
void *memmove(void *d, const void *s, size_t n) { unsigned char *a = d; const unsigned char *b = s; if (a < b) while (n--) *a++ = *b++; else { a += n; b += n; while (n--) *--a = *--b; } return d; }
int _fltused = 0;
EOF
    OBJS=""
    for f in $FILES; do
        clang --target=x86_64-pc-windows-msvc -O2 -ffreestanding -fno-stack-protector -mno-stack-arg-probe \
            -fms-extensions -I "$SHIM" -I "$SRC/src" -c "$SRC/src/$f.c" -o "$OUT/$f.o"
        OBJS="$OBJS $OUT/$f.o"
    done
    clang --target=x86_64-pc-windows-msvc -O1 -ffreestanding -fno-builtin -fno-stack-protector \
        -mno-stack-arg-probe -c "$SHIM/shim.c" -o "$OUT/shim.o"
    # dash-style flags: Git Bash would rewrite /dll into a path
    lld-link -dll -noentry -nodefaultlib -machine:x64 -export:lzfse_decode_buffer \
        -export:lzfse_decode_scratch_size -out:"$OUT/lzfse.dll" $OBJS "$OUT/shim.o"
    echo "$OUT/lzfse.dll"
    ;;
*)
    cc -O2 -shared -fPIC -I "$SRC/src" $(for f in $FILES; do printf '%s ' "$SRC/src/$f.c"; done) -o "$OUT/liblzfse.so"
    echo "$OUT/liblzfse.so"
    ;;
esac
