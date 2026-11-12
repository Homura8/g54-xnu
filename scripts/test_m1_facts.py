import json
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import m1_facts as m  # noqa: E402


def fdt(nodes: dict[str, dict[str, bytes]]) -> bytes:
    """Minimal FDT v17 writer for tests: {path: {prop: value}} in path order."""
    strings, offsets, body = b"", {}, b""

    def name_offset(name):
        nonlocal strings
        if name not in offsets:
            offsets[name] = len(strings)
            strings += name.encode() + b"\0"
        return offsets[name]

    def pad(data):
        return data + b"\0" * (-len(data) % 4)

    open_stack = []
    for path in sorted(nodes, key=lambda p: (p.count("/") if p != "/" else 0, p)):
        parts = [] if path == "/" else path.strip("/").split("/")
        while open_stack and open_stack != parts[:len(open_stack)]:
            body += struct.pack(">I", 2)
            open_stack.pop()
        for depth in range(len(open_stack), len(parts) + (1 if path == "/" else 0)):
            label = "" if path == "/" else parts[depth]
            body += struct.pack(">I", 1) + pad(label.encode() + b"\0")
            if path != "/":
                open_stack.append(parts[depth])
        for prop, value in nodes[path].items():
            body += struct.pack(">III", 3, len(value), name_offset(prop)) + pad(value)
    body += struct.pack(">I", 2) * (len(open_stack) + 1) + struct.pack(">I", 9)
    header_size, rsvmap = 40, b"\0" * 16
    struct_off = header_size + len(rsvmap)
    strings_off = struct_off + len(body)
    total = strings_off + len(strings)
    header = struct.pack(">10I", 0xD00DFEED, total, struct_off, strings_off, header_size, 17, 16, 0,
                         len(strings), len(body))
    return header + rsvmap + body + strings


DTB = fdt({
    "/": {"compatible": b"motorola,test\0mediatek,mt6855\0", "model": b"Test phone\0"},
    "/cpus/cpu@0": {"compatible": b"arm,cortex-a55\0", "reg": struct.pack(">I", 0)},
    "/cpus/cpu@600": {"compatible": b"arm,cortex-a78\0", "reg": struct.pack(">I", 0x600)},
    "/memory": {"reg": struct.pack(">4I", 0, 0x40000000, 0, 0x80000000)},
    "/reserved-memory/framebuffer@7c000000": {"reg": struct.pack(">4I", 0, 0x7C000000, 0, 0x2000000)},
    "/interrupt-controller@c000000": {"compatible": b"arm,gic-v3\0", "interrupt-controller": b""},
    "/soc/ufshci@11270000": {"compatible": b"mediatek,mt6855-ufshci\0"},
    "/soc/serial@11001000": {"compatible": b"mediatek,mt6577-uart\0"},
})


def boot_v2(kernel=b"\x1f\x8b" + b"k" * 100, ramdisk=b"070701" + b"r" * 50, dtb=DTB, page=2048) -> bytes:
    header = bytearray(page)
    header[0:8] = b"ANDROID!"
    struct.pack_into("<8I", header, 8, len(kernel), 0x40080000, len(ramdisk), 0x51100000, 0, 0, 0x47c80000, page)
    struct.pack_into("<I", header, 40, 2)
    header[64:76] = b"console=ttyS"
    struct.pack_into("<IQI", header, 1632, 0, 0, 1660)
    struct.pack_into("<IQ", header, 1648, len(dtb), 0x47c80000)
    image = bytes(header)
    for chunk in (kernel, ramdisk, dtb):
        image += chunk + b"\0" * (-len(chunk) % page)
    return image


