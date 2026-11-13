# E32: no more press-linked power-off in iOS (kernel K5, 0203 PMIC acknowledgement)

| Field | Observation |
| --- | --- |
| UTC date | 2026-11-13, flashed and rebooted 10:35:39 |
| Image | `out/g4/e32-pmicack-ios-boot.img`, SHA-256 `c125e353e63e30032844a903a81a91ee6164fc19f4db5ed6d7ccc34a321558f6` |
| Kernel | K5 = CI run 43409471875 (PR #8, `382f960`, all gates passed), `kernel.development.sweet` SHA-256 `029a222b8ecd75a69213fe916537c39c7c94ca9befead8abee434e6596f82c26`; `sweet_log_ring`/`sweet_log_total` at the same VAs as K4, so the E29 LASTLOG probe applies unchanged |
| Probe / cmdline | `out/g1-lastlog` (E29); cmdline E28's (`… sweetfb_noconsole=1 g54nvt=1 g54keys=1`) |
| Observation (owner) | In iOS the owner pressed the side keys (power sleep/wake, volume), then **unplugged USB and left the phone for several minutes: it stayed on** (before: cold reset ~79 s after a power press on USB, power-off on battery) |
| Result | **PASS: the press-linked cold reset/power-off (issue #7) is fixed.** The key driver acknowledges MT6363 interrupts like the stock PMIC IRQ handler |
