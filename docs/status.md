# Status and handoff

## Milestones

| Milestone | Needs the phone | State |
| --- | --- | --- |
| **M2** toolchain: reproducible kernel pipeline (line K0) | no | pipeline written; first CI result pending — see below |
| **M1** device facts and safety baseline | read-only first | not started; template in [device-facts.md](device-facts.md) |
| **M3** first observable execution: LK runs our code (panel colour), then XNU's early framebuffer mark | yes, with explicit approval | not started; depends on M1 + M2 |

Success criteria for M3, borrowed from ruby's proven ladder: (1) LK accepts
the image and a tiny payload paints the panel; (2) the kernel's stage-0 band
appears; (3) kernel log on screen. Each step is RAM-booted if the G54 permits
`fastboot boot`, photographed, and tied to the image hash.

## Why this route (decided 2026-11-12)

The fastest path to both first execution and a usable iOS is the direct
LK → XNU route proven on the MediaTek MT6877 by ruby-ios-bringup (iOS 16.7.16,
same kernel lineage as ios-qemu, the owner already has the IPSW). UniXNU's
iPadOS 17 route would first need a G54 UEFI port; no MediaTek UniXNU port has
reached a home screen. UniXNU stays the fallback if the G54's LK refuses
direct kernels.

## Next concrete steps

1. Get the K0 CI run green (exec-data `6b22fc25…` with an empty `KDKROOT`).
2. M1 read-only facts (owner, with the phone): fill device-facts.md.
3. Boot-image format work once the header version and DTB location are known.