class BootImageTests(unittest.TestCase):
    def test_header_v2_layout_and_dtb(self):
        result = m.analyse_bootimg(boot_v2())
        self.assertEqual((result["kind"], result["header_version"], result["page_size"]), ("boot", 2, 2048))
        names = [(s["name"], s["format"], s["inside_file"]) for s in result["sections"]]
        self.assertIn(("kernel", "gzip", True), names)
        self.assertIn(("dtb", "dtb", True), names)
        self.assertEqual(result["kernel_addr"], "0x40080000")
        dtb = [s for s in result["sections"] if s["name"] == "dtb"][0]
        blob = boot_v2()[dtb["offset"]:dtb["offset"] + dtb["size"]]
        self.assertEqual(m.fdt_blobs(blob)[0], DTB)

    def test_header_v4_and_vendor_boot_v4(self):
        boot = bytearray(4096)
        boot[0:8] = b"ANDROID!"
        struct.pack_into("<4I", boot, 8, 64, 0, 0, 1584)
        struct.pack_into("<I", boot, 40, 4)
        boot = bytes(boot) + b"\0" * 0x38 + b"ARM\x64" + b"\0" * 4
        result = m.analyse_bootimg(boot)
        self.assertEqual((result["header_version"], result["sections"][0]["format"]), (4, "arm64-image"))
        vendor = bytearray(4096)
        vendor[0:8] = b"VNDRBOOT"
        struct.pack_into("<5I", vendor, 8, 4, 4096, 0x40000000, 0x51100000, 4096)
        struct.pack_into("<IIQ", vendor, 2096, 2128, len(DTB), 0x47c80000)
        struct.pack_into("<4I", vendor, 2112, 108, 1, 108, 0)
        vendor = bytes(vendor) + b"070701".ljust(4096, b"\0") + DTB
        result = m.analyse_bootimg(vendor)
        self.assertEqual((result["kind"], result["header_version"]), ("vendor_boot", 4))
        self.assertEqual([s["format"] for s in result["sections"][:2]], ["cpio", "dtb"])

    def test_avb_footer_and_garbage(self):
        image = boot_v2()
        footer = b"AVBf" + struct.pack(">IIQQQ", 1, 0, len(image), 4096, 2048) + b"\0" * 28
        self.assertEqual(m.analyse_bootimg(image + footer)["avb_footer"]["original_image_size"], len(image))
        self.assertEqual(m.analyse_bootimg(b"not an image")["kind"], "unknown")

    def test_dtb_summary(self):
        summary = m.summarise_dtb(DTB)
        self.assertEqual(summary["compatible"], ["motorola,test", "mediatek,mt6855"])
        self.assertEqual([c["compatible"][0] for c in summary["cpus"]], ["arm,cortex-a55", "arm,cortex-a78"])
        self.assertEqual(summary["reserved_memory"][0]["reg"], ["0x0", "0x7c000000", "0x0", "0x2000000"])
        self.assertEqual(summary["interrupt_controllers"][0]["compatible"], ["arm,gic-v3"])
        self.assertTrue(summary["ufs"] and summary["uarts"])

    def test_concatenated_and_prefixed_dtbs(self):
        blob = b"\x88\x16\x88\x58" + b"\0" * 508 + DTB + b"\0" * 8 + DTB
        self.assertEqual(len(m.fdt_blobs(blob)), 2)


