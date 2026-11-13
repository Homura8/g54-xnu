# E17: isolate CPU-wakeup notification overhead

Hypothesis: disabling the default CPU-wakeup monitor removes the resource
notification/error flood and lets this bring-up boot proceed with less
monitoring and console overhead. This is not an established GUI fix.

## Inputs and controls

- Same K2 kernel, UFS probe, ADT, six A55s and writable iOS root as E16.
- The complete payload compares equal to E16 after adding only
  `task_wakeups_monitor_rate=0` in the fixed-size boot-argument area.
- Boot SHA-256:
  `951658eec9b1e1057b0a34756070fd04526d630ca48547e64ae601dd73ab28cd`.
- Stock restore SHA-256 rechecked:
  `e0fe4010a8a897e0b99253d4a51665582a850d6bb10837f535ebe3e0337cc2d4`.
- Private live preflight `facts/20261112T182735Z-fastboot`: same
  `cancunf`, XT2343-2, 5-8-6 bootloader, unlocked, slot A,
  bootloader Fastboot, `snapshot-update-status=none`.
- Owner returned the phone manually to Fastboot. Existing standing
  authorization covers this reversible `boot_a` write.

Apple's [task.c at xnu-8796.141.3](https://github.com/apple-oss-distributions/xnu/blob/xnu-8796.141.3/osfmk/kern/task.c)
parses this argument and enables the default task wakeup monitor only when
the rate is nonzero. `disable_exc_resource` is checked after notification
delivery, so it was not chosen to address this particular path. No kernel
patch or root-image modification is needed for this experiment.

## Execution and result

`fastboot flash boot_a out/g4/e17-nowakemon-boot.img` returned OKAY for
send and write in **1.845 s**. Reboot issued at **18:27:53 UTC,
12 November 2026**; `fastboot reboot` returned OKAY.

**Owner observation, 13 November UTC:** the CPU-wakeup warning flood appears
gone, but boot remained very slow and no GUI was reported. The owner left
the phone running while asleep, so there is no measured boot duration.
The supplied photograph shows many alternating `exec fairplayd.H2`,
`exec xpcproxy` and `exec bluetoothd` lines. That is consistent with repeated
service exits/restarts, but the photo contains no exit status or crash reason
and does not establish that SpringBoard itself is restarting. The visible
AppleKeyStore call from ospredictiond returns success (`0x0`).

E17 therefore suppresses the observed warning flood without resolving the
slow boot or producing an observed interface. No new UI-process sample was
captured in this photograph. Warm-root state still prevents attributing an
elapsed-time difference solely to this flag.

Next: [E18](2026-11-13-e18-dyld-dof.md) retains warning suppression and
disables dyld's DTrace section scan using an existing kernel argument.

Rollback: flash E16's image (removes only this argument), or the matched
stock boot image. Android additionally needs userdata reset. Only `boot_a`
was flashed; iOS continues to write its root during execution. No slot
metadata or critical partition was changed.
