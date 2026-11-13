// G54 multiboot stub: a key menu in boot_a that starts either iOS 16.7.16
// (XNU) or the stock Android kernel that shares the image, or returns to
// Fastboot.
//
// Reuse, not reimplementation: this file includes payload/g1/probe.c, the
// probe/loader that booted iOS in E20-E37b, as one translation unit.
//   * iOS entry  = probe_main(), unchanged, built with the E37b "fast probe"
//                  flags (UFS_FIX UFS_HS TOUCH_SPI TOUCH_FW TOUCH_TEST_S=0
//                  NO_RESV PHASE1_S=1 LOADER_S=1; scripts/g54_multiboot.py
//                  build forces them). It finds the touch firmware and the
//                  SWEETXNU payload after _end exactly as in a probe image.
//   * DTB, framebuffer, text, Fastboot reset, exception screen: probe.c
//     (parse_dtb, find_scanout, puts_, reboot_bootloader, exc_main).
//   * Keys: probe.c spmi_rd/spmi_wr on the AP channel SWINF 2 (E27/E28) and
//     KPD KP_MEM1 bit 0; MT6363 PSC acknowledgement as kernel patch 0203
//     gk_pmic_ack (E31/E32: without it a power press powers the phone off
//     ~79 s later).
// New here: the menu, the /chosen + bootconfig scan, the image self-check
// and linux_boot (entry.S). None of it has run on the phone yet; see
// docs/multiboot-feasibility.md for what is proven and the next experiments.
//
// SPDX-License-Identifier: MIT

#ifndef G54_MULTIBOOT
#error "build with scripts/g54_multiboot.py build (it defines G54_MULTIBOOT and the probe flags)"
#endif
#if !defined(UFS_FIX) || !defined(UFS_HS) || !defined(TOUCH_SPI) || !defined(TOUCH_FW)
#error "the iOS entry needs the proven E37b probe flags: UFS_FIX UFS_HS TOUCH_SPI TOUCH_FW"
#endif

#include "../g1/probe.c"

#define RED     0xffff0000U
#define YELLOW  0xffffff00U
#define CYAN    0xff00ffffU

/* Mirrors mb_hdr in entry.S (stub + 0x08) and HDR in g54_multiboot.py. */
struct mb_header {
    char magic[8];
    u32 version, hdr_size;
    u64 stub_off;
    u32 orig_code0, default_item, timeout_s, flags;
    u64 blob_size, stub_end, image_id;
};
extern const struct mb_header mb_hdr;
extern char _start[];
extern void linux_boot(u64 dtb, u64 image_base, u32 code0) __attribute__((noreturn));

#define MBF_RECOVERY_PASS   (1U << 0)   /* LK booted recovery/FastbootD: no menu, straight to Linux */
#define MBF_ANDROID         (1U << 1)   /* userdata holds Android: offer the Android entry */

enum { IT_IOS, IT_ANDROID, IT_FASTBOOT, N_IT };
enum { MODE_UNKNOWN, MODE_NORMAL, MODE_RECOVERY };

/* ---- what LK prepared for Linux: /chosen and the bootconfig trailer ---- */

struct chosen {
    const volatile u8 *args, *bc;
    u32 args_len, bc_len;
    u64 initrd_start, initrd_end;
};
static struct chosen ch;

static u64 cell(const volatile u8 *p, u32 len)
{
    return len == 8 ? be64(p) : len == 4 ? be32(p) : 0;
}

/* /chosen bootargs and linux,initrd-start/-end; parse_dtb() validated the header. */
static void scan_chosen(u64 dtb)
{
    if (!h.dtb_size)
        return;
    const volatile u8 *b = (const volatile u8 *)dtb;
    u32 total = h.dtb_size, off_struct = be32(b + 8), off_str = be32(b + 12);
    const volatile u8 *p = b + off_struct, *end = b + total;
    int depth = 0, in_chosen = 0;
    for (u32 guard = 0; guard < 400000U && p + 4 <= end; guard++) {
        u32 tok = be32(p);
        p += 4;
        if (tok == FDT_BEGIN_NODE) {
            depth++;
            if (depth == 2)
                in_chosen = streq(p, "chosen");
            while (p < end && *p)
                p++;
            p = (const volatile u8 *)(((u64)p + 4) & ~3UL);
        } else if (tok == FDT_END_NODE) {
            if (depth == 2)
                in_chosen = 0;
            depth--;
        } else if (tok == FDT_PROP) {
            if (p + 8 > end)
                return;
            u32 len = be32(p), nameoff = be32(p + 4);
            p += 8;
            if (off_str + nameoff >= total || p + len > end)
                return;
            const volatile u8 *name = b + off_str + nameoff;
            if (depth == 2 && in_chosen) {
                if (streq(name, "bootargs")) {
                    ch.args = p;
                    ch.args_len = len;
                } else if (streq(name, "linux,initrd-start")) {
                    ch.initrd_start = cell(p, len);
                } else if (streq(name, "linux,initrd-end")) {
                    ch.initrd_end = cell(p, len);
                }
            }
            p += (len + 3) & ~3U;
        } else if (tok == FDT_NOP) {
            continue;
        } else {
            break;
        }
    }
}

