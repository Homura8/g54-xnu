# USB console: log, screenshots and input over one cable

Kernel patch `0210-g54-usb-console` turns the G54's USB port into a serial
console while iOS runs. With it you (or an agent) can read the whole kernel
log, take screenshots, tap/swipe/press keys and reboot into Fastboot without
touching the phone. It replaced the old workflow of forcing a restart and
photographing the probe's previous-boot log page.

| Need | Command (repo root) |
| --- | --- |
| Is the phone up? | `python3 scripts/g54_usb.py wait` |
| What is happening now | `python3 scripts/g54_usb.py log --seconds 20 --grep "CRASH\|G54"` |
| The whole boot log | `python3 scripts/g54_usb.py log --all --seconds 15 --out out/usblog/boot.log` |
| What is on screen | `python3 scripts/g54_usb.py shot` (270×600 PNG) |
| Read small text | `python3 scripts/g54_usb.py shot --size half` (540×1200) |
| Documentation image | `python3 scripts/g54_usb.py shot --size full` (1080×2400) |
| Touch | `tap X Y`, `swipe X0 Y0 X1 Y1 --ms 300`, `home` (swipe up) |
| Keys | `key power\|volup\|voldown\|home --ms 100` |
| Back to Fastboot | `python3 scripts/g54_usb.py fastboot` |

Coordinates are panel pixels: 1080 × 2400, origin top left. On Windows use
`python` instead of `python3`. The host tool needs only the Python standard
library; no driver install on Windows 10/11, macOS or Linux.

## Requirements

- Kernel with patch 0210, **K21 or later** (K18: log only; K19/K20: commands
  work but `shot` panics, E50/E51). **K23 or later to replug the cable while
  iOS runs** (E53); with K21/K22 the cable must stay attached from Fastboot
  through the boot.
- Boot arguments: `g54usb=1` (high speed). Fallback: add `g54usbfs=1` for
  full speed. Both are in the best boot line in [status.md](status.md).
- A USB data cable to the host. The phone shows up as **USB ID
  `1209:0003`**, serial `G54XNU0001`: Windows "USB Serial Device (COMn)",
  macOS `/dev/cu.usbmodemG54XNU00011` (E53), Linux `/dev/ttyACM*`
  (`/dev/serial/by-id/*G54*`).
- The port appears about 60–70 s after `fastboot reboot`, when the kernel
  mounts its root (the driver starts in `bsd_init`).

## For agents: keep it cheap

- **Prefer text.** `log --grep REGEX --tail N` costs a few lines. A
  screenshot costs image tokens; use it to check the UI, not to read logs.
- **Default screenshot is `low` (270×600).** Roughly 200 image tokens, enough
  to see which screen is up and where to tap. Use `half` only to read small
  text, `full` only for images that go into docs.
- Every action prints one line (`done tap #43`, `out/usbshots/…-low.png 270x600 0.4s`).
- A hands-free test loop needs no buttons:

```sh
python3 scripts/g54_usb.py fastboot                  # phone syncs and reboots to Fastboot
fastboot flash boot_a out/x/new-boot.img && fastboot reboot   # r35 fastboot, see AGENTS.md
python3 scripts/g54_usb.py wait                      # ~70 s
python3 scripts/g54_usb.py home                      # unlock / home screen
python3 scripts/g54_usb.py shot                      # look
python3 scripts/g54_usb.py log --seconds 10 --grep "CRASH|panic"
```

Ask the owner before the first write of a session; the standing authorisation
in [AGENTS.md](../AGENTS.md) covers `boot_a` only.

## Protocol (for other tools)

- **CDC-ACM** (IAD + communication interface + data interface, bulk EP1
  IN/OUT, interrupt EP2 IN unused). Line coding is accepted and ignored.
- **Opening the port** (DTR 0→1): with **RTS set** the phone replays the whole
  4 MiB log ring, then follows it live (terminals such as `screen`, PuTTY and
  `scripts/g54_console.ps1` do this); with **RTS clear** it starts at the
  current end (live tail; `g54_usb.py` except `log --all`).
- **Commands**: one text line each on the OUT direction:

| Command | Effect | Reply line |
| --- | --- | --- |
| `ping` | | `G54 USB: ok pong #N` |
| `status` | | `G54 USB: ok status #N gesture g shot s sent bytes` |
| `tap X Y [ms]` | touch down/up (finger slot 9), default 60 ms | `G54 USB: done tap #N` |
| `swipe X0 Y0 X1 Y1 [ms]` | linear move, 8 ms steps, default 300 ms | `G54 USB: done swipe #N` |
| `key power\|volup\|voldown\|home [ms]` | HID consumer key, default 100 ms | `G54 USB: done key #N` |
| `shot [low\|half\|full]` | screenshot, 1/4, 1/2 or full size | frame (below), then `G54 USB: done shot WxH #N in T ms` |
| `fastboot` / `reboot` | sync, TOPRGU reboot-mode 3 / 0, PSCI SYSTEM_RESET | `G54 USB: fastboot: sync, then PSCI SYSTEM_RESET` |
| anything else | | `G54 USB: err commands: …` |

