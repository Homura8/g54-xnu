# Working on g54-xnu

**Resuming ("pick up the iOS port, the G54 is on USB"):**

1. Read [`docs/status.md`](docs/status.md) (the handoff: state, phone image,
   best boot line, next step, open issues), then
   [`docs/hardware-loop.md`](docs/hardware-loop.md) §3a–3c.
2. Find the phone. If iOS is running with the USB console:
   `python3 scripts/g54_usb.py wait`, then `log --seconds 10` and `shot`.
   Otherwise `fastboot devices` (use platform-tools **r35**, see Host setup).
3. If `out/` is empty (new machine), rebuild the inputs: hardware-loop §3b.
4. Continue with the next step in status.md, one experiment at a time; record
   each run in `docs/experiments/` and update status.md in the same PR.

**Working with the phone (USB console, [`docs/usb-console.md`](docs/usb-console.md)):**
with boot-arg `g54usb=1` (kernel patch 0210) the phone is a USB serial port
while iOS runs. `scripts/g54_usb.py` reads the log, takes screenshots, taps,
swipes, presses keys and reboots into Fastboot, so a test loop needs no
hands: `g54_usb.py fastboot` → `fastboot flash boot_a …` → `fastboot reboot`
→ `g54_usb.py wait` → `home` / `tap` / `shot` / `log --grep`. Keep tokens
low: read logs with `--grep`/`--tail`, use the default `low` screenshot
(270×600) to see the UI, `half` only to read small text, `full` only for docs.

## Rules

- Read `docs/status.md` first; it is the handoff. Update status in the same
  PR as any change in what works.
- This is a **connected-device bring-up project**, not just an offline research
  assignment. Check whether the owner's Moto G54 is attached (USB console,
  ADB/Fastboot). If available, use real experiments to test hypotheses within
  the explicit session scope; if absent, do useful offline work and leave
  precise next hardware steps. **Do not invent hardware evidence.**
- Prioritise working iOS 16.7.16 on the G54 (SpringBoard is up; see the open
  issues in status.md). Reuse the proven pinned K0 build.
- This repository is the G54 port. Hardware-agnostic tooling belongs in
  Celestia Nexus; proven upstream code stays upstream and is fetched at pins.
- Never commit Apple material (IPSWs, KDKs, root images, kernelcaches), phone
  dumps, stock firmware images, keys or credentials. `scripts/check_repo.py`
  rejects common forms of them. Everything derived goes in Git-ignored `out/`.
- Hardware is risky and ownership/consent matters. Read-only queries are fine
  for the owner's authorised connected device; for writes/temporary boots
  follow `docs/hardware-loop.md`: confirm current approval scope, live
  identity, firmware/slot, verified stock restore images and recovery route,
  then run one bounded, observable, reversible experiment. The owner has
  indicated willingness to reset and experiment on this spare G54, **not**
  permission to bypass recovery checks.
- **Standing owner authorization (given 2026-11-12 UTC, in chat):** the G54
  is a dedicated test phone with no data the owner needs. Agents may reboot
  it and flash it **as long as the change can be reverted**. In practice
  that means writing `boot_a` (and other boot images that have a verified
  stock copy) and rebooting between Android, Fastboot and test images.
  Restoring stock `boot.img` between tests is **not** required; restore at
  the end of a session or when Android is needed. This authorization does
  not cover the critical partitions below. The Claude Code auto-mode
  classifier may still block `fastboot flash`. If it does, ask the owner and
  quote this line; never work around it.
- No unattended writes to preloader, LK, bootloader/TEE, GPT, calibration,
  NVRAM/NVDATA/persist/efuse, rollback/security configuration or relock.
  These require fresh, specific owner approval and a separate recovery plan.
  Do not treat an OTA-in-progress or a newer downloaded package as a safe
  stock backup. No unbounded flash loops. Gate every flash on
  `product=cancunf`, `current-slot=a`, `snapshot-update-status=none`.
- Facts in `docs/device-facts.md` need an observed source. Hypotheses go in
  their own section.
- Before pushing: `python3 scripts/check_repo.py` and
  `python3 -m unittest discover -s scripts -p 'test_*.py'`. Kernel changes are
  verified by `kernel.yml`'s hash gates, not by a successful compile alone.
- Pull requests only; the owner merges. Any push to a PR branch cancels its
  running kernel build: batch docs pushes.

## Host setup (macOS or Windows; no WSL needed)

| Tool | macOS | Windows |
| --- | --- | --- |
| Fastboot | `brew install --cask android-platform-tools` | Google platform-tools **r35.0.2** (`dl.google.com/android/repository/platform-tools_r35.0.2-win.zip`); r37's `fastboot flash` hangs at "Fetching super" on this phone (LK has no `fetch`) |
| LLVM (probe payload) | `brew install llvm lld` | `winget install LLVM.LLVM`, then add `C:\Program Files\LLVM\bin` to PATH |
| GitHub CLI (kernel artifacts) | `brew install gh` | `winget install GitHub.cli` |
| Python 3 | system / brew | python.org; standard library only for all scripts |
| USB console | built-in CDC driver | built-in `usbser` (Windows 10/11) |

On Windows, use Git Bash for the shell snippets. Git's default
`core.autocrlf=true` checks files out with CRLF: patch files are hashed after
LF normalisation (fine), but any local XNU tree used to make patches must be
cloned with `-c core.autocrlf=false` and patches applied from LF copies.

## Writing kernel patches

`patches/02NN-g54-*.patch` apply after ruby's series, in glob order, inside
darwin-xnu-build's `build.sh` (`git apply`; a patch that does not apply is
**silently skipped**). Then `kernel.yml`'s "G54 patches applied" step
reverse-checks every G54 patch against the final tree. So:

1. Build a local tree exactly like CI and make the change there (see
   [`docs/build.md`](docs/build.md) "Local patched tree"):
   `sh scripts/xnu_tree.sh setup` → edit `out/xnu` → `sh scripts/xnu_tree.sh
   diff patches/02NN-….patch "header text"`.
2. `sh scripts/xnu_tree.sh gate` applies the new patch to a clean copy and
   reverse-checks all G54 patches, as CI does.
3. `sh scripts/xnu_tree.sh hash` prints the new `G54_PATCHSET_SHA256` for
   `config/kernel.env`.
4. A new patch must not edit lines within 3 lines of another G54 patch's
   hunk (it breaks that patch's reverse check), and must not modify a file
   another G54 patch creates (fold the change into that patch instead).
5. Multi-instruction inline asm separates instructions with `"\n\t"`, never
   `;` (a comment in Apple's assembler; E38).
6. If a kernel change moves `sweet_log_ring` (`llvm-nm`), probe builds that
   show the previous-boot log need the new `LASTLOG_RING`/`LASTLOG_TOTAL`.
7. `ml_io_map` mappings come from the 8 MB `io_submap` and are permanent
   (`KMA_PERMANENT`; `ml_io_unmap` on them panics). For large or temporary
   mappings use `ml_io_map_unmappable(pa, size, 0x7 /* VM_WIMG_IO */)`
   (E50/E51).
8. MediaTek MUSB interrupt status registers are write-1-to-clear (E46/E47).
