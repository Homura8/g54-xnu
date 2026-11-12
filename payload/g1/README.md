# G1 probe: first G54 code execution under Motorola LK

A 3 KB freestanding AArch64 probe placed in the stock 5-8-6 `boot.img`
kernel stream (ruby-ios-bringup's "small payload" recipe, adapted to boot
header v4). Its only job is to prove that LK ran our code. It also reports
that fact over USB, so nobody has to watch the screen:

1. LK jumps to the raw kernel with the MMU off and x0 = DTB. `raw[0]`
   branches to the probe at `raw+0x1000`.
2. The probe reads the LK framebuffer from that DTB (`/chosen
   atag,videolfb-fb_base_h/_l`, `atag,videolfb-vramSize`; fallback: a
   `*framebuffer*` reserved-memory node). It paints **magenta**, and
   **green** after 10 s.
3. 5 s later it writes reboot-mode `3` (bootloader) to the MT6855 watchdog
   (`0x1c007000 + 0x24`, mask `0xf`) and issues a watchdog software reset.
   This is the same register sequence Android's `reboot bootloader` uses
   on this phone. PSCI `SYSTEM_RESET` is the fallback.

Expected host signal: Fastboot disappears at `fastboot reboot`, then comes
back roughly 15 s plus two LK boots later, with `getvar reason` =
`preloader set fastboot mode`. An LK rejection falls back to Fastboot within
seconds and reports a different reason.

```sh
python3 scripts/g54_payload.py build                        # out/g1/probe.bin
python3 scripts/g54_payload.py pack --stock <5-8-6 boot.img> \
    --payload out/g1/probe.bin --out out/g1/probe-boot.img   # verifies itself
```

Emulation (QEMU `virt`, cortex-a55, `-kernel` = the gunzipped kernel from
the packed image, a DTB with the `/chosen` atag properties added) checked
entry at EL2, the framebuffer fill in all three DTB cases, the phase timing
(reset at 16.1 s) and the PSCI fallback. It cannot check the watchdog itself
or Motorola LK's acceptance; that is experiment E1.
