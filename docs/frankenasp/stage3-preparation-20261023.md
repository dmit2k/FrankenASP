# Stage 3 preparation — input integrity, factory-runtime preflight and measurement protocol

**Historical checkpoint (23 October 2026):** the deferred benchmark and proposed next steps below describe the state **at the time of this preparation audit**, not the current project status. The later [completed limited wake-word series](acoustic-results-20261023.md) has since been published. That series did **not** complete the broader objective/subjective comparison program, including listener assessments of processed microphone PCM or post-wake STT.

**Checkpoint: 2026-10-23.** This is preparatory work only. The next full
reproducible A/B DSP benchmark is **deferred until after the scheduled
acoustic recordings**. No audio was played, no new capture was initiated
and no volume or cutoff setting was changed during this audit.

## 1. What is verified from existing evidence

The owner-private prior hardware-AWB capture is 10 seconds long, with
960,000 interleaved frames in each stream:

- Four microphone channels: 96 kHz, S32_LE, 24-bit **left-aligned**
  in each 32-bit word. All four have 100% zero low bytes in this capture;
  the measured per-channel RMS ranges from approximately
  **-60.90 to -59.96 dBFS** (normalized to 24-bit full scale).
  No full-scale clipping was detected.
- Two reference channels: 96 kHz stereo S16_LE, from the real
  DL1_AWB_Record interface. They contain **only digital zero** in this
  particular saved recording.
- The capture metadata reports **zero dropped frames** and 160,000
  received 16-kHz-equivalent reference-valid frames. These are
  delivery counters, **not proof of an energized acoustic reference**.
- The shared AFE sample clock and equal frame counts alone do **not**
  establish the initial mic/ref sample offset, electroacoustic echo
  delay, or validity of echo suppression measurements.

The synthetic-tested, read-only
[`audit_capture.py`](../../tools/frankenasp/audit_capture.py)
now checks per-channel frame counts, format alignment, clipping, levels,
AWB activity, and basic capture metadata consistency. It intentionally
does **not** perform factory-DSP replay or make AEC quality claims.

### Calibration contract — risk identified and bounded

On the inspected converted Athena, the mainline kernel does **not**
expose `/proc/idme/miccal.0`; the underlying boot1 area is readable
via TECHO5's existing `layout.Idme` fallback. Current FrankenASP
source applies the four owner-specific IDME Q30 gains before sending
PCM to the native process. Original `asp.cfg` configures the factory
`Calibrator` to read `/proc/idme/miccal.*`, with unity fallback if
unavailable. Consequently, **double application is not expected in
the verified mainline mount layout**: the external adapter applies
the gain and the internal factory processor should fall back to unity.

This is a conclusion about the inspected setup and the factory config,
**not** a live numeric trace of the internal coefficient selection.
The expected behavior must be revalidated if procfs, namespaces,
kernels, or factory firmware change. Do not print owner coefficients
or copy IDME values into GitHub. Do not edit calibration before the
acoustic study.

### Factory PCM low-bit metadata

The factory 16-kHz mono PCM can contain Version33 metadata encoded in
bit 0 of samples. Any later audio/RMS/null-sample comparison should
report whether this bit is present and should calculate signal metrics
on a **derived analysis copy** with bit 0 cleared, while preserving
the original PCM unchanged. Metadata time is processing time, **not
a sample clock**. The private decoder is not distributed publicly.
No claim of speech-quality improvement is justified by metadata alone.

## 2. Host-side factory dependency preflight

[`preflight.py`](../../tools/frankenasp/preflight.py) checks **seven
critical** factory files under the intact read-only `/vendor`, verifies
the SHA-256 identity of `libasp.so` against the *tested* Athena build,
and, when supplied, checks existence of 41 conservative system ELF
dependencies plus native `linker` and `sh`.

Options:

```sh
# Host with a pre-extracted /vendor tree:
python3 tools/frankenasp/preflight.py --vendor-root /path/to/vendor

# PC/workstation with SSH key access to the owner Echo (no SSH writes):
python3 tools/frankenasp/preflight.py --ssh-target root@YOUR_ECHO

# If original p21 is on the installer workstation, inspect its ext4
# directory entries *without extracting, mounting or reflashing* it:
python3 tools/frankenasp/preflight.py --ssh-target root@YOUR_ECHO \
    --system-image /path/to/backups/YOUR_UNIT/partitions/p21-system.img

# Check an already isolated owner-local ARM32 runtime:
python3 tools/frankenasp/preflight.py --vendor-root /path/to/vendor \
    --runtime-root /path/to/private/amazon-arm32
```

