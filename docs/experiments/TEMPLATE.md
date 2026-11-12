# Sanitised G54 hardware run card

Keep the complete run locally in `facts/` or `out/` (Git-ignored).
Commit a *sanitised* run card only if it establishes a meaningful milestone
or corrects a prior assumption. Never include a raw device serial,
IMEI/ICCID, unlock token, MAC, partition dump, Apple image, Motorola firmware,
personal path or unreviewed console log.

| Field | Observation |
| --- | --- |
| UTC date | |
| Device class | Moto G54 XT2343-2 / cancunf (recheck) |
| Current OS/bootloader/slot | |
| Repo commit + upstream pins | |
| Exact hypothesis / one changed input | |
| Kernel exec-data hash (if rebuilt) | |
| Boot image SHA-256 (private record; publish only if non-identifying) | |
| Stock image source/build + matching recovery verification | |
| Execution mode | offline / temporary boot / FastbootD / bootloader flash |
| Preflight gates | identity / rollback / format / size / backups / consent |
| Expected positive observation | |
| Actual observation and time | |
| Result | PASS / FAIL / SKIP / NOT TESTED |
| Evidence | sanitised screen, relevant bounded log extract, CI |
| Restoration / Android verified afterwards | |
| What was ruled out | |
| Next smallest experiment | |

Never label **image built** as **payload executed**, **XNU booted**,
**launchd started**, or **SpringBoard visible** without corresponding evidence.
When reporting an image's hash publicly, consider whether it could identify
a privately modified proprietary asset; prefer retaining such hashes locally.
