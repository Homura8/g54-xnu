# Working on g54-xnu

- Read `docs/status.md` first; it is the handoff. For physical-device work,
  immediately read [`docs/hardware-loop.md`](docs/hardware-loop.md).
  Update status in the same PR as any change in what works.
- This is a **connected-device bring-up project**, not just an offline research
  assignment. On the owner's Mac, check whether ADB/Fastboot has an authorised
  Moto G54 attached. If available, use real experiments to test hypotheses
  within the explicit session scope; if absent, do useful offline work and
  leave precise next hardware steps. **Do not invent hardware evidence.**
- Prioritise the actual iOS 16.7.16 SpringBoard/home-screen milestone.
  LK payload, XNU marker, storage and userspace probes are gates toward it,
  not an excuse for more infrastructure. Reuse the proven pinned K0 build.
- This repository is the G54 port only. Hardware-agnostic tooling belongs in
  Celestia Nexus; proven upstream code stays upstream and is fetched at pins.
- Never commit Apple material (IPSWs, KDKs, root images, kernelcaches), phone
  dumps, stock firmware images, keys or credentials. `scripts/check_repo.py`
  rejects common forms of them.
- Hardware is risky and ownership/consent matters. Read-only queries are fine
  for the owner's authorised connected device; for writes/temporary boots
  follow `docs/hardware-loop.md`: confirm current approval scope, live
  identity, firmware/slot, verified stock restore images and recovery route,
  then run one bounded, observable, reversible experiment. The owner has
  indicated willingness to reset and experiment on this spare G54, **not**
  permission to bypass recovery checks.
- No unattended writes to preloader, LK, bootloader/TEE, GPT, calibration,
  NVRAM/NVDATA/persist/efuse, rollback/security configuration or relock.
  These require fresh, specific owner approval and a separate recovery plan.
  Do not treat an OTA-in-progress or a newer downloaded package as a safe
  stock backup. No unbounded flash loops.
- Facts in `docs/device-facts.md` need an observed source. Hypotheses go in
  their own section.
- Before pushing: `python3 scripts/check_repo.py` and
  `python3 -m unittest discover -s scripts -p 'test_*.py'`. Kernel changes are
  verified by `kernel.yml`'s hash gates, not by a successful compile alone.
- Pull requests only; the owner merges.