`N` increases by one per command line; `g54_usb.py` sends `ping` first and
then waits for `#N+1`, so replayed or older lines never match. One gesture
runs at a time (`err busy`).

- **Screenshot frame** inside the IN stream (the log pauses meanwhile):
  `\n@@G54SHOT w=W h=H fmt=rgb888 bytes=W*H*3 seq=N@@\n`, then exactly
  `bytes` of RGB rows (top to bottom, no padding), then
  `\n@@G54SHOT end seq=N@@\n`. Pixels are box averages of the BGRA scanout
  (`PE_current_console`), so small text stays readable when scaled down.
- Status lines `G54 USB: waiting …` (every 5 s for a minute, then every
  minute, until configured) and `G54 USB: hist …` (last 8 control requests)
  help when enumeration fails; the request log lines are
  `G54 USB: setup …` and `G54 USB: ep0 …`.

## Troubleshooting

| Symptom | Meaning / next step |
| --- | --- |
| No device at all on the host | Booted without `g54usb=1`, a kernel without 0210, or a charge-only cable. On the probe's log page (if enabled) look for `G54 USB: disabled` |
| Windows: "Unknown USB Device (Device Descriptor Request Failed)" | The bus works but EP0 failed (E42–E46 history). Read the `G54 USB:` lines; build the probe with `-D 'LASTLOG_GREP="G54 USB"'` (see status.md) and photograph the second page after a Power + Volume Down restart |
| Device gone after replugging the cable under iOS (Type-C attaches, no USB device) | Kernel older than K23: the driver kept its USB address after the bus reset (E53). Reboot with the cable attached, or use K23+ |
| macOS: `g54_usb.py` opened `/dev/cu.usbmodem<number>` | That was the MediaTek preloader's one-second port at power-on (also listed in Network settings as "MT65xx Preloader", harmless). Fixed: the script only accepts `cu.usbmodemG54*` |
| Port present but `g54_usb.py` cannot open it | Another program (terminal, PowerShell script) holds it |
| Commands time out, log works | Kernel older than K19 (no command channel) |
| Fastboot `flash` hangs at "Fetching super" | platform-tools r37; use r35.0.2 (AGENTS.md) |

## Porting to another MediaTek phone with MUSB

The driver is `bsd/dev/g54_usb.c` in patch 0210; all board values are
`#define`s at the top. What each one is and how it was found (E42–E47 run
card has the details):

1. **Controller**: in the stock DTB (vendor_boot), the node with
   `compatible = "mediatek,mtXXXX-usb20"` / `musb-hdrc`: `reg` gives the MUSB
   base (G54 `0x11210000`) and the PHY (`0x11e40000`). `scripts/fw_tools.py
   dtb` prints these nodes. If it says `mtu3`/`ssusb` instead, the phone has
   MTU3: use ruby's `ruby_usb.c` approach, not this driver.
2. **Clocks**: the node's `clocks` point at a `pericfg_ao`-style provider.
   Decode the gate table in the stock `clk-mtXXXX-peri.ko` (vendor_boot
   ramdisk) with `scripts/fw_tools.py ko-table <ko> <symbol>`: each gate gives
   status/clr/set offsets and a bit; writing the bit to **clr** enables it.
3. **PHY**: T-PHY v2 U2 bank at PHY + `0x300`; board eye values come from the
   PHY node (`mediatek,eye-vrt`, `eye-term`, `discth`, `rx_sqth`); device mode
   is `U2PHYDTM1 |= 0x202` (from `phy-mtk-tphy.ko`
   `u2_phy_instance_set_mode`).
4. **PHY supply**: check that `VUSB` is `regulator-always-on`.
5. **Interrupt status registers are write-1-to-clear** on MediaTek
   (`mt_usb_interrupt` in `musb_hdrc.ko`): keep the write-backs.
6. **SET_ADDRESS**: switch FADDR only after CSR0 DataEnd clears, and within
   2 ms. The polled design depends on it.
7. **Screen**: anything `PE_current_console()` reports works; touch and key
   injection call the SWEET HID entry points (`sweet_hid_touch`,
   `sweet_hid_key`).
8. **Reboot**: the TOPRGU reboot-mode register (`0x1c007000 + 0x24` on
   MT6855) and the value LK maps to Fastboot (3 here) are SoC-specific.

Use `g54usbfs=1`, `g54usbsrc=0..7` (HS slew rate) and `g54usbfifo=1|2`
(FIFO write width) to bisect hardware problems without rebuilding.
