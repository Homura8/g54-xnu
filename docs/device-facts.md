# G54 device facts (milestone M1)

Every porting decision below depends on these facts. Record each value with
its source and date. **Status `unknown` means nobody has observed it; do not
fill it from a spec sheet, a forum post or another phone.** Collect read-only
facts first; nothing here needs an unlocked bootloader unless marked.

| Fact | Value | Source / how to obtain | Status |
| --- | --- | --- | --- |
| Exact model number (XT…) and region/carrier | | Settings → About phone; box label | unknown |
| Device codename | | `adb shell getprop ro.product.device` | unknown |
| SoC | MT6855 (owner-reported) | `adb shell getprop ro.board.platform`, `ro.soc.model`, `/proc/cpuinfo` | unconfirmed |
| CPU clusters | | `/sys/devices/system/cpu/cpu*/cpu_capacity`, `cpuinfo` part numbers (A55 = 0xd05, A78 = 0xd41) | unknown |
| RAM size | | `/proc/meminfo` | unknown |
| Storage type (UFS/eMMC) | | `adb shell ls /dev/block/by-name`, `getprop ro.boot.bootdevice` | unknown |
| Android version / launch API level | | `getprop ro.build.version.release`, `ro.product.first_api_level` | unknown |
| A/B slots, current slot | | `getprop ro.boot.slot_suffix`; `fastboot getvar current-slot` | unknown |
| Boot image header version | | `getprop ro.boot.boot_image_version`? else unpack the stock `boot` image | unknown |
| `vendor_boot` / `init_boot` present | | `ls /dev/block/by-name` | unknown |
| Where the DTB lives | | stock `boot`/`vendor_boot`/`dtbo` unpacked on the host | unknown |
| Panel resolution, framebuffer address and stride left by LK | | DTB `framebuffer`/`memory` reservations; later confirmed on device | unknown |
| Bootloader unlock eligibility | | Motorola's official unlock programme for this exact model/carrier | unknown |
| `fastboot getvar all` | | fastboot mode, read-only | unknown |
| `fastboot boot` (RAM boot) accepted | | **needs unlock + owner approval**; test with the stock image first | unknown |
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
