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

## After K0

A G54 change goes in `patches/NNNN-g54-*.patch` (APSL 2.0, XNU paths). Its
pull request updates `G54_PATCHSET_SHA256` and clears
`KERNEL_EXPECT_EXEC_DATA` (record only) until a booted G54 kernel provides a
new reference. Expected first deltas, all waiting on [device facts](device-facts.md):

| Delta | Why | ruby reference |
| --- | --- | --- |
| Early framebuffer address/stride | the first visible kernel stage writes straight to the LK framebuffer | `ci/baseline-changes.patch` (0010/0012) |
| Memory map / ADT inputs | RAM base and reservations differ per board | upstream ADT builder |
| UFS LUN/partition of the root | board layout | 0080 |
| Touch, keys, PMIC | different parts on the G54 | 0085, 0149/0150, 0154 |

## Not here yet

- A G54 boot-image packer: ruby's `tools/image` handles its 128 MiB header v2
  image; the G54 format is unknown until M1.
- Local compilation: needs Xcode 16.0 on the host; deferred until it would
  clearly speed up development.
