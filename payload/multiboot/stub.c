// G54 Stage-1 Multiboot Chainloader (iOS 16.7.16 XNU + ColorOS/Android Linux).
//
// Hardware facts (verified in g54-xnu E1-E36):
//   - WDT TOPRGU: 0x1c007000 (WDT_RST 0x08 = 0x1971, NONRST2 0x24 low nibble 3 = fastboot)
//   - Display scanout: OVL0 0x14002000 L1 (0xfeac6000, pitch 4320, 1080x2400)
//   - Keys: KPD 0x1c00e000 KP_MEM1 (+0x1c) bit 0 = Vol Up;
//           MT6363 SPMI SID 4 via PMIF SWINF 2 (0x1c804000 + 0x880) reg 0x1e:
//             bit 1 = Power, bit 3 = Vol Down (active-low).
//           Must ACK MT6363 PSC IRQs (0x91b, 0x91c, 0x41b=1) to prevent 79s cold reset!
//   - UFS: 0x112b0000, SiP reset SMC 0xc2000276 (cmd 2 = DEVICE_RESET), HS-G3 PMC
//   - Novatek NT36672C SPI3: 0x11013000, pericfg_ao 0x11036000 bit 14, GPIO 0x10005000
//   - Free DRAM for trampoline: 0x50f00000 (E4)
//
// SPDX-License-Identifier: MIT

#include "text.h"

typedef unsigned char u8;
typedef unsigned int u32;
typedef unsigned long u64;

#define WDT_BASE            0x1c007000UL
#define WDT_RST             0x08U
#define WDT_RST_KEY         0x1971U
#define WDT_SWRST           0x14U
#define WDT_SWRST_KEY       0x1209U
#define WDT_NONRST2         0x24U
#define RB_MODE_MASK        0x0fU
#define RB_MODE_BOOTLOADER  0x3U

#define DRAM_LO             0x40000000UL
#define DRAM_HI             0x240000000UL
#define TRAMPOLINE_PA       0x50f00000UL

#define FB_W                1080U
#define FB_H                2400U
#define FB_PITCH            4320U
#define FB_MIN              (FB_W * FB_H * 4UL)
#define FB_MAX              0x4000000UL

#define BLACK               0xff000000U
#define WHITE               0xffffffffU
#define GREY                0xff909090U
#define GREEN               0xff22dd66U
#define CYAN                0xff33ccffU
#define YELLOW              0xffffdd33U
#define RED                 0xffff3333U

#define FDT_MAGIC           0xd00dfeedU
#define FDT_BEGIN_NODE      1U
#define FDT_END_NODE        2U
#define FDT_PROP            3U
#define FDT_NOP             4U
#define FDT_MAX             0x400000U

#define OVL0                0x14002000UL
#define OVL1                0x14004000UL
#define RDMA0               0x14006000UL

#define KPD_BASE            0x1c00e000UL
#define KPD_MEM1            0x1cU
#define PMIF_BASE           0x1c804000UL

#define UFS                 0x112b0000UL
#define U_IS                0x20
#define U_HCS               0x30
#define U_HCE               0x34
#define U_UTRLBA            0x50
#define U_UTRLBAU           0x54
#define U_UTRLDBR           0x58
#define U_UTRLRSR           0x60
#define U_UICCMD            0x90
#define U_ARG1              0x94
#define U_ARG2              0x98
#define U_ARG3              0x9c
#define U_REFCLK            0x144
#define HCS_UCRDY           (1U << 3)
#define IS_UPMS             (1U << 4)
#define IS_UCCS             (1U << 10)
#define IS_ULSS             (1U << 8)
#define UTP_BASE            0x50f01000UL
#define UTRD                (UTP_BASE)
#define UCD                 (UTP_BASE + 0x400)
#define UCD_RSP             0x200

#define SPI3                0x11013000UL
#define S_CFG0              0x00
#define S_CFG1              0x04
#define S_TX                0x10
#define S_RX                0x14
#define S_CMD               0x18
#define S_ST0               0x1c
#define S_PAD               0x24
#define S_CFG2              0x28
#define C_ACT               (1U << 0)
#define C_RST               (1U << 2)
#define C_PAUSE             (1U << 4)
#define C_MSB               ((1U << 12) | (1U << 13))
#define PERAO               0x11036000UL
#define GPIOB               0x10005000UL
#define NVT_SWRST           0x3f0feU
#define EVT                 0x22d00U

