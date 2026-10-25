# Building FrankenASP Dev Edition on Ubuntu 26.04 LTS

This records a **fresh-host, independent** build/verification on the independent build host (23–24 October 2026) for the FrankenASP **objective and subjective comparison toolkit**. The worker and adapter make two speech frontends observable under controlled conditions; they are **not** a ready-made replacement for TECHO5's own voice processing. It is **not** an instruction to flash a TECHO5 image or to copy Amazon binaries. The deliverable built here is the open-source AArch64 experimental `echod` daemon. The ARM32 native DSP worker is a **separate Android NDK build** (below); the owner's factory `libasp.so` is never built or distributed.

## Tested host and dependencies

| Item | Independent build host |
| --- | --- |
| OS | Ubuntu 26.04 LTS (Resolute Raccoon), x86_64 |
| Kernel | 7.0.0-34-generic |
| Hardware | 8 logical CPUs, 31 GiB RAM |
| Git | 2.53.0 |
| Go | **1.26.0** linux/amd64 (official archive, downloaded independently) |
| Python | 3.14.4 (standard library sufficient for 31 installer/protocol tests) |
| GCC / Clang | GCC 15.2 / Clang 21 present, not needed for `CGO_ENABLED=0` ARM64 daemon |
| Auxiliary tools | Git, curl, CA certificates, file, binutils/readelf, e2fsprogs/debugfs, SSH and tar installed; **patchelf was absent on this build-only host** (required for the separate owner-backup installer/staging workflow) |

On a normal Ubuntu host, the prerequisite packages are:

```sh
sudo apt-get update
# Required for downloading, unpacking, building and testing the open sources:
sudo apt-get install -y git curl ca-certificates python3 file binutils tar unzip

# Additionally required only for owner-device backup preflight and staging:
sudo apt-get install -y e2fsprogs patchelf openssh-client
```

`gcc` and `make` are useful for broader development but are not necessary for the pure-Go cross-build. Do not interpret this package list as permission to install FrankenASP on an unsupported device.

## Install a verified Go toolchain

The Go version is dictated by `echod/go.mod`: `go 1.26.0`. An ordinary `go` executable was **not** preinstalled on the independent build host. For a user-local installation:

```sh
mkdir -p "$HOME/.local/opt"
cd "$HOME/.local/opt"
curl -fL --retry 3 -O https://go.dev/dl/go1.26.0.linux-amd64.tar.gz
echo 'aac1b08a0fb0c4e0a7c1555beb7b59180b05dfc5a3d62e40e9de90cd42f88235  go1.26.0.linux-amd64.tar.gz' | sha256sum -c -
tar -xzf go1.26.0.linux-amd64.tar.gz
export PATH="$HOME/.local/opt/go/bin:$PATH"
go version
```

The SHA-256 above was obtained from the official `go.dev/dl/?mode=json&include=all` release metadata and verified against the downloaded 66,768,540-byte archive.

## Clean source checkout and tests

```sh
git clone https://github.com/dmit2k/FrankenASP.git frankenasp
git clone --branch frankenasp-adapter https://github.com/dmit2k/techo5.git techo5-adapter
# Pin the adapter revision used in the independent split CI;
# do not assume the development branch will always remain unchanged.
git -C techo5-adapter checkout --detach 046589f6c6d5a33d5840c734b5b0cc603ce4ba28
# Fetch upstream release tags: the builder verifies the real baseline by ancestry.
git -C techo5-adapter fetch --tags https://github.com/HuskerMinion/techo5.git
cd frankenasp
test -z "$(git status --porcelain)"
python3 -m unittest discover -s tools/frankenasp/tests -q

cd ../techo5-adapter/echod
go test -p 3 ./... -count=1
go test -p 3 -tags dot ./... -count=1
go test -p 3 -tags spot ./... -count=1
go test -p 3 -tags panel ./... -count=1
GOOS=windows go vet -p 3 ./cmd/techo5-deck
GOOS=darwin go vet -p 3 ./cmd/techo5-deck
cd ../../frankenasp
```

`-p 3` bounds package-build concurrency; it is not required for functional correctness. Keep diagnostics/logs and downloaded toolchains **outside the source checkout** so that the release builder can stamp a clean commit instead of `.dirty`.

