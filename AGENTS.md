# Working on g54-xnu

- Read `docs/status.md` first; it is the handoff. Update it in the same PR as
  any change in what works.
- This repository is the G54 port only. Hardware-agnostic tooling belongs in
  Celestia Nexus; proven upstream code stays upstream and is fetched at pins.
- Never commit Apple material (IPSWs, KDKs, root images, kernelcaches), phone
  dumps, stock firmware images, keys or credentials. `scripts/check_repo.py`
  rejects common forms of them.
- Never unlock, flash, erase or write to the phone. Read-only commands
  (`getprop`, `fastboot getvar`) are fine when the owner runs them or approves.
- Facts in `docs/device-facts.md` need an observed source. Hypotheses go in
  their own section.
- Before pushing: `python3 scripts/check_repo.py` and
  `python3 -m unittest discover -s scripts -p 'test_*.py'`. Kernel changes are
  verified by `kernel.yml`'s hash gates, not by a successful compile alone.
- Pull requests only; the owner merges.
