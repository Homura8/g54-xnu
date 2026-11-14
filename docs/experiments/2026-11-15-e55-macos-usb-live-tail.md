# E55 — Fix macOS USB console ring replay and `seq` desync (#15)

- **Date:** 2026-11-15
- **Kernel:** K23 (`E53c`, CI `43615780625`, `g54usb=1`)
- **Host:** macOS (`AppleUSBCDCACMData`, `/dev/cu.usbmodemG54XNU00011`)
- **Result:** **Pass** — live tail, screenshots, and commands work cleanly without triggering boot ring replay or `TimeoutError` waiting for `pong #<seq>`; `log --all` replay still works.

## Cause

On macOS, `os.open()` on the CDC-ACM callout device asserts both DTR and RTS (`SET_CONTROL_LINE_STATE 0x0003`) before Python can issue `TIOCMBIC` to clear RTS (`0x0001`). In `0210-g54-usb-console.patch`, `g54u_set_dtr` sees RTS set on the initial open and starts a full log-ring replay (`pos = 0`, `G54 USB: port open (replay)`). Two things break as a result:

1. `AppleUSBCDCACMData` buffers roughly 8.7 KB of the aborted `0x0003` replay and flushes it once `TIOCMBIS(DTR)` arrives right before `G54 USB: port open (live), log from <pos> of <pos>`.
2. `Session.command()` and `Session.shot()` send `ping` and match `G54 USB: ok pong #(\d+)`, so a replayed `G54 USB: ok pong #1` from earlier in the ring steals the match and leaves `g54_usb.py` waiting for `#2` while the phone executes a higher `#N`.

## Change

Fixed in `scripts/g54_usb.py` (with regression coverage in `scripts/test_g54_usb.py`), requiring no kernel rebuild:

- `Port._open_posix(name, replay)` (when `not replay`): clears `TIOCM_DTR | TIOCM_RTS`, waits `0.03 s` for `g54u_thread` (1 ms poll) to observe `DTR=0`, raises `TIOCM_DTR` alone, and calls `_discard_preopen_replay()` to read and discard buffered pre-open replay bytes until the end of the `G54 USB: port open (live)` line (preserving any trailing live bytes in `self._prebuf`, with a `0.5 s` max / `0.05 s` idle fallback).
- Added `Port.drain()` (non-blocking drain via `select(..., 0)` on POSIX plus clearing `_prebuf`; no-op on Windows) and `Session._drain()`, called at the start of `Session.command()` and `Session.shot()` before `ping`.
- Updated `scripts/test_g54_usb.py` (`test_command_matches_its_own_sequence_number` and new `test_shot_ignores_replayed_pong`).

## Verification

- **Offline unit tests:** `python3 -m unittest discover -s scripts -p 'test_g54_usb.py' -v` → `Ran 7 tests in 0.014s`, `OK`.
- **Live phone (K23, `/dev/cu.usbmodemG54XNU00011`):**
  - `python3 scripts/g54_usb.py cmd status` → `ok status #306 gesture 0 shot 0 sent 32282822`
  - `python3 scripts/g54_usb.py log --seconds 2` → 23 live log lines only (no boot ring replay)
  - `python3 scripts/g54_usb.py shot` → `out/usbshots/20261115-042947-low.png 270x600 0.5s` (Home Screen)
  - `python3 scripts/g54_usb.py cmd status` → `ok status #310 gesture 0 shot 0 sent 32796472`
  - `python3 scripts/g54_usb.py log --all --seconds 3 --out out/usblog/verify-e55-all.log` → `[12927 lines -> out/usblog/verify-e55-all.log]` (replay starts at `Darwin Kernel Version 22.6.0` and reports `G54 USB: port open (replay), log from 0 of 727252`).
