# G54 hardware iteration loop — fast route to an iOS home screen

**Target:** get the real iPhone X / iOS 16.7.16 userland to SpringBoard on
Moto G54 5G (`cancunf`, XT2343-2). An early XNU marker is a **diagnostic
milestone**, not the final objective. Make the smallest measurable experiment,
run it on this actual phone when access and permission exist, diagnose, repeat.
Follow [AGENTS.md](../AGENTS.md) and the live [status](status.md).

**Important:** this document is an engineering *procedure*, **not blanket
permission to flash anyone's phone**. Before a live session, confirm the owner
authorises the proposed risk tier and the device is physically available. A
phone-free agent can do all host preparation but must not claim a hardware boot.

## 0. Resume correctly

- Work in **g54-xnu**, not Celestia Nexus. Preserve existing local work and
  inspect `git status`, branches, PRs, `AGENTS.md`, `docs/status.md` and
  `docs/device-facts.md`. PR #4 is still an open read-only M1 preflight PR as
  of this workflow's creation; inspect whether it has been merged.
- **Do not assume the earlier M1 firmware is still installed.** On
  2026-11-12 UTC the phone was observed on Android 15
  `V1TDS35H.83-20-5-8-3`, slot A, with an unlocked bootloader. The owner later
  reported an OTA to `...5-8-4` underway. Motorola Software Fix downloaded a
  different `...5-8-6` package to Windows; it was *not* verified as the
  currently installed image. At start of each physical session, recheck the
  fingerprint, bootloader, slot and rollback/recovery constraints.
- The local Mac can reach the physical G54 over **ADB/Fastboot when connected
  and authorised**. Discover that access instead of assuming it is unavailable
  or that only offline work was requested. Never invent a connected device.
- The already-proven XNU 8796 K0 CI baseline needs **no rebuild** merely to
  reproduce the same hash. A G54-specific delta or device boot artifact does.
- The user wants a **fast real iOS home screen**, not a large generic framework,
  GPU drivers, phone features or polish. Use functional stub/CPU-rendered paths
  where already proven upstream; do not claim the port is secure or daily-usable.

## 1. Preflight on every connection

Run **read-only** checks and log only sanitised conclusions:

```sh
git status --short
python3 scripts/check_repo.py
python3 -m unittest discover -s scripts -p 'test_*.py'
adb devices -l                     # PRIVATE: do not paste the serial
adb shell getprop ro.product.device
adb shell getprop ro.boot.hardware.sku
adb shell getprop ro.build.fingerprint
adb shell getprop ro.boot.slot_suffix
adb shell getprop ro.boot.flash.locked
adb shell getprop ro.boot.verifiedbootstate
adb shell getprop ro.bootloader
```

If the phone is in bootloader Fastboot, use `fastboot devices`,
`fastboot getvar product`, `fastboot getvar current-slot`,
`fastboot getvar securestate`, and `fastboot getvar is-userspace` as needed.
**FastbootD is not bootloader Fastboot.** Both modes must be identified rather
than assumed interchangeable. Use only one connected phone; if the tool lists
more, stop. Read-only collector: `python3 scripts/m1_facts.py adb` or
`python3 scripts/m1_facts.py fastboot` in its respective mode.

After an OTA, don't silently trust prior partition contents, security-state
data, inactive slot contents, rollback counters or firmware hashes. If OTA is
running, let it finish; don't interrupt it for experiments.

### Offline firmware preparation

- Identify local **Motorola Software Fix** package and `flashfile.xml` /
  `servicefile.xml`. Extract and analyse locally without running the XML's
  operations. Check ZIP integrity, version, product, variant, region,
  CID **where actually observed**, XML file checksums, and component
  rollback restrictions. Store copies *outside Git*; SHA-256 each source.
- `...5-8-6` downloaded while `...5-8-3` was installed. A higher suffix
  does **not** prove a compatible backup, safe downgrade, or current firmware.
  Get the actual post-OTA build before choosing a restore image. Do not
  accidentally flash a future/older build to the phone.
- Existing host tools: `python3 scripts/m1_facts.py bootimg ...` and
  `python3 scripts/m1_facts.py dtb ...`. Inspect `boot`, `vendor_boot`,
  `dtbo`, `vbmeta*` and `lk` as *offline files*. Cross-check with AOSP
  boot v3/v4 layouts and `cancunf` source, but never substitute community
  values for observations. `init_boot` was absent from M1 partition listing.
- Confirm a **known-good, matching restoration route**: tested official
  Motorola recovery process or reproducibly verified images and command
  sequence for this build, known-working Fastboot access even if Android won't
  start, and all required host tools. A downloaded but untested newer
  package is not yet proof of recoverability. If missing, **stop before
  writing any boot-related partition**.