class SafetyTests(unittest.TestCase):
    def test_only_read_only_commands(self):
        ok = [("adb", ["shell", "getprop"]), ("adb", ["shell", "cat", "/proc/cpuinfo"]),
              ("adb", ["shell", "ls", "-1", "/dev/block/by-name"]), ("fastboot", ["getvar", "all"]),
              ("adb", ["shell", "cat", "/sys/devices/system/cpu/cpu7/regs/identification/midr_el1"])]
        refused = [("fastboot", ["flash", "boot", "x.img"]), ("fastboot", ["oem", "unlock"]),
                   ("fastboot", ["flashing", "unlock"]), ("fastboot", ["boot", "x.img"]),
                   ("fastboot", ["reboot"]), ("fastboot", ["erase", "userdata"]), ("fastboot", ["getvar", "imei"]),
                   ("adb", ["reboot", "bootloader"]), ("adb", ["shell", "dd", "if=/dev/block/by-name/boot_a"]),
                   ("adb", ["shell", "cat", "/dev/block/by-name/boot_a"]), ("adb", ["shell", "cat", "/data/x"]),
                   ("adb", ["shell", "cat", "/proc/cpuinfo;reboot"]), ("adb", ["shell", "su", "-c", "id"]),
                   ("adb", ["shell", "getprop", "x", ";", "reboot"]), ("adb", ["push", "a", "/data"]),
                   ("adb", ["shell", "ls", "-1", "/dev/block/by-name; reboot"]), ("sh", ["-c", "true"])]
        for tool, args in ok:
            with self.subTest(args=args):
                self.assertTrue(m.allowed(tool, args))
        for tool, args in refused:
            with self.subTest(args=args):
                self.assertFalse(m.allowed(tool, args))
                with self.assertRaises(PermissionError):
                    m.run("/bin/true", tool, args)

    def test_redaction(self):
        props = {"ro.serialno": "ZY22ABCDEF", "ro.boot.serialno": "ZY22ABCDEF", "ro.product.model": "moto g54 5G",
                 "persist.vendor.wifimac": "00:11:22:33:44:55", "ro.build.fingerprint": "motorola/x/y"}
        redacted = m.redact_pairs(props)
        self.assertTrue(redacted["ro.serialno"].startswith("REDACTED:"))
        self.assertEqual(redacted["ro.serialno"], redacted["ro.boot.serialno"])
        self.assertTrue(redacted["persist.vendor.wifimac"].startswith("REDACTED:"))
        self.assertEqual(redacted["ro.product.model"], "moto g54 5G")
        self.assertEqual(redacted["ro.build.fingerprint"], "motorola/x/y")
        self.assertNotIn("ZY22ABCDEF", m.redact_text("serial ZY22ABCDEF here", ["ZY22ABCDEF"]))

    def test_getvar_parsing_including_continuations(self):
        text = "(bootloader) imei: 351234567890123\n(bootloader) unlocked: no\n(bootloader) ro.carrier: retgb\n" \
               "(bootloader) partition-size:boot_a: 0x4000000\nall: listed above\n"
        values = m.parse_getvar(text)
        self.assertEqual(m.parse_getvar("(bootloader) unlocked:no")["unlocked"], "no")
        self.assertEqual(values["unlocked"], "no")
        self.assertEqual(m.parse_getvar("product: cancunf\nserialno: ABCD")["product"], "cancunf")
        self.assertEqual(values["partition-size:boot_a"], "0x4000000")
        self.assertTrue(m.redact_pairs(values)["imei"].startswith("REDACTED:"))


