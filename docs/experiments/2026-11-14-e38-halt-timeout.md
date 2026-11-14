# E38: halt-timer power-off (0209) → PSCI smc missing from 0207

| Field | Observation |
| --- | --- |
| UTC date | 14 November 2026, flashed and rebooted 07:16:44 UTC |
| Device class | Moto G54 XT2343-2 / `cancunf` (Fastboot `product`) |
| Current OS/bootloader/slot | `MBM-3.1-cancunf_g_vext-…-V1TDS35H.83-20-5-8-6-…`, slot `a`, `flashing_unlocked`, `snapshot-update-status: none`; `userdata` = iOS 16.7.16 root |
| Repo commit + upstream pins | `main` `3be4ae9`; kernel **K11** = CI run 43427334873 (commit `64df23a`, patches 0200–0209, G54 patchset `3fd0a41e…`), kernel SHA-256 `d5b7f9ab…`, exec-data `36951419…` |
| Exact hypothesis / one changed input | E37b + K11 (0209) + `halt_restart_timeout=60`: when iOS teardown stalls, the halt timer syncs and powers off instead of panicking |
| Boot image SHA-256 | `e38-k11-boot.img` `e191ad38…40b1`: fast probe (status.md flags, `LASTLOG_RING=0x141c765f8`; K11 ring symbols unchanged), `--ncpu 8`, touch firmware appended, status.md best boot line + `halt_restart_timeout=60` |
| Stock image source/build + matching recovery verification | 5-8-6 package via Motorola Software Fix (unpacked folder; all 44 `flashfile.xml` MD5s match); `boot.img` `e0fe4010…37cc2d4` exact |
| Execution mode | bootloader flash of `boot_a` (standing owner authorisation) |
| Preflight gates | identity/slot/unlock/merge state as above, read-only `getvar` before the write |
| Expected positive observation | Settings → General → Shut Down: phone powers off ~60 s after the slide |
| Actual observation and time | ~75 s after the slide (owner stopwatch): `panic(cpu 1 caller 0xfffffe0007b525dc): Halt/Restart Timed Out @IOPlatformExpert.cpp:900`, then automatic return to Fastboot (`getvar reason` = `preloader set fastboot mode`) |
| Result | **FAIL**, cause found (see below) |

## Previous-boot log (LASTLOG page, reboot at 07:23:58 UTC; partly bit-decayed)

The tail matches E37b: `SHUTDOWN COMMITTED … WAITING_ON_SERVICES` (launchd),
`ifnet_detach_final: waiting for IO references on utun… interface to be
released`, then `SWEET AKS` calls. The ring ends mid-line
(`SWEET AKS: AMSACCOUNTSD SE…`); neither the 0209 `G54: halt/restart timed
out` line, 0207's `SWEET: power off` line nor the panic text reached it.
Late-shutdown console output is not captured by the sweetlog ring.

## Analysis (K11 disassembly, `llvm-objdump`)

- The caller is `IOShutdownNotificationsTimedOut` (outlined panic path).
  Line 900 is 0209's **fallback** `panic()` after `sync_internal()` and
  `gIOPlatform->haltRestart(type)`; E37's unpatched panic was line 884. So
  the timer fired, synced and asked the platform to power off, and that
  call returned.
- `IOPlatformExpert::haltRestart` tail-calls `PE_halt_restart`
  (`sweet_halt_restart`, 0207).
- `sweet_halt_restart` loads `0x84000008` (SYSTEM_OFF) into `w0`, executes
  `dsb sy` and returns `-1`: **there is no `smc #0`.** 0207 wrote
  `"dsb sy; smc #0"`; Apple's arm64 assembler (Mach-O) treats `;` as a
  comment, so the `smc` was dropped. The same affects CPU_OFF in
  `quiesceCPU` (it fell into its WFI loop) and the `wfi` in `haltCPU`
  (spins on `dsb`). User **restart** (SYSTEM_RESET) could not have worked
  either. 0201's panic reset is a single `"smc #0"`, which is why panics
  always reached Fastboot; the probe (ELF, GNU syntax) is unaffected.

## Fix

0207 now separates instructions with `"\n\t"`; G54 patchset
`5d74c398…` (reproduced locally with ruby `ci/prepare-baseline.sh` +
`ci/patchset_hash.py`, which also reproduced K11's `3fd0a41e…` first).
Kernel **K12** is built by `kernel.yml`; check its disassembly for
`smc #0` in `sweet_halt_restart` before flashing.

## What was ruled out

The 0209 timer path (it runs and syncs), the `haltRestart` →
`PE_halt_restart` wiring, and the panic-to-Fastboot route.
Not yet known: whether MediaTek's BL31 honours PSCI SYSTEM_OFF with USB
power connected.

## Next smallest experiment

**E39** = E38 inputs with K12. Shut Down → expect power-off ~60 s after the
slide. If SYSTEM_OFF now returns or hangs, try again on battery (USB
unplugged after the slide) to separate BL31 from PMIC/charger behaviour.
Also test Settings → Restart (SYSTEM_RESET; should boot normally, not
Fastboot).

## Host note

This run was prepared on Windows (no WSL). Platform-tools **r37.0.3**
`fastboot flash` hung at `Fetching super (offset=0, size=100000)` before
sending anything (LK has no `fetch`); r35.0.2 flashed in 2 s.
