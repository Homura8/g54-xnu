#!/usr/bin/env python3
"""Build a G54 boot_a image that boots XNU: probe/loader + SWEETXNU payload.

  python3 scripts/g54_xnu_image.py --topaz <ios-topaz checkout at BASE_SHA> \\
      --kernel <kernel.development.sweet> --stock <5-8-6 boot.img> \\
      --out out/g2/xnu-boot.img [--cmdline "..."] [--cpus 1]

Reuses the pinned upstream tools instead of copying them: ios-topaz
tools/adt.py, tools/mkadt.py and tools/mkpayload.py (BASE_REPO at BASE_SHA in
config/kernel.env). mkadt.py's constants describe the topaz phone. They are
overridden here with G54 (MT6855) values observed on the phone (see
docs/device-facts.md and docs/experiments/), then the tree is adjusted:

  * six Cortex-A55 CPUs, MPIDR Aff1 = 0..5 (live DTB cpu@000..005 reg
    0x000..0x500; boot CPU reads MPIDR 0x81000000, E4),
  * /sweet-ufs only with --ufs (MT6855 ufshci@112b0000; read-only unless
    the cmdline has ufsrw=1).

The resulting payload is appended after the probe (payload/g1) at its
`_end`; the probe's loader finds it, copies the kernel to phys_base and
jumps. This script only writes files on the host.
"""
import argparse
import hashlib
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import g54_payload  # noqa: E402

G54 = dict(
    PHYS_BASE=0x140000000,      # ruby's window; free on the G54 (E4: 0x140000000+0xffe00000)
    MEM_SIZE=0x80000000,
    GICD=0x0c000000, GICD_SIZE=0x40000,     # stock DTB interrupt-controller reg
    GICR=0x0c040000, GICR_SIZE=0x200000,
    FB=0xfeac6000, FB_SIZE=0x9e4000,        # OVL0 L1 scanout (E4), 4320*2400 rounded to 16 KiB
    FB_W=1080, FB_H=2400, FB_STRIDE=4320,
    TIMEBASE=13000000,                      # CNTFRQ 0xc65d40 (E4)
    VTIMER_INTID=27,                        # DT timer PPI 11
    UFS=0x112b0000, UFS_SIZE=0x4000,        # stock DTB ufshci@112b0000 (reg size 0x2300)
)
DEFAULT_CMDLINE = "debug=0xc serial=3 cpus={cpus} keepsyms=1 -noprogress wdt=-1"


def env(path):
    out = {}
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


def load_topaz(topaz):
    pins = env(os.path.join(ROOT, "config", "kernel.env"))
    head = subprocess.run(["git", "-C", topaz, "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()
    if head != pins["BASE_SHA"]:
        raise SystemExit(f"{topaz} is at {head}, expected BASE_SHA {pins['BASE_SHA']}")
    sys.path.insert(0, os.path.join(topaz, "tools"))
    import adt, mkadt, mkpayload  # noqa: E401,E402
    return adt, mkadt, mkpayload


def build_adt(adt, mkadt, ncpu, ufs=False, d22ap=None):
    if d22ap:
        mkadt.D22AP_ADT = d22ap   # /product of the real iPhone X tree (Apple material: keep in out/)
    mkadt.HIGH_PHYS_BASE, mkadt.HIGH_MEM_SIZE = G54["PHYS_BASE"], G54["MEM_SIZE"]
    for k in ("GICD", "GICD_SIZE", "GICR", "GICR_SIZE", "FB", "FB_SIZE", "FB_W", "FB_H",
              "FB_STRIDE", "TIMEBASE", "VTIMER_INTID", "UFS", "UFS_SIZE"):
        setattr(mkadt, k, G54[k])
    seed = hashlib.sha512(b"g54 adt seed").digest()  # reproducible images
    root = mkadt.build(seed=seed, highmem=True)

    def name(n):
        return dict((k, v) for k, f, v in n.props).get("name", b"").rstrip(b"\0").decode()

    if not ufs:
        root.children = [c for c in root.children if name(c) != "sweet-ufs"]
    cpus = next(c for c in root.children if name(c) == "cpus")
    template = cpus.children[0]
    nodes = []
    for core in range(ncpu):
        n = adt.Node()
        props = []
        for k, f, v in template.props:
            if k == "name":
                v = mkadt.cstr(f"cpu{core}")
            elif k == "reg":
                v = mkadt.u32(core << 8)          # MPIDR Aff1:Aff0 (MT bit not in reg)
            elif k in ("cpu-id", "cluster-core-id"):
                v = mkadt.u32(core)
            elif k == "AAPL,phandle":
                v = mkadt.u32(0x800 + core)
            elif k == "state":
                v = mkadt.cstr("running" if core == 0 else "stopped")
            elif k == "clock-frequency":
                v = mkadt.u32(2000000000)
            props.append((k, f, v))
        n.props = props
        n.children = []
        nodes.append(n)
    cpus.children = nodes
    blob = adt.serialize(root)
    adt.parse(blob)  # round-trip check
    return blob


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--topaz", required=True)
    ap.add_argument("--kernel", required=True)
    ap.add_argument("--stock", required=True)
    ap.add_argument("--probe", default=os.path.join(ROOT, "out", "g1"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--cpus", type=int, default=1)
    ap.add_argument("--cmdline")
    ap.add_argument("--d22ap", help="decoded DeviceTree.d22ap (for /product); see docs/status.md")
    ap.add_argument("--ufs", action="store_true",
                    help="describe the UFS host (/sweet-ufs); the driver stays read-only without ufsrw=1")
    a = ap.parse_args(argv)

    adt, mkadt, mkpayload = load_topaz(a.topaz)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    adt_blob = build_adt(adt, mkadt, 6, ufs=a.ufs, d22ap=a.d22ap)
    adt_path = a.out + ".adt"
    open(adt_path, "wb").write(adt_blob)
    cmdline = a.cmdline or DEFAULT_CMDLINE.format(cpus=a.cpus)
    payload, info = mkpayload.build(a.kernel, adt_path, cmdline)
    open(a.out + ".payload", "wb").write(payload)

    probe = open(os.path.join(a.probe, "probe.bin"), "rb").read()
    nm = subprocess.run([g54_payload.tool("llvm-nm"), os.path.join(a.probe, "probe.elf")],
                        capture_output=True, text=True, check=True).stdout
    end = next(int(l.split()[0], 16) for l in nm.splitlines() if l.endswith(" _end"))
    stock = open(a.stock, "rb").read()
    img, pinfo = g54_payload.pack(stock, probe, append=payload, append_at=end)
    errs = g54_payload.verify(stock, img, probe)
    if errs:
        raise SystemExit("; ".join(errs))
    raw = g54_payload.gunzip(img[g54_payload.PAGE:g54_payload.PAGE + pinfo["kernel_size"]])
    if raw[end:end + len(payload)] != payload:
        raise SystemExit("payload not at _end in the packed image")
    open(a.out, "wb").write(img)
    sha = lambda b: hashlib.sha256(b).hexdigest()
    print(f"kernel   {a.kernel} sha256={sha(open(a.kernel, 'rb').read())}")
    print(f"adt      {len(adt_blob)} bytes sha256={sha(adt_blob)}")
    print(f"payload  {len(payload)} bytes at raw+{end:#x} entry={info['entry']} "
          f"virt_base={info['virt_base']} kernel_end={info['kernel_end']} fixups={info['fixups']}")
    print(f"cmdline  {cmdline}")
    print(f"image    {a.out} sha256={sha(img)} {pinfo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
