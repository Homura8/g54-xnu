#!/usr/bin/env python3
"""Build the G54 multiboot stub and pack it, with the stock Android kernel and
an optional iOS payload, into a boot header v4 image for boot_a.

  python3 scripts/g54_multiboot.py build  [--out out/mb] [-D LASTLOG_RING=... ...]
  python3 scripts/g54_multiboot.py pack   --stock boot.img --stub out/mb \\
      [--payload out/x/boot.img.payload] [--touch-fw novatek_ts_fw.bin] \\
      --userdata ios|android [--default ios|android|fastboot] [--timeout 5] \\
      [--recovery-passthrough] --out out/mb/mb-boot.img
  python3 scripts/g54_multiboot.py verify --stock boot.img --image mb-boot.img --stub out/mb \\
      [--payload ...] [--touch-fw ...]

Unlike scripts/g54_payload.py (probe images, proven E1-E37b), the stock
Linux Image must survive, so the kernel stream grows and the image layout
changes. See docs/multiboot-feasibility.md. Raw kernel (gunzipped stream):

  0                 stock arm64 Image, code0 replaced by `b stub_off`
  stub_off          multiboot stub (payload/multiboot, includes payload/g1/probe.c);
                    stub_off = max(file size, Image image_size) rounded up to 64 KiB
  stub_off + _end   [NVTFWBIN touch firmware] [SWEETXNU payload] zero pad,
                    "G54MBEND" + u64 image_id (the last 16 raw bytes)

image_id = the first 8 bytes (little endian) of SHA-256 over the raw kernel
with both image_id fields zero; it is also in the stub header.

Boot image: the stock header page with only kernel_size changed, the new
gzip stream, then the stock ramdisk and boot signature sections byte for
byte at their new page-aligned offsets. If the stock image has an AVB hash
footer, its vbmeta blob moves to the first 4 KiB boundary after the sections
and the footer's original_image_size/vbmeta_offset follow; the hash itself
stays stale, as in every image LK has accepted so far (orange state, E1).
The total size stays the stock size (the 64 MiB boot_a partition).

The verifier rebuilds nothing: it checks a finished image against the stock
one section by section. This script only writes files on the host; it never
talks to a phone.
"""
import argparse
import gzip
import hashlib
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import g54_payload  # noqa: E402
from g54_payload import PackError, gunzip, ARM64_MAGIC  # noqa: E402

PAGE = 4096
SRC = os.path.join(HERE, "..", "payload", "multiboot")

# The proven E37b "fast probe" configuration (docs/status.md): the iOS entry
# is probe_main() built exactly like this. -D on the command line may add to
# it or override a value (e.g. LASTLOG_RING/LASTLOG_TOTAL for a new kernel).
STUB_DEFS = {"G54_MULTIBOOT": None, "UFS_FIX": None, "UFS_HS": None, "TOUCH_SPI": None,
             "TOUCH_FW": None, "TOUCH_TEST_S": "0", "NO_RESV": None, "PHASE1_S": "1",
             "LOADER_S": "1"}

# Header at stub + 0x08 (entry.S mb_hdr, stub.c struct mb_header).
HDR_OFF = 8
HDR = struct.Struct("<8sIIQIIIIQQQ")
MAGIC = b"G54MBOOT"
TRAILER = b"G54MBEND"
ITEMS = {"ios": 0, "android": 1, "fastboot": 2}
FLAG_RECOVERY_PASS = 1
FLAG_ANDROID = 2

STUB_ALIGN = 0x10000
BRANCH_RANGE = 128 << 20            # b imm26
FIND_WINDOW = 0x200000              # probe.c find_fw/find_payload scan 2 MiB after _end
# E4: LK puts the Image at 0x40000000 and the DTB at 0x47C80000. A larger raw
# kernel would reach the DTB if LK keeps that address (hypothesis H2 in
# docs/multiboot-feasibility.md); the probe's UTP buffer at 0x50F00000 is beyond.
OBSERVED_KERNEL_PA = 0x40000000
OBSERVED_DTB_PA = 0x47C80000
MAX_RAW = OBSERVED_DTB_PA - OBSERVED_KERNEL_PA

AVB_FOOTER = struct.Struct(">4sIIQQQ28s")


def align(n, a):
    return (n + a - 1) // a * a


