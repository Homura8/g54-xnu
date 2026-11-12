/* Linked at 0x1000: the probe sits at raw-kernel offset 0x1000, and ADRP is
 * page-relative, so any 4 KiB-aligned kernel load address works. */
ENTRY(_start)
SECTIONS
{
    . = 0x1000;
    .text : { KEEP(*(.text.entry)) *(.text*) }
    .rodata : { *(.rodata*) }
    .data : { *(.data*) }
    . = ALIGN(16);
    __bss_start = .;
    .bss : { *(.bss*) *(COMMON) }
    . = ALIGN(16);
    __bss_end = .;
    .stack (NOLOAD) : { *(.stack) }
    . = ALIGN(0x1000);
    _end = .;   /* an XNU payload, if any, starts at the next 4 KiB boundary */
    /DISCARD/ : { *(.comment*) *(.note*) *(.eh_frame*) }
}
