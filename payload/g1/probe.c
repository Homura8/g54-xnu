// G54 probe v3: prove that LK executed our code, report what LK handed over,
// and return to Fastboot without anyone touching the phone.
//
//   1. Parse the DTB LK passes in x0: the LK framebuffer (/chosen
//      atag,videolfb-*; fallback: reserved-memory *framebuffer*), /memory and
//      every /reserved-memory child.
//   2. Paint MAGENTA for PHASE1_S seconds (alive marker; same in RGB/BGR).
//   3. Show a text screen for INFO_S seconds (photograph it): CPU IDs, EL,
//      entry PC, DTB, framebuffer, memory, reserved regions, and the largest
//      free DRAM ranges. Two vertical test lines settle the pitch: the one
//      drawn with the true pitch is straight.
//   4. Paint GREEN for PHASE2_S seconds, then reboot to Fastboot: watchdog
//      reboot-mode 3, then PSCI SYSTEM_RESET (E2; a direct watchdog SWRST
//      boots normally, E1).
//
// History: v1 (E1) magenta/green + SWRST; v2 (E2) PSCI reset + 4 diagnostic
// bands: EL1 entry, watchdog enabled, reboot-mode write effective.
//
// Hardware facts: stock 5-8-6 vendor_boot DTB (watchdog@1c007000,
// reboot-mode offset 0x24 mask 0xf bootloader=3; PSCI 1.0 smc). Watchdog keys:
// upstream Linux drivers/watchdog/mtk_wdt.c (WDT_RST 0x08/0x1971).
//
// Built freestanding with -mstrict-align: the MMU is off, so every data access
// is Device memory and must be naturally aligned.
//
// SPDX-License-Identifier: MIT

#include "text.h"

typedef unsigned char u8;
typedef unsigned int u32;
typedef unsigned long u64;

#define WDT_BASE        0x1c007000UL
#define WDT_MODE        0x00U
#define WDT_RST         0x08U
#define WDT_RST_KEY     0x1971U
#define WDT_SWRST       0x14U
#define WDT_SWRST_KEY   0x1209U
#define WDT_NONRST2     0x24U
#define RB_MODE_MASK    0x0fU
#define RB_MODE_BOOTLOADER 0x3U

#define DRAM_LO         0x40000000UL
#define DRAM_HI         0x240000000UL   /* 8 GiB observed (getvar ram) */
#define FB_MIN          (1080UL * 2400UL * 4UL)
#define FB_MAX          0x4000000UL
#define FB_W            1080U
#define FB_H            2400U
#ifndef FB_PITCH
#define FB_PITCH        (1080U * 4U)    /* E2 hint: 4352 pushed the bottom band off-screen */
#endif
#define ALT_PITCH       (1088U * 4U)

#define MAGENTA         0xffff00ffU
#define GREEN           0xff00ff00U
#define WHITE           0xffffffffU
#define BLACK           0xff000000U
#define GREY            0xff808080U

#ifndef PHASE1_S
#define PHASE1_S 3
#endif
#ifndef INFO_S
#define INFO_S 60
#endif
#ifndef PHASE2_S
#define PHASE2_S 2
#endif
#ifndef LOADER_S
#define LOADER_S 8   /* time to photograph the info screen before XNU */
#endif

#define FDT_MAGIC       0xd00dfeedU
#define FDT_BEGIN_NODE  1U
#define FDT_END_NODE    2U
#define FDT_PROP        3U
#define FDT_NOP         4U
#define FDT_MAX         0x400000U

#define MAX_MEM         8
#define MAX_RES         96
#define MAX_FREE        6

static inline void w32(u64 a, u32 v) { *(volatile u32 *)a = v; }
static inline u32 r32(u64 a) { return *(volatile u32 *)a; }

/* Byte-wise big-endian read: safe for any alignment on Device memory. */
static u32 be32(const volatile u8 *p)
{
    return ((u32)p[0] << 24) | ((u32)p[1] << 16) | ((u32)p[2] << 8) | p[3];
}

static u64 be64(const volatile u8 *p) { return ((u64)be32(p) << 32) | be32(p + 4); }

static int streq(const volatile u8 *a, const char *b)
{
    while (*b)
        if (*a++ != (u8)*b++)
            return 0;
    return *a == 0;
}

static int starts(const volatile u8 *a, const char *b)
{
    while (*b)
        if (*a++ != (u8)*b++)
            return 0;
    return 1;
}

static int contains(const volatile u8 *a, const char *b)
{
    for (; *a; a++) {
        const volatile u8 *x = a;
        const char *y = b;
        while (*y && *x == (u8)*y) {
            x++;
            y++;
        }
        if (!*y)
            return 1;
    }
    return 0;
}

#define rsr(r) ({ u64 _v; __asm__ volatile("mrs %0, " r : "=r"(_v)); _v; })

static u64 ticks(void)
{
    __asm__ volatile("isb");
    return rsr("cntpct_el0");
}

static u64 freq(void)
{
    u64 v = rsr("cntfrq_el0");
    return v ? v : 13000000UL;  /* MTK system counter is 13 MHz */
}

static void kick(void) { w32(WDT_BASE + WDT_RST, WDT_RST_KEY); }

static void wait_s(u64 s)
{
    u64 end = ticks() + s * freq();
    while (ticks() < end)
        kick();
}

/* ---- what LK handed over ---- */

struct range {
    u64 base, size;
};

struct handoff {
    u64 dtb;
    u32 dtb_size, nres_nodes;
    int have_fb;
    struct range fb;
    int nmem, nres;
    struct range mem[MAX_MEM], res[MAX_RES];
};

static void add(struct range *arr, int *n, int max, u64 base, u64 size)
{
    if (*n < max && size) {
        arr[*n].base = base;
        arr[*n].size = size;
        (*n)++;
    }
}

/* Walk the flattened tree once. Bounded by totalsize and an iteration guard.
 * Assumes #address-cells = #size-cells = 2 for /memory and /reserved-memory,
 * as in the stock MT6855 DTB. */
static void parse_dtb(u64 dtb, struct handoff *h)
{
    const volatile u8 *b = (const volatile u8 *)dtb;
    h->dtb = dtb;
    if (!dtb || dtb & 3 || dtb < DRAM_LO || dtb >= DRAM_HI || be32(b) != FDT_MAGIC)
        return;
    u32 total = be32(b + 4), off_struct = be32(b + 8), off_str = be32(b + 12);
    if (total < 40 || total > FDT_MAX || off_struct >= total || off_str >= total)
        return;
    h->dtb_size = total;

    const volatile u8 *p = b + off_struct, *end = b + total;
    int depth = 0, in_chosen = 0, in_fbnode = 0, in_mem = 0, in_resv = 0, in_res_child = 0;
    u32 lo = 0, hi = 0, vram = 0, have_lo = 0, have_vram = 0;
    u64 rbase = 0, rsize = 0;

    for (u32 guard = 0; guard < 400000U && p + 4 <= end; guard++) {
        u32 tok = be32(p);
        p += 4;
        if (tok == FDT_BEGIN_NODE) {
            depth++;
            if (depth == 2) {
                in_chosen = streq(p, "chosen");
                in_mem = streq(p, "memory") || starts(p, "memory@");
                in_resv = streq(p, "reserved-memory");
            }
            if (depth == 3) {
                in_res_child = in_resv;
                in_fbnode = in_resv && contains(p, "framebuffer");
                if (in_resv)
                    h->nres_nodes++;
            }
            while (p < end && *p)
                p++;
            p = (const volatile u8 *)(((u64)p + 4) & ~3UL);
        } else if (tok == FDT_END_NODE) {
            if (depth == 2)
                in_chosen = in_mem = in_resv = 0;
            if (depth == 3)
                in_res_child = in_fbnode = 0;
            depth--;
        } else if (tok == FDT_PROP) {
            if (p + 8 > end)
                return;
            u32 len = be32(p), nameoff = be32(p + 4);
            p += 8;
            if (off_str + nameoff >= total || p + len > end)
                return;
            const volatile u8 *name = b + off_str + nameoff;
            if (depth == 2 && in_chosen && len == 4) {
                if (streq(name, "atag,videolfb-fb_base_l")) {
                    lo = be32(p);
                    have_lo = 1;
                } else if (streq(name, "atag,videolfb-fb_base_h")) {
                    hi = be32(p);
                } else if (streq(name, "atag,videolfb-vramSize")) {
                    vram = be32(p);
                    have_vram = 1;
                }
            } else if (streq(name, "reg") && len % 16 == 0) {
                for (u32 i = 0; i < len; i += 16) {
                    u64 base = be64(p + i), size = be64(p + i + 8);
                    if (depth == 2 && in_mem)
                        add(h->mem, &h->nmem, MAX_MEM, base, size);
                    else if (depth == 3 && in_res_child)
                        add(h->res, &h->nres, MAX_RES, base, size);
                    if (depth == 3 && in_fbnode && i == 0) {
                        rbase = base;
                        rsize = size;
                    }
                }
            }
            p += (len + 3) & ~3U;
        } else if (tok == FDT_NOP) {
            continue;
        } else {
            break;  /* FDT_END or garbage */
        }
    }

    u64 base = have_lo ? (((u64)hi << 32) | lo) : rbase;
    u64 size = have_vram ? vram : rsize;
    if (base >= DRAM_LO && size >= FB_MIN && size <= FB_MAX && base + size <= DRAM_HI &&
        !(base & 0xfff)) {
        h->fb.base = base;
        h->fb.size = size;
        h->have_fb = 1;
    }
}

