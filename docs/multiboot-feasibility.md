# Multiboot feasibility: iOS 16.7.16 and stock Android on one G54

**State (13 November 2026 UTC): offline work only. Nothing in this document
has run on the phone.** The boot side is built, unit-tested and emulated in
QEMU; the storage side has one usable answer today (time-sharing `userdata`)
and one permanent answer that needs a GPT change and fresh owner approval.
Facts below cite a run card or a file; everything else is in
[Hypotheses](#6-proven-emulated-hypothesis).

Note: the G54 runs Motorola's Android 15 (`cancunf`, 5-8-6), not ColorOS.
The menu says ANDROID.

## Verdict

| Question | Answer |
| --- | --- |
| Can one `boot_a` image offer iOS and Android? | **Probably.** The stub, packer and verifier exist (below). The open questions are whether LK loads a boot image larger than the stock AVB `image_size` (H1) and decompresses a ~60 MB raw kernel without hitting its DTB (H2). One bounded experiment (MB-E0) answers both without booting either OS |
| Can both OSes keep their data? | **Not today.** The iOS root uses `userdata`, Android's `/data`. Booting Android against the HFS+ root ends in recovery's "factory data reset" prompt; accepting it destroys the iOS root. The stub hides the Android entry unless the image is packed with `--userdata android` |
| Cheapest way to use both now | **Time-share `userdata`** with one multiboot `boot_a`: switch OS by flashing `userdata` (iOS root: 45 sparse chunks in 384 s, E15; Android: `fastboot -w`). No new risk class |
| Permanent coexistence | Split `userdata` in the GPT (iOS root at the front, smaller Android `userdata` after it), plus a kernel change so the XNU UFS driver mounts the new name. GPT is a critical partition: **fresh owner approval and a separate recovery plan first** |

## 1. Boot chain

Observed on this phone (5-8-6, slot A):

1. Preloader → **LK** (`lk_a`, `MBM-3.1-cancunf_g_vext-f9d83-…-f6c76f`;
   [device facts](device-facts.md)). Unlocked, `securestate=flashing_unlocked`,
   AVB state orange.
2. LK reads `boot_a` (boot header **v4**, 4 KiB pages, gzip kernel, generic
   ramdisk, boot signature; 64 MiB partition and image, E1), `vendor_boot_a`
   (vendor ramdisk, DTB) and `dtbo_a`. There is no `init_boot` in the
   partition list (M1).
3. LK decompresses the kernel stream to **`0x40000000`**, places the DTB at
   **`0x47C80000`** (`0x4CB6A` bytes), and jumps to the Image start at
   **EL1, MMU off, x0 = DTB** (E2, E4). It leaves the UFS device in reset
   (E13) and the watchdog running (E2).
4. Today that Image start is either stock Linux or our probe
   (`raw[0] = b 0x1000`, E1), which loads XNU from a SWEETXNU payload
   (E5–E37b).
5. `fastboot boot` is a no-op that answers `OKAY` (E0): every test is a
   `boot_a` flash. Reboot-mode 3 + PSCI `SYSTEM_RESET` returns to Fastboot
   (E2); Power + Volume Down is the manual escape (E1).

The multiboot image inserts one step between 3 and 4: the stub at the end
of the raw kernel shows a menu, then either restores Image `code0` and
enters Linux as LK would have, or runs the proven probe/loader.

```text
LK ── jump 0x40000000 ──> b stub_off ──> stub menu ──┬─ Android: restore code0, br 0x40000000 (x0 = DTB)
                                                      ├─ iOS: probe_main() = E37b probe → XNU (0x140000000)
                                                      └─ Fastboot: reboot-mode 3 + PSCI SYSTEM_RESET
```

## 2. AVB and vbmeta

- `vbmeta_a` holds the hash descriptors for `boot`, `dtbo` and
  `vendor_boot` and chains to `vbmeta_system`; all three hashes matched the
  package images, and `ro.boot.vbmeta.digest` matched the package vbmeta
  (device facts). The `boot.img` AVB footer is therefore not what LK
  verifies against; the descriptor in `vbmeta_a` is.
- LK in orange state accepts a `boot_a` whose hash no longer matches (E1,
  every experiment since). All those images kept the **stock size and
  layout**, so the bytes the descriptor covers (`image_size`) were exactly
  the bytes LK needed.
- A multiboot image cannot keep that: Linux and the iOS payload must both
  fit in the kernel stream, so `kernel_size` grows and the ramdisk and boot
  signature move later. libavb loads a hash partition by the descriptor's
  `image_size`. If LK hands that buffer to its boot code instead of reading
  the image by its header, the tail is missing (**H1**). The stub detects
  this (missing trailer) and disables the iOS entry; see MB-E0.
- The packer keeps the image self-consistent: header page unchanged except
  `kernel_size`, ramdisk and signature byte-identical, the footer's vbmeta
  blob moved to the new end and `original_image_size`/`vbmeta_offset`
  updated. No vbmeta partition, rollback index or flag is touched.
- If H1 fails, the options are, in order: put the iOS payload outside
  `boot_a` (the stub reads it over UFS; new code, the probe only sends
  control queries today), or a `vbmeta_a` with verification disabled.
  The latter is a security-configuration write and needs fresh owner
  approval (AGENTS.md), even though the package `vbmeta.img` would restore it.
- `scripts/multiboot_audit.py offline --boot … --vbmeta …` now reports each
  hash descriptor's partition and `image_size` (the parser read the wrong
  offsets before this change) and `feasibility_checks.boot_avb_image_size`.

