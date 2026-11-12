"""Tests for g54_payload.py on synthetic boot images (no firmware needed)."""
import gzip
import os
import random
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g54_payload as gp  # noqa: E402


def fake_raw_kernel(size=0x300000, seed=1):
    rnd = random.Random(seed)
    # Mix of compressible and incompressible data, like a real Image.
    raw = bytearray()
    while len(raw) < size:
        raw += bytes(rnd.getrandbits(8) for _ in range(256)) + b"\x00" * 768
    raw = raw[:size]
    raw[0x38:0x3C] = gp.ARM64_MAGIC
    return bytes(raw)


def fake_v4(raw, header_version=4, tail=b"RAMDISK" * 100 + b"AVBf" + b"\x01" * 60):
    gz = gzip.compress(raw, compresslevel=9, mtime=0)
    hdr = bytearray(gp.PAGE)
    hdr[:8] = b"ANDROID!"
    struct.pack_into("<II", hdr, 8, len(gz), 700)
    struct.pack_into("<I", hdr, 40, header_version)
    body = gz + bytes(-len(gz) % gp.PAGE)
    return bytes(hdr) + body + tail


class PackTest(unittest.TestCase):
    def setUp(self):
        self.raw = fake_raw_kernel()
        self.stock = fake_v4(self.raw)
        self.payload = b"\x1f\x20\x03\xd5" * 64  # nops

    def test_pack_keeps_layout_and_inserts_probe(self):
        img, info = gp.pack(self.stock, self.payload)
        self.assertEqual(len(img), len(self.stock))
        self.assertEqual(gp.verify(self.stock, img, self.payload), [])
        ks = info["kernel_size"]
        raw = gp.gunzip(img[gp.PAGE:gp.PAGE + ks])
        self.assertEqual(struct.unpack_from("<I", raw, 0)[0], 0x14000400)
        self.assertEqual(raw[gp.PAYLOAD_OFF:gp.PAYLOAD_OFF + len(self.payload)], self.payload)

    def test_verify_detects_tampering(self):
        img, _ = gp.pack(self.stock, self.payload)
        bad = bytearray(img)
        bad[-10] ^= 0xFF  # AVB footer region
        self.assertTrue(any("after the kernel" in e for e in gp.verify(self.stock, bytes(bad), self.payload)))
        self.assertTrue(gp.verify(self.stock, img, self.payload[:-4] + b"\x00\x00\x00\x00"))

    def test_rejects_non_v4_and_missing_arm64_header(self):
        with self.assertRaises(gp.PackError):
            gp.pack(fake_v4(self.raw, header_version=2), self.payload)
        raw = bytearray(self.raw)
        raw[0x38:0x3C] = b"XXXX"
        with self.assertRaises(gp.PackError):
            gp.pack(fake_v4(bytes(raw)), self.payload)
        with self.assertRaises(gp.PackError):
            gp.pack(b"NOTABOOT" + self.stock[8:], self.payload)

    def test_fixed_size_gzip_is_exact_and_valid(self):
        raw = fake_raw_kernel(0x200000, seed=7)
        target = len(gzip.compress(raw, 9)) + 1000
        gz, out_raw, zeroed = gp.fixed_size_gzip(raw, target)
        self.assertEqual(len(gz), target)
        self.assertEqual(gp.gunzip(gz), out_raw)
        self.assertEqual(zeroed, 0)

    def test_fixed_size_gzip_shrinks_by_zeroing_tail(self):
        raw = fake_raw_kernel(0x300000, seed=9)
        target = len(gzip.compress(raw, 9)) - 20000
        gz, out_raw, zeroed = gp.fixed_size_gzip(raw, target)
        self.assertEqual(len(gz), target)
        self.assertGreater(zeroed, 0)
        self.assertEqual(out_raw[:gp.PAYLOAD_OFF + 0x100000], raw[:gp.PAYLOAD_OFF + 0x100000])


if __name__ == "__main__":
    unittest.main()