## 2. Choose one falsifiable experiment

Prefer the shortest discriminating ladder, not a full iOS boot on the first
iteration:

| Gate | Evidence required | If it fails |
| --- | --- | --- |
| G0 boot-image acceptance | Bootloader accepts image *without* layout/signature/decompression error | Investigate stock v4 image header, ramdisk, vendor_boot, AVB, load layout and loader policy |
| G1 execution | Unique nonce/colour/pattern from our payload, photographed or logged | Check entrypoint, exception level, reserved memory, watchdog, display address; don't claim XNU boot |
| G2 XNU early | XNU-owned stage-0 marker and source/build hash | Diagnose shim/ADT/MMU/GIC/timer before userspace |
| G3 usable kernel | CPU init, memory, interrupts, stable logs, read-only storage probe | Change one subsystem; do not attempt root writes yet |
| G4 Darwin PID 1 | Measured userspace heartbeat/launchd | Distinguish kernel faults from userspace service deadlock |
| G5 iOS UI | Apple userland backboardd/SpringBoard, lock/home screen observed on phone | Investigate launch services, framebuffer services, root contents; don't assume Wi-Fi/GPU/camera are needed |

Use existing pinned ruby/sweet paths first. For the first few passes make **one
hardware assumption change per image** and give each build an unmistakable
marker. A silent or timed-out boot is a failed experiment, not success.

## 3. Execute the fastest *recoverable* loop

```text
Discover connected phone + actual firmware + consent
   -> prepare known-good restore artifacts, verify hashes and restore route
   -> choose ONE hypothesis and success/failure signal
   -> build changed payload (or reuse cached pinned kernel)
   -> host-format & size checks; diff against stock; verify exact image hash
   -> select supported execution mechanism and correct Fastboot context
   -> run one approved test; capture screen/logs/panic/bootloader result
   -> restore to known-good state if needed; verify phone/slot
   -> record result + next hypothesis; repeat
```

- Prefer `fastboot boot` **only if this exact bootloader supports it**, not
  because a Xiaomi or Pixel does. G54-specific reports suggest it may be
  unimplemented. Do not probe it with an unverified image.
- If temporary boot is unavailable, G54 community installation guides report
  FastbootD (`is-userspace: yes`) and timestamp/preflash-validation issues.
  **First establish a tested recovery path and precise acceptable target**;
  don't blindly copy instructions for another firmware or custom ROM.
- Device write scope must be agreed for the current session. The owner has
  expressed willingness to reset/flash this *spare* G54 for fast progress,
  but that does not make persistent changes automatically reversible.
  **May automate:** read-only ADB/Fastboot, host builds, extraction, format
  checks, synthetic tests, logs, and reversible boot attempts after a valid
  restore path is proved and permission established.
  **Require explicit new owner approval:** changing partition table/GPT or
  anti-rollback state; preloader, LK/bootloader, TEE, trust/firmware partitions;
  nvram/nvdata/persist/proinfo/efuse/calibration; relock; any action where
  recovery is unverified. Never attempt security/ARB bypass as a convenience.
- On a failed boot, don't fire an endless retry loop or repeatedly force-write
  partitions. Stop, diagnose a distinguishing signature, and revert using the
  *verified* restore image. A/B slots are **not automatically safe backups**:
  OTA may have changed the inactive slot.

## 3a. The proven G54 loop (2026-11-12 UTC, firmware 5-8-6, slot A)

Established by [E0](experiments/2026-11-12-e0-fastboot-boot.md),
[E1](experiments/2026-11-12-e1-g1-probe.md) and
[E2](experiments/2026-11-12-e2-psci-reset.md). Reuse it rather than
rediscovering it:

1. **No RAM boot.** `fastboot boot` replies `OKAY` and does nothing. Every
   test is `fastboot flash boot_a <image>` then `fastboot reboot`.
2. **Image format.** Keep the stock 5-8-6 `boot.img` byte for byte except
   the gzip kernel stream: same `kernel_size`, FEXTRA padding, arm64 Image
   header kept, `raw[0]` branches to code at `raw+0x1000`. Build with
   `scripts/g54_payload.py pack` (it self-verifies). LK accepts the stale
   AVB hash with the orange-state warning. A boot cycle shows Hello Moto
   (about 5 s), the unlocked warning (about 5 s), then our code.
3. **Entry.** LK jumps with the MMU off and x0 = DTB. The visible LK
   framebuffer is read from `/chosen atag,videolfb-fb_base_h/_l` and
   `atag,videolfb-vramSize` in that DTB. Filling the whole vram range is
   visible on the panel.
