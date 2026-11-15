# E56–E60: Service hang/crash sampling (`#9`, `#13`, `#16`, `#17`, `#18`)

- **Date:** 2026-11-15
- **Device:** Moto G54 (`cancunf`, `boot_a`)
- **Result:** Diagnostic captures isolating root causes for `#9`, `#13`, `#16`, `#17`, and matching `IONetworkController` (`#18` stub).

## Findings

1. **`#9` (`Settings → General → About` hang, `E56`, `out/usblog/e56-about-smp.log`):**
   - `Preferences[328]` (`slide 0x14aa8000`) sample 4 shows `t1` waiting inside `AppleMediaServices` (`+0xbe604`, `+0x104f64`, `+0xe21d8`, `+0x4558ac`) and `t3` blocked in `PreferencesUI + 0xa564` → `Preferences + 0x1c980` → `PassKitCore + 0x18bf4` / `+0x191a8` → `Foundation` (`+0x33cb0`, `+0x9a224`) → `libxpc.dylib + 0xe0ec` (`mach_msg`).
2. **`#13` (`Settings → General → Storage` crash, `out/usblog/storage-crash.log`):**
   - `Preferences[298]` (`slide 0x2db5c000`) hits `SIGTRAP` (`sig 5`, `reason ns 2 code 0x5`) at `PodcastsUI + 0x8dda8` (`lr PodcastsUI + 0x8dd10`, `bt PodcastsUI + 0x5e958`, `libdispatch.dylib + 0x637a8`).
3. **`#16` (`Photos`) / `fairplayd.H2` IOKit dependency (`E57–E60`):**
   - `E60` (`sweetiolog=fairplayd.H2,vmd,locationd`) showed `fairplayd.H2` matching `com_apple_driver_FairPlayIOKit` (`IOServiceNotificationUser`) and getting `0 found`, preceding `checkpointd` and `locationd` stalls (`E63`/`E64` below confirm both block on `fairplayd.H2` MIG RPCs).
4. **`#18` (`IONetworkController` service matching, `ccee111` / `E57–E60`):**
   - `scripts/g54_xnu_image.py` now adds `/arm-io/marconi-wifi` (`mac-address-wifi0 = 02:54:00:00:00:01`) to the D22AP ADT when absent, attaching `SweetNetwork.cpp` (`SWEET NET: IONetworkController up, mac 02:54:00:00:00:01`) and unblocking `SWEET IOX: class-match IONetworkController -> 1 candidate(s), state=0x4` notifications. Actual packet transport (Wi-Fi or USB networking) remains unimplemented.