## 3. Dynamic partitions

- `super` holds Android's logical partitions (system, system_ext, product,
  vendor, …) with Virtual A/B, userspace snapshots and compression; merge
  delay 300 s; writes wait for `snapshot-update-status: none` (device facts,
  hardware loop §3a). Nothing here writes `super`.
- First-stage init mounts them from the fstab in the `vendor_boot` ramdisk.
  The multiboot image leaves `vendor_boot` and the generic ramdisk untouched,
  so Android's mount plan is the stock one.
- `super` is not a home for the iOS root: it is sized for Android plus
  snapshots, and creating a logical partition there needs FastbootD and LP
  metadata writes that an OTA would fight. Free space in `super` is
  **unmeasured** (`multiboot_audit.py offline --super` reports it from an
  unsparsed `super` image).
- **OTAs:** an Android OTA writes the inactive slot and switches to it; on
  this phone LK warns that slot B's bootloader images may be invalid (E0).
  With multiboot installed, never accept an OTA (turn off automatic system
  updates in Android's developer options) and never `set_active`.

## 4. Where each OS's root lives

| OS | Root | Location | Evidence |
| --- | --- | --- | --- |
| Android 15 | `system` etc. (dm-verity, from `super`); `/data` | `super`; `/data` = **`userdata`** | stock layout; `userdata` currently does not hold Android |
| iOS 16.7.16 | HFS+ `iOSRoot`, 16 GiB raw image (≈11 GiB used), mounted read-write as `ufsroot0` | **`userdata`**, from its first block: the XNU UFS driver reports `"userdata" on LUN 2: first block 0x1de800, 114359 MiB` | E14, E15 (owner photos), every boot since |

The iOS root is a raw HFS+ image written over the whole start of
`userdata`. Android cannot use that partition while it holds the root:
`/data` fails to mount and Android falls into recovery's "Cannot load
Android system … Factory data reset" prompt; a reset formats `userdata`.
Whether Android could also format `userdata` without asking (for example
when `/metadata` holds no encryption key) is unverified; read the stock
fstab and AOSP fs_mgr/vold for this build before relying on the prompt.

Options for both roots, best first:

| Option | What changes | Risk tier | Open points |
| --- | --- | --- | --- |
| **A. Time-share** | Nothing new: flash the iOS root (`fastboot -S 256M flash userdata ios16-root.simg`, 384 s, E15) or wipe for Android (`fastboot -w`). Repack the multiboot image with the matching `--userdata` | as E15 (owner-approved `userdata` writes; the root image is rebuilt on the owner's Mac) | Each switch loses the other OS's data. Android's first boot after `-w` re-creates the metadata key |
| **B. GPT split** | `userdata` → `iosroot` (16 GiB, existing data in place) + smaller `userdata`; kernel patch so the UFS driver mounts `iosroot` (its log shows it selecting `userdata` by name; source not checked here). `multiboot_audit.py`'s `plan_userdata_split()` computes the LBAs | **critical (GPT)**: fresh owner approval, separate recovery plan | Does LK/preloader accept a changed GPT? Restore path = package GPT image, untested. Android's fstab finds `userdata` by name, so a smaller partition should mount |
| C. Tail carve-out | Android's filesystem made smaller than `userdata`, iOS root in the tail at an offset; kernel patch for a root offset | boot images + `userdata` | Hypothesis only: whether the stock fstab/vold (metadata encryption over the whole partition) can be limited (`length=`) has to be read from the stock `fstab.mt6855` and AOSP vold first |
| D. Root as a file in `/data` | DSU-style pinned file | — | Probably unusable: if `/data` uses metadata encryption (expected for an Android 13 launch device; check the stock fstab), every block under it is encrypted with a key XNU does not have |

## 5. The multiboot image (what this repository builds)

Files: [`payload/multiboot/`](../payload/multiboot/README.md),
[`scripts/g54_multiboot.py`](../scripts/g54_multiboot.py) (build, pack,
verify) and its tests.

Raw kernel (gunzipped stream), written at `0x40000000` by LK:

| Offset | Content |
| --- | --- |
| `0` | stock arm64 Image, byte for byte except `code0` = `b stub_off` |
| `stub_off` | stub: `max(Image file size, image_size)` rounded up to 64 KiB, so Linux's BSS never covers it |
| `stub_off + _end` | `NVTFWBIN` touch firmware, then the SWEETXNU payload at the next 4 KiB, exactly as `g54_xnu_image.py` lays them out after the probe |
| last 16 bytes | `G54MBEND` + image ID (SHA-256-based, also in the stub header) |

Stub behaviour (`stub.c`, one translation unit with `payload/g1/probe.c`):

1. Parse the DTB with the probe's `parse_dtb`; read `/chosen` `bootargs`
   and `linux,initrd-start/-end`, and the bootconfig trailer at the end of
   the initrd (boot header v4 passes `androidboot.*` there).
2. Self-check: header `_end` matches, the trailer and image ID are present
   (else iOS is disabled: H1/H2), and neither the DTB nor the initrd
   overlaps the Linux Image or the stub/payload (else that entry is
   disabled).
3. With `--recovery-passthrough`, a boot without
   `androidboot.force_normal_boot=1` (recovery, FastbootD) goes straight to
   Linux. **Off by default** until MB-E0 shows what LK passes (H5).
4. Menu on the visible OVL0 layer (`find_scanout`, E4): Volume Up/Down move,
   Power starts; auto-boot after `--timeout` seconds unless a key was
   pressed; 0 waits. Keys: KPD `KP_MEM1` bit 0 and MT6363 TOPSTATUS over
   SWINF 2 with the probe's `spmi_rd`; every 20 ms poll acknowledges the PSC
   interrupt group like kernel 0203 (E31/E32). A diagnostic block at the
   bottom shows the mode, all addresses, and why an entry is off.
5. **iOS** = the proven path from the top: state cleared, then
   `probe_main()` built with the E37b fast-probe flags (UFS reset and
   HS-G3, Novatek firmware download, LASTLOG if given, XNU loader with
   reboot-mode 3 for panics). **Android** = `linux_boot` (entry.S): clean
   and invalidate the `code0` line, store it, invalidate the I-cache, enter
   the Image with x0 = DTB and x1–x3 = 0. **Fastboot** = the probe's
   `reboot_bootloader`. Any exception = the probe's red screen and Fastboot.

What the tools check:

- `g54_multiboot.py build`: `-Wall -Werror`, PC-relative relocations only
  (the probe's allowlist), **no unresolved symbols** (catches
  compiler-emitted `memset`/`memcpy` from initialisers; a unit test proves
  the check fires), `mb_hdr` at `+0x08`.
- `pack` verifies its own output; `verify` checks any image against the
  stock `boot.img`: size, header page, ramdisk and signature bytes, footer
  and vbmeta blob, Linux bytes, branch, stub bytes and header fields, blob
  and image ID, raw size below the observed DTB address.
- The probe refactor is safe: six probe configurations (default, E37b fast,
  E26 `tfw3`, `KEY_SCAN`, `PMIC_DIFF`+`PMIC_ACK`, `CPU_FREQ`+`TOUCH_SCAN`)
  build **byte-identical** `.bin` and `.elf` before and after this change.

## 6. Proven, emulated, hypothesis

**Proven on the G54** (run cards): LK accepts a modified kernel stream at
stock size (E1); entry at `0x40000000`, EL1, x0 = DTB at `0x47C80000`
(E2, E4); PSCI return to Fastboot (E2); OVL0 L1 `0xFEAC6000`/4320 is
visible (E4); probe UFS bring-up and HS-G3 (E13, E14, E20), Novatek firmware
download (E24, E26), keys via SWINF 2 and the PSC acknowledgement (E28, E31,
E32), XNU loader to SpringBoard (E21–E37b); iOS root on `userdata` (E15).

**Emulated only** (QEMU 8.2 `virt`, `virtualization=on`, cortex-a55, 8 GiB,
a DTB with the `/chosen atag,videolfb-*` properties, framebuffer read with
QMP `pmemsave`; this change):

| Case | Result |
| --- | --- |
| Android entry, 2 s timeout | fake Image saw x0 = DTB, x1–x3 = 0, DAIF masked and its own `code0` restored |
| `--userdata ios` with default Android | Android shown OFF, falls back to Fastboot (PSCI reset) |
| Recovery passthrough, bootconfig without `force_normal_boot` | Linux entered at once, no menu |
| Same with `force_normal_boot = "1"` | menu, then the default |
| iOS entry with a fake SWEETXNU kernel | menu → probe screens → loader copied it to `0x140000000` and jumped with boot_args revision 2 and the payload cmdline |
| Raw kernel cut short by 4 KiB | "IMAGE TAIL MISSING", iOS OFF, Fastboot |

QEMU cannot check keys (the MMIO window reads all-ones), LK, the PMIC,
UFS or the real Android kernel.

**Hypotheses** (each with the experiment that decides it):

| # | Hypothesis | Decided by |
| --- | --- | --- |
| H1 | LK reads `boot_a` by its header (larger `kernel_size`, moved ramdisk), not only the AVB descriptor's `image_size` | MB-E0: menu appears and the iOS entry is not OFF for "TAIL MISSING" |
| H2 | LK decompresses a raw kernel of stock size + ~17 MB (iOS payload) and keeps the DTB/initrd out of it | MB-E0 diagnostic lines (`END` below `DTB`/`INITRD`, no OFF reason) |
| H3 | Stock Linux boots through `linux_boot` after a few seconds in the stub | MB-E2 |
| H4 | Keys read correctly in the stub (as in the probe's E27 `KEY_SCAN`) | MB-E0: marker moves |
| H5 | `androidboot.force_normal_boot=1` (cmdline or bootconfig) marks normal boots; recovery/FastbootD omit it | MB-E0 `MODE` line; MB-E2 via `adb reboot recovery`. Read-only now: `adb shell cat /proc/bootconfig` in Android (may be denied by SELinux) |
| H6 | The PSC acknowledgement and the delay do not disturb Android's PMIC driver | MB-E2 (keys work in Android, no power-off after ~80 s) |
| H7 | iOS through the stub = E37b (the probe code is identical; only its position and `_end` differ) | MB-E1 |

## 7. Next steps

**Offline, on the Mac (no phone):**

1. Measure: `python3 scripts/multiboot_audit.py offline --boot
   out/fw/boot.img --vbmeta out/fw/vbmeta.img out/fw/vbmeta_system.img
   --xnu-payload out/x/<e37b>.img.payload` (stock `image_size`,
   `kernel_size`, raw size, boot descriptor size).
2. Read LK before risking H1/H2, as E0/E13 did: find how the boot image is
   loaded (header sizes or the libavb buffer) and the gunzip output limit.
   Record the answer in this file.
3. Build and pack (prints raw size, `kernel_size`, sections end and whether
   they exceed the AVB `image_size`):

   ```sh
   python3 scripts/g54_multiboot.py build --out out/mb -D LASTLOG_S=8 \
       -D LASTLOG_RING=0x141c765f8 -D LASTLOG_TOTAL=0x141c765f0
   # the E37b/K11 payload: g54_xnu_image.py writes <out>.payload next to <out>
   python3 scripts/g54_xnu_image.py --topaz out/topaz --kernel <K11> --stock out/fw/boot.img \
       --probe out/g1-fast --ufs --d22ap out/ipsw/d22ap.adt --touch-fw out/touch/novatek_ts_fw.bin \
       --ncpu 8 --cmdline "<E37 + 0209 boot line, docs/status.md>" --out out/x/e38-boot.img
   python3 scripts/g54_multiboot.py pack --stock out/fw/boot.img --stub out/mb \
       --payload out/x/e38-boot.img.payload --touch-fw out/touch/novatek_ts_fw.bin \
       --userdata ios --default fastboot --timeout 0 --out out/mb/mb-e0-boot.img
   ```

**On the phone** (hardware loop §1 preflight each time: `product=cancunf`,
`current-slot=a`, `snapshot-update-status=none`, stock `boot.img`
`e0fe4010…` at hand; writes are `boot_a` only, covered by the standing
authorization):

- **MB-E0 (H1, H2, H4, H5):** flash `mb-e0-boot.img` to `boot_a`, reboot.
  Expected: Hello Moto, unlocked warning, then the menu waiting (timeout 0).
  Photograph the diagnostic block. Press Volume Down/Up (marker moves),
  select FASTBOOT, Power. Pass = menu, no OFF reason for iOS, back in
  Fastboot with `getvar reason` = `preloader set fastboot mode`. Fail
  modes: LK error or boot loop (H1; Power + Volume Down, restore stock),
  "TAIL MISSING" (H1/H2), DTB/INITRD reason (H2), no menu but a red screen
  (exception: photograph it).
- **MB-E1 (H7):** same image, select iOS. Pass = probe screens, then iOS
  SpringBoard with touch and keys as E37b. Then repack with `--default ios
  --timeout 5` for daily use.
- **MB-E2 (H3, H5, H6), only when Android is wanted:** this needs
  `userdata` for Android, which **erases the iOS root** (rebuild/reflash:
  `docs/status.md`, 384 s). Ask the owner first. `fastboot -w`, pack with
  `--userdata android --default android`, flash, boot. Pass = Android lock
  screen, `ro.boot.vbmeta.digest` = `e6a5d57f…`, keys work, no power-off
  after 2 min. Then `adb reboot recovery` and photograph the `MODE` line.
- **Restore** at the end: stock `boot.img` to `boot_a`; for Android also
  `fastboot -w` if `userdata` holds the iOS root.

Not without fresh owner approval: option B (GPT), any `vbmeta` change,
slot switching, and anything on the critical-partition list in AGENTS.md.
