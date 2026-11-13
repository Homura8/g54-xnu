"""Tests for read-only multiboot discovery & offline analyzers."""
from pathlib import Path
import gzip
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import multiboot_audit as ma  # noqa: E402


class MultibootAuditTests(unittest.TestCase):
    def test_fastboot_allowlist_blocks_writes(self):
        self.assertTrue(ma.allowed_fastboot(["devices"]))
        self.assertTrue(ma.allowed_fastboot(["getvar", "all"]))
        self.assertTrue(ma.allowed_fastboot(["getvar", "partition-size:boot_a"]))
        for bad in (
            ["flash", "boot_a", "x.img"],
            ["erase", "userdata"],
            ["set_active", "b"],
            ["reboot"],
            ["boot", "x.img"],
            ["oem", "unlock"],
        ):
            self.assertFalse(ma.allowed_fastboot(bad), f"must reject {bad}")

    def test_inspect_boot_image_v4(self):
        raw = bytearray(0x2000)
        struct.pack_into("<IIQQ", raw, 0, 0x91005A4D, 0, 0, 0x10000)
        raw[0x38:0x3C] = b"ARM\x64"
        gz = gzip.compress(bytes(raw), mtime=0)
        hdr = bytearray(4096)
        hdr[:8] = b"ANDROID!"
        struct.pack_into("<4I", hdr, 8, len(gz), 64, 0, 1584)
        struct.pack_into("<I", hdr, 40, 4)
        struct.pack_into("<I", hdr, 1580, 4096)
        img = bytes(hdr) + gz + bytes(-len(gz) % 4096) + b"R" * 4096 + b"S" * 4096
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "boot.img"
            p.write_bytes(img)
            info = ma.inspect_boot_image(p)
        self.assertEqual(info["header_version"], 4)
        self.assertTrue(info["arm64_image"]["magic_ok"])
        self.assertEqual(info["arm64_image"]["code0"], "0x91005a4d")
        self.assertEqual(info["kernel_size_raw"], 0x2000)

    def test_userdata_split_preserves_front_ios_region(self):
        plan = ma.plan_userdata_split(0x1BEB7F8000, ios_gib=16, ios_boot_mib=32)
        self.assertEqual(plan["ios_root"]["rel_first_block"], 0)
        self.assertEqual(plan["ios_root"]["bytes"], 16 * 1024 ** 3)
        self.assertEqual(plan["ios_boot"]["bytes"], 32 * 1024 ** 2)
        self.assertEqual(
            plan["ios_root"]["blocks"] + plan["ios_boot"]["blocks"] + plan["new_userdata"]["blocks"],
            plan["original_userdata_blocks"],
        )

    def test_inspect_gpt_parses_entries(self):
        # Construct minimal 4K-LBA protective MBR + GPT header + 2 entries
        buf = bytearray(4096 * 4)
        hdr_off = 4096
        struct.pack_into(
            "<8sIIIIQQQQ16sQIII",
            buf,
            hdr_off,
            b"EFI PART", 0x00010000, 92, 0, 0, 1, 999, 34, 966, b"\x11" * 16, 2, 4, 128, 0,
        )
        ent0 = 4096 * 2
        buf[ent0 : ent0 + 16] = b"\x22" * 16
        struct.pack_into("<QQQ", buf, ent0 + 32, 100, 199, 0)
        buf[ent0 + 56 : ent0 + 56 + len("userdata") * 2] = "userdata".encode("utf-16-le")
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "pgpt.bin"
            p.write_bytes(bytes(buf))
            gpt = ma.inspect_gpt(p)
        self.assertEqual(gpt["used_entries"], 1)
        self.assertEqual(gpt["free_entries"], 3)
        self.assertEqual(gpt["partitions"][0]["name"], "userdata")
        self.assertEqual(gpt["partitions"][0]["blocks"], 100)

    def test_inspect_vbmeta_hash_and_chain_descriptors(self):
        def desc(tag, body):
            body += bytes(-len(body) % 8)
            return struct.pack(">QQ", tag, len(body)) + body
        name = b"boot"
        hashd = struct.pack(">Q", 0x2345000) + b"sha256".ljust(32, b"\0")
        hashd += struct.pack(">IIII", len(name), 32, 32, 0) + bytes(60) + name + b"S" * 32 + b"D" * 32
        chaind = struct.pack(">IIII", 1, len(b"vbmeta_system"), 8, 0) + bytes(60) + b"vbmeta_system" + b"K" * 8
        aux = desc(2, hashd) + desc(4, chaind)
        hdr = bytearray(256)
        struct.pack_into(">4sIIQQIQQQQQQQQQQQII", hdr, 0, b"AVB0", 1, 0, 0, len(aux), 0,
                         0, 0, 0, 0, 0, 0, 0, 0, 0, len(aux), 0, 0, 0)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "vbmeta.img"
            p.write_bytes(bytes(hdr) + aux)
            info = ma.inspect_vbmeta(p)
        self.assertEqual(info["hash_descriptors"][0]["partition"], "boot")
        self.assertEqual(info["hash_descriptors"][0]["image_size"], 0x2345000)
        self.assertEqual(info["hash_descriptors"][0]["alg"], "sha256")
        self.assertEqual(info["chains"][0]["partition"], "vbmeta_system")
        self.assertEqual(info["chains"][0]["rollback_index_location"], 1)


if __name__ == "__main__":
    unittest.main()
