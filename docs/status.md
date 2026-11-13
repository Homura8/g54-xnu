# Status and handoff

## Milestones

| Milestone | Needs the phone | State |
| --- | --- | --- |
| **M2** toolchain: reproducible kernel pipeline (line K0) | no | **done**: CI run [43207707172](https://github.com/Homura8/g54-xnu/actions/runs/43207707172) reproduced ruby's kernel code and data (exec-data `6b22fc25…`) without any KDK, in 10 minutes |
| **M1** device facts and safety baseline | read-only first | **done for 5-8-6** (2026-11-12 UTC): post-OTA firmware, slot, AVB chain, LK framebuffer/watchdog sources and a cryptographically matched stock `boot.img` recorded in [device-facts.md](device-facts.md) |
| **M3** first observable execution: LK runs our code (panel colour), then XNU's early framebuffer mark | yes, controlled experiment | **done 2026-11-12**: [E1](experiments/2026-11-12-e1-g1-probe.md) LK runs our probe; [E2](experiments/2026-11-12-e2-psci-reset.md) unattended return to Fastboot; [E4](experiments/2026-11-12-e3-e4-handoff-screen.md) scanout `0xfeac6000`/4320; **[E5](experiments/2026-11-12-e5-xnu-first-boot.md) XNU boots on the G54**: GIC, SGI, VM, IOKit platform expert, AppleCLCD on the panel |
| **M4** storage and root: UFS from XNU, iOS root mounted, launchd | yes | **done 2026-11-12**: [E15](experiments/2026-11-12-e15-ios-root.md) owner photos show iOS 16.7.16 HFS+ root mounted read-write, real Apple launchd PID 1 and early boot complete |
| **M5** graphical iOS interface | yes | **First iOS graphics observed in [E18](experiments/2026-11-13-e18-dyld-dof.md): Apple logo, IOSurface 2/3 copied to the panel.** Six A55s verified; wakeup-warning flood suppressed. UI processes advance beyond dyld through input/display setup; lock/home screen and physical touch remain unobserved |

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

**Connected resume (12 November UTC / 13 November Melbourne):** read-only
Fastboot communication was re-established with the same `cancunf`, XT2343-2,
5-8-6 firmware, unlocked bootloader, slot A and `snapshot-update-status=none`
(`facts/20261112T173138Z-fastboot`, private). The stock restore image and K2 hashes were rechecked;
the pinned topaz tools and an iOS-root boot image are staged locally.
Host preparation caught and fixed the macOS builder's nonexistent-output
`realpath` failure, rsync-version SIGPIPE under `pipefail`, Bash 3.2 empty-array
errors and root-owned output permissions. It also fixed `--d22ap`: changing
upstream's constant did not override its import-time default argument, so the
generated tree silently lacked `/product`. The rebuilt tree now matches all
61 supplied D22AP product properties. The first privileged attempt reached HFS+ formatting but
failed at `diskutil enableOwnership` on a manual mount; cleanup left that
output mounted. The builder now reattaches the formatted raw image with
`hdiutil -owners on` and explicitly unmounts it during cleanup. A disposable
32 MiB raw HFS+ test of that attach method reported
`GlobalPermissionsEnabled=true`. The owner's full build then completed:
16 GiB raw volume, about 11 GiB used, both fsck passes OK. Read-only checks
confirmed iOS 16.7.16 / 20H392, arm64 root:wheel 0755 launchd/dyld, 44 matching
shared-cache hardlinks, launchd tweaks and the SpringBoard executable.
Raw root SHA-256: `c549420151e9ad4e342619b9c97dd91340def600f0eb4bf8d8b08442188b6b95`.
Direct raw flashing stopped on the host with `Failed reading from userdata`
before any transfer; convert with upstream `img2simg` first (see below).
The verified sparse root was subsequently flashed successfully (45 chunks,
383.684 seconds), then the prepared boot image was flashed to `boot_a`.
The first iOS-root test was rebooted at 17:58:35 UTC. Owner photos confirm
the writable HFS+ root, real launchd, early boot complete and `exec SpringBoard`,
with no GUI. See [E15](experiments/2026-11-12-e15-ios-root.md).

**Current phone state:** unlocked, 5-8-6, slot A, `boot_a` = the E18 six-A55 XNU
image; `userdata` holds the iOS root. Android restoration requires stock
`boot.img` and a userdata reset. Latest kernel: K2 = 0200+0201, CI run
43265320296. Rebuild every input with `docs/hardware-loop.md` §3b. The decoded
D22AP tree is made by extracting `Firmware/all_flash/DeviceTree.d22ap.im4p`
from the IPSW and LZFSE-decoding its IM4P payload (macOS `libcompression`,
algorithm 0x801) into `out/ipsw/d22ap.adt`.

1. **Preserve the progressing E18 boot.** The owner has now photographed an
   Apple logo and framebuffer copies of IOSurfaces 2/3 to `0xfeac6000`.
   This confirms first graphical iOS output, not yet a lock/home screen.
   E18 is running from `out/g4/e18-nodof-boot.img`, SHA-256
   `441c222b62e82ac99d40fd708a8f46383f9a180f025b7f2389854bea257f696b`.
   It adds only `dtrace_dof_mode=0` to E17. Live Fastboot preflight reverified
   5-8-6/slot A/no pending merge; flash succeeded and reboot was issued at
   **01:40:39 UTC, 13 November 2026**. Apple's XNU source defines mode 0
   as never loading DOF and enables the dyld commpage flag for the macOS
   default, whereas iOS defaults to mode 0. Dyld checks that flag before the
   scan seen in E16's UI-process samples. E18 samples show the same UI PIDs
   advancing through libobjc initialization, backboardd's main entry,
   SweetHIDTouch open, ProgressUI resource loading, and then SpringBoard's
   system-service/Control Center initialization. Rapid `IOAcceleratorES`
   lookups returning zero preceded the logo and do not prove a restart or
   a required GPU driver. Keep observing the logo/ProgressUI transition and
   later UI samples; do not reboot while it advances. A driverkitd kill is
   decoded as Jetsam's **per-process memory limit**, not global exhaustion
   or a captured UI-process kill. The known upstream ICL/MobileGestalt
   deadlock is not established and its patch remains unapplied. Storage
   remains in PWM slow-auto mode; loading is still slow, but no measured
   throughput or controlled boot-time improvement is established.
2. **For root reconstruction only** (E15 is already built and flashed):
   build on the Mac (needs sudo; ~20 GB free):
   `sudo bash scripts/mkiosroot-macos.sh ~/Downloads/iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw out/topaz out/root/ios16-root.img 16g`
   (ask the owner to run it: it needs their sudo password)
   (macOS port of topaz `mkiosroot.sh`; full host build now verified). The decoded D22AP
   tree for `/product` is `out/ipsw/d22ap.adt` (pass `--d22ap`).
   **Convert to Android sparse and flash it:** use upstream
   `anestisb/android-simg2img` at
   `a6fcc0f1c61b2aa5b55516829cd7d13dbfbacb91` (`make img2simg simg2img`),
   then `img2simg out/root/ios16-root.img out/root/ios16-root.simg`.
   Validate a `simg2img` round trip against the raw image before
   `fastboot flash userdata out/root/ios16-root.simg`. This erases
   Android userdata; it is revertible with `fastboot -w` plus the stock boot.img.
3. **Boot:** build with `--probe out/g1-ufs` (`-D UFS_FIX`), `--ufs --d22ap
   out/ipsw/d22ap.adt`, kernel K2 (CI run 43265320296), cmdline as topaz:
   `debug=0xc serial=3 cpus=6 keepsyms=1 -noprogress rd=ufsroot0
   ufsrw=1 rootrw=1 launchd_unsecure_cache=1 unentitled_ios_sim_launch=1
   ignition_level=1 wdt=-1 wdt_test=no_user_checkin g54panicreset=45
   task_wakeups_monitor_rate=0` (E17; E18 also adds `dtrace_dof_mode=0`).
   Use `cpus=1` to reproduce E15 or isolate an SMP regression.
4. Then: UFS HS gear, USB log channel (ruby `ruby_usb`), input.

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
