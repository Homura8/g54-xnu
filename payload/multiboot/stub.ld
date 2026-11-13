/* Position-independent Stage-1 multiboot stub linker script.
 * Linked at 0x0; all references are PC-relative so it runs at any
 * 4 KiB-aligned offset appended after an Android/ColorOS Linux Image. */
ENTRY(_start)
SECTIONS
{
    . = 0x0;
    .text : { KEEP(*(.text.entry)) KEEP(*(.text.hdr)) *(.text*) }
    .rodata : { *(.rodata*) }
    .data : { *(.data*) }
    . = ALIGN(16);
    __bss_start = .;
    .bss : { *(.bss*) *(COMMON) }
    . = ALIGN(16);
    __bss_end = .;
    .stack (NOLOAD) : { *(.stack) }
    . = ALIGN(0x1000);
    _end = .;
    /DISCARD/ : { *(.comment*) *(.note*) *(.eh_frame*) }
}
