/* Linked at 0x1000: the probe sits at raw-kernel offset 0x1000, and ADRP is
 * page-relative, so any 4 KiB-aligned kernel load address works. */
ENTRY(_start)
SECTIONS
{
    . = 0x1000;
    .text : { KEEP(*(.text.entry)) *(.text*) }
    .rodata : { *(.rodata*) }
    .data : { *(.data*) }
    .bss : { *(.bss*) *(COMMON) }
    .stack (NOLOAD) : { *(.stack) }
    /DISCARD/ : { *(.comment*) *(.note*) *(.eh_frame*) }
}
