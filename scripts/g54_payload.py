#!/usr/bin/env python3
"""Build the G54 G1 probe and pack it into a stock boot image (header v4).

  python3 scripts/g54_payload.py build  [--out out/g1]
  python3 scripts/g54_payload.py pack   --stock boot.img --payload probe.bin --out probe-boot.img
  python3 scripts/g54_payload.py verify --stock boot.img --image probe-boot.img --payload probe.bin

Recipe (ruby-ios-bringup docs/en/03-boot-chain.md, proven on MediaTek LK):
keep the stock image byte-for-byte except the gzip kernel stream, keep the
stream at exactly the stock ``kernel_size`` (FEXTRA padding), keep the arm64
Image header, branch from raw[0] to the probe at raw+0x1000. Header,
ramdisk, boot signature and AVB footer stay untouched, so LK sees the stock
layout. Ruby's own packer reads a v2 page-size field that is reserved in v4,
hence this implementation.

This script only writes files on the host. It never talks to a phone.
"""
import argparse
import hashlib
import os
import shutil
import struct
import subprocess
import sys
import zlib

PAGE = 4096                      # fixed for boot header v3/v4
PAYLOAD_OFF = 0x1000
BRANCH = 0x14000000 | (PAYLOAD_OFF // 4)   # b #0x1000
ARM64_MAGIC = b"ARM\x64"
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "payload", "g1")


class PackError(Exception):
    pass


def parse_v4(img):
    if img[:8] != b"ANDROID!":
        raise PackError("not an Android boot image")
    kernel_size, ramdisk_size = struct.unpack_from("<II", img, 8)
    header_version = struct.unpack_from("<I", img, 40)[0]
    if header_version not in (3, 4):
        raise PackError(f"boot header v{header_version}; only v3/v4 supported")
    if PAGE + kernel_size > len(img):
        raise PackError("kernel extends past end of image")
    return {"header_version": header_version, "kernel_size": kernel_size,
            "ramdisk_size": ramdisk_size}


def gunzip(stream):
    return zlib.decompress(stream, 16 + zlib.MAX_WBITS)


def fixed_size_gzip(raw, size):
    """gzip `raw` into exactly `size` bytes using FEXTRA padding.

    If plain deflate is too large, zero the raw kernel from the end
    (that code is never run: the probe owns the CPU) until it fits.
    """
    raw = bytearray(raw)
    tail = len(raw)
    step = 0x10000
    while True:
        co = zlib.compressobj(9, zlib.DEFLATED, -15, 9)
        deflate = co.compress(bytes(raw)) + co.flush()
        extra = size - 20 - len(deflate)
        if 0 <= extra <= 0xFFFF:
            break
        if extra > 0xFFFF:
            raise PackError(f"deflate too small to pad ({len(deflate)} for {size})")
        if tail - step <= PAYLOAD_OFF + 0x100000:
            raise PackError("cannot shrink kernel stream to the stock size")
        tail -= step
        raw[tail:] = bytes(len(raw) - tail)
    header = b"\x1f\x8b\x08\x04" + b"\x00" * 4 + b"\x02\x03" + struct.pack("<H", extra)
    footer = struct.pack("<II", zlib.crc32(raw) & 0xFFFFFFFF, len(raw) & 0xFFFFFFFF)
    gz = header + bytes(extra) + deflate + footer
    assert len(gz) == size
    return gz, bytes(raw), len(raw) - tail


def pack(stock, payload):
    info = parse_v4(stock)
    ks = info["kernel_size"]
    raw = bytearray(gunzip(stock[PAGE:PAGE + ks]))
    if raw[0x38:0x3C] != ARM64_MAGIC:
        raise PackError("stock kernel lacks the arm64 Image header")
    if PAYLOAD_OFF + len(payload) > len(raw) // 2:
        raise PackError("payload too large")
    raw[0:4] = struct.pack("<I", BRANCH)
    raw[PAYLOAD_OFF:PAYLOAD_OFF + len(payload)] = payload
    gz, final_raw, zeroed = fixed_size_gzip(raw, ks)
    out = bytearray(stock)
    out[PAGE:PAGE + ks] = gz
    return bytes(out), {"kernel_size": ks, "raw": len(final_raw), "zeroed_tail": zeroed}


