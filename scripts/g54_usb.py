#!/usr/bin/env python3
"""Talk to a G54 running kernel patch 0210 with boot-arg g54usb=1 over its USB
serial console (CDC-ACM, USB ID 1209:0003). Standard library only: Windows
(ctypes), macOS and Linux (termios). Read docs/usb-console.md first.

    python3 scripts/g54_usb.py wait                  # until the port appears
    python3 scripts/g54_usb.py log --seconds 20 --grep "G54|CRASH"
    python3 scripts/g54_usb.py log --all --out out/usblog/boot.log   # whole ring
    python3 scripts/g54_usb.py shot                  # low: 270x600 PNG (cheap to view)
    python3 scripts/g54_usb.py shot --size half      # 540x1200, small text
    python3 scripts/g54_usb.py shot --size full      # 1080x2400, documentation
    python3 scripts/g54_usb.py tap 540 1200
    python3 scripts/g54_usb.py swipe 540 2000 540 800 --ms 300
    python3 scripts/g54_usb.py home                  # swipe up from the bottom edge
    python3 scripts/g54_usb.py key power|volup|voldown|home [--ms 100]
    python3 scripts/g54_usb.py fastboot              # reboot into Fastboot (no buttons)
    python3 scripts/g54_usb.py reboot
    python3 scripts/g54_usb.py cmd "raw command"

Coordinates are panel pixels, 1080 x 2400, origin top left. Output is one
short line per action (paths, sizes, timings) so an agent can loop cheaply.
Nothing here writes to the phone's storage; fastboot/reboot sync first.
"""
import argparse
import glob
import os
import re
import struct
import sys
import time
import zlib

VID_PID = "VID_1209&PID_0003"
SHOT_RE = re.compile(rb"@@G54SHOT w=(\d+) h=(\d+) fmt=rgb888 bytes=(\d+) seq=(\d+)@@\n")


# --------------------------------------------------------------------- ports
def find_port():
    if os.name == "nt":
        import winreg
        active = set()
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM") as k:
                i = 0
                while True:
                    try:
                        active.add(str(winreg.EnumValue(k, i)[1]).upper())
                    except OSError:
                        break
                    i += 1
        except OSError:
            return None
        base = r"SYSTEM\CurrentControlSet\Enum\USB"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as usb:
                i = 0
                while True:
                    try:
                        dev = winreg.EnumKey(usb, i)
                    except OSError:
                        break
                    i += 1
                    if not dev.upper().startswith(VID_PID):
                        continue
                    with winreg.OpenKey(usb, dev) as dk:
                        j = 0
                        while True:
                            try:
                                inst = winreg.EnumKey(dk, j)
                            except OSError:
                                break
                            j += 1
                            try:
                                with winreg.OpenKey(dk, inst + r"\Device Parameters") as pk:
                                    name = str(winreg.QueryValueEx(pk, "PortName")[0]).upper()
                                    if name in active:
                                        return name
                            except OSError:
                                pass
        except OSError:
            return None
        return None
    for pat in ("/dev/serial/by-id/*G54*", "/dev/cu.usbmodemG54*", "/dev/cu.usbmodem*"):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[0]
    return None