The output is JSON without proprietary file contents or IDME data.
It distinguishes intact vendor but **missing original system**, a
complete source image needing private extraction, a complete *static*
runtime file set, and an **unvalidated factory revision** (unknown
`libasp.so` SHA-256). An unknown revision must not be enabled just
because filenames match.

The check is **not** an installation utility, a proof of ELF namespace
compatibility, a full inventory of all 37 audio configs, nor a
qualified runtime smoke test. The original system backup remains
necessary for the tested runtime, but the official Athena installer
normally creates it *on the PC*, before writing p21.

## 3. Preserve the planned acoustic tests; add metadata, not extra runs

The planned acoustic session already compares stock AEC/MWW cutoff
**0.75** against the experimental fixed **0.85**; keep that variable
explicit in the log. **Do not silently change either cutoff, playback
volume, microphone gain or other test controls.** Test results at
different thresholds must be analyzed as different conditions, not
merged into an uncontrolled result.

For each recording/condition preserve **privately**, when the existing
capture setup already provides them:

| Field | Purpose |
|---|---|
| Session/condition ID, timestamps, clock basis | Pair clips with events; avoid processing-time/audio-time confusion |
| TECHO5 commit/build, active DSP backend and MWW model/hash | Check what actually processed each segment |
| Cutoff 0.75 or 0.85, actual operating mode mono/stereo | Prevent threshold and speaker-path confounding |
| Playback source: Echo, TV, silence; intended volume/gain | Separate acoustic-reference quality by source |
| Talker/position/distance and speech/background type | Group trials by acoustic geometry and content |
| Raw four-mic S32_LE 96-kHz capture | Save unprocessed common input for later A/B |
| True stereo S16_LE 96-kHz hardware AWB, if available | Preserve the signal needed to evaluate factory AEC |
| Reference nonzero/RMS and per-channel clipping | Detect valid-but-silent or saturated captures |
| ALSA frame loss, XRUN, stream-start offsets where available | Detect discontinuities and infer limitations |
| Trigger log and manual ground-truth phrase labels | Later TP/FN/FP attribution and onset delay |

The raw four-mic capture and native 96-kHz hardware reference must
be from **the same session**. A separate 16-kHz software reference
is not interchangeable with the factory hardware loopback. When
recording uses fixed-length chunks, retain chunk timestamps and
discontinuity counters; mark possible alignment limitations rather
than inventing a sample-perfect relation.

Where playback is expected to be active, the capture-audit checker
must confirm **nonzero** AWB channels. A capture whose AWB is all zero
is useful for quiet/background mic-level analysis, **not** for
quantifying playback-echo cancellation.

If the existing session capture tooling does not provide a channel or
metric, record it as **missing** rather than changing the active
experiment merely to fill out this table.

## 4. Later analysis only (explicitly deferred)

After acoustic recordings have finished and labels are available:

1. Verify that source PCM formats, channel mapping, calibration and
   mic/reference timing are comparable across modes.
2. Replay identical, time-aligned source input privately through
   factory ASP and the actual open TECHO5 speech path. Respect ASP
   cold-start state and its multi-second adaptation/training periods.
3. Compare MWW results with **identical** model, cutoff and dataset
   before drawing DSP conclusions. Report TP, FN, FP per exposure
   hour, onset/response latencies and uncertainty by condition.
4. Quantify reference-dependent AEC on segments with sufficient
   reference energy. Avoid interpreting near-end speech attenuation
   or raw RMS reduction alone as a valid ERLE measurement.
5. Conduct randomized, blind A/B or ABX listening using time-aligned,
   appropriately level-matched, derived PCM copies. Keep raw audio
   private; don't publish voice content without consent.

**Not being done now:** A/B DSP replay, new microphone acquisition,
active AFE soak tests, changes to MWW cutoff, long-duration playback
or changes to the Show's listening/speaker configuration.

See [controlled comparison protocol](testing.md),
[architecture](architecture.md), and
[partition dependencies](partition-dependencies-20261023.md).
