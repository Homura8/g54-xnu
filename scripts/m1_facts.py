#!/usr/bin/env python3
"""Collect M1 device facts **read-only**, and analyse stock images offline.

  python3 scripts/m1_facts.py adb                 # phone booted to Android, USB debugging on
  python3 scripts/m1_facts.py fastboot            # phone in fastboot mode: `getvar all` only
  python3 scripts/m1_facts.py bootimg FILE...     # stock boot / vendor_boot / init_boot images
  python3 scripts/m1_facts.py dtb FILE...         # a DTB, or a DTB section/blob

Everything is written to facts/<UTC time>-<mode>/ (ignored by Git): raw
outputs, facts.json and summary.md to copy into docs/device-facts.md.

Safety: the phone is only *read*. Every adb/fastboot command is checked
against an allowlist before it runs (getprop, uname, reads of fixed /proc and
/sys paths, partition-name listings, `fastboot getvar all`). Nothing can
unlock, flash, erase, boot or reboot the phone. Serial numbers, IMEIs, MAC
addresses and similar identifiers are replaced by a short hash.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = 20

# --- read-only command allowlist ------------------------------------------------

READ_PATHS = [
    r"/proc/(cpuinfo|meminfo|version|cmdline)",
    r"/sys/devices/system/cpu/(possible|present|online)",
    r"/sys/devices/system/cpu/cpu\d+/(cpu_capacity|regs/identification/midr_el1|cpufreq/cpuinfo_max_freq)",
    r"/proc/device-tree/(compatible|model|chosen/[\w,.-]+|memory(@[0-9a-f]+)?/reg|cpus/cpu@[0-9a-f]+/compatible)",
    r"/sys/class/graphics/fb0/(virtual_size|stride|bits_per_pixel)",
]
LIST_PATHS = [r"/dev/block/by-name", r"/dev/block/platform/[\w.-]+/(by-name|[\w.-]+/by-name)",
              r"/proc/device-tree", r"/proc/device-tree/cpus", r"/proc/device-tree/reserved-memory"]


def allowed(tool: str, args: list[str]) -> bool:
    """True only for the exact read-only command shapes this tool uses."""
    if tool == "fastboot":
        return args in (["devices"], ["getvar", "all"])
    if tool != "adb":
        return False
    if args in (["devices", "-l"], ["get-state"], ["shell", "getprop"], ["shell", "uname", "-a"]):
        return True
    if len(args) == 3 and args[:2] == ["shell", "cat"]:
        return any(re.fullmatch(p, args[2]) for p in READ_PATHS)
    if len(args) == 4 and args[:3] == ["shell", "ls", "-1"]:
        return any(re.fullmatch(p, args[3]) for p in LIST_PATHS)
    return False


def run(tool_path: str, tool: str, args: list[str], timeout: float = TIMEOUT) -> dict:
    if not allowed(tool, args):
        raise PermissionError(f"refused: {tool} {' '.join(args)} is not a read-only command on the allowlist")
    try:
        # A fresh session so a hung adb/fastboot can be killed with its children.
        process = subprocess.Popen([tool_path, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as error:
        return {"argv": [tool, *args], "error": str(error)}
    try:
        out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, 9)
        out, err = process.communicate()
        return {"argv": [tool, *args], "error": f"timed out after {timeout} s",
                "stdout": out.decode(errors="replace"), "stderr": err.decode(errors="replace")}
    return {"argv": [tool, *args], "returncode": process.returncode, "stdout": out.decode(errors="replace"),
            "stderr": err.decode(errors="replace")}


# --- privacy -----------------------------------------------------------------------

SENSITIVE = re.compile(r"serial|imei|meid|iccid|imsi|msisdn|mac|uid|uuid|token|cert|key|sn$|barcode|"
                       r"phone|number|account|android_id|fingerprint_id|ssn", re.IGNORECASE)
SAFE_KEYS = re.compile(r"^(ro\.product\.model_?.*|ro\.build\..*|.*\.machine|.*\.keyboard.*)$")


def redact_value(value: str) -> str:
    if not value.strip():
        return value
    return "REDACTED:" + hashlib.sha256(value.encode()).hexdigest()[:8]


def redact_pairs(pairs: dict[str, str]) -> dict[str, str]:
    return {key: (redact_value(value) if SENSITIVE.search(key) and not SAFE_KEYS.match(key) else value)
            for key, value in pairs.items()}


def parse_getprop(text: str) -> dict[str, str]:
    return dict(re.findall(r"^\[([^\]]+)\]: \[(.*)\]$", text, re.MULTILINE))


def parse_getvar(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        # Keys may contain colons ("partition-size:boot_a: 0x4000000"); keys have no spaces.
        match = re.match(r"^\(bootloader\)\s+(\S+):\s*(.*)$", line.strip())
        if match:
            key = match[1].strip()
            values[key] = (values[key] + match[2]) if key in values else match[2].strip()
    return values


def redact_text(text: str, secrets: list[str]) -> str:
    for secret in sorted({s for s in secrets if len(s) >= 6}, key=len, reverse=True):
        text = text.replace(secret, redact_value(secret))
    return text


# --- offline image analysis ------------------------------------------------------

def page(n: int, size: int) -> int:
    return (n + size - 1) // size * size


def payload_kind(data: bytes) -> str:
    if data[:2] == b"\x1f\x8b":
        return "gzip"
    if data[:4] == b"\x02\x21\x4c\x18" or data[:4] == b"\x04\x22\x4d\x18":
        return "lz4"
    if data[:4] == b"\x88\x16\x88\x58":
        return "mediatek-header"
    if data[0x38:0x3c] == b"ARM\x64":
        return "arm64-image"
    if data[:4] == b"\xd0\x0d\xfe\xed":
        return "dtb"
    if data[:6] in (b"070701", b"070702"):
        return "cpio"
    return "unknown" if data else "empty"


def avb_footer(data: bytes) -> dict | None:
    if len(data) >= 64 and data[-64:-60] == b"AVBf":
        major, minor, original, vbmeta_offset, vbmeta_size = struct.unpack(">IIQQQ", data[-60:-28])
        return {"version": f"{major}.{minor}", "original_image_size": original,
                "vbmeta_offset": vbmeta_offset, "vbmeta_size": vbmeta_size}
    return None


def analyse_bootimg(data: bytes) -> dict:
    """Android boot (v0-v4) or vendor_boot (v3-v4) header and section layout."""
    result = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "avb_footer": avb_footer(data)}
    sections = []
    if data[:8] == b"ANDROID!":
        version = struct.unpack_from("<I", data, 40)[0]
        result.update(kind="boot", header_version=version)
        if version <= 2:
            (kernel, kernel_addr, ramdisk, ramdisk_addr, second, second_addr, tags, page_size) = \
                struct.unpack_from("<8I", data, 8)
            result.update(page_size=page_size, kernel_addr=hex(kernel_addr), ramdisk_addr=hex(ramdisk_addr),
                          tags_addr=hex(tags), cmdline=data[64:576].split(b"\0")[0].decode(errors="replace"))
            sizes = [("kernel", kernel), ("ramdisk", ramdisk), ("second", second)]
            if version >= 1:
                sizes.append(("recovery_dtbo", struct.unpack_from("<I", data, 1632)[0]))
            if version == 2:
                dtb_size, dtb_addr = struct.unpack_from("<IQ", data, 1648)
                sizes.append(("dtb", dtb_size))
                result["dtb_addr"] = hex(dtb_addr)
            offset = page_size
        else:
            kernel, ramdisk, _, header_size = struct.unpack_from("<4I", data, 8)
            page_size = 4096
            result.update(page_size=page_size, header_size=header_size,
                          cmdline=data[44:44 + 1536].split(b"\0")[0].decode(errors="replace"))
            sizes = [("kernel", kernel), ("ramdisk", ramdisk)]
            if version >= 4:
                sizes.append(("boot_signature", struct.unpack_from("<I", data, 1580)[0]))
            offset = page(header_size, page_size)
    elif data[:8] == b"VNDRBOOT":
        version, page_size, kernel_addr, ramdisk_addr, ramdisk = struct.unpack_from("<5I", data, 8)
        tags_addr = struct.unpack_from("<I", data, 2076)[0]
        header_size, dtb_size, dtb_addr = struct.unpack_from("<IIQ", data, 2096)
        result.update(kind="vendor_boot", header_version=version, page_size=page_size,
                      kernel_addr=hex(kernel_addr), ramdisk_addr=hex(ramdisk_addr), tags_addr=hex(tags_addr),
                      dtb_addr=hex(dtb_addr), cmdline=data[28:28 + 2048].split(b"\0")[0].decode(errors="replace"),
                      name=data[2080:2096].split(b"\0")[0].decode(errors="replace"))
        sizes = [("vendor_ramdisk", ramdisk), ("dtb", dtb_size)]
        if version >= 4:
            table, entries, entry_size, bootconfig = struct.unpack_from("<4I", data, 2112)
            sizes += [("vendor_ramdisk_table", table), ("bootconfig", bootconfig)]
            result["vendor_ramdisk_entries"] = entries
        offset = page(header_size, page_size)
    else:
        return {**result, "kind": "unknown", "error": "no ANDROID! or VNDRBOOT magic"}
    for name, size in sizes:
        chunk = data[offset:offset + size]
        sections.append({"name": name, "offset": offset, "size": size, "format": payload_kind(chunk),
                         "inside_file": offset + size <= len(data)})
        offset = page(offset + size, page_size)
    result["sections"] = sections
    return result


def fdt_blobs(data: bytes) -> list[bytes]:
    """Every flattened device tree in data (DTB sections may concatenate several)."""
    blobs = []
    start = data.find(b"\xd0\x0d\xfe\xed")
    while start >= 0 and start + 8 <= len(data):
        size = struct.unpack_from(">I", data, start + 4)[0]
        if 40 <= size <= len(data) - start:
            blobs.append(data[start:start + size])
            start = data.find(b"\xd0\x0d\xfe\xed", start + size)
        else:
            start = data.find(b"\xd0\x0d\xfe\xed", start + 4)
    return blobs


def fdt_nodes(blob: bytes) -> dict[str, dict[str, bytes]]:
    """Path -> {property: raw value} for one FDT (spec v17)."""
    total, struct_off, strings_off = struct.unpack_from(">III", blob, 4)
    struct_size = struct.unpack_from(">I", blob, 36)[0] if len(blob) >= 40 else total - struct_off
    cursor, end, stack, nodes = struct_off, struct_off + struct_size, [], {}
    while cursor < end:
        token = struct.unpack_from(">I", blob, cursor)[0]
        cursor += 4
        if token == 1:  # FDT_BEGIN_NODE
            name_end = blob.index(b"\0", cursor)
            stack.append(blob[cursor:name_end].decode(errors="replace"))
            cursor = page(name_end + 1, 4)
            nodes.setdefault("/" + "/".join(s for s in stack if s), {})
        elif token == 2:  # FDT_END_NODE
            stack.pop()
        elif token == 3:  # FDT_PROP
            length, name_off = struct.unpack_from(">II", blob, cursor)
            cursor += 8
            name = blob[strings_off + name_off:blob.index(b"\0", strings_off + name_off)].decode(errors="replace")
            nodes["/" + "/".join(s for s in stack if s)][name] = blob[cursor:cursor + length]
            cursor = page(cursor + length, 4)
        elif token == 4:  # FDT_NOP
            continue
        elif token == 9:  # FDT_END
            break
        else:
            raise ValueError(f"bad FDT token {token:#x} at {cursor - 4:#x}")
    return nodes


def strings(value: bytes) -> list[str]:
    return [s.decode(errors="replace") for s in value.rstrip(b"\0").split(b"\0") if s]


def cells(value: bytes) -> list[int]:
    return list(struct.unpack(f">{len(value) // 4}I", value[:len(value) // 4 * 4]))


def summarise_dtb(blob: bytes) -> dict:
    nodes = fdt_nodes(blob)
    root = nodes.get("/", {})
    pick = {"compatible": strings(root.get("compatible", b"")), "model": strings(root.get("model", b"")),
            "cpus": [], "memory": [], "reserved_memory": [], "interrupt_controllers": [], "uarts": [],
            "framebuffers": [], "ufs": [], "displays": [], "touch": []}
    for path, props in nodes.items():
        name = path.rsplit("/", 1)[-1]
        compatible = strings(props.get("compatible", b""))
        joined = " ".join(compatible).lower()
        entry = {"path": path, "compatible": compatible}
        if "reg" in props:
            entry["reg"] = [hex(c) for c in cells(props["reg"])]
        if path.startswith("/cpus/cpu@"):
            pick["cpus"].append(entry)
        elif name.startswith("memory") and path.count("/") == 1:
            pick["memory"].append(entry)
        elif path.startswith("/reserved-memory/"):
            pick["reserved_memory"].append(entry)
        if "interrupt-controller" in props or "gic" in joined:
            pick["interrupt_controllers"].append(entry)
        if "uart" in joined or "serial" in name:
            pick["uarts"].append(entry)
        if "framebuffer" in name.lower() or "framebuffer" in joined:
            pick["framebuffers"].append(entry)
        if "ufs" in joined:
            pick["ufs"].append(entry)
        if any(word in joined for word in ("dsi", "disp_ovl", "mediatek,disp", "panel")):
            pick["displays"].append(entry)
        if any(word in joined for word in ("touch", "goodix", "focaltech", "novatek,nvt-ts", "himax", "ilitek")):
            pick["touch"].append(entry)
    return pick


def load_image(path: Path) -> bytes:
    data = path.read_bytes()
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" and path.suffix == ".gz" else data


# --- commands -----------------------------------------------------------------------

def output_dir(mode: str, base: Path | None) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = (base or ROOT / "facts") / f"{stamp}-{mode}"
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def tool_path(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise SystemExit(f"{name} not found. Install Android platform tools (macOS: "
                         f"`brew install --cask android-platform-tools`) and run again.")
    return found


def collect_adb(out: Path) -> dict:
    adb = tool_path("adb")
    log = []

    def call(*args):
        entry = run(adb, "adb", list(args))
        log.append(entry)
        return entry

    state = call("get-state")
    if state.get("stdout", "").strip() != "device":
        raise SystemExit("No single authorised Android device: enable USB debugging, accept the prompt "
                         "on the phone, and check `adb devices`. " + state.get("stderr", "").strip())
    props = parse_getprop(call("shell", "getprop").get("stdout", ""))
    facts = {"getprop": redact_pairs(props), "reads": {}, "lists": {}}
    for path in ("/proc/cpuinfo", "/proc/meminfo", "/proc/version", "/sys/devices/system/cpu/possible",
                 "/proc/device-tree/compatible", "/proc/device-tree/model",
                 "/sys/class/graphics/fb0/virtual_size", "/sys/class/graphics/fb0/stride"):
        entry = call("shell", "cat", path)
        facts["reads"][path] = entry.get("stdout", "").replace("\0", " ").strip() or entry.get("stderr", "").strip()
    possible = facts["reads"]["/sys/devices/system/cpu/possible"]
    count = int(possible.split("-")[-1]) + 1 if re.fullmatch(r"0-\d+", possible) else 0
    for cpu in range(count):
        for leaf in ("cpu_capacity", "regs/identification/midr_el1", "cpufreq/cpuinfo_max_freq"):
            path = f"/sys/devices/system/cpu/cpu{cpu}/{leaf}"
            entry = call("shell", "cat", path)
            facts["reads"][path] = entry.get("stdout", "").strip() or entry.get("stderr", "").strip()
    for path in ("/dev/block/by-name", "/proc/device-tree/reserved-memory"):
        entry = call("shell", "ls", "-1", path)
        facts["lists"][path] = entry.get("stdout", "").split() if entry.get("returncode") == 0 \
            else entry.get("stderr", "").strip()
    facts["uname"] = call("shell", "uname", "-a").get("stdout", "").strip()
    secrets = [value for key, value in props.items() if SENSITIVE.search(key) and not SAFE_KEYS.match(key)]
    raw = json.dumps(log, indent=1)
    (out / "adb-commands.json").write_text(redact_text(raw, secrets))
    return {"mode": "adb", "facts": facts, "summary": adb_summary(props, facts)}


def adb_summary(props: dict, facts: dict) -> dict:
    get = props.get
    by_name = facts["lists"].get("/dev/block/by-name")
    names = by_name if isinstance(by_name, list) else []
    base = sorted({re.sub(r"_[ab]$", "", n) for n in names})
    midr = sorted({facts["reads"][k] for k in facts["reads"] if k.endswith("midr_el1") and facts["reads"][k].startswith("0x")})
    parts = {"0xd05": "Cortex-A55", "0xd41": "Cortex-A78", "0xd0b": "Cortex-A76", "0xd44": "Cortex-X1"}
    cores = [parts.get(hex((int(m, 16) >> 4) & 0xFFF), hex((int(m, 16) >> 4) & 0xFFF)) for m in midr]
    return {
        "model": get("ro.product.model"), "device": get("ro.product.device"), "manufacturer": get("ro.product.manufacturer"),
        "board_platform": get("ro.board.platform"), "soc_model": get("ro.soc.model"), "hardware": get("ro.boot.hardware"),
        "android_release": get("ro.build.version.release"), "first_api_level": get("ro.product.first_api_level"),
        "build_fingerprint": get("ro.build.fingerprint"), "slot_suffix": get("ro.boot.slot_suffix"),
        "verified_boot_state": get("ro.boot.verifiedbootstate"), "flash_locked": get("ro.boot.flash.locked"),
        "boot_image_header_version": get("ro.boot.boot_image_version") or "unknown (analyse the stock boot image)",
        "dynamic_partitions": get("ro.boot.dynamic_partitions"), "bootdevice": get("ro.boot.bootdevice"),
        "cpu_core_types": cores, "partitions": base,
        "has_vendor_boot": "vendor_boot" in base, "has_init_boot": "init_boot" in base,
        "has_lk": any(n in base for n in ("lk", "lk2", "bootloader")),
        "framebuffer_virtual_size": facts["reads"].get("/sys/class/graphics/fb0/virtual_size"),
    }


def collect_fastboot(out: Path) -> dict:
    fastboot = tool_path("fastboot")
    devices = run(fastboot, "fastboot", ["devices"])
    if not devices.get("stdout", "").strip():
        raise SystemExit("No phone in fastboot mode (`fastboot devices` is empty).")
    entry = run(fastboot, "fastboot", ["getvar", "all"], timeout=60)
    text = entry.get("stdout", "") + entry.get("stderr", "")  # fastboot prints getvar output on stderr
    values = parse_getvar(text)
    secrets = [value for key, value in values.items() if SENSITIVE.search(key)]
    secrets += [line.split()[0] for line in devices["stdout"].splitlines() if line.split()]
    (out / "getvar-all.txt").write_text(redact_text(text, secrets))
    redacted = redact_pairs(values)
    keys = ("product", "variant", "unlocked", "securestate", "is-userspace", "current-slot", "slot-count",
            "max-download-size", "version-bootloader", "hw-revision", "partition-size:boot_a",
            "partition-size:vendor_boot_a", "partition-size:init_boot_a", "partition-size:lk_a")
    return {"mode": "fastboot", "facts": {"getvar": redacted},
            "summary": {key: redacted.get(key) for key in keys if key in redacted}}


def write_report(out: Path, report: dict) -> None:
    (out / "facts.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = [f"# M1 facts ({report['mode']}, {out.name})", "",
             "Copy observed values into docs/device-facts.md with this source and date.", "",
             "| Fact | Value |", "| --- | --- |"]
    for key, value in report["summary"].items():
        text = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
        lines.append(f"| {key} | {text.replace('|', '/')} |")
    (out / "summary.md").write_text("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, help="output base directory (default facts/)")
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("adb")
    sub.add_parser("fastboot")
    for name in ("bootimg", "dtb"):
        sub.add_parser(name).add_argument("files", type=Path, nargs="+")
    args = parser.parse_args(argv)
    out = output_dir(args.mode, args.out)
    try:
        report = collect(args, out)
    except BaseException:
        if not any(out.iterdir()):
            out.rmdir()  # nothing collected: leave no empty run behind
        raise
    write_report(out, report)
    print((out / "summary.md").read_text())
    print(f"Saved to {out} (not committed). Review before sharing: it describes your phone.")
    return 0


def collect(args: argparse.Namespace, out: Path) -> dict:
    if args.mode == "adb":
        report = collect_adb(out)
    elif args.mode == "fastboot":
        report = collect_fastboot(out)
    elif args.mode == "bootimg":
        images = {str(path): analyse_bootimg(load_image(path)) for path in args.files}
        summary = {}
        for name, image in images.items():
            dtb = [s for s in image.get("sections", []) if s["name"] == "dtb" and s["size"]]
            summary[Path(name).name] = (f"{image['kind']} v{image.get('header_version')}, page {image.get('page_size')}, "
                                        f"dtb {'yes' if dtb else 'no'}, avb {'yes' if image.get('avb_footer') else 'no'}, "
                                        + ", ".join(f"{s['name']}={s['size']}:{s['format']}" for s in image.get("sections", [])))
            data = load_image(Path(name))
            for section in dtb:
                for index, blob in enumerate(fdt_blobs(data[section["offset"]:section["offset"] + section["size"]])):
                    image.setdefault("dtbs", []).append(summarise_dtb(blob))
        report = {"mode": "bootimg", "images": images, "summary": summary}
    else:
        dtbs = {str(path): [summarise_dtb(blob) for blob in fdt_blobs(load_image(path))] for path in args.files}
        summary = {Path(name).name: f"{len(blobs)} DTB(s): " + "; ".join(
            f"{', '.join(b['compatible'][:2])} ({len(b['cpus'])} cpus, {len(b['reserved_memory'])} reserved)"
            for b in blobs) for name, blobs in dtbs.items()}
        report = {"mode": "dtb", "dtbs": dtbs, "summary": summary}
    return report


if __name__ == "__main__":
    sys.exit(main())
