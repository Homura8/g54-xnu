"""Tests for g54_multiboot.py on synthetic boot images (no firmware needed)."""
import gzip
import os
import random
import shutil
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g54_multiboot as mb  # noqa: E402
from g54_payload import PackError, gunzip  # noqa: E402

PAGE = mb.PAGE
CODE0 = 0xFA405A4D          # "MZ" + ccmp, as in an EFI-stub arm64 Image


def fake_linux(size=0x180000, image_size=0x200000, seed=3):
    rnd = random.Random(seed)
    raw = bytearray()
    while len(raw) < size:
        raw += bytes(rnd.getrandbits(8) for _ in range(256)) + b"\x00" * 256
    raw = raw[:size]
    struct.pack_into("<IIQQ", raw, 0, CODE0, 0x14000010, 0, image_size)
    raw[0x38:0x3C] = b"ARM\x64"
    return bytes(raw)


def fake_stock(raw=None, partition=0x800000, footer=True, sig=True):
    raw = raw or fake_linux()
    gz = gzip.compress(raw, 9, mtime=0)
    hdr = bytearray(PAGE)
    hdr[:8] = b"ANDROID!"
    ramdisk = b"RAMDISK!" * 300 + b"\x07"
    signature = b"SIG" * 100 if sig else b""
    struct.pack_into("<4I", hdr, 8, len(gz), len(ramdisk), 0x0F000000, 1584)
    struct.pack_into("<I", hdr, 40, 4)
    struct.pack_into("<I", hdr, 1580, len(signature))
    hdr[44:52] = b"cmdline!"
    img = bytes(hdr) + gz + bytes(-len(gz) % PAGE)
    img += ramdisk + bytes(-len(ramdisk) % PAGE)
    img += signature + bytes(-len(signature) % PAGE)
    if not footer:
        return img + bytes(partition - len(img))
    end = len(img)
    vbmeta = b"AVB0" + bytes(range(252)) + b"V" * 700
    img += vbmeta
    img += bytes(partition - 64 - len(img))
    img += mb.AVB_FOOTER.pack(b"AVBf", 1, 0, end, end, len(vbmeta), bytes(28))
    return img