FAKE_ADB = r"""#!/usr/bin/env python3
import sys
args = sys.argv[1:]
if args == ["get-state"]: print("device")
elif args == ["shell", "getprop"]:
    print("[ro.product.model]: [moto g54 5G]\n[ro.serialno]: [ZY22SECRET1]\n[ro.board.platform]: [mt6855]\n"
          "[ro.boot.slot_suffix]: [_a]\n[ro.product.first_api_level]: [33]")
elif args[:2] == ["shell", "cat"]:
    data = {"/sys/devices/system/cpu/possible": "0-1",
            "/sys/devices/system/cpu/cpu0/regs/identification/midr_el1": "0x00000000412fd050",
            "/sys/devices/system/cpu/cpu1/regs/identification/midr_el1": "0x00000000411fd410"}
    if args[2] in data: print(data[args[2]])
    else: sys.stderr.write("Permission denied\n"); sys.exit(1)
elif args[:3] == ["shell", "ls", "-1"]:
    print("boot_a\nboot_b\nvendor_boot_a\nvendor_boot_b\nlk_a\nlk_b\ninit_boot_a" if args[3] == "/dev/block/by-name" else "")
elif args == ["shell", "uname", "-a"]: print("Linux localhost 5.10 aarch64")
elif args == ["devices"]: print("ZY22SECRET1 fastboot")
elif args == ["getvar", "all"]:
    sys.stderr.write("(bootloader) unlocked: no\n(bootloader) imei: 351234567890123\n"
                     "(bootloader) serialno: ZY22SECRET1\n(bootloader) current-slot: a\n"
                     "factory note: PRIVATE-UNPARSED-9988\n")
"""


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        for name in ("adb", "fastboot"):
            path = bin_dir / name
            path.write_text(FAKE_ADB)
            path.chmod(path.stat().st_mode | stat.S_IEXEC)
        patcher = mock.patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.out = Path(self.tmp.name) / "facts"

    def run_mode(self, mode):
        with mock.patch("sys.stdout"):
            self.assertEqual(m.main(["--out", str(self.out), mode]), 0)
        run_dir = next(self.out.iterdir())
        return run_dir, json.loads((run_dir / "facts.json").read_text())

    def test_adb_collection_is_redacted(self):
        run_dir, report = self.run_mode("adb")
        summary = report["summary"]
        self.assertEqual(summary["board_platform"], "mt6855")
        self.assertEqual(sorted(summary["cpu_core_types"]), ["Cortex-A55", "Cortex-A78"])
        self.assertTrue(summary["has_vendor_boot"] and summary["has_init_boot"] and summary["has_lk"])
        for file in run_dir.iterdir():
            self.assertNotIn("ZY22SECRET1", file.read_text(), file.name)

    def test_fastboot_collection_is_redacted(self):
        run_dir, report = self.run_mode("fastboot")
        self.assertEqual(report["summary"]["unlocked"], "no")
        for file in run_dir.iterdir():
            text = file.read_text()
            self.assertNotIn("ZY22SECRET1", text, file.name)
            self.assertNotIn("351234567890123", text, file.name)
            self.assertNotIn("PRIVATE-UNPARSED-9988", text, file.name)

    def test_fastboot_rejects_ambiguous_devices(self):
        path = Path(self.tmp.name, "bin", "fastboot")
        path.write_text('#!/bin/sh\nprintf "FIRST\tfastboot\nSECOND\tfastboot\n"\n')
        with mock.patch("sys.stdout"), self.assertRaises(SystemExit):
            m.main(["--out", str(self.out), "fastboot"])
        self.assertEqual(list(self.out.iterdir()), [])

    def test_fastboot_rejects_failed_getvar(self):
        path = Path(self.tmp.name, "bin", "fastboot")
        path.write_text('#!/bin/sh\nif [ "$1" = "devices" ]; then echo "SERIAL fastboot"; else echo "(bootloader) unlocked: no"; exit 1; fi\n')
        with mock.patch("sys.stdout"), self.assertRaises(SystemExit):
            m.main(["--out", str(self.out), "fastboot"])
        self.assertEqual(list(self.out.iterdir()), [])

    def test_fastboot_rejects_unparseable_getvar(self):
        path = Path(self.tmp.name, "bin", "fastboot")
        path.write_text('#!/bin/sh\nif [ "$1" = "devices" ]; then echo "SERIAL fastboot"; else echo "No getvars available"; fi\n')
        with mock.patch("sys.stdout"), self.assertRaises(SystemExit):
            m.main(["--out", str(self.out), "fastboot"])
        self.assertEqual(list(self.out.iterdir()), [])

    def test_adb_rejects_failed_getprop(self):
        path = Path(self.tmp.name, "bin", "adb")
        path.write_text('#!/bin/sh\nif [ "$1" = "get-state" ]; then echo device; else echo "Permission denied" >&2; exit 1; fi\n')
        with mock.patch("sys.stdout"), self.assertRaises(SystemExit):
            m.main(["--out", str(self.out), "adb"])
        self.assertEqual(list(self.out.iterdir()), [])

    def test_failed_collection_leaves_no_empty_run(self):
        Path(self.tmp.name, "bin", "adb").write_text("#!/bin/sh\necho 'error: no devices' >&2\nexit 1\n")
        with mock.patch("sys.stdout"), self.assertRaises(SystemExit):
            m.main(["--out", str(self.out), "adb"])
        self.assertEqual(list(self.out.iterdir()), [])

    def test_offline_bootimg_and_dtb(self):
        image = Path(self.tmp.name) / "boot.img"
        image.write_bytes(boot_v2())
        with mock.patch("sys.stdout"):
            self.assertEqual(m.main(["--out", str(self.out), "bootimg", str(image)]), 0)
            self.assertEqual(m.main(["--out", str(self.out / "d"), "dtb", str(image)]), 0)
        report = json.loads(next(self.out.glob("*-bootimg/facts.json")).read_text())
        self.assertIn("boot v2", report["summary"]["boot.img"])
        self.assertEqual(report["images"][str(image)]["dtbs"][0]["compatible"][1], "mediatek,mt6855")


if __name__ == "__main__":
    unittest.main()
