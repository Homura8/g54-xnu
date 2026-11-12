// G54 G1 probe: prove that LK executed our code, without needing anyone to
// watch the phone.
//
//   1. Read the LK framebuffer from the DTB that LK hands over in x0
//      (/chosen atag,videolfb-*; fallback: reserved-memory *framebuffer*).
//   2. If it looks sane, paint it MAGENTA (identical in RGB and BGR order).
//   3. After PHASE1_S seconds paint it GREEN, after PHASE2_S more seconds
//      set the MT6855 watchdog reboot-mode to "bootloader" (3) and reset.
//
// LK then enters bootloader Fastboot with a reboot-mode reason, which the
// host sees over USB ~PHASE1_S+PHASE2_S seconds after boot. An LK rejection
// instead falls back to Fastboot immediately ("Failed to boot Linux...").
//
// Register facts come from the stock 5-8-6 vendor_boot DTB:
//   watchdog@1c007000 "mediatek,mt6855-wdt"; reboot-mode offset 0x24,
//   mask 0x0f, mode-bootloader = 3. Key values are upstream Linux
//   drivers/watchdog/mtk_wdt.c (WDT_RST 0x08/0x1971, WDT_SWRST 0x14/0x1209).
//   PSCI 1.0, method "smc" (fallback reset).
//
// Built freestanding with -mstrict-align: the MMU is off, so every data
// access is Device memory and must be naturally aligned.
//
// SPDX-License-Identifier: MIT

typedef unsigned char u8;
typedef unsigned int u32;
typedef unsigned long u64;

#define WDT_BASE        0x1c007000UL
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

#define MAGENTA         0xffff00ffU
#define GREEN           0xff00ff00U

#ifndef PHASE1_S
#define PHASE1_S 4
#endif
#ifndef DIAG_S
#define DIAG_S 25
#endif
#ifndef PHASE2_S
#define PHASE2_S 3
#endif

#define FDT_MAGIC       0xd00dfeedU
#define FDT_BEGIN_NODE  1U
#define FDT_END_NODE    2U
#define FDT_PROP        3U
#define FDT_NOP         4U
#define FDT_END         9U
#define FDT_MAX         0x400000U

static inline void w32(u64 a, u32 v) { *(volatile u32 *)a = v; }
static inline u32 r32(u64 a) { return *(volatile u32 *)a; }

/* Byte-wise big-endian read: safe for any alignment on Device memory. */
static u32 be32(const volatile u8 *p)
{
    return ((u32)p[0] << 24) | ((u32)p[1] << 16) | ((u32)p[2] << 8) | p[3];
}

static int streq(const volatile u8 *a, const char *b)
{
    while (*b)
        if (*a++ != (u8)*b++)
            return 0;
    return *a == 0;
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

static u64 ticks(void)
{
    u64 v;
    __asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(v));
    return v;
}

static u64 freq(void)
{
    u64 v;
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(v));
    return v ? v : 13000000UL;  /* MTK system counter is 13 MHz */
}

static void kick(void) { w32(WDT_BASE + WDT_RST, WDT_RST_KEY); }

static void wait_s(u64 s)
{
    u64 end = ticks() + s * freq();
    while (ticks() < end)
        kick();
}

struct fb {
    u64 base, size;
};

/* Walk the flattened tree once; collect videolfb props and a framebuffer
 * reservation. Bounded by totalsize and an iteration guard. */
