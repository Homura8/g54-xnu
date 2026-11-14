# E53: USB console on macOS, and replugging under iOS (patch 0210)

**Result: PASS (E53c, kernel K23).** First run of the USB console on a Mac (Apple
silicon MacBook Pro, USB-C port, the same Apple USB 2 C-to-C cable that works
on the owner's Zephyrus G14). The console works on macOS when the cable is
attached through the boot. **Replugging while iOS runs never enumerated** (a
host-independent driver bug; observed on macOS): after the USB bus reset the driver kept the old USB address
(`FADDR 01`), so the host's requests to address 0 went unanswered. K23 clears the
address on every bus reset; a replug under iOS now reconnects in seconds.

| Run | Kernel (CI run) | Observation | Finding |
| --- | --- | --- | --- |
| **E53-0** | K21 (43610154079), image E52 | Phone in iOS, cable plugged in under iOS: no USB device on the Mac, all USB-C ports `ConnectionActive = No`. Power + Volume Down → Fastboot: port USB-C@2 `ConnectionActive = Yes`, CC + USB2, `fastboot devices` lists the phone. `fastboot reboot` with the cable attached: `G54 XNU console` 1209:0003 after 39 s, `/dev/cu.usbmodemG54XNU00011`, `log` and `shot` work | Cable, Mac port and macOS CDC driver are fine. The ConnectionActive = No reading was not reproduced later (see below); its cause is open |
| **E53-1** | K21 | Unplug + replug under iOS: Type-C attaches again (CC + USB2 active within 4 s), but no USB device appears | Not the Type-C/CC side; the USB device side does not come back |
| **E53a** | K22 (43614511551): 0210 + restart the MUSB session when it ends (DISCON, SESSION clear, VBUS falling) | Boot with cable: console after 34 s, `connected power 70 devctl 99 … dtm1 00003f2f`, configured high speed, no false session loss. Unplug + replug: console gone at 03:20:58, does not return; Type-C attached | Fix did not help. `dtm1 3f2f`: LK leaves the PHY forcing VBUSVALID/AVALID/BVALID/SESSEND, so the session never ends |
| **E53b** | K22 + probe previous-boot page (`LASTLOG_GREP="G54 USB"`), after Power + Volume Down | Page photographed by the owner (extract below) | Host resets the device repeatedly after the replug; `FADDR` stays `01`; no new SETUPs |
| **E53c** | K23 (43615780625, patchset `dae8465d…`): 0210 + `FADDR = 0` on every bus reset; image `e53c-faddr-k23-boot.img` `bd9abeb6…`, probe `out/g1-fast-nolog`, best boot line | Hands-free loop on the Mac (`g54_usb.py fastboot` → r35 flash → reboot): console after 56 s. Unplug 03:37:48, replug ~5 s later: console back 03:37:58. Log: `waiting … faddr 00 … resets 2`, then `configured (high speed)`, `port open (replay)`; `shot` shows the lock screen | **PASS** |

## E53b extract (previous boot, `G54 USB` lines, transcribed from the photo)

```
G54 USB: configured (high speed)
G54 USB: port open (replay), log from 0 of 50132
G54 USB: waiting power 70 devctl 99 csr0 0000 faddr 01 frame 0 dtm1 00003f2f resets 2 setups 32 stalls 0 cfg 0 dtr 0 sent 91905
G54 USB: bus reset #3 (high speed) … bus reset #16 (high speed)
G54 USB: waiting power 7? devctl 98 csr0 0000 faddr 01 frame 1463 dtm1 00003f2f resets 3? setups 3? stalls 0 cfg 0 dtr 0 sent 91905
```

- Unplugging produced `bus reset #2` (SE0 on the lines) and `cfg 0`, no
  `session lost` line (session forced valid).
- After the replug the Mac saw the device (D+ pull-up present) and reset it
  over and over; the address stayed 1. A reset device must answer at address
  0. MUSB does not clear `FADDR` on reset; Linux's `musb_g_reset` writes 0.
  0210 cleared it only at probe time, so the first enumeration after boot
  always worked and every later one failed. The G14 runs never replugged the
  cable under iOS.

## Changes

- Kernel 0210: `FADDR = 0` in the bus reset handler (the fix). The session
  restart from E53a stays as a defensive path for an unforced PHY; it has not
  fired on the G54.
- `scripts/g54_usb.py`: no fallback to any `/dev/cu.usbmodem*`. During E53-0
  it picked `/dev/cu.usbmodem1101`, the MediaTek preloader's one-second CDC
  port at power-on (macOS also lists it as the network service "MT65xx
  Preloader"). Only `cu.usbmodemG54*`, `/dev/serial/by-id/*G54*`, or
  `ttyACM*` with sysfs 1209:0003 match now.

## macOS notes

- Port name: `/dev/cu.usbmodemG54XNU00011` (USB serial + interface number).
- Android File Transfer Agent and other apps open a user client on every new
  USB device; no effect on the console was seen.
- Homebrew's `fastboot` is r37 (read-only `getvar` only); flash with r35.0.2
  in `out/tools/platform-tools/` (AGENTS.md).