def fake_stub(size=0x900):
    stub = bytearray(b"\x1f\x20\x03\xd5" * (size // 4))      # nops
    stub[0:4] = struct.pack("<I", 0x14000000 | (0x48 // 4))  # b over the header
    mb.HDR.pack_into(stub, mb.HDR_OFF, mb.MAGIC, 1, 64, 0, 0, 2, 5, 0, 0, 0, 0)
    return bytes(stub)


def fake_payload(n=0x20000, seed=5):
    rnd = random.Random(seed)                                  # incompressible, like a kernel
    return b"SWEETXNU" + struct.pack("<II", 1, 1) + bytes(rnd.getrandbits(8) for _ in range(n))


def find_like_probe(raw, frm, tag):
    """probe.c find_fw/find_payload: 4 KiB steps within 2 MiB after _end."""
    for a in range(align(frm, 0x1000), frm + 0x200000, 0x1000):
        if raw[a:a + 8] == tag:
            return a
    return None


def align(n, a):
    return (n + a - 1) // a * a


def raw_of(img):
    b = mb.parse_boot(img)
    return gunzip(img[PAGE:PAGE + b["kernel_size"]])


class PackTest(unittest.TestCase):
    def setUp(self):
        self.linux = fake_linux()
        self.stock = fake_stock(self.linux)
        self.stub = fake_stub()
        self.end = 0x1000
        self.fw = b"FWFW" * 300
        self.payload = fake_payload()
        self.body = mb.blob_body(self.payload, self.fw)

    def pack(self, **kw):
        return mb.pack(self.stock, self.stub, self.end, self.body, **kw)

    def test_pack_verifies_and_keeps_stock_sections(self):
        img, info = self.pack(default="ios", timeout=7, flags=mb.FLAG_ANDROID)
        self.assertEqual(len(img), len(self.stock))
        self.assertEqual(mb.verify(self.stock, img, self.stub, self.end, self.body), [])
        sb, ib = mb.parse_boot(self.stock), mb.parse_boot(img)
        self.assertEqual(img[ib["ramdisk_off"]:ib["end"]], self.stock[sb["ramdisk_off"]:sb["end"]])
        self.assertEqual(img[12:PAGE], self.stock[12:PAGE])
        self.assertGreater(ib["kernel_size"], sb["kernel_size"])
        self.assertTrue(info["exceeds_stock_avb_image_size"])

    def test_raw_layout(self):
        img, info = self.pack(default="android", flags=mb.FLAG_ANDROID)
        raw = raw_of(img)
        off = info["stub_off"]
        self.assertEqual(off, 0x200000)                       # past image_size, 64 KiB aligned
        self.assertEqual(struct.unpack_from("<I", raw, 0)[0], 0x14000000 | off // 4)
        self.assertEqual(raw[4:len(self.linux)], self.linux[4:])
        h = mb.read_header(raw[off:off + len(self.stub)])
        self.assertEqual((h["stub_off"], h["orig_code0"], h["default_item"], h["timeout_s"], h["flags"],
                          h["stub_end"]), (off, CODE0, 1, 5, mb.FLAG_ANDROID, self.end))
        self.assertEqual(len(raw), off + self.end + h["blob_size"])
        self.assertEqual(raw[-16:-8], mb.TRAILER)
        self.assertEqual(struct.unpack("<Q", raw[-8:])[0], h["image_id"])
        self.assertEqual(h["image_id"], mb.image_id(raw, off))
        self.assertNotEqual(h["image_id"], 0)
        start = off + self.end
        self.assertEqual(find_like_probe(raw, start, b"NVTFWBIN"), start)
        pl = find_like_probe(raw, start, b"SWEETXNU")
        self.assertEqual(raw[pl:pl + len(self.payload)], self.payload)
        self.assertEqual(struct.unpack_from("<I", raw, start + 8)[0], len(self.fw))

    def test_footer_moves_with_vbmeta(self):
        img, _ = self.pack()
        f, sf = mb.parse_footer(img), mb.parse_footer(self.stock)
        b = mb.parse_boot(img)
        self.assertEqual(f["original_image_size"], b["end"])
        self.assertEqual(f["vbmeta_offset"], b["end"])
        self.assertEqual(img[f["vbmeta_offset"]:f["vbmeta_offset"] + f["vbmeta_size"]],
                         self.stock[sf["vbmeta_offset"]:sf["vbmeta_offset"] + sf["vbmeta_size"]])

    def test_without_footer_or_payload(self):
        stock = fake_stock(self.linux, footer=False, sig=False)
        img, info = mb.pack(stock, self.stub, self.end)
        self.assertEqual(mb.verify(stock, img, self.stub, self.end, b""), [])
        self.assertNotIn("exceeds_stock_avb_image_size", info)
        self.assertEqual(info["blob"], 16)                    # trailer only

    def test_verify_detects_tampering(self):
        img, _ = self.pack()
        b = mb.parse_boot(img)
        f = mb.parse_footer(img)

        def flip(off, why):
            bad = bytearray(img)
            bad[off] ^= 1
            errs = mb.verify(self.stock, bytes(bad), self.stub, self.end, self.body)
            self.assertTrue(any(why in e for e in errs), f"{why}: {errs}")

        flip(b["ramdisk_off"] + 5, "ramdisk")
        flip(b["sig_off"] + 1, "signature")
        flip(44, "header page")
        flip(f["vbmeta_offset"] + 10, "vbmeta")
        flip(len(img) - 100, "outside the sections")
        flip(len(img) - 40, "footer")
        other = bytearray(self.stub)
        other[0x200] ^= 1
        self.assertTrue(any("stub bytes" in e for e in
                            mb.verify(self.stock, img, bytes(other), self.end, self.body)))
        self.assertTrue(any("payload" in e for e in
                            mb.verify(self.stock, img, self.stub, self.end, mb.blob_body(self.payload))))

    def test_verify_detects_kernel_changes(self):
        def repack(mutate):
            img, _ = self.pack()
            b = mb.parse_boot(img)
            raw = bytearray(raw_of(img))
            mutate(raw)
            gz = gzip.compress(bytes(raw), 9, mtime=0)
            self.assertLessEqual(len(gz), b["ramdisk_off"] - PAGE)
            out = bytearray(img)
            struct.pack_into("<I", out, 8, len(gz))
            out[PAGE:b["ramdisk_off"]] = gz + bytes(b["ramdisk_off"] - PAGE - len(gz))
            return mb.verify(self.stock, bytes(out), self.stub, self.end, self.body)

        def code0(raw):
            raw[0:4] = b"\x00\x00\x00\x14"
        self.assertTrue(any("branch" in e for e in repack(code0)))
        self.assertTrue(any("Linux" in e for e in repack(lambda r: r.__setitem__(0x1000, r[0x1000] ^ 1))))
        self.assertTrue(any("trailer" in e for e in repack(lambda r: r.__setitem__(-1, r[-1] ^ 1))))

        def wrong_code0(raw):
            struct.pack_into("<I", raw, 0x200000 + mb.HDR_OFF + 24, 0x12345678)
        self.assertTrue(any("header fields" in e for e in repack(wrong_code0)))

    def test_limits(self):
        with self.assertRaises(PackError):
            self.pack(max_raw=0x200000)                       # would reach the DTB
        tight = mb.parse_boot(self.stock)["end"] + 0x2000         # stock fits, the payload does not
        with self.assertRaises(PackError):
            mb.pack(fake_stock(self.linux, partition=tight), self.stub, self.end, self.body)
        with self.assertRaises(PackError):
            self.pack(default="linux")
        with self.assertRaises(PackError):
            self.pack(timeout=61)
        with self.assertRaises(PackError):
            mb.pack(self.stock, self.stub, 0x800, self.body)  # _end inside the stub
        with self.assertRaises(PackError):
            mb.pack(self.stock, b"\x00" * 0x100, self.end)    # no header
        with self.assertRaises(PackError):
            mb.blob_body(b"NOTSWEET" + bytes(100))
        with self.assertRaises(PackError):
            mb.blob_body(self.payload, b"F" * 0x200000)       # payload beyond the probe's window

    def test_refuses_odd_stock(self):
        img, _ = self.pack()
        with self.assertRaises(PackError):                    # already multiboot
            mb.pack(img, self.stub, self.end)
        bad = bytearray(self.stock)
        bad[mb.parse_boot(self.stock)["end"] + 0x2000] = 1    # data between vbmeta and footer
        with self.assertRaises(PackError):
            mb.pack(bytes(bad), self.stub, self.end)
        raw = bytearray(self.linux)
        raw[0x38:0x3C] = b"XXXX"
        with self.assertRaises(PackError):
            mb.pack(fake_stock(bytes(raw)), self.stub, self.end)

    def test_deterministic(self):
        self.assertEqual(self.pack()[0], self.pack()[0])


TOOLS = all(shutil.which(t) for t in ("clang", "ld.lld", "llvm-objcopy", "llvm-objdump", "llvm-nm"))


@unittest.skipUnless(TOOLS, "needs clang, ld.lld and llvm tools")
class BuildTest(unittest.TestCase):
    def test_stub_builds_position_independent_with_header(self):
        with tempfile.TemporaryDirectory() as td:
            elf, binf = mb.build(td)
            stub, end = mb.load_stub(td)
            h = mb.read_header(stub)
            self.assertEqual((h["version"], h["hdr_size"]), (1, 64))
            self.assertEqual(end % 0x1000, 0)
            self.assertGreaterEqual(end, len(stub))
            stock = fake_stock()
            img, _ = mb.pack(stock, stub, end, mb.blob_body(fake_payload()), default="ios")
            self.assertEqual(mb.verify(stock, img, stub, end, mb.blob_body(fake_payload())), [])

    def test_memset_from_an_initialiser_is_rejected(self):
        import g54_payload as gp
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "x.c"), "w") as f:      # sink() in another object
                f.write("void sink(char *);\nvoid f(void) { char a[512] = {0}; sink(a); }\n")
            with open(os.path.join(td, "y.c"), "w") as f:
                f.write("void sink(char *p);\nvoid sink(char *p) { (void)p; }\n")
            with open(os.path.join(td, "x.ld"), "w") as f:
                f.write("SECTIONS { .text : { *(.text*) } }\n")
            with self.assertRaisesRegex(PackError, "memset"):
                gp.compile_link(td, ("x.c", "y.c"), "x.ld", os.path.join(td, "o"), "x")


if __name__ == "__main__":
    unittest.main()