static u32 le32(const volatile u8 *p)
{
    return p[0] | ((u32)p[1] << 8) | ((u32)p[2] << 16) | ((u32)p[3] << 24);
}

/* Linux Documentation/admin-guide/bootconfig.rst: initrd ends with the
 * bootconfig text, le32 size, le32 checksum, "#BOOTCONFIG\n". Boot header
 * v4 bootloaders pass androidboot.* there instead of the command line. */
static void scan_bootconfig(void)
{
    u64 e = ch.initrd_end;
    if (e < ch.initrd_start + 20 || e < DRAM_LO + 20 || e > DRAM_HI)
        return;
    const volatile u8 *t = (const volatile u8 *)(e - 12);
    if (!starts(t, "#BOOTCONFIG"))
        return;
    u32 size = le32((const volatile u8 *)(e - 20));
    if (size == 0 || size > 0x40000 || e - 20 - size < ch.initrd_start)
        return;
    ch.bc = (const volatile u8 *)(e - 20 - size);
    ch.bc_len = size;
}

static int find_n(const volatile u8 *a, u32 len, const char *s)
{
    if (!a)
        return 0;
    for (u32 i = 0; i < len; i++) {
        u32 j = 0;
        while (s[j] && i + j < len && a[i + j] == (u8)s[j])
            j++;
        if (!s[j])
            return 1;
    }
    return 0;
}

/* Hypothesis (docs/multiboot-feasibility.md H5): on a normal boot LK sets
 * androidboot.force_normal_boot=1; recovery and FastbootD boots omit it. */
static int boot_mode(void)
{
    int seen = find_n(ch.args, ch.args_len, "androidboot.") || find_n(ch.bc, ch.bc_len, "androidboot.");
    int normal = find_n(ch.args, ch.args_len, "androidboot.force_normal_boot=1") ||
                 find_n(ch.bc, ch.bc_len, "androidboot.force_normal_boot = \"1\"") ||
                 find_n(ch.bc, ch.bc_len, "androidboot.force_normal_boot=\"1\"") ||
                 find_n(ch.bc, ch.bc_len, "androidboot.force_normal_boot=1");
    if (!seen)
        return MODE_UNKNOWN;
    return normal ? MODE_NORMAL : MODE_RECOVERY;
}

/* ---- is the image in RAM the one the packer wrote? ---- */

struct layout {
    u64 image_base, end;
    u64 payload, fw;
    const char *android_why, *ios_why;   /* 0 = entry usable */
};
static struct layout lay;

static int overlaps(u64 a, u64 an, u64 b, u64 bn)
{
    return an && bn && a < b + bn && b < a + an;
}

static void check_layout(u64 dtb, u64 stub_base)
{
    u64 stub_end = (u64)_end - stub_base;
    lay.image_base = stub_base - mb_hdr.stub_off;
    lay.end = (u64)_end + mb_hdr.blob_size;
    if (!(mb_hdr.flags & MBF_ANDROID))
        lay.android_why = "PACKED WITH USERDATA = IOS";
    if (mb_hdr.stub_end != stub_end || mb_hdr.blob_size < 16) {
        lay.ios_why = lay.android_why = "BAD MULTIBOOT HEADER";
        return;
    }
    /* Trailer written by the packer as the last 16 raw bytes, with this
     * image's ID: if LK copied less than the whole raw kernel, it is missing
     * (H1), and a warm reset's leftover of another image does not match. */
    const volatile u8 *t = (const volatile u8 *)(lay.end - 16);
    if (!starts(t, "G54MBEND") || rd64(lay.end - 8) != mb_hdr.image_id) {
        lay.ios_why = "IMAGE TAIL MISSING (TRUNCATED?)";
        return;
    }
    u64 sb = stub_base, sn = lay.end - stub_base;
    u64 lb = lay.image_base, ln = mb_hdr.stub_off;
    u64 rs = ch.initrd_start, rn = ch.initrd_end > rs ? ch.initrd_end - rs : 0;
    if (overlaps(dtb, h.dtb_size, lb, ln) || overlaps(rs, rn, lb, ln))
        lay.android_why = "DTB/INITRD OVER LINUX";
    if (overlaps(dtb, h.dtb_size, sb, sn) || overlaps(rs, rn, sb, sn)) {
        lay.ios_why = "DTB/INITRD OVER PAYLOAD";
        return;
    }
    u64 pl = find_payload((u64)_end), fw = find_fw((u64)_end);
    lay.payload = pl && pl + 0x2a8 <= lay.end ? pl : 0;
    lay.fw = fw && fw < lay.end ? fw : 0;
    if (!lay.payload)
        lay.ios_why = "NO SWEETXNU PAYLOAD";
}

