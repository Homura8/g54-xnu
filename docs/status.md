# Status and handoff

## Milestones

| Milestone | Needs the phone | State |
| --- | --- | --- |
| **M2** toolchain: reproducible kernel pipeline (line K0) | no | **done**: CI run [43207707172](https://github.com/Homura8/g54-xnu/actions/runs/43207707172) reproduced ruby's kernel code and data (exec-data `6b22fc25…`) without any KDK, in 10 minutes |
| **M1** device facts and safety baseline | read-only first | **ADB and Fastboot collected 2026-11-12 UTC** on unlocked XT2343-2; firmware/DTB/recovery analysis still pending ([observed facts](device-facts.md)) |
| **M3** first observable execution: LK runs our code (panel colour), then XNU's early framebuffer mark | yes, controlled experiment | **not started**; recovery/boot-entry route unverified; follow [hardware loop](hardware-loop.md) |

Success criteria for M3, borrowed from ruby's proven ladder: (1) LK accepts
the image and a tiny payload paints the panel; (2) the kernel's stage-0 band
appears; (3) kernel log on screen. An in-RAM test is preferred **only if this G54 supports `fastboot boot`**.
G54 community reports raise doubt. Determine an approved recoverable execution
path before writing anything, and link each observed milestone to an image hash.

## Why this route (decided 2026-11-12)

The fastest path to both first execution and a usable iOS is the direct
LK → XNU route proven on the MediaTek MT6877 by ruby-ios-bringup (iOS 16.7.16,
same kernel lineage as ios-qemu, the owner already has the IPSW). UniXNU's
iPadOS 17 route would first need a G54 UEFI port; no MediaTek UniXNU port has
reached a home screen. UniXNU stays the fallback if the G54's LK refuses
direct kernels.

## M1 offline preflight (2026-11-12; **not a G54 hardware test**)

- Collector review found that failed Fastboot `getvar all` commands and ambiguous
  device selection could otherwise yield misleading reports. The focused
  [hardened collector](../scripts/m1_facts.py) now rejects these, checks failed/empty
  ADB `getprop`, accepts both prefixed and bare `getvar` lines, and writes
  only parsed/redacted Fastboot variables to disk (not unparsed raw lines).
- A [read-only first-session runbook](first-session.md) documents the Mac
  commands, privacy review, and stop points. No phone, kernel or Apple asset
  was accessed during this work.
- Motorola confirms the G54 launched with Android 13/Dimensity 7020. The
  community `cancunf` BoardConfig targets boot header v4, 4 KiB pages and
  `vendor_boot`; stock header, DTB placement and `init_boot` on this unit
  remain **unobserved**. Do not infer phone-specific values from that tree.
- **Potential M3 blocker:** a G54-specific report says `fastboot boot` is not
  implemented. RAM-only boot is unverified; do not plan any writable alternative
  without a matching stock recovery path and separate owner approval.
- The manufacturer Software Fix recovery flow requires a Windows PC and can
  erase personal data; do not assume a Mac-only restore route.
- No general Celestia Nexus change is required: these are G54-specific
  preflight constraints. **After** this offline work, the owner successfully
  collected M1 ADB and Fastboot hardware facts; firmware-image and recovery
  verification remain outstanding. See the checkpoint below.

## Next concrete steps (13 November 2026)

1. **Use the connected phone**, if present, under [the agent-led hardware
   loop](hardware-loop.md). The owner has explicitly unlocked the bootloader;
   verified M1 Android+Fastboot data are recorded in [device-facts.md](device-facts.md).
   The phone was later reported OTA-updating from `...5-8-3` to `...5-8-4`;
   **re-read actual firmware/slot after OTA** rather than assuming completion.
2. Extract and verify the locally copied Motorola Software Fix
   `V1TDS35H.83-20-5-8-6` firmware *offline*. It is **not** a matching backup
   until current firmware, component compatibility, rollback and a working
   restore path have been verified. Read the real v4-style boot/vendor_boot
   headers, DTBs and LK behaviour; never copy ruby's v2 format or addresses.
3. Prepare the smallest observable execution payload with a recoverable and
   authorised G54-specific boot route. Distinguish accepted image, entered
   payload, early XNU and iOS userspace; advance on evidence. The **goal**
   is iOS 16.7.16 SpringBoard, not merely a coloured pixel.
4. When implementing a real G54 XNU patch, update patchset pins and record-only
   exec-data gate per [build.md](build.md), then run focused CI. Reuse unchanged
   K0 artifacts in the meantime.

## Observed G54 hardware checkpoint (2026-11-12 UTC)

- ADB `facts/20261112T143123Z-adb`: XT2343-2 (later read-only
  `ro.boot.hardware.sku`), `cancunf`, MT6855V/AZA, Cortex-A55/A78,
  Android 15, first API 33, `retapac`, software
  `V1TDS35H.83-20-5-8-3`, slot `_a`, AVB `orange`, lock flag `0`.
  `vendor_boot`, `dtbo`, `lk` present; no `init_boot` observed;
  `/sys/class/graphics/fb0` absent.
- Fastboot `facts/20261112T143344Z-fastboot`: `product=cancunf`,
  `securestate=flashing_unlocked`, `is-userspace=no`,
  `current-slot=a`, `slot-count=2`,
  `max-download-size=268435456`. These data do **not** establish
  partition sizes or `fastboot boot` support.
- Bootloader property: `MBM-3.1-cancunf_g_vext-31a87-V1TDS35H.83-20-5-8-3-6e233`.
  The downloaded `...5-8-6` package is a distinct version; no firmware
  images have yet been verified in this repository.
- Do not publish raw `facts/` reports or the device serial. No custom
  G54 payload or XNU execution has been observed.

## K0 evidence (2026-11-12)

| Item | Result |
| --- | --- |
| Runner | `macos-15` image `20261104.0514.1`, macOS 15.8.2 (24H232) |
| Xcode | 16.0, build 16A242d (checked by the workflow) |
| KDK | none preinstalled; `KDKROOT` = empty directory, still empty after the build; no download |
| Patchsets | ruby `a9cc0050…` and G54 `a9cc0050…` (187 files) |
| Kernel | exec-data `6b22fc25…` = ruby CI 42301546006; `__TEXT`, `__CTF`, `__LINKEDIT` differ (build paths), all code and data segments identical |
| Time | 10 min with a cold ccache |