#define PL_SEGS             0x2a8
#define BOOT_LINE           608
#define PAGE16K             0x4000UL

struct mboot_hdr {
    char magic[8];          /* "G54MBOOT" */
    u32 version;
    u32 hdr_size;
    u64 image_base_delta;   /* stub_base - 0x40000000 */
    u32 orig_code0;
    u32 default_os;         /* 0 = iOS, 1 = ColorOS */
    u32 timeout_s;
    u32 flags;              /* bit 0: FastbootD/recovery auto-passthrough */
    u64 xnu_rel_off;        /* offset from stub_base to SWEETXNU */
    u64 xnu_size;
    u64 fw_rel_off;         /* offset from stub_base to NVTFWBIN */
};

extern char linux_trampoline[];
extern char linux_trampoline_end[];

static inline void w32(u64 a, u32 v) { *(volatile u32 *)a = v; }
static inline u32 r32(u64 a) { return *(volatile u32 *)a; }
static inline u64 rd64(u64 a) { return *(volatile u64 *)a; }
static inline void wr64(u64 a, u64 v) { *(volatile u64 *)a = v; }

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

static int contains_n(const volatile u8 *a, u32 len, const char *b)
{
    for (u32 i = 0; i < len && a[i]; i++) {
        u32 j = 0;
        while (b[j] && i + j < len && a[i + j] == (u8)b[j])
            j++;
        if (!b[j])
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
    return v ? v : 13000000UL;
}

static void kick(void) { w32(WDT_BASE + WDT_RST, WDT_RST_KEY); }

static void delay_us(u64 us)
{
    u64 end = ticks() + freq() * us / 1000000 + 1;
    while (ticks() < end)
        kick();
}

static void wait_s(u64 s)
{
    u64 end = ticks() + s * freq();
    while (ticks() < end)
        kick();
}

/* ---- DTB parsing & framebuffer ---- */

struct handoff {
    u64 fb_base, fb_size;
    int have_fb;
    int recovery_mode;
};
static struct handoff h;
static u64 scan_base, scan_end;
static u32 scan_pitch;
static u32 cx, cy, sc = 3;

static void parse_dtb(u64 dtb, struct handoff *out)
{
    const volatile u8 *b = (const volatile u8 *)dtb;
    if (!dtb || (dtb & 3) || dtb < DRAM_LO || dtb >= DRAM_HI || be32(b) != FDT_MAGIC)
        return;
    u32 total = be32(b + 4), off_struct = be32(b + 8), off_str = be32(b + 12);
    if (total < 40 || total > FDT_MAX || off_struct >= total || off_str >= total)
        return;
    const volatile u8 *p = b + off_struct, *end = b + total;
    int depth = 0, in_chosen = 0;
    u32 lo = 0, hi = 0, vram = 0, have_lo = 0, have_vram = 0;

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
                if (len == 4 && streq(name, "atag,videolfb-fb_base_l")) {
                    lo = be32(p);
                    have_lo = 1;
                } else if (len == 4 && streq(name, "atag,videolfb-fb_base_h")) {
                    hi = be32(p);
                } else if (len == 4 && streq(name, "atag,videolfb-vramSize")) {
                    vram = be32(p);
                    have_vram = 1;
                } else if (streq(name, "bootargs") && len > 0) {
                    /* LK sets force_normal_boot=1 on normal Android boots; recovery/fastbootd omits it. */
                    if (contains_n(p, len, "androidboot.") &&
                        !contains_n(p, len, "androidboot.force_normal_boot=1"))
                        out->recovery_mode = 1;
                }
            }
            p += (len + 3) & ~3U;
        } else if (tok == FDT_NOP) {
            continue;
        } else {
            break;
        }
    }
    u64 base = have_lo ? (((u64)hi << 32) | lo) : 0;
    if (base >= DRAM_LO && have_vram && vram >= FB_MIN && vram <= FB_MAX && !(base & 0xfff)) {
        out->fb_base = base;
        out->fb_size = vram;
        out->have_fb = 1;
    }
}