For the historical **combined** Dev Edition source, see the [original snapshot](https://github.com/dmit2k/techo5/tree/snapshot/frankenasp-v1.0.0-dev.1). The separated research toolkit and adapter must be treated as a **pair of source revisions**, not as an arbitrary FrankenASP tag combined with whichever adapter branch HEAD happens to be latest.

## Reproducible AArch64 experimental daemon build

```sh
# Use the official TECHO5 release already installed on your Athena as the base.
export TECHO5_ADAPTER_ROOT="$(cd ../techo5-adapter && pwd)"
bash tools/frankenasp/build_experimental.sh v1.6.0 ./techo5-experimental
file ./techo5-experimental
readelf -h ./techo5-experimental | grep -E 'Class:|Machine:'
sha256sum ./techo5-experimental
git status --porcelain
```

Expected architecture: **ELF64 AArch64**. The experimental daemon stamps three identities: the **owner-selected upstream TECHO5 baseline** before `_`, the nearest reachable **FrankenASP release tag** (or `dev`, with `.nextN` for subsequent commits) and shortened **FrankenASP and adapter source SHAs** after `_`. For a clean checkout at the research release, the format is `v1.6.0_frankenasp-1.0.0-dev.1.f<franken-SHA10>.a<adapter-SHA10>`. Go's `layout.GitCommit` metadata contains **both full 40-character SHAs**. Changes in either checkout add `.fd<digest>` and/or `.ad<digest>`, so a dirty source cannot masquerade as the tagged release. A checkout beyond the tag additionally gets `.nextN` (unreleased development).

**Important:** the requested TECHO5 base must exist as an official Git release tag in the adapter checkout, be an ancestor of its HEAD, and be the newest released baseline contained in that history. The builder rejects missing, unrelated or outdated baselines. Fetch official tags as shown above; if a shallow clone lacks older ancestry, unshallow it or fetch sufficient upstream history before retrying. Do not invent a newer base merely to suppress OTA. This is a source-provenance check, **not** acoustic or on-device compatibility certification. The portion after the underscore is ignored for HA version ranking, and binary hashes may differ because builds are timestamped.

## ARM32/Bionic worker and device-side components

The open worker source `tools/frankenasp/asp_stream_worker.c` is compiled using the official **Android NDK ARMv7 API 28** toolchain, not host glibc. Install Android NDK r27d using **standard `unzip`** (no Python extraction or manual correction of executable permissions/symlinks is necessary):

```sh
mkdir -p "$HOME/.local/opt"
(
  cd "$HOME/.local/opt"
  curl -fL --retry 3 -O https://dl.google.com/android/repository/android-ndk-r27d-linux.zip
  echo '22105e410cf29afcf163760cc95522b9fb981121  android-ndk-r27d-linux.zip' | sha1sum -c -
  unzip -q android-ndk-r27d-linux.zip
)
export ANDROID_NDK_HOME="$HOME/.local/opt/android-ndk-r27d"
test -x "$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/bin/armv7a-linux-androideabi28-clang"
```

The subshell leaves your current working directory unchanged. **From the FrankenASP repository root**, build and inspect the independent worker:

```sh
bash tools/frankenasp/build_worker.sh ./libasp_stream_worker.so
readelf -h ./libasp_stream_worker.so | grep -E 'Class:|Machine:'
```

The official NDK ZIP is large and its extraction needs sufficient disk space. The published SHA-1 value checks the downloaded archive against the recorded NDK r27d checksum; download it only from the official Google URL over HTTPS.

The ARM32 worker is **not** produced by the Go-only build above. Private factory binaries, original Bionic runtime files, DSP configurations, factory beamformer coefficients and user recordings are **not** included in this repository or a public release. Use the owner-specific read-only preflight, explicit `--install`, guarded activation and rollback procedures in [installation.md](installation.md).

### Independent native-worker build actually performed on the independent build host

The additional **ARM32/Bionic native worker** was successfully built using **Android NDK r27d (27.3.13750724)**, downloaded from Google's official Android repository. Google's release checksums list the `android-ndk-r27d-linux.zip` size as **663,956,036 bytes**, SHA-1 **`22105e410cf29afcf163760cc95522b9fb981121`**, which was verified after the download. No proprietary Amazon files were needed.

The output was verified as `ELF32 ARM EABI5`, API 28, built by NDK r27d, and the worker's glibc-reference guard passed:

```text
libasp_stream_worker.so SHA-256:
7017258766e7496b088a8b11b06b7b5ed11ae647c55831c3ee58aacab47dd649
```

The Go archive and official Android NDK archive were independently checksum-verified, and `tar -xzf` plus `unzip -q` were **successfully exercised in a fresh, ordinary Linux build environment**. These are the recommended extraction methods; no special extraction scripts or remote-executor workarounds are necessary.

## Scope and safety

Supported research prototype: **Echo Show 8 Gen 2 (Athena)** with the specifically validated original factory DSP revision and TECHO5 AArch64 baseline. Short guarded runs, native PCM continuity, a persistent startup probation/stock fallback, and controlled **wake-word-only** acoustic comparisons have been demonstrated. Published mono/stereo modes describe the Echo's **own background-music speaker output**, not its microphone channel count. Post-wake STT, longitudinal stability, false-positive qualification, alternate factory firmware and other Echo models remain unverified.

See [initial acoustic results](acoustic-results-20261023.md) and [release notes](release-v1.0.0-dev.1.md).

**Migration/provenance note:** the historical independent CI and acoustic experiment used the preserved combined Dev Edition snapshot. The later repository split was independently rebuilt and retested, but the *split binaries have not undergone a new on-device acoustic A/B study*. For new checkouts, `TECHO5_ADAPTER_ROOT` is required. See [the split integration contract](adapter.md).
