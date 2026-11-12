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
