# Factory ASP dependencies by partition — Athena / TECHO5

Research date: 2026-10-23. Scope: Echo Show 8 Gen 2 (Athena, MT8183), original Fire OS PS75741.7080N, Android 9/API 28 ARM32 Bionic.

**Source-only audit. Do not distribute original Amazon binaries, vendor configurations, or personal IDME values.** This is a conservative ELF dependency inventory, not proof that every extracted file is indispensable to every ASP runtime path.

## Survival of original partitions after TECHO5

| Source partition | eMMC GPT | Present TECHO5 mount | Observed outcome |
|---|---|---|---|
| Fire OS `vendor` | p12 | `/vendor` (read-only) | Preserved intact. Factory ASP library, its companion vendor libraries, DSP models/configs remain available. |
| Fire OS `system` | p21 | `/store` TECHO5 slots | Original Android/Bionic system overwritten by TECHO5 installer. Required ARM32 linker/Bionic/VNDK libraries must be restored to a separate local runtime from a pre-install backup. |
| Fire OS `userdata` | p23 | `/data` (bind of `userdata/techo5`) | Preserved; isolated private runtime may be staged here. Not by itself a source of the overwritten factory system. |
| Fire OS `boot` | p20 | kernel boot | Replaced on mainline kernel install; not the ASP ELF runtime. Amp tuning was derived by the installer from pre-install boot. |
| Factory IDME | eMMC boot1 area, not a GPT partition | `layout.Idme` read-only mainline fallback via boot1 | Original microphone coefficients may remain readable without a system image. Do not disclose identifiers/calibration. |

The actual TECHO5 `tools/install-athena.py` does **automatically create host-side partition backups** before writing system and boot, normally at `backups/<serial>/partitions/`. See `docs/install-athena.md`; `--backups` or `TECHO5_BACKUPS` may change the destination. The first-install **Fire OS** `p21-system.img` is the key recovery resource; a post-TECHO5 system image is not a substitute. Nothing is saved automatically on the Echo itself.

## Static closure summary

- 53 extracted factory objects total: 6 from `vendor`, 47 from `system`.
- 4 vendor shared objects, 41 system shared objects, 8 additional files.
- 320 `DT_NEEDED` dependency edges; unresolved SONAMEs: 0. Android linker namespace choices and runtime `dlopen` are not fully captured by this heuristic.
- `libtensorflowlite_c.so` has explicit EGL/GLES dependencies; the graphics/HIDL subtree is part of the conservative static closure even if the speech task has no graphics output.

### Direct DT_NEEDED of `/vendor/lib/libasp.so` (13 entries)

| SONAME | Selected original path | Post-install status |
|---|---|---|
| `libamazonlog.so` | `/vendor/lib/libamazonlog.so` | Preserved p12 |
| `libmedia_helper.so` | `/system/lib/vndk-28/libmedia_helper.so` | Unavailable at original `/system` path (p21 overwritten) |
| `libutils.so` | `/system/lib/vndk-sp-28/libutils.so` | Unavailable at original `/system` path (p21 overwritten) |
| `liblog.so` | `/system/lib/liblog.so` | Unavailable at original `/system` path (p21 overwritten) |
| `libcutils.so` | `/system/lib/vndk-sp-28/libcutils.so` | Unavailable at original `/system` path (p21 overwritten) |
| `libspeexresampler.so` | `/system/lib/vndk-28/libspeexresampler.so` | Unavailable at original `/system` path (p21 overwritten) |
| `libaudioutils.so` | `/system/lib/vndk-28/libaudioutils.so` | Unavailable at original `/system` path (p21 overwritten) |
| `libtensorflowlite_c.so` | `/vendor/lib/libtensorflowlite_c.so` | Preserved p12 |
| `libedgeflow_core_neon.so` | `/vendor/lib/libedgeflow_core_neon.so` | Preserved p12 |
| `libc++.so` | `/system/lib/vndk-sp-28/libc++.so` | Unavailable at original `/system` path (p21 overwritten) |
| `libc.so` | `/system/lib/libc.so` | Unavailable at original `/system` path (p21 overwritten) |
| `libm.so` | `/system/lib/libm.so` | Unavailable at original `/system` path (p21 overwritten) |
| `libdl.so` | `/system/lib/libdl.so` | Unavailable at original `/system` path (p21 overwritten) |

## Exact shared-library inventory by original directory

### `/vendor/lib/` — 4 files (preserved)

- `/vendor/lib/libamazonlog.so`
- `/vendor/lib/libasp.so`
- `/vendor/lib/libedgeflow_core_neon.so`
- `/vendor/lib/libtensorflowlite_c.so`

