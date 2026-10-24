# Franken ASP on Athena: automated staging and hands-on installation

**Experimental Athena only — voice capture / microphone DSP, not speaker sound quality.**
This is a preparation/staging guide for **independent comparative research**,
**not** a supported permanent replacement or recommended upgrade for TECHO5.
The opt-in native frontend is a means of collecting objective measurements and
future subjective captured-speech comparisons, not the project's principal
product. This guide does **not** perform live acoustic trials, change speaker
settings or turn on factory ASP. No factory firmware or coefficient files are distributed.

## What you need

1. **Echo Show 8 Gen 2, Athena/MT8183**, already running the experimental
   TECHO5 AArch64 mainline build, with original `/vendor` preserved,
   mounted **read-only**. Currently qualified for staging only against
   original factory **PS75741.7080N**, Android 9/API28, and one verified
   `libasp.so` SHA-256. Other Echo models, firmware revisions and software
   stacks are **not** compatible by default.
2. A backup of your **own device from before the initial TECHO5 install**.
   Pass the directory that directly contains `p21-system.img`, e.g.
   `backups/<your-device>/partitions/`. The official
   `tools/install-athena.py` normally creates this directory on the
   **installer's computer**, not on the Echo. A system image backed up
   after TECHO5 replaced the stock system is **not valid**.
3. Linux host with Python 3, `debugfs` (`e2fsprogs`), `readelf`
   (`binutils`), `patchelf`, `tar`, an SSH client, and a key that
   already grants **root SSH** to your own Echo. No Android kernel
   compilation or privileged filesystem mount is needed to inspect
   and extract the original system image.
4. An **Android NDK** containing the
   `armv7a-linux-androideabi28-clang` cross-compiler, or your own
   previously built **ARM32 Android/Bionic worker** `.so`.
5. An independently built **AArch64 experimental TECHO5 daemon**
   containing FrankenASP integration from the companion `frankenasp-adapter` branch. The
   unmodified official TECHO5 daemon does not contain those features.
   You must provide this binary explicitly; the installer will not
   download an unverified release or overwrite the official binary.
6. Sufficient free disk space for the original backup, staging and
   transfer, and a working rescue/recovery route for the Echo.

The original `/vendor/lib/libasp.so` and
`/vendor/etc/audio-algorithms/` already remain **on the Echo**. **Do
not** copy or flash a vendor partition to install FrankenASP.

## A. Automated workflow (recommended preparation)

From the root of the experimental FrankenASP source checkout:

```sh
# 1. Point explicitly to YOUR backup directory. There is no autodiscovery.
BACKUP_PARTITIONS="/path/to/backups/YOUR_DEVICE/partitions"
ECHO="root@YOUR_ECHO_IP"
ANDROID_NDK_HOME="/path/to/android-ndk"

# 2. Safe, READ-ONLY check; this is the default (no --install).
python3 tools/frankenasp/install.py \
  --backup-partitions "$BACKUP_PARTITIONS" \
  --device "$ECHO"
```

The check verifies the backup's `SHA256SUMS` entry when present, the
original `system` build properties, all 47 required/referenced system
runtime files, the actual board/kernel, read-only vendor mounting,
original vendor dependencies and the known matching factory
`libasp.so` hash. It does not touch the device.

If your legitimate backup has **no `SHA256SUMS` manifest**, inspect its
provenance carefully and explicitly pass
`--accept-unverified-backup`. That option only bypasses the
**backup-image checksum ledger**; it does **not** relax board, factory
firmware or `libasp.so` identity checks.

