# g54-xnu

An independent port of Apple's open-source XNU kernel, and eventually the
iOS 16.7.16 userland, to the **Motorola Moto G54 5G** (MediaTek, reported
MT6855 / Dimensity 7020). Research bring-up: nothing here is a usable or secure
iOS device, and nothing here has run on a G54 yet.

## Approach

The G54 port builds on the closest proven implementation instead of starting
from scratch:

| Upstream | What we reuse |
| --- | --- |
| [lky005/ruby-ios-bringup](https://github.com/lky005/ruby-ios-bringup) | XNU 8796 + iPhone X iOS 16.7.16 on a MediaTek MT6877 phone, booted directly by the stock LK bootloader: UFS root, LK framebuffer display, touch, keys, SpringBoard. Kernel patch recipe, CI hash gates, boot-image tools |
| [lgrachov/ios-qemu](https://github.com/lgrachov/ios-qemu) / sweet lineage | The underlying XNU patch series (sweet 0001–0079), device-tree and payload tools, the iOS root-disk builder |
| [blacktop/darwin-xnu-build](https://github.com/blacktop/darwin-xnu-build) | The XNU build driver |
| [UniXNU](https://github.com/UniXNU/UniXNU) | Fallback route (UEFI + iPadOS 17) if direct LK boot proves impossible on the G54 |
| [Celestia Nexus](https://github.com/Homura8/celestia-nexus) | Hardware-agnostic experiment records, pinned inputs and evidence conventions |

Nothing from these projects is vendored: sources are fetched at pinned commits
during builds. No Apple firmware, IPSW, KDK, root image or device dump is ever
committed.

## Status

See [docs/status.md](docs/status.md). In short: line **K0**, which builds
ruby's kernel unchanged in CI to prove the pipeline, is in place. Device facts (M1) have been collected from the actual G54; firmware/recovery
analysis and the first observable execution (M3) remain pending.

## Connected-device bring-up (G54 owner / local coding agent)

**Current focus:** the real device has an unlocked bootloader and captured
ADB/Fastboot M1 facts. The fastest route to **iOS 16.7.16 SpringBoard** is the
iterative [hardware experiment loop](docs/hardware-loop.md), not another
framework milestone. Read its firmware/OTA and recovery prerequisites
**before issuing any boot or write operation**.

The Mac may have direct ADB/Fastboot access to the phone. Agents should
check for it, use host-side verification, and iteratively test only within
the owner's current approved risk scope. Bootloader acceptance, XNU entry,
PID 1 and SpringBoard are separate evidence gates; none has yet been
observed on this G54.

The baseline [K0 build](docs/build.md) is already reproducible; see
[observed M1 facts](docs/device-facts.md) and the
[run card template](docs/experiments/TEMPLATE.md). This project keeps
G54-specific boot work separate from Celestia Nexus.

## Build the kernel

`.github/workflows/kernel.yml` runs on GitHub's `macos-15` runner with
Xcode 16.0. It verifies every pin in [`config/kernel.env`](config/kernel.env):
ruby's patchset hash, the G54 patchset hash and the built kernel's
executable-data hash. Details are in [docs/build.md](docs/build.md).

```sh
python3 scripts/check_repo.py                          # no device, no network
python3 -m unittest discover -s scripts -p 'test_*.py'
gh workflow run kernel.yml -R Homura8/g54-xnu          # or push to patches/ or config/
```

## Safety

No command in this repository unlocks, flashes or writes to a phone. Physical
device steps are documented separately, need the owner's explicit approval,
prefer RAM-only `fastboot boot`, and start with a verified backup and recovery
path ([docs/device-facts.md](docs/device-facts.md)).

## Licence

Original code and documentation: MIT ([LICENSE](LICENSE)). XNU patches in
`patches/` modify Apple's XNU and are under the APSL 2.0. Upstream projects
retain their own terms ([NOTICE](NOTICE)). Apple, iOS and iPhone are
trademarks of Apple Inc.; Motorola and Moto are trademarks of their owners. This
project is not affiliated with Apple, Motorola, MediaTek or the upstream projects.
