# Factory ASP architecture: observations versus hypotheses

**Context:** This architecture documents the experimental plumbing for an **independent A/B comparison** of TECHO5 and original factory microphone processing. It does not prescribe which frontend should be used in production. Subjective and objective evaluation must distinguish actual measurements from assumptions about internal DSP algorithms. See the [completed limited wake-word series](acoustic-results-20261023.md) and [comparative methodology](testing.md).

## Verified I/O surface on Athena (Gen 2)

| ALSA | Description | Captured PCM format |
|---|---|---|
| `hw:0,0` | DL1 playback | stereo S16_LE, 96 kHz |
| `hw:0,1` | DL1_AWB_Record | stereo S16_LE, 96 kHz |
| `hw:0,2` | microphone capture / VUL12 | four S32_LE channels, 96 kHz |

The existing upstream Athena kernel patches `patch-afe-di2.py` and
`patch-afe-awb-dl1.py` provide the four-microphone and physical stereo AWB
capture paths, respectively. **Credit:** [@nuno407](https://github.com/nuno407)
authored the [DL1_AWB_Record kernel change (PR #214)](https://github.com/HuskerMinion/techo5/commit/c94f013b8d6d30e49f3262649e0c243363e5b72c).
It added the missing AFE routes `UL2_CH1 DL1_CH1` and `UL2_CH2 DL1_CH2`,
allowing the two-channel, 96 kHz playback reference to be captured alongside
the four-channel, 96 kHz microphone stream. This gives comparative research
access to **a hardware input arrangement closer to the one used by Fire OS**,
rather than relying solely on a software reference. The contribution belongs
to TECHO5's open kernel/hardware support; FrankenASP builds on it.

Matching the available microphone/reference **channel topology and nominal
sample rates** does **not** establish identical calibration, clock alignment,
latency, playback tap position, echo cancellation or other internal DSP
behavior. The hardware AWB stream is distinct from TECHO5's software playback
reference; its precise tap position relative to output DSP still requires
verification in the specific test setup.

## Prototyped Franken path

1. Read four 96 kHz S32 microphone channels and two 96 kHz S16 AWB channels.
2. Arithmetic-shift left-aligned 24-bit microphone values right by eight,
   multiply by owner-device IDME Q30 calibration, and clamp to signed 24-bit.
3. Store 4 microphone S32 slots and 2 reference S32 slots (each S16 shifted
   left by 16), interleaved at 96 kHz: `768 x 6 x 4 = 18432` bytes per 8 ms.
4. ARM64 TECHO5 communicates with an isolated ARM32/Bionic native process by
   fixed-sized binary stdin/stdout blocks. Original DSP returns mono signed
   PCM16, 16 kHz: `128 x 2 = 256` bytes per 8 ms.
5. Native output reaches MWW and ASR, bypassing TECHO5's second software AEC,
   denoiser and leveler. A FIFO reconciles 8-ms DSP and 20-ms TECHO5 callbacks.

The worker resolves `asp_init`, `asp_deinit`, `asp_create_pipeline`,
`asp_destroy_pipeline`, `asp_set_ext_ref_sync_status` and `asp_process`.
The prototype has established an ABI on one FireOS build; cross-version
ABI compatibility is NOT established.

Original configuration and symbols refer to `AEC_V2`, `FBF_V2`
(eight beam directions), `ARA_V2`, VAD and reference managers. This is
NOT proof of their exact processing order or the implementation of steering,
beam selection or echo path tracking.

## Microphone calibration and unresolved issues

Owner-specific IDME entries `miccal.0` through `miccal.3` are applied as
Q30 coefficients (unity = `1 << 30`). Missing or invalid values fall back
to unity. Their private numeric values must never be logged or published.
Physical capsule ordering, phase/time skew, geometry and additional
response calibration remain unverified.

Original physical playback-to-mic delay, AEC convergence, sample timing,
alignment and drift remain to be measured. During previous extended live
work, playback/TTS once stopped with an MT8183 AFE IRQ status
`0xdddd0000` while MWW continued. Causality is unproven; investigate
ALSA/DMA/IRQ transitions across DL1, AWB and VUL12, and verify recovery.

Frame-processing timing measured on an external test runner must not be
presented as Show 8 CPU performance. **Earlier qualitative wake observations**
are not statistical evidence of general superiority; later controlled
wake-word counts support only the limited conditions described in the
[October 23 results](acoustic-results-20261023.md).