class Port:
    """Raw serial port. replay=True raises RTS so the phone replays its log ring."""

    def __init__(self, name, replay=False):
        self.name = name
        if os.name == "nt":
            self._open_win(name, replay)
        else:
            self._open_posix(name, replay)

    # Windows
    def _open_win(self, name, replay):
        import ctypes
        from ctypes import wintypes as wt
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = wt.HANDLE
        h = k32.CreateFileW("\\\\.\\" + name, 0xC0000000, 0, None, 3, 0, None)
        if h in (None, ctypes.c_void_p(-1).value):
            raise OSError("cannot open %s (error %d): in use by another program?" % (name, ctypes.get_last_error()))

        class DCB(ctypes.Structure):
            _fields_ = [("DCBlength", wt.DWORD), ("BaudRate", wt.DWORD), ("flags", wt.DWORD),
                        ("wReserved", wt.WORD), ("XonLim", wt.WORD), ("XoffLim", wt.WORD),
                        ("ByteSize", ctypes.c_ubyte), ("Parity", ctypes.c_ubyte), ("StopBits", ctypes.c_ubyte),
                        ("XonChar", ctypes.c_char), ("XoffChar", ctypes.c_char), ("ErrorChar", ctypes.c_char),
                        ("EofChar", ctypes.c_char), ("EvtChar", ctypes.c_char), ("wReserved1", wt.WORD)]

        class TIMEOUTS(ctypes.Structure):
            _fields_ = [(n, wt.DWORD) for n in ("ReadIntervalTimeout", "ReadTotalTimeoutMultiplier",
                                                 "ReadTotalTimeoutConstant", "WriteTotalTimeoutMultiplier",
                                                 "WriteTotalTimeoutConstant")]
        dcb = DCB()
        dcb.DCBlength = ctypes.sizeof(DCB)
        k32.GetCommState(h, ctypes.byref(dcb))
        dcb.BaudRate, dcb.ByteSize, dcb.Parity, dcb.StopBits = 115200, 8, 0, 0
        # fBinary | fDtrControl=ENABLE | fRtsControl=ENABLE/DISABLE
        dcb.flags = 1 | (1 << 4) | ((1 if replay else 0) << 12)
        k32.SetCommState(h, ctypes.byref(dcb))
        k32.SetupComm(h, 1 << 20, 1 << 16)
        to = TIMEOUTS(0xFFFFFFFF, 0xFFFFFFFF, 100, 0, 2000)
        k32.SetCommTimeouts(h, ctypes.byref(to))
        self._k32, self._h, self._ct, self._wt = k32, h, ctypes, wt

    def _read_win(self, n):
        buf = self._ct.create_string_buffer(n)
        got = self._wt.DWORD(0)
        if not self._k32.ReadFile(self._h, buf, n, self._ct.byref(got), None):
            raise OSError("read failed (error %d): phone gone?" % self._ct.get_last_error())
        return buf.raw[:got.value]

    # macOS / Linux
    def _open_posix(self, name, replay):
        import fcntl
        import termios
        import tty
        self._fd = os.open(name, os.O_RDWR | os.O_NOCTTY)
        tty.setraw(self._fd)
        bits = struct.pack("I", termios.TIOCM_DTR | (termios.TIOCM_RTS if replay else 0))
        fcntl.ioctl(self._fd, termios.TIOCMBIS, bits)
        if not replay:
            fcntl.ioctl(self._fd, termios.TIOCMBIC, struct.pack("I", termios.TIOCM_RTS))

    def read(self, n=1 << 16):
        if os.name == "nt":
            return self._read_win(n)
        import select
        r, _, _ = select.select([self._fd], [], [], 0.1)
        return os.read(self._fd, n) if r else b""

    def write(self, data):
        if os.name == "nt":
            got = self._wt.DWORD(0)
            self._k32.WriteFile(self._h, data, len(data), self._ct.byref(got), None)
        else:
            os.write(self._fd, data)

    def close(self):
        try:
            if os.name == "nt":
                self._k32.CloseHandle(self._h)
            else:
                os.close(self._fd)
        except OSError:
            pass


# --------------------------------------------------------------------- protocol
class Session:
    def __init__(self, port):
        self.p = port
        self.buf = b""

    def _fill(self):
        chunk = self.p.read()
        if chunk:
            self.buf += chunk
        return bool(chunk)

    def wait_line(self, pattern, timeout):
        """Return the first log line matching pattern (bytes regex) seen from now on."""
        rx = re.compile(pattern)
        end = time.time() + timeout
        while time.time() < end:
            while b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                if rx.search(line):
                    return line.decode("latin-1").rstrip("\r")
            self._fill()
        raise TimeoutError("no reply matching %r within %ss" % (pattern, timeout))

    def command(self, text, timeout=15.0, done=True):
        """ping to learn the sequence number, then send text and wait for its own reply."""
        self.buf = b""
        self.p.write(b"\nping\n")
        seq = int(self.wait_line(rb"G54 USB: ok pong #(\d+)", 10).rsplit("#", 1)[1])
        self.p.write(text.encode() + b"\n")
        want = seq + 1
        pat = (rb"G54 USB: (done|err|ok) .*#%d\b" % want) if done else (rb"G54 USB: (err|ok) .*#%d\b" % want)
        return want, self.wait_line(pat, timeout)

    def shot(self, size, timeout):
        self.buf = b""
        self.p.write(b"\nping\n")
        seq = int(self.wait_line(rb"G54 USB: ok pong #(\d+)", 10).rsplit("#", 1)[1])
        self.p.write(b"shot " + size.encode() + b"\n")
        want = seq + 1
        end = time.time() + timeout
        while time.time() < end:
            m = SHOT_RE.search(self.buf)
            if m and int(m.group(4)) == want:
                w, h, n = int(m.group(1)), int(m.group(2)), int(m.group(3))
                data = self.buf[m.end():]
                while len(data) < n:
                    if time.time() > end:
                        raise TimeoutError("shot: %d of %d bytes" % (len(data), n))
                    chunk = self.p.read()
                    data += chunk
                self.buf = data[n:]
                return w, h, data[:n]
            if re.search(rb"G54 USB: err .*#%d\b" % want, self.buf):
                raise RuntimeError(self.buf.split(b"G54 USB: err", 1)[1].split(b"\n", 1)[0].decode("latin-1"))
            self._fill()
        raise TimeoutError("no screenshot within %ss" % timeout)