Build your **own** experimental daemon from the companion
[dmit2k/techo5 `frankenasp-adapter` branch](https://github.com/dmit2k/techo5/tree/frankenasp-adapter). Example for an appropriately configured Go toolchain:

```sh
# Use the actual TECHO5 release currently installed on the Echo as the base.
# Example: v1.6.0. No upstream version is faked or raised merely to hide updates.
# Fetch official TECHO5 release tags before building: the script verifies base ancestry.
git -C /absolute/path/to/techo5-frankenasp-adapter fetch --tags https://github.com/HuskerMinion/techo5.git
export PATH="/path/to/go1.26/bin:$PATH"
export TECHO5_ADAPTER_ROOT="/absolute/path/to/techo5-frankenasp-adapter"
bash tools/frankenasp/build_experimental.sh v1.6.0 ./techo5-experimental
```

Check the resulting ELF:

```sh
readelf -h ./techo5-experimental | grep -E 'Class:|Machine:'
# Expected: ELF64, AArch64.
```

The complete, **explicitly authorized staging** command is:

```sh
python3 tools/frankenasp/install.py \
  --backup-partitions "$BACKUP_PARTITIONS" \
  --device "$ECHO" \
  --android-ndk "$ANDROID_NDK_HOME" \
  --experimental-binary ./techo5-experimental \
  --install
```

If you built the ARM32 worker earlier, substitute
`--worker /path/to/libasp_stream_worker.so` for `--android-ndk`.

`--install` extracts the original **system-only** runtime into a
temporary **private host directory**, builds or copies the
independently authored worker, and patches a **copy** of the original
Android shell to point to a private Bionic linker. It transfers only
the new, checksummed private staging directories:

| Target on Echo | Contents |
|---|---|
| `/data/techo5-linux/amazon-arm32/` | original owner-local `system` linker, Bionic/VNDK ELF closure, patched `sh-native`, self-built worker |
| `/data/techo5-linux/frankenasp-trial/` | self-built AArch64 experimental TECHO5 daemon, guarded `trial.sh` controller |

Remote staged files are checksum-verified before renaming the incoming
directories into place. All staging resides under `/data`. The
installer **refuses to overwrite** either existing destination
directory, an active trial, or TECHO5's hold marker. It does not set
`fireos-asp.enabled`, the volatile armed marker, or create a service.

If you explicitly want to inspect every staged file afterward, add
`--stage-dir /some/new/private/host/directory`; it must **not** already
exist. That directory contains proprietary copies from your backup:
keep it private, away from Git and public bug reports.

Verify from the host **without starting audio**:

```sh
ssh "$ECHO" 'test -x /data/techo5-linux/amazon-arm32/system/bin/sh-native && echo RUNTIME_STAGED'
ssh "$ECHO" 'test -s /data/techo5-linux/amazon-arm32/libasp_stream_worker.so && echo WORKER_STAGED'
ssh "$ECHO" 'test -x /data/techo5-linux/frankenasp-trial/techo5-experimental && echo EXPERIMENT_STAGED'
ssh "$ECHO" 'test ! -e /data/techo5-linux/fireos-asp.enabled && test ! -e /run/techo5/frankenasp-armed && echo FACTORY_MODE_OFF'
```

**A successful installation means staged files only**, not a verified
running DSP. The official TECHO5 binary, boot/system/vendor partitions,
amplifier and playback settings remain untouched. A different,
deliberate guarded trial procedure is described in
[`runtime.md`](runtime.md), but **live tests are postponed** for now.

## B. Hands-on process: understand every component

Use this if you want to audit the format, ELF dependencies and native
loader integration personally, rather than running the combined installer.
Run these commands on your Linux host, not on the Echo, until the
explicit file-transfer step.

### 1. Verify the factory backup and stock vendor

```sh
BACKUP_PARTITIONS="/path/to/backups/YOUR_DEVICE/partitions"
SYSTEM_IMAGE="$BACKUP_PARTITIONS/p21-system.img"
ECHO="root@YOUR_ECHO_IP"

# Same checks as the automated script; no device writes.
python3 tools/frankenasp/install.py \
  --backup-partitions "$BACKUP_PARTITIONS" --device "$ECHO"

# Inspect any single factory file WITHOUT extracting or mounting:
debugfs -R 'stat /system/bin/linker' "$SYSTEM_IMAGE"
debugfs -R 'stat /system/lib/vndk-28/libmedia_helper.so' "$SYSTEM_IMAGE"

# See the Android ARM32 ABI and native factory identity.
ssh "$ECHO" 'sha256sum /vendor/lib/libasp.so'
ssh "$ECHO" 'mount | grep " /vendor "'
```

**Important image-layout detail:** `p21-system.img` contains the
`/system` directory *inside* the ext4 image. The actual debugfs path
is `/system/lib/...`, not `/lib/...`. No mount and no writable
filesystem operation is needed.

### 2. Extract only the original system runtime, not vendor

The tested conservative dependency set is **41 system `.so` files,
the ARM32 `linker` and `sh`, and four auxiliary build/linker configs**.
A helper table of their exact names lives in `preflight.py`:

```sh
# This creates a private local tree, not an image of the whole system.
umask 077
mkdir -m 700 -p "$HOME/frankenasp-private"
STAGE="$HOME/frankenasp-private"

# Example single-file extraction:
mkdir -p "$STAGE/system/bin"
debugfs -R "dump /system/bin/linker $STAGE/system/bin/linker" "$SYSTEM_IMAGE"
readelf -h "$STAGE/system/bin/linker" | grep -E 'Class:|Machine:'
```

For the full list without manually typing 47 filenames:

```sh
STAGE="$STAGE" SYSTEM_IMAGE="$SYSTEM_IMAGE" python3 - <<'PY'
import os, sys, subprocess
from pathlib import Path
sys.path.insert(0, str(Path("tools/frankenasp").resolve()))
from preflight import REQUIRED_SYSTEM, OPTIONAL_SYSTEM
stage = Path(os.environ["STAGE"]).resolve()
image = Path(os.environ["SYSTEM_IMAGE"]).resolve()
for rel in REQUIRED_SYSTEM + OPTIONAL_SYSTEM:
    dst = stage / "system" / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if any(ch.isspace() for ch in str(dst)):
        raise SystemExit("Use a private stage path without spaces for debugfs dump")
    subprocess.run(["debugfs", "-R",
                    "dump /system/" + rel + " " + str(dst), str(image)], check=True)
    if not dst.is_file() or dst.stat().st_size == 0:
        raise SystemExit("Bad extraction: " + rel)
for exe in ("linker", "sh"):
    (stage / "system/bin" / exe).chmod(0o755)
print("Extracted original system-only closure to private staging")
PY
```

Do **not** extract `/vendor` a second time. The real device will load
`/vendor/lib/libasp.so`, `libamazonlog.so`, `libtensorflowlite_c.so`,
`libedgeflow_core_neon.so` and the board-specific AFE configs directly
from the preserved, read-only vendor partition.

### 3. Build the independent worker and patch the original shell copy

```sh
export ANDROID_NDK_HOME="/path/to/android-ndk"
bash tools/frankenasp/build_worker.sh "$STAGE/libasp_stream_worker.so"
cp "$STAGE/system/bin/sh" "$STAGE/system/bin/sh-native"
patchelf --set-interpreter \
  /data/techo5-linux/amazon-arm32/system/bin/linker \
  "$STAGE/system/bin/sh-native"
chmod 755 "$STAGE/system/bin/sh-native"

readelf -l "$STAGE/system/bin/sh-native" | grep amazon-arm32
readelf -h "$STAGE/libasp_stream_worker.so" | grep -E 'Class:|Machine:'
readelf --version-info "$STAGE/libasp_stream_worker.so" | grep GLIBC_ && \
  echo 'ERROR: glibc worker' || echo 'No GLIBC version dependency found'
```

The Android **32-bit** Bionic interpreter is not the same executable as
the Echo's **64-bit** Linux ELF interpreter. The patched
`sh-native` is a separate copy and must resolve its dependencies
using the intended private `system/lib`, VNDK and the intact
`/vendor/lib`. This manual example demonstrates the ABI structure;
the automated installer adds required checksums and overwrite guards.

### 4. Install manually only after reviewing your private payload

**Only on an Echo with no previous FrankenASP installation or active
trial**, create two new private folders. These commands refuse to
overwrite existing payloads; they do not flash partitions or replace
`/usr/local/bin/techo5`. Confirm the official recovery route before
doing any remote write.

```sh
# Stop if any destination or experimental marker already exists.
ssh "$ECHO" 'set -eu
  test ! -e /data/techo5-linux/amazon-arm32
  test ! -e /data/techo5-linux/frankenasp-trial
  test ! -e /data/techo5-linux/fireos-asp.enabled
  test ! -e /run/techo5/frankenasp-armed
  test ! -e /run/techo5/hold
  mkdir -m 700 /data/techo5-linux/amazon-arm32
  mkdir -m 700 /data/techo5-linux/frankenasp-trial'

# Add a private SHA ledger. It includes system files and the self-built
# worker, not anyone's microphone recordings, factory coefficients or IDME.
( cd "$STAGE" &&
  find system -type f -print0 | sort -z | xargs -0 sha256sum &&
  sha256sum libasp_stream_worker.so ) > "$STAGE/SHA256SUMS"

# Transfer only your original system runtime and your OWN worker.
# Keep the host-side pipeline's failure reporting enabled.
set -o pipefail
tar -C "$STAGE" -cf - system libasp_stream_worker.so SHA256SUMS |
  ssh "$ECHO" 'tar -C /data/techo5-linux/amazon-arm32 -xf -'

ssh "$ECHO" 'cd /data/techo5-linux/amazon-arm32 &&
             sha256sum -c SHA256SUMS >/dev/null && echo RUNTIME_MATCHES'
```

Stage the **independently built AArch64** TECHO5 executable in the
separate trial directory. This is a storage operation only.

```sh
mkdir -m 700 -p "$STAGE/trial"
cp ./techo5-experimental "$STAGE/trial/techo5-experimental"
cp tools/frankenasp/trial.sh "$STAGE/trial/trial.sh"
# Optional persistence scripts are copied but remain COMPLETELY INACTIVE.
cp tools/frankenasp/persist.sh tools/frankenasp/persistent-run.sh \
   tools/frankenasp/persist-watch.sh "$STAGE/trial/"
chmod 700 "$STAGE/trial/"*
( cd "$STAGE/trial" &&
  sha256sum techo5-experimental trial.sh persist.sh persistent-run.sh \
    persist-watch.sh > SHA256SUMS )
tar -C "$STAGE/trial" -cf - techo5-experimental trial.sh \
    persist.sh persistent-run.sh persist-watch.sh SHA256SUMS |
  ssh "$ECHO" 'tar -C /data/techo5-linux/frankenasp-trial -xf -'
ssh "$ECHO" 'cd /data/techo5-linux/frankenasp-trial &&
             sha256sum -c SHA256SUMS >/dev/null && echo TRIAL_FILES_MATCH'

# Explicit owner-only ownership for manually transferred tar files:
ssh "$ECHO" 'chown -R root:root /data/techo5-linux/amazon-arm32 /data/techo5-linux/frankenasp-trial'

# This must print INACTIVE. Do NOT create any marker:
ssh "$ECHO" 'test ! -e /data/techo5-linux/fireos-asp.enabled &&
             test ! -e /run/techo5/frankenasp-armed && echo INACTIVE'
```

The installer performs those same actions with **an additional temporary
upload directory, a second checksum pass, and rename-after-validation**.
The simplified manual method above is intentionally less atomic. If a
transfer fails, you must investigate the partially created owner-private
directory yourself, and must not start a trial until validation succeeds.

Running `trial.sh start` is a **separate, time-limited, deliberately
authorized measurement experiment**, and is **not part of either installation
method**. No acoustic experiments are performed in this staging phase;
see the [comparative test protocol](testing.md) for the distinction
between completed wake-word metrics and planned subjective/STT studies.

## C. Optional persistence across ordinary reboots (advanced owners)

**NOT enabled by the installer.** Enable only after you have independently
qualified this version of the factory voice-input chain and have a working
recovery path. A **dated guarded persistence/rollback trial** was conducted on the research Echo; the original launcher was restored afterward. This installation guide does not authorize unattended persistence and does not imply that a separated FrankenASP build has been requalified on hardware.

The regular `trial.sh` mechanism is deliberately temporary. A new,
separately authorized launcher hook lets the owner opt into **persisting
FrankenASP across ordinary reboots of the current TECHO5 A/B slot**.
It modifies **one shell launcher in that slot's TECHO5 filesystem**,
not the original Amazon `/vendor`, boot kernel, official TECHO5 executable
or a factory firmware image. This is an actual write to the TECHO5
**system-slot store**, so it is intentionally separate from the safe
read-only install/preflight stages.

### Version is now explicit

Without `-ldflags`, Go builds were reported by TECHO5 as
`v0.0.0-dev (unknown, unknown)`. The build helper now stamps three independent
identities: **TECHO5 baseline**, **FrankenASP toolkit version/source revision**
and **TECHO5 adapter revision**, for example
`v1.6.0_frankenasp-1.0.0-dev.1.f0123456789.aabcdef0123`.
The complete source SHAs are also embedded in `layout.GitCommit` and reported
by the daemon's version command. A build from a FrankenASP commit after the
release tag gets `.nextN`; either dirty checkout gets its own content digest.
The **TECHO5 base version remains a deliberately supplied, owner-checked
compatibility claim**, not a Git ancestry check performed by this script.
Do **not** stamp a fake, newer TECHO5 version to suppress updates.
Home Assistant's version comparison ignores everything after `_`, so the next
official TECHO5 release may still be offered. Persistent FrankenASP operation
continues to be protected by its independent update guard.

For persistent operation, **rebuild with the current experimental
source** including `frankenasp_guard.go`, which refuses official
rootfs installation while this mode is active or requested. The
earlier `v0.0.0-dev` binary must **not** be used for persistence.

### Three explicit actions

After `install.py --install` has staged your correctly versioned
experimental daemon and all files have passed their SHA-256 checks:

```sh
ECHO=root@YOUR_ECHO_IP
P=/data/techo5-linux/frankenasp-trial/persist.sh

# 1. Inspect the running settled slot and existing state (read only).
ssh "$ECHO" "sh $P status"

# 2. Patch ONLY the current good TECHO5 slot's launcher.
#    The original is kept beside it as techo5-run.frankenasp.stock.
#    This changes NO running service and doesn't activate factory ASP.
ssh "$ECHO" "sh $P install-hook"

# 3. Separately request persistence (a file under /data).
ssh "$ECHO" "sh $P enable"

# Reboot the Echo manually when ready; no automated reboot is issued.
```

The hook runs after TECHO5's normal device/network preparation. Before
launching the experimental daemon, it checks the owner's runtime and
experimental daemon against their private SHA-256 manifests, verifies
the exact tested stock `libasp.so` identity, rejects a `v0.0.0-dev`
build, and checks that no temporary trial or binary bind mount is active.
Only then does it create the transient `/run/techo5/frankenasp-armed`
marker and start the experimental daemon from `/data`.

**Fail-safe behavior:**

- **Missing/altered payload, library version mismatch, unsupported
  version:** the stock TECHO5 daemon starts instead.
- **Experimental daemon exits/crashes:** the stock launcher starts on
  the next init respawn; FrankenASP is attempted **at most once per boot**.
  Future persistence is disabled if this early failure is observed.
- **Unexpected reboot while first startup is unconfirmed:** a private
  `startup.pending` marker survives. The next boot refuses to run
  FrankenASP and clears the persistent opt-in; this avoids a repeated
  kernel-reboot loop. A lightweight verifier clears the pending marker
  only after **120 seconds** with a real native factory worker mapped.
  This probation check is a safety mechanism, **not** the deferred
  long-duration acoustic/AFE stability qualification.
- **Different A/B slot on boot:** only a slot carrying the opt-in hook
  can start FrankenASP. An ordinary upstream rootfs has no hook and
  boots stock TECHO5 even if owner-private files remain on `/data`.

The stock daemon remains at `/usr/local/bin/techo5`. There is no
persistent bind mount over the official binary.

### Disable, then update normally

```sh
# Disable persistence without stopping playback or crashing a daemon.
ssh "$ECHO" "sh $P disable"
# Then REBOOT once into the ordinary stock daemon.
# You may then use Update from Home Assistant/TECHO5 normally.

# Optional cleanup of the current slot's launcher hook, after reboot:
ssh "$ECHO" "sh $P uninstall-hook"
```

The experimental `echod` refuses a manual normal TECHO5 update (a
click on **Install now**) if either the persistent opt-in or the
boot-scoped active marker exists. Its overnight automatic-update loop
**skips** the attempt while persistence is enabled, rather than
repeatedly reporting an installation failure. The user
gets a message explaining to run `persist.sh disable`, reboot, and
retry the official update. **This block is specific to the FrankenASP
experimental fork.** It does not modify upstream releases or Home
Assistant itself.

A stock TECHO5 update on Athena downloads a **whole A/B rootfs** into
the other slot and reboots there. It will **not** bring FrankenASP along
automatically, and it does not delete the owner's factory runtime from
`/data`. An upgrade performed by a separate recovery tool or `slotctl`
bypasses the experimental daemon's update guard; in that case the
new unpatched slot boots **stock**, not FrankenASP. If a broken upgrade
later rolls back to a previously patched slot and the owner has
left persistence enabled, its hook can run again; use `disable` first
for a deliberate transition.

**Do not enable persistence on the currently staged legacy research
binary** (which reports `v0.0.0-dev`). Rebuild, restage its experimental
daemon, regenerate its owner-private SHA-256 manifest, and only then
use the opt-in steps. The installer itself refuses to overwrite an
existing runtime; a manual migration must be reviewed separately.

## Troubleshooting and limits

- **No `p21-system.img`:** the installer will not search your disk.
  Supply the right pre-TECHO5 partition-backup directory.
- **Backup was created after TECHO5 installation:** its system build
  identity will fail verification. Never use a random Android 9 system
  or an unrelated Echo system image as a replacement.
- **Different Amazon build or ASP hash:** hard refusal. Investigate
  dependency/ABI compatibility first; do not bypass by renaming files.
- **Existing `amazon-arm32` or `frankenasp-trial`:** hard refusal.
  Inspect existing owner data; the installer does not delete or replace
  it. This also avoids damaging a previously prepared trial environment.
- **`patchelf` or Android NDK missing:** install host prerequisites
  or provide a proven self-built worker.
- **SSH/TAR error:** no partition is written and official TECHO5 remains
  untouched. An owner-private `.frankenasp-incoming-...` directory may
  remain under `/data/techo5-linux`; inspect and clean only the exact
  failed incoming path when you know no trial is active.
- **A complete file set is not proof of functional compatibility.**
  This work covers one factory revision only. Native loader namespace,
  dynamic loading, ARM32 process startup and actual DSP quality require
  separate qualification; long-duration tests are not authorized now.

See [verified partition dependencies](partition-dependencies-20261023.md),
[factory-vs-TECHO5 voice capture manifesto](README.md) and
[pre-acoustic-test preparation](stage3-preparation-20261023.md).
