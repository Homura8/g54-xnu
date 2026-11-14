# E48/E49: issue #14 is InCallService (Side + volume chord)

First issue debugged with the USB console (patch 0210): live logs instead of
LASTLOG photos.

| Run | Image / change | Observation (owner + USB log) | Result |
| --- | --- | --- | --- |
| **E48** | K18, `g54usb=1` (high speed), `g54noexec=bluetoothd,fairplayd.H2` | Chord held ~3 s: wedge as before (apps do not open, pages scroll). Log: `key 0x30 down`, `key 0xea down`, **both releases**, and later single presses (`0xea`, `0xe9`) all delivered. During the hold SpringBoard runs `exec InCallService`; it never crashes or exits | The key path is fine; SpringBoard starts InCallService and hangs on it |
| **E49** | E48 + `InCallService` in `g54noexec` (`d254a593…`) | **No wedge**: apps and the app switcher open. The power-off screen does not appear. Log: `exec InCallService refused (g54noexec)` once, no retry, not even on a second chord | **InCallService is the cause** |

## Interpretation

- Holding Side + a volume key is iOS's power-off / Emergency SOS gesture. In
  iOS 16 that screen is hosted by **InCallService** (the phone-call UI), which
  SpringBoard launches on the gesture.
- This phone has no telephony: `CommCenter` never runs (only
  `CommCenterMobileHelper`); `callservicesd` and `sosd` start at boot.
  InCallService never finishes presenting, and SpringBoard's app transitions
  queue behind it.
- E40's missing key releases were not reproduced with the sampler off
  (E41 onwards) and USB logging; they are not part of #14.
- The chord can come in as `0xea` (Volume Decrement) as well as `0xe9`
  (E40); both are the same gesture and both wedge. Single presses map
  correctly (key 1 = `0xe9` up, key 2 = `0xea` down).

## Decision

Refuse InCallService by default (`g54noexec=bluetoothd,fairplayd.H2,InCallService`).
Shut down remains available in Settings → General → Shut Down; restart via
AssistiveTouch (E39). Restoring the power-off screen needs to know what
InCallService waits for (thread samples, symbolized with the IPSW's shared
cache): open.
