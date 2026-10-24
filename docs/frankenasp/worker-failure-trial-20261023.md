# Franken ASP native worker termination / emergency rollback test — 2026-10-23

This was an owner-authorized, short live test on Echo Show 8 Gen 2 (Athena). The official TECHO5 binary remained available unchanged. No test tones, TTS, music, volume adjustments, or speaker DSP setting changes were initiated.

## Test setup

- Guarded ARM64 experimental TECHO5 build with owner-local ARM32/Bionic factory ASP.
- A separate watchdog with a **90-second** maximum trial window.
- Watchdog updated to pin the **first observed worker PID** and treat a new native ASP process as a recovery event requiring immediate rollback.
- Original installed binary SHA-256: `14d6e80836360024f10352d816e1cd3be60683a723175a512bf0b7ff0cd57fb3`.
- Only the temporary experimental bind mount and associated arming markers were used.

## Observed sequence — Europe/Riga local time

| Time | Event |
|---|---|
| 00:58:02 | Controlled trial started; watchdog active |
| 00:58:07 | Original native ASP worker PID **14290** loaded and pinned by watchdog |
| After startup | Operator sent **SIGTERM** specifically to the original worker, after verifying that its process maps included both the native worker and original factory ASP |
| 00:58:26 | Watchdog found a different native worker PID **15066**, recorded process replacement and triggered emergency rollback |
| 00:58:27 | Automatic rollback finished |
| 00:58:31 | Official daemon was running, PID **15145**; experimental mount absent |
| 00:59:04 | Stable follow-up check: official daemon still PID **15145**, AWB routes off, no hold/arming/request markers |

The temporary mount and both activation markers were absent after the emergency rollback. The restored official executable's SHA-256 matched the pretrial hash. The native worker was gone. The device's two checked hardware UL2-to-DL1 recording routes were both off.

The previous 90-second **timeout** rollback trial had also passed. This test adds an independent verification that **unexpected worker replacement** triggers fail-closed recovery rather than silently continuing under another PID.

## Scope and limitations

- **PASS:** active worker verified, SIGTERM sent, replacement detected, emergency rollback and official service respawn completed.
- **PASS:** post-rollback ALSA AWB routes off; stock executable hash unchanged.
- **Not measured:** subjective audio, wake detection, transcription, echo cancellation quality or long-running thermal/CPU stability.
- **Not tested:** hard kill, kernel crash, power loss during the transition, simultaneous external updates, rollback failure injection.
- The 150-ms Go pipe deadline test is a synthetic unit test and not a proof of every possible hardware stall.

**Research only:** do not enable Franken ASP as an unattended or permanent option based solely on these tests.
