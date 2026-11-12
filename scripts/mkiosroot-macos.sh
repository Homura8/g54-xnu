#!/bin/bash
# Build the SWEET iOS 16 root image on macOS (port of ios-topaz
# tools/mkiosroot.sh, which needs Linux apfs-fuse/hfsprogs).
#
#   sudo bash scripts/mkiosroot-macos.sh IPSW TOPAZ_CHECKOUT OUT.img [SIZE]
#
# IPSW            iPhone10,3 iOS 16.7.16 (20H392) restore IPSW
# TOPAZ_CHECKOUT  ios-topaz at BASE_SHA (config/kernel.env); its
#                 tools/sweet-root-tweaks.py is run unmodified
# OUT.img         raw case-sensitive journaled HFS+ volume (sparse file),
#                 for `fastboot flash userdata OUT.img` and rd=ufsroot0
#
# Same layout as topaz: the OS root, both cryptexes under
# /private/preboot/Cryptexes, the shared cache and cryptex-only files
# hard-linked into the root, logd stores, a plain-plist system keybag, then
# the bring-up tweaks. Owners, modes, symlinks and hard links are preserved
# (rsync -aH --numeric-ids as root). macOS reads the LZBITMAP-compressed APFS
# files transparently, so the HFS+ copy is uncompressed.
#
# Apple's images never leave this machine; nothing here is committed.
set -euo pipefail

[[ $# -ge 3 ]] || { sed -n '2,12p' "$0"; exit 2; }
[[ $(id -u) == 0 ]] || { echo "run with sudo (root owners must be preserved)" >&2; exit 1; }
ipsw=$(realpath "$1") topaz=$(realpath "$2") out=$3 size=${4:-16g}
[[ ! -e $out ]] || { echo "refusing to overwrite $out" >&2; exit 1; }
RSYNC=${RSYNC:-/opt/homebrew/bin/rsync}
"$RSYNC" --version | head -1 | grep -q 'version 3' || { echo "need GNU rsync 3 (brew install rsync)" >&2; exit 1; }

OS=087-86698-044.dmg SYSOS=087-86593-047.dmg APPOS=087-86715-047.dmg   # BuildManifest d22ap Erase
work=$(mktemp -d "$(dirname "$(realpath "$out")")/iosroot.XXXX")
attached=()
cleanup() {
	for d in "${attached[@]}"; do hdiutil detach -force "$d" >/dev/null 2>&1 || true; done
	rm -f "$work"/*.dmg
	rmdir "$work"/* "$work" 2>/dev/null || true
}
trap cleanup EXIT

echo "extracting $OS $SYSOS $APPOS"
unzip -q -j "$ipsw" "$OS" "$SYSOS" "$APPOS" -d "$work"

attach_ro() {  # image mountpoint [raw]
	mkdir -p "$2"
	local extra=()
	[[ ${3:-} == raw ]] && extra=(-imagekey diskimage-class=CRawDiskImage)
	local dev
	dev=$(hdiutil attach "${extra[@]}" -readonly -nobrowse -noverify -owners on -mountpoint "$2" "$1" |
		awk 'NR==1{print $1}')
	attached+=("$dev")
}
attach_ro "$work/$OS" "$work/os"
attach_ro "$work/$SYSOS" "$work/sysos" raw
attach_ro "$work/$APPOS" "$work/appos" raw

mkfile -n "$size" "$out"
rdev=$(hdiutil attach -nomount -imagekey diskimage-class=CRawDiskImage "$out" | awk 'NR==1{print $1}')
attached=("$rdev" "${attached[@]}")
newfs_hfs -s -J -v iOSRoot "$rdev"
mkdir -p "$work/root"
mount -t hfs "$rdev" "$work/root"
diskutil enableOwnership "$work/root" >/dev/null
R=$work/root

copy() {
	echo "copying $1 -> ${2#"$R"}"
	mkdir -p "$2"
	"$RSYNC" -aH --numeric-ids "$1/" "$2/"
}
copy "$work/os" "$R"
copy "$work/sysos" "$R/private/preboot/Cryptexes/OS"
copy "$work/appos" "$R/private/preboot/Cryptexes/App"

dsc=private/preboot/Cryptexes/OS/System/Library/Caches/com.apple.dyld
mkdir -p "$R/System/Library/Caches/com.apple.dyld"
for f in "$R/$dsc"/*; do ln "$f" "$R/System/Library/Caches/com.apple.dyld/${f##*/}"; done

for c in OS App; do
	(cd "$R/private/preboot/Cryptexes/$c" && find . ! -type d ! -path './System/Library/Caches/com.apple.dyld/*') |
	while IFS= read -r f; do
		f=${f#./}
		if [[ ! -e $R/$f && ! -L $R/$f ]]; then
			mkdir -p "$R/$(dirname "$f")"
			src="$R/private/preboot/Cryptexes/$c/$f"
			if [[ -L $src ]]; then cp -P "$src" "$R/$f"; else ln "$src" "$R/$f"; fi
		fi
	done
done

db=$R/private/var/db
install -d -o 272 -g 272 -m 0751 "$db/diagnostics"
install -d -o 272 -g 272 -m 0755 "$db/uuidtext" "$db/diagnostics/timesync"
for d in diagnostics uuidtext diagnostics/timesync; do install -o 272 -g 272 -m 0644 /dev/null "$db/$d/.migrated"; done
install -d -m 0700 -o 0 -g 0 "$R/private/var/keybags"
printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>' \
	'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">' \
	'<plist version="1.0"><dict><key>KeyBagKeys</key><data>U1dFRVQ=</data></dict></plist>' \
	> "$R/private/var/keybags/systembag.kb"
chown 0:0 "$R/private/var/keybags/systembag.kb"; chmod 0600 "$R/private/var/keybags/systembag.kb"

/usr/bin/python3 -I "$topaz/tools/sweet-root-tweaks.py" "$R"

df -h "$R"
umount "$R"
fsck_hfs -fy "$rdev" || true
fsck_hfs -fn "$rdev"
hdiutil detach "$rdev" >/dev/null
attached=("${attached[@]:1}")
echo "root image: $out ($(du -h "$out" | cut -f1) used of $size)"
