// G54 Stage-1 Multiboot Chainloader entry & Linux jump trampoline.
// Entered at 0x40000000 via patched Linux Image code0 (`b #stub_off`),
// with MMU off and x0 = DTB physical address from Motorola LK.
//
// SPDX-License-Identifier: MIT

    .section .text.entry, "ax"
    .global _start
_start:
    b       _real_start
    nop

// Fixed 64-byte header at stub_base + 0x08, patched by scripts/g54_multiboot.py.
    .section .text.hdr, "a"
    .global mb_hdr
mb_hdr:
    .ascii  "G54MBOOT"          // +0x00 magic
    .word   1                   // +0x08 version
    .word   64                  // +0x0c header size
    .quad   0                   // +0x10 image_base_delta (stub_off)
    .word   0                   // +0x18 orig_code0 (saved Linux Image[0..3])
    .word   0                   // +0x1c default_os (0=iOS, 1=ColorOS)
    .word   3                   // +0x20 timeout_s
    .word   1                   // +0x24 flags (bit 0: FastbootD/recovery passthrough)
    .quad   0                   // +0x28 xnu_rel_off (offset from _start to SWEETXNU)
    .quad   0                   // +0x30 xnu_size
    .quad   0                   // +0x38 fw_rel_off (offset from _start to NVTFWBIN)

    .text
_real_start:
    msr     daifset, #0xf
    mov     x19, x0             // DTB physical address from LK
    adr     x1, stack_top
    mov     sp, x1
    adr     x1, vectors
    mrs     x2, CurrentEL
    cmp     x2, #8
    b.eq    4f
    msr     vbar_el1, x1
    b       5f
4:  msr     vbar_el2, x1
5:  isb
    adr     x1, __bss_start
    adr     x2, __bss_end
1:  cmp     x1, x2
    b.hs    2f
    str     xzr, [x1], #8
    b       1b
2:  mov     x0, x19
    adr     x1, _start
    bl      mb_main
3:  wfe
    b       3b

    .balign 0x800
vectors:
    .rept   16
    .balign 0x80
    adr     x1, stack_top
    mov     sp, x1
    bl      exc_main
    b       .
    .endr

// Copied to free DRAM (0x50f00000) before launching Linux so head.S BSS
// clearing cannot overwrite running trampoline instructions.
// Args: x0 = dtb_pa, x1 = image_base, w2 = orig_code0
    .global linux_trampoline
    .global linux_trampoline_end
    .balign 8
linux_trampoline:
    str     w2, [x1]
    dc      cvau, x1
    dsb     sy
    ic      iallu
    dsb     sy
    isb
    mov     x4, x1
    mov     x1, xzr
    mov     x2, xzr
    mov     x3, xzr
    br      x4
linux_trampoline_end:

    .section .stack, "aw", %nobits
    .balign 16
    .space  0x8000
stack_top:
