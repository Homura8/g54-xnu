# E19: isolate the console overlay (staged, not executed)

## Purpose

E18 reached an Apple logo through the IOSurface/IOMFB copy path. The owner
then saw the logo overwritten and redrawn, followed by distorted old probe
graphics underneath fresh iOS logs. UI samples still advance with the same
PIDs. The console intentionally continues drawing into scanout memory by
default. E19 tests that specific interference before changing framebuffer
geometry, surface handling or drivers.

Add only **`sweetfb_noconsole=1`** to E18's arguments. The existing pinned
`0067-sweet-console-mute.patch` sets `sweet_console_muted` on first frame
presentation: ordinary console output still reaches the persistent log,
but stops drawing over the panel. Panics draw again. This does not remove
the ruby magenta/green debug squares and does not claim to fix the distorted
probe contents, slow loading or any preferences-service wait.

## Verified host preparation

- Image: `out/g4/e19-quietfb-boot.img`, 64 MiB, SHA-256
  `45666da5b7537f2fba00ef93a3dbea50ee39d8afe075145eca7f5bd4e15edf48`.
- Unchanged K2 kernel, SHA-256
  `2bb9311a91e2c59552e961c2dcee4a916ee65a47bff024de6fcb9bdc543f43dc`.
- Same six A55s, UFS_FIX probe, D22AP ADT and phone root as E18.
- Payload comparison confirms that only the fixed-size command-line area
  changes. ADT, loaded kernel bytes and probe match E18. Regenerated
  inactive gzip filler is outside the loader's consumed payload.
- Stock header, image size, compressed kernel length, decompressed length,
  probe branch/contents and post-kernel bytes pass the existing verifier.
- Matching stock restore boot SHA-256 rechecked:
  `e0fe4010a8a897e0b99253d4a51665582a850d6bb10837f535ebe3e0337cc2d4`.

## Hardware gate and observation

**Not flashed or booted. E18 remains running.** Do not interrupt it while it
is making useful progress. Before a later write, repeat the live device,
firmware/slot, no-merge and recovery checks in hardware-loop §3a–3b, using
the standing owner authorization for a reversible `boot_a` test.

Run one bounded boot, then observe whether the first iOS frame remains
visible without ordinary console text, whether distorted probe graphics
still return, and whether a lock/home screen appears. A quiet or black panel
alone cannot distinguish a stall from output that has merely been muted.
Preserve the persistent log for subsequent readout. If old distorted graphics
persist, console isolation alone is insufficient; inspect source-surface
dimensions/stride and scanout contents next. Rollback is E18's verified boot
image, or the matching stock boot image (Android also needs a userdata reset).
