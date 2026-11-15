# G54 kernel patches

`NNNN-g54-<topic>.patch`, applied after ruby-ios-bringup's patchset (see
`docs/build.md`). Each patch modifies Apple XNU and is therefore under the
Apple Public Source License 2.0. Adding or changing a patch updates
`G54_PATCHSET_SHA256` in `config/kernel.env`. Name patches `02NN-g54-*` so they
sort after ruby's `0195`. The build driver skips patches that do not apply, so
`kernel.yml` checks each one with `git apply --reverse --check` after the build.

| Patch | Purpose | Evidence |
| --- | --- | --- |
| `0200-g54-early-framebuffer` | stage-0 band, early console, V=P block on the G54 LK scanout buffer `0xfeac6000`, pitch 4320 | `docs/experiments/2026-11-12-e3-e4-handoff-screen.md` |
| `0201-g54-panic-reset` | `g54panicreset=<s>`: after a panic, keep it on screen `<s>` seconds, then PSCI reset (the loader set reboot-mode 3, so the phone returns to Fastboot) | `docs/experiments/2026-11-12-e2-psci-reset.md` |
| `0202-g54-novatek-touch` | `g54nvt=1`: Novatek NT36672C polled SPI3 touch driver (`0x1101d000`), idle/bad_sum accounting | `docs/experiments/2026-11-13-e26-ios-touch.md`, `docs/experiments/2026-11-15-e61c-e64-k26-rtc-fairplay.md` |
| `0203-g54-keys` | `g54keys=1`: polled side keys (KPD `0x1c00e000` + MT6363 SPMI SWINF 2 `0x1c804880` with PMIC IRQ ack) and shared locked SPMI read/write helpers | `docs/experiments/2026-11-13-e28-ios-keys.md`, `docs/experiments/2026-11-13-e32-pmic-ack-ios.md` |
| `0204-g54-fb-no-debug-markers` | Drop `SweetFramebuffer` 64×64 swap debug squares and per-frame pixel console log | `docs/status.md` |
| `0205-g54-fb-alpha-blend` | `sweetfb_blend`: premultiplied BGRA source-over blending for framebuffer layers above the first | `docs/status.md` |
| `0206-g54-noexec` | `g54noexec=a,b`: early `EACCES` refusal in `exec_check_permissions()` without `SIGKILL`/`ReportCrash` spam | `docs/experiments/2026-11-14-e48-e49-chord-incallservice.md`, `docs/experiments/2026-11-15-e61c-e64-k26-rtc-fairplay.md` |
| `0207-g54-halt-restart` | PSCI `CPU_OFF` / `SYSTEM_OFF` / `SYSTEM_RESET` (clearing TOPRGU Fastboot reboot-mode nibble on user restart) | `docs/experiments/2026-11-14-e38-halt-timeout.md`, `docs/experiments/2026-11-14-e39-shutdown.md` |
| `0208-g54-halt-keep-root` | Skip HFS+ root unmount at halt (`g54halt_unmountroot=1` restores) | `docs/experiments/2026-11-13-e36-shutdown.md` |
| `0209-g54-halt-timeout-poweroff` | On IOKit halt/restart timeout (`halt_restart_timeout=<s>`), sync and call `haltRestart` instead of panicking | `docs/experiments/2026-11-14-e38-halt-timeout.md` |
| `0210-g54-usb-console` | `g54usb=1`: MediaTek MUSB (`0x11210000`) CDC-ACM USB serial console (4 MiB log ring, screenshots, HID input, sync+Fastboot control) | `docs/usb-console.md`, `docs/experiments/2026-11-14-e42-e47-usb-console.md` |
| `0211-g54-mt6685-rtc` | MT6685 PMIC RTC over SPMI slave 9 (`g54iortc=1` publishes `"IORTC"`, eliminating the 30 s `IOKitInitializeTime` stall) | `docs/experiments/2026-11-15-e61c-e64-k26-rtc-fairplay.md` |
| `0212-g54-fairplay-stub` | `g54fpstub=1`: diagnostic `com_apple_driver_FairPlayIOKit` stub and externalMethod selector logger | `docs/experiments/2026-11-15-e61c-e64-k26-rtc-fairplay.md` |
