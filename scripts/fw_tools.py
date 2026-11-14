#!/usr/bin/env python3
"""Read-only helpers for stock Android firmware packages, standard library
only (works on Windows without WSL, macOS, Linux). They extract the facts the
G54 port needs from a manufacturer package; they never touch a phone.

    fw_tools.py super   <pkg dir> <partition> <out.img>    # super.img_sparsechunk.* -> one logical partition
    fw_tools.py erofs   ls  <image> [dir]                   # list an EROFS directory
    fw_tools.py erofs   cat <image> <path> <out>            # extract a file (plain or LZ4)
    fw_tools.py ramdisk <vendor_boot.img> <out dir>         # vendor ramdisk (lz4-legacy/gzip cpio)
    fw_tools.py dtb     <image> <regex>                     # DTB nodes whose name/compatible match
    fw_tools.py ko-table <module.ko> <symbol> [stride]      # dump a data table with resolved relocations
    fw_tools.py ipsw-dt <ipsw> <model> <out.adt> [lzfse lib] # e.g. d22ap: DeviceTree IM4P -> decoded ADT
    fw_tools.py im4p    <in.im4p> <out> [lzfse lib]         # decode an LZFSE (bvx2) IM4P payload
LZFSE: macOS uses /usr/lib/libcompression.dylib; elsewhere pass the library
built by scripts/build_lzfse.sh (Apple's open-source lzfse, pinned commit).

Typical G54 uses (docs/usb-console.md, docs/hardware-loop.md):
    fw_tools.py super out/dl/<pkg> vendor_a out/vb/vendor_a.img
    fw_tools.py erofs cat out/vb/vendor_a.img firmware/novatek_ts_fw.bin out/touch/novatek_ts_fw.bin
    fw_tools.py ramdisk out/dl/<pkg>/vendor_boot.img out/vb/rd
    fw_tools.py dtb out/dl/<pkg>/vendor_boot.img "usb|tphy"
    fw_tools.py ko-table out/vb/rd/lib/modules/clk-mt6855-peri.ko perao_clks 64
Paths inside images have no leading slash (Git Bash rewrites "/firmware/...").
"""
import bisect
import glob
import gzip
import hashlib
import os
import re
import struct
import sys


# ------------------------------------------------------------------ LZ4 block
def lz4_block(src, max_out):
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        tok = src[i]
        i += 1
        lit = tok >> 4
        if lit == 15:
            while True:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        out += src[i:i + lit]
        i += lit
        if i >= n or len(out) >= max_out:
            break
        off = src[i] | src[i + 1] << 8
        i += 2
        if off == 0 or off > len(out):
            raise ValueError("bad LZ4 offset")
        ml = tok & 15
        if ml == 15:
            while True:
                b = src[i]
                i += 1
                ml += b
                if b != 255:
                    break
        ml += 4
        start = len(out) - off
        for k in range(ml):
            out.append(out[start + k])
    return bytes(out[:max_out])


