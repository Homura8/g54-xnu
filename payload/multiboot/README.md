# G54 multiboot stub (offline; not yet run on the phone)

A position-independent AArch64 stub appended to the **stock Android arm64
Image** inside the gzip kernel stream of `boot_a`. Image `code0` becomes
`b stub_off`, so LK's jump (EL1, MMU off, x0 = DTB) lands in the stub, which
shows a key menu:

- **IOS 16.7.16**: runs `probe_main()` from [`../g1/probe.c`](../g1/probe.c)
  unchanged, built with the E37b fast-probe flags (UFS reset + HS-G3,
  Novatek firmware download, XNU loader). The touch firmware and SWEETXNU
  payload follow the stub's `_end` exactly as they follow the probe's.
- **ANDROID**: restores `code0` and enters the Image as LK would have
  (`linux_boot` in `entry.S`). Off unless packed with `--userdata android`:
  today `userdata` holds the iOS root.
- **FASTBOOT**: reboot-mode 3 + PSCI `SYSTEM_RESET` (E2).

Volume Up/Down move, Power starts; the default item boots after the
timeout unless a key was pressed. Keys and the MT6363 PSC acknowledgement
use the probe's SWINF 2 `spmi_rd`/`spmi_wr` (E28, E31). The stub checks
that LK copied the whole raw kernel (trailer + image ID) and that the DTB
and initrd do not overlap it, and shows why an entry is off.

Files: `entry.S` (entry, 64-byte header at `+0x08`, exception vectors,
`linux_boot`), `stub.c` (menu; `#include`s `../g1/probe.c`), `stub.ld`
(linked at 0, `_end` 4 KiB aligned). `probe.c` provides everything else, so
fixes to the proven code reach both images.

```sh
python3 scripts/g54_multiboot.py build --out out/mb
python3 scripts/g54_multiboot.py pack --stock out/fw/boot.img --stub out/mb \
    --payload out/x/<image>.payload --touch-fw out/touch/novatek_ts_fw.bin \
    --userdata ios --default fastboot --timeout 0 --out out/mb/mb-e0-boot.img
python3 scripts/g54_multiboot.py verify --stock out/fw/boot.img --stub out/mb \
    --payload out/x/<image>.payload --touch-fw out/touch/novatek_ts_fw.bin --image out/mb/mb-e0-boot.img
```

Read [docs/multiboot-feasibility.md](../../docs/multiboot-feasibility.md)
(layout, AVB, what is proven, hypotheses H1–H7, experiments MB-E0–E2) and
follow [docs/hardware-loop.md](../../docs/hardware-loop.md) before flashing.
