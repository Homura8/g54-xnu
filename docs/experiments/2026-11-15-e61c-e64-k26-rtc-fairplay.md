# E61c–E64: MT6685 PMIC RTC (`#4`), clean `g54noexec` (`#21`), Novatek SPI (`#20`), and FairPlay (`#16`/`#17`) on K24–K26

- **Date:** 2026-11-15
- **Kernel:** K26 (`92af91a`, CI run `43707017931`, patchset `0200`–`0212`)
- **Device:** Moto G54 (`cancunf`, `boot_a`, `current-slot=a`, `snapshot-update-status=none`)

## Kernel changes (K24–K26)

- **`0202-g54-novatek-touch.patch`:** Extends SPI transfer poll timeout from 2 ms to 10 ms with `delay(1)`, reorders startup speed probing (`31` then `9`), and splits `nvt.idle` from `nvt.bad_sum` with sample logging for the first 3 `bad_sum` headers.
- **`0203-g54-keys.patch`:** Adds `gk_spmi_mtx` and exported `g54_spmi_read()` / `g54_spmi_write()` over SWINF 2 so the RTC driver shares SPMI safely.
- **`0206-g54-noexec.patch`:** Refuses `g54noexec` binaries early in `exec_check_permissions()` (`EACCES`) instead of late in `process_signature()`, eliminating `SIGKILL`, `CRASH` console prints, and `ReportCrash` spam (`#21` log noise fixed).
- **`0211-g54-mt6685-rtc.patch`:** Reads the MT6685 PMIC hardware RTC (`bsd/dev/g54_rtc.c`, SPMI slave 9, `0x580`/`0x588`/`0x592..0x59e`). `K24` failed early boot (`E61c`) when publishing `"IORTC"` unconditionally; `K25`/`K26` gate `publishResource("IORTC")` on `g54iortc=1`.
- **`0212-g54-fairplay-stub.patch`:** Registers diagnostic `com_apple_driver_FairPlayIOKit` + `IOUserClient` (`g54fpstub=1`), fixed in `K26` (`92af91a`) by quoting `com_apple_driver_FairPlayIOKit` in `KernelConfigTables.cpp`.

## Hardware observations

1. **`E63` (`K26` + `g54fpstub=1`, no `g54iortc=1`):**
   - `G54 RTC: 2026-11-15 11:09:10 UTC (epoch 1794740950)` reads live time accurately, while `launchd` starts at `03:09:40.513544` (+30 s waiting on `IOKitInitializeTime` without `IORTC`).
   - `fairplayd.H2` matches and opens `com_apple_driver_FairPlayIOKit`, calls external methods `sel 22` (`in 0/0 out 0/4`), `sel 23` (`in 0/0 out 0/4`), and `sel 21` (`in 0/552 out 0/552`), and exits when `sel 21` returns `kIOReturnUnsupported` (`0xe00002c7`).
2. **`E63b` (`K26` + `g54iortc=1`):**
   - `G54 RTC: 2026-11-15 11:26:21 UTC (epoch 1794741981)` matches `launchd` `03:26:21.478700` immediately (**0 s delay**; USB console COM8 ready at **26 s** vs **57 s** in `E63`). **`#4` wrong clock is fixed with `g54iortc=1`.**
   - `Settings → General → Date & Time` still freezes Settings (`out/usbshots/e63b-datetime.png`) even with valid time and `IORTC`.
   - `G54 NVT: bad_sum sample ff 78 32 14 sum 97 got 10` (`frames 6556 touches 0 spi_err 14 idle 0 bad_sum 6556`) proves idle Novatek frames have `d[0] == 0xff` with non-`0xff` trailing bytes (`ff 78 32 14` / `ff 78 32 44`), missing `d[0]==0xff && d[1]==0xff && d[2]==0xff`. Valid touch reports have finger ID `1..10` (`d[0] >> 3` <= 10, so `d[0] <= 0x57`), so checking `d[0] == 0xff` in `0202` will classify idle reads cleanly (`#20` remaining work).
3. **`E64` (`K26` + `g54iortc=1` + `sweetsample=Preferences,timed,MobileSlideShow,locationd`):**
   - Root-caused both **`#16` (`Photos`)** and **`#17` (`Settings → General → Date & Time`)** to the same blocked `fairplayd.H2` MIG RPC (`msgh_id = 0x4b3` = `1203` in `E63` sample stacks):
     - `MobileSlideShow` `t0` (`e64-smp1.log`, slide `0x3d034000`) waits inside `PhotoLibraryServicesCore + 0x7ee0c` → `libMobileCheckpoint.dylib` (`+0x18fc`, `+0x1350`, `+0x19e8`) → `MobileSystemServices + 0x3a10` → `mach_msg` to `com.apple.mobilecheckpoint.checkpointd`, while `checkpointd` (`e63-smp.log`) hangs calling FairPlay MIG `0x4b3`.
     - `Preferences[227]` `t0` (`e64-smp1.log`) waits inside `GeneralSettingsUI` (`+0x1ac04`, `+0x1acc0`) → `CoreLocation` (`+0x33ec0`, `+0xb710`, `+0xca6c`) → `Foundation + 0x9a224` → `libxpc.dylib + 0xe0ec` (XPC to `locationd`), while `locationd[62]` `t2` hangs in the same FairPlay MIG `0x4b3` call (`e64-smp0.log`, `e64-smp1.log`).

## Next

1. Inspect `out/ipsw/chk/fairplayd.H2` callers of `sel 22`, `sel 23`, and `sel 21` (`552`-byte struct) to test minimal `0212` stub responses that allow `fairplayd.H2` to reach `bootstrap_check_in` (unblocking `checkpointd` → `#16` and `locationd` → `#17`).
2. Update `0202` idle detection from `d[0..2] == 0xff` to `d[0] == 0xff` (`#20`) and publish `"IORTC"` when `g54_rtc_init()` succeeds unless `g54iortc=0` (`0211`).
