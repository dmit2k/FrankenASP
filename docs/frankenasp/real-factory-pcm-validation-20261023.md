# FrankenASP — verification of real factory ASP output PCM (2026-10-23)

**Scope: microphone capture and speech-signal processing, not speaker sound quality.**
This analysis used **existing private original-Amazon-ASP output PCM** from
the October 21 Athena investigation. The current Echo was **not** changed.

## Verification of source provenance

The primary dataset is the October 21 **real** Athena four-microphone
(96 kHz, four-channel S32_LE) capture accompanied by genuine two-channel,
96-kHz S16_LE hardware DL1_AWB_Record playback reference. Capture metadata
reports 960,000 frames per stream (10 seconds), no dropped frames, and
hardware-reference delivery for all 160,000 equivalent 16-kHz frames.
Actual reference activity is nonzero: approximately 56.3% of all samples
in each channel, with full-capture RMS about -41.60/-41.39 dBFS (L/R).
These are not proof of stream-start alignment or echo-path delay.

The previous independent factory-replay tool produced:

- `captures/processed/show8-v150-stereo-awb-factory16k.pcm`
- 160,000 signed mono PCM16 frames at 16 kHz = 320,000 bytes
- Private SHA-256:
  `ee123cef8c95279a313039d6f200a6d91411557d09ddd1febbeda62d7d4a52aa`
- Byte-identical file in `captures/processed/show8-v150-stereo-awb-mww/factory.pcm`

Original factory DSP execution/replay already happened during the
October 21 investigation. **Re-running QEMU during this October 23
review was blocked by the remote command safety guard.** This is
an independent analysis of saved outputs, not a claim of a fresh run.

A second archived 10-second dataset with a software-reconstructed
reference also has a previously generated native-device output and QEMU
output. An earlier audit compared their bit-zero-cleared upper 15 PCM
bits and found them equal, notwithstanding small differences in the
embedded Version33 metadata LSB.

## PCM signal integrity results

| Signal (real stereo-hardware-AWB scene) | RMS dBFS | Peak dBFS | Full-scale samples |
|---|---:|---:|---:|
| Original Amazon ASP native PCM16 mono (no TECHO5 leveling) | **-57.12** | **-35.12** | **0** |
| Same factory PCM with saved TECHO5-leveling step | -36.60 | -14.32 | 0 |
| Saved TECHO5 all-four-mic pre-AEC output | -39.01 | -17.72 | 0 |
| Saved TECHO5 configured AEC output | **-52.14** | **-30.08** | **0** |
| Saved TECHO5 configured AEC plus leveling | -31.78 | -10.08 | 0 |

For the factory native output, 93.77% of samples are nonzero.
Of the entire 10 seconds, the factory output's per-second RMS ranges
from about **-73.0 to -51.3 dBFS**, rather than being stuck at zero.
These numbers establish continuity, levels and absence of sample
full-scale clipping, **not** speech intelligibility.

For the same input, the factory output is about 18.1 dB below the
saved raw-four-mic pre-AEC path in whole-capture RMS, and the TECHO5
configured AEC output is about 13.1 dB below that pre-AEC path.
This is **not a valid cross-DSP ERLE comparison**: beamforming,
gain structure, near-end speech, source position, capture time
alignment and different ASR processing may all contribute.
Do not describe the 5 dB difference as superior echo cancellation.

## What remains unproven

- These are **pre-existing** recordings; they do not establish that
  the *current* FrankenASP deployment emits nonzero PCM after the
  October 23 reboot.
- No ground-truth utterance annotation or independent transcript exists
  for this dataset; signal energy is not proof of preserved speech,
  consonant onsets or ASR accuracy.
- Zero PCM16 clipping does not rule out analog-domain compression,
  internal DSP clipping, muted onset segments or speech suppression.
- Residual stereo playback/reference-to-microphone time alignment
  remains unmeasured; ERLE/AEC-specific attribution is not supported.
- The stored MWW scores used an **approximate zserge audiofrontend**,
  not a fully matched live TECHO5/HA run. All saved methods peak at
  approximately 0.2667 with cutoff 0.85; do **not** claim detection
  success or failure as a reliable live quality metric.
- Exact performance after the real October 23 persistent reboot, and
  normal/update-induced persistence across multiple slots, still
  require separate device-side tests.

## Source-code finding from the October 23 live trial

Previously, the factory branch's `factoryAux16()` populated a
diagnostic six-channel frame but did not update `athenaMeter`.
This explains the misleading -150 dBFS **meter** values observed on
the real October 23 boot. The actual factory output is routed
separately by `FactoryOutput()` to `broadcastWithFactory()`.
The input-meter bug was fixed and regression-tested on the development
branch, but this fix was **not deployed on the Echo** during the
persistent-boot trial. The meter bug is not evidence that native ASP
PCM was zero. The archived factory outputs demonstrate that the
original DSP can produce real nonzero audio on Athena material, but
do not prove that the current device run did so.

## Recommended next controlled test

The smallest conclusive live check is an explicitly enabled, bounded
private capture of the native `Process20ms()` 16-kHz PCM16 output,
**before** the TECHO5 noise/leveling stage, alongside the matching
four 96-kHz raw microphone channels and the genuine two-channel AWB
reference. Capture no more than a few seconds after warmup, store
only owner-private data, verify 16-kHz sample count and clipping, and
run a short guarded trial with automatic stock fallback. The planned
next-day acoustic A/B protocol is unchanged; do not change MWW cutoff,
volume or playback settings for this check.

No proprietary Amazon library, factory config or personal voice
recording should be committed to the repository.