/* Keep the MAX_FREE largest ranges, sorted by size, descending. */
static void keep_largest(struct range *out, int *n, struct range f)
{
    int i;
    if (*n < MAX_FREE)
        i = (*n)++;
    else if (f.size > out[MAX_FREE - 1].size)
        i = MAX_FREE - 1;
    else
        return;
    out[i] = f;
    while (i > 0 && out[i - 1].size < out[i].size) {
        struct range t = out[i - 1];
        out[i - 1] = out[i];
        out[i] = t;
        i--;
    }
}

/* Pieces of /memory not covered by any reserved region; the largest few. */
static int free_ranges(const struct handoff *h, struct range *out)
{
    int n = 0;
    for (int m = 0; m < h->nmem; m++) {
        u64 cur = h->mem[m].base, end = h->mem[m].base + h->mem[m].size;
        for (u32 guard = 0; cur < end && guard < 1000; guard++) {
            u64 next = end;
            int covered = 0;
            for (int r = 0; r < h->nres; r++) {
                u64 rb = h->res[r].base, re = rb + h->res[r].size;
                if (rb <= cur && re > cur) {
                    cur = re;      /* skip a reservation covering cur */
                    covered = 1;
                } else if (rb > cur && rb < next) {
                    next = rb;
                }
            }
            if (covered)
                continue;
            struct range f = {cur, next - cur};
            keep_largest(out, &n, f);
            cur = next;
        }
    }
    return n;
}

/* ---- framebuffer drawing ---- */

static u64 fb_base;
static u32 pitch;

static void fill(const struct range *fb, u32 color)
{
    volatile u64 *p = (volatile u64 *)fb->base;
    u64 v = ((u64)color << 32) | color;
    for (u64 i = 0; i < fb->size / 8; i++) {
        p[i] = v;
        if ((i & 0xffff) == 0)
            kick();
    }
    __asm__ volatile("dsb sy" ::: "memory");
}

static u64 fb_end;

static void px(u32 x, u32 y, u32 c, u32 stride)
{
    u64 a = fb_base + (u64)y * stride + (u64)x * 4;
    if (x < FB_W && y < FB_H && a + 4 <= fb_end)
        *(volatile u32 *)a = c;
}

#define SCALE 4
#define CW (6 * SCALE)
#define CH (9 * SCALE)
static u32 cx, cy;

static void putc_(char ch, u32 color)
{
    if (ch == '\n') {
        cx = 0;
        cy += CH;
        return;
    }
    if (ch >= 'a' && ch <= 'z')
        ch -= 32;
    if (ch < 32 || ch > 95)
        ch = '?';
    const unsigned char *g = font5x7[ch - 32];
    for (u32 r = 0; r < 7; r++)
        for (u32 c = 0; c < 5; c++)
            if (g[r] & (0x10 >> c))
                for (u32 dy = 0; dy < SCALE; dy++)
                    for (u32 dx = 0; dx < SCALE; dx++)
                        px(12 + cx + c * SCALE + dx, 12 + cy + r * SCALE + dy, color, pitch);
    cx += CW;
    if (cx + CW > FB_W - 24) {
        cx = 0;
        cy += CH;
    }
}

static void puts_(const char *s, u32 color)
{
    while (*s)
        putc_(*s++, color);
}

static void hex(u64 v, int digits, u32 color)
{
    for (int i = digits - 1; i >= 0; i--)
        putc_("0123456789ABCDEF"[(v >> (i * 4)) & 0xf], color);
}

static void kv(const char *k, u64 v, int digits)
{
    puts_(k, GREY);
    puts_("=", GREY);
    hex(v, digits, WHITE);
    puts_(" ", WHITE);
}

static void dump_engines(void);


#ifdef TOUCH_SCAN
/*
 * E22: which touch controller does this unit have? LK merges one dtbo
 * overlay (panel-specific) into the DTB it passes us. Print every node whose
 * first compatible looks like a touch IC, with status, name and parent (the
 * bus), plus /chosen mmi,panel_name.
 */
#define TS_MAXD 16
/* Explicit literals: a pointer table would need absolute relocations. */
static int ts_match(const volatile u8 *c)
{
    return contains(c, "nt36") || contains(c, "novatek") || contains(c, "focaltech") ||
           contains(c, "fts") || contains(c, "ilitek") || contains(c, "chipone") ||
           contains(c, "icnl") || contains(c, "goodix") || contains(c, "himax") ||
           contains(c, "touch");
}

static void puts_v(const volatile u8 *p, int max, u32 color)
{
    for (int i = 0; i < max && p[i]; i++)
        putc_((char)p[i], color);
}

static void touch_scan(u64 dtb)
{
    const volatile u8 *b = (const volatile u8 *)dtb;
    if (!dtb || be32(b) != FDT_MAGIC)
        return;
    u32 total = be32(b + 4), off_struct = be32(b + 8), off_str = be32(b + 12);
    const volatile u8 *p = b + off_struct, *end = b + total;
    static const volatile u8 *name[TS_MAXD], *compat[TS_MAXD], *status[TS_MAXD];
    static int done[TS_MAXD];   /* .bss: zeroed by entry.S; one scan per buffer */
    for (int i = 0; i < TS_MAXD; i++) {
        name[i] = compat[i] = status[i] = 0;
        done[i] = 1;
    }
    int depth = 0, shown = 0;
    puts_("TOUCH SCAN\n", GREEN);
    for (u32 guard = 0; guard < 400000U && p + 4 <= end && shown < 12; guard++) {
        u32 tok = be32(p);
        p += 4;
        if (tok == FDT_BEGIN_NODE || tok == FDT_END_NODE) {
            /* the node at `depth` has all its own properties now */
            if (depth > 0 && depth < TS_MAXD && !done[depth]) {
                done[depth] = 1;
                if (compat[depth] && ts_match(compat[depth])) {
                    puts_v(compat[depth], 30, WHITE);
                    puts_(" ", WHITE);
                    puts_v(status[depth] ? status[depth] : (const volatile u8 *)"(no status)", 9,
                           status[depth] && streq(status[depth], "okay") ? GREEN : GREY);
                    puts_("\n  ", WHITE);
                    puts_v(name[depth], 24, GREY);
                    puts_(" IN ", GREY);
                    puts_v(depth > 1 ? name[depth - 1] : (const volatile u8 *)"/", 24, GREY);
                    puts_("\n", WHITE);
                    shown++;
                }
            }
            if (tok == FDT_BEGIN_NODE) {
                depth++;
                if (depth < TS_MAXD) {
                    name[depth] = p;
                    compat[depth] = status[depth] = 0;
                    done[depth] = 0;
                }
                while (p < end && *p)
                    p++;
                p = (const volatile u8 *)(((u64)p + 4) & ~3UL);
            } else {
                depth--;
            }
        } else if (tok == FDT_PROP) {
            u32 len = be32(p), nameoff = be32(p + 4);
            p += 8;
            const volatile u8 *pn = b + off_str + nameoff;
            if (depth < TS_MAXD && len) {
                if (streq(pn, "compatible"))
                    compat[depth] = p;
                else if (streq(pn, "status"))
                    status[depth] = p;
                else if (depth == 2 && streq(pn, "mmi,panel_name")) {
                    puts_("PANEL ", GREEN);
                    puts_v(p, 40, WHITE);
                    puts_("\n", WHITE);
                }
            }
            p += (len + 3) & ~3U;
        } else if (tok == FDT_NOP) {
            continue;
        } else {
            break;
        }
    }
    if (!shown)
        puts_("  NO TOUCH NODES\n", GREY);
}
#endif /* TOUCH_SCAN */

