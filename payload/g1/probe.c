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
