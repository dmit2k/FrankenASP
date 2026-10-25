# Athena FrankenASP: live factory-output PCM probe — 2026-10-23

**Outcome: PASS for real DSP audio continuity and bounded probe; NO CLAIM about spoken-word quality or AEC effectiveness.**

This study evaluates **microphone capture and speech processing**, not Echo
speaker sound quality. No music, TV, microphone gain, sensitivity/cutoff or
speaker volume settings were changed during the run.

## Procedure

- Device: owner's Echo Show 8 Gen 2 (Athena), official TECHO5 `v1.6.0`;
  experimental `v1.6.0_frankenasp.f523881099.dirty` was built with an
  owner-only, **disabled-by-default** PCM integrity probe.
- Prerequisites: factory `libasp.so` from the owner's original read-only
  `/vendor`, existing private Android 9 Bionic runtime and native worker.
- A private, explicit `pcm-probe.enable` flag was created **only for
  this experiment**.
- Launch used `tools/frankenasp/trial.sh start 60` with a background
  watchdog and automatic stock rollback, without reboot or persistence.
- Capture began **2 seconds** after ASP startup, then collected exactly
  **8 seconds** of three streams inside the private trial directory:
  - Four raw microphone channels, interleaved S32LE/96 kHz,
    **12,288,000 bytes**.
  - Two hardware AWB channels, interleaved S16LE/96 kHz,
    **3,072,000 bytes**.
  - Direct `Process20ms()` factory mono output, S16LE/16 kHz,
    **256,000 bytes**. Recorded before TECHO5's downstream leveling.
- The probe wrote 128,000 consecutive 16 kHz samples and closed its
  output files automatically. Private recordings were transferred to
  the private research host, compared byte-for-byte by SHA-256, and removed from
  the Echo. The files are **not** in Git or distributed.
- The 60-second trial completed with `trial deadline; automatic
  rollback`; factory markers and the temporary binary bind mount
  were removed. Stock TECHO5 returned, `/store` remained read-only.
  No reboot, boot hook or persistent-mode setting was involved.

## Results

| Measurement | Real capture |
|---|---:|
| Factory ASP output, mono PCM16 duration | **8.000 seconds** |
| Factory PCM16 RMS | **-68.212 dBFS** |
| Factory PCM16 peak | **-54.746 dBFS (60 sample units)** |
| Nonzero PCM16 samples | **93.463%** |
| PCM16 full-scale clipping | **0 samples** |
| Raw microphone RMS, channels 0–3 | **-72.406, -73.205, -73.111, -72.584 dBFS** |
| Raw microphone clipping | **0** |
| Hardware AWB L/R | **digital zero on both channels** |
| Factory PCM SHA-256 | `0f966e52fe9e62e8de6151b4676262c4e38c64b231c17816873f84ca881aada4` |
| Mic RAW SHA-256 | `d495d396416acf04087592e2a4820290f4d8066dd7a7861b68590b62f4ce1523` |
| AWB RAW SHA-256 | `76ed5c9c326ba62322d464a22d3fcf7b76c7352c6d33badc36ccea7a33325e97` |

An independent FFmpeg volumedetect pass over the same private
factory PCM confirmed **-68.2 dBFS** whole-band RMS and
**-54.7 dBFS** peak. Filtered passbands give approximately
**-70.7 dBFS** below 250 Hz, **-73.3 dBFS** for 250–3500 Hz,
and **-90.3 dBFS** above 3500 Hz (first-order filter-based
diagnostics; approximate, not calibrated orthogonal-band energy
accounting). Most energy in this quiet sample is at lower
frequencies; these figures cannot establish speech intelligibility.

The raw microphone channels are approximately **-72 to -73 dBFS**,
therefore the factory output's -68 dBFS alone is **not** evidence
of severe additional attenuation. No known spoken utterance was
presented or annotated in this sample. The AWB channels were
exactly zero because the device was not actively playing
audio during the probe, so this run cannot validate AEC.

## Version33 metadata validation — critical additional evidence

The independent Version33 decoder previously validated against the
original Amazon ARM reader/writer was applied to the live PCM16.

Initially an offset-zero read found **0/1000 valid full packets**.
An alignment scan located the factory 128-sample packet boundary at
**offset 64 PCM16 samples = 4 milliseconds**. This matches the
known 4 ms startup FIFO adjustment in the experimental Go integration.

At this alignment:

- **999/999 full packets** pass the Version33 header, version,
  length, checksum and profile-consistency checks.
- The remaining trailing **64 samples** are an expected partial
  packet; they do not represent a dropped audio block.
- **0 frame-counter spacing mismatches**; 998 consecutive
  transitions increment the modulo-64 counter by exactly one.
- The factory `reference_energy_active` field is **0 in all 999
  complete packets**, agreeing with the two-channel zero AWB capture.
- The coarse factory `dnn_vad_q4` marker was **0 in 996 frames** and
  **1 in 3 frames**. Its field scale is low-resolution and does not
  establish a ground-truth speech transcript. No reliable speech
  quality or wake-word success claim follows from this scene.
- Syntax-valid factory metadata is evidence of structured
  **original ASP processing**, not validation of every undocumented
  metadata field's semantic meaning.

The 4 ms offset must be considered before comparing live
factory PCM to raw input clocks. The exact physical
microphone/reference start offset and acoustic playback delay have
**not** been calibrated.

## Limitations and next acoustic test

The run demonstrates that the current TECHO5/ARM32/Bionic/libasp
integration can continuously capture four real microphone channels,
pass them through original factory processing, and return a
valid 16 kHz mono PCM16 stream with intact Version33 metadata.
It does **not** demonstrate intelligible speech, wake-word accuracy,
near-end voice preservation, or echo cancellation.

For those, use the separately planned controlled acoustic sessions
with a **known spoken phrase** and **nonzero playback reference**,
keeping the user-approved cutoff variants (0.75 and 0.85)
strictly distinct and measuring identical material in both DSP paths.

The probe source and tests live under
`echod/internal/hardware/mic/factory_pcm_probe_athena.go` and
`factory_pcm_probe_athena_test.go`; integration uses
`openFactoryPCMProbe()`, `Process20ms()` and `factoryProbe.push()`.
It is disabled by default, uses mode 0600 private files and a strict
2s warmup + 8s file size/duration limit. The private PCM files and
the full Version33 decoded per-packet JSON remain on the owner's
trainer VM and must not be committed to GitHub.