def verify(stock, image, payload):
    """Return a list of failures; empty means the image matches the recipe."""
    errs = []
    if len(stock) != len(image):
        errs.append(f"size {len(image)} != stock {len(stock)}")
        return errs
    info = parse_v4(stock)
    ks = info["kernel_size"]
    if image[:PAGE] != stock[:PAGE]:
        errs.append("header page differs from stock")
    if image[PAGE + ks:] != stock[PAGE + ks:]:
        errs.append("bytes after the kernel stream differ from stock")
    try:
        raw = gunzip(image[PAGE:PAGE + ks])
    except zlib.error as e:
        errs.append(f"kernel stream does not gunzip: {e}")
        return errs
    stock_raw_len = len(gunzip(stock[PAGE:PAGE + ks]))
    if len(raw) != stock_raw_len:
        errs.append("decompressed kernel size differs from stock")
    if struct.unpack_from("<I", raw, 0)[0] != BRANCH:
        errs.append("raw[0] is not the branch to the probe")
    if raw[0x38:0x3C] != ARM64_MAGIC:
        errs.append("arm64 Image magic missing")
    if raw[PAYLOAD_OFF:PAYLOAD_OFF + len(payload)] != payload:
        errs.append("payload bytes not at raw+0x1000")
    if image[PAGE:PAGE + 4] != b"\x1f\x8b\x08\x04":
        errs.append("gzip header is not FEXTRA")
    return errs


def tool(name):
    for cand in (f"/opt/homebrew/opt/llvm/bin/{name}", shutil.which(name)):
        if cand and os.path.exists(cand):
            return cand
    raise PackError(f"{name} not found (brew install llvm lld)")


def build(out_dir, phase1=None, phase2=None):
    os.makedirs(out_dir, exist_ok=True)
    defs = []
    if phase1 is not None:
        defs.append(f"-DPHASE1_S={int(phase1)}")
    if phase2 is not None:
        defs.append(f"-DPHASE2_S={int(phase2)}")
    cflags = ["--target=aarch64-none-elf", "-ffreestanding", "-fno-builtin",
              "-nostdlib", "-mstrict-align", "-mgeneral-regs-only", "-fno-pic",
              "-fno-stack-protector", "-fno-asynchronous-unwind-tables",
              "-mcmodel=small", "-O2", "-Wall", "-Werror", *defs]
    objs = []
    for src in ("entry.S", "probe.c"):
        obj = os.path.join(out_dir, src + ".o")
        subprocess.run(["clang", *cflags, "-c", os.path.join(SRC, src), "-o", obj], check=True)
        objs.append(obj)
    elf = os.path.join(out_dir, "probe.elf")
    subprocess.run([tool("ld.lld"), "-T", os.path.join(SRC, "probe.ld"), "-static",
                    "--no-dynamic-linker", "-o", elf, *objs], check=True)
    # Position independence: only PC-relative relocations may exist.
    rel = subprocess.run([tool("llvm-objdump"), "-r", *objs], check=True,
                         capture_output=True, text=True).stdout
    allowed = ("R_AARCH64_ADR_PREL_PG_HI21", "R_AARCH64_ADD_ABS_LO12_NC",
               "R_AARCH64_CALL26", "R_AARCH64_JUMP26", "R_AARCH64_ADR_PREL_LO21",
               "R_AARCH64_LDST64_ABS_LO12_NC", "R_AARCH64_LDST32_ABS_LO12_NC",
               "R_AARCH64_CONDBR19")
    for line in rel.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].startswith("R_AARCH64") and parts[1] not in allowed:
            raise PackError(f"non PC-relative relocation: {line.strip()}")
    binf = os.path.join(out_dir, "probe.bin")
    subprocess.run([tool("llvm-objcopy"), "-O", "binary", elf, binf], check=True)
    return binf


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", default="out/g1")
    b.add_argument("--phase1", type=int)
    b.add_argument("--phase2", type=int)
    p = sub.add_parser("pack")
    p.add_argument("--stock", required=True)
    p.add_argument("--payload", required=True)
    p.add_argument("--out", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--stock", required=True)
    v.add_argument("--image", required=True)
    v.add_argument("--payload", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "build":
            binf = build(a.out, a.phase1, a.phase2)
            data = open(binf, "rb").read()
            print(f"probe {binf} {len(data)} bytes sha256={sha256(data)}")
        elif a.cmd == "pack":
            stock = open(a.stock, "rb").read()
            payload = open(a.payload, "rb").read()
            img, info = pack(stock, payload)
            errs = verify(stock, img, payload)
            if errs:
                raise PackError("; ".join(errs))
            with open(a.out, "wb") as f:
                f.write(img)
            print(f"packed {a.out} stock_sha256={sha256(stock)} image_sha256={sha256(img)} {info}")
        else:
            errs = verify(open(a.stock, "rb").read(), open(a.image, "rb").read(),
                          open(a.payload, "rb").read())
            for e in errs:
                print("FAIL", e)
            if errs:
                return 1
            print("OK image matches the stock layout and contains the probe")
    except PackError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
