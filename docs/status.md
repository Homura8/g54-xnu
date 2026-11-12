# Status and handoff

## Milestones

| Milestone | Needs the phone | State |
| --- | --- | --- |
| **M2** toolchain: reproducible kernel pipeline (line K0) | no | **done**: CI run [43207707172](https://github.com/Homura8/g54-xnu/actions/runs/43207707172) reproduced ruby's kernel code and data (exec-data `6b22fc25…`) without any KDK, in 10 minutes |
| **M1** device facts and safety baseline | read-only first | **done for 5-8-6** (2026-11-12 UTC): post-OTA firmware, slot, AVB chain, LK framebuffer/watchdog sources and a cryptographically matched stock `boot.img` recorded in [device-facts.md](device-facts.md) |
| **M3** first observable execution: LK runs our code (panel colour), then XNU's early framebuffer mark | yes, controlled experiment | **done 2026-11-12**: [E1](experiments/2026-11-12-e1-g1-probe.md) LK runs our probe; [E2](experiments/2026-11-12-e2-psci-reset.md) unattended return to Fastboot; [E4](experiments/2026-11-12-e3-e4-handoff-screen.md) scanout `0xfeac6000`/4320; **[E5](experiments/2026-11-12-e5-xnu-first-boot.md) XNU boots on the G54**: GIC, SGI, VM, IOKit platform expert, AppleCLCD on the panel |
| **M4** storage and root: UFS from XNU, iOS root mounted, launchd | yes | **UFS done 2026-11-12** ([E6–E14](experiments/2026-11-12-e6-e8-ufs.md)): LK leaves the device in reset; the probe's vendor-order reset + `fDeviceInit` lets XNU find `userdata` (LUN 2, 114,359 MiB) and try `ufsroot0`. Root image not flashed yet |

Success criteria for M3, borrowed from ruby's proven ladder: (1) LK accepts
the image and a tiny payload paints the panel; (2) the kernel's stage-0 band
appears; (3) kernel log on screen. RAM boot is **not** available (E0), so each
step flashes `boot_a` and restores the verified stock 5-8-6 `boot.img`
(SHA-256 `e0fe4010…`) afterwards. Link each observed milestone to an image hash.

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

## Next concrete steps (12 November 2026 UTC, after E14)

**Phone state at handover:** unlocked, 5-8-6, slot A, `boot_a` = the E14 XNU
image (Android won't boot until the stock `boot.img` is flashed back);
`userdata` still holds Android data. Latest kernel: K2 = 0200+0201, CI run
43265320296. Rebuild every input with `docs/hardware-loop.md` §3b. The decoded
D22AP tree is made by extracting `Firmware/all_flash/DeviceTree.d22ap.im4p`
from the IPSW and LZFSE-decoding its IM4P payload (macOS `libcompression`,
algorithm 0x801) into `out/ipsw/d22ap.adt`.

1. **Build the iOS root** on the Mac (needs sudo; ~20 GB free):
   `sudo bash scripts/mkiosroot-macos.sh ~/Downloads/iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw out/topaz out/root/ios16-root.img 16g`
   (ask the owner to run it: it needs their sudo password)
   (macOS port of topaz `mkiosroot.sh`; untested yet). The decoded D22AP
   tree for `/product` is `out/ipsw/d22ap.adt` (pass `--d22ap`).
2. **Flash it:** `fastboot flash userdata out/root/ios16-root.img`. This erases
   Android userdata; it is revertible with `fastboot -w` plus the stock boot.img.
3. **Boot:** build with `--probe out/g1-ufs` (`-D UFS_FIX`), `--ufs --d22ap
   out/ipsw/d22ap.adt`, kernel K2 (CI run 43265320296), cmdline as topaz:
   `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=ufsroot0
   ufsrw=1 rootrw=1 launchd_unsecure_cache=1 unentitled_ios_sim_launch=1
   ignition_level=1 wdt=-1 wdt_test=no_user_checkin g54panicreset=45`.
   Expect slow I/O (PWM link) and then launchd.
4. Then: UFS HS gear, `cpus=6`, USB log channel (ruby `ruby_usb`), input.

### Safety notes learned this session

- `fastboot boot` answers `OKAY` without booting. Never read that as success.
- LK's `set_active` warns that the target slot's bootloader images may be
  invalid (brick risk), and slot B still holds 5-8-4. Do not switch slots.
- Never run the package's `flashfile.xml` wholesale: it flashes preloader, LK,
  TEE, GPT and efuseBackup, and erases `nvdata`.
- Wait for the post-OTA Virtual A/B merge (`snapshot-update-status=none`, no
  `*-cow` mapper devices; merge starts 300 s after boot) before any write.

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
