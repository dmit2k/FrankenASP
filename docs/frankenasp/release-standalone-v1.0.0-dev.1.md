# FrankenASP 1.0 — Dev Edition 1 (standalone research toolkit)

**Intended tag:** `v1.0.0-dev.1`  
**GitHub release type:** **Pre-release**, source only  
**Scope:** independent comparative research tools for **Echo Show 8 Gen 2 (Athena)**; **not** a stable production firmware or audio replacement.

## Purpose

FrankenASP supplies an **independent, reproducible framework for objective measurements and subjective evaluations** of the open TECHO5 microphone-processing path and the device's original factory Amazon ASP **on the same hardware**. The wrapper, installer and TECHO5 Go adapter are experimental tools for observing and comparing the frontends. Better wake-word results in some controlled tests are a **finding**, not a predetermined objective or proof of general superiority.

**This is the first separately organized source release.** The previous [combined FrankenASP 1.0 Dev Edition snapshot](https://github.com/dmit2k/techo5/tree/snapshot/frankenasp-v1.0.0-dev.1) remains unchanged and is the provenance for the October 23 real-device wake-word experiment.

## Two repositories, one tested source pair

- **FrankenASP** (this repository): ARM32/Bionic stream worker, build scripts, owner-side preflight, staging/rollback/watchdog utilities, synthetic tests and research documentation. The `v1.0.0-dev.1` tag will identify this exact source revision.
- **[TECHO5 frankenasp-adapter](https://github.com/dmit2k/techo5/tree/frankenasp-adapter)**: the Go integration and its tests, pinned for this preview at **`046589f6c6d5a33d5840c734b5b0cc603ce4ba28`**.
- **[Upstream TECHO5](https://github.com/HuskerMinion/techo5)**: the underlying Linux firmware, device support, voice satellite and audio/playback services. FrankenASP does **not** replace or redistribute this project.

The separate experimental daemon keeps its upstream-compatible version prefix `v1.6.0_frankenasp.046589f6c6` when built with the validated `v1.6.0` baseline. **That is a TECHO5 daemon build identifier, not the version of this standalone research toolkit.**

## Independent clean reproduction on Ubuntu 26.04 (24 October 2026)

A new test workspace was created by cloning both public repositories and unpacking the official toolchains in the **normal Linux execution environment** (without the restrictions of any remote-command sandbox). The Go 1.26.0 tarball and Android NDK r27d ZIP were checksum-verified against the expected upstream values. **Normal `tar -xzf` and `unzip -q` succeeded**, preserving the required NDK compiler executable without repair scripts.

| Check | Result |
| --- | --- |
| Clean checkout of both repositories | **PASS** |
| Python 3 standard-library test suite | **31/31 PASS** |
| Go 1.26: full `go test -p 3 -timeout 240s ./... -count=1` default | **PASS** |
| Same full Go tests, `-tags dot` | **PASS** |
| Same full Go tests, `-tags spot` | **PASS** |
| Same full Go tests, `-tags panel` | **PASS** |
| `GOOS=windows` / `GOOS=darwin` Go vet | **PASS** |
| AArch64 statically linked TECHO5 daemon, clean version stamp | **PASS** |
| ARM32 Android/Bionic native worker, NDK r27d | **PASS** |
| Source tree clean after the build | **PASS** |

Reproduction logs and binary outputs are retained privately on `independent build host` in `a private local workspace`. The successful checked run ended **2026-10-24 00:12:50 UTC**. Subsequent changes to the standalone repository before tagging were documentation-only; the tested worker, installer and adapter code are unchanged.

Representative binaries from this independent off-device run:

| Artifact | SHA-256 |
| --- | --- |
| `libasp_stream_worker.so` (ARM32) | `7017258766e7496b088a8b11b06b7b5ed11ae647c55831c3ee58aacab47dd649` |
| `techo5-experimental` (AArch64) | `63a0483eb2504a8f52c2b993122387a4d0a79214949eb8b5b0cdf68a882625db` |

These checksums identify **specific local build artifacts**; the daemon includes a build timestamp, so independently rebuilt binary hashes need not match. **No Amazon proprietary material was used for these off-device builds.**

See the [standard Ubuntu build guide](build-on-ubuntu-26.04.md) for a runnable, checksum-verified setup with `tar`, `unzip` and the matching adapter SHA. The [owner-local installation guide](installation.md) is deliberately separate: preflight/staging and real ASP activation were **not** retested as part of this source-release reproduction, because that requires the device owner's legal factory backup and a controlled hardware experiment.

## Initial acoustic finding — historical device trial

At normal stimulus level 35, while the Echo itself played background music, the earlier combined prototype observed wake-word activations of **45/60 (mono speaker music) and 22/60 (stereo speaker music)** for stock TECHO5, versus **59/60 and 54/60** for the factory ASP path. **Mono/stereo refers only to music reproduction through the Echo's speakers**, not microphone array size or ASP output.

The effective microWakeWord cutoff differed: **stock 0.75 during music; FrankenASP 0.85**. This was an end-to-end observation, **not** a threshold-matched DSP-only experiment. No false-positive trade-off, post-wake STT improvement, individual AEC/beamforming cause, subjective listening quality or long-duration stability was established. **The newly separated binaries have not yet been acoustically retested on a real Echo.**

See [the complete limited wake-word results](acoustic-results-20261023.md) and [comparative research protocol](testing.md).

## Licensing, thanks and safety

Thank you to **[HuskerMinion](https://github.com/HuskerMinion)** and the **TECHO5 contributors** for the open platform that brought ageing Echo devices back into service. Special credit to **[@nuno407](https://github.com/nuno407)** for the [Athena two-channel DL1_AWB_Record hardware-reference kernel patch](https://github.com/HuskerMinion/techo5/commit/c94f013b8d6d30e49f3262649e0c243363e5b72c), which enables more faithful comparative hardware input arrangements.

Published open-source material is [MIT-licensed](../../LICENSE), preserving applicable upstream attribution. Amazon's factory libraries, firmware, models, tuning, original runtime, credentials, voice recordings and backups are **not MIT-licensed by this project** and are **not distributed**. Owner-local experimentation requires appropriate authorization and careful validation of hardware and firmware identity, fail-safe rollback and legal rights. This project is **independent, unofficial, and not endorsed or supported by Amazon or TECHO5 maintainers**.

**Use the source-only Pre-release for research. Do not treat it as a consumer-installable or long-term-stability-qualified version of TECHO5.**
