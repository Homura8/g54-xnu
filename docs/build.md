# Kernel build pipeline

## Line K0: reproduce the reference kernel

The first job of the pipeline is to rebuild a kernel that already booted on a
MediaTek phone, bit-for-bit in its code and data, before any G54 change:

1. Fetch `ruby-ios-bringup` at `RUBY_SHA` and run its `ci/prepare-baseline.sh`
   with the public fallback: `MakrSas/ios-topaz` at `BASE_SHA`, manifest root
   `BASELINE_MANIFEST_SHA256` over the 82 sweet-lineage files, plus ruby's
   patches. Gate: patchset `RUBY_PATCHSET_SHA256` (187 files).
2. Add `patches/*.patch` (none in K0). Gate: `G54_PATCHSET_SHA256`.
3. Build with `darwin-xnu-build` at `DXB_SHA`, macOS 13.5 xnu
   (`xnu-8796.141.3`), `DEVELOPMENT`, `MACHINE_CONFIG=SWEET`,
   `-mcpu=cortex-a55`, on `macos-15` with Xcode 16.0 (build `16A242d`).
   The workflow fails if the runner lacks that exact Xcode.
4. Gate: `ci/kernel_hash.py` exec-data hash (`__TEXT_EXEC` plus the data
   segments; excludes `__TEXT` strings and `__LINKEDIT`, which embed build
   paths) equals `KERNEL_EXPECT_EXEC_DATA`. For K0 that is ruby's CI kernel
   (run 42301546006, `6b22fc25…`), which was checked independently before
   this repository existed.

### No KDK

`darwin-xnu-build` normally downloads Apple's Kernel Debug Kit from a
third-party mirror. XNU 8796 links a KDK library only for the `T6000`,
`T8101` and `VMAPPLE` machine configs (`makedefs/MakeInc.def`); the sweet
patches build the open-source arm64 assembly and pmap for `SWEET` instead
(patch 0006). The workflow therefore points `KDKROOT` at an empty
directory and fails if anything is written into it. **Verified in CI run
43207707172:** no KDK on the runner, the directory stayed empty, and the
exec-data gate passed, so the KDK contributes nothing to this kernel.

## After K0: writing G54 patches

A G54 change goes in `patches/02NN-g54-*.patch` (APSL 2.0, XNU paths). Its
pull request updates `G54_PATCHSET_SHA256` (record only for
`KERNEL_EXPECT_EXEC_DATA`). The G54 series today: 0200 framebuffer, 0201
panic reset, 0202 Novatek touch, 0203 keys + PMIC ack, 0204/0205 framebuffer
fixes, 0206 `g54noexec`, 0207 PSCI halt/restart, 0208/0209 shutdown, 0210
USB console ([usb-console.md](usb-console.md)).

### Local patched tree (no Mac, no CI round trip)

`scripts/xnu_tree.sh` rebuilds the exact source tree CI compiles and runs
CI's patch checks locally (macOS, Linux, or Git Bash on Windows; needs git,
Python and network for the first run):

```sh
sh scripts/xnu_tree.sh setup                          # out/base + out/xnu: Apple xnu-8796.141.3 + whole series (committed)
sh scripts/xnu_tree.sh setup 0210-g54-usb-console.patch   # same, but 0210 left as editable working changes
#   edit out/xnu/...
sh scripts/xnu_tree.sh diff patches/0210-g54-usb-console.patch   # working changes -> patch (header kept)
sh scripts/xnu_tree.sh gate patches/0210-g54-usb-console.patch   # forward apply + reverse-check every G54 patch
sh scripts/xnu_tree.sh hash                           # new G54_PATCHSET_SHA256 for config/kernel.env
```

On Windows set `PYTHON=python`. The tree is cloned with LF line endings;
patches are applied from LF copies (`out/lfpatches/`), because Git for
Windows checks the repository out with CRLF. The libpthread/BearSSL/HFS
staging scripts may be skipped on Windows; that only drops the HFS patches
0031/0041, which no G54 patch touches.

Why the gate matters: `build.sh` silently **skips** a patch that does not
apply, and `kernel.yml`'s "G54 patches applied" step reverse-checks every G54
patch against the final tree. A new hunk within 3 lines of another G54
patch's hunk breaks that patch's reverse check (E42); a file created by one
G54 patch must be changed in that patch, not a later one.

Not compiled locally: the kernel needs Xcode 16.0 (CI, ~5 min). Before
pushing, a syntax/type check with any clang against stub headers catches most
mistakes in new C files (see the E42–E47 run card). Remember that a push to a
PR branch cancels its running kernel build.

## Not here yet

- Local kernel compilation (Xcode 16.0); CI is fast enough so far.
