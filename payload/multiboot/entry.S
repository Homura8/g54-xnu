// G54 multiboot stub entry, header and Linux hand-off.
//
// The stub is appended to the stock Android arm64 Image inside the gzip
// kernel stream of boot_a, at raw offset `stub_off` (4 KiB aligned, past the
// Image's image_size). scripts/g54_multiboot.py replaces Image code0 with
// `b stub_off`, so LK's jump to the Image start (MMU off, EL1, x0 = DTB;
// E1-E4) lands here. Position independent: PC-relative references only.
//
// SPDX-License-Identifier: MIT

    .section .text.entry, "ax"
    .global _start
_start:
    b       _real_start
    nop

// Fixed 64-byte header at stub + 0x08. The packer fills it in and
// scripts/g54_multiboot.py verify checks it; layout mirrored in stub.c.
    .section .text.hdr, "a"
    .global mb_hdr
    .balign 8
mb_hdr:
    .ascii  "G54MBOOT"          // +0x00 magic
    .word   1                   // +0x08 version
    .word   64                  // +0x0c header size
    .quad   0                   // +0x10 stub_off: raw offset of _start (Image base = _start - stub_off)
    .word   0                   // +0x18 orig_code0: the Image's first word, restored before Linux runs
    .word   2                   // +0x1c default item: 0 iOS, 1 Android, 2 Fastboot
    .word   5                   // +0x20 timeout_s
    .word   0                   // +0x24 flags: bit 0 recovery passthrough, bit 1 Android entry enabled
    .quad   0                   // +0x28 blob_size: bytes after _end (touch fw, SWEETXNU, trailer)
    .quad   0                   // +0x30 stub_end: _end as linked (packer cross-check)
    .quad   0                   // +0x38 image_id: also in the trailer (the last 16 raw bytes)

    .text
_real_start:
    msr     daifset, #0xf           // no interrupts: we have no vectors yet
    mov     x19, x0                 // DTB from LK
    adr     x1, stack_top
    mov     sp, x1
    adr     x1, vectors             // any exception -> exc_main (probe.c) -> Fastboot
    mrs     x2, CurrentEL
    cmp     x2, #8
    b.eq    4f
    msr     vbar_el1, x1
    b       5f
4:  msr     vbar_el2, x1
5:  isb
    adr     x1, __bss_start          // zero .bss: it holds whatever was in RAM
    adr     x2, __bss_end
1:  cmp     x1, x2
    b.hs    2f
    str     xzr, [x1], #8
    b       1b
2:  mov     x0, x19
    adr     x1, _start              // where LK put us
    bl      mb_main
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

// void linux_boot(u64 dtb, u64 image_base, u32 orig_code0) -- does not return.
// Restores the Image's first instruction word and enters it exactly as LK
// would have (arm64 booting.rst: MMU off, x0 = DTB, x1-x3 = 0, DAIF masked).
// Runs in place: nothing is written before the branch except code0, so the
// stub cannot be overwritten under itself (Linux clears its BSS much later).
    .text
    .global linux_boot
    .balign 8
linux_boot:
    dc      civac, x1               // drop any cached copy of the patched word
    dsb     sy
    str     w2, [x1]                // MMU off: a non-cacheable store to RAM
    dsb     sy
    ic      iallu                   // the old branch may be in the I-cache
    dsb     sy
    isb
    mov     x4, x1
    mov     x1, xzr
    mov     x2, xzr
    mov     x3, xzr
    br      x4

    .section .stack, "aw", %nobits
    .balign 16
    .space  0x8000
stack_top:
