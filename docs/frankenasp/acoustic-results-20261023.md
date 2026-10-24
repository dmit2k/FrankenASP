# Initial acoustic results — Echo Show 8 Gen 2 (Athena)

**23 October 2026 · Research preview · Wake-word activations during music playback by the Echo itself**

This document records the **first limited measurement output of an independent A/B research instrument**, not a preselected winner or a recommendation to replace TECHO5's audio frontend. The FrankenASP proof of concept was run on real Athena hardware, using the device's original Amazon speech-input ASP through an owner-local ARM32/Bionic worker. Startup, continuous PCM output, wake-word input, and guarded recovery have been demonstrated. Controlled, repeated acoustic testing shows a substantial initial wake-word detection advantage over the stock TECHO5 voice frontend. This is a practical engineering comparison, **not** a long-duration reliability qualification or an academic characterization of individual DSP algorithms.

## Scope of this first acoustic comparison

**These measurements cover wake-word detection only, while the Echo Show 8 itself was playing background music through its built-in speakers.** They do **not** measure recognition or intelligibility of the spoken command *after* wake-word activation. In some scenarios, speech stimuli and interfering TV audio were also emitted by separate, spatially positioned external loudspeakers. Those external sources were test stimuli/interference, **not** the source of the Echo's own background music.

In the result table, **mono** and **stereo** refer **only to the Echo's built-in music/speaker playback setting**:

- **Mono playback:** the Echo reproduces its background music in mono via its own speakers.
- **Stereo playback:** the Echo reproduces the background music with separate left and right speaker channels.

They **do not** mean single- versus multi-microphone capture, alternative microphone beamforming modes, or mono versus stereo output from Amazon ASP. The same four physical microphones are used in both playback conditions, and the audio delivered to the wake-word detector is mono PCM at 16 kHz. The compared *voice frontends* are stock TECHO5 processing and FrankenASP's original Amazon factory processing. The playback mode can change the echo/reference conditions and thus affect wake-word performance.

## First-pass results

**Successful wake detections / 60 scheduled utterances** (near misses do *not* count as detections):

| Speech stimulus level | Stock TECHO5 + mono music | Stock TECHO5 + stereo music | FrankenASP + mono music | FrankenASP + stereo music |
| --- | ---: | ---: | ---: | ---: |
| 30 — quiet | Not in this matched series | Not in this matched series | **41/60 (68.3%)** | **45/60 (75.0%)** |
| 35 — normal | 45/60 (75.0%) | 22/60 (36.7%) | **59/60 (98.3%)** | **54/60 (90.0%)** |
| 40 — loud | 49/60 (81.7%) | 33/60 (55.0%) | **60/60 (100%)** | **59/60 (98.3%)** |

The **30/35/40 labels denote controlled stimulus playback levels**, used here as quiet/normal/loud test voice levels; they are not calibrated sound-pressure levels. An earlier stock TECHO5 level-30 session exists but is not merged into the later comparison matrix as an equivalent full control.

**Threshold caveat (important):** stock TECHO5 had MWW cutoff configured at 0.85, but the *observed effective cutoff during music playback* was **0.75**. FrankenASP's observed effective cutoff remained **0.85**. Thus the factory frontend's higher detection rate was observed despite its *stricter* wake-word threshold. This comparison describes end-to-end behavior under the measured settings; it is not a same-threshold DSP-only isolation experiment. False-positive trade-offs were not established by these trials.

## Test approach, in brief

- Same physical Athena Echo Show 8 Gen 2, wake-word model, room arrangement, and scripted speech material.
- Five predefined spatial scenarios per level, **12 utterances each** (60 per mode/level), including separately positioned voice and interfering TV audio.
- Fixed background music played **by the Echo's own speakers**, controlled track restart/playback position, playback-state verification, and explicit **speaker music output** mono/stereo selection. The wake-word stimulus and, where applicable, TV interference came from external spatially positioned loudspeakers.
- Wake events/near misses collected from device logs and matched to the stimulus schedule. Completed stock runs cover levels 35 and 40; FrankenASP was tested at 30, 35 and 40 with both speaker modes.
- The prototype uses four real microphone channels and the original factory speech-processing library. Amazon binaries, calibration data, private voice recordings and raw device logs are **not** distributed in this repository.

## What this establishes — and what it does not

Within these **Echo-playing-music** conditions, the factory ASP path consistently achieved **markedly better wake-word activation rates**, including adverse spatial/interference scenarios and the stereo speaker-playback condition. The results quantify a difference **within this controlled wake-word test**, rather than ranking either frontend in general. They **do not identify AEC, beamforming, beam selection, denoising, or any particular component as its proven cause**. Other conditions, including false-positive behavior and subsequent commands, might change the practical trade-off.

The prototype does not reproduce the complete original Fire OS voice stack. Long-running stability, false-positive rate, cross-device and cross-firmware compatibility, and **post-wake command intelligibility/STT under spatial interference** remain for later research.

The broader comparative program also envisages **subjective listening to captured/processed microphone PCM**, independent objective STT measurements, detailed documentation of the automated test rig and acoustic geometry, and tests of spatial-tracking hypotheses. **Those subjective and post-wake studies were not part of the reported wake-word series.** These preliminary findings should not delay that work or be represented as a production-ready FrankenASP release.
