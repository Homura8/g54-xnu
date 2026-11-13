# Status and handoff

## Milestones

| Milestone | Needs the phone | State |
| --- | --- | --- |
| **M2** toolchain: reproducible kernel pipeline (line K0) | no | **done**: CI run [43207707172](https://github.com/Homura8/g54-xnu/actions/runs/43207707172) reproduced ruby's kernel code and data (exec-data `6b22fc25…`) without any KDK, in 10 minutes |
| **M1** device facts and safety baseline | read-only first | **done for 5-8-6** (2026-11-12 UTC): post-OTA firmware, slot, AVB chain, LK framebuffer/watchdog sources and a cryptographically matched stock `boot.img` recorded in [device-facts.md](device-facts.md) |
| **M3** first observable execution: LK runs our code (panel colour), then XNU's early framebuffer mark | yes, controlled experiment | **done 2026-11-12**: [E1](experiments/2026-11-12-e1-g1-probe.md) LK runs our probe; [E2](experiments/2026-11-12-e2-psci-reset.md) unattended return to Fastboot; [E4](experiments/2026-11-12-e3-e4-handoff-screen.md) scanout `0xfeac6000`/4320; **[E5](experiments/2026-11-12-e5-xnu-first-boot.md) XNU boots on the G54**: GIC, SGI, VM, IOKit platform expert, AppleCLCD on the panel |
| **M4** storage and root: UFS from XNU, iOS root mounted, launchd | yes | **done 2026-11-12**: [E15](experiments/2026-11-12-e15-ios-root.md) owner photos show iOS 16.7.16 HFS+ root mounted read-write, real Apple launchd PID 1 and early boot complete |
| **M5** graphical iOS interface | yes | **done 13 November 2026**: [E21](experiments/2026-11-13-e21-home-screen.md) home screen; **[E26](experiments/2026-11-13-e26-ios-touch.md) real touch in iOS** (Novatek NT36672C, firmware downloaded by the probe, kernel 0202 polled driver): unlock, Settings, App Library, app switcher, Control Center, back swipe |

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

## ▶ Resume here (handoff, 13 November 2026 04:35 UTC)

**State:** iOS 16.7.16 boots to SpringBoard on the G54 in ~3 min with **real
touch and all three side keys** (E26, E28). Phone has **E29** on `boot_a`
(flashed 04:32:25 UTC): kernel **K4** (CI 43363468664, `6b7ddff8…`, patches
0200–0203), cmdline E28's (`… sweetfb_noconsole=1 g54nvt=1 g54keys=1`),
probe `out/g1-lastlog` (touch firmware download + dot test, VRAM clear
before the jump, **LASTLOG page**). The gated CI run 43364654526 (`00ace74`,
same code as K4, 0203 hooks moved) passed. PR #7 is open, not merged.

**E29 result ([run card](experiments/2026-11-13-e29-lastlog.md)):** the LASTLOG
page works; Power + Volume Down is a warm reset (clean log), but the
**press-linked spontaneous reset is a cold PMIC power cycle** (the previous
log came back bit-decayed). Next: read the MT6363 long-press/power-off and
key-interrupt registers through SWINF 2 and compare with what Android's
`mtk-pmic-keys` sets up. Also seen: `bluetoothd`/`fairplayd.h2` relaunch loop.

**How E29 works:** each boot first shows "LAST BOOT LOG" for 25 s:
the tail of the *previous* boot's kernel console, read from RAM
(`sweet_log_ring` PA `0x141c765f8`, `sweet_log_total` PA `0x141c765f0`, valid
for K4 only; recompute with `llvm-nm` + `PA = VA - 0xfffffe0006000000 +
0x140000000` for any other kernel). Ask the owner to press the keys in iOS,
wait for the spontaneous reset (issue #7), and photograph the LAST BOOT LOG
page of the following boot. "NO VALID RING"/garbage means a cold reset
(RAM lost). Write the E29 run card from that.

**Rebuild E29:** probe `python3 scripts/g54_payload.py build --out
out/g1-lastlog -D UFS_FIX -D UFS_HS -D TOUCH_SPI -D TOUCH_FW -D NO_RESV -D
LOADER_S=5 -D LASTLOG_RING=0x141c765f8 -D LASTLOG_TOTAL=0x141c765f0`; image
`scripts/g54_xnu_image.py --topaz out/topaz --kernel out/k4/kernel.development.sweet
--stock out/fw/boot.img --probe out/g1-lastlog --ufs --d22ap out/ipsw/d22ap.adt
--touch-fw out/touch/novatek_ts_fw.bin --cmdline "<E28 cmdline>" --out …`
(`novatek_ts_fw.bin` is extracted locally from vendor_dlkm firmware, never
committed). Local kernel tree with the full patch stack: `out/kxnu` (Apple
xnu-8796.141.3 + `out/kbase/xnu/patches`), used to write and regenerate
patches; each G54 patch must also reverse-apply on its own (CI gate).

**Lessons this session:** never use PMIF SWINF 0 (E27: touch lost); the AP's
channel is SWINF 2 (`regs[25 + 5*soc_chan]`, soc_chan 2). The Novatek report
is big-endian 16-bit x/y in 4320×9600 units with a checksum (stock
`nvt_ts_work_func`). Stock module disassembly (`out/vb/rd/lib/modules`,
`out/dlkm`) answered every register question faster than guessing.

**Next, in order:** (1) ~~press-linked cold reset~~ fixed (E30–E32, kernel 0203 PMIC acknowledgement);
(2) composition/fps issues (#6, #8, #10); (3) RTC, battery, backlight.

## 🎉 Milestone (13 November 2026 UTC): iOS 16.7.16 usable by touch and keys on the G54

[E26](experiments/2026-11-13-e26-ios-touch.md): kernel K3 (patch 0202,
`g54nvt=1`) plus the probe's firmware download gives **real touch in iOS**:
the owner unlocked the phone and used Settings, the App Library, the app
switcher and Control Center. Build E26 with probe `out/g1-tfw3` (`-D UFS_FIX
-D UFS_HS -D TOUCH_SPI -D TOUCH_FW -D NO_RESV -D LOADER_S=8`),
`--touch-fw <novatek_ts_fw.bin from vendor_dlkm>`, K3 from CI run
43359626570 and the cmdline in the run card. Remaining problems are in the
open-issue table below.

## Previous: iOS 16.7.16 home screen on the G54

[E21](experiments/2026-11-13-e21-home-screen.md): E20 plus ruby's synthetic
swipe-up reached **SpringBoard's home screen** (owner photo: Photos, App
Store, Settings, widgets, dock with Phone/Safari/Messages, 4:04). Boot is
about 3 minutes. Touch is a **Novatek NT36672C flashless TDDI on SPI3** ([E22](experiments/2026-11-13-e22-touch-scan.md)). SPI3 reads its ID ([E23](experiments/2026-11-13-e23-touch-spi.md)); the probe downloads its firmware and reads finger reports ([E24](experiments/2026-11-13-e24-touch-fw.md)); the XNU-side driver is next. Open items: no real input (touch/keys), spontaneous restart
after a few minutes with no panic text, no log channel. See E21 "Next".

## Open issues (owner list, 13 November 2026 UTC)

Observed on the E21–E26 iOS boots; keep this list current.

| # | Issue | What is known / first idea |
| --- | --- | --- |
| 1 | ~~**No touch** in iOS~~ **fixed in E26** | One boot of E27 (unchanged kernel) had **no touch in iOS**; cause unknown. The 0202 start-up chip check ran once and gave up on failure; it now retries until it succeeds and reprograms SPI3 after ~2 s of failed reads. Polled at 8 ms; no IRQ (EINT22), no firmware reload on chip watchdog (FD/FE reports are only counted), probe-side download only |
| 2 | ~~**No buttons**~~ **fixed in [E28](experiments/2026-11-13-e28-ios-keys.md)** | Kernel 0203 (`g54keys=1`): volume up = KPD `0x1c00e000` KP_MEM1 bit 0; power/volume down = MT6363 TOPSTATUS `0x1e` bits 1/3 over SPMI through the AP channel SWINF 2 (`PMIF 0x1c804000 + 0x880`). Never use SWINF 0 (E27: lost touch). Volume HUD appears on the left (iPhone layout) |
| 3 | **Garbled framebuffer after the Apple logo and on sleep** (E20, E28) | The probe drew its info screen into OVL1 L0 (`FE0D0000`, pitch 0x1100) too; it shows whenever iOS hides its OVL0 layer. Fixed in the probe (VRAM cleared before the jump), first used in E29; sleep will then show black with the backlight still on (no backlight driver) |
| 4 | **Wrong time and date** (Wed 31 Dec, ~4:00) | No RTC driver: the clock starts at the epoch-ish default. Needs the MT6359-family PMIC RTC (SPMI/PWRAP) or a time passed in by the loader |
| 5 | **No real battery info** | No fuel-gauge/charger driver for the G54 PMIC; the indicator is a placeholder |
| 6 | **Composition glitches**: red clock, no wallpaper, white dock, blank widgets | May share one cause (owner's suggestion): missing/incorrect blending or colour format in the software compositor (alpha/premultiplied, BGRA vs RGBA, or CoreAnimation falling back without GPU). Compare with ruby's/topaz screenshots and the SweetFramebuffer pixel format before changing anything |
| 7 | ~~**Spontaneous restart**~~ **fixed in [E32](experiments/2026-11-13-e32-pmic-ack-ios.md)** after a few minutes (E18, E21) | **Linked to button presses** (E27: same image reset after presses, booted cleanly without; owner saw the same on E18/E21). The reset is below XNU (normal boot, not the loader's Fastboot route). Suspect the MT6363 key long-press/interrupt state (stock regs 0x90f, 0xa0e, 0xa0f); **E28: still resets after presses with the kernel driver on SWINF 2**, so not our channel. E29's probe shows the previous boot's kernel console from RAM (`LASTLOG`) to see what happened before the reset **E29: it is a cold PMIC power cycle** (previous-boot RAM log bit-decayed; warm resets keep it clean). **Owner, 13 November: on battery (no USB power) the same key presses lead, a few minutes later, to a full shutdown instead of a restart; on power-up the log is gone.** So the PMIC powers off after an unserviced key event and only restarts when external power is present. Fix next session (MT6363 key/long-press/interrupt registers) **Cause found and fixed in the probe ([E30](experiments/2026-11-13-e30-pmic-diff.md), [E31](experiments/2026-11-13-e31-pmic-ack.md)):** a power press starts a ~79 s MT6363 countdown (`0xa15–0xa17`) unless the interrupt is acknowledged like the stock PMIC IRQ handler does (write back `0x91b`/`0x91c`, then `0x41b = 1`). Kernel 0203 does this (K5); **E32: keys pressed in iOS, unplugged, phone stays on** |
| 8 | **~5 fps UI and screen tearing** (E26) | Software presentation path (IOSurface copy to the LK scanout, no vsync/double buffering). Likely related to #6 |
| 9 | **Settings → General → About does not load** (E26) | Probably a missing service/property (MobileGestalt, baseband, storage); needs logs |
| 10 | **Blur turns solid white after transitions** in App Library and app switcher; Control Center blur is fine (E26) | Composition: static blur layers cached/rendered differently from animated ones; probably the same root as #6 |
| 11 | **Brightness slider stuck at 50%**, **volume has no effect** (E26) | No backlight driver (panel/`sprd_backlight`/aw99703 in the DTBO) and no audio |

## Previous: fast boot to the iOS lock screen

[E20](experiments/2026-11-13-e20-ufs-hs.md) restored UFS HS-G3 (probe
`-D UFS_HS`) and muted the console over iOS (`sweetfb_noconsole=1`):
**the iOS 16 lock screen appears in about 2–3 minutes** (E18: 30+ minutes),
with the clock advancing. There is no input yet (touch, power, volume). Next:
E21 = E20 + `sweetautoswipe=150000 sweetautoswipeattempts=8
sweetautoswiperetry=20000` (ruby's synthetic swipe-up) toward the home
screen, then a G54 touch/key driver. Build E20/E21 with probe
`out/g1-ufs-hs` (`-D UFS_FIX -D UFS_HS -D LOADER_S=25`).

## Next concrete steps (13 November 2026 UTC, E18 running)

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
   Later samples put backboardd in its main event loop and SpringBoard in a
   synchronous user-cfprefsd preferences wait after Control Center bundle
   loading. Distorted old probe graphics reappear beneath fresh iOS logs;
   the same UI PIDs remain. Treat this as a presentation symptom, not a
   demonstrated reboot. [E19](experiments/2026-11-13-e19-console-isolation.md)
   is host-verified and **staged only**: it adds `sweetfb_noconsole=1` to
   isolate the console drawing over iOS frames. Do not interrupt advancing
   E18 just to run it; repeat live recovery preflight before any future write.
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
