// G54 G1 probe entry. LK jumps here (arm64 Image protocol: MMU off,
// x0 = DTB physical address). Position independent: only PC-relative
// references, no absolute pointers, so any 4 KiB-aligned load address works.
//
// SPDX-License-Identifier: MIT

    .section .text.entry, "ax"
    .global _start
_start:
    msr     daifset, #0xf           // no interrupts: we have no vectors
    mov     x19, x0                 // DTB from LK
    adr     x1, stack_top
    mov     sp, x1
    adr     x1, vectors             // any exception -> exc_main -> Fastboot
    mrs     x2, CurrentEL
    cmp     x2, #8
    b.eq    4f
    msr     vbar_el1, x1
    b       5f
4:  msr     vbar_el2, x1
5:  isb
    adr     x1, __bss_start          // zero .bss: it holds stale kernel bytes
    adr     x2, __bss_end
1:  cmp     x1, x2
    b.hs    2f
    str     xzr, [x1], #8
    b       1b
2:  mov     x0, x19
    adr     x1, _start              // where LK put us
    bl      probe_main
3:  wfe
    b       3b

    .balign 0x800
vectors:
    .rept   16
    .balign 0x80
    adr     x1, stack_top           // fresh stack: sp may be what faulted
    mov     sp, x1
    bl      exc_main
    b       .
    .endr

    .section .stack, "aw", %nobits
    .balign 16
    .space  0x8000
stack_top:
