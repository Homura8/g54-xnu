# E3/E4: what LK hands over (on-screen text probe)

| Field | Observation |
| --- | --- |
| UTC date | 2026-11-12. E3 flashed 16:13:28, back in Fastboot 16:15:01; E4 flashed 16:18:58, back 16:20:31 |
| Device / firmware / slot | G54 XT2343-2, 5-8-6, slot A |
| Images | E3 probe v3 `c58c8fd8…` (boot `5e14fa81…`); E4 probe v4 `47a0ac08…` (boot `57c578ed…`) |
| Hypothesis | E3: drawing at `atag,videolfb-fb_base` with pitch 4320 shows text. E4: LK scans out a different buffer; read it from the display engine's layer registers |
| Result E3 | magenta, then **black with no text**, then green, then Fastboot (87 s). The text went into a buffer that isn't scanned out |
| Result E4 | **PASS**: text screen photographed by the owner; Fastboot after 87 s. No exception fired, so OVL/RDMA reads from EL1 are fine |

## Values read on the phone (E4 photo)

| Item | Value |
| --- | --- |
| Visible scanout | **OVL0 layer 1 (`0x14002000`): address `0xFEAC6000`, pitch `0x10E0` (4320), size `0x0960×0x0438` (2400×1080)**. The green test line drawn with pitch 4320 is straight; the magenta one at 4352 slants |
| Other layer | OVL1 layer 0 (`0x14004000`): `0xFE0D0000` (= `atag,videolfb-fb_base`), pitch `0x1100` (4352), hidden under OVL0 L1 |
| RDMA0 | `GLOBAL_CON=0x101` (direct-link, not memory mode), 1080×2400 |
| `atag,videolfb` | base `0xFE0D0000`, vramSize `0x1DF0000`. Visible buffer = base + `0x9F6000` (= 4352×2400) |
| CPU | EL1; MIDR `0x412FD050` (Cortex-A55 r2p0); MPIDR `0x81000000` (MT bit set); ID_AA64MMFR0 `0x00101122` (16K granule supported, PARange 40 bits); CNTFRQ `0xC65D40` (13 MHz) |
| LK handoff | kernel Image at `0x40000000` (probe at `0x40001000`); DTB at `0x47C80000`, `0x4CB6A` bytes |
| Watchdog | `WDT_MODE=0x7D`, `NONRST2=0x40002000` (before our write) |
| `/memory` | `0x40000000 + 0x200000000` (8 GiB) |
| Largest free (memory minus all reserved regs) | `0x140000000+0xFFE00000`, `0xFFFFF000+0x40000000`, `0x50F00000+0x1F100000`, `0x9FFFF000+0x1E001000`, `0xDB470000+0x10410000`, `0xC0000000+0x10000000` |
| Reserved | 0x28 regions in 0x2A nodes, including `0xFE0D0000+0x1F2F000`, `0x13FFFF000+0x1000`, `0x23FE00000+0x100000`, `0x23FFFF000+0x1000` (full list in the private photo) |

## Consequences

- XNU's early console and stage-0 band must target `0xFEAC6000`, pitch
  4320. Ruby's kernel hard-codes `0x7cdfc000`/4352 (its MT6877 visible
  layer). That address is unrelated memory on the G54, so the K0 kernel
  must not run unpatched.
- Ruby's XNU window `phys_base 0x140000000`, 2 GiB, lies inside the
  G54's largest free range. Reuse it.
- Every probe now has exception vectors that paint red and return to Fastboot.