static void info_screen(const struct handoff *h, u64 pc, int which)
{
    /* Pitch test: x = 1000 drawn with both candidate pitches. */
    for (u32 y = 0; y < FB_H; y++) {
        px(1000, y, GREEN, FB_PITCH);
        px(1040, y, MAGENTA, ALT_PITCH);
    }
    cx = cy = 0;
    puts_("G54 PROBE V4 BUF ", WHITE);
    hex(which, 1, WHITE);
    puts_(" AT ", WHITE);
    hex(fb_base, 9, WHITE);
    puts_(" P ", WHITE);
    hex(pitch, 4, WHITE);
    puts_("\n", WHITE);
    kv("EL", (rsr("CurrentEL") >> 2) & 3, 1);
    kv("MIDR", rsr("midr_el1"), 8);
    kv("MPIDR", rsr("mpidr_el1"), 8);
    puts_("\n", WHITE);
    kv("MMFR0", rsr("id_aa64mmfr0_el1"), 8);
    kv("CNTFRQ", rsr("cntfrq_el0"), 8);
    puts_("\n", WHITE);
    kv("PC", pc, 9);
    kv("DTB", h->dtb, 9);
    kv("SZ", h->dtb_size, 6);
    puts_("\n", WHITE);
    kv("FB", h->fb.base, 9);
    kv("VRAM", h->fb.size, 8);
    puts_("\n", WHITE);
    kv("WDT MODE", r32(WDT_BASE + WDT_MODE), 8);
    kv("NONRST2", r32(WDT_BASE + WDT_NONRST2), 8);
    puts_("\n", WHITE);
    dump_engines();
    puts_("MEMORY\n", GREEN);
    for (int i = 0; i < h->nmem; i++) {
        hex(h->mem[i].base, 9, WHITE);
        puts_("+", GREY);
        hex(h->mem[i].size, 9, WHITE);
        puts_("\n", WHITE);
    }
    struct range fr[MAX_FREE];
    for (int i = 0; i < MAX_FREE; i++)
        fr[i].base = fr[i].size = 0;
    int nf = free_ranges(h, fr);
    puts_("LARGEST FREE\n", GREEN);
    for (int i = 0; i < nf; i++) {
        hex(fr[i].base, 9, WHITE);
        puts_("+", GREY);
        hex(fr[i].size, 9, WHITE);
        puts_(i & 1 ? "\n" : "  ", WHITE);
    }
#if defined(TOUCH_SCAN)
    puts_("\n", WHITE);
    touch_scan(h->dtb);
#elif defined(NO_RESV)
    /* reserved list omitted for space (recorded in E4) */
#else
    puts_("\nRESERVED ", GREEN);
    hex(h->nres, 2, WHITE);
    puts_(" IN ", GREEN);
    hex(h->nres_nodes, 2, WHITE);
    puts_(" NODES\n", GREEN);
    for (int i = 0; i < h->nres; i++) {
        hex(h->res[i].base, 9, WHITE);
        puts_("+", GREY);
        hex(h->res[i].size, 8, WHITE);
        puts_(i & 1 ? "\n" : "  ", WHITE);
        if ((i & 7) == 0)
            kick();
    }
#endif
    __asm__ volatile("dsb sy" ::: "memory");
}

/* ---- which buffer is LK scanning out? ---- */
/* Register layout: upstream Linux drivers/gpu/drm/mediatek/mtk_disp_ovl.c and
 * mtk_disp_rdma.c (OVL SRC_CON 0x2c, Ln_PITCH 0x44+0x20n, Ln_ADDR 0xf40+0x20n;
 * RDMA GLOBAL_CON 0x10, SRC_PITCH 0x2c, MEM_START_ADDR 0xf00). Bases from the
 * stock DTB: disp_ovl0@14002000, disp_ovl1_2l@14004000, disp_rdma0@14006000. */
#define OVL0  0x14002000UL
#define OVL1  0x14004000UL
#define RDMA0 0x14006000UL
#define MAX_CAND 12

struct cand {
    u64 addr;
    u32 pitch;
};
static struct cand cands[MAX_CAND];
static int ncand;

static void add_cand(const struct range *fb, u64 addr, u32 pit)
{
    if (addr < fb->base || addr >= fb->base + fb->size || ncand >= MAX_CAND)
        return;
    if (pit < FB_W * 4 || pit > 8192)
        pit = FB_PITCH;
    for (int i = 0; i < ncand; i++)
        if (cands[i].addr == addr && cands[i].pitch == pit)
            return;
    cands[ncand].addr = addr;
    cands[ncand].pitch = pit;
    ncand++;
}

static void find_scanout(const struct range *fb)
{
    const u64 ovls[2] = {OVL0, OVL1};
    for (int o = 0; o < 2; o++) {
        u32 src = r32(ovls[o] + 0x2c);
        for (u32 n = 0; n < 4; n++)
            if (src & (1U << n))
                add_cand(fb, r32(ovls[o] + 0xf40 + 0x20 * n), r32(ovls[o] + 0x44 + 0x20 * n) & 0xffff);
    }
    if (r32(RDMA0 + 0x10) & 2)  /* memory mode */
        add_cand(fb, r32(RDMA0 + 0xf00), r32(RDMA0 + 0x2c) & 0xffff);
    add_cand(fb, fb->base, FB_PITCH);  /* always also the start of vram */
}

static void dump_engines(void)
{
    const u64 ovls[2] = {OVL0, OVL1};
    for (int o = 0; o < 2; o++) {
        puts_(o ? "OVL1 " : "OVL0 ", GREEN);
        kv("SRC", r32(ovls[o] + 0x2c), 8);
        kv("ROI", r32(ovls[o] + 0x20), 8);
        puts_("\n", WHITE);
        for (u32 n = 0; n < 4; n++) {
            kv(" A", r32(ovls[o] + 0xf40 + 0x20 * n), 8);
            kv("P", r32(ovls[o] + 0x44 + 0x20 * n), 8);
            kv("S", r32(ovls[o] + 0x38 + 0x20 * n), 8);
            puts_("\n", WHITE);
        }
    }
    puts_("RDMA ", GREEN);
    kv("CON", r32(RDMA0 + 0x10), 8);
    kv("A", r32(RDMA0 + 0xf00), 8);
    puts_("\n", WHITE);
    kv("     P", r32(RDMA0 + 0x2c), 8);
    kv("W", r32(RDMA0 + 0x14), 8);
    kv("H", r32(RDMA0 + 0x18), 8);
    puts_("\n", WHITE);
}



#ifdef UFS_FIX
/* ---- UFS link (E8): diagnose and wake the link LK leaves behind ---- */
/*
 * UFSHCI 2.x registers (JEDEC JESD223) at the stock DTB ufshci@112b0000.
 * MediaTek link state: Linux drivers/ufs/host/ufs-mediatek.c
 * ufs_mtk_wait_link_state(): REG_UFS_DEBUG_SEL (0x22c0) = 0x20, then
 * REG_UFS_PROBE (0x22c8) >> 28 (VS_LINK_UP 2, VS_LINK_HIBERN8 3).
 * E7: XNU's polled driver got OCS 5 (UIC communication failure) on its first
 * TEST UNIT READY. Only the link power state is changed here; no data access.
 */
#define UFS         0x112b0000UL
#define U_AHIT      0x18
#define U_IS        0x20
#define U_HCS       0x30
#define U_HCE       0x34
#define U_UECPA     0x38
#define U_UECDL     0x3c
#define U_UECDME    0x48
#define U_UICCMD    0x90
#define U_ARG1      0x94
#define U_ARG2      0x98
#define U_ARG3      0x9c
#define IS_UHXS     (1U << 5)
#define IS_UCCS     (1U << 10)
#define HCS_UCRDY   (1U << 3)

static u32 ufs_link_state(void)
{
    w32(UFS + 0x22c0, 0x20);
    __asm__ volatile("dsb sy" ::: "memory");
    return r32(UFS + 0x22c8) >> 28;
}

/* Returns the UIC result code (ARG2 low byte), or 0xff on timeout. */
static u32 ufs_uic(u32 cmd, u32 arg1, u32 *val)
{
    u64 end = ticks() + freq() / 2;
    while (!(r32(UFS + U_HCS) & HCS_UCRDY))
        if (ticks() > end)
            return 0xfe;
    w32(UFS + U_IS, IS_UCCS);
    w32(UFS + U_ARG1, arg1);
    w32(UFS + U_ARG2, 0);
    w32(UFS + U_ARG3, 0);
    w32(UFS + U_UICCMD, cmd);
    end = ticks() + freq() / 2;
    while (!(r32(UFS + U_IS) & IS_UCCS))
        if (ticks() > end)
            return 0xff;
    w32(UFS + U_IS, IS_UCCS);
    if (val)
        *val = r32(UFS + U_ARG3);
    return r32(UFS + U_ARG2) & 0xff;
}

#define IS_ULSS     (1U << 8)

static void ufs_link_line(const char *tag)
{
    u32 tx = 0, rx = 0, peer = 0;
    u32 rtx = ufs_uic(0x01, 0x1561U << 16, &tx);   /* DME_GET PA_CONNECTEDTXDATALANES */
    u32 rrx = ufs_uic(0x01, 0x1581U << 16, &rx);   /* DME_GET PA_CONNECTEDRXDATALANES */
    u32 rp = ufs_uic(0x03, 0x1571U << 16, &peer);  /* DME_PEER_GET PA_PWRMODE */
    puts_(tag, GREEN);
    kv("TX", rtx ? 0xee : tx, 2);
    kv("RX", rrx ? 0xee : rx, 2);
    kv("PEER", peer, 2);
    kv("RC", rp, 2);
    kv("LINK", ufs_link_state(), 1);
    puts_("\n", WHITE);
}

/* Returns nonzero if the UFS device answers over the link. */
static int ufs_peer_ok(void)
{
    u32 v = 0;
    return ufs_uic(0x03, 0x1571U << 16, &v) == 0;
}

/*
 * E10: MediaTek gates the UFS device reference clock through
 * REG_UFS_REFCLK_CTRL (0x144): bit 0 = request, bit 1 = ack (Linux
 * ufs-mediatek.c ufs_mtk_setup_ref_clk waits for ack == request). Without
 * the clock the device PHY cannot train, which matches E9 (peer RC 8,
 * DME_LINKSTARTUP RC 1).
 */