/* ---- keys (E27/E28, kernel 0203) ---- */

#define K_UP    1U
#define K_DOWN  2U
#define K_PWR   4U

static u32 keys_raw(void)
{
    u32 k = 0, top = 0xff;
    if (!(r32(KPD + 0x04) & 1))                    /* KP_MEM1 bit 0, 0 = volume up pressed */
        k |= K_UP;
    if (spmi_rd(2, 4, 0x1e, &top) == 0) {          /* MT6363 TOPSTATUS via SWINF 2 */
        if (!(top & 2))
            k |= K_PWR;
        if (!(top & 8))
            k |= K_DOWN;
    }
    return k;
}

/* Kernel 0203 gk_pmic_ack(false): write back the PSC status, then 0x41b = 1. */
static void psc_ack(void)
{
    u32 any = 0;
    for (u32 r = 0x91b; r <= 0x91c; r++) {
        u32 v = 0;
        if (spmi_rd(2, 4, r, &v) == 0 && (v & 0xff)) {
            spmi_wr(2, 4, r, v & 0xff);
            any |= v & 0xff;
        }
    }
    if (any)
        spmi_wr(2, 4, 0x41b, 1);
}

/* ---- menu ---- */

static const char *item_name(int it)
{
    if (it == IT_IOS)
        return "IOS 16.7.16";
    if (it == IT_ANDROID)
        return "ANDROID";
    return "FASTBOOT";
}

static const char *item_why(int it)
{
    if (it == IT_IOS)
        return lay.ios_why;
    if (it == IT_ANDROID)
        return lay.android_why;
    return 0;
}

static void band(u32 y, u32 rows)
{
    for (u32 r = y; r < y + rows && r < FB_H; r++) {
        volatile u64 *p = (volatile u64 *)(fb_base + (u64)r * pitch);
        for (u32 i = 0; i < FB_W / 2; i++)
            p[i] = ((u64)BLACK << 32) | BLACK;
    }
}

static void dec(u32 v, u32 color)
{
    char d[4] = {0, 0, 0, 0};
    int n = 0;
    do {
        d[n++] = (char)('0' + v % 10);
        v /= 10;
    } while (v && n < 3);
    while (n)
        putc_(d[--n], color);
}

#define Y_ITEMS 160U
#define Y_STEP  72U
#define Y_HELP  (Y_ITEMS + 3 * Y_STEP + 40)
#define Y_AUTO  (Y_HELP + 2 * 36 + 24)
#define Y_DIAG  1500U

/* text.h has no '>' glyph (and changing it would change every probe image):
 * the selection marker is a solid square. */
static void draw_item(int it, int sel)
{
    if (!h.have_fb)
        return;
    sc = SCALE;
    u32 y = 12 + Y_ITEMS + it * Y_STEP;
    band(y, CH);
    if (it == sel)
        for (u32 dy = sc; dy < 7 * sc; dy++)
            for (u32 dx = 0; dx < 5 * sc; dx++)
                px(12 + dx, y + dy, YELLOW, pitch);
    cx = 2 * CW;
    cy = Y_ITEMS + it * Y_STEP;
    const char *why = item_why(it);
    puts_(item_name(it), why ? GREY : it == sel ? YELLOW : WHITE);
    if (why)
        puts_(" (OFF)", GREY);
}

static void draw_auto(int sel, int left)
{
    if (!h.have_fb)
        return;
    sc = SCALE;
    band(12 + Y_AUTO, CH);
    cx = 0;
    cy = Y_AUTO;
    if (left < 0) {
        puts_("AUTO-BOOT OFF", GREY);
        return;
    }
    puts_(item_name(sel), WHITE);
    puts_(" IN ", GREY);
    dec((u32)left, WHITE);
    puts_(" S", GREY);
}