### `/system/lib/vndk-28/` — 3 files (needs p21 backup)

- `/system/lib/vndk-28/libaudioutils.so`
- `/system/lib/vndk-28/libmedia_helper.so`
- `/system/lib/vndk-28/libspeexresampler.so`

### `/system/lib/vndk-sp-28/` — 3 files (needs p21 backup)

- `/system/lib/vndk-sp-28/libc++.so`
- `/system/lib/vndk-sp-28/libcutils.so`
- `/system/lib/vndk-sp-28/libutils.so`

### `/system/lib/` — 35 files (needs p21 backup)

- `/system/lib/android.hardware.configstore-utils.so`
- `/system/lib/android.hardware.configstore@1.0.so`
- `/system/lib/android.hardware.configstore@1.1.so`
- `/system/lib/android.hardware.graphics.allocator@2.0.so`
- `/system/lib/android.hardware.graphics.common@1.0.so`
- `/system/lib/android.hardware.graphics.common@1.1.so`
- `/system/lib/android.hardware.graphics.mapper@2.0.so`
- `/system/lib/android.hardware.graphics.mapper@2.1.so`
- `/system/lib/ld-android.so`
- `/system/lib/libEGL.so`
- `/system/lib/libGLESv2.so`
- `/system/lib/libbacktrace.so`
- `/system/lib/libbase.so`
- `/system/lib/libc++.so`
- `/system/lib/libc.so`
- `/system/lib/libcutils.so`
- `/system/lib/libdexfile.so`
- `/system/lib/libdl.so`
- `/system/lib/libgraphicsenv.so`
- `/system/lib/libhardware.so`
- `/system/lib/libhidlbase.so`
- `/system/lib/libhidltransport.so`
- `/system/lib/libhwbinder.so`
- `/system/lib/liblog.so`
- `/system/lib/liblzma.so`
- `/system/lib/libm.so`
- `/system/lib/libnativewindow.so`
- `/system/lib/libsync.so`
- `/system/lib/libui.so`
- `/system/lib/libunwind.so`
- `/system/lib/libunwindstack.so`
- `/system/lib/libutils.so`
- `/system/lib/libutilscallstack.so`
- `/system/lib/libvndksupport.so`
- `/system/lib/libz.so`

## Non-shared objects in the extraction set

| Original path | Origin | Role |
|---|---|---|
| `/system/bin/linker` | p21 | **Required in current working launcher:** original ARM32 Bionic ELF interpreter. |
| `/system/bin/sh` | p21 | **Required for this launcher:** factory Bionic shell, copied and patched to `sh-native` with a device-local ELF interpreter path. |
| `/system/etc/ld.config.28.txt` | p21 | Linker namespace config retained for provenance; isolated worker has not independently proven it mandatory. |
| `/system/etc/public.libraries.txt` | p21 | Factory public-library list retained for provenance, not proven mandatory. |
| `/system/etc/public.libraries-AMAZON.txt` | p21 | Amazon public-library list retained for provenance, not proven mandatory. |
| `/system/build.prop` | p21 | Build properties retained for provenance, not proven mandatory. |
| `/vendor/build.prop` | p12 | Vendor properties retained for provenance; p12 preserved. |
| `/vendor/default.prop` | p12 | Vendor default properties retained for provenance; p12 preserved. |

## `/vendor/etc/audio-algorithms/` — 37 factory files (preserved p12)

**Scope warning:** this is the complete observed *Athena* vendor directory
from one Fire OS PS75741.7080N build, **not** a cross-Echo model/firmware
configuration pack. The original `AFE.cfg` and `asp.cfg` both identify
`Hardware Definition.Name = "Athena"`, with **4 microphones and 2 speakers**.
The multiple ASR/VoIP/playback/BT/etc. presets are modes of that hardware;
its beamformer coefficients must not be assumed valid for Crown, Cronos,
Checkers, Rook, Biscuit or Radar. See
[multi-device portability research](multi-device-scope.md).

`libasp.so` references the factory audio-algorithm directory and `asp.cfg` / `AFE.cfg`. `AFE.cfg` mentions 28 filenames from this directory. Those textual references are **not** proof that all files are opened in the active ASR processing path.