#define U_XOUFS     0x140
#define U_REFCLK    0x144

static void ufs_vendor_line(void)
{
    puts_("    MTK ", GREEN);
    kv("XO", r32(UFS + U_XOUFS), 8);
    kv("REFCLK", r32(UFS + U_REFCLK), 8);
    kv("IPVER", r32(UFS + 0x2240), 8);
    puts_("\n", WHITE);
}

static int ufs_linkstartup(void)
{
    for (int i = 0; i < 3; i++) {
        w32(UFS + U_IS, IS_ULSS);
        u32 rc = ufs_uic(0x16, 0, 0);              /* DME_LINKSTARTUP */
        u64 end = ticks() + freq() / 2;
        while (!(r32(UFS + U_HCS) & 1) && ticks() < end)
            ;
        puts_("    LINKSTARTUP ", GREEN);
        kv("RC", rc, 2);
        kv("IS", r32(UFS + U_IS), 8);
        puts_("\n", WHITE);
        w32(UFS + U_IS, r32(UFS + U_IS));
        if (rc == 0 && ufs_peer_ok())
            return 1;
    }
    return 0;
}

/*
 * E13: MediaTek vendor ufs-mediatek.c order (kernel_device_modules-5.15):
 *   ufs_mtk_device_reset: ufshcd_hba_stop (HCE=0), RST_n low >= 10 us, high,
 *     10-15 ms; reset via MTK_SIP_UFS_CONTROL 0xc2000276 cmd DEVICE_RESET (2)
 *     (E11: accepted, ret 0; LK's 0xc200040d is refused from EL1, E12).
 *   hce enable: HCE=1 (no extra host reset when UniPro was left in LPM).
 *   ufs_mtk_pre_link: DME_SET VS_UNIPROPOWERDOWNCONTROL(0xd0a8,sel 0)=0,
 *     PA_LOCAL_TX_LCC_ENABLE(0x155e)=0, VS_SAVEPOWERCONTROL(0xd0a6) bit 6 clear.
 *   DME_LINKSTARTUP.
 * No MPHY/VA09 steps: the stock DTB ufshci node has no phys or va09-supply.
 */
static u64 mtk_ufs_smc(u64 cmd, u64 val)
{
    register u64 x0 __asm__("x0") = 0xc2000276UL;
    register u64 x1 __asm__("x1") = cmd;
    register u64 x2 __asm__("x2") = val;
    register u64 x3 __asm__("x3") = 0;
    __asm__ volatile("smc #0" : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3)::"x4", "x5", "x6", "x7",
                     "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17", "memory");
    return x0;
}

static void delay_us(u64 us)
{
    u64 end = ticks() + freq() * us / 1000000 + 1;
    while (ticks() < end)
        ;
}

static u32 dme_set(u32 attr, u32 sel, u32 val)
{
    u64 end = ticks() + freq() / 2;
    while (!(r32(UFS + U_HCS) & HCS_UCRDY))
        if (ticks() > end)
            return 0xfe;
    w32(UFS + U_IS, IS_UCCS);
    w32(UFS + U_ARG1, (attr << 16) | sel);
    w32(UFS + U_ARG2, 0);
    w32(UFS + U_ARG3, val);
    w32(UFS + U_UICCMD, 0x02);                     /* DME_SET */
    end = ticks() + freq() / 2;
    while (!(r32(UFS + U_IS) & IS_UCCS))
        if (ticks() > end)
            return 0xff;
    w32(UFS + U_IS, IS_UCCS);
    return r32(UFS + U_ARG2) & 0xff;
}

static int hce_set(u32 on)
{
    w32(UFS + U_HCE, on);
    u64 end = ticks() + freq() / 50;               /* 20 ms */
    while ((r32(UFS + U_HCE) & 1) != on)
        if (ticks() > end)
            return 0;
    return 1;
}


/*
 * E14: a freshly reset UFS device answers TEST UNIT READY with CHECK
 * CONDITION until the host completes device init (JESD220: set flag
 * fDeviceInit, poll until the device clears it; Linux
 * ufshcd_complete_dev_init). Minimal polled UTP engine: one transfer
 * request descriptor + command descriptor in free RAM (E4 free range
 * 0x50f00000+0x1f100000). Control queries only, no LUN data.
 */
#define U_UTRLBA    0x50
#define U_UTRLBAU   0x54
#define U_UTRLDBR   0x58
#define U_UTRLRSR   0x60
#define UTP_BASE    0x50f00000UL
#define UTRD        (UTP_BASE)
#define UCD         (UTP_BASE + 0x400)
#define UCD_RSP     0x200

static void utp_zero(void)
{
    for (u64 a = UTP_BASE; a < UTP_BASE + 0x1000; a += 8)
        *(volatile u64 *)a = 0;
}

static void ucd_byte(u32 off, u8 v)
{
    u64 a = UCD + off;
    u32 sh = (a & 3) * 8;
    u64 w = a & ~3UL;
    w32(w, (r32(w) & ~(0xffU << sh)) | ((u32)v << sh));
}

static u8 rsp_byte(u32 off)
{
    u64 a = UCD + UCD_RSP + off;
    return (u8)(r32(a & ~3UL) >> ((a & 3) * 8));
}

/* Returns OCS (0 = success), 0xfe if the doorbell never cleared. */
static u32 utp_send(void)
{
    w32(UTRD + 0, 1U << 28);                       /* CT = UFS storage, no data */
    w32(UTRD + 8, 0x0f);                           /* OCS = invalid until done */
    w32(UTRD + 16, (u32)UCD);
    w32(UTRD + 20, (u32)(UCD >> 32));
    w32(UTRD + 24, ((UCD_RSP / 4) << 16) | (0x80));  /* response offset, length (dwords) */
    w32(UTRD + 28, ((0x300 / 4) << 16) | 0);       /* PRDT offset, no entries */
    __asm__ volatile("dsb sy" ::: "memory");
    w32(UFS + U_UTRLRSR, 0);
    w32(UFS + U_UTRLBA, (u32)UTRD);
    w32(UFS + U_UTRLBAU, (u32)(UTRD >> 32));
    w32(UFS + U_UTRLRSR, 1);
    w32(UFS + U_IS, r32(UFS + U_IS));
    w32(UFS + U_UTRLDBR, 1);
    u64 end = ticks() + freq() / 5;
    while (r32(UFS + U_UTRLDBR) & 1)
        if (ticks() > end)
            return 0xfe;
    __asm__ volatile("dsb sy" ::: "memory");
    return r32(UTRD + 8) & 0xff;
}

static void upiu_hdr(u8 type, u8 tag, u8 func)
{
    for (u32 i = 0; i < 0x400; i += 4)
        w32(UCD + i, 0);
    ucd_byte(0, type);
    ucd_byte(3, tag);
    ucd_byte(5, func);
}

static void ufs_dev_init(void)
{
    u32 ocs = 0xff, nop = 0xff;
    utp_zero();
    for (int i = 0; i < 10; i++) {                 /* NOP OUT until NOP IN */
        upiu_hdr(0x00, 1, 0);
        ocs = utp_send();
        nop = rsp_byte(0);
        if (ocs == 0 && nop == 0x20)
            break;
        delay_us(10000);
    }
    puts_("    NOP ", GREEN);
    kv("OCS", ocs, 2);
    kv("RSP", nop, 2);
    puts_("\n", WHITE);

    upiu_hdr(0x16, 2, 0x81);                       /* QUERY, standard write */
    ucd_byte(12, 0x06);                            /* SET FLAG */
    ucd_byte(13, 0x01);                            /* fDeviceInit */
    u32 so = utp_send();
    u32 st = rsp_byte(0), sr = rsp_byte(6);
    u32 flag = 0xff, ro = 0xff, polls = 0;
    u64 end = ticks() + freq() * 2;
    do {
        upiu_hdr(0x16, 3, 0x01);                   /* QUERY, standard read */
        ucd_byte(12, 0x05);                        /* READ FLAG */
        ucd_byte(13, 0x01);
        ro = utp_send();
        flag = rsp_byte(23);               /* utp_upiu_query.value (be32), low byte */
        polls++;
        if (ro == 0 && rsp_byte(6) == 0 && flag == 0)
            break;
        delay_us(5000);
    } while (ticks() < end);
    puts_("    DEVINIT ", GREEN);
    kv("SET", so, 2);
    kv("T", st, 2);
    kv("R", sr, 2);
    kv("FLAG", flag, 2);
    kv("N", polls, 2);
    puts_("\n", WHITE);
    w32(UFS + U_UTRLRSR, 0);                       /* hand a quiet host to XNU */
    w32(UFS + U_IS, r32(UFS + U_IS));
}


#ifdef UFS_HS
/*
 * E20: E13/E14 leave the link in PWM slow-auto (peer PA_PWRMODE 0x55), while
 * LK ran it FAST (E8: 0x11). iOS boot (E15-E18) then takes ~30 min. Restore
 * HS like Linux ufshcd_change_power_mode(): gear = min(local, peer
 * PA_MAXRXHSGEAR), rate B, terminations on, all connected lanes, the default
 * DL timeouts in PA_PWRMODEUSERDATA0-5 and DME_Local*TimeOutVal, then
 * PA_PWRMODE = FAST/FAST and wait for IS.UPMS; HCS.UPMCRS 1 = PWR_LOCAL.
 * Attribute IDs: include/ufs/unipro.h. No PMC via FASTAUTO: that MediaTek
 * path is for HS-G4+.
 */
