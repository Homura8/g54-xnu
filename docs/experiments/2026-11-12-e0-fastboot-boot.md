# E0: is `fastboot boot` (RAM boot) available on the G54?

| Field | Observation |
| --- | --- |
| UTC date | 2026-11-12 15:49 |
| Device class | Moto G54 XT2343-2 / `cancunf`, `PVT`, unlocked |
| Current OS/bootloader/slot | `V1TDS35H.83-20-5-8-6/f6c76f-a73c57`, `MBM-3.1-cancunf_g_vext-f9d83-V1TDS35H.83-20-5-8-6-f6c76f`, slot A; Fastboot `snapshot-update-status: snapshotted` (post-OTA merge pending) |
| Repo commit + upstream pins | this branch; K0 pins unchanged; no XNU involved |
| Exact hypothesis / one changed input | H: this LK implements `fastboot boot`. Static prediction from the 5-8-6 `lk.img` (identical build to the installed one): **no** |
| Kernel exec-data hash (if rebuilt) | n/a |
| Boot image SHA-256 | private record (`out/g1/`); stock 5-8-6 `boot.img` with the G1 probe in the kernel stream, verified by `scripts/g54_payload.py verify` |
| Stock image source/build + matching recovery verification | Motorola package `…5_8_6…cid50_CFC.xml.zip` (zip SHA-256 `a8fab65d…`), all 43 `flashfile.xml` MD5s match; nothing written in E0 |
| Execution mode | `fastboot boot` (RAM only) |
| Preflight gates | identity ✓, firmware = package ✓, image format ✓, nothing flashed |
| Expected positive observation | a RAM boot would run the probe: phone leaves Fastboot, returns ~15 s later |
| Actual observation and time | `Sending 'boot.img' (65536 KB) OKAY`; `Booting (bootloader) command is not implemented!` then `OKAY`; phone stayed in Fastboot (checked every 5 s for 30 s) |
| Result | **FAIL (as predicted)**: RAM boot is unavailable on this LK |
| Evidence | host transcript above; static analysis below |
| Restoration / Android verified afterwards | nothing to restore; `fastboot reboot` → Android 5-8-6 booted normally |
| What was ruled out | RAM-only testing. Any G54 execution experiment must flash `boot_a` and restore it |
| Next smallest experiment | E1: flash the G1 probe to `boot_a`, observe, restore the verified stock `boot.img` |

## Static analysis (5-8-6 `lk.img`, sub-image `lk`, 1,246,392 bytes)

- The command dispatcher compares the command against a table of
  `{name, handler}` pairs. Entry 4 is `"boot"`; its handler only logs
  `command is not implemented!`, returns 1, and the dispatcher then replies
  **`OKAY`**. A host-side `fastboot boot` therefore *looks* successful. Never
  treat its `OKAY` as an executed image.
- Motorola's pre/post hook lists register handlers only for `download`,
  `flash`, `erase`, `reboot-bootloader` and `set_active`. Nothing overrides
  `boot`.
- `set_active` warns `Bootloader images on target slot %s are not valid!!
  There is risk of bricking HW`. Slot switching is not a safe experiment
  tool on this phone.
