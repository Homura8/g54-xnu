"""Offline tests for scripts/g54_usb.py (no phone, no serial port)."""
import os
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.dirname(__file__))
import g54_usb  # noqa: E402


class FakePort:
    """Answers like the 0210 driver: ping -> pong #seq, commands -> reply #seq+1."""

    def __init__(self, stale=b""):
        self.seq = 41
        self.out = [stale]

    def write(self, data):
        for line in data.decode().split("\n"):
            if not line:
                continue
            self.seq += 1
            if line == "ping":
                self.out.append(b"noise\nG54 USB: ok pong #%d\n" % self.seq)
            elif line.startswith("tap"):
                self.out.append(b"SWEET HID: touch 9 down\nG54 USB: done tap #%d\n" % self.seq)
            elif line.startswith("shot"):
                w, h = 3, 2
                pix = bytes(range(w * h * 3))
                self.out.append(b"log before\n@@G54SHOT w=%d h=%d fmt=rgb888 bytes=%d seq=%d@@\n" %
                                (w, h, len(pix), self.seq) + pix + b"\n@@G54SHOT end seq=%d@@\n" % self.seq)

    def read(self, n=1 << 16):
        return self.out.pop(0) if self.out else b""


class G54UsbTests(unittest.TestCase):
    def test_command_matches_its_own_sequence_number(self):
        stale = b"G54 USB: done tap #3\nG54 USB: done tap #43\n"   # replayed lines must not match
        sess = g54_usb.Session(FakePort(stale))
        seq, reply = sess.command("tap 10 20 60")
        self.assertEqual(seq, 43)
        self.assertEqual(reply, "G54 USB: done tap #43")

    def test_shot_frame_is_cut_by_length(self):
        sess = g54_usb.Session(FakePort())
        w, h, rgb = sess.shot("low", timeout=5)
        self.assertEqual((w, h), (3, 2))
        self.assertEqual(rgb, bytes(range(18)))

    def test_png_is_valid(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.png")
            g54_usb.write_png(path, 3, 2, bytes(range(18)))
            data = open(path, "rb").read()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        w, h, depth, ctype = struct.unpack(">IIBB", data[16:26])
        self.assertEqual((w, h, depth, ctype), (3, 2, 8, 2))
        idat_len = struct.unpack(">I", data[33:37])[0]
        raw = zlib.decompress(data[41:41 + idat_len])
        self.assertEqual(raw, b"\x00" + bytes(range(9)) + b"\x00" + bytes(range(9, 18)))


if __name__ == "__main__":
    unittest.main()