#define IS_UPMS     (1U << 4)

static void ufs_hs(void)
{
    u32 lmax = 0, pmax = 0, tx = 0, rx = 0;
    ufs_uic(0x01, 0x1587U << 16, &lmax);           /* local PA_MAXRXHSGEAR */
    ufs_uic(0x03, 0x1587U << 16, &pmax);           /* peer PA_MAXRXHSGEAR */
    ufs_uic(0x01, 0x1561U << 16, &tx);             /* PA_CONNECTEDTXDATALANES */
    ufs_uic(0x01, 0x1581U << 16, &rx);             /* PA_CONNECTEDRXDATALANES */
    u32 gear = lmax < pmax ? lmax : pmax;
    if (gear > 4)
        gear = 4;
    puts_("    HS ", GREEN);
    kv("MAX L", lmax, 1);
    kv("P", pmax, 1);
    kv("GEAR", gear, 1);
    kv("LN", (tx << 4) | rx, 2);
    puts_("\n", WHITE);
    if (gear == 0 || tx == 0 || rx == 0)
        return;
    u32 bad = 0;
    bad |= dme_set(0x1568, 0, gear);               /* PA_TXGEAR */
    bad |= dme_set(0x1583, 0, gear);               /* PA_RXGEAR */
    bad |= dme_set(0x156a, 0, 2);                  /* PA_HSSERIES = rate B */
    bad |= dme_set(0x1569, 0, 1);                  /* PA_TXTERMINATION */
    bad |= dme_set(0x1584, 0, 1);                  /* PA_RXTERMINATION */
    bad |= dme_set(0x1560, 0, tx);                 /* PA_ACTIVETXDATALANES */
    bad |= dme_set(0x1580, 0, rx);                 /* PA_ACTIVERXDATALANES */
    bad |= dme_set(0x15b0, 0, 8191);               /* PA_PWRMODEUSERDATA0..5 */
    bad |= dme_set(0x15b1, 0, 65535);
    bad |= dme_set(0x15b2, 0, 32767);
    bad |= dme_set(0x15b3, 0, 8191);
    bad |= dme_set(0x15b4, 0, 65535);
    bad |= dme_set(0x15b5, 0, 32767);
    bad |= dme_set(0xd041, 0, 8191);               /* DME_Local*TimeOutVal */
    bad |= dme_set(0xd042, 0, 65535);
    bad |= dme_set(0xd043, 0, 32767);
    w32(UFS + U_IS, IS_UPMS);
    u32 rc = dme_set(0x1571, 0, 0x11);             /* PA_PWRMODE = FAST/FAST */
    u64 end = ticks() + freq();
    while (!(r32(UFS + U_IS) & IS_UPMS) && ticks() < end)
        ;
    u32 is = r32(UFS + U_IS), upmcrs = (r32(UFS + U_HCS) >> 8) & 7;
    w32(UFS + U_IS, is);
    u32 lpm = 0, ppm = 0, g = 0;
    ufs_uic(0x01, 0x1571U << 16, &lpm);
    ufs_uic(0x03, 0x1571U << 16, &ppm);
    ufs_uic(0x01, 0x1568U << 16, &g);
    puts_("    PMC ", GREEN);
    kv("SET", bad, 2);
    kv("RC", rc, 2);
    kv("UPMCRS", upmcrs, 1);
    kv("PWR L", lpm, 2);
    kv("P", ppm, 2);
    kv("TXG", g, 1);
    puts_("\n", WHITE);
}
#endif /* UFS_HS */


#ifdef TOUCH_SPI
/*
 * E23: SPI3 bring-up and Novatek NT36672C chip-ID read (touch stage 1).
 * G54 values (docs/experiments/2026-11-13-e22-touch-scan.md):
 *   SPI3 0x11013000 ("mediatek,mt6983-spi"), pad-select 0 for CS0;
 *   clock peraop_spi3_bclk = pericfg_ao 0x11036000 bit 14 (sta 0x10,
 *   clr/ungate 0x2c, set/gate 0x28; decoded from stock clk-mt6855-peri.ko);
 *   pins GPIO73-76 function 2 (GPIO_MODE9 nibbles 1-4); TP reset GPIO3.
 * Controller sequence: ruby-ios-bringup bsd/dev/ruby_spi3.c (FIFO mode,
 * <= 32-byte packets). Novatek SPI framing (public nt36xxx driver behaviour):
 * page = {0xff, a>>15, a>>7}; write = {(a&0x7f)|0x80, data...};
 * read = {a&0x7f, dummy, ...} with data from the third byte.
 */
#define SPI3        0x11013000UL
#define S_CFG0      0x00
#define S_CFG1      0x04
#define S_TX        0x10
#define S_RX        0x14
#define S_CMD       0x18
#define S_ST0       0x1c
#define S_PAD       0x24
#define S_CFG2      0x28
#define S_CFG3      0x2c
#define C_ACT       (1U << 0)
#define C_RST       (1U << 2)
#define C_PAUSE     (1U << 4)
#define C_MSB       ((1U << 12) | (1U << 13))
#define PERAO       0x11036000UL
#define GPIOB       0x10005000UL
#define NVT_SWRST   0x3f0feU
#define NVT_TRIM    0x3f004U

static int spi_xfer(const u8 *tx, u8 *rx, u32 len)
{
    w32(SPI3 + S_CMD, C_RST);
    w32(SPI3 + S_CMD, 0);
    w32(SPI3 + S_CMD, C_MSB);
    w32(SPI3 + S_PAD, 0);
    u32 c1 = r32(SPI3 + S_CFG1) & ~(0xff00U | 0x3ff0000U);
    w32(SPI3 + S_CFG1, c1 | ((len - 1) & 0x3ff) << 16);
    for (u32 i = 0; i < len; i += 4) {
        u32 w = 0;
        for (u32 j = 0; j < 4 && i + j < len; j++)
            w |= (u32)tx[i + j] << (8 * j);
        w32(SPI3 + S_TX, w);
    }
    __asm__ volatile("dsb sy" ::: "memory");
    w32(SPI3 + S_CMD, C_MSB | C_ACT);
    u64 end = ticks() + freq() / 100;
    while (!(r32(SPI3 + S_ST0) & 1))
        if (ticks() > end) {
            w32(SPI3 + S_CMD, C_MSB | C_PAUSE);
            return 0;
        }
    if (rx)
        for (u32 i = 0; i < len; i += 4) {
            u32 w = r32(SPI3 + S_RX);
            for (u32 j = 0; j < 4 && i + j < len; j++)
                rx[i + j] = (u8)(w >> (8 * j));
        }
    w32(SPI3 + S_CMD, C_MSB | C_PAUSE);
    return 1;
}

static int nvt_page(u32 a)
{
    u8 tx[3] = {0xff, (u8)(a >> 15), (u8)(a >> 7)};
    return spi_xfer(tx, 0, 3);
}

static int nvt_write1(u32 a, u8 v)
{
    if (!nvt_page(a))
        return 0;
    u8 tx[2] = {(u8)((a & 0x7f) | 0x80), v};
    return spi_xfer(tx, 0, 2);
}

static int nvt_read(u32 a, u8 *out, u32 n)   /* n <= 28 */
{
    u8 tx[32], rx[32];
    for (u32 i = 0; i < 32; i++)
        tx[i] = rx[i] = 0;
    if (!nvt_page(a))
        return 0;
    tx[0] = (u8)(a & 0x7f);
    if (!spi_xfer(tx, rx, n + 2))
        return 0;
    for (u32 i = 0; i < n; i++)
        out[i] = rx[2 + i];
    return 1;
}

