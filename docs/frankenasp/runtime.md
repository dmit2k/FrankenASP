# Owner-local ARM32/Bionic runtime preparation

**Purpose:** this private runtime is only a technical prerequisite for
**independent objective and subjective comparisons** of the factory and
open TECHO5 speech-input paths. It is not a proposed permanent replacement
for the TECHO5 voice frontend or a redistributable Amazon runtime. See the
[research mission](README.md) and [comparison protocol](testing.md).

**Do not commit or redistribute a factory payload.** Obtain legally
appropriate FireOS `system` and `vendor` partition images from your
own Athena, and retain backup integrity evidence. The scripts only
read images and create files within the explicitly provided output
directory; they do not download binaries or touch the running Echo.

Requirements: Python 3, `debugfs`, `readelf` and (to build the worker)
the official Android NDK including the ARMv7 API 28 compiler.

~~~sh
cd tools/frankenasp
python3 extract_runtime.py   --system-image /path/to/your/p21-system.img   --vendor-image /path/to/your/p12-vendor.img   --output vendor-local/runtime
python3 extract_configs.py   --vendor-image /path/to/your/p12-vendor.img   --output vendor-local/runtime
export ANDROID_NDK_HOME=/path/to/android-ndk
./build_worker.sh
python3 -m unittest discover -s tests -v
~~~

`extract_runtime.py` walks a heuristic ELF dependency closure from
`/vendor/lib/libasp.so` and reports unresolved sonames. It is NOT a substitute
for verifying Android linker namespaces, symbol versions and ABI.
Vendor, VNDK and Bionic components must correspond to the factory build.
The output contains licensed proprietary material and is gitignored.

**Device staging is now documented separately** in
[automatic and manual setup](installation.md). The new `install.py`
requires an explicit `--backup-partitions DIR` containing the owner's
original `p21-system.img`, validates the known Athena firmware and
preserved read-only `/vendor`, extracts **only** the factory `system`
dependencies and stages a private ARM32/Bionic runtime plus self-built
experimental TECHO5 daemon under `/data`. It requires `--install` for
any device write and refuses to replace an existing runtime/trial.
It **does not enable native ASP, run a test or change the official daemon**.
The installation flow has completed dry-run checks on the researched unit
and full 47-file original image extraction, but has **not** been
qualified as a clean full-device install on a second unit. **The later
October 23 controlled wake-word benchmark is documented separately**;
that does not establish a second-device installation, post-wake speech
quality or long-duration reliability.

The opt-in marker records *intent*, not confirmed execution. The read-only
`status.sh` checks native ASP and worker shared objects in process maps,
but it does not yet certify real-time processing health.


## Time-limited guarded live trial (operator-only)

The optional `tools/frankenasp/trial.sh` is intended for an **Athena owner's
lab**, after the experimental AArch64 daemon and owner-local Bionic runtime
have been independently reviewed. It does not persistently replace the official
daemon or alter the A/B slot. It bind-mounts a separate executable only during
a strictly time-limited session and uses a separate `nohup` watchdog to restore
the original path at timeout or when the native worker disappears or its process identity changes.

**Preconditions:** The normal TECHO5 binary must be running; the experimental
binary must already be staged as
`/data/techo5-linux/frankenasp-trial/techo5-experimental`;
`/data/techo5-linux/amazon-arm32/` must contain the owner-local ARM32 worker,
Bionic runtime and `sh-native`. There must be no other hold, bind mount or
factory-mode marker.

Commands on the **device**, after manual review:

~~~sh
sh /data/techo5-linux/frankenasp-trial/trial.sh status
sh /data/techo5-linux/frankenasp-trial/trial.sh start 90
sh /data/techo5-linux/frankenasp-trial/trial.sh rollback
~~~

The mode needs **both** persistent `fireos-asp.enabled` and temporary
`/run/techo5/frankenasp-armed`. `/run` disappears on reboot: a power loss
must not leave FrankenASP activated. Trial control does not change volume,
the user's stereo preference, or cause test audio playback. Automatic
time-out and unexpected worker disappearance call rollback; log in
`/data/techo5-linux/frankenasp-trial/trial-events.log`. Inspect its status,
the original daemon's health and playback/capture before extending any test.
The trial is *not* a supported unattended permanent installation.

## Optional persistent mode (separate from the temporary trial)

See [the installer and persistence guide](installation.md#c-optional-persistence-across-ordinary-reboots-advanced-owners).
It provides a version-stamped experimental daemon, a separately authorized
launcher hook **only in the current settled Athena rootfs slot**,
a private owner opt-in flag, per-boot checks of staged ELF/runtime hashes,
120-second startup probation, and a one-attempt-per-boot fallback to the
original daemon. The official binary is **never overwritten** by this hook.

**Upstream TECHO5 rootfs updates are blocked while the opt-in or boot-scoped
FrankenASP active flag exists**. Disable and reboot to stock before using the
TECHO5 or Home Assistant update button. Updating by `slotctl` outside the
experimental daemon bypasses this guard: the new, unpatched slot boots stock
and does not automatically reenable FrankenASP. This is a deliberate safety
boundary, not cross-release persistence. The experimental hook is opt-in. A **historical controlled persistence and rollback trial** was performed on the research Echo and its original launcher was restored afterward; this is **not** evidence of permanent activation or long-term stability. See the [dated trial record](persistence-trial-20261023.md).
