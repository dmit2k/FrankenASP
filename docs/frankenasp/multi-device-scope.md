# Can Franken ASP support every TECHO5 Echo?

FrankenASP's principal purpose is **independent objective and subjective comparison**, not deployment of Amazon processing across every TECHO5 device. Any future support for another board would require a fresh, board-specific research protocol and owner-provided factory components — not simply reusing Athena's DSP files.

**Scope note (2026-10-23):** the **37** files listed in
[the partition dependency inventory](partition-dependencies-20261023.md)
are the complete *observed directory inventory* of
`/vendor/etc/audio-algorithms/` from **one Amazon Echo Show 8 Gen 2
(Athena, MT8183), original Fire OS PS75741.7080N**. They are **not** a
collection of configurations for all Echo models, firmware revisions, or
TECHO5-supported devices.

## Direct evidence that this is an Athena-specific factory bundle

The actual original configuration files have explicit hardware identity:

| File | Verified original field | Meaning |
|---|---|---|
| `/vendor/etc/audio-algorithms/AFE.cfg` | `Hardware Definition.Name = "Athena"` | Identifies the target board |
| `AFE.cfg` | `Num Mics = 4`, `Num Speakers = 2` | Specifies Athena's audio hardware topology |
| `AFE.cfg` | microphone input and loopback reference at **96 kHz**; ASR path at **16 kHz** | Specifies its signal formats/rates |
| `/vendor/etc/audio-algorithms/asp.cfg` | `Hardware Definition.Name = "Athena"` | Second independent board identity |
| `asp.cfg` | `Mics.Num = 4`, `Speakers.Num = 2` | Agrees with the Athena topology |
| `asp.cfg` | ASR: six interleaved input channels at 96 kHz, mono output at 16 kHz | The ABI exercised by the present research worker |
| `AFE.cfg` | `coefs_FBFV2_LowLatency_8beams.cfg` | Beamformer coefficients selected by this board's configuration |

That bundle contains **multiple paths or presets for the same board**:
ASR, voice/VoIP, playback, ultrasonic/presence processing, EQ and
volume-dependent profiles. Within ASR it also has operating-mode
parameters for internal speaker, Bluetooth, line-out and WHA. Those
modes **do not represent different Echo models**.

The configuration itself even comments that Crown and Athena have
*different hardware microphone gains* (the Athena microphone
preprocessing boost is documented as 5.89 dB). The presence of another
board name in a comment is **not** the presence of its tuning files.

The **37** count is the number of files found on the one inspected
vendor partition, **not 37 device types** and **not 37 files guaranteed
to be loaded during ASR**. For example, `AFE.cfg` textually references
28 other filenames, but only a subset belongs to the active ASR chain.

## What can and cannot be universal

**Plausibly reusable source-side framework:**

- select a validated board+factory-firmware profile, then perform
  read-only dependency and vendor configuration checks;
- extract or locate an *owner-provided* matching native runtime
  (Bionic/linker/VNDK or other native environment as actually used);
- supervise an isolated factory DSP subprocess, bound IPC deadlines and
  process failure, feed 16-kHz speech to the existing MWW/STT pipeline;
- preserve official TECHO5 as the default, with guarded opt-in,
  controlled rollback, verified device volume and playback settings;
- compare **objective measurements and subjective assessments of processed microphone speech** under a reproducible, per-device A/B test protocol; do not conflate microphone quality with speaker playback quality.

**Necessarily device- or firmware-specific until proven otherwise:**

- original ASP library presence, SONAMEs, ABI and exact exported API;
- compatible native dynamic linker, system/vendor libraries and firmware;
- microphone count, channel order, PCM alignment, sampling rates;
- microphone array geometry, beamformer weights, acoustic calibration;
- where to capture synchronized stereo/mono playback reference (hardware
  AWB, hardware I2S loopback, software tap or absent);
- ALSA/ASoC device names, kernel drivers, mixer routing and cleanup;
- availability/persistence of the factory `vendor` partition after the
  board-specific TECHO5 installer;
- per-board native performance and recovery behavior.