static void draw_diag(u64 dtb, u64 stub_base, int mode)
{
    sc = 3;                                 /* small enough for 4 lines, big enough to photograph */
    cx = 0;
    cy = Y_DIAG;
    puts_("MODE ", GREEN);
    puts_(mode == MODE_RECOVERY ? "RECOVERY/FASTBOOTD" : mode == MODE_NORMAL ? "NORMAL" : "UNKNOWN", WHITE);
    puts_(ch.bc ? " (BOOTCONFIG)" : ch.args ? " (CMDLINE)" : " (NO ARGS)", GREY);
    puts_("\n", WHITE);
    kv("IMAGE", lay.image_base, 9);
    kv("STUB", stub_base, 9);
    kv("END", lay.end, 9);
    puts_("\n", WHITE);
    kv("DTB", dtb, 9);
    kv("SZ", h.dtb_size, 6);
    kv("INITRD", ch.initrd_start, 9);
    kv("-", ch.initrd_end, 9);
    puts_("\n", WHITE);
    kv("XNU", lay.payload, 9);
    kv("FW", lay.fw, 9);
    kv("FLAGS", mb_hdr.flags, 2);
    puts_("\n", WHITE);
    for (int it = 0; it < N_IT; it++)
        if (item_why(it)) {
            puts_(item_name(it), GREY);
            puts_(": ", GREY);
            puts_(item_why(it), RED);
            puts_("\n", WHITE);
        }
    sc = SCALE;
}

static void draw_menu(u64 dtb, u64 stub_base, int mode, int sel, int left)
{
    if (!h.have_fb)
        return;
    fill(&h.fb, BLACK);
    sc = 5;
    cx = 0;
    cy = 40;
    puts_("G54 MULTIBOOT", CYAN);
    for (int it = 0; it < N_IT; it++)
        draw_item(it, sel);
    sc = SCALE;
    cx = 0;
    cy = Y_HELP;
    puts_("VOL+ / VOL-  CHOOSE\nPOWER        START", GREY);
    draw_auto(sel, left);
    draw_diag(dtb, stub_base, mode);
}

/* ---- boot actions ---- */

static void zero_state(void)
{
    volatile u8 *p = (volatile u8 *)&h;   /* volatile: no memset call */
    for (u64 i = 0; i < sizeof(h); i++)
        p[i] = 0;
    ncand = 0;
}

static void start(int it, u64 dtb, u64 stub_base)
{
    if (it == IT_ANDROID) {
        if (h.have_fb)
            fill(&h.fb, BLACK);
        linux_boot(dtb, lay.image_base, mb_hdr.orig_code0);
    }
    if (it == IT_IOS) {
        /* The proven path, from the top: probe_main re-parses the DTB. */
        zero_state();
        sc = SCALE;
        probe_main(dtb, stub_base);
    }
    reboot_bootloader();
    for (;;)
        __asm__ volatile("wfe");
}

void mb_main(u64 dtb, u64 stub_base)
{
    kick();
    parse_dtb(dtb, &h);
    scan_chosen(dtb);
    scan_bootconfig();
    check_layout(dtb, stub_base);
    int mode = boot_mode();

    if ((mb_hdr.flags & MBF_RECOVERY_PASS) && mode == MODE_RECOVERY && !lay.android_why)
        start(IT_ANDROID, dtb, stub_base);

    if (h.have_fb) {
        find_scanout(&h.fb);
        fb_end = h.fb.base + h.fb.size;
        fb_base = cands[0].addr;            /* the visible layer (OVL0 L1, E4) */
        pitch = cands[0].pitch;
    }

    int sel = mb_hdr.default_item < N_IT ? (int)mb_hdr.default_item : IT_FASTBOOT;
    if (item_why(sel))
        sel = IT_FASTBOOT;
    int left = mb_hdr.timeout_s > 60 ? 60 : (int)mb_hdr.timeout_s;
    if (left == 0)
        left = -1;                          /* 0 = wait for a key */
    draw_menu(dtb, stub_base, mode, sel, left);

    u32 cand = keys_raw(), down = cand;     /* keys held at entry are not presses */
    u64 next = ticks() + freq();
    for (;;) {
        kick();
        delay_us(20000);
        psc_ack();
        u32 now = keys_raw(), press = 0;
        if (now == cand) {                  /* two equal samples 20 ms apart */
            press = now & ~down;
            down = now;
        }
        cand = now;
        if (press & (K_UP | K_DOWN)) {
            int prev = sel;
            do
                sel = (sel + (press & K_UP ? N_IT - 1 : 1)) % N_IT;
            while (item_why(sel));
            left = -1;                      /* a person is here: no auto-boot */
            draw_item(prev, sel);
            draw_item(sel, sel);
            draw_auto(sel, left);
        } else if (press & K_PWR) {
            break;
        }
        if (left > 0 && ticks() >= next) {
            next += freq();
            draw_auto(sel, --left);
            if (left == 0)
                break;
        }
    }
    start(sel, dtb, stub_base);
}