static void find_scanout(const struct handoff *ho)
{
    u64 addr = ho->fb_base;
    u32 pitch = FB_PITCH;
    const u64 ovls[2] = {OVL0, OVL1};
    for (int o = 0; o < 2; o++) {
        u32 src = r32(ovls[o] + 0x2c);
        for (u32 n = 0; n < 4; n++) {
            if (!(src & (1U << n)))
                continue;
            u64 a = r32(ovls[o] + 0xf40 + n * 0x20);
            u32 pit = r32(ovls[o] + 0x44 + n * 0x20) & 0xffffU;
            if (a >= ho->fb_base && a + FB_MIN <= ho->fb_base + ho->fb_size) {
                addr = a;
                if (pit >= FB_W * 4 && pit <= 8192)
                    pitch = pit;
                goto found;
            }
        }
    }
found:
    scan_base = addr;
    scan_pitch = pitch;
    scan_end = ho->fb_base + ho->fb_size;
}

static void fill_range(u64 base, u64 size, u32 color)
{
    volatile u64 *p = (volatile u64 *)base;
    u64 v = ((u64)color << 32) | color;
    for (u64 i = 0; i < size / 8; i++) {
        p[i] = v;
        if ((i & 0xffff) == 0)
            kick();
    }
    __asm__ volatile("dsb sy" ::: "memory");
}

static void px(u32 x, u32 y, u32 c)
{
    u64 a = scan_base + (u64)y * scan_pitch + (u64)x * 4;
    if (x < FB_W && y < FB_H && a + 4 <= scan_end)
        *(volatile u32 *)a = c;
}

static void putc_(char ch, u32 color)
{
    u32 cw = 6 * sc, ch_h = 9 * sc;
    if (ch == '\n') {
        cx = 0;
        cy += ch_h;
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
                for (u32 dy = 0; dy < sc; dy++)
                    for (u32 dx = 0; dx < sc; dx++)
                        px(24 + cx + c * sc + dx, 40 + cy + r * sc + dy, color);
    cx += cw;
    if (cx + cw > FB_W - 48) {
        cx = 0;
        cy += ch_h;
    }
}

static void puts_(const char *s, u32 color)
{
    while (*s)
        putc_(*s++, color);
}

/* ---- SPMI SWINF 2 + KPD + E31 PMIC PSC ACK ---- */

static int spmi_xfer(u32 opc, u32 sid, u32 addr, u32 *val, int write)
{
    u64 ch = PMIF_BASE + 0x800 + 2 * 0x40; /* AP owns SWINF 2 */
    u64 end = ticks() + freq() / 100;
    while (r32(ch + 0x28) & 1)
        if (ticks() > end)
            return -1;
    if (write)
        w32(ch + 0x04, *val & 0xff);
    w32(ch + 0x00, (opc << 30) | (write ? (1U << 29) : 0) | ((sid & 0xf) << 24) | (addr & 0xffff));
    end = ticks() + freq() / 100;
    while (r32(ch + 0x28) & 1)
        if (ticks() > end)
            return -2;
    if (!write && val)
        *val = r32(ch + 0x14) & 0xff;
    w32(ch + 0x24, 1);
    return 0;
}

static void pmic_ack_psc(void)
{
    u32 s1 = 0, s2 = 0, z = 1;
    spmi_xfer(3, 4, 0x91b, &s1, 0);
    spmi_xfer(3, 4, 0x91c, &s2, 0);
    if (s1)
        spmi_xfer(3, 4, 0x91b, &s1, 1);
    if (s2)
        spmi_xfer(3, 4, 0x91c, &s2, 1);
    if (s1 || s2)
        spmi_xfer(3, 4, 0x41b, &z, 1);
}

#define KEY_VUP     (1U << 0)
#define KEY_VDOWN   (1U << 1)
#define KEY_PWR     (1U << 2)

static u32 poll_keys(void)
{
    u32 mask = 0;
    if (!(r32(KPD_BASE + KPD_MEM1) & 1))
        mask |= KEY_VUP;
    u32 top = 0xff;
    if (spmi_xfer(3, 4, 0x1e, &top, 0) == 0) {
        if (!(top & (1U << 1)))
            mask |= KEY_PWR;
        if (!(top & (1U << 3)))
            mask |= KEY_VDOWN;
    }
    pmic_ack_psc();
    return mask;
}

/* ---- Reset to Fastboot ---- */

static void psci_system_reset(void)
{
    register u64 x0 __asm__("x0") = 0x84000009UL;
    __asm__ volatile("smc #0" : "+r"(x0) :: "x1", "x2", "x3", "memory");
}

static void reboot_bootloader(void)
{
    u32 m = r32(WDT_BASE + WDT_NONRST2);
    w32(WDT_BASE + WDT_NONRST2, (m & ~RB_MODE_MASK) | RB_MODE_BOOTLOADER);
    __asm__ volatile("dsb sy" ::: "memory");
    psci_system_reset();
    for (int i = 0; i < 20; i++) {
        w32(WDT_BASE + WDT_SWRST, WDT_SWRST_KEY);
        delay_us(50000);
    }
}

/* ---- UFS + Touch bring-up for iOS ---- */

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
    w32(UFS + U_UICCMD, 0x02);
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
    u64 end = ticks() + freq() / 50;
    while ((r32(UFS + U_HCE) & 1) != on)
        if (ticks() > end)
            return 0;
    return 1;
}

