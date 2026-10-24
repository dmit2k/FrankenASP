# FrankenASP

**An independent research and benchmarking toolkit for comparing the open-source [TECHO5](https://github.com/HuskerMinion/techo5) audio frontend with the original factory Amazon audio processing on Echo Show 8 Gen 2 (Athena).**

*Experimental measurement and comparison tools — not replacement firmware, not a competing voice assistant, not an Amazon software distribution, and not a production release.*

**The purpose of FrankenASP is to enable reproducible objective measurements and subjective listening evaluations of two audio-processing paths on the same physical Echo**, under documented acoustic conditions. The goal is to observe, measure and understand their differences — **not to demonstrate a predetermined winner** or make proprietary Amazon processing a permanent dependency of TECHO5.

To make that comparison possible, FrankenASP provides an open-source ARM32/Bionic streaming wrapper, a separate experimental TECHO5 adapter, installation and recovery tools, tests and research documentation. On Athena, the factory processing path takes four physical microphone channels and two hardware playback-reference channels and returns **16 kHz mono PCM** to TECHO5's existing wake-word and Home Assistant voice pipeline.

The first controlled experiments revealed substantially higher **wake-word activation rates while the Echo itself played music** with the factory processing path. That is an **initial research finding, not the project's original objective**. It neither establishes the cause of the difference nor proves better post-wake speech recognition.

> **Developer preview — Athena only.** Installation requires the owner's compatible factory backup, a separately built TECHO5 adapter, a restorable stock setup and acceptance of substantial experimental risk. **No proprietary Amazon audio binaries are provided here.**

**First standalone research-preview version:** `v1.0.0-dev.1` — see [release scope, independent reproduction and known limitations](docs/frankenasp/release-standalone-v1.0.0-dev.1.md). This version identifies the **research toolkit**, not a stable or production-qualified replacement for TECHO5.

## Research purpose and boundaries

FrankenASP is first and foremost a **comparative research instrument**. We want to make it possible to:

1. Run controlled A/B experiments on the *same hardware*, documenting the playback configuration, spatial arrangement, voice stimuli, interference and effective wake-word thresholds.
2. Evaluate the resulting microphone signals and voice behavior **objectively** (for example, wake-word detections and misses, captured PCM and future STT error measurements) and **subjectively** (critical listening and human assessment of audible speech quality).
3. Publish methods, observations and limitations — including cases where either processing path performs better, or where the experiment cannot distinguish competing explanations.
4. Investigate which lessons, if any, could inform an **entirely open-source audio frontend** without requiring proprietary factory components.

The wrapper and adapter are means of enabling these comparisons. An owner may run the factory path as a **temporary, opt-in experimental frontend** to collect measurements, but shipping a production replacement for TECHO5's own processing is **not the primary goal**.

Our completed trials so far primarily quantify **wake-word activations**; we do **not** claim to have completed a calibrated subjective-listening study, long-duration reliability qualification or post-wake STT comparison. Improving any of those outcomes would be welcome, but independent measurement comes first.

## Built on TECHO5 — with genuine gratitude

Before discussing FrankenASP, we want to recognize **[HuskerMinion](https://github.com/HuskerMinion) and the [TECHO5 contributors](https://github.com/HuskerMinion/techo5)**.

Making Linux work on ageing, tightly integrated Echo hardware is already impressive. Making displays, sound, hardware interfaces, Home Assistant integration, music playback and daily usability work *together* across multiple generations is a remarkable engineering accomplishment. Just as impressive is the pace and persistence with which HuskerMinion continues to improve TECHO5.

For owners of Echo devices that might otherwise become obsolete or e-waste, **TECHO5 gives that hardware a useful second life**: local control, integration with our own home automation, and a reason to keep good equipment in service instead of discarding it.

A special thank-you also goes to **[@nuno407](https://github.com/nuno407)**, who authored the [Athena kernel work exposing the two-channel `DL1_AWB_Record` hardware echo reference](https://github.com/HuskerMinion/techo5/commit/c94f013b8d6d30e49f3262649e0c243363e5b72c) (PR #214). By adding the missing DL1-to-UL2 routes, this contribution made the 96 kHz stereo playback-reference capture available alongside Athena's four-microphone input — a crucial prerequisite for comparing processing paths with **more closely matched input signals to those used by the original Fire OS audio pipeline**. It is an important improvement to TECHO5's own open hardware support, independently of FrankenASP. We are especially grateful because reliable access to the real microphone and playback-reference streams makes our **objective measurements and subjective comparisons** more meaningful. It does **not** imply that the open and factory DSP algorithms are equivalent.

**None of this project would exist without that work.** FrankenASP is not competing firmware, claims none of the credit for the platform, and is not a request that the maintainer take responsibility for an experiment relying on proprietary components. We are genuinely grateful for what TECHO5 already makes possible.

Our research addresses a narrower, immediate interest: **measuring and understanding what the original audio hardware and processing can achieve on Athena today**, alongside TECHO5's open-source frontend. If useful, the methodology, results and a future vendor-neutral adapter design could be shared upstream. We do not ask TECHO5 to adopt our proprietary-compatibility experiment; whether to use any findings is entirely the maintainers' decision.

**Full credit for the foundation belongs to TECHO5.** The scope and risks of FrankenASP belong to this project.

## How the projects fit together

| Codebase | Responsibility |
| --- | --- |
| **[FrankenASP](https://github.com/dmit2k/FrankenASP)** (this repository) | Open ARM32/Bionic stream worker; Android NDK build scripts; owner-side preflight, installation and rollback; synthetic tests; acoustic measurements and research documentation |
| **[TECHO5 fork: frankenasp-adapter](https://github.com/dmit2k/techo5/tree/frankenasp-adapter)** | Athena Go integration: microphone/reference capture, worker lifecycle, PCM routing, explicit opt-in and update protection |
| **[Upstream TECHO5](https://github.com/HuskerMinion/techo5)** | Linux firmware, hardware support, Go daemon, playback, UI, Home Assistant and voice-satellite functionality |

The adapter is presently **Athena-specific, not a generic stable plugin API**. A clean, vendor-neutral audio-frontend interface could become a future upstream contribution. TECHO5 need not ship or depend on Amazon factory libraries for such an interface to be useful.

The experimentally validated all-in-one implementation remains frozen in the [FrankenASP 1.0 Dev Edition snapshot](https://github.com/dmit2k/techo5/tree/snapshot/frankenasp-v1.0.0-dev.1). Separating the source code into two repositories is a **reorganization, not a new acoustic qualification**.

## Completed Athena acoustic comparison — 25 October 2026

**[Read the full wake-word benchmark, including the room-layout diagram, methodology, five directional scenarios and interpretation](docs/frankenasp/athena-acoustic-comparison-20261025.md).**

Using the same physical Echo Show 8 Gen 2, microWakeWord model, room and external speech recordings, the experiment compared the **standard TECHO5 microphone frontend** with the **original Amazon factory ASP running via FrankenASP**. Quiet (30), normal (35) and loud (40) speech were tested with music off, mono and stereo; a five-scenario sweep supplied **60 scheduled presentations per configuration**.

| With music playing on the Echo | Quiet — 30 | Normal — 35 | Loud — 40 |
| --- | ---: | ---: | ---: |
| TECHO5 · mono | 35/60 (58.3%) | 45/60 (75.0%) | 49/60 (81.7%) |
| TECHO5 · stereo | 13/60 (21.7%) | 22/60 (36.7%) | 33/60 (55.0%) |
| FrankenASP · mono | 41/60 (68.3%) | 59/60 (98.3%) | 60/60 (100%) |
| FrankenASP · stereo | 45/60 (75.0%) | 54/60 (90.0%) | 59/60 (98.3%) |

The **no-music baselines**, directional interference results, and the geometry of the loudspeaker arrangement are covered in the [full report](docs/frankenasp/athena-acoustic-comparison-20261025.md). Notably, even *faint secondary household speech* from the nearer speaker severely reduced stock TECHO5's detection of a voice from the more distant side.

**Interpretation boundaries:** Mono/stereo describes only the Echo's **own speaker playback**, not microphone-array modes. During music, the observed effective MWW cutoff was **0.75 for stock TECHO5** and **0.85 for FrankenASP** despite the same configured model threshold. These are end-to-end wake-word activations, **not** threshold-isolated algorithm rankings, false-positive measurements, evidence of better STT accuracy, or proof that a particular factory DSP stage caused the gap. This remains a research project, **not** an Amazon software distribution or a proposal to introduce proprietary processing into upstream TECHO5.

The [initial results dated 23 October](docs/frankenasp/acoustic-results-20261023.md) are preserved as a historical interim snapshot; the **full benchmark linked above supersedes their incomplete level-30 matrix**.

## Licensing, ownership and the proprietary boundary

This distinction is fundamental to the project:

- **Open code:** the distributable FrankenASP source code is offered under the [MIT License](LICENSE); TECHO5-derived portions retain original copyright and license attribution. [Upstream TECHO5](https://github.com/HuskerMinion/techo5) is also MIT-licensed.
- **Amazon components:** the factory DSP libraries (including libasp.so), firmware, calibration, models/configuration and proprietary Android/Bionic runtime files remain proprietary to their respective owners. **They are not licensed under FrankenASP's MIT License and are not bundled, mirrored, uploaded or redistributed here.**
- **Owner-local experiments:** the tools expect compatible files the owner has separately and lawfully obtained from the **owner's own device/backup**, with appropriate authorization. No factory components are downloaded by this project. Hardware ownership alone does **not** establish unrestricted rights to extract, modify, use or redistribute software. Users must consider applicable law, device terms and license restrictions.
- **Independence:** this is an **unofficial third-party project, not affiliated with, endorsed by or supported by Amazon or the TECHO5 maintainers**. Names and trademarks are used only for identification.

The MIT license grants rights **only over materials we may lawfully license**; it grants no rights over Amazon software. Do not post original factory libraries, backup images, device credentials, serial numbers, private speech recordings or unredacted logs in issues or pull requests.

## Building the open-source parts

On Linux, use **Go 1.26**, Python 3 and an official Android NDK (**r27d** was tested). Keep the repositories as siblings:

~~~sh
git clone https://github.com/dmit2k/FrankenASP.git frankenasp
git clone --branch frankenasp-adapter https://github.com/dmit2k/techo5.git techo5-adapter

cd frankenasp
python3 -m unittest discover -s tools/frankenasp/tests -q

export TECHO5_ADAPTER_ROOT="$(cd ../techo5-adapter && pwd)"
bash tools/frankenasp/build_experimental.sh v1.6.0 ./techo5-experimental

export ANDROID_NDK_HOME=/absolute/path/to/android-ndk
bash tools/frankenasp/build_worker.sh ./libasp_stream_worker.so
~~~

The **v1.6.0** base version comes from the tested configuration, **not a universal compatibility guarantee**. Building these programs **does not install or activate them**. Before working with hardware, consult the [split-repository adapter contract](docs/frankenasp/adapter.md), [build instructions](docs/frankenasp/build-on-ubuntu-26.04.md) and [owner-controlled installation, safety and rollback guide](docs/frankenasp/installation.md).

## Current status and future work

The experimental code has passed automated tests and independent builds. Protected startup, real-device worker operation and limited **objective wake-word acoustic measurements** are documented. **The newly separated binaries have not yet been requalified acoustically on the device.** This is not a production-ready or long-term-stability-qualified release.

Further comparisons may include structured **subjective listening assessments**, post-wake command intelligibility/STT under spatial interference, spatial source selection/tracking, longer fault-recovery and stability testing, and a vendor-neutral TECHO5 audio-frontend interface with no Amazon-specific requirement in upstream code. **Measurements, reproducibility and candid negative results remain the project's organizing principles.**

**Thank you again to HuskerMinion and everyone who builds TECHO5.** It is a remarkable project, and we hope this research can eventually make a small, useful contribution alongside it.

