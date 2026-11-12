#!/usr/bin/env python3
"""Fast repository checks: no device, no network, no Apple material.

  python3 scripts/check_repo.py

* config/kernel.env: known keys only, exact pins (40-hex commits, 64-hex
  hashes), HTTPS sources; KERNEL_EXPECT_EXEC_DATA may be empty only while a
  G54 patch has no booted reference.
* With no G54 patch, the G54 patchset gate must equal ruby's (line K0).
* Tracked files: no images, archives, IPSWs, KDKs, dumps or keys.
* patches/: only *.patch plus README.md.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
COMMITS = {"RUBY_SHA", "BASE_SHA", "DXB_SHA"}
HASHES = {"RUBY_PATCHSET_SHA256", "BASELINE_MANIFEST_SHA256", "G54_PATCHSET_SHA256"}
URLS = {"RUBY_REPO", "BASE_REPO", "DXB_REPO"}
PLAIN = {"MACOS_VERSION": r"\d+\.\d+", "APPLE_XNU_TAG": r"xnu-[\d.]+", "KERNEL_CONFIG": r"RELEASE|DEVELOPMENT|DEBUG",
         "MACHINE_CONFIG": r"[A-Z0-9]+", "KERNEL_CPU": r"[a-z0-9-]+", "RUNNER_IMAGE": r"macos-\d+",
         "XCODE_VERSION": r"\d+\.\d+(\.\d+)?", "XCODE_BUILD": r"[0-9A-Za-z]+",
         "KERNEL_EXPECT_EXEC_DATA": r"([0-9a-f]{64})?"}
FORBIDDEN = re.compile(r"\.(img|bin|ipsw|dmg|kdk|pkg|zip|7z|tar|gz|xz|tgz|elf|o|a|dtb|dtbo|ozip|apfs|"
                       r"hfs|raw|lz4|im4p|img4|key|pem|p12|mobileprovision)$", re.IGNORECASE)


def env(path: Path) -> dict[str, str]:
    values = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"([A-Z0-9_]+)=(\S*)", line)
        if not match:
            raise SystemExit(f"{path}:{number}: expected KEY=value without spaces")
        if match[1] in values:
            raise SystemExit(f"{path}:{number}: duplicate {match[1]}")
        values[match[1]] = match[2]
    return values


def check_pins(values: dict[str, str], patches: list[Path]) -> list[str]:
    problems = []
    known = COMMITS | HASHES | URLS | set(PLAIN)
    for key in sorted(set(values) ^ known):
        problems.append(f"{'unknown' if key in values else 'missing'} key {key}")
    for key in COMMITS & set(values):
        if not re.fullmatch(r"[0-9a-f]{40}", values[key]):
            problems.append(f"{key} must be a full commit SHA")
    for key in HASHES & set(values):
        if not re.fullmatch(r"[0-9a-f]{64}", values[key]):
            problems.append(f"{key} must be a SHA-256")
    for key in URLS & set(values):
        if not re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+?(\.git)?", values[key]):
            problems.append(f"{key} must be an HTTPS GitHub URL")
    for key, pattern in PLAIN.items():
        if key in values and not re.fullmatch(pattern, values[key]):
            problems.append(f"{key}={values[key]!r} does not match {pattern}")
    if not patches and values.get("G54_PATCHSET_SHA256") != values.get("RUBY_PATCHSET_SHA256"):
        problems.append("no G54 patches: G54_PATCHSET_SHA256 must equal RUBY_PATCHSET_SHA256 (line K0)")
    return problems


def tracked() -> list[str]:
    try:
        output = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--cached", "--others",
                                 "--exclude-standard"], capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return [str(path.relative_to(ROOT)) for path in ROOT.rglob("*") if path.is_file() and ".git" not in path.parts]
    return [name for name in output.decode().split("\0") if name]


def main() -> int:
    patch_dir = ROOT / "patches"
    patches = sorted(patch_dir.glob("*.patch"))
    problems = check_pins(env(ROOT / "config/kernel.env"), patches)
    for name in tracked():
        if FORBIDDEN.search(name):
            problems.append(f"forbidden file type in the repository: {name}")
        if name.startswith("patches/") and not (name.endswith(".patch") or name == "patches/README.md"):
            problems.append(f"unexpected file in patches/: {name}")
    workflow = (ROOT / ".github/workflows/kernel.yml").read_text()
    if "config/kernel.env" not in workflow:
        problems.append("kernel.yml does not load config/kernel.env")
    for problem in problems:
        print(f"check_repo: {problem}", file=sys.stderr)
    print(f"check_repo: {'FAILED' if problems else 'ok'} ({len(patches)} G54 patches)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
