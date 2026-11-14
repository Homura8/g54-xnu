# g54-xnu

An independent port of Apple's open-source XNU kernel and the unmodified
iOS 16.7.16 userland (iPhone X) to the **Motorola Moto G54 5G** (MediaTek
MT6855 / Dimensity 7020). Research bring-up: nothing here is a usable or
secure iOS device.

**What works on the G54 today** (details: [docs/status.md](docs/status.md)):
the stock LK bootloader starts our payload, XNU boots on all eight CPUs,
mounts an iOS 16.7.16 root from UFS and reaches **SpringBoard** with real
touch and side keys; Settings → Shut Down and restart work; a **USB
console** gives the kernel log, screenshots and touch/key input over one
cable. Still missing: GPU (software rendering, ~8 fps), audio, RTC, battery,
backlight, telephony.

## Start here

| You are | Read |
| --- | --- |
| Resuming work on the G54 (owner or agent) | [AGENTS.md](AGENTS.md) → [docs/status.md](docs/status.md) → [docs/hardware-loop.md](docs/hardware-loop.md) |
| Driving the phone from a computer | [docs/usb-console.md](docs/usb-console.md) (`scripts/g54_usb.py`: log, `shot`, `tap`, `swipe`, `key`, `fastboot`) |
| Writing a kernel patch | [docs/build.md](docs/build.md) (`scripts/xnu_tree.sh`: local tree, CI's gate, patchset hash) |
| Porting to a similar MediaTek phone | the run cards in [docs/experiments/](docs/experiments/), [docs/device-facts.md](docs/device-facts.md), the porting checklist in [docs/usb-console.md](docs/usb-console.md), and `scripts/fw_tools.py` |

Host: macOS or Windows (no WSL needed) with Python 3, LLVM, platform-tools
and the GitHub CLI; setup table in [AGENTS.md](AGENTS.md).

## Approach

The G54 port builds on the closest proven implementation instead of starting
from scratch:

| Upstream | What we reuse |
| --- | --- |
| [lky005/ruby-ios-bringup](https://github.com/lky005/ruby-ios-bringup) | XNU 8796 + iPhone X iOS 16.7.16 on a MediaTek MT6877 phone, booted directly by the stock LK bootloader: UFS root, LK framebuffer display, touch, keys, SpringBoard. Kernel patch recipe, CI hash gates |
| [lgrachov/ios-qemu](https://github.com/lgrachov/ios-qemu) / sweet lineage, fetched via [MakrSas/ios-topaz](https://github.com/MakrSas/ios-topaz) at `BASE_SHA` | The underlying XNU patch series (sweet 0001–0079), device-tree and payload tools, the iOS root-disk builder |
| [blacktop/darwin-xnu-build](https://github.com/blacktop/darwin-xnu-build) | The XNU build driver |
| [UniXNU](https://github.com/UniXNU/UniXNU) | Fallback route (UEFI + iPadOS 17) if direct LK boot had failed |
| [Celestia Nexus](https://github.com/Homura8/celestia-nexus) | Hardware-agnostic experiment records, pinned inputs and evidence conventions |

Nothing from these projects is vendored: sources are fetched at pinned commits
during builds. No Apple firmware, IPSW, KDK, root image, stock firmware or
device dump is ever committed (`scripts/check_repo.py` enforces common
cases); everything derived lives in Git-ignored `out/`.

## Repository map

| Path | What |
| --- | --- |
| `patches/02NN-g54-*.patch` | G54 kernel patches (APSL 2.0), applied after ruby's series |
| `config/kernel.env` | Every pin and hash the kernel build checks |
| `payload/g1/` | The probe: runs first from LK, fixes UFS/touch hardware state, loads XNU |
| `scripts/g54_payload.py`, `g54_xnu_image.py` | Build the probe and the bootable `boot_a` image |
| `scripts/g54_usb.py`, `g54_console.ps1` | USB console host tools |
| `scripts/fw_tools.py`, `build_lzfse.sh` | Read-only firmware extraction (super/EROFS/ramdisk/DTB/.ko tables/IM4P) |
| `scripts/xnu_tree.sh` | Local patched XNU tree and CI's patch checks |
| `scripts/mkiosroot-macos.sh` | Builds the iOS root image (macOS) |
| `docs/experiments/` | One run card per hardware experiment (E0–E50…) |

## Build the kernel

`.github/workflows/kernel.yml` runs on GitHub's `macos-15` runner with
Xcode 16.0 (~5 min). It verifies every pin in
[`config/kernel.env`](config/kernel.env): ruby's patchset hash, the G54
patchset hash and, when recorded, the built kernel's executable-data hash.
Details are in [docs/build.md](docs/build.md).

```sh
python3 scripts/check_repo.py                          # no device, no network
python3 -m unittest discover -s scripts -p 'test_*.py'
gh workflow run kernel.yml -R Homura8/g54-xnu          # or push to patches/ or config/
```

## Safety

Phone writes are documented steps, never automatic: they need the owner's
approval (a standing approval covers reflashing `boot_a`, see AGENTS.md), a
verified stock restore image and a recovery route
([docs/hardware-loop.md](docs/hardware-loop.md)). `fastboot boot` does not
work on the G54, so tests flash `boot_a`. The scripts here never flash; the
USB console's `fastboot`/`reboot` commands only reboot the phone (after a
filesystem sync). Never flash a package's `flashfile.xml` wholesale.

## Licence

Original code and documentation: MIT ([LICENSE](LICENSE)). XNU patches in
`patches/` modify Apple's XNU and are under the APSL 2.0. Upstream projects
retain their own terms ([NOTICE](NOTICE)). Apple, iOS and iPhone are
trademarks of Apple Inc.; Motorola and Moto are trademarks of their owners. This
project is not affiliated with Apple, Motorola, MediaTek or the upstream projects.
