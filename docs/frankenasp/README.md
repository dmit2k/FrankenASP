# Franken ASP — comparing factory and TECHO5 microphone capture and speech processing

**Repository split:** This repository contains the independent **research and benchmarking tools**: the worker, staging and rollback utilities, tests and documentation. The Go voice-input integration is maintained separately in [dmit2k/techo5 (frankenasp-adapter)](https://github.com/dmit2k/techo5/tree/frankenasp-adapter). See the [split contract](adapter.md).


## Purpose: a factory voice-input reference for objective and subjective A/B tests

**Franken ASP is a research project for comparing the quality of microphone
capture and speech-signal processing on Amazon Echo hardware: Amazon's
original factory voice front end versus TECHO5's open implementation.**
Our goal is to let Echo owners measure and listen to the differences in
what the voice assistant actually *hears*, using the same physical device
and reproducible conditions. Users should be able to evaluate both
approaches themselves instead of relying on assumptions or anecdotal claims.

**This is not a comparison of speaker sound quality, music playback,
amplifier tuning, or how the Echo sounds when playing audio.** Music,
TV and the Echo's own speaker output matter here only as acoustic
interference and/or playback-reference signals for echo cancellation
(AEC). The output under evaluation is the **captured and processed
microphone signal sent toward wake-word detection and speech recognition**.

The project provides a controlled, opt-in **comparison instrument** that can run the device's
*own* original factory microphone/voice DSP as a **reference baseline**
alongside TECHO5's existing open voice-capture and processing path.
Comparisons can include:

- **Objective voice-input measurements:** wake-word detection and false
  activations; missed speech and clipped word onsets; residual playback
  echo/AEC behavior, background-speech/noise suppression, input signal
  levels and clipping, processing latency and recovery from faults.
- **Subjective evaluation of captured speech:** blind listening to
  recorded **microphone/processed-voice PCM**, focusing on speech
  intelligibility, naturalness, onset preservation and suppression of
  TV, music or other competing sounds. These recordings are not
  evaluations of the Echo's loudspeakers.

Fair comparisons must control speaker/background level, microphone
position, source material, input gain, test ordering and relevant DSP
state. We intend to publish repeatable test methods and results,
**not proprietary factory firmware or private voice recordings**.
Either voice-processing pipeline may have strengths, weaknesses and
trade-offs; which performs better is a question to measure, not a
predetermined conclusion. **FrankenASP is not a production replacement for
TECHO5's audio frontend.** Lessons from comparisons *may* help improve
fully open **microphone and speech-processing implementations**.

**Important limitation:** running Amazon's original ASP library under
TECHO5 Linux does not recreate the complete Fire OS microphone pipeline,
its control state or its capture/reference timing. Claims of equivalence
to voice capture on stock Fire OS require separate validation. This
project does **not** currently provide one-click A/B switching for every
TECHO5 user.

## Current experimental implementation and status

**Research preview, not an official TECHO5 feature or a ready-to-install build.**
The working proof of concept is limited to **Echo Show 8 Gen 2
(Athena, MT8183)** on a specific tested factory firmware build. It
routes four microphone channels and two physical playback-reference
channels to a separate ARM32/Android Bionic process running the
owner's original factory **speech-input** processor. TECHO5's open
microphone/speech-processing pipeline stays the default. This experiment
does not modify TECHO5's speaker playback implementation, amplifier tuning,
upstream stereo support or kernel patches, nor benchmark speaker **audio
quality**. A/B trials **do control mono/stereo speaker playback of music**
as an acoustic test variable.

**This repository distributes open research source code, tests and
documentation — not third-party factory components.** No Amazon binaries, partition images,
beamformer coefficients, native DSP configurations, original factory
runtimes or voice recordings are included. Owners supply any required
factory components from their own lawfully obtained device backups,
keep them private and remain responsible for applicable license and
copyright requirements. The research/benchmarking purpose does not
itself grant permission to redistribute third-party materials.

### First controlled acoustic results (23 October 2026)

On an Echo Show 8 Gen 2 (Athena), the original Amazon voice-input ASP
achieved substantially higher **wake-word activation** rates than stock
TECHO5 in controlled trials **while the Echo itself was playing
background music through its built-in speakers**. Here **mono/stereo**
means **mono or stereo playback of that music by the Echo**, *not*
microphone-array operation or mono/stereo ASP processing. All four
microphones were used; the wake-word input remained mono PCM16 at 16 kHz.
Speech stimuli and, where applicable, interfering TV sound came from
separate external loudspeakers at predefined positions.

At the normal-level (35) voice stimulus, stock TECHO5 with Echo music
in mono/stereo detected **45/60 and 22/60** utterances; with the same
Echo playback modes, FrankenASP detected **59/60 and 54/60**.
The observed effective wake threshold was **0.75 for stock TECHO5**
during music and **0.85 for FrankenASP**.

**This first result is wake-word detection only:** intelligibility and
STT accuracy of subsequent voice commands have **not yet been tested**.
These are preliminary end-to-end observations, **not** proof that any
one Amazon algorithm (AEC, beamforming, etc.) caused the improvement.
See the **[completed acoustic comparison, room diagram and full results](athena-acoustic-comparison-20261025.md)**; the [23 October snapshot](acoustic-results-20261023.md) records the earlier interim state.

## Contents

The **Go integration sources are in the separate TECHO5 fork**, not this
repository. In [frankenasp-adapter](https://github.com/dmit2k/techo5/tree/frankenasp-adapter):

- [`echod/internal/hardware/mic/factory_asp_athena.go`](https://github.com/dmit2k/techo5/blob/frankenasp-adapter/echod/internal/hardware/mic/factory_asp_athena.go): guarded worker invocation, Q30 microphone calibration, six-channel packing and 16 kHz mono speech output.
- [`athena.go`](https://github.com/dmit2k/techo5/blob/frankenasp-adapter/echod/internal/hardware/mic/athena.go) / [`mic.go`](https://github.com/dmit2k/techo5/blob/frankenasp-adapter/echod/internal/hardware/mic/mic.go): stereo AWB capture and delivery to MWW/STT without secondary TECHO5 AEC/denoising/leveling.

The following tools **are in this FrankenASP repository**:
- `tools/frankenasp/asp_stream_worker.c`: clean research source code for ARM32
  Bionic worker; no native factory payload is embedded.
- `tools/frankenasp/extract_runtime.py` and `extract_configs.py`:
  read-only extraction from operator-selected factory partition backups.
- `tools/frankenasp/build_worker.sh`: optional Android NDK source build.
- `tools/frankenasp/status.sh`: distinguish requested marker from loaded ASP.
- `tools/frankenasp/audit_capture.py`: read-only, no-audio-playback integrity audit of previously saved 4-mic/2-AWB PCM (detects silent reference).
- `tools/frankenasp/preflight.py`: read-only inventory of preserved factory vendor, private Android runtime and optional original system backup (no extraction or install).
- `tools/frankenasp/install.py`: explicit `--backup-partitions DIR` (no discovery), read-only verification by default; optional guarded staging of owner's private ARM32 system runtime and self-built experimental binaries with `--install`, **without activation**.
- `tools/frankenasp/build_experimental.sh`: explicit HA-rankable `vX.Y.Z_frankenasp.<commit>` local version rather than unstamped `v0.0.0-dev`.
- `tools/frankenasp/persist.sh`, `persistent-run.sh`, `persist-watch.sh`: **disabled by default**, slot-local opt-in persistence and automatic stock fallback; patched updater refuses normal updates until opt-out and reboot.
- `tools/frankenasp/tests`: synthetic PCM and fixed-point tests.

## Device and firmware scope

The **37** factory DSP configuration/model files observed under
`/vendor/etc/audio-algorithms/` are from **this Athena device's original
Fire OS**. The directory also contains ASR, VoIP, playback, Bluetooth
and other settings — **modes of Athena hardware, not factory profiles
for every Echo**. Their presence does not expand Franken ASP's scope:
this research compares **microphone capture and voice processing only**,
not the sound produced by the speaker.
Original `AFE.cfg` and `asp.cfg` identify the target board as `Athena`,
with four microphones and two speakers. Neither the Athena `libasp.so`
nor its beamformer coefficient bundle has been validated on any other Echo.
A reusable **multi-device Franken ASP framework** remains a possible
future design, but each board/firmware needs its own validated DSP/runtime,
calibration and synchronized-reference adapter.

See [multi-device compatibility and portability scope](multi-device-scope.md).

## Documentation

- **[Full Athena wake-word acoustic benchmark (25 October 2026): all speech levels, no music / mono / stereo, directional interference and room diagram](athena-acoustic-comparison-20261025.md)**

- [FrankenASP 1.0 Dev Edition 1: release scope and known limitations](release-v1.0.0-dev.1.md)
- [Independent build on Ubuntu 26.04: verified Go toolchain, packages, tests and build commands](build-on-ubuntu-26.04.md)
- [Architecture and open questions](architecture.md)
- [Multi-device scope: why 37 factory files are *not* universal Echo profiles](multi-device-scope.md)
- [Exact Athena factory paths, ELF dependencies and surviving partitions](partition-dependencies-20261023.md)
- [Local runtime assembly and limitations](runtime.md)
- [Owner setup: guarded automatic installer and step-by-step manual instructions](installation.md)
- [Optional reboot persistence, fail-safe fallback, and TECHO5 update interaction](installation.md#c-optional-persistence-across-ordinary-reboots-advanced-owners)
- [Historical Athena persistent reboot/fallback trial (2026-10-23): confirmed boot and stock recovery; PCM and wake-word quality were not evaluated in *that trial*](persistence-trial-20261023.md)
- [Verification of previously captured real factory PCM16 output (2026-10-23): signal integrity, level comparisons and AEC limitations](real-factory-pcm-validation-20261023.md)
- [Live 8-second native factory PCM probe (2026-10-23): 999 valid aligned Version33 frames, synchronized 4-mic/AWB capture, automatic rollback](live-factory-output-pcm-probe-20261023.md)
- [Controlled comparison protocol](testing.md)
- [First controlled acoustic results (2026-10-23): stock mono/stereo vs factory ASP, voice stimulus levels 30/35/40](acoustic-results-20261023.md)
- [Stage 3 preparation: input integrity, zero-AWB finding, factory preflight and acoustic test metadata](stage3-preparation-20261023.md)

## Safety and milestones

**Historical reports below record what was known at each checkpoint.** Earlier
statements that acoustic testing was "not yet performed" must be read in their
original date context; the subsequent wake-word results are documented in
[the completed acoustic study](athena-acoustic-comparison-20261025.md). The tested
combined Dev Edition remains archived separately; later repository splitting
has not been followed by new on-device acoustic qualification.

The research prototype has now completed limited live **Athena-only**
trials with time-limited rollback, controlled worker termination and a real
SIGSTOP-induced native IPC timeout. Detailed observations are in the
[trial reports](ipc-hang-trial-20261023.md).
**This is not a qualified release.** Initial controlled acoustic
wake-word testing is now complete on one Athena device (see above).
Long-duration ALSA/AFE stability, false-positive rate, isolated AEC
effectiveness, post-wake STT, cross-firmware compatibility and broader
installation safety remain unvalidated. Do not use the persistent
`/data/techo5-linux/fireos-asp.enabled` marker alone: the guarded trial
also requires the explicitly temporary `/run/techo5/frankenasp-armed`
flag and an independent watchdog.

No experiments should overwrite the official TECHO5 binary or modify
factory partitions. For microphone-quality comparisons, **record and
restore** any intentionally varied speaker playback mode or level:
mono/stereo music playback is an explicit experimental variable, not
something the installation tools may silently change. Keep the official
release and its recovery method.
Attribution of these initial wake-word gains to individual algorithms
such as AEC or beamforming remains a research hypothesis; matched
microphone recordings and post-wake command tests are future work.
