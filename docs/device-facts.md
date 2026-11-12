# G54 device facts (milestone M1)

## Observed on the owner's XT2343-2 (12 November 2026 UTC)

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