def branch(off):
    if off % 4 or not 0 < off < BRANCH_RANGE:
        raise PackError(f"stub offset {off:#x} not reachable by b")
    return 0x14000000 | (off // 4)


def parse_boot(img):
    """Section layout of a boot header v3/v4 image (page size fixed at 4096)."""
    if img[:8] != b"ANDROID!":
        raise PackError("not an Android boot image")
    kernel_size, ramdisk_size, _os, header_size = struct.unpack_from("<4I", img, 8)
    version = struct.unpack_from("<I", img, 40)[0]
    if version not in (3, 4):
        raise PackError(f"boot header v{version}; only v3/v4 supported")
    sig_size = struct.unpack_from("<I", img, 1580)[0] if version == 4 else 0
    if header_size > PAGE:
        raise PackError(f"header_size {header_size} > one page")
    k = PAGE
    r = k + align(kernel_size, PAGE)
    s = r + align(ramdisk_size, PAGE)
    end = s + align(sig_size, PAGE)
    if end > len(img):
        raise PackError("sections extend past the end of the image")
    return {"version": version, "kernel_size": kernel_size, "ramdisk_size": ramdisk_size,
            "sig_size": sig_size, "kernel_off": k, "ramdisk_off": r, "sig_off": s, "end": end}


def parse_footer(img):
    """AVB footer (last 64 bytes) and the vbmeta blob it points at, or None."""
    if len(img) < AVB_FOOTER.size or img[-64:-60] != b"AVBf":
        return None
    magic, major, minor, orig, vbm_off, vbm_size, reserved = AVB_FOOTER.unpack(img[-64:])
    if vbm_off + vbm_size > len(img) - 64 or img[vbm_off:vbm_off + 4] != b"AVB0":
        raise PackError("AVB footer does not point at a vbmeta blob")
    return {"major": major, "minor": minor, "original_image_size": orig,
            "vbmeta_offset": vbm_off, "vbmeta_size": vbm_size, "reserved": reserved}


def footer_bytes(f):
    return AVB_FOOTER.pack(b"AVBf", f["major"], f["minor"], f["original_image_size"],
                           f["vbmeta_offset"], f["vbmeta_size"], f["reserved"])


def stock_sections(stock):
    """The parts of the stock image that are carried over unchanged."""
    b = parse_boot(stock)
    footer = parse_footer(stock)
    ramdisk = stock[b["ramdisk_off"]:b["sig_off"]]          # page-padded, as in stock
    sig = stock[b["sig_off"]:b["end"]]
    tail_end = footer["vbmeta_offset"] if footer else len(stock)
    if any(stock[b["end"]:tail_end]):
        raise PackError("stock image has unknown data after its sections; refusing")
    if footer and any(stock[footer["vbmeta_offset"] + footer["vbmeta_size"]:-64]):
        raise PackError("stock image has unknown data between vbmeta and the footer; refusing")
    raw = gunzip(stock[b["kernel_off"]:b["kernel_off"] + b["kernel_size"]])
    if raw[0x38:0x3C] != ARM64_MAGIC:
        raise PackError("stock kernel lacks the arm64 Image header")
    code0 = struct.unpack_from("<I", raw, 0)[0]
    if code0 == g54_payload.BRANCH or raw.find(MAGIC) >= 0:
        raise PackError("stock kernel already carries a probe or multiboot stub")
    image_size = struct.unpack_from("<Q", raw, 0x10)[0] or len(raw)
    return {"boot": b, "footer": footer, "ramdisk": ramdisk, "sig": sig, "raw": raw,
            "code0": code0, "image_size": image_size}


def stub_layout(st):
    stub_off = align(max(len(st["raw"]), st["image_size"]), STUB_ALIGN)
    branch(stub_off)
    return stub_off


def read_header(stub):
    if len(stub) < HDR_OFF + HDR.size:
        raise PackError("stub too small")
    f = HDR.unpack_from(stub, HDR_OFF)
    if f[0] != MAGIC:
        raise PackError("stub has no G54MBOOT header at +0x08")
    keys = ("magic", "version", "hdr_size", "stub_off", "orig_code0", "default_item",
            "timeout_s", "flags", "blob_size", "stub_end", "image_id")
    return dict(zip(keys, f))


def blob_body(payload=None, touch_fw=None):
    """What follows the stub's _end: the same order g54_xnu_image.py gives the
    probe (touch firmware tag first, SWEETXNU at the next 4 KiB boundary)."""
    out = b""
    if touch_fw is not None:
        out = b"NVTFWBIN" + struct.pack("<II", len(touch_fw), 0) + touch_fw
        out += bytes(-len(out) % PAGE)
    if payload is not None:
        if payload[:8] != b"SWEETXNU":
            raise PackError("payload is not a SWEETXNU payload")
        if len(out) + PAGE > FIND_WINDOW:
            raise PackError("touch firmware too large: the probe looks for the payload within 2 MiB of _end")
        out += payload
    return out


def blob_with_trailer(body, image_id=0):
    """Pad `body` to 16 bytes and append the trailer."""
    return body + bytes(-len(body) % 16) + TRAILER + struct.pack("<Q", image_id)


def image_id(raw, stub_off):
    """ID over the raw kernel with the header's and the trailer's ID zeroed."""
    r = bytearray(raw)
    r[stub_off + HDR_OFF + 0x38:stub_off + HDR_OFF + 0x40] = bytes(8)
    r[-8:] = bytes(8)
    return struct.unpack("<Q", hashlib.sha256(bytes(r)).digest()[:8])[0]


def pack(stock, stub, stub_end, body=b"", default="fastboot", timeout=5, flags=0,
         max_raw=MAX_RAW):
    st = stock_sections(stock)
    hdr = read_header(stub)
    if stub_end % PAGE or stub_end < len(stub):
        raise PackError(f"stub _end {stub_end:#x} must be 4 KiB aligned and cover the stub")
    if default not in ITEMS:
        raise PackError(f"default must be one of {sorted(ITEMS)}")
    if not 0 <= timeout <= 60:
        raise PackError("timeout must be 0..60 s (0 = wait for a key)")
    stub_off = stub_layout(st)
    blob = blob_with_trailer(body)
    fields = HDR.pack(MAGIC, hdr["version"], HDR.size, stub_off, st["code0"], ITEMS[default],
                      timeout, flags, len(blob), stub_end, 0)
    s = bytearray(stub)
    s[HDR_OFF:HDR_OFF + HDR.size] = fields
    raw = bytearray(st["raw"])
    raw[0:4] = struct.pack("<I", branch(stub_off))
    raw += bytes(stub_off - len(raw)) + s + bytes(stub_end - len(s)) + blob
    iid = struct.pack("<Q", image_id(raw, stub_off))
    raw[stub_off + HDR_OFF + 0x38:stub_off + HDR_OFF + 0x40] = iid
    raw[-8:] = iid
    if len(raw) > max_raw:
        raise PackError(f"raw kernel {len(raw):#x} bytes would reach the DTB LK placed at "
                        f"{OBSERVED_DTB_PA:#x} (E4); limit {max_raw:#x}")
    gz = gzip.compress(bytes(raw), compresslevel=9, mtime=0)
    b = st["boot"]
    head = bytearray(stock[:PAGE])
    struct.pack_into("<I", head, 8, len(gz))
    body_img = bytes(head) + gz + bytes(-len(gz) % PAGE) + st["ramdisk"] + st["sig"]
    end = len(body_img)
    footer = st["footer"]
    info = {"stub_off": stub_off, "raw": len(raw), "kernel_size": len(gz),
            "stock_kernel_size": b["kernel_size"], "sections_end": end,
            "stock_sections_end": b["end"], "blob": len(blob)}
    if footer:
        vbmeta = stock[footer["vbmeta_offset"]:footer["vbmeta_offset"] + footer["vbmeta_size"]]
        vo = align(end, PAGE)
        if vo + len(vbmeta) > len(stock) - 64:
            raise PackError(f"image needs {vo + len(vbmeta) + 64} bytes; the partition image is {len(stock)}")
        nf = dict(footer, original_image_size=end, vbmeta_offset=vo)
        out = body_img + bytes(vo - end) + vbmeta
        out += bytes(len(stock) - 64 - len(out)) + footer_bytes(nf)
        info["stock_avb_image_size"] = footer["original_image_size"]
        info["exceeds_stock_avb_image_size"] = end > footer["original_image_size"]
    else:
        if end > len(stock):
            raise PackError(f"image needs {end} bytes; the stock image is {len(stock)}")
        out = body_img + bytes(len(stock) - end)
    assert len(out) == len(stock)
    return out, info


def verify(stock, image, stub, stub_end, body=None, max_raw=MAX_RAW):
    """Failures of `image` against `stock` (empty = matches the layout above).
    `body` (blob_body()) also checks the appended firmware/payload bytes."""
    errs = []
    st = stock_sections(stock)
    if len(image) != len(stock):
        return [f"size {len(image)} != stock {len(stock)}"]
    try:
        b = parse_boot(image)
    except PackError as e:
        return [str(e)]
    if image[:8] + image[12:PAGE] != stock[:8] + stock[12:PAGE]:
        errs.append("header page differs from stock beyond kernel_size")
    if image[b["ramdisk_off"]:b["sig_off"]] != st["ramdisk"]:
        errs.append("ramdisk section differs from stock")
    if image[b["sig_off"]:b["end"]] != st["sig"]:
        errs.append("boot signature section differs from stock")
    footer = st["footer"]
    if footer:
        try:
            f = parse_footer(image)
        except PackError as e:
            errs.append(str(e))
            f = None
        if f is None:
            errs.append("AVB footer missing or broken")
        else:
            if (f["major"], f["minor"], f["vbmeta_size"], f["reserved"]) != \
                    (footer["major"], footer["minor"], footer["vbmeta_size"], footer["reserved"]):
                errs.append("AVB footer fields changed beyond size/offset")
            if f["original_image_size"] != b["end"] or f["vbmeta_offset"] != align(b["end"], PAGE):
                errs.append("AVB footer does not describe the new sections")
            vs = footer["vbmeta_offset"]
            if image[f["vbmeta_offset"]:f["vbmeta_offset"] + f["vbmeta_size"]] != \
                    stock[vs:vs + footer["vbmeta_size"]]:
                errs.append("vbmeta blob differs from stock")
            if any(image[b["end"]:f["vbmeta_offset"]]) or \
                    any(image[f["vbmeta_offset"] + f["vbmeta_size"]:-64]):
                errs.append("non-zero bytes outside the sections, vbmeta and footer")
    elif any(image[b["end"]:]):
        errs.append("non-zero bytes after the sections")
    if image[PAGE:PAGE + 2] != b"\x1f\x8b":
        errs.append("kernel stream is not gzip")
        return errs
    try:
        raw = gunzip(image[PAGE:PAGE + b["kernel_size"]])
    except Exception as e:  # zlib.error, EOFError
        errs.append(f"kernel stream does not gunzip: {e}")
        return errs
    stub_off = stub_layout(st)
    linux = st["raw"]
    if struct.unpack_from("<I", raw, 0)[0] != branch(stub_off):
        errs.append("raw[0] is not the branch to the stub")
    if raw[4:len(linux)] != linux[4:]:
        errs.append("stock Linux Image bytes changed")
    if any(raw[len(linux):stub_off]):
        errs.append("non-zero bytes between the Linux Image and the stub")
    s = raw[stub_off:stub_off + len(stub)]
    if s[:HDR_OFF] + s[HDR_OFF + HDR.size:] != stub[:HDR_OFF] + stub[HDR_OFF + HDR.size:]:
        errs.append("stub bytes differ from the built stub")
    try:
        h = read_header(s)
    except PackError as e:
        errs.append(str(e))
        return errs
    if (h["version"], h["hdr_size"], h["stub_off"], h["orig_code0"], h["stub_end"]) != \
            (read_header(stub)["version"], HDR.size, stub_off, st["code0"], stub_end):
        errs.append("multiboot header fields wrong (version/size/stub_off/code0/_end)")
    if h["default_item"] not in ITEMS.values() or h["timeout_s"] > 60 or h["flags"] & ~3:
        errs.append("multiboot header options out of range")
    if any(raw[stub_off + len(stub):stub_off + stub_end]):
        errs.append("non-zero bytes between the stub and _end")
    start = stub_off + stub_end
    if len(raw) != start + h["blob_size"]:
        errs.append("raw kernel length does not match the header's blob_size")
    if raw[-16:-8] != TRAILER or struct.unpack("<Q", raw[-8:])[0] != h["image_id"] or \
            h["image_id"] != image_id(raw, stub_off):
        errs.append("trailer or image_id missing or wrong")
    if body is not None and raw[start:] != blob_with_trailer(body, h["image_id"]):
        errs.append("firmware/payload bytes after _end differ")
    if len(raw) > max_raw:
        errs.append(f"raw kernel {len(raw):#x} exceeds {max_raw:#x} (reaches the observed DTB)")
    return errs


# ---- host commands ----

def build(out_dir, extra=()):
    defs = dict(STUB_DEFS)
    for d in extra:
        k, _, v = d.partition("=")
        defs[k] = v or None
    flags = [f"-D{k}" if v is None else f"-D{k}={v}" for k, v in defs.items()]
    elf, binf = g54_payload.compile_link(SRC, ("entry.S", "stub.c"), "stub.ld", out_dir, "stub", flags)
    if g54_payload.symbol(elf, "mb_hdr") != HDR_OFF:
        raise PackError("mb_hdr is not at stub + 0x08")
    read_header(open(binf, "rb").read())
    return elf, binf


def load_stub(stub_dir):
    stub = open(os.path.join(stub_dir, "stub.bin"), "rb").read()
    end = g54_payload.symbol(os.path.join(stub_dir, "stub.elf"), "_end")
    return stub, end


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", default="out/mb")
    b.add_argument("-D", dest="defs", action="append", default=[],
                   help="extra or overriding C define for the included probe (e.g. LASTLOG_RING=0x...)")
    for name in ("pack", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--stock", required=True, help="verified stock boot.img (5-8-6: e0fe4010...)")
        p.add_argument("--stub", default="out/mb", help="directory with stub.bin and stub.elf")
        p.add_argument("--payload", help="SWEETXNU payload (g54_xnu_image.py writes <out>.payload)")
        p.add_argument("--touch-fw", help="local Novatek firmware blob (never committed)")
        if name == "pack":
            p.add_argument("--out", required=True)
            p.add_argument("--userdata", required=True, choices=("ios", "android"),
                           help="what userdata holds now; 'ios' disables the Android entry")
            p.add_argument("--default", default="fastboot", choices=sorted(ITEMS))
            p.add_argument("--timeout", type=int, default=5, help="seconds, 0 = wait for a key")
            p.add_argument("--recovery-passthrough", action="store_true",
                           help="skip the menu when LK booted recovery/FastbootD (hypothesis H5)")
        else:
            p.add_argument("--image", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "build":
            elf, binf = build(a.out, a.defs)
            data = open(binf, "rb").read()
            print(f"stub {binf} {len(data)} bytes _end={g54_payload.symbol(elf, '_end'):#x} sha256={sha256(data)}")
            return 0
        stock = open(a.stock, "rb").read()
        stub, stub_end = load_stub(a.stub)
        payload = open(a.payload, "rb").read() if a.payload else None
        fw = open(a.touch_fw, "rb").read() if a.touch_fw else None
        body = blob_body(payload, fw)
        if a.cmd == "pack":
            if a.default == "ios" and payload is None:
                raise PackError("--default ios needs --payload")
            flags = (FLAG_RECOVERY_PASS if a.recovery_passthrough else 0) | \
                    (FLAG_ANDROID if a.userdata == "android" else 0)
            img, info = pack(stock, stub, stub_end, body, a.default, a.timeout, flags)
            errs = verify(stock, img, stub, stub_end, body)
            if errs:
                raise PackError("; ".join(errs))
            with open(a.out, "wb") as f:
                f.write(img)
            print(f"packed {a.out} stock_sha256={sha256(stock)} image_sha256={sha256(img)}")
            print(f"stub_sha256={sha256(stub)} payload={len(payload) if payload else 0} "
                  f"touch_fw={len(fw) if fw else 0} flags={flags} {info}")
            if info.get("exceeds_stock_avb_image_size"):
                print("note: the sections now exceed the stock AVB image_size; LK must load the "
                      "image by its header (hypothesis H1, docs/multiboot-feasibility.md)")
            return 0
        errs = verify(stock, open(a.image, "rb").read(), stub, stub_end, body)
        for e in errs:
            print("FAIL", e)
        if errs:
            return 1
        print("OK image = stock boot.img + Linux Image + multiboot stub" +
              (" + payload" if payload else ""))
        return 0
    except PackError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