static void touch_spi(void)
{
    puts_("TOUCH SPI3\n", GREEN);
    u32 cg0 = r32(PERAO + 0x10);
    w32(PERAO + 0x2c, 1U << 14);                   /* ungate peraop_spi3_bclk */
    u32 cg1 = r32(PERAO + 0x10);
    u32 m9 = r32(GPIOB + 0x390), m0 = r32(GPIOB + 0x300);
    kv(" CG", cg0, 8);
    kv("->", cg1, 8);
    kv("M9", m9, 8);
    puts_("\n", WHITE);
    kv(" CFG0", r32(SPI3 + S_CFG0), 8);
    kv("1", r32(SPI3 + S_CFG1), 8);
    kv("2", r32(SPI3 + S_CFG2), 8);
    puts_("\n", WHITE);
    kv(" CFG3", r32(SPI3 + S_CFG3), 8);
    kv("CMD", r32(SPI3 + S_CMD), 8);
    kv("M0", m0, 8);
    puts_("\n", WHITE);

    /* Controller first (ruby order), slow clock: sck/cs counts 32 (~0.4-1 MHz). */
    w32(SPI3 + S_CMD, C_RST);
    w32(SPI3 + S_CMD, 0);
    w32(SPI3 + S_PAD, 0);
    w32(SPI3 + S_CMD, C_MSB);
    w32(SPI3 + S_CFG2, (31U << 16) | 31U);         /* sck low/high */
    w32(SPI3 + S_CFG0, (63U << 16) | 63U);         /* cs hold/setup */
    w32(SPI3 + S_CFG1, (r32(SPI3 + S_CFG1) & ~0xffU) | 63U);
    w32(SPI3 + S_CMD, C_MSB | C_PAUSE);
    /* Pins 73-76 -> function 2; TP reset GPIO3 -> GPIO, output, high. */
    w32(GPIOB + 0x390, (m9 & ~0x000ffff0U) | 0x00022220U);
    w32(GPIOB + 0x300, m0 & ~0x0000f000U);
    w32(GPIOB + 0x004, 1U << 3);                   /* DIR set */
    w32(GPIOB + 0x104, 1U << 3);                   /* DOUT set */
    delay_us(20000);
    kv(" M9 NOW", r32(GPIOB + 0x390), 8);
    puts_("\n", WHITE);

    u8 id[8] = {0};
    int r0 = nvt_read(NVT_TRIM, id, 6);
    puts_(" ID0 ", GREEN);
    kv("OK", r0, 1);
    for (int i = 0; i < 6; i++)
        hex(id[i], 2, WHITE), puts_(" ", WHITE);
    puts_("\n", WHITE);
    int w = nvt_write1(NVT_SWRST, 0x69);           /* bootloader reset */
    delay_us(40000);
    for (int i = 0; i < 8; i++)
        id[i] = 0;
    int r1 = nvt_read(NVT_TRIM, id, 6);
    puts_(" ID1 ", GREEN);
    kv("W", w, 1);
    kv("OK", r1, 1);
    for (int i = 0; i < 6; i++)
        hex(id[i], 2, WHITE), puts_(" ", WHITE);
    puts_("\n", WHITE);
}
#endif /* TOUCH_SPI */


#ifdef TOUCH_FW
/*
 * E24: NT36672C flashless firmware download + on-screen touch test.
 * Chip values from the stock nova_0flash_mmi_v2.ko: trim id 0C xx xx 72 66 03
 * selects NT36675_memory_map (EVENT_BUF 0x22d00, BOOT_RDY 0x3f10d,
 * ILM/DLM DES 0x3f128/0x3f12c, LENGTH 0x3f118/0x3f130, G_*_CHECKSUM
 * 0x3f100/0x3f104, BLD_CRC_EN 0x3f30e) and hw_crc 2. Sequence: Novatek
 * host-download flow (eng reset 0x5a@0x7fff80, bootloader reset 0x69@0x3f0fe,
 * SPI_RD_FAST 0x3f310 = 0, SRAM partitions from the bin header, CRC regs,
 * host cmd 0xae@EVENT+0x50, BOOT_RDY=1, reset state 0xa0-0xaf @EVENT+0x60).
 * The firmware blob is appended locally ("NVTFWBIN" tag), never committed.
 */
#define EVT         0x22d00U
static u8 fwb(u64 fw, u32 i) { return *(volatile u8 *)(fw + i); }
static u32 fw32(u64 fw, u32 i)
{
    return fwb(fw, i) | (u32)fwb(fw, i + 1) << 8 | (u32)fwb(fw, i + 2) << 16 | (u32)fwb(fw, i + 3) << 24;
}

static int nvt_write_n(u32 a, const u8 *v, u32 n)   /* n <= 30, within one 128 B page */
{
    u8 tx[32];
    if (!nvt_page(a))
        return 0;
    tx[0] = (u8)((a & 0x7f) | 0x80);
    for (u32 i = 0; i < n; i++)
        tx[1 + i] = v[i];
    return spi_xfer(tx, 0, n + 1);
}

static int nvt_write_le(u32 a, u32 v, u32 n)
{
    u8 b[4] = {(u8)v, (u8)(v >> 8), (u8)(v >> 16), (u8)(v >> 24)};
    return nvt_write_n(a, b, n);
}

static u32 sram_write(u64 fw, u32 bin, u32 sram, u32 len)
{
    u8 buf[30];
    u32 done = 0, bad = 0;
    while (done < len) {
        u32 a = sram + done;
        u32 n = 128 - (a & 0x7f);
        if (n > 30)
            n = 30;
        if (n > len - done)
            n = len - done;
        for (u32 i = 0; i < n; i++)
            buf[i] = fwb(fw, bin + done + i);
        if (!nvt_write_n(a, buf, n))
            bad++;
        done += n;
        if ((done & 0xfff) < 30)
            kick();
    }
    return bad;
}

static u64 find_fw(u64 from)
{
    for (u64 a = (from + 0xfff) & ~0xfffUL; a < from + 0x200000; a += 0x1000) {
        const volatile u8 *m = (const volatile u8 *)a;
        if (m[0] == 'N' && m[1] == 'V' && m[2] == 'T' && m[3] == 'F' && m[4] == 'W' && m[5] == 'B' &&
            m[6] == 'I' && m[7] == 'N')
            return a;
    }
    return 0;
}

static void dot(u32 x, u32 y, u32 c)
{
    for (u32 dy = 0; dy < 12; dy++)
        for (u32 dx = 0; dx < 12; dx++)
            px(x + dx, y + dy, c, pitch);
}

extern char _end[];

static void touch_fw(void)
{
    u64 tag = find_fw((u64)_end);
    puts_("TOUCH FW ", GREEN);
    if (!tag) {
        puts_("NO BLOB\n", 0xffff0000U);
        return;
    }
    u32 fwsize = r32(tag + 8);
    u64 fw = tag + 16;
    u32 hdr = fw32(fw, 0);
    kv("AT", tag, 9);
    kv("SZ", fwsize, 6);
    kv("HDR", hdr, 4);
    puts_("\n", WHITE);

    nvt_write1(0x7fff80, 0x5a);                    /* eng reset */
    delay_us(30000);
    nvt_write1(NVT_SWRST, 0x69);                   /* bootloader reset */
    delay_us(35000);
    nvt_write1(0x3f310, 0x00);                     /* SPI_RD_FAST off */

    /* partitions: ILM/DLM 12-byte entries (bin, sram, size) + CRC at 0x18/0x1c,
     * then 16-byte info entries (sram, size, bin, crc) from 0x30 to hdr. */
    u32 bad = 0, parts = 0, bytes = 0;
    u32 ilm_sram = fw32(fw, 4), ilm_size = fw32(fw, 8), ilm_crc = fw32(fw, 0x18);
    u32 dlm_sram = fw32(fw, 16), dlm_size = fw32(fw, 20), dlm_crc = fw32(fw, 0x1c);
    for (u32 k = 0; k < 2; k++) {
        u32 bin = fw32(fw, k * 12), sram = fw32(fw, k * 12 + 4), size = fw32(fw, k * 12 + 8);
        if (size && bin + size + 1 <= fwsize) {
            bad += sram_write(fw, bin, sram, size + 1);
            parts++;
            bytes += size + 1;
        }
    }
    for (u32 pos = 0x30; pos + 16 <= hdr; pos += 16) {
        u32 sram = fw32(fw, pos), size = fw32(fw, pos + 4), bin = fw32(fw, pos + 8);
        if (size && bin + size + 1 <= fwsize) {
            bad += sram_write(fw, bin, sram, size + 1);
            parts++;
            bytes += size + 1;
        }
    }
    puts_(" WROTE ", GREEN);
    kv("P", parts, 2);
    kv("B", bytes, 6);
    kv("ERR", bad, 4);
    puts_("\n", WHITE);

    nvt_write_le(0x3f118, ilm_size, 3);            /* ILM_LENGTH */
    nvt_write_le(0x3f128, ilm_sram, 3);            /* ILM_DES */
    nvt_write_le(0x3f100, ilm_crc, 4);             /* G_ILM_CHECKSUM */
    nvt_write_le(0x3f130, dlm_size, 3);            /* DLM_LENGTH */
    nvt_write_le(0x3f12c, dlm_sram, 3);            /* DLM_DES */
    nvt_write_le(0x3f104, dlm_crc, 4);             /* G_DLM_CHECKSUM */
    u8 c[2] = {0};
    nvt_read(0x3f30e, c, 1);
    nvt_write1(0x3f30e, c[0] | 0x80);              /* BLD_CRC_EN */

    nvt_write1(EVT + 0x60, 0x00);
    nvt_write1(EVT + 0x50, 0xae);                  /* host cmd: download done */
    nvt_write1(0x3f10d, 0x01);                     /* BOOT_RDY */
    delay_us(10000);
    u8 st[8] = {0};
    u32 tries = 0;
    for (; tries < 60; tries++) {
        nvt_read(EVT + 0x60, st, 6);
        if (st[0] >= 0xa0 && st[0] <= 0xaf)
            break;
        delay_us(10000);
    }
    u8 info[16] = {0};
    nvt_read(EVT + 0x78, info, 16);
    puts_(" BOOT ", GREEN);
    kv("ST", st[0], 2);
    kv("N", tries, 2);
    kv("VER", info[0], 2);
    kv("BAR", info[1], 2);
    puts_("\n", WHITE);

    /* Firmware info (EVT+0x78): ver, ~ver, x_num, y_num, abs_x_max (BE), abs_y_max (BE). */
    u32 xmax = ((u32)info[4] << 8) | info[5], ymax = ((u32)info[6] << 8) | info[7];
    puts_(" INFO", GREEN);
    for (int i = 0; i < 10; i++)
        puts_(" ", WHITE), hex(info[i], 2, WHITE);
    puts_("\n", WHITE);
    if (xmax < 100 || xmax > 20000)
        xmax = 1080;
    if (ymax < 100 || ymax > 40000)
        ymax = 2400;

    /*
     * 20 s touch test. Layout from the stock nvt_ts_work_func (E25): finger i
     * at EVT + 6i, id = b0 >> 3, status = b0 & 7 (1/2 = down), x = b1 << 8 | b2,
     * y = b3 << 8 | b4 (big-endian, 4x panel units, max from INFO). Raw bytes
     * are shown when they change.
     */
    puts_(" TOUCH THE SCREEN (20 S)\n", GREEN);
    u32 lx = cx, ly = cy;
    u64 end = ticks() + 20 * freq();
    u8 last[14] = {0};
    u32 n = 0;
    while (ticks() < end) {
        u8 e[16] = {0};
        nvt_read(EVT, e, 14);
        u32 id = e[0] >> 3, sts = e[0] & 7;
        if (id >= 1 && id <= 10 && (sts == 1 || sts == 2)) {
            u32 x = ((u32)e[1] << 8) | e[2], y = ((u32)e[3] << 8) | e[4];
            if (x <= xmax && y <= ymax)
                dot(x * 1068 / xmax, y * 2388 / ymax, 0xffffff00U);   /* yellow dot */
        }
        int diff = 0;
        for (int i = 0; i < 14; i++)
            if (e[i] != last[i])
                diff = 1, last[i] = e[i];
        if (diff && (n++ & 3) == 0) {
            cx = lx;
            cy = ly;
            puts_(" EV", WHITE);
            for (int i = 0; i < 12; i++)
                puts_(" ", WHITE), hex(e[i], 2, WHITE);
            puts_("  ", WHITE);
        }
        kick();
        delay_us(10000);
    }
    cx = 0;
    cy = ly + 36;
}
#endif /* TOUCH_FW */


