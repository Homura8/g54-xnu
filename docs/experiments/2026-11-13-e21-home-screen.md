# E21: iOS 16.7.16 home screen on the Moto G54

| Field | Observation |
| --- | --- |
| UTC date | 2026-11-13; flashed and rebooted 02:38:11 |
| Device / firmware / slot | G54 XT2343-2 `cancunf`, 5-8-6, slot A, unlocked; live preflight: bootloader Fastboot, `snapshot-update-status=none` |
| Image | `out/g4/e21-autoswipe-boot.img`, SHA-256 `e400327fe5939d81a9ee03a9cd37528be923285e5c420ed2a94703bd8d5d8d11` |
| Kernel | K2 (0200 + 0201), CI 43265320296, `2bb9311a…43dc` |
| Probe | `-D UFS_FIX -D UFS_HS -D LOADER_S=25` (`out/g1-ufs-hs`, `f7d08eee…`) |
| Root | E15 iOS 16.7.16 (20H392) HFS+ root in `userdata` (writable) |
| One change vs E20 | cmdline adds `sweetautoswipe=150000 sweetautoswipeattempts=8 sweetautoswiperetry=20000` (SweetHID synthetic swipe-up; ADT and kernel bytes identical, the payload differs only in the cmdline area) |
| Full cmdline | `debug=0xc serial=3 cpus=6 keepsyms=1 -noprogress rd=ufsroot0 ufsrw=1 rootrw=1 launchd_unsecure_cache=1 unentitled_ios_sim_launch=1 ignition_level=1 wdt=-1 wdt_test=no_user_checkin g54panicreset=45 task_wakeups_monitor_rate=0 dtrace_dof_mode=0 sweetfb_noconsole=1 sweetautoswipe=150000 sweetautoswipeattempts=8 sweetautoswiperetry=20000` |
| Observation (owner, photos) | Apple logo, then backboardd `IOAcceleratorES` matching lines, then the garbled probe layer briefly, then the lock screen (4:03), then **"IT SWIPED UP": the iOS home screen**: status bar 4:04 with charging battery, two widgets "Waiting…", Photos, App Store, Settings, the search pill, and a dock with Phone, Safari and Messages (badge). Later synthetic swipes nudge the home screen toward the app switcher without completing |
| Result | **G5 PASS: iOS 16.7.16 SpringBoard home screen on the Moto G54.** No real input yet (touch, power and volume keys do nothing) |
| Also observed | In E20 the phone restarted by itself after a few minutes on the lock screen, with no panic text (a kernel panic would still draw with `sweetfb_noconsole`). This points to a userspace-initiated reboot; the cause is unknown |

## Next

1. **Input:** a G54 touch driver (the controller depends on the panel; the
   probe can print `/chosen mmi,panel_name`; the stock dtbo overlays carry
   Novatek nt36xxx, FocalTech, ILITEK and Chipone nodes) and keys
   (`mediatek,kp` at `0x1c00e000`: hardware key 0 = KEY_VOLUMEDOWN; power on the PMIC).
2. **Spontaneous reboot after a few minutes:** read the persistent log.
   The probe already has a polled UFS engine, so it can show the tail of
   the previous boot's sweet log ring (last 4 MiB of `userdata`) on its
   info screen. That gives a cause without a USB log channel.
3. Cosmetics: draw the probe only into the visible OVL0 layer (the garbled
   OVL1 copy); one autoswipe attempt.