static u64 mtk_ufs_smc(u64 cmd, u64 val)
{
    register u64 x0 __asm__("x0") = 0xc2000276UL;
    register u64 x1 __asm__("x1") = cmd;
    register u64 x2 __asm__("x2") = val;
    register u64 x3 __asm__("x3") = 0;
    __asm__ volatile("smc #0" : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3) :: "x4", "x5", "x6", "x7",
                     "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17", "memory");
    return x0;
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

static u32 utp_send(void)
{
    w32(UTRD + 0, 1U << 28);
    w32(UTRD + 8, 0x0f);
    w32(UTRD + 16, (u32)UCD);
    w32(UTRD + 20, (u32)(UCD >> 32));
    w32(UTRD + 24, ((UCD_RSP / 4) << 16) | 0x80);
    w32(UTRD + 28, ((0x300 / 4) << 16) | 0);
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

static void ufs_bringup_hs(void)
{
    u32 v = 0;
    if (ufs_uic(0x03, 0x1571U << 16, &v) == 0)
        return;
    if ((r32(UFS + U_REFCLK) & 1) == 0) {
        w32(UFS + U_REFCLK, 1);
        delay_us(10000);
    }
    hce_set(0);
    mtk_ufs_smc(2, 0);
    delay_us(20);
    mtk_ufs_smc(2, 1);
    delay_us(15000);
    hce_set(1);
    u64 end = ticks() + freq() / 10;
    while (!(r32(UFS + U_HCS) & HCS_UCRDY) && ticks() < end)
        kick();
    dme_set(0xd0a8, 0, 0);
    dme_set(0x155e, 0, 0);
    u32 spc = 0;
    if (ufs_uic(0x01, 0xd0a6U << 16, &spc) == 0)
        dme_set(0xd0a6, 0, spc & ~(1U << 6));
    int up = 0;
    for (int i = 0; i < 3 && !up; i++) {
        w32(UFS + U_IS, IS_ULSS);
        u32 rc = ufs_uic(0x16, 0, 0);
        end = ticks() + freq() / 2;
        while (!(r32(UFS + U_HCS) & 1) && ticks() < end)
            ;
        w32(UFS + U_IS, r32(UFS + U_IS));
        if (rc == 0 && ufs_uic(0x03, 0x1571U << 16, &v) == 0)
            up = 1;
    }
    if (!up)
        return;
    for (u64 a = UTP_BASE; a < UTP_BASE + 0x1000; a += 8)
        *(volatile u64 *)a = 0;
    for (int i = 0; i < 10; i++) {
        upiu_hdr(0x00, 1, 0);
        if (utp_send() == 0 && rsp_byte(0) == 0x20)
            break;
        delay_us(10000);
    }
    upiu_hdr(0x16, 2, 0x81);
    ucd_byte(12, 0x06);
    ucd_byte(13, 0x01);
    utp_send();
    end = ticks() + freq() * 2;
    do {
        upiu_hdr(0x16, 3, 0x01);
        ucd_byte(12, 0x05);
        ucd_byte(13, 0x01);
        if (utp_send() == 0 && rsp_byte(6) == 0 && rsp_byte(23) == 0)
            break;
        delay_us(5000);
    } while (ticks() < end);
    w32(UFS + U_UTRLRSR, 0);
    w32(UFS + U_IS, r32(UFS + U_IS));

    /* Switch to HS-G3 */
    u32 lmax = 0, pmax = 0, tx = 0, rx = 0;
    ufs_uic(0x01, 0x1587U << 16, &lmax);
    ufs_uic(0x03, 0x1587U << 16, &pmax);
    ufs_uic(0x01, 0x1561U << 16, &tx);
    ufs_uic(0x01, 0x1581U << 16, &rx);
    u32 gear = lmax < pmax ? lmax : pmax;
    if (gear > 3)
        gear = 3;
    if (gear && tx && rx) {
        dme_set(0x1568, 0, gear);
        dme_set(0x1583, 0, gear);
        dme_set(0x156a, 0, 2);
        dme_set(0x1569, 0, 1);
        dme_set(0x1584, 0, 1);
        dme_set(0x1560, 0, tx);
        dme_set(0x1580, 0, rx);
        dme_set(0x15b0, 0, 0x1fff);
        dme_set(0x15b1, 0, 0xffff);
        dme_set(0x15b2, 0, 0x7fff);
        dme_set(0x15b3, 0, 0x1fff);
        dme_set(0x15b4, 0, 0xffff);
        dme_set(0x15b5, 0, 0x7fff);
        dme_set(0x2044, 0, 0x1fff);
        dme_set(0x2045, 0, 0xffff);
        dme_set(0x2046, 0, 0x7fff);
        w32(UFS + U_IS, IS_UPMS);
        if (dme_set(0x1571, 0, 0x11) == 0) {
            end = ticks() + freq() / 5;
            while (!(r32(UFS + U_IS) & IS_UPMS) && ticks() < end)
                kick();
            w32(UFS + U_IS, IS_UPMS);
        }
    }
}

static int spi_xfer(const u8 *tx, u32 len)
{
    w32(SPI3 + S_CMD, C_RST);
    w32(SPI3 + S_CMD, 0);
    w32(SPI3 + S_CMD, C_MSB);
    w32(SPI3 + S_PAD, 0);
    w32(SPI3 + S_CFG1, (r32(SPI3 + S_CFG1) & ~(0xff00U | 0x3ff0000U)) | (((len - 1) & 0x3ff) << 16));
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
    w32(SPI3 + S_CMD, C_MSB | C_PAUSE);
    return 1;
}

static void nvt_w(u32 a, const u8 *v, u32 n)
{
    u8 pg[3] = {0xff, (u8)(a >> 15), (u8)(a >> 7)};
    spi_xfer(pg, 3);
    u8 tx[32];
    tx[0] = (u8)((a & 0x7f) | 0x80);
    for (u32 i = 0; i < n; i++)
        tx[1 + i] = v[i];
    spi_xfer(tx, n + 1);
}

static void nvt_w1(u32 a, u8 v) { nvt_w(a, &v, 1); }

static u32 fw32(u64 fw, u32 i)
{
    const volatile u8 *p = (const volatile u8 *)fw;
    return p[i] | ((u32)p[i + 1] << 8) | ((u32)p[i + 2] << 16) | ((u32)p[i + 3] << 24);
}

static void touch_download(u64 tag)
{
    const volatile u8 *m = (const volatile u8 *)tag;
    if (!tag || m[0] != 'N' || m[1] != 'V' || m[2] != 'T' || m[3] != 'F')
        return;
    u32 fwsize = r32(tag + 8);
    u64 fw = tag + 16;
    u32 hdr = fw32(fw, 0);

    w32(PERAO + 0x2c, 1U << 14);
    w32(SPI3 + S_CMD, C_RST);
    w32(SPI3 + S_CMD, 0);
    w32(SPI3 + S_PAD, 0);
    w32(SPI3 + S_CMD, C_MSB);
    w32(SPI3 + S_CFG2, (31U << 16) | 31U);
    w32(SPI3 + S_CFG0, (63U << 16) | 63U);
    w32(SPI3 + S_CFG1, (r32(SPI3 + S_CFG1) & ~0xffU) | 63U);
    w32(SPI3 + S_CMD, C_MSB | C_PAUSE);
    u32 m9 = r32(GPIOB + 0x390), m0 = r32(GPIOB + 0x300);
    w32(GPIOB + 0x390, (m9 & ~0x000ffff0U) | 0x00022220U);
    w32(GPIOB + 0x300, m0 & ~0x0000f000U);
    w32(GPIOB + 0x004, 1U << 3);
    w32(GPIOB + 0x104, 1U << 3);
    delay_us(20000);

    nvt_w1(0x7fff80, 0x5a);
    delay_us(30000);
    nvt_w1(NVT_SWRST, 0x69);
    delay_us(35000);
    nvt_w1(0x3f310, 0x00);

    for (u32 k = 0; k < 2; k++) {
        u32 bin = fw32(fw, k * 12), sram = fw32(fw, k * 12 + 4), sz = fw32(fw, k * 12 + 8);
        for (u32 done = 0; sz && bin + sz + 1 <= fwsize && done < sz + 1;) {
            u32 n = 128 - ((sram + done) & 0x7f);
            if (n > 30) n = 30;
            if (n > sz + 1 - done) n = sz + 1 - done;
            u8 buf[30];
            for (u32 i = 0; i < n; i++) buf[i] = *(volatile u8 *)(fw + bin + done + i);
            nvt_w(sram + done, buf, n);
            done += n;
            kick();
        }
    }
    for (u32 pos = 0x30; pos + 16 <= hdr; pos += 16) {
        u32 sram = fw32(fw, pos), sz = fw32(fw, pos + 4), bin = fw32(fw, pos + 8);
        for (u32 done = 0; sz && bin + sz + 1 <= fwsize && done < sz + 1;) {
            u32 n = 128 - ((sram + done) & 0x7f);
            if (n > 30) n = 30;
            if (n > sz + 1 - done) n = sz + 1 - done;
            u8 buf[30];
            for (u32 i = 0; i < n; i++) buf[i] = *(volatile u8 *)(fw + bin + done + i);
            nvt_w(sram + done, buf, n);
            done += n;
            kick();
        }
    }
    u8 ilm_b[4] = {(u8)fw32(fw, 8), (u8)(fw32(fw, 8) >> 8), (u8)(fw32(fw, 8) >> 16), 0};
    u8 ilmd_b[4] = {(u8)fw32(fw, 4), (u8)(fw32(fw, 4) >> 8), (u8)(fw32(fw, 4) >> 16), 0};
    u8 ilmc_b[4] = {(u8)fw32(fw, 0x18), (u8)(fw32(fw, 0x18) >> 8), (u8)(fw32(fw, 0x18) >> 16), (u8)(fw32(fw, 0x18) >> 24)};
    u8 dlm_b[4] = {(u8)fw32(fw, 20), (u8)(fw32(fw, 20) >> 8), (u8)(fw32(fw, 20) >> 16), 0};
    u8 dlmd_b[4] = {(u8)fw32(fw, 16), (u8)(fw32(fw, 16) >> 8), (u8)(fw32(fw, 16) >> 16), 0};
    u8 dlmc_b[4] = {(u8)fw32(fw, 0x1c), (u8)(fw32(fw, 0x1c) >> 8), (u8)(fw32(fw, 0x1c) >> 16), (u8)(fw32(fw, 0x1c) >> 24)};
    nvt_w(0x3f118, ilm_b, 3);
    nvt_w(0x3f128, ilmd_b, 3);
    nvt_w(0x3f100, ilmc_b, 4);
    nvt_w(0x3f130, dlm_b, 3);
    nvt_w(0x3f12c, dlmd_b, 3);
    nvt_w(0x3f104, dlmc_b, 4);
    nvt_w1(0x3f30e, 0x80);
    nvt_w1(EVT + 0x60, 0x00);
    nvt_w1(EVT + 0x50, 0xae);
    nvt_w1(0x3f10d, 0x01);
    delay_us(50000);
}

static const char *launch_xnu(u64 pl)
{
    const volatile u8 *m = (const volatile u8 *)pl;
    if (!pl || m[0] != 'S' || m[1] != 'W' || m[2] != 'E' || m[3] != 'E' ||
        m[4] != 'T' || m[5] != 'X' || m[6] != 'N' || m[7] != 'U')
        return "NO SWEETXNU PAYLOAD";
    u32 version = r32(pl + 8), nsegs = r32(pl + 12);
    u64 virt_base = rd64(pl + 0x10), entry_va = rd64(pl + 0x18);
    u64 adt_off = rd64(pl + 0x20), adt_size = rd64(pl + 0x28), kend = rd64(pl + 0x30);
    u64 phys_base = rd64(pl + 0x38), mem_size = rd64(pl + 0x40);
    if (version != 1 || nsegs == 0 || nsegs > 32 || (adt_off & 7))
        return "BAD PAYLOAD HEADER";
    if (phys_base < 0x140000000UL || phys_base + mem_size > 0x23fe00000UL)
        return "PHYS WINDOW OUT OF RANGE";
    u64 off = phys_base - virt_base;
    for (u32 i = 0; i < nsegs; i++) {
        u64 s = pl + PL_SEGS + 32 * i;
        u64 va = rd64(s), vmsize = rd64(s + 8), foff = rd64(s + 16), fsize = rd64(s + 24);
        u64 dst = va + off;
        for (u64 k = 0; k < (fsize + 7) / 8; k++) {
            wr64(dst + 8 * k, rd64(pl + foff + 8 * k));
            if ((k & 0x3ffff) == 0) kick();
        }
        u64 done = (fsize + 7) & ~7UL;
        for (u64 k = 0; k < (vmsize - done) / 8; k++) {
            wr64(dst + done + 8 * k, 0);
            if ((k & 0x3ffff) == 0) kick();
        }
    }
    u64 adt_pa = kend + off;
    for (u64 k = 0; k < (adt_size + 7) / 8; k++)
        wr64(adt_pa + 8 * k, rd64(pl + adt_off + 8 * k));
    u64 ba = (adt_pa + adt_size + PAGE16K - 1) & ~(PAGE16K - 1);
    u64 top = ba + PAGE16K;
    for (u64 k = 0; k < PAGE16K / 8; k++)
        wr64(ba + 8 * k, 0);
    *(volatile unsigned short *)(ba + 0) = 2;
    *(volatile unsigned short *)(ba + 2) = 2;
    wr64(ba + 8, virt_base);
    wr64(ba + 16, phys_base);
    wr64(ba + 24, mem_size);
    wr64(ba + 32, top);
    wr64(ba + 40, scan_base ? scan_base : 0xfeac6000UL);
    wr64(ba + 48, 1);
    wr64(ba + 56, scan_pitch ? scan_pitch : FB_PITCH);
    wr64(ba + 64, FB_W);
    wr64(ba + 72, FB_H);
    wr64(ba + 80, 32);
    wr64(ba + 96, adt_pa - off);
    w32(ba + 104, (u32)adt_size);
    for (u32 i = 0; i < BOOT_LINE; i += 4)
        w32(ba + 108 + i, r32(pl + 0x48 + i));

    /* Set reboot-mode=3 so panics return to Fastboot (cleared on iOS Restart by 0207). */
    u32 m2 = r32(WDT_BASE + WDT_NONRST2);
    w32(WDT_BASE + WDT_NONRST2, (m2 & ~RB_MODE_MASK) | RB_MODE_BOOTLOADER);
    __asm__ volatile("dsb sy; ic iallu; dsb sy; isb" ::: "memory");
    register u64 x0 __asm__("x0") = ba;
    register u64 x1 __asm__("x1") = entry_va + off;
    __asm__ volatile("br x1" :: "r"(x0), "r"(x1));
    return "XNU RETURNED";
}

static void launch_linux(u64 dtb, u64 image_base, u32 orig_code0)
{
    if (h.have_fb)
        fill_range(h.fb_base, h.fb_size, BLACK);
    u64 sz = (u64)(linux_trampoline_end - linux_trampoline);
    const volatile u32 *src = (const volatile u32 *)linux_trampoline;
    volatile u32 *dst = (volatile u32 *)TRAMPOLINE_PA;
    for (u64 i = 0; i < (sz + 3) / 4; i++)
        dst[i] = src[i];
    __asm__ volatile("dsb sy; ic iallu; dsb sy; isb" ::: "memory");
    void (*tramp)(u64, u64, u32) = (void (*)(u64, u64, u32))TRAMPOLINE_PA;
    tramp(dtb, image_base, orig_code0);
}

/* ---- Boot menu & main ---- */

static void draw_menu(int sel, int secs_left, int have_xnu)
{
    if (!h.have_fb)
        return;
    fill_range(scan_base, FB_MIN, BLACK);
    cx = cy = 0;
    sc = 4;
    puts_("G54 MULTIBOOT\n\n", CYAN);
    sc = 3;
    puts_(sel == 0 ? "> [1] IOS 16.7.16 (XNU)" : "  [1] IOS 16.7.16 (XNU)",
          sel == 0 ? GREEN : WHITE);
    if (!have_xnu)
        puts_(" [MISSING]", RED);
    puts_("\n\n", WHITE);
    puts_(sel == 1 ? "> [2] COLOROS / ANDROID\n\n" : "  [2] COLOROS / ANDROID\n\n",
          sel == 1 ? GREEN : WHITE);
    puts_(sel == 2 ? "> [3] FASTBOOT\n\n\n" : "  [3] FASTBOOT\n\n\n",
          sel == 2 ? YELLOW : WHITE);
    puts_("VOL+ / VOL- : SELECT\n", GREY);
    puts_("POWER       : BOOT NOW\n", GREY);
    puts_("AUTO-BOOT IN ", GREY);
    putc_((char)('0' + (secs_left >= 0 && secs_left <= 9 ? secs_left : 0)), WHITE);
    puts_("S\n", GREY);
}

void mb_main(u64 dtb, u64 stub_base)
{
    kick();
    const struct mboot_hdr *hdr = (const struct mboot_hdr *)(stub_base + 8);
    u64 image_base = stub_base - hdr->image_base_delta;
    parse_dtb(dtb, &h);
    if (h.have_fb)
        find_scanout(&h);

    /* Fast-path recovery / FastbootD directly to Linux without menu delay. */
    if ((hdr->flags & 1U) && h.recovery_mode)
        launch_linux(dtb, image_base, hdr->orig_code0);

    int sel = (hdr->default_os <= 2U) ? (int)hdr->default_os : 0;
    int have_xnu = (hdr->xnu_rel_off != 0);
    int left = (int)(hdr->timeout_s > 9U ? 9U : hdr->timeout_s);
    u32 prev_keys = poll_keys();
    draw_menu(sel, left, have_xnu);

    u64 sec_ticks = freq();
    u64 next_tick = ticks() + sec_ticks;
    while (left > 0) {
        kick();
        u32 keys = poll_keys();
        u32 edge = keys & ~prev_keys;
        prev_keys = keys;
        if (edge & KEY_VUP) {
            sel = (sel + 2) % 3;
            left = 9;
            next_tick = ticks() + sec_ticks;
            draw_menu(sel, left, have_xnu);
        } else if (edge & KEY_VDOWN) {
            sel = (sel + 1) % 3;
            left = 9;
            next_tick = ticks() + sec_ticks;
            draw_menu(sel, left, have_xnu);
        } else if (edge & KEY_PWR) {
            break;
        }
        if (ticks() >= next_tick) {
            left--;
            next_tick += sec_ticks;
            if (left > 0)
                draw_menu(sel, left, have_xnu);
        }
        delay_us(15000);
    }

    if (sel == 2)
        reboot_bootloader();
    if (sel == 1)
        launch_linux(dtb, image_base, hdr->orig_code0);

    /* Boot iOS 16.7.16 */
    if (h.have_fb)
        fill_range(h.fb_base, h.fb_size, BLACK);
    ufs_bringup_hs();
    if (hdr->fw_rel_off)
        touch_download(stub_base + hdr->fw_rel_off);
    const char *err = launch_xnu(hdr->xnu_rel_off ? (stub_base + hdr->xnu_rel_off) : 0);
    if (h.have_fb) {
        cx = cy = 0;
        sc = 3;
        puts_("IOS LAUNCH FAILED: ", RED);
        puts_(err, WHITE);
        puts_("\nRETURNING TO FASTBOOT...\n", GREY);
    }
    wait_s(5);
    reboot_bootloader();
}

void exc_main(void)
{
    if (h.have_fb)
        fill_range(h.fb_base, h.fb_size, RED);
    wait_s(5);
    reboot_bootloader();
    for (;;)
        __asm__ volatile("wfe");
}