**A vendor-neutral audio-frontend adapter may be useful for future open-source measurement, but is not required for FrankenASP's Athena research mission.** A universal adapter framework is only a possible future engineering direction. A universal Athena `libasp.so`/configuration pack for other Echos is **neither demonstrated nor a supported usage**. Shared Amazon
algorithm family names (`AEC_V2`, `FBF_V2`, `ARA_V2`) are not
evidence of a portable binary+calibration bundle.

## Compatibility research status

| TECHO5 device | Board | Factory ASP port status |
|---|---|---|
| Echo Show 8 Gen 2 | `athena` | **Live prototype demonstrated** for the tested original Fire OS build; worker hangs and rollback tested; **limited wake-word-only acoustic A/B results obtained under Echo self-played music** ([measurements](acoustic-results-20261023.md)); general speech/audio quality, subjective comparisons, post-wake STT and long-duration stability **not yet qualified** |
| Echo Show 8 Gen 1 | `crown` | **Not investigated** here; needs its own factory DSP binary/config/ABI and audio capture/reference study |
| Echo Show 5 Gen 2 | `cronos` | **Not investigated** here; no evidence Athena's coefficients or runtime are usable |
| Echo Show 5 Gen 1 | `checkers` | **Not investigated** here |
| Echo Spot Gen 1 | `rook` | **Not investigated** here; separate TECHO5 Spot repository |
| Echo Dot Gen 2 | `biscuit` | **Not investigated** here; separate TECHO5 Dot repository |
| Echo Gen 2 | `radar` | **Not investigated** here; separate TECHO5 Dot repository |

Other TECHO5 ports, including Android Panel and the Skylight
Calendar (which has no microphone), are **not automatically within
the scope** of a native Amazon Echo factory microphone DSP adapter.
The table is not a statement that `libasp.so` exists on every listed
Echo. Confirm that first.

## Proposed portability architecture (future work, not implemented)

Model-specific adapters could satisfy a common, strictly validated
processing contract:

1. **Board detection:** verify manufacturer hardware ID and current
   kernel/TECHO5 capture implementation; do not infer model from the
   presence of a config filename alone.
2. **Factory identity:** record original firmware build identifier and
   cryptographic hashes of the local factory library and configuration
   bundle, without uploading proprietary files or IDME data.
3. **Native dependency profile:** enumerate and verify ELF closure,
   loader ABI, sysroot and dynamic-load requirements. Determine
   independently whether stock factory partitions remain mounted or
   have been overwritten.
4. **Capture/profile adapter:** specify mic count, sample rates,
   interleaving, reference source, timing, calibration and DSP ABI.
   Never reuse Athena-specific channel or mixer constants by default.
5. **Fail-safe activation:** only expose the opt-in after all checks
   succeed; preserve user volume and playback; watchdog active
   subprocess health and automatically restore TECHO5.
6. **Per-board qualification:** native worker startup, bounded IPC
   stall, SIGTERM/SIGSTOP recovery, ALSA cleanup, then controlled
   acoustic A/B testing for that *specific board and firmware version*.

A prospective profile must be **versioned by board and factory
firmware**, not only by the library filename. Do not enable a device
just because it also has a `libasp.so`.

## Packaging and intellectual property

Only the portable framework, adapter source, tests, version/hash
metadata and instructions should go into the public GitHub branch.
Original Amazon binaries, beamformer coefficients, tuning configs,
firmware images and user-specific calibration belong **on the owner's
own hardware or in the owner's private backup**, never in the repo.

For the existing Athena build, the preserved read-only `/vendor`
supplies the original factory library, companion vendor libraries and
37 configs. The overwritten p21 `/system` supplies the missing
Android 9 ARM32 linker/Bionic/VNDK components only if the user has
a matching preinstall backup (which the official Athena installer
normally creates on the installation computer).

See [partition dependencies](partition-dependencies-20261023.md) for
the exact Athena filenames, [architecture](architecture.md) for
the tested audio contract, and [runtime](runtime.md) for the limited
owner-local setup.
