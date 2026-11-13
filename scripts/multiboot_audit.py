#!/usr/bin/env python3
"""Read-only multiboot discovery & feasibility audit for Moto G54 5G (cancunf).

  python3 scripts/multiboot_audit.py fastboot
  python3 scripts/multiboot_audit.py offline \
      --boot out/fw/boot.img \
      --vendor-boot out/vb/vendor_boot.img \
      --vbmeta out/fw/vbmeta.img out/fw/vbmeta_system.img \
      --super out/super/super.raw \
      --fstab out/vb/rd/first_stage_ramdisk/fstab.mt6855 \
      --xnu-payload out/g4/e36b-k8-boot.img.payload

Safety:
- Live fastboot mode only runs allowlisted read-only `fastboot devices` and
  `fastboot getvar ...` queries. It never flashes, erases, unlocks, switches
  slots, or reboots the device.
- Sensitive identifiers (serialno, imei, uid, token, etc.) are hashed just like
  scripts/m1_facts.py before writing to facts/.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import zlib

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = 20

SENSITIVE = re.compile(
    r"serial|imei|meid|iccid|imsi|msisdn|mac|uid|uuid|token|cert|key|sn$|barcode|"
    r"phone|number|account|android_id|fingerprint_id|ssn",
    re.IGNORECASE,
)
SAFE_KEYS = re.compile(r"^(ro\.product\.model_?.*|ro\.build\..*|.*\.machine|.*\.keyboard.*)$")

PROBE_PARTITIONS = [
    "boot_a", "boot_b", "vendor_boot_a", "vendor_boot_b",
    "dtbo_a", "dtbo_b", "lk_a", "lk_b",
    "vbmeta_a", "vbmeta_b", "vbmeta_system_a", "vbmeta_system_b",
    "super", "userdata", "metadata", "misc", "para", "expdb",
    "nvram", "nvdata", "nvcfg", "persist", "tee_a", "md1img_a",
]
SLOT_PARTITIONS = [
    "boot", "vendor_boot", "dtbo", "lk", "vbmeta", "vbmeta_system",
    "tee", "gz", "scp", "sspm", "mcupm", "dpm", "md1img", "preloader",
]
LOGICAL_CANDIDATES = [
    "system", "system_ext", "product", "vendor", "vendor_dlkm",
    "odm", "my_product", "my_stock", "my_heytap", "my_manifest",
    "super", "userdata",
]


def redact_value(value: str) -> str:
    if not value.strip():
        return value
    return "REDACTED:" + hashlib.sha256(value.encode()).hexdigest()[:8]


def redact_pairs(pairs: dict[str, str]) -> dict[str, str]:
    return {
        k: (redact_value(v) if SENSITIVE.search(k) and not SAFE_KEYS.match(k) else v)
        for k, v in pairs.items()
    }


def parse_getvar(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^(?:\(bootloader\)\s+)?(\S+):\s*(.*)$", line.strip())
        if match:
            key = match[1].strip()
            values[key] = (values[key] + match[2]) if key in values else match[2].strip()
    return values


def allowed_fastboot(args: list[str]) -> bool:
    if args in (["devices"], ["getvar", "all"]):
        return True
    if len(args) == 2 and args[0] == "getvar":
        return bool(re.fullmatch(r"[A-Za-z0-9_.:-]+", args[1]))
    return False


def run_fastboot(fb_path: str, args: list[str], timeout: float = TIMEOUT) -> dict:
    if not allowed_fastboot(args):
        raise PermissionError(f"refused non-read-only fastboot command: {args!r}")
    proc = subprocess.Popen(
        [fb_path, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, 9)
        out, err = proc.communicate()
        return {"argv": ["fastboot", *args], "error": f"timed out after {timeout}s"}
    return {
        "argv": ["fastboot", *args],
        "returncode": proc.returncode,
        "stdout": out.decode(errors="replace"),
        "stderr": err.decode(errors="replace"),
    }


def parse_hex_int(text: str | None) -> int | None:
    if not text:
        return None
    text = text.strip()
    try:
        return int(text, 16) if text.startswith(("0x", "0X")) else int(text)
    except ValueError:
        return None


def collect_fastboot() -> dict:
    fb = shutil.which("fastboot")
    if not fb:
        raise SystemExit("fastboot not found in PATH")
    devs = run_fastboot(fb, ["devices"])
    connected = [
        parts[0]
        for line in devs.get("stdout", "").splitlines()
        if len(parts := line.split()) >= 2 and parts[1].startswith("fastboot")
    ]
    if len(connected) != 1:
        raise SystemExit(f"Expected 1 device in fastboot mode, found {len(connected)}")

    all_res = run_fastboot(fb, ["getvar", "all"], timeout=60)
    if all_res.get("returncode") != 0:
        raise SystemExit("fastboot getvar all failed")
    getvar = redact_pairs(parse_getvar(all_res["stdout"] + all_res["stderr"]))

    partitions: dict[str, dict] = {}
    for name in PROBE_PARTITIONS:
        sz_res = run_fastboot(fb, ["getvar", f"partition-size:{name}"])
        tp_res = run_fastboot(fb, ["getvar", f"partition-type:{name}"])
        sz_kv = parse_getvar(sz_res.get("stdout", "") + sz_res.get("stderr", ""))
        tp_kv = parse_getvar(tp_res.get("stdout", "") + tp_res.get("stderr", ""))
        raw_sz = sz_kv.get(f"partition-size:{name}", "")
        raw_tp = tp_kv.get(f"partition-type:{name}", "")
        partitions[name] = {
            "size_raw": raw_sz,
            "size_bytes": parse_hex_int(raw_sz),
            "type": raw_tp,
        }

    has_slot: dict[str, str] = {}
    for name in SLOT_PARTITIONS:
        res = run_fastboot(fb, ["getvar", f"has-slot:{name}"])
        kv = parse_getvar(res.get("stdout", "") + res.get("stderr", ""))
        has_slot[name] = kv.get(f"has-slot:{name}", "")

    is_logical: dict[str, str] = {}
    for name in LOGICAL_CANDIDATES:
        res = run_fastboot(fb, ["getvar", f"is-logical:{name}"])
        kv = parse_getvar(res.get("stdout", "") + res.get("stderr", ""))
        is_logical[name] = kv.get(f"is-logical:{name}", "")

    block_info = {}
    for var in ("logical-block-size", "erase-block-size"):
        res = run_fastboot(fb, ["getvar", var])
        kv = parse_getvar(res.get("stdout", "") + res.get("stderr", ""))
        block_info[var] = parse_hex_int(kv.get(var))

    hazards = []
    if getvar.get("securestate") != "flashing_unlocked":
        hazards.append(f"bootloader not unlocked: securestate={getvar.get('securestate')!r}")
    if getvar.get("is-userspace") != "no":
        hazards.append(f"expected bootloader fastboot (is-userspace=no), got {getvar.get('is-userspace')!r}")
    if getvar.get("snapshot-update-status", "none") != "none":
        hazards.append(f"Virtual A/B snapshot merge pending: {getvar.get('snapshot-update-status')!r}")
    if getvar.get("slot-successful:_b") != "yes":
        hazards.append("slot _b is NOT marked slot-successful=yes; do not use fastboot set_active for multiboot")

    return {
        "mode": "fastboot-multiboot-audit",
        "getvar": getvar,
        "block_info": block_info,
        "partitions": partitions,
        "has_slot": has_slot,
        "is_logical": is_logical,
        "hazards": hazards,
    }


# --- Offline parsers -----------------------------------------------------------

def align_up(n: int, page: int) -> int:
    return (n + page - 1) // page * page


def inspect_boot_image(path: Path) -> dict:
    data = path.read_bytes()
    if data[:8] != b"ANDROID!":
        return {"path": str(path), "error": "missing ANDROID! magic"}
    ks, rs, _, hs = struct.unpack_from("<4I", data, 8)
    ver = struct.unpack_from("<I", data, 40)[0]
    info: dict = {
        "path": str(path),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "header_version": ver,
        "header_size": hs,
        "kernel_size_compressed": ks,
        "ramdisk_size": rs,
    }
    if ver >= 4:
        info["boot_signature_size"] = struct.unpack_from("<I", data, 1580)[0]
    if len(data) >= 64 and data[-64:-60] == b"AVBf":
        maj, min_, orig_sz, vbm_off, vbm_sz = struct.unpack(">IIQQQ", data[-60:-28])
        info["avb_footer"] = {
            "version": f"{maj}.{min_}",
            "original_image_size": orig_sz,
            "vbmeta_offset": vbm_off,
            "vbmeta_size": vbm_sz,
        }
    k_off = align_up(hs, 4096) if ver >= 3 else 4096
    k_blob = data[k_off : k_off + ks]
    if k_blob[:2] == b"\x1f\x8b":
        raw = zlib.decompress(k_blob, 16 + zlib.MAX_WBITS)
        info["kernel_compression"] = "gzip"
        info["kernel_size_raw"] = len(raw)
        if len(raw) >= 0x40:
            code0, code1, text_off, image_size = struct.unpack_from("<IIQQ", raw, 0)
            info["arm64_image"] = {
                "magic_ok": raw[0x38:0x3C] == b"ARM\x64",
                "code0": hex(code0),
                "text_offset": hex(text_off),
                "image_size": image_size,
                "image_size_hex": hex(image_size),
                "tail_beyond_image_size": max(0, len(raw) - image_size),
            }
    return info


def inspect_vbmeta(path: Path) -> dict:
    d = path.read_bytes()
    if d[:4] != b"AVB0":
        return {"path": str(path), "error": "missing AVB0 magic"}
    (
        _magic, rmaj, rmin, auth_sz, aux_sz, alg,
        _hoff, _hsz, _soff, _ssz, _pkoff, _pksz, _pkmoff, _pkmsz,
        d_off, d_sz, rb_idx, flags, rb_loc,
    ) = struct.unpack_from(">4sIIQQIQQQQQQQQQQQII", d, 0)
    rel = d[128:176].split(b"\0")[0].decode(errors="replace")
    aux = d[256 + auth_sz : 256 + auth_sz + aux_sz]
    pos, end = d_off, d_off + d_sz
    props = {}
    hashes = []
    chains = []
    hashtrees = 0
    while pos + 16 <= end:
        tag, num_bytes = struct.unpack_from(">QQ", aux, pos)
        body = aux[pos + 16 : pos + 16 + num_bytes]
        if tag == 0 and len(body) >= 16:
            klen, vlen = struct.unpack_from(">QQ", body, 0)
            k = body[16 : 16 + klen].decode(errors="replace")
            v = body[17 + klen : 17 + klen + vlen].decode(errors="replace")
            props[k] = v
        elif tag == 1:
            hashtrees += 1
        elif tag == 2 and len(body) >= 56:
            img_sz, pn_len, salt_len, dig_len, hflags = struct.unpack_from(">QIIII", body, 0)
            alg_name = body[24:56].split(b"\0")[0].decode(errors="replace")
            # Android AVBHashDescriptor has 64 bytes reserved after flags before part_name (total header 120 bytes? wait: 24+32+64? No: struct AvbHashDescriptor = 16(parent)+8(img)+4(pn)+4(salt)+4(dig)+4(flags)+32(alg)+60(reserved)=132? Let's locate ASCII alg+name cleanly)
            hashes.append({"image_size": img_sz, "alg": alg_name, "flags": hflags})
        elif tag == 4 and len(body) >= 12:
            rb_loc2, pn_len, pk_len = struct.unpack_from(">III", body, 0)
            chains.append({"rollback_index_location": rb_loc2, "public_key_len": pk_len})
        pos += 16 + num_bytes
    return {
        "path": str(path),
        "sha256": hashlib.sha256(d).hexdigest(),
        "avb_version": f"{rmaj}.{rmin}",
        "algorithm_type": alg,
        "flags": flags,
        "verification_disabled": bool(flags & 2),
        "hashtree_disabled": bool(flags & 1),
        "rollback_index": rb_idx,
        "rollback_index_location": rb_loc,
        "release_string": rel,
        "properties": props,
        "chain_count": len(chains),
        "hash_count": len(hashes),
        "hashtree_count": hashtrees,
    }


def inspect_super_lp(path: Path) -> dict:
    """Parse Android Logical Partition (LP) metadata from raw super image."""
    with path.open("rb") as f:
        f.seek(4096)
        geom = f.read(52)
        if len(geom) < 52:
            return {"path": str(path), "error": "file too small for LP geometry"}
        magic, _ssz, _csum, max_meta_sz, slot_cnt, lba_sz = struct.unpack("<II32sIII", geom)
        if magic != 0x616C4467:
            return {"path": str(path), "error": f"bad LP geometry magic {magic:#x} (sparse images must be unsparsed first)"}
        f.seek(4096 + 4096 * 2)  # primary metadata slot 0 starts at 0x3000
        hdr = f.read(256)
        m_magic, maj, min_, hdr_sz = struct.unpack_from("<IHHI", hdr, 0)
        if m_magic != 0x414C5030:
            return {"path": str(path), "error": f"bad LP header magic {m_magic:#x}"}
        tables_sz = struct.unpack_from("<I", hdr, 44)[0]
        p_off, p_num, p_esz = struct.unpack_from("<III", hdr, 80)
        e_off, e_num, e_esz = struct.unpack_from("<III", hdr, 92)
        g_off, g_num, g_esz = struct.unpack_from("<III", hdr, 104)
        b_off, b_num, b_esz = struct.unpack_from("<III", hdr, 116)
        f.seek(4096 * 3 + hdr_sz)
        tbl = f.read(tables_sz)

    bdevs = []
    for i in range(b_num):
        first_lba, _sz, align, _aoff, pname, flags = struct.unpack_from("<QQII36sI", tbl, b_off + i * b_esz)
        bdevs.append({"name": pname.split(b"\0")[0].decode(errors="replace"), "first_lba": first_lba, "alignment": align, "flags": flags})

    groups = []
    for i in range(g_num):
        gname, flags, max_sz = struct.unpack_from("<36sIQ", tbl, g_off + i * g_esz)
        groups.append({"name": gname.split(b"\0")[0].decode(errors="replace"), "flags": flags, "max_size_bytes": max_sz})

    parts = []
    total_sec = 0
    for i in range(p_num):
        pname, attrs, first_ext, num_exts, grp_idx = struct.unpack_from("<36sIIII", tbl, p_off + i * p_esz)
        sec = 0
        for j in range(first_ext, first_ext + num_exts):
            num_sec, _ttype, _tdata, _tsrc = struct.unpack_from("<QIQQ", tbl, e_off + j * e_esz)
            sec += num_sec
        total_sec += sec
        parts.append({
            "name": pname.split(b"\0")[0].decode(errors="replace"),
            "group": groups[grp_idx]["name"] if grp_idx < len(groups) else str(grp_idx),
            "attrs": attrs,
            "sectors_512": sec,
            "size_bytes": sec * 512,
        })

    return {
        "path": str(path),
        "file_bytes": path.stat().st_size,
        "lp_version": f"{maj}.{min_}",
        "max_metadata_size": max_meta_sz,
        "metadata_slots": slot_cnt,
        "logical_block_size": lba_sz,
        "block_devices": bdevs,
        "groups": groups,
        "partitions": parts,
        "total_allocated_bytes": total_sec * 512,
    }


def inspect_fstab(path: Path) -> dict:
    entries = []
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cols = line.split()
        if len(cols) >= 5:
            flags = cols[4].split(",")
            entries.append({
                "src": cols[0],
                "mount": cols[1],
                "fs": cols[2],
                "logical": "logical" in flags,
                "slotselect": "slotselect" in flags,
                "avb": [f for f in flags if f.startswith("avb")],
                "encryption": [f for f in flags if "encryption" in f or f == "inlinecrypt"],
            })
    return {"path": str(path), "entries": entries}


def inspect_gpt(path: Path, lba_size: int = 4096) -> dict:
    data = path.read_bytes()
    # MediaTek PGPT may place EFI PART at offset 512 (512B LBA) or lba_size (4KB LBA)
    hdr_off = None
    for cand in (lba_size, 512, 0):
        if data[cand : cand + 8] == b"EFI PART":
            hdr_off = cand
            break
    if hdr_off is None:
        return {"path": str(path), "error": "no EFI PART header found"}
    hdr = data[hdr_off : hdr_off + 92]
    (_sig, _rev, hsz, hc_crc, _resv, cur_lba, bkup_lba, first_usable, last_usable,
     _guid, part_lba, num_entries, entry_sz, entries_crc) = struct.unpack("<8sIIIIQQQQ16sQIII", hdr)
    # Determine effective LBA spacing from entry offset if PGPT uses 512-byte offset
    ent_off = 1024 if hdr_off == 512 else part_lba * lba_size
    if ent_off + num_entries * entry_sz > len(data):
        ent_off = hdr_off + lba_size if hdr_off + lba_size + num_entries * entry_sz <= len(data) else hdr_off + 512
    parts = []
    for i in range(num_entries):
        off = ent_off + i * entry_sz
        if off + entry_sz > len(data):
            break
        ent = data[off : off + entry_sz]
        if ent[:16] == b"\x00" * 16:
            continue
        flba, llba, attrs = struct.unpack_from("<QQQ", ent, 32)
        name = ent[56:128].decode("utf-16-le", errors="replace").split("\0")[0]
        parts.append({
            "index": i + 1,
            "name": name,
            "first_lba": flba,
            "last_lba": llba,
            "blocks": llba - flba + 1,
            "size_bytes": (llba - flba + 1) * lba_size,
            "attrs": hex(attrs),
        })
    return {
        "path": str(path),
        "header_offset": hdr_off,
        "lba_size": lba_size,
        "first_usable_lba": first_usable,
        "last_usable_lba": last_usable,
        "num_entries": num_entries,
        "used_entries": len(parts),
        "free_entries": num_entries - len(parts),
        "partitions": parts,
    }


def plan_userdata_split(userdata_bytes: int, ios_gib: int = 16, ios_boot_mib: int = 0, lba_size: int = 4096) -> dict:
    """Compute exact non-destructive in-place split of `userdata` preserving the front iOS region."""
    total_blocks = userdata_bytes // lba_size
    ios_blocks = (ios_gib * 1024 * 1024 * 1024) // lba_size
    boot_blocks = (ios_boot_mib * 1024 * 1024) // lba_size
    if ios_blocks + boot_blocks >= total_blocks:
        raise ValueError("Requested iOS partitions exceed userdata size")
    android_blocks = total_blocks - ios_blocks - boot_blocks
    return {
        "lba_size": lba_size,
        "original_userdata_bytes": userdata_bytes,
        "original_userdata_blocks": total_blocks,
        "ios_root": {
            "rel_first_block": 0,
            "blocks": ios_blocks,
            "bytes": ios_blocks * lba_size,
            "preserves_existing_ios_front_region": True,
        },
        "ios_boot": None if boot_blocks == 0 else {
            "rel_first_block": ios_blocks,
            "blocks": boot_blocks,
            "bytes": boot_blocks * lba_size,
        },
        "new_userdata": {
            "rel_first_block": ios_blocks + boot_blocks,
            "blocks": android_blocks,
            "bytes": android_blocks * lba_size,
            "gib": round(android_blocks * lba_size / (1024 ** 3), 2),
        },
    }


def run_offline_audit(args: argparse.Namespace) -> dict:
    report: dict = {"mode": "offline-multiboot-audit"}
    if args.boot:
        report["boot"] = inspect_boot_image(args.boot)
    if args.vendor_boot:
        # Reuse m1_facts style basic check + size
        from m1_facts import analyse_bootimg
        report["vendor_boot"] = analyse_bootimg(args.vendor_boot.read_bytes())
    if args.vbmeta:
        report["vbmeta"] = [inspect_vbmeta(p) for p in args.vbmeta]
    if args.super:
        report["super"] = inspect_super_lp(args.super)
    if args.fstab:
        report["fstab"] = inspect_fstab(args.fstab)
    if args.gpt:
        report["gpt"] = inspect_gpt(args.gpt)
    if args.xnu_payload:
        data = args.xnu_payload.read_bytes()
        report["xnu_payload"] = {
            "path": str(args.xnu_payload),
            "bytes": len(data),
            "magic_ok": data[:8] == b"SWEETXNU",
        }
    if args.userdata_bytes:
        report["userdata_split_plan"] = plan_userdata_split(args.userdata_bytes, args.ios_gib, args.ios_boot_mib)

    # Feasibility checks
    checks = {}
    if "boot" in report and "xnu_payload" in report and "kernel_size_compressed" in report["boot"]:
        # Conservative estimate: gzip(linux) + gzip(xnu ~55% of raw) + ramdisk + 64KB stub/headers <= 64 MiB
        est = report["boot"]["kernel_size_compressed"] + int(report["xnu_payload"]["bytes"] * 0.6) + report["boot"]["ramdisk_size"] + 131072
        checks["dual_kernel_boot_a_est_bytes"] = est
        checks["fits_in_64mib_boot_a"] = est <= 64 * 1024 * 1024
    if "super" in report and "total_allocated_bytes" in report["super"]:
        max_main = max((g["max_size_bytes"] for g in report["super"]["groups"]), default=0)
        checks["super_allocated_bytes"] = report["super"]["total_allocated_bytes"]
        checks["super_main_max_bytes"] = max_main
        checks["super_free_bytes"] = max(0, max_main - report["super"]["total_allocated_bytes"])
    report["feasibility_checks"] = checks
    return report


def save_report(report: dict, out_base: Path | None) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = (out_base or ROOT / "facts") / f"{stamp}-multiboot-audit"
    out.mkdir(parents=True, exist_ok=False)
    (out / "audit.json").write_text(json.dumps(report, indent=2) + "\n")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, help="output directory base (default facts/)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fastboot")
    off = sub.add_parser("offline")
    off.add_argument("--boot", type=Path)
    off.add_argument("--vendor-boot", type=Path)
    off.add_argument("--vbmeta", type=Path, nargs="+")
    off.add_argument("--super", type=Path)
    off.add_argument("--fstab", type=Path)
    off.add_argument("--gpt", type=Path)
    off.add_argument("--xnu-payload", type=Path)
    off.add_argument("--userdata-bytes", type=int, default=0x1BEB7F8000)
    off.add_argument("--ios-gib", type=int, default=16)
    off.add_argument("--ios-boot-mib", type=int, default=0)
    args = ap.parse_args(argv)

    if args.cmd == "fastboot":
        report = collect_fastboot()
    else:
        report = run_offline_audit(args)
    out = save_report(report, args.out)
    print(json.dumps(report, indent=2))
    print(f"\nSaved read-only audit to {out} (not committed).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