def write_png(path, w, h, rgb):
    raw = b"".join(b"\x00" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
                chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# --------------------------------------------------------------------- cli
def open_port(args, replay=False):
    name = args.port or find_port()
    if not name:
        sys.exit("no G54 USB console found (boot with g54usb=1, cable plugged in; try: g54_usb.py wait)")
    return Port(name, replay=replay)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", help="COMn or /dev/... (default: auto-detect 1209:0003)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("wait", help="wait until the console port appears")
    w.add_argument("--timeout", type=float, default=240)
    lg = sub.add_parser("log", help="print the log (live tail; --all replays the ring)")
    lg.add_argument("--all", action="store_true")
    lg.add_argument("--seconds", type=float, default=10)
    lg.add_argument("--grep", help="only lines matching this regex")
    lg.add_argument("--tail", type=int, help="print only the last N (matching) lines")
    lg.add_argument("--out", help="also write everything to this file")
    sh = sub.add_parser("shot", help="screenshot to PNG")
    sh.add_argument("--size", choices=("low", "half", "full"), default="low")
    sh.add_argument("--out", help="PNG path (default out/usbshots/<time>-<size>.png)")
    t = sub.add_parser("tap")
    t.add_argument("x", type=int)
    t.add_argument("y", type=int)
    t.add_argument("--ms", type=int, default=60)
    s = sub.add_parser("swipe")
    for n in ("x0", "y0", "x1", "y1"):
        s.add_argument(n, type=int)
    s.add_argument("--ms", type=int, default=300)
    sub.add_parser("home", help="swipe up from the bottom edge (iPhone X home / unlock)")
    k = sub.add_parser("key")
    k.add_argument("name", choices=("power", "volup", "voldown", "home"))
    k.add_argument("--ms", type=int, default=100)
    sub.add_parser("fastboot", help="sync and reboot into Fastboot")
    sub.add_parser("reboot", help="sync and reboot normally")
    c = sub.add_parser("cmd", help="send a raw command line")
    c.add_argument("text")
    args = ap.parse_args()

    if args.cmd == "wait":
        t0 = time.time()
        while time.time() - t0 < args.timeout:
            name = args.port or find_port()
            if name:
                print("port %s after %.0fs" % (name, time.time() - t0))
                return
            time.sleep(1)
        sys.exit("no console port within %.0fs" % args.timeout)

    port = open_port(args, replay=(args.cmd == "log" and args.all))
    try:
        sess = Session(port)
        if args.cmd == "log":
            rx = re.compile(args.grep) if args.grep else None
            out = open(args.out, "w", encoding="latin-1", newline="") if args.out else None
            kept, end, n = [], time.time() + args.seconds, 0
            while time.time() < end:
                sess._fill()
                while b"\n" in sess.buf:
                    raw, sess.buf = sess.buf.split(b"\n", 1)
                    line = raw.decode("latin-1").rstrip("\r")
                    n += 1
                    if out:
                        out.write(line + "\n")
                    if rx and not rx.search(line):
                        continue
                    if args.tail:
                        kept.append(line)
                        del kept[:-args.tail]
                    else:
                        print(line)
            if args.tail:
                print("\n".join(kept))
            if out:
                out.close()
                print("[%d lines -> %s]" % (n, args.out))
        elif args.cmd == "shot":
            t0 = time.time()
            wd, ht, rgb = sess.shot(args.size, timeout={"low": 20, "half": 40, "full": 120}[args.size])
            path = args.out or os.path.join("out", "usbshots", time.strftime("%Y%m%d-%H%M%S") + "-" + args.size + ".png")
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            write_png(path, wd, ht, rgb)
            print("%s %dx%d %.1fs" % (path, wd, ht, time.time() - t0))
        else:
            text = {"tap": lambda: "tap %d %d %d" % (args.x, args.y, args.ms),
                    "swipe": lambda: "swipe %d %d %d %d %d" % (args.x0, args.y0, args.x1, args.y1, args.ms),
                    "home": lambda: "swipe 540 2390 540 1300 250",
                    "key": lambda: "key %s %d" % (args.name, args.ms),
                    "fastboot": lambda: "fastboot",
                    "reboot": lambda: "reboot",
                    "cmd": lambda: args.text}[args.cmd]()
            if args.cmd in ("fastboot", "reboot"):
                port.write(b"\n" + text.encode() + b"\n")
                print("%s sent" % args.cmd)
                return
            gesture = args.cmd in ("tap", "swipe", "home", "key")
            _, reply = sess.command(text, timeout=20, done=gesture)
            print(reply.split("G54 USB: ", 1)[-1])
    finally:
        port.close()


if __name__ == "__main__":
    main()
