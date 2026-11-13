# G54 Stage-1 Multiboot Stub (Offline Prototype)

Position-independent bare-metal AArch64 Stage-1 chainloader appended after an
Android/ColorOS arm64 Linux `Image` inside a `boot` v4 image.

- `entry.S`: branches over the `G54MBOOT` header (`stub_base + 0x08`), masks
  interrupts, installs Fastboot-safe exception vectors, zeroes `.bss`, and
  enters `mb_main(dtb, stub_base)`. Also provides `linux_trampoline` (copied to
  free DRAM `0x50f00000` before restoring `orig_code0` and jumping to Linux).
- `stub.c`:
  - Fast-paths Android recovery / FastbootD (`androidboot.*` without
    `androidboot.force_normal_boot=1`) directly to Linux.
  - Presents a hardware-key menu on OVL0 L1 (`0xfeac6000`) using the verified
    KPD (Vol Up) and MT6363 SPMI SWINF 2 (Vol Down / Power) registers,
    including the E31 PSC interrupt ACK (`0x91b`, `0x91c`, `0x41b=1`).
  - Launches ColorOS/Android via `linux_trampoline` without touching UFS or
    `NONRST2`, or launches iOS 16.7.16 via the proven `ufs_bringup_hs()`,
    `touch_download()`, and `launch_xnu()` sequence.

Build and pack offline with `scripts/g54_multiboot.py`. Do not flash without
following `docs/hardware-loop.md` and `docs/multiboot-feasibility.md`.
