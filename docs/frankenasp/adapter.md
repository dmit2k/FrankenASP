# Split repositories and adapter contract

FrankenASP is an independent **objective and subjective comparison toolkit**. The native worker and TECHO5 adapter exist so the factory and open voice-processing paths can be studied under repeatable conditions on the same device. The two codebases have separate responsibilities:

| Repo | Owns |
| --- | --- |
| [FrankenASP](https://github.com/dmit2k/FrankenASP) | Original open-source ARM32 Bionic `asp_stream_worker.c`; Android NDK worker build; owner-device preflight, runtime extraction, installer, persistence/watchdog and recovery; acoustic methodology and research documentation |
| [TECHO5 frankenasp-adapter](https://github.com/dmit2k/techo5/tree/frankenasp-adapter) | Athena PCM capture integration; socketless stdin/stdout PCM framing and native worker launch; wake-word mono output routing; feature gate and update guard; Go tests |

**No generic dynamic plugin API exists yet.** The current adapter is an Athena-specific **experimental measurement enabler**, not a recommended permanent substitute for TECHO5's own frontend. Its responsibilities may eventually inform a neutral, versioned `audio-frontend` contract for upstream TECHO5. No extra DSP features or new real-device tests are claimed in this split.

## Check out and build the pair

```sh
git clone https://github.com/dmit2k/FrankenASP.git frankenasp
git clone --branch frankenasp-adapter https://github.com/dmit2k/techo5.git techo5-adapter
cd frankenasp
python3 -m unittest discover -s tools/frankenasp/tests -q
export TECHO5_ADAPTER_ROOT="$(cd ../techo5-adapter && pwd)"
bash tools/frankenasp/build_experimental.sh v1.6.0 ./techo5-experimental
# Requires the official Android NDK:
export ANDROID_NDK_HOME=/path/to/android-ndk
bash tools/frankenasp/build_worker.sh ./libasp_stream_worker.so
```

Set `TECHO5_ADAPTER_ROOT` explicitly; the builder refuses a checkout that lacks the Athena factory-ASP glue. The firmware's TECHO5 base `v1.6.0` must match what is actually installed on the device; do **not** install an arbitrary adapter on a mismatched firmware.

The owner-controlled installer remains in this repository and accepts the adapter-built executable through `--experimental-binary`. See [installation.md](installation.md) for exact preflight and rollback requirements. The runtime location on Athena remains `/data/techo5-linux/amazon-arm32/`, worker `libasp_stream_worker.so`, and the two-channel AWB reference and four-microphone input retain the **same source-level format contract** as the combined prototype. The split **does not itself constitute an on-device requalification**; installation or migration must still be verified under the existing safeguards.

## Historical result provenance

The first experiments measured wake-word activations under self-played Echo music. **Subjective captured-speech comparisons and post-wake STT tests are planned but not yet completed.** The reported differences are research outcomes, not a claim that proprietary factory processing should replace the open frontend.

FrankenASP 1.0 Dev Edition 1's acoustic results, verified SHA-256 and tests refer to the **preserved all-in-one snapshot** in dmit2k/techo5. Extracting the worker and installer into their own repository is a *source reorganization*, not new on-device acoustic validation. For a fully byte-for-byte reproduced installation, pin both revisions together (the adapter SHA and this repository's commit) and capture binary checksums. Do not claim the independent split's newly compiled binaries were acoustically retested until actually tested.

## Future upstream interface

The proposed upstream interface will eventually need explicit mic/ref format negotiation, process lifecycle/health, PCM framing and timestamp semantics, feature gating, safe fallback, and owner-controlled provider selection. Those are future design issues, not working features in this split.
