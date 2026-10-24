# Athena FrankenASP persistent-boot trial — 2026-10-23

**Historical trial record:** all PASS / NOT TESTED entries describe **this particular reboot/fallback experiment**. They do not override later [wake-word-only acoustic measurements](acoustic-results-20261023.md); nor do those later measurements qualify long-duration persistence, subjective speech quality or post-wake STT. FrankenASP's purpose is independent comparison, not deployment of the factory DSP as a supported permanent replacement.

**Status: guarded boot/fallback PASS; production-quality voice DSP and long-duration
stability NOT qualified.** This record concerns *microphone capture and speech
processing*, **not speaker sound quality**.

## Scope and starting state

- Test board: Echo Show 8 Gen 2 (Athena), TECHO5 rootfs slot `b`, slot
  status `good`, vendor partition mounted read-only.
- Official daemon: `v1.6.0`; owner-built experimental daemon:
  `v1.6.0_frankenasp.f523881099.dirty`. The `.dirty` suffix
  reflects uncommitted local source changes in the build environment;
  it is not an upstream release.
- Existing private Bionic/ARM32 system dependencies were preserved.
  The previous research executable (`v0.0.0-dev`) was saved beside
  the new experimental binary on the owner's device.
- Before changing the boot slot launcher, the new experimental executable,
  startup scripts, and full native runtime were checked against private
  `SHA256SUMS` manifests. The device had no active trial, hold or
  persistent-mode flag. No playback settings, amplifier tuning or
  factory partitions were modified.

## Observed sequence

1. Installed the opt-in hook in the active, settled `b` slot's
   `/usr/local/sbin/techo5-run`. The original launcher was backed up,
   and the system-slot store was remounted read-only afterward.
   The official `/usr/local/bin/techo5` executable was not modified.
2. Explicitly set `frankenasp-persistent.enabled`, then performed
   **one controlled reboot**.
3. The Echo successfully rebooted into slot `b`. The hook selected
   `/data/techo5-linux/frankenasp-trial/techo5-experimental run`,
   with one attempted start recorded for that boot. A separate native
   ARM32 process was observed with both the factory `libasp.so` and
   the locally compiled `libasp_stream_worker.so` mapped.
4. The experimental daemon started ordinary TECHO5 network, web,
   Home Assistant and Sendspin services. The update checker reported
   running `v1.6.0_frankenasp.f523881099.dirty` and offered the
   official `v1.6.1` release; **no update installation was attempted**.
5. For approximately the first 80–100 seconds of the new boot, the
   existing `athena: capture levels` diagnostic printed `-150 dBFS`
   across all four microphone channels.
6. Investigation **after** the trial showed this was a **diagnostic
   implementation defect**, not proof of silent microphone PCM:
   the native factory path uses `factoryAux16()`, which filled the
   auxiliary diagnostic audio channels but did **not** update the
   `athenaMeter` counters. These values therefore stayed at zero.
   The factory DSP's processed output follows a separate route through
   `FactoryOutput()` into the wake-word pipeline; its actual speech
   quality was **not** measured in this test.
7. Deliberately sent SIGTERM to the verified experimental `echod`
   process to exercise **one automatic failover**. BusyBox init
   respawned the stock launcher, which detected the previous
   attempt, disabled future persistence, cleared factory flags and
   started the official `/usr/local/bin/techo5 run`.
8. Confirmed that stock `v1.6.0` reconnected to Home Assistant and
   Sendspin. Microphone metering returned nonzero values, including
   approximately `-66 to -69 dBFS` per raw/stock microphone
   channel, and wake processing remained near 50 frames/s.
9. Invoked `persist.sh uninstall-hook` to restore the original
   boot launcher and verified its SHA-256 matched the saved original.
   The store was again mounted read-only. Removed the exact temporary
   transfer directory. No active factory marker, persistent opt-in,
   temporary hold or experimental process remained.

## Engineering conclusion

| Check | Result |
|---|---|
| Owner-installed native runtime and versioned binary integrity | PASS |
| Explicit opt-in in one settled A/B slot | PASS |
| Successful reboot into owner-installed experimental daemon | PASS |
| Factory `libasp.so` loaded by independent ARM32 worker | PASS |
| Automatic stock fallback after experimental daemon exit | PASS |
| Persistent opt-in automatically disabled after early failure | PASS |
| Original launcher restored, matching saved SHA-256 | PASS |
| Rootfs store returned read-only | PASS |
| Voice PCM correctness / wake-word effectiveness / AEC | **NOT TESTED** |
| Factory DSP startup probation after 120 seconds | **NOT REACHED** |
| Automatic recovery from a spontaneous kernel reboot | **NOT TESTED** |
| Manual OTA update refusal and overnight updater skip on-device | **NOT TESTED** (code-level tests passed) |
| Repeated reboot persistence or long AFE soak | **DEFERRED** |

**Important diagnostic fix:** `factoryAux16()` now populates
`athenaMeter` using a cheap 1-in-6 sample from the **raw input**
and marks the measurement `meter_source=raw_1_in_6`, distinguishing
it from TECHO5's `meter_source=techo5_fir` processed-meter path.
These coarse raw levels must **not** be compared as quality measurements
of the factory-processed 16-kHz ASR output. A synthetic regression
test covers nonzero mic and AWB reference inputs. Both test and code
were committed to this branch **after** the device trial; the patched
meter was **not** deployed to the Echo during this test.

## Follow-up boundaries

The planned acoustic recordings and offline A/B quality evaluation
remain separate and deferred as previously agreed. Before another
live experiment, explicitly capture or meter the **actual processed
factory PCM** to distinguish successful library initialization
from useful speech-signal output. The initial version-stamped
experiment is no longer persistent on the research Echo, and the
official daemon continues operating normally.

Do not publish the original Amazon `.so` files, runtime
dependencies, model configs, original partition backups or private
voice recordings as part of these results.
