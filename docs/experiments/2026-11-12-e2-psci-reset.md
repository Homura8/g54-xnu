# E2: automatic return to Fastboot via PSCI, plus diagnostic screen

| Field | Observation |
| --- | --- |
| UTC date | 2026-11-12, flash and reboot 16:04:09, Fastboot back 16:05:06 |
| Device class | Moto G54 XT2343-2 / `cancunf`, unlocked |
| Current OS/bootloader/slot | 5-8-6, slot A (as E1) |
| Repo commit + upstream pins | probe v2 (this PR) |
| Exact hypothesis / one changed input | H: E1 looped because a direct watchdog `SWRST` skips what the trusted firmware's reset does. Android's `reboot bootloader` ends in PSCI (Linux's PSCI restart handler outranks mtk-wdt). Change: PSCI `SYSTEM_RESET` first, `SWRST` only as a fallback. Same reboot-mode write |
| Image SHA-256 | probe `0a7db6d0…`, boot image `10df9329…` |
| Stock image + recovery | as E1; not restored afterwards (owner: no restore needed between tests) |
| Execution mode | `fastboot flash boot_a`, `fastboot reboot` |
| Expected positive observation | Fastboot returns on its own with `reason: preloader set fastboot mode`; magenta 4 s, a 4-band diagnostic screen for 25 s, green 3 s |
| Actual observation | Fastboot back **57 s** after `fastboot reboot`, no key press, `reason: preloader set fastboot mode` |
| Result | **PASS**: the payload returns the phone to Fastboot automatically. The flash → run → observe loop needs no human |
| Diagnostic bands (top → bottom) | Q1 entered at EL2 · Q2 LK left the watchdog enabled · Q3 reboot-mode write reads back 3 · Q4 register readable and changed. **Pending owner's reading** |
| What was ruled out | the reboot-mode write being ignored (Fastboot was entered via the preloader path) |
| Next smallest experiment | G2: topaz/ruby shim with stage bands, then XNU early framebuffer mark |