static int find_fb(u64 dtb, struct fb *out)
{
    const volatile u8 *b = (const volatile u8 *)dtb;
    if (!dtb || dtb & 3 || dtb < DRAM_LO || dtb >= DRAM_HI)
        return 0;
    if (be32(b) != FDT_MAGIC)
        return 0;
    u32 total = be32(b + 4), off_struct = be32(b + 8), off_str = be32(b + 12);
    if (total < 40 || total > FDT_MAX || off_struct >= total || off_str >= total)
        return 0;

    const volatile u8 *p = b + off_struct, *end = b + total;
    int depth = 0, in_chosen = 0, in_fbnode = 0;
    u32 lo = 0, hi = 0, vram = 0, have_lo = 0, have_vram = 0;
    u64 rbase = 0, rsize = 0;

    for (u32 guard = 0; guard < 400000U && p + 4 <= end; guard++) {
        u32 tok = be32(p);
        p += 4;
        if (tok == FDT_BEGIN_NODE) {
            depth++;
            in_chosen = depth == 2 && streq(p, "chosen");
            in_fbnode = depth == 3 && contains(p, "framebuffer");
            while (p < end && *p)
                p++;
            p = (const volatile u8 *)(((u64)p + 4) & ~3UL);
        } else if (tok == FDT_END_NODE) {
            depth--;
            in_chosen = in_fbnode = 0;
        } else if (tok == FDT_PROP) {
            if (p + 8 > end)
                return 0;
            u32 len = be32(p), nameoff = be32(p + 4);
            p += 8;
            if (off_str + nameoff >= total || p + len > end)
                return 0;
            const volatile u8 *name = b + off_str + nameoff;
            if (in_chosen && len == 4) {
                if (streq(name, "atag,videolfb-fb_base_l")) {
                    lo = be32(p);
                    have_lo = 1;
                } else if (streq(name, "atag,videolfb-fb_base_h")) {
                    hi = be32(p);
                } else if (streq(name, "atag,videolfb-vramSize")) {
                    vram = be32(p);
                    have_vram = 1;
                }
            } else if (in_fbnode && len == 16 && streq(name, "reg")) {
                rbase = ((u64)be32(p) << 32) | be32(p + 4);
                rsize = ((u64)be32(p + 8) << 32) | be32(p + 12);
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
    if (base < DRAM_LO || size < FB_MIN || size > FB_MAX || base + size > DRAM_HI ||
        base & 0xfff)
        return 0;
    out->base = base;
    out->size = size;
    return 1;
}

static void fill(const struct fb *fb, u32 color)
{
    volatile u64 *p = (volatile u64 *)fb->base;
    u64 v = ((u64)color << 32) | color;
    for (u64 i = 0; i < fb->size / 8; i++) {
        p[i] = v;
        if ((i & 0xffff) == 0)
            kick();
    }
    /* MMU is off (non-cacheable), but clean anyway in case LK left the
     * D-cache enabled for this range. */
    for (u64 a = fb->base; a < fb->base + fb->size; a += 64)
        __asm__ volatile("dc civac, %0" ::"r"(a) : "memory");
    __asm__ volatile("dsb sy" ::: "memory");
}

/*
 * E1 (2026-11-12) showed the probe runs and the reset happens, but a direct
 * WDT_SWRST boots normally instead of entering Fastboot. Android's
 * `reboot bootloader` (which works) ends in PSCI SYSTEM_RESET, because Linux's
 * PSCI restart handler outranks mtk-wdt. E2 changes only that: PSCI first,
 * WDT_SWRST as fallback.
 */
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

/*
 * Diagnostic screen: four horizontal quarters, white = yes, black = no,
 * separated by green lines. Rows are computed modulo one 1088x2400x32bpp
 * screen (LK pitch on MediaTek = width aligned to 32 px; ruby observed 4352
 * bytes for 1080), so every screen-sized buffer in the region shows it.
 */
#define PITCH   (1088UL * 4UL)
#define ROWS    2400UL
#define SCREEN  (PITCH * ROWS)
#define WHITE   0xffffffffU
#define BLACK   0xff000000U

static void diag_screen(const struct fb *fb, const int yes[4])
{
    for (u64 base = fb->base; base + PITCH <= fb->base + fb->size; base += PITCH) {
        u64 row = ((base - fb->base) % SCREEN) / PITCH;
        u64 q = row / (ROWS / 4), in = row % (ROWS / 4);
        u32 c = (in < 12 || in >= ROWS / 4 - 12) ? GREEN : (yes[q] ? WHITE : BLACK);
        volatile u64 *p = (volatile u64 *)base;
        u64 v = ((u64)c << 32) | c;
        for (u64 i = 0; i < PITCH / 8; i++)
            p[i] = v;
        if ((row & 63) == 0)
            kick();
    }
    __asm__ volatile("dsb sy" ::: "memory");
}

static u32 current_el(void)
{
    u64 v;
    __asm__ volatile("mrs %0, CurrentEL" : "=r"(v));
    return (u32)(v >> 2) & 3;
}

void probe_main(u64 dtb)
{
    struct fb fb;
    int have_fb = find_fb(dtb, &fb);

    kick();
    if (have_fb)
        fill(&fb, MAGENTA);
    wait_s(PHASE1_S);

    /* Observe, then set the reboot mode (same write as reboot_bootloader). */
    u32 el = current_el();
    u32 mode = r32(WDT_BASE + 0x00);
    u32 before = r32(WDT_BASE + WDT_NONRST2);
    w32(WDT_BASE + WDT_NONRST2, (before & ~RB_MODE_MASK) | RB_MODE_BOOTLOADER);
    __asm__ volatile("dsb sy" ::: "memory");
    u32 after = r32(WDT_BASE + WDT_NONRST2);
    int yes[4] = {
        el == 2,                                  /* Q1: entered at EL2 */
        (mode & 1U) != 0,                         /* Q2: watchdog enabled by LK */
        (after & RB_MODE_MASK) == RB_MODE_BOOTLOADER, /* Q3: reboot-mode write stuck */
        before != 0xffffffffU && before != after, /* Q4: register readable and changed */
    };
    if (have_fb)
        diag_screen(&fb, yes);
    wait_s(DIAG_S);

    if (have_fb)
        fill(&fb, GREEN);
    wait_s(PHASE2_S);
    reboot_bootloader();
    for (;;)
        __asm__ volatile("wfe");
}