- `/vendor/etc/audio-algorithms/AFE.cfg`
- `/vendor/etc/audio-algorithms/EQ_100.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/EQ_30.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/EQ_50.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/EQ_70.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/EdgeflowModelConfig.json`
- `/vendor/etc/audio-algorithms/MBCL_10percent.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/MBCL_20percent.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/MBCL_VOIP.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/MBCL_VOIP_10percent.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/MBCL_VOIP_20percent.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/MBCL_default.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/SpatialAudio_MonoEQ.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/SpatialAudio_SideContentEQ.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/SpatialAudio_UnityEQ.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/SpatialAudio_XTC_Cont_FIR_d_546.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/SpatialAudio_XTC_Ipsi_FIR_d_546.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/SpatialAudio_ZeroEQ.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/UserEQ.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/VOIPRxParametricEQ.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/VOIPTxParametricEQ.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/asp.cfg`
- `/vendor/etc/audio-algorithms/coefs_FBF.cfg`
- `/vendor/etc/audio-algorithms/coefs_FBFV2_LowLatency_8beams.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/coefs_FilterBank_160.cfg`
- `/vendor/etc/audio-algorithms/coefs_FilterBank_640.cfg`
- `/vendor/etc/audio-algorithms/coefs_FilterBank_AnaSyn_M512_D128_Lh512.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/coefs_FilterBank_AnalysisSynthesis_768cvxGLow.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/dtd_cpd_priors.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/es_cpd_priors.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/hamming512_earcon.cfg`
- `/vendor/etc/audio-algorithms/nonPlaybackUspd.tflite`
- `/vendor/etc/audio-algorithms/playbackUspd.tflite`
- `/vendor/etc/audio-algorithms/ue_cpd_priors.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/vad_cpd_priors.cfg` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/vad_lite.tflite` — referenced by `AFE.cfg`
- `/vendor/etc/audio-algorithms/vss_cpd_priors.cfg` — referenced by `AFE.cfg`

`EdgeflowModelConfig.json` also references `nonPlaybackUspd.tflite`, `playbackUspd.tflite`, and `vad_lite.tflite`; this does not independently prove runtime loading.

On the tested post-conversion Athena the full configuration directory exists. The hashes of all four original vendor `.so` libraries and the three files `asp.cfg`, `AFE.cfg`, and `coefs_FBFV2_LowLatency_8beams.cfg` matched the original factory backup exactly.

## Tested isolated runtime layout

```text
TECHO5 mainline kernel + AArch64 Go daemon
  /data/techo5-linux/amazon-arm32/system/bin/sh-native  (ELF32)
    PT_INTERP = /data/techo5-linux/amazon-arm32/system/bin/linker
    LD_PRELOAD = /data/techo5-linux/amazon-arm32/libasp_stream_worker.so
    LD_LIBRARY_PATH = /vendor/lib:
       /data/techo5-linux/amazon-arm32/system/lib:
       /data/techo5-linux/amazon-arm32/system/lib/vndk-28:
       /data/techo5-linux/amazon-arm32/system/lib/vndk-sp-28
    dlopen("/vendor/lib/libasp.so", RTLD_NOW)
      configurations under /vendor/etc/audio-algorithms/
```

The worker library is self-built from public `tools/frankenasp/asp_stream_worker.c`, **not** a recovered Fire OS file. Alpine/musl `.so` libraries cannot be used as drop-in replacements for Android 9 Bionic/VNDK libraries with similar names.

## Advice for users lacking a manual preflash dump

1. **Use the official installer backup first.** Search the computer that ran `tools/install-athena.py`, including any custom `--backups` / `TECHO5_BACKUPS` location, for `partitions/p21-system.img` and `SHA256SUMS`. Check that it truly predates TECHO5.
2. If a pre-TECHO5 p21 image exists, extract the matching ARM32 system libraries and loader using `tools/frankenasp/extract_runtime.py`; the published version also expects a p12 image, even though an intact converted Echo already has the vendor files. That extraction interface can be improved.
3. If no p21 image exists, **do not overwrite p21 or flash an unverified donor image**. The intact p12 does not supply the missing Bionic/VNDK graph. Compatible original Fire OS full-system images or a rebuilt system runtime are possible research directions, but **neither has been validated as a drop-in substitute**.
4. For a normal installation, add a read-only preflight checker and a system-only extraction path that reuses the live `/vendor`. Do not require the owner to copy back the intact vendor partition or publish proprietary payloads.

## Caveats

- These file paths are anchored to the tested Fire OS 7080N build, not guaranteed for all Athena firmware revisions.
- The 41-system-library set is a static, heuristic transitive closure, not a verified minimal runtime file set. A few dependencies might be removable after dynamic loader tracing, and future runtime-only `dlopen`/configuration reads could add files.
- Factory mic calibration may be read from the eMMC boot1 area by `layout.Idme`; absence of `/proc/idme` does not imply the values were destroyed. Avoid double application of calibration until measured.
- This audit is for Athena Gen 2, not Crown Gen 1 (different partitions and installation procedure).
