# First physical G54 session — read-only M1

**Goal:** leave with actual device/firmware/bootloader facts. **Stop before** unlocking,
`fastboot boot`, flashing, wiping, rooting, modifying partitions or running an
unknown recovery script. None of those are part of this session. The host
commands below read metadata only; Developer options and USB debugging are
needed to authorise ADB.

## 1. Mac and phone

- Have one G54, a known-good data-capable USB cable, an unlocked Android screen
  and enough battery. Unplug other Android/Fastboot devices.
- On macOS, open Terminal. Platform tools provide `adb` and `fastboot`;
  Python 3 and Git are needed for the collector.
- Phone: Settings > About phone > tap **Build number** seven times to enable
  Developer options; Settings > System > Developer options > **USB debugging**.
  **Do not enable OEM unlocking** merely for M1.
- Connect the phone and accept its **Allow USB debugging?** prompt. If ADB shows
  `unauthorized`, address that first; never skip the authorization screen.

```sh
brew install --cask android-platform-tools
adb version
fastboot --version
git clone https://github.com/Homura8/g54-xnu.git   # skip if already cloned
cd g54-xnu
git pull --ff-only                                    # only on your own clean branch
python3 scripts/check_repo.py
python3 -m unittest discover -s scripts -p 'test_*.py'
adb devices -l                                        # PRIVATE: exposes USB serial
python3 scripts/m1_facts.py adb
```

Do not continue unless `adb devices -l` shows **exactly one** authorised
`device` and the collector prints `Saved to facts/...`.

## 2. Optional bootloader metadata (still read-only)

1. Turn the phone off. Hold **Power + Volume Down** to reach the bootloader
   screen; this does not unlock it. Reconnect USB if needed.
2. In the same `g54-xnu` directory, run:

```sh
fastboot devices                # PRIVATE: exposes USB serial
python3 scripts/m1_facts.py fastboot
```

There must be exactly one Fastboot device. If `getvar all` is unavailable or
fails, **stop** and keep the ADB facts rather than trying alternative OEM or
unlock commands. To leave the screen, select **Start** using the phone's
hardware keys; do not run a flashing/recovery helper.

## 3. Inspect and preserve the results locally

```sh
find facts -name summary.md -print -exec cat {} \;
find facts -name facts.json -print
git status --short              # should NOT show facts/ as a tracked change
```

Review `summary.md`, `facts.json`, `adb-commands.json`, and
`getvar-all.txt` **locally**. Redaction is best-effort, not proof that a
file is safe to share. Keep the original `facts/` directory private.
Never commit or paste raw serials, IMEIs, unlock codes/data, MAC addresses,
tokens, accounts, phone dumps, unredacted logs, firmware images, DTBs, boot
images or Apple OS material. Only copy minimal verified *nonidentifying*
facts into `docs/device-facts.md`, with date/source and any contradictions.

Record the phone's actual **XT model, build fingerprint, Android version,
first API level, product/device, MTK SoC, current slot, bootloader state,
partition names and CPU IDs**. Check whether `vendor_boot` and `init_boot`
appear. Treat absent/permission-denied fields as **unknown**, not `false`.
The Linux framebuffer sysfs entries may be unavailable or may not tell us
what LK leaves active; an LK physical address is **not** established by this
collector.

## 4. Decision after M1

- Identify exact Motorola firmware **for this unit's XT variant, region/CID and
  build**, without flashing or extracting on the phone. Preserve its provenance
  and hashes privately. If verified stock files are available, analyse them
  **offline** (the extra files below are optional, not first-session blockers):

```sh
python3 scripts/m1_facts.py bootimg /private/path/boot.img /private/path/vendor_boot.img
python3 scripts/m1_facts.py dtb /private/path/example.dtb
```

- Verify the real boot header, vendor ramdisk/DTB locations, DTBO, partition
  sizes, boot chain and rollback/recovery constraints. Compare to the
  [PixelOS cancunf BoardConfig](https://github.com/PixelOS-Devices/android_device_motorola_cancunf/blob/seventeen/BoardConfig.mk),
  **as a hypothesis, not a stock-device fact**.
- Only after a matching recovery path is established should a *separately
  approved* boot experiment be designed. `fastboot boot` has been reported
  **unsupported on a Moto G54**, so do not make RAM-only boot an assumption.
  First possible execution milestone: verify a minimally observable payload
  using a device-specific, recoverable path; then XNU stage-0 framebuffer
  evidence. Do not start with iOS userland.

## External evidence (not observations of our phone)

- [Motorola G54 specifications](https://en-us.support.motorola.com/app/answers/detail/a_id/176649/): Android 13 at launch, Dimensity 7020.
- [Motorola developer options](https://en-us.support.motorola.com/app/answers/detail/a_id/159678/).
- [Motorola bootloader legal warning](https://en-us.support.motorola.com/euf/assets/docs/Bootloader-Legal_Agreement_and_Warning.pdf):
  unlock-code requirements and device risks; eligibility depends on variant/carrier.
- [AOSP generic boot](https://source.android.com/docs/core/architecture/partitions/generic-boot)
  and [vendor boot](https://source.android.com/docs/core/architecture/partitions/vendor-boot-partitions):
  boot v3/v4, DTB/vendor ramdisk, Android 13 `init_boot` conventions.
- [G54-specific temporary boot report](https://droidwin.com/fix-bootloader-this-command-is-not-implemented-supported/)
  (single-device report, not a verified property of ours).
- [Motorola Software Fix](https://en-us.support.motorola.com/app/answers/detail/a_id/178862):
  Windows PC required for official rescue; data can be erased.
- [cancunf stock restore research](https://github.com/lukumaki/moto-g54-linux-flasher-debloater/blob/main/docs/stock-restore.md):
  sample firmware XML checks, not permission to flash, not a guaranteed match.
- [ruby-ios-bringup](https://github.com/lky005/ruby-ios-bringup):
  MT6877 demonstration and proven XNU stages, **not** G54 hardware evidence.
