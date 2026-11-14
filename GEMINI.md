# Instructions for Gemini / Antigravity agents

This repository's agent instructions live in [AGENTS.md](AGENTS.md). Read it
first, then [docs/status.md](docs/status.md) (the handoff) and
[docs/usb-console.md](docs/usb-console.md) (how to drive the phone). The
rules there apply to every agent, including the safety rules for flashing,
the standing owner authorization (it covers `boot_a` only) and "pull
requests only; the owner merges".

Quick orientation:

- The phone (Moto G54, `cancunf`) runs iOS 16.7.16 on our XNU kernel. With
  `g54usb=1` it is a USB serial port: `python3 scripts/g54_usb.py wait`, then
  `log --seconds 10 --grep …`, `shot` (low-res by default; keep screenshots
  small to save tokens), `tap`, `swipe`, `home`, `key`, `fastboot`.
- Flash only with platform-tools **r35.0.2** fastboot (`fastboot --version`;
  r37 hangs on this phone) and only after the read-only checks in
  docs/hardware-loop.md (§3a, §3c).
- Kernel changes: `patches/02NN-g54-*.patch`, built by GitHub Actions
  (`kernel.yml`); check them locally with `scripts/xnu_tree.sh` (docs/build.md).
- Never commit Apple or Motorola material; everything derived goes in `out/`.
- Record each hardware run in `docs/experiments/` and update docs/status.md
  in the same pull request.