# ------------------------------------------------------------------ sparse + LP (super)
class SparseSet:
    """Several Android sparse images of the same device (Motorola sparsechunks) as one raw device."""

    def __init__(self, files):
        self.ranges, self.fh = [], {}
        for f in files:
            with open(f, "rb") as fh:
                magic, major, _minor, fhs, chs, blk, total, nchunks, _ = struct.unpack("<IHHHHIIII", fh.read(28))
                assert magic == 0xED26FF3A and major == 1, f
                self.blk, self.size = blk, total * blk
                fh.seek(fhs)
                pos = 0
                for _ in range(nchunks):
                    ctype, _, csz, tsz = struct.unpack("<HHII", fh.read(chs)[:12])
                    data_off = fh.tell()
                    n = csz * blk
                    if ctype == 0xCAC1:
                        self.ranges.append((pos, pos + n, "raw", f, data_off))
                    elif ctype == 0xCAC2:
                        self.ranges.append((pos, pos + n, "fill", f, fh.read(4)))
                    elif ctype == 0xCAC4:
                        n = 0
                    fh.seek(data_off + tsz - chs)
                    pos += n
        self.ranges.sort()
        self.starts = [r[0] for r in self.ranges]

    def read(self, off, n):
        out = bytearray(n)
        end = off + n
        i = max(bisect.bisect_right(self.starts, off) - 1, 0)
        while i < len(self.ranges) and self.ranges[i][0] < end:
            s, e, kind, f, arg = self.ranges[i]
            lo, hi = max(s, off), min(e, end)
            if lo < hi:
                if kind == "raw":
                    fh = self.fh.get(f) or self.fh.setdefault(f, open(f, "rb"))
                    fh.seek(arg + lo - s)
                    out[lo - off:hi - off] = fh.read(hi - lo)
                else:
                    out[lo - off:hi - off] = (arg * ((hi - lo) // 4 + 1))[:hi - lo]
            i += 1
        return bytes(out)


def lp_partitions(dev):
    geo = dev.read(4096, 4096)
    magic, _, _, meta_max, _slots, _lbs = struct.unpack_from("<II32sIII", geo)
    assert magic == 0x616C4467, "no LP geometry"
    meta = dev.read(4096 * 3, meta_max)
    magic, _major, _minor, hsz = struct.unpack_from("<IHHI", meta)
    assert magic == 0x414C5030, "no LP metadata"
    tsz = struct.unpack_from("<I", meta, 44)[0]
    pd = struct.unpack_from("<III", meta, 80)
    ed = struct.unpack_from("<III", meta, 92)
    tables = meta[hsz:hsz + tsz]
    exts = [struct.unpack_from("<QIQI", tables, ed[0] + i * ed[2]) for i in range(ed[1])]
    parts = {}
    for i in range(pd[1]):
        name, _attrs, first, num, _grp = struct.unpack_from("<36sIIII", tables, pd[0] + i * pd[2])
        parts[name.rstrip(b"\0").decode()] = exts[first:first + num]
    return parts


def cmd_super(pkg, name, out):
    files = sorted(glob.glob(os.path.join(pkg, "super.img_sparsechunk.*")),
                   key=lambda p: int(re.search(r"(\d+)$", p).group(1)))
    if not files:
        files = glob.glob(os.path.join(pkg, "super*.img"))
    dev = SparseSet(files)
    parts = lp_partitions(dev)
    for k, v in parts.items():
        print("  %-24s %12d bytes" % (k, sum(e[0] for e in v) * 512))
    total = 0
    with open(out, "wb") as o:
        for nsec, ttype, tdata, tsrc in parts[name]:
            assert ttype == 0 and tsrc == 0, "only linear extents on device 0"
            off, n = tdata * 512, nsec * 512
            while n:
                k = min(n, 1 << 24)
                o.write(dev.read(off, k))
                off, n, total = off + k, n - k, total + k
    print("wrote %s: %d bytes -> %s" % (name, total, out))


# ------------------------------------------------------------------ EROFS
class Erofs:
    def __init__(self, path):
        self.f = open(path, "rb")
        sb = self.read(1024, 128)
        assert struct.unpack_from("<I", sb)[0] == 0xE0F5E1E2, "not EROFS"
        self.blkbits = sb[12]
        self.bs = 1 << self.blkbits
        self.root_nid = struct.unpack_from("<H", sb, 14)[0]
        self.meta_blkaddr = struct.unpack_from("<I", sb, 40)[0]
        self.zero_padding = bool(struct.unpack_from("<I", sb, 80)[0] & 1)

    def read(self, off, n):
        self.f.seek(off)
        return self.f.read(n)

    def inode(self, nid):
        loc = self.meta_blkaddr * self.bs + nid * 32
        h = self.read(loc, 64)
        fmt, xcount, mode = struct.unpack_from("<HHH", h)
        ext = fmt & 1
        size = struct.unpack_from("<Q" if ext else "<I", h, 8)[0]
        iu = struct.unpack_from("<I", h, 16)[0]
        return dict(nid=nid, loc=loc, mode=mode, layout=(fmt >> 1) & 7, isize=64 if ext else 32,
                    xsize=0 if xcount == 0 else 12 + (xcount - 1) * 4, size=size, iu=iu)

    def flat(self, ino):
        size, bs = ino["size"], self.bs
        if ino["layout"] == 0:
            return self.read(ino["iu"] * bs, size)
        assert ino["layout"] == 2, ino
        full = size // bs * bs
        return (self.read(ino["iu"] * bs, full) if full else b"") + \
            self.read(ino["loc"] + ino["isize"] + ino["xsize"], size - full)

    def listdir(self, ino):
        data, out = self.flat(ino), {}
        for b in range(0, len(data), self.bs):
            blk = data[b:b + self.bs]
            n = struct.unpack_from("<H", blk, 8)[0] // 12
            ents = [struct.unpack_from("<QHBB", blk, i * 12) for i in range(n)]
            for i, (nid, noff, ftype, _) in enumerate(ents):
                end = ents[i + 1][1] if i + 1 < n else len(blk)
                out[blk[noff:end].split(b"\0", 1)[0].decode()] = (nid, ftype)
        return out

    def lookup(self, path):
        ino = self.inode(self.root_nid)
        for part in [p for p in path.split("/") if p]:
            ino = self.inode(self.listdir(ino)[part][0])
        return ino

    def _lcluster(self, ino, lcn):
        """(type, clusterofs, pblk, cblkcnt) following erofs-utils lib/zmap.c."""
        lcb, totalidx = ino["lcb"], -(-ino["size"] // self.bs)
        if ino["layout"] == 1:
            adv, cofs, u = struct.unpack_from("<HHI", self.read(ino["ebase"] + lcn * 8, 8))
            t = adv & 3
            if t == 2:
                return t, 1 << lcb, None, (u & 0x7FF) if (u & 0x800) else None
            return t, cofs, u, None
        ebase = ino["ebase"]
        c4 = ((32 - ebase % 32) // 4) & 7
        c2 = (totalidx - c4) // 16 * 16 if (ino["advise"] & 1) and c4 < totalidx else 0
        pos, shift, lc = ebase, 2, lcn
        if lc >= c4:
            pos += c4 * 4
            lc -= c4
            if lc < c2:
                shift = 1
            else:
                pos += c2 * 2
                lc -= c2
        pos += lc << shift
        vcnt = 2 if shift == 2 else 16
        packsz, lobits = vcnt << shift, max(lcb, 12)
        encodebits = ((packsz - 4) * 8) // vcnt
        base = pos - pos % packsz
        pack = self.read(base, packsz) + b"\0" * 4
        i = (pos - base) >> shift

        def dec(j):
            p = encodebits * j
            v = struct.unpack_from("<I", pack, p // 8)[0] >> (p & 7)
            return (v >> lobits) & 3, v & ((1 << lobits) - 1)
        t, lo = dec(i)
        if t == 2:
            return t, 1 << lcb, None, (lo & 0x7FF) if lo & 0x800 else None
        big = bool(ino["advise"] & 2)
        nblk, j = (0, i) if big else (1, i)
        while j > 0:
            j -= 1
            jt, jlo = dec(j)
            if not big:
                if jt == 2:
                    j -= jlo
                if j >= 0:
                    nblk += 1
            elif jt == 2:
                if jlo & 0x800:
                    j -= 1
                    nblk += jlo & 0x7FF
                else:
                    j -= jlo - 2
            else:
                nblk += 1
        return t, lo, struct.unpack_from("<I", pack, packsz - 4)[0] + nblk, None

    def zread(self, ino):
        mh = (ino["loc"] + ino["isize"] + ino["xsize"] + 7) & ~7
        _, adv, alg, cb = struct.unpack_from("<IHBB", self.read(mh, 8))
        ino.update(ebase=mh + 8, advise=adv, alg=alg, lcb=self.blkbits + (cb & 7))
        if adv & (0x8 | 0x10 | 0x20):
            raise SystemExit("unsupported EROFS features (ztailpacking/interlaced/fragments): 0x%x" % adv)
        lcb, size = ino["lcb"], ino["size"]
        lcs = [self._lcluster(ino, n) for n in range((size + (1 << lcb) - 1) >> lcb)]
        heads = [((n << lcb) | c[1], n, c) for n, c in enumerate(lcs) if c[0] != 2]
        out = bytearray()
        for k, (la, n, (t, _cofs, pblk, _)) in enumerate(heads):
            end = heads[k + 1][0] if k + 1 < len(heads) else size
            nb = 1
            if ((t == 1 and adv & 2) or (t in (0, 3) and adv & 4)) and ((n + 1) << lcb) < size \
                    and lcs[n + 1][0] == 2 and lcs[n + 1][3]:
                nb = lcs[n + 1][3]
            raw = self.read(pblk * self.bs, nb * self.bs)
            if t == 0:
                piece = raw[:end - la]
            else:
                if (alg & 0xF if t == 1 else alg >> 4) != 0:
                    raise SystemExit("only LZ4-compressed EROFS files are supported")
                piece = lz4_block(raw.lstrip(b"\0") if self.zero_padding else raw, end - la)
            out += piece
        return bytes(out)

    def cat(self, path):
        ino = self.lookup(path)
        return self.flat(ino) if ino["layout"] in (0, 2) else self.zread(ino)


def cmd_erofs(args):
    if args[0] == "ls":
        e = Erofs(args[1])
        for name, (nid, ftype) in sorted(e.listdir(e.lookup(args[2] if len(args) > 2 else "")).items()):
            print("%s%s" % (name, "/" if ftype == 2 else ""))
    elif args[0] == "cat":
        data = Erofs(args[1]).cat(args[2])
        with open(args[3], "wb") as o:
            o.write(data)
        print("%s: %d bytes sha256 %s" % (args[3], len(data), hashlib.sha256(data).hexdigest()))
    else:
        raise SystemExit("erofs ls|cat")


# ------------------------------------------------------------------ vendor_boot ramdisk
def cmd_ramdisk(img, outdir):
    d = open(img, "rb").read()
    assert d[:8] == b"VNDRBOOT", "not a vendor_boot image"
    ver, page = struct.unpack_from("<II", d, 8)
    rd_size = struct.unpack_from("<I", d, 24)[0]
    hdr_size = struct.unpack_from("<I", d, 2096)[0]
    off = -(-hdr_size // page) * page
    rd = d[off:off + rd_size]
    if rd[:4] == bytes.fromhex("02214c18"):
        raw, i = bytearray(), 4
        while i + 4 <= len(rd):
            n = struct.unpack_from("<I", rd, i)[0]
            i += 4
            if n == 0x184C2102:
                continue
            raw += lz4_block(rd[i:i + n], 8 << 20)
            i += n
        raw = bytes(raw)
    else:
        raw = gzip.decompress(rd)
    p, count = 0, 0
    while p + 110 <= len(raw):
        h = raw[p:p + 110]
        fields = [int(h[6 + 8 * i:14 + 8 * i], 16) for i in range(13)]
        mode, fsize, nsize = fields[1], fields[6], fields[11]
        name = raw[p + 110:p + 110 + nsize - 1].decode()
        p = (p + 110 + nsize + 3) & ~3
        body = raw[p:p + fsize]
        p = (p + fsize + 3) & ~3
        if name == "TRAILER!!!":
            break
        if name.startswith("/") or ".." in name.split("/"):
            continue
        dst = os.path.join(outdir, name)
        if (mode & 0o170000) == 0o040000:
            os.makedirs(dst, exist_ok=True)
        elif (mode & 0o170000) == 0o100000:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as o:
                o.write(body)
            count += 1
    print("vendor_boot v%d: %d files -> %s" % (ver, count, outdir))


# ------------------------------------------------------------------ DTB
def fdt_nodes(blob):
    _magic, _tot, off_struct, off_str = struct.unpack_from(">IIII", blob)
    strs, p, path, out = blob[off_str:], off_struct, [], []
    while True:
        tok = struct.unpack_from(">I", blob, p)[0]
        p += 4
        if tok == 1:
            e = blob.index(b"\0", p)
            path.append(blob[p:e].decode(errors="replace"))
            p = (e + 4) & ~3
            props = {}
            out.append(("/".join(path), props))
        elif tok == 2:
            path.pop()
        elif tok == 3:
            ln, no = struct.unpack_from(">II", blob, p)
            p += 8
            props[strs[no:strs.index(b"\0", no)].decode()] = blob[p:p + ln]
            p = (p + ln + 3) & ~3
        elif tok == 9:
            return out


def fmt_prop(v):
    if v and v[-1:] == b"\0" and all(32 <= c < 127 or c == 0 for c in v):
        return v.rstrip(b"\0").replace(b"\0", b" | ").decode()
    if len(v) % 4 == 0:
        return " ".join("%#x" % x for x in struct.unpack(">%dI" % (len(v) // 4), v))
    return v.hex()


def cmd_dtb(img, pattern):
    data, rx, seen = open(img, "rb").read(), re.compile(pattern, re.I), set()
    for m in re.finditer(b"\xd0\x0d\xfe\xed", data):
        try:
            nodes = fdt_nodes(data[m.start():])
        except Exception:
            continue
        for path, props in nodes:
            comp = props.get("compatible", b"").decode(errors="replace")
            if (rx.search(path.split("/")[-1]) or rx.search(comp)) and (path, comp) not in seen:
                seen.add((path, comp))
                print("[dtb@%#x] %s" % (m.start(), path))
                for k, v in props.items():
                    print("    %s = %s" % (k, fmt_prop(v)))


# ------------------------------------------------------------------ .ko data tables
def cmd_ko_table(path, want, stride=8):
    f = open(path, "rb").read()
    shoff, = struct.unpack_from("<Q", f, 0x28)
    shentsize, shnum, shstrndx = struct.unpack_from("<HHH", f, 0x3A)
    S = [struct.unpack_from("<IIQQQQIIQQ", f, shoff + i * shentsize) for i in range(shnum)]

    def sname(i):
        o = S[shstrndx][4] + S[i][0]
        return f[o:f.index(b"\0", o)].decode()
    symtab = next(i for i, s in enumerate(S) if s[1] == 2)
    strtab = S[symtab][6]
    syms = []
    for k in range(S[symtab][5] // 24):
        nm, _info, _other, shndx, val, size = struct.unpack_from("<IBBHQQ", f, S[symtab][4] + k * 24)
        o = S[strtab][4] + nm
        syms.append((f[o:f.index(b"\0", o)].decode(), shndx, val, size))

    def cstr(sec, off):
        o = S[sec][4] + off
        return f[o:f.index(b"\0", o)].decode(errors="replace")

    def target(si, add):
        n, shndx, val, _size = syms[si]
        if not shndx or shndx >= shnum:
            return "&%s+%d" % (n, add)
        if n and not n.startswith("$"):
            return "&%s+%d" % (n, add) if add else "&" + n
        off = val + add
        for m in syms:
            if m[1] == shndx and m[0] and not m[0].startswith("$") and m[2] <= off < m[2] + max(m[3], 1):
                return "&%s+%d" % (m[0], off - m[2]) if off - m[2] else "&" + m[0]
        t = cstr(shndx, off)
        return repr(t) if t and all(32 <= ord(c) < 127 for c in t) else "%s+%#x" % (sname(shndx), off)
    sym = next(s for s in syms if s[0] == want)
    sec, base, size = sym[1], sym[2], sym[3]
    relas = {}
    for s in S:
        if s[1] == 4 and s[7] == sec:
            for k in range(s[5] // 24):
                off, info, add = struct.unpack_from("<QQq", f, s[4] + k * 24)
                if base <= off < base + size:
                    relas[off - base] = target(info >> 32, add)
    data = f[S[sec][4] + base:S[sec][4] + base + size]
    print("%s: %s, %d bytes" % (want, sname(sec), size))
    for o in range(0, size, stride):
        row = []
        for q in range(o, min(o + stride, size), 8):
            if q in relas:
                row.append(relas[q])
            else:
                w = data[q:q + 8]
                row.append(" ".join("%#x" % x for x in struct.unpack("<%dI" % (len(w) // 4), w[:len(w) // 4 * 4])))
        print("+%5d: %s" % (o, "  ".join(row)))


# ------------------------------------------------------------------ IM4P / LZFSE
def _der(buf, i):
    tag, n = buf[i], buf[i + 1]
    i += 2
    if n & 0x80:
        k = n & 0x7F
        n = int.from_bytes(buf[i:i + k], "big")
        i += k
    return tag, buf[i:i + n], i + n


def lzfse_decode(payload, size, lib=None):
    import ctypes
    cap = max(size or 0, len(payload) * 8) + 4096
    out = ctypes.create_string_buffer(cap)
    if lib is None and sys.platform == "darwin":
        cl = ctypes.CDLL("/usr/lib/libcompression.dylib")
        cl.compression_decode_buffer.restype = ctypes.c_size_t
        cl.compression_decode_buffer.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                                                 ctypes.c_size_t, ctypes.c_void_p, ctypes.c_int]
        n = cl.compression_decode_buffer(out, cap, payload, len(payload), None, 0x801)
    else:
        if lib is None:
            raise SystemExit("LZFSE needs a library here: build it with scripts/build_lzfse.sh and pass its path")
        lz = ctypes.CDLL(os.path.abspath(lib))
        lz.lzfse_decode_scratch_size.restype = ctypes.c_size_t
        lz.lzfse_decode_buffer.restype = ctypes.c_size_t
        lz.lzfse_decode_buffer.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                                           ctypes.c_size_t, ctypes.c_void_p]
        scratch = ctypes.create_string_buffer(lz.lzfse_decode_scratch_size() + 1)
        n = lz.lzfse_decode_buffer(out, cap, payload, len(payload), scratch)
    if not 0 < n < cap or (size and n != size):
        raise SystemExit("LZFSE decode failed (%d bytes, expected %s)" % (n, size))
    return out.raw[:n]


def im4p_decode(raw, lib=None):
    tag, body, _ = _der(raw, 0)
    assert tag == 0x30, "not DER"
    items, i = [], 0
    while i < len(body):
        t, v, i = _der(body, i)
        items.append((t, v))
    assert items[0] == (0x16, b"IM4P"), "not an IM4P"
    payload = items[3][1]
    size = None
    if len(items) > 4 and items[4][0] == 0x30:
        _, _, j = _der(items[4][1], 0)
        size = int.from_bytes(_der(items[4][1], j)[1], "big")
    if payload[:4] != b"bvx2":
        return payload
    return lzfse_decode(payload, size, lib)


def cmd_im4p(src, dst, lib=None):
    data = im4p_decode(open(src, "rb").read(), lib)
    with open(dst, "wb") as o:
        o.write(data)
    print("%s: %d bytes sha256 %s" % (dst, len(data), hashlib.sha256(data).hexdigest()))


def cmd_ipsw_dt(ipsw, model, dst, lib=None):
    import zipfile
    name = "Firmware/all_flash/DeviceTree.%s.im4p" % model
    data = im4p_decode(zipfile.ZipFile(ipsw).read(name), lib)
    with open(dst, "wb") as o:
        o.write(data)
    print("%s -> %s: %d bytes sha256 %s" % (name, dst, len(data), hashlib.sha256(data).hexdigest()))


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    cmd, a = argv[1], argv[2:]
    if cmd == "super":
        cmd_super(*a)
    elif cmd == "erofs":
        cmd_erofs(a)
    elif cmd == "ramdisk":
        cmd_ramdisk(*a)
    elif cmd == "dtb":
        cmd_dtb(*a)
    elif cmd == "ko-table":
        cmd_ko_table(a[0], a[1], int(a[2]) if len(a) > 2 else 8)
    elif cmd == "im4p":
        cmd_im4p(*a)
    elif cmd == "ipsw-dt":
        cmd_ipsw_dt(*a)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
