# Franken ASP real-device IPC hang and rollback test — 2026-10-23

## Scope

Short, owner-authorized fault-injection test on Echo Show 8 Gen 2 (Athena). The objective was specifically to confirm that an unresponsive native ARM32 factory ASP worker cannot indefinitely block TECHO5's microphone capture loop, and that the preexisting trial watchdog restores the official daemon. **Long-duration AFE stability, wake-word quality, AEC performance and acoustic playback tests were explicitly deferred.** User playback volume and speaker settings were not adjusted; no test audio was played.

## Preconditions

- Official TECHO5 was running as PID 15145.
- No preexisting factory activation flags, `/run/techo5/hold`, or bind mount.
- Existing AWB recording switches were off.
- A time-limited, 90-second experimental run was armed under the independent `tools/frankenasp/trial.sh` watchdog.
- The ARM32 worker's loaded `libasp_stream_worker.so` and `libasp.so` mappings were verified before fault injection.

## Evidence

| Europe/Riga local time | Observation |
|---|---|
| 01:07:36 | Start of guarded 90-second trial |
| 01:07:46 | Factory ARM32 worker PID **18312** confirmed |
| 01:07:47 | Watchdog pinned original worker PID **18312** |
| 01:07:57 | Sent **SIGSTOP** to PID 18312; `/proc/18312/status` reported `T (stopped)`. Worker was alive but could no longer read/write its IPC. |
| Shortly after injection | TECHO5 logged `service failed, restarting service=capture err="factory ASP processing: ASP output read: read |0: i/o timeout"`. The capture service did not remain blocked forever. |
| Before 01:08:00 | Capture service had recovered sufficiently to launch a replacement ARM32 worker PID **18919**. |
| 01:08:00 | Independent watchdog detected the changed worker PID **18312 → 18919** and initiated emergency rollback. |
| 01:08:02 | Trial watchdog logged `rollback complete; official launcher resumed`. |
| 01:08:28 | Official TECHO5 running as PID **18998**; worker absent; both activation flags and temporary binary bind mount absent. |

Final SHA-256 of installed official executable:
`14d6e80836360024f10352d816e1cd3be60683a723175a512bf0b7ff0cd57fb3`
(matched its pretrial SHA-256).

Both AWB recording routes (`UL2_CH1 DL1_CH1`, `UL2_CH2 DL1_CH2`) reported `off`. The maintenance hold was absent. TECHO5 was again launched from the original executable.

## Conclusions and limits

**PASS — failure handling on actual hardware:** the synthetic IPC deadline unit test is corroborated by a real SIGSTOP-induced native-worker hang and a logged Go pipe I/O timeout. The capture service restarted rather than remaining indefinitely blocked, and the independent watchdog restored the official daemon.

**PASS — fail-closed recovery:** the watchdog treated replacement of the native ARM32 worker as a fault and rolled back before the maximum trial duration.

**Not established:** a precisely measured 150-ms hardware response latency (the trace does not contain fine-grained timestamps for the signal-to-timeout interval); total AFE stability under playback, future unattended uptime, response to a hung Linux kernel driver, or graceful handling of simultaneous update/reboot/failure races.

No further extended AFE testing was performed.