#ifdef KEY_SCAN
/*
 * E27: G54 key hardware, read live (no writes except SPMI read commands).
 *   Volume up:   MTK KPD 0x1c00e000 (DTBO hw-init-map key 0 = 0x73),
 *                KP_STA 0x00, KP_MEM1 0x04 bit 0 (0 = pressed, ruby).
 *   Power, volume down: MT6363 PMIC (SPMI slave 4) TOPSTATUS 0x1e, bit 1 =
 *                pwrkey, bit 3 = homekey (DTBO sw-rstkey 0x72 = VOLUMEDOWN);
 *                offsets from the stock mtk-pmic-keys.ko mt6363_regs.
 *   SPMI: PMIF 0x1c804000, SWINF n at 0x800 + 0x40 n: ACC +0, RDATA +0x14,
 *                VLD_CLR +0x24, STA +0x28 (stock spmi-mtk-pmif.ko table for
 *                mediatek,mt6855-spmi); ACC = opc << 30 | wr << 29 | sid << 24
 *                | (bytes - 1) << 16 | addr, opc 3 = extended long read;
 *                STA bits 3:1 = 0 idle, 6 wait-for-valid-clear.
 */
#define KPD         0x1c00e000UL
#define PMIF        0x1c804000UL

static int spmi_rd(u32 ch, u32 sid, u32 addr, u32 *out)
{
    u64 b = PMIF + 0x800 + 0x40 * ch;
    u64 end = ticks() + freq() / 100;
    while (((r32(b + 0x28) >> 1) & 7) != 0)
        if (ticks() > end)
            return -1;
    w32(b, (3U << 30) | (sid << 24) | (0U << 16) | (addr & 0xffff));
    end = ticks() + freq() / 100;
    while (((r32(b + 0x28) >> 1) & 7) != 6)
        if (ticks() > end)
            return -2;
    *out = r32(b + 0x14);
    w32(b + 0x24, 1);
    return 0;
}

static void key_scan(void)
{
    puts_("KEYS\n", GREEN);
    puts_(" SWINF STA", GREEN);
    for (u32 ch = 0; ch < 4; ch++)
        puts_(" ", WHITE), hex(r32(PMIF + 0x828 + 0x40 * ch), 4, WHITE);
    puts_("\n", WHITE);
    u32 ch = 0, v = 0;
    int rc = -9;
    for (ch = 0; ch < 4; ch++) {
        rc = spmi_rd(ch, 4, 0x1e, &v);
        if (rc == 0)
            break;
    }
    puts_(" PMIC ", GREEN);
    kv("CH", ch, 1);
    kv("RC", (u32)rc & 0xff, 2);
    kv("TOP", v, 8);
    puts_("\n PRESS POWER, VOL UP, VOL DOWN (BRIEFLY, 25 S)\n", GREEN);
    u32 lx = cx, ly = cy;
    u64 end = ticks() + 25 * freq();
    u32 last_t = 0xffffffffU, last_k = 0xffffffffU;
    while (ticks() < end) {
        u32 t = 0;
        int r = (ch < 4) ? spmi_rd(ch, 4, 0x1e, &t) : -9;
        u32 k = r32(KPD + 0x04);
        if (t != last_t || k != last_k) {
            last_t = t;
            last_k = k;
            cx = lx;
            cy = ly;
            kv(" TOP", r ? 0xeeU : (t & 0xff), 2);
            puts_(r == 0 && !(t & 2) ? " POWER " : "       ", 0xffffff00U);
            puts_(r == 0 && !(t & 8) ? "VDOWN " : "      ", 0xffffff00U);
            kv("KP", k & 0xffff, 4);
            puts_(!(k & 1) ? " VUP " : "     ", 0xffffff00U);
            kv("STA", r32(KPD) & 0xffff, 4);
        }
        kick();
        delay_us(20000);
    }
    cx = 0;
    cy = ly + 36;
}
#endif /* KEY_SCAN */

static void ufs_diag_fix(void)
{
    puts_("UFS ", GREEN);
    kv("HCE", r32(UFS + U_HCE), 8);
    kv("HCS", r32(UFS + U_HCS), 8);
    kv("IS", r32(UFS + U_IS), 8);
    puts_("\n", WHITE);
    ufs_vendor_line();
    ufs_link_line("    BEFORE ");
    if (ufs_peer_ok())
        return;
    if ((r32(UFS + U_REFCLK) & 1) == 0) {  /* E10: already on (3) on the G54 */
        w32(UFS + U_REFCLK, 1);                    /* request the reference clock */
        u64 end = ticks() + freq() / 100;          /* 10 ms; Linux allows 3 ms */
        while (((r32(UFS + U_REFCLK) >> 1) & 1) != 1 && ticks() < end)
            ;
        puts_("    REFCLK ON ", GREEN);
        kv("NOW", r32(UFS + U_REFCLK), 8);
        puts_("\n", WHITE);
        wait_s(1);
    }
    u32 lpm = 0, spc = 0;
    u32 r1 = ufs_uic(0x01, 0xd0a8U << 16, &lpm);
    u32 r2 = ufs_uic(0x01, 0xd0a6U << 16, &spc);
    puts_("    VS ", GREEN);
    kv("PWRDN", r1 ? 0xee : lpm, 2);
    kv("SAVEPWR", r2 ? 0xee : spc, 8);
    puts_("\n", WHITE);

    int stop = hce_set(0);                         /* ufshcd_hba_stop */
    u64 lo = mtk_ufs_smc(2, 0);
    delay_us(20);
    u64 hi = mtk_ufs_smc(2, 1);
    delay_us(15000);
    int start = hce_set(1);
    u64 end = ticks() + freq() / 10;
    while (!(r32(UFS + U_HCS) & HCS_UCRDY) && ticks() < end)
        ;
    puts_("    RESET ", GREEN);
    kv("STOP", stop, 1);
    kv("LO", lo, 2);
    kv("HI", hi, 2);
    kv("START", start, 1);
    kv("HCS", r32(UFS + U_HCS), 8);
    puts_("\n", WHITE);

    u32 a1 = dme_set(0xd0a8, 0, 0);                /* UniPro out of LPM */
    u32 a2 = dme_set(0x155e, 0, 0);                /* host TX LCC off */
    u32 a3 = 0xee;
    if (ufs_uic(0x01, 0xd0a6U << 16, &spc) == 0)
        a3 = dme_set(0xd0a6, 0, spc & ~(1U << 6));
    puts_("    PRELINK ", GREEN);
    kv("LPM", a1, 2);
    kv("LCC", a2, 2);
    kv("SAVE", a3, 2);
    puts_("\n", WHITE);
    int up = ufs_linkstartup();
    ufs_link_line("    AFTER  ");
    if (up)
        ufs_dev_init();
#ifdef UFS_HS
    if (up)
        ufs_hs();
#endif
}

