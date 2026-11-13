/* Position-independent multiboot stub. Linked at 0: the packer places it at a
 * 4 KiB-aligned raw-kernel offset (ADRP is page-relative), so any 4 KiB-
 * aligned load address works. The 64-byte header must sit at +0x08. */
ENTRY(_start)
SECTIONS
{
    . = 0x0;
    .text : { KEEP(*(.text.entry)) KEEP(*(.text.hdr)) *(.text*) }
    ASSERT(mb_hdr == 0x8, "multiboot header must be at stub + 0x08")
    .rodata : { *(.rodata*) }
    .data : { *(.data*) }
    . = ALIGN(16);
    __bss_start = .;
    .bss : { *(.bss*) *(COMMON) }
    . = ALIGN(16);
    __bss_end = .;
    .stack (NOLOAD) : { *(.stack) }
    . = ALIGN(0x1000);
    _end = .;   /* touch firmware, then the SWEETXNU payload, start here (probe.c find_fw/find_payload) */
    /DISCARD/ : { *(.comment*) *(.note*) *(.eh_frame*) }
}
