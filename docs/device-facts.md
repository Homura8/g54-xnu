# G54 device facts (milestone M1)

## Current: after OTA to 5-8-6 (12 November 2026, ~15:45–15:55 UTC)

Sources: private `facts/20261112T154824Z-adb`, `facts/20261112T154843Z-fastboot`,
direct read-only `getprop`/`/proc`/sysfs listings, and offline analysis of the
verified Motorola package. Supersedes the 5-8-3 table below where they differ.

| Field | Observed value | Source |
| --- | --- | --- |
| OTA path | 5-8-3 (slot A) → 5-8-4 (slot B) → **5-8-6 (slot A)**, all OTAs on 2026-11-12 | `getprop` after each reboot |
| Build | `motorola/cancunf_g_sysn/cancunf:15/V1TDS35H.83-20-5-8-6/f6c76f-a73c57`; vendor `cancunf_g_vext/…/f6c76f`; security patch 2026-09-01 | `getprop` |
| Bootloader | `MBM-3.1-cancunf_g_vext-f9d83-V1TDS35H.83-20-5-8-6-f6c76f` | `getprop`, `getvar` |
| Kernel | `5.10.240-android12-9-00006-g25161a557b20-ab14744618`, built 20 Jan 2026; **the same GKI build on 5-8-3, 5-8-4 and 5-8-6** | `/proc/version`, `getvar`, package `boot.img` |
| Slots | current `a`; `slot-successful` a/b `yes`; `slot-retry-count` a/b `1`; unbootable a/b `no` | `getvar all` |
| Virtual A/B | enabled, userspace snapshots, compression; `merge_delay_seconds=300`; right after the OTA `snapshot-update-status: snapshotted` | `getprop`, `getvar` |
| AVB | `ro.boot.vbmeta.digest` = digest recomputed from the package's `vbmeta.img` + `vbmeta_system.img` (chain order vbmeta → vbmeta_system); that vbmeta holds the `boot`, `dtbo`, `vendor_boot` hash descriptors, and all three match the package images | `getprop` + host AVB parse |
| Panel | 1080×2400, 400 dpi | `wm size`, `wm density` |
| Storage | UFS (`/dev/block/sdc*`; `boot_b` → `sdc65`) | `ls -l /dev/block/by-name` |
| RAM | 8 GB (`MemTotal` 7,786,768 kB) | `/proc/meminfo`, `getvar ram` |
| LK framebuffer | runtime `/chosen` has `atag,videolfb`, `atag,videolfb-fb_base_h/_l`, `atag,videolfb-vramSize`; reserved node `mblock-15-framebuffer`. Values are not readable as shell (SELinux) | `/proc/device-tree` listing |
| Watchdog / reboot-mode | `watchdog@1c007000` (`mediatek,mt6855-wdt`); `reboot-mode` offset `0x24`, mask `0xf`, bootloader = `3`; bound to Linux `syscon-reboot-mode` and `mtk-wdt` | package DTB + `/sys/bus/platform/drivers` |
| Fastboot reason after `adb reboot bootloader` | `preloader set fastboot mode` | `getvar all` |
| `fastboot boot` | **not implemented**: replies `(bootloader) command is not implemented!` then `OKAY`, and nothing boots | [E0](experiments/2026-11-12-e0-fastboot-boot.md) |
| PSCI | 1.0, method `smc` | package DTB |
| LK boot of a modified `boot_a` | accepted: stock v4 layout with a replaced gzip kernel stream, stale AVB hash, orange warning; jumps to the arm64 Image with x0 = DTB | [E1](experiments/2026-11-12-e1-g1-probe.md) |
| LK framebuffer visibility | filling `atag,videolfb-fb_base`…`+vramSize` is visible on the panel | E1 |
| Return to Fastboot from our code | reboot-mode 3 + PSCI `SYSTEM_RESET` → `reason: preloader set fastboot mode`; reboot-mode 3 + watchdog `SWRST` → normal boot | [E2](experiments/2026-11-12-e2-psci-reset.md), E1 |
| Manual Fastboot | Power + Volume Down → `reason: Volume down key pressed` | E1 |
| Exception level at kernel entry | **EL1** (not EL2) | E2 on-screen diagnostic |
| XNU on the G54 | ruby's kernel + `0200-g54-early-framebuffer` boots to IOKit: `RUBY GIC: ready gicd=1`, SGI1 OK on cpu0 (MPIDR Aff 0), AppleCLCD at `0xfeac6000` stride 4320 | [E5](experiments/2026-11-12-e5-xnu-first-boot.md) |
| Watchdog at kernel entry | enabled (`WDT_MODE` bit 0 = 1); feed it at `0x1c007008` with `0x1971` | E2 |

**Matching restore images:** the package
`CANCUNF_G_SYS_V1TDS35H.83_20_5_8_6_subsidy_DEFAULT_regulatory_DEFAULT_cid50_CFC.xml.zip`
(zip SHA-256 `a8fab65dbf6b44ed…d1f78477`, all 43 `flashfile.xml` MD5s match)
is the installed build. Its `boot.img` (SHA-256 `e0fe4010…37cc2d4`) is the
image the phone's own vbmeta expects for `boot_a`. Caveats: its
`flashfile.xml` targets `_a` only, flashes preloader/LK/TEE/GPT/efuseBackup
and *erases* `nvdata`, so it must never be run wholesale. Use individual,
named images only. Its product label is `cancunf_g_sys`, the phone's is
`cancunf_g_sysn`; the build hashes match exactly.

## Observed on the owner's XT2343-2 before the OTAs (12 November 2026 UTC)

These are **historical observations**, not assertions about the phone
following its later OTA. Sources: private
`facts/20261112T143123Z-adb`,
`facts/20261112T143344Z-fastboot` and direct read-only Android properties.
The original reports remain local and uncommitted. **Recheck after any OTA.**

| Field | Observed value |
| --- | --- |
| Model / device / SKU | moto g54 5G / `cancunf` / `XT2343-2` |
| SoC / core types | `MT6855V/AZA`, Cortex-A55 and Cortex-A78 (counts unverified) |
| Software channel | `retapac` |
| Android / launch API | Android 15 / 33 |
| Build | `V1TDS35H.83-20-5-8-3` |
| Build fingerprint | `motorola/cancunf_g_sysn/cancunf:15/V1TDS35H.83-20-5-8-3/6e233-fa3e4:user/release-keys` |
| Bootloader | `MBM-3.1-cancunf_g_vext-31a87-V1TDS35H.83-20-5-8-3-6e233` |
| Lock state | Android `ro.boot.flash.locked=0`, `verifiedbootstate=orange`; Fastboot `securestate=flashing_unlocked` |
| A/B | slot A active; 2 slots |
| Fastboot mode / download limit | bootloader Fastboot (`is-userspace=no`); 268435456 bytes maximum download |
| Visible named partitions | `boot`, `vendor_boot`, `dtbo`, `lk`, `vbmeta`, `vbmeta_system`, `super`, others |
| `init_boot` | not seen in the `/dev/block/by-name` listing; absence not independently verified |
| Panel/LK framebuffer | unknown; Linux `/sys/class/graphics/fb0` not present |
| Boot header, runtime DTB, storage LUN, recovery, temporary boot | unknown |

**Firmware caution:** the owner subsequently reported Android OTA
`...5-8-4` in progress and downloaded a separate Motorola Software Fix
`...5-8-6` package, not yet proven to match the current installed firmware.
Neither the OTA's completion nor any package compatibility is established
here. See [hardware-loop.md](hardware-loop.md) for the current procedure.

Every porting decision below depends on these facts. Record each value with
its source and date. **Status `unknown` means nobody has observed it; do not
fill it from a spec sheet, a forum post or another phone.** Collect read-only
facts first; nothing here needs an unlocked bootloader unless marked.

**First time connecting the phone? Follow the [read-only M1 session checklist](first-session.md) before running the commands below.**

## How to collect (read-only)

`scripts/m1_facts.py` gathers most rows below. It cannot change the phone: every
command is checked against a read-only allowlist (`getprop`, fixed `/proc` and
`/sys` reads, partition-name listings, `fastboot getvar all`) before it runs,
and serial numbers, IMEIs and MAC addresses are replaced by short hashes.
Results go to `facts/` (never committed; review before sharing).

```sh
brew install --cask android-platform-tools   # adb + fastboot
python3 scripts/m1_facts.py adb              # Android running, USB debugging on, prompt accepted
python3 scripts/m1_facts.py fastboot         # phone in fastboot mode (Power + Volume down)
python3 scripts/m1_facts.py bootimg boot.img vendor_boot.img init_boot.img   # stock images, offline
python3 scripts/m1_facts.py dtb some.dtb      # any DTB or blob containing DTBs, offline
```

Entering fastboot mode and running `getvar` changes nothing on the phone.
Stock `boot`/`vendor_boot` images come from the exact firmware build the phone
runs (match `ro.build.fingerprint`); reading them from the phone itself needs
root and is not part of M1.

| Fact | Value | Source / how to obtain | Status |
| --- | --- | --- | --- |
| Exact model number (XT…) and region/carrier | XT2343-2 / retapac software channel | `ro.boot.hardware.sku`; `ro.carrier` | observed 2026-11-12 |
| Device codename | cancunf | `adb shell getprop ro.product.device` | observed 2026-11-12 |
| SoC | MT6855V/AZA | `adb shell getprop ro.board.platform`, `ro.soc.model` | observed 2026-11-12 |
| CPU clusters | Cortex-A55 + Cortex-A78 types; counts/affinity not confirmed | MIDR via M1 collector | observed types, counts unknown |
| RAM size | | `/proc/meminfo` | unknown |
| Storage type (UFS/eMMC) | | `adb shell ls /dev/block/by-name`, `getprop ro.boot.bootdevice` | unknown |
| Android version / launch API level | 15 / 33 (pre-OTA) | `getprop ro.build.version.release`, `ro.product.first_api_level` | observed 2026-11-12 |
| A/B slots, current slot | two slots / A | `getprop ro.boot.slot_suffix`; `fastboot getvar current-slot`, `slot-count` | observed 2026-11-12 |
| Boot image header version | | `getprop ro.boot.boot_image_version`? else unpack the stock `boot` image | unknown |
| `vendor_boot` / `init_boot` present | vendor_boot listed; init_boot not listed | `ls /dev/block/by-name` | observed 2026-11-12 |
| Where the DTB lives | | stock `boot`/`vendor_boot`/`dtbo` unpacked on the host | unknown |
| Panel resolution, framebuffer address and stride left by LK | | DTB `framebuffer`/`memory` reservations; later confirmed on device | unknown |
| Bootloader unlock eligibility | unlocked | Motorola's eligibility, Fastboot `securestate=flashing_unlocked`, ADB `ro.boot.flash.locked=0` | observed 2026-11-12 |
| `fastboot getvar all` | product=cancunf, slot A/2, bootloader Fastboot, 256 MiB download; other variables may be absent | Fastboot M1 collector | observed 2026-11-12 |
| `fastboot boot` (RAM boot) accepted | unknown; reports of unsupported command | **device-specific validated test only after matching recovery** | unknown |
| Recovery path if a boot fails | | stock firmware for this exact model + a tested restore procedure | unknown |
| Touch controller, PMIC/charger, display bridge | | DTB compatibles, `dmesg` | unknown |

## Working hypotheses to check (not facts)

- ruby's phone launched with Android 12 and boots a **header v2** image with the
  DTB inside `boot`. A phone launched with Android 13 normally uses **header
  v4** with `vendor_boot` and GKI. If true for the G54, ruby's 128 MiB v2
  layout does not apply as-is and the boot-image packer needs a v4 path.
- LK on the G54 is a Motorola build, not Xiaomi's. Accepted image sizes, the
  load addresses and the handoff (EL2/EL1, `x0` = DTB) must be observed, not copied.
- MT6855 has Cortex-A78 and A55 cores; ruby runs XNU on its six A55 cores only.
  Starting on the little cores is the conservative assumption.

## Backups before any write

Before anything other than read-only commands: save the stock `boot`,
`vendor_boot`, `init_boot`, `dtbo`, `vbmeta*` and `lk*` images for the current
slot, record their SHA-256 here (never commit the images), and confirm that the
recovery path restores them. Unlocking normally wipes user data.