#endif /* UFS_FIX */

/* ---- XNU loader (SWEETXNU payload, topaz tools/mkpayload.py format) ---- */
/*
 * Layout (from mkpayload.py at the pinned ios-topaz BASE_SHA): "SWEETXNU",
 * u32 version=1, nsegs; u64 virt_base, entry_va, adt_off, adt_size,
 * kernel_end_va, phys_base, mem_size; char cmdline[608]; then at 0x2a8
 * nsegs x {u64 vmaddr, vmsize, file_off, file_size}. boot_args is
 * pexpert/pexpert/arm64/boot.h Revision 2 / Version 2 (736 bytes).
 */
#define PL_SEGS     0x2a8
#define BOOT_LINE   608
#define PAGE16K     0x4000UL
#define LCD_FB      0xfeac6000UL   /* visible LK layer (E4) */
#define LCD_PITCH   4320U

static u64 rd64(u64 a) { return *(volatile u64 *)a; }
static void wr64(u64 a, u64 v) { *(volatile u64 *)a = v; }

static u64 find_payload(u64 from)
{
    for (u64 a = (from + 0xfff) & ~0xfffUL; a < from + 0x200000; a += 0x1000) {
        const volatile u8 *m = (const volatile u8 *)a;
        if (m[0] == 'S' && m[1] == 'W' && m[2] == 'E' && m[3] == 'E' && m[4] == 'T' &&
            m[5] == 'X' && m[6] == 'N' && m[7] == 'U')
            return a;
    }
    return 0;
}

static void copy64(u64 dst, u64 src, u64 n)
{
    for (u64 i = 0; i < (n + 7) / 8; i++) {
        wr64(dst + 8 * i, rd64(src + 8 * i));
        if ((i & 0x3ffff) == 0)
            kick();
    }
}

static void zero64(u64 dst, u64 n)
{
    for (u64 i = 0; i < n / 8; i++) {
        wr64(dst + 8 * i, 0);
        if ((i & 0x3ffff) == 0)
            kick();
    }
}

/* Returns only on error, with a reason. */
static const char *load_xnu(u64 pl)
{
    u32 version = r32(pl + 8), nsegs = r32(pl + 12);
    u64 virt_base = rd64(pl + 0x10), entry_va = rd64(pl + 0x18);
    u64 adt_off = rd64(pl + 0x20), adt_size = rd64(pl + 0x28), kend = rd64(pl + 0x30);
    u64 phys_base = rd64(pl + 0x38), mem_size = rd64(pl + 0x40);
    if (version != 1 || nsegs == 0 || nsegs > 32 || (adt_off & 7))
        return "BAD PAYLOAD HEADER";
    /* The G54 window chosen from E4: inside free 0x140000000+0xffe00000. */
    if (phys_base < 0x140000000UL || phys_base + mem_size > 0x23fe00000UL)
        return "PHYS WINDOW NOT IN FREE RAM";
    u64 off = phys_base - virt_base;  /* pa = va + off */

    for (u32 i = 0; i < nsegs; i++) {
        u64 s = pl + PL_SEGS + 32 * i;
        u64 va = rd64(s), vmsize = rd64(s + 8), foff = rd64(s + 16), fsize = rd64(s + 24);
        u64 dst = va + off;
        if (dst < phys_base || dst + vmsize > phys_base + mem_size || fsize > vmsize)
            return "SEGMENT OUTSIDE WINDOW";
        copy64(dst, pl + foff, fsize);
        u64 done = (fsize + 7) & ~7UL;
        if (vmsize > done)
            zero64(dst + done, vmsize - done);
    }
    u64 adt_pa = kend + off;
    copy64(adt_pa, pl + adt_off, adt_size);
    u64 ba = (adt_pa + adt_size + PAGE16K - 1) & ~(PAGE16K - 1);
    u64 top = ba + PAGE16K;
    zero64(ba, PAGE16K);
    /* struct boot_args (Revision 2, Version 2) */
    *(volatile unsigned short *)(ba + 0) = 2;
    *(volatile unsigned short *)(ba + 2) = 2;
    wr64(ba + 8, virt_base);
    wr64(ba + 16, phys_base);
    wr64(ba + 24, mem_size);
    wr64(ba + 32, top);
    wr64(ba + 40, LCD_FB);          /* Video.v_baseAddr */
    wr64(ba + 48, 1);               /* v_display */
    wr64(ba + 56, LCD_PITCH);       /* v_rowBytes */
    wr64(ba + 64, FB_W);
    wr64(ba + 72, FB_H);
    wr64(ba + 80, 32);              /* v_depth */
    /* machineType u32 at 88; deviceTreeP u64 at 96 (a VA); deviceTreeLength u32 at 104 */
    wr64(ba + 96, adt_pa - off);
    w32(ba + 104, (u32)adt_size);
    for (u32 i = 0; i < BOOT_LINE; i += 4)  /* CommandLine at 108 */
        w32(ba + 108 + i, r32(pl + 0x48 + i));
    /* bootFlags u64 at 720 (0), memSizeActual u64 at 728 */
    wr64(ba + 728, mem_size);

    puts_("JUMP ", GREEN);
    hex(entry_va + off, 9, WHITE);
    puts_(" BA ", GREEN);
    hex(ba, 9, WHITE);
    puts_("\n", WHITE);

    /* XNU has no watchdog driver this early: stop LK's (key 0x22000000,
     * enable bit clear), as ruby's shim does. A hang then stays on screen. */
    w32(WDT_BASE + WDT_MODE, 0x22000000U | (r32(WDT_BASE + WDT_MODE) & 0x7eU));
    /* Any PSCI SYSTEM_RESET from XNU (patch 0201 g54panicreset) now lands in
     * Fastboot (E2). */
    w32(WDT_BASE + WDT_NONRST2, (r32(WDT_BASE + WDT_NONRST2) & ~RB_MODE_MASK) | RB_MODE_BOOTLOADER);
    __asm__ volatile("dsb sy; ic iallu; dsb sy; isb" ::: "memory");
    register u64 x0 __asm__("x0") = ba;
    register u64 x1 __asm__("x1") = entry_va + off;
    __asm__ volatile("br x1" ::"r"(x0), "r"(x1));
    return "XNU RETURNED";
}

/* ---- return to Fastboot ---- */

static void psci_system_reset(void)
{
    register u64 x0 __asm__("x0") = 0x84000009UL;
    __asm__ volatile("smc #0" : "+r"(x0)::"x1", "x2", "x3", "memory");
}

static void reboot_bootloader(void)
{
    u32 m = r32(WDT_BASE + WDT_NONRST2);
    w32(WDT_BASE + WDT_NONRST2, (m & ~RB_MODE_MASK) | RB_MODE_BOOTLOADER);
    __asm__ volatile("dsb sy" ::: "memory");
    psci_system_reset();
    for (int i = 0; i < 20; i++) {
        w32(WDT_BASE + WDT_SWRST, WDT_SWRST_KEY);
        u64 end = ticks() + freq() / 20;
        while (ticks() < end)
            ;
    }
}

static struct handoff h;

extern char _end[];

void probe_main(u64 dtb, u64 pc)
{
    kick();
    parse_dtb(dtb, &h);
    if (h.have_fb)
        fill(&h.fb, MAGENTA);
    wait_s(PHASE1_S);
#ifdef TEST_FAULT
    __asm__ volatile("brk #0");  /* emulation test of the exception path */
#endif
    if (h.have_fb) {
        fill(&h.fb, BLACK);
        find_scanout(&h.fb);
        fb_end = h.fb.base + h.fb.size;
        for (int i = 0; i < ncand; i++) {
            fb_base = cands[i].addr;
            pitch = cands[i].pitch;
            info_screen(&h, pc, i);
            kick();
        }
        fb_base = cands[0].addr;  /* the visible layer (OVL0 L1 on the G54) */
        pitch = cands[0].pitch;
    }

    u64 pl = find_payload((u64)_end);
#ifdef UFS_FIX
    ufs_diag_fix();
#endif
#ifdef TOUCH_SPI
    touch_spi();
#endif
#ifdef TOUCH_FW
    touch_fw();
#endif
#ifdef KEY_SCAN
    key_scan();
#endif
    if (pl) {
        puts_("\nSWEETXNU PAYLOAD AT ", GREEN);
        hex(pl, 9, WHITE);
        puts_("\n", WHITE);
        wait_s(LOADER_S);
        const char *why = load_xnu(pl);
        puts_("LOADER FAILED: ", 0xffff0000U);
        puts_(why, WHITE);
        puts_("\n", WHITE);
    }
    wait_s(INFO_S);
    if (h.have_fb)
        fill(&h.fb, GREEN);
    wait_s(PHASE2_S);
    reboot_bootloader();
    for (;;)
        __asm__ volatile("wfe");
}

/* Any exception (vectors in entry.S): red screen for 5 s, then Fastboot.
 * Keeps a faulting experiment from hanging until the watchdog boots it again. */
void exc_main(void)
{
    if (h.have_fb)
        fill(&h.fb, 0xffff0000U);
    wait_s(5);
    reboot_bootloader();
    for (;;)
        __asm__ volatile("wfe");
}
