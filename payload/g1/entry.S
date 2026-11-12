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
    mov     x0, x19
    bl      probe_main
1:  wfe
    b       1b

    .section .stack, "aw", %nobits
    .balign 16
    .space  0x8000
stack_top:
