# FrankenASP 1.0 — Dev Edition 1

**Historical release checkpoint:** this report describes the original combined research prototype **before** the code was divided between this standalone FrankenASP toolkit and the TECHO5 `frankenasp-adapter` branch. It remains the provenance of the initial hardware experiments, **not** a statement that newly split binaries have already been field-qualified.

**Project mission:** independent, reproducible **objective and subjective comparison** of TECHO5's open microphone/speech frontend and original factory Amazon ASP on the same Athena hardware. The wrapper is the instrument; it is **not intended as a production replacement** for TECHO5. The first wake-word advantage emerged as a **measured finding**, not a predetermined outcome.

**Proposed release identifier:** `frankenasp-v1.0.0-dev.1`  
**Status:** experimental, developer-oriented research preview (not a stable release)  
**Supported device:** Amazon Echo Show 8 Gen 2, **Athena / MT8183 only**, with the validated original factory ASP revision  
**TECHO5 baseline:** v1.6.0, AArch64 mainline-Linux edition

## What works

FrankenASP demonstrates an alternative **microphone-capture and speech-input frontend** using the Athena owner's original Amazon factory ASP within a separate native ARM32/Bionic worker. TECHO5 continues to handle music, Home Assistant integration, wake-word detection and the rest of the voice-satellite workflow. The processor receives four physical microphone channels and two physical playback-reference channels, and returns **16 kHz mono PCM** to the existing wake-word/STT input.

The implemented research features include:

- Source-built, owner-controlled AArch64 experimental `echod` and separate ARM32 DSP worker, with no proprietary factory payload included.
- Factory identity and private-runtime integrity preflight; explicit backup-directory selection; read-only verification by default.
- Guarded, opt-in staging and trial activation with rollback; optional slot-local persistent activation with 120-second startup verification and **fallback to stock TECHO5**.
- TECHO5 update protection while the experimental persistent process may be active.
- Real native-ASP output checks, synthetic PCM/protocol tests, worker stall/failure recovery and validated cold boot into the experiment.
- Completed controlled first-pass **wake-word-only** acoustic tests during **background music played through the Echo's own speakers**.

## Initial acoustic findings

This limited series measures **wake-word detection during music played by the Echo's own speakers**. It is one objective metric within a broader proposed research program; **subjective listening assessments and post-wake command/STT evaluations were not conducted in this series**. A measured advantage in this scenario does not establish universal superiority of either audio frontend.

At stimulus level 35 (the study's “normal voice” level), 60 scheduled wake-word stimuli yielded:

| Voice frontend | Echo music mono | Echo music stereo |
| --- | ---: | ---: |
| Stock TECHO5 | 45/60 (75.0%) | 22/60 (36.7%) |
| FrankenASP | **59/60 (98.3%)** | **54/60 (90.0%)** |

The study's mono/stereo designations refer to the **Echo's own speaker playback of music**, not microphone-array modes or multiple ASP output channels. All conditions used four physical microphones. The stock TECHO5 effective wake threshold was observed at **0.75** during music; FrankenASP remained at **0.85**. This is an end-to-end engineering comparison at the observed settings, **not** a matched-threshold causal attribution to any one ASP algorithm.

More results, including quiet/loud stimuli, limitations and study boundaries: [Initial acoustic results](acoustic-results-20261023.md).

## Verification and reproducibility

- The experimentally deployed ARM32 worker and Amazon `libasp.so` were verified loaded together on real Athena hardware; continuous output was observed after reboot.
- Short live trials, watchdog/fallback and native PCM signal-integrity tests were performed; long-duration stability qualification remains open.
- The open staging/protocol suite contains **31 Python tests**, passed on an independent Ubuntu 26.04 host.
- **Independent full Go CI: PASS on all four configurations** at source commit `8fc18e89ca5585de7d144d3d7f61007b07782e69`. On an Ubuntu 26.04 x86_64 clean checkout with Go 1.26.0, `go test -p 3 ./... -count=1` succeeded for default, `-tags dot`, `-tags spot` and `-tags panel`. Cross-platform `GOOS=windows` and `GOOS=darwin` vet checks for `./cmd/techo5-deck` also passed.
- **Independent AArch64 build: PASS**, using the version-stamped clean-tree builder (`v1.6.0_frankenasp.<commit>`), producing a statically linked ELF64 ARM aarch64 executable with no `.dirty` suffix.
- **Independent ARM32 worker build: PASS**, using the officially checksummed Android NDK r27d. It produced an Android API 28 ELF32 ARM shared library, with no host-glibc linkage.
- The first independent CI attempt exposed a cross-device compilation error in `frankenasp_guard.go` when building Dot. It was corrected to use `layout.AthenaMainline()` in commit `8fc18e8`, **then all four complete Go configurations were rerun and passed**.
- The separate, clean Ubuntu 26.04 x86_64 host and official Go 1.26.0/Android NDK toolchains are documented in [independent build instructions](build-on-ubuntu-26.04.md).
- Original factory libraries, Bionic runtime, device-private coefficients, backups, microphone recordings, credentials and unredacted logs are **not distributed**.

**Hardware-provenance boundary:** the wake-word acoustic tests used an earlier owner-built experimental daemon on the same Athena. The newly built clean-commit artifacts have passed off-device build/static tests but **have not been deployed back to the Echo for another acoustic run**. This Dev Edition is a validated research code baseline, not a second completed field qualification of a byte-identical release binary.

### Independent repeat CI on the release source snapshot (24 October 2026)

A **second complete clean-source CI run** was performed on `gptlab-core` using source commit `f9c1e76d9e734f12de7d8c9b10c3eda803015831`, Go 1.26.0, `-count=1` and bounded Go package parallelism (`-p 3`). Its fresh results:

| Check | Repeat result |
| --- | --- |
| Python staging/protocol unit tests (31) | **PASS** |
| Go `./...` default / Show | **PASS** |
| Go `./...` with `-tags dot` | **PASS** |
| Go `./...` with `-tags spot` | **PASS** |
| Go `./...` with `-tags panel` | **PASS** |
| `GOOS=windows go vet ./cmd/techo5-deck` | **PASS** |
| `GOOS=darwin go vet ./cmd/techo5-deck` | **PASS** |
| AArch64 `build_experimental.sh` on clean checkout | **PASS** |

The last repeat-run marker was `REPEAT_CI_ALL_PASS` at **2026-10-23 22:18:27 UTC** (24 October, Riga time). Test logs and the locally built executable remain on the independent build host under `/home/gptlab-agent/dev/frankenasp-dev1-ci-logs/repeat-20261024/`.

The only subsequent adjustments in the preserved combined release snapshot were **documentation-only**; no `echod` or `tools/frankenasp` source changes were made after the repeated CI. The current [independent build guide](build-on-ubuntu-26.04.md) describes the standard Linux toolchain and archive extraction commands. The repeated off-device CI does not supersede the acoustic-trial provenance limitation stated above.

## Explicitly not qualified

- Production or unattended long-duration stability; continuous ALSA/AFE and thermal resilience.
- Post-wake spoken-command quality and STT transcription accuracy, spatial speaker tracking, false-positive rate and algorithm-specific AEC/beamforming claims.
- Other Echo models, other Fire OS factory revisions, altered or missing vendor partitions.
- One-click consumer installation, automatic updates while FrankenASP runs, and stock Fire OS equivalence.
- Redistribution of any proprietary Amazon DSP library or native runtime.

**Installation is deliberately owner-controlled and potentially risky.** Keep a known-working stock TECHO5 build and device recovery method; review [Athena setup, activation and rollback](installation.md) before attempting anything. Do not interpret “Dev Edition 1.0” as an official TECHO5 release or endorsement.

## Next development tracks

Independent benchmark methods remain central: reproducible **subjective comparison of processed microphone PCM**, additional objective measures and publication of limitations or negative findings. Other potential tracks include stability and fault-injection soak tests; full documentation of room/test geometry and the acoustic harness; post-wake command/STT tests with directional interference; spatial beam selection/tracking research; and architectural discussion of a neutral, versioned external audio-frontend interface for TECHO5.