4. **Automatic return to Fastboot.** Write `3` into the watchdog reboot-mode
   register (`0x1c007000 + 0x24`, mask `0xf`), then PSCI `SYSTEM_RESET`
   (`smc` with `x0 = 0x84000009`). LK then reports `reason: preloader set
   fastboot mode`. A direct watchdog `SWRST` resets but boots normally, so
   the image loops (E1). Every payload, including future shims and XNU panic
   paths, should end with this sequence so the host can poll `fastboot
   devices` without anyone touching the phone.
5. **Manual escape.** If an image loops or hangs, hold Power + Volume Down.
   LK then reports `reason: Volume down key pressed`.
6. **Observation.** USB timing and `getvar reason` are automatic. For values
   only the payload can see, paint a coded screen (white/black bands, green
   separators, rows computed modulo a 1088×2400 screen) and ask the owner
   to read or photograph it.
7. **Restore.** Flash the package `boot.img` (SHA-256 `e0fe4010…`) to
   `boot_a`, then check Android's fingerprint and `ro.boot.vbmeta.digest`
   (`e6a5d57f…`).
8. **Before the first write after any OTA**, wait for
   `snapshot-update-status: none`; the Virtual A/B merge starts 300 s after
   boot.

## 4. Keep small evidence, not giant logs or rebuilds

For every test record a private run card with date UTC, repo commit, toolchain
and CI run, installed firmware/slot, stock/experimental image SHA-256, partition
and execution method, hypothesis, result, log/photograph path, restored state,
and next experiment. Use [run card template](experiments/TEMPLATE.md). Keep
private logs and binary inputs in ignored `facts/`, `out/`, `dumps/` or
an external folder; publish **only explicitly sanitised conclusions**.

- Successful CI proves kernel **compilation/identity**, not LK acceptance or
  XNU execution. A photograph alone proves only what is visible. A booted
  home screen needs on-device evidence, build identity and basic interaction.
- Reuse the K0 build and golden reference when no XNU patch changed. Cache
  expensive host outputs. When only the payload/boot parameters change,
  repack/test without rebuilding XNU if technically justified.
- Use tiny instrumentation and unique stage markers; compare failure log to
  last good run. If a theory fails, preserve the negative result, revert,
  and test the next hypothesis. Don't reintroduce a failed workaround.
- When physical device is disconnected: inspect source, prepare images,
  static validation, tests and the next queued experiment; then stop at the
  hardware boundary rather than inventing observations.
- Keep mainline and PR changes small and independently reviewable, with status
  updated in the same PR. Don't modify Celestia Nexus for G54 specifics.

## Why this loop (source-backed methods, not performance guarantees)

1. [ruby-ios-bringup: experiments](https://github.com/lky005/ruby-ios-bringup/blob/main/docs/en/07-experiments.md)
   records a same-day path from red-screen payload → shim → XNU → UFS root
   (19 Oct), then an iOS home screen (21 Oct); its failure catalogue prevents
   repeated wrong turns. [Boot chain](https://github.com/lky005/ruby-ios-bringup/blob/main/docs/en/03-boot-chain.md)
   and [recovery](https://github.com/lky005/ruby-ios-bringup/blob/main/docs/en/08-recovery.md)
   demonstrate matching full-image layout and a stock restore handle.
   **Their MT6877 addresses/128 MiB v2 header/slot behaviour are not G54 facts.**
2. [ios-spes](https://github.com/AdyaGMD/ios-spes) first validated a live
   FDT and RAM-only diagnostic PID 1, then read-only storage probes and
   userspace; its `NOTES.md` tracks one-variable changes and failed results.
   Its Qualcomm phone supports RAM-only `fastboot boot`, unlike the
   *unverified* G54 route.
3. [PixOS AI development](https://github.com/PixOS-Project/pixelios-kernel/blob/main/docs/AI_DEVELOPMENT.md)
   describes agent-authored tests, scripted hardware experiments, independent
   read-only review and the owner's approval gates. Device observations
   outrank agent claims.
4. [G54/G64 maintainer flashing guide](https://cyberknight777.dev/instructions/cancunf/)
   reports FastbootD and Motorola preflash validation limitations plus
   firmware-specific rollback risks. Treat it as maintainer experience,
   **not** a guarantee for this XT2343-2 / RETAPAC build.
5. [G54 stock restore study](https://github.com/lukumaki/moto-g54-linux-flasher-debloater/blob/main/docs/stock-restore.md)
   validates Motorola XML, product, CID, image hashes and restore sequence,
   but its sample hardware/software identity need not match this device.
   Do not run third-party flashing scripts without auditing them.

**Next action for a connected G54:** record post-OTA firmware/slot;
verify the copied Motorola image package and recovery path; select the
smallest approved boot-image execution probe. The fastest route to SpringBoard
is the route that can be iterated without losing the phone.
