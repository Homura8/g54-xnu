# E5: first XNU boot on the Moto G54 (G2)

| Field | Observation |
| --- | --- |
| UTC date | 2026-11-12, flashed and rebooted 16:35:11 |
| Device / firmware / slot | G54 XT2343-2, 5-8-6, slot A |
| Kernel | `0200-g54-early-framebuffer` on ruby `1aaa8837` / topaz `5095ac19`; CI run [43258645696](https://github.com/Homura8/g54-xnu/actions/runs/43258645696) ("G54 patches applied" gate passed); `kernel.development.sweet` SHA-256 `98d4caad…`, exec-data `d05a83e7…` |
| ADT / payload | `scripts/g54_xnu_image.py` (G54 values on topaz `mkadt.py`); ADT `b236d38f…` (8,232 bytes); SWEETXNU payload 16,797,360 bytes at raw+`0xf000`; entry `0xfffffe0007494488`; phys `0x140000000` + 2 GiB |
| Boot image | `2aa4ebde…` (stock 5-8-6 layout, probe v4 + loader) |
| cmdline | `debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress wdt=-1` (no MediaTek driver boot-args; no UFS node) |
| Hypothesis | the probe's loader can boot ruby's XNU on MT6855 with only the framebuffer moved |
| Emulation first | QEMU virt (8 GiB, EL1): SWEET EARLY 1–20, then a panic on the absent GIC redistributor |
| Actual observation (owner photos) | info screen, then `SWEETXNU PAYLOAD AT 04000F000`, then the XNU console on the panel. Lines: `Boot version: topaz-shim`, `SWEET AMFI: built-in interface registered`, `SWEET: starting device-tree platform expert`, **`RUBY GIC: ready gicd=1 … vectors=1024`**, AppleKeyStore/IOWatchdog/IOCoreSurfaceRoot/HID buttons and touch registered, `SWEET BATTERY: static fallback`, **`SWEET FB: AppleCLCD 1080x2400 stride 4320 at 0xfeac6000, default surface 1, presented as 1125x2436`**, `SWEET CPU: requested=1 selected=1 (limit=8)`, **`SWEET CPU: cpu=0 mpidr=0x0 came alive; SGI1 OK`**, BSD copyright, `MAC Framework successfully initialized`, **`SWEET CPU: 1/1 CPUs initialized, SGI1 verified`** (newest line; the console wraps to the top). Older wrapped lines: kmem ranges, `zone_init`, `VM bootstrap done`, OSLog/firehose configured, scheduler quanta, `core zlib memory 0x8000` |
| Result | **G2 PASS** (XNU runs and draws on the panel). **Partial G3**: memory and VM, the GIC and SGIs on the boot CPU, IOKit platform expert and drivers. Not yet: secondary CPUs (cpus=1), storage, root |
| Return to Fastboot | manual (Power + Volume Down): the loader stops LK's watchdog before XNU |
| What was ruled out | GIC/timer incompatibility on the boot CPU; MMU/16K-granule issues; the ADT/boot_args layout |
| Next smallest experiment | read-only UFS probe from XNU (`/sweet-ufs` at `0x112b0000`, no root, no writes), then root on UFS |
