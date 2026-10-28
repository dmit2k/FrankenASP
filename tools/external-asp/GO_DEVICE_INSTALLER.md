# Native Go device installer — D1-B0

The host Python I2-S tool prepares OTA/backup runtime files. The separate native
Go executable only handles prepared compact TAR bundles and local generations.
It contains no network client, OTA reader, Python runtime, DSP, CFG2 or host code.
Nothing here activates External ASP, stops stock TECHO5 or changes boot/slots.
Device operations require a separate explicit DEVICE GO.

## Build offline

Linux host, existing Go **1.26.9**, cached golang.org/x/sys **v0.48.0**. No fetching:

~~~sh
GO=/private/go1.26.9/bin/go OUT=/private/asp2-artifacts \
  bash tools/external-asp/device-installer/build.sh
~~~

The default GO path identifies the existing trainer toolchain. The script checks
its version, uses GOTOOLCHAIN=local/GOPROXY=off/GOSUMDB=off, GOOS=linux,
GOARCH=arm, GOARM=7, CGO_ENABLED=0 and embeds the exact Git revision plus dirty
state. --version prints that stamp. The output is asp2-install-arm32, separate
from bin/external-asp inside the payload. Keep it outside the deployment tree.
Only one small x/sys dependency is needed, with its normal go.sum checksum.

## Prepare and pack on the computer

Use the existing approved launcher, Bionic child, channel map and mapping JSON.
All source paths below are examples; no source download is necessary.
The mapping receipt is the existing captured-channel choice, not OTA provenance.

Linux/macOS:

~~~sh
python3 -B tools/external-asp/asp2_installer.py prepare \
  --mode OTA_VENDOR_BUNDLED_MATCHED --ota /private/update-kindle-athena-7080.bin \
  --launcher /private/external-asp-launcher-arm32 --child /private/asp2-child \
  --channel-map /private/channel-map --mapping-authority /private/mapping.json \
  --output /private/new-B7080 --pack-output /private/B7080.tar.gz

# Or pack an already prepared directory:
python3 -B tools/external-asp/asp2_installer.py pack \
  --payload /private/new-B7080 --output /private/B7080.tar.gz

# A reads exactly these two image files within the explicit directory:
python3 -B tools/external-asp/asp2_installer.py prepare \
  --mode LIVE_VENDOR_MATCHED --backup-dir /private/preunlock-7080 \
  --launcher /private/external-asp-launcher-arm32 --child /private/asp2-child \
  --channel-map /private/channel-map --mapping-authority /private/mapping.json \
  --output /private/new-A --pack-output /private/A.tar.gz
~~~

PowerShell:

~~~powershell
py -3 tools/external-asp/asp2_installer.py prepare --mode OTA_VENDOR_BUNDLED_MATCHED --ota 'C:\ASP\update-kindle-athena-7080.bin' --launcher 'C:\ASP\external-asp-launcher-arm32' --child 'C:\ASP\asp2-child' --channel-map 'C:\ASP\channel-map' --mapping-authority 'C:\ASP\mapping.json' --output 'C:\ASP\new-B7080' --pack-output 'C:\ASP\B7080.tar.gz'
py -3 tools/external-asp/asp2_installer.py pack --payload 'C:\ASP\new-B7080' --output 'C:\ASP\second-B7080.tar.gz'
~~~

--pack-output permits Windows preparation without live proc/IDME symlinks.
The packer emits the eight exact approved aliases as TAR symlink entries even
when they are absent on the host. A present wrong alias is refused. No extra
manifest or marker is introduced. Windows modes are represented as the known
POSIX payload modes; on POSIX all existing modes are preserved. Packing the
same prepared directory gives identical bytes: sorted USTAR, UID/GID 0, fixed
mtime 0, empty owner names and gzip filename, mtime 0. A fresh prepare creates
a fresh payload UUID/receipt, so independently prepared archives can differ.
Linux tests pass; native Windows/macOS execution remains unqualified.

The archive contains only bin/, etc/, lib/. The original receipt is unchanged.
There is no full OTA, image, second vendor copy for A, source hash database,
mandatory OTA SHA, certificate check, source attestation or qualification flag.
The host remains responsible for its existing full factory dependency closure.

## Transfer examples — ONLY after separate DEVICE GO

These are documentation, not an automatic deployment script. First verify the
same Echo/SSH host key and approved stock SHA/slots. The private maintenance
directory must already exist, be root-owned 0700, and be outside external-asp.

~~~sh
scp /private/asp2-artifacts/asp2-install-arm32 /private/B7080.tar.gz \
  root@ECHO:/data/techo5-linux/asp2-maintenance/
~~~

~~~powershell
scp 'C:\ASP\asp2-install-arm32' 'C:\ASP\B7080.tar.gz' root@ECHO:/data/techo5-linux/asp2-maintenance/
~~~

On Echo, after authorization, chmod the maintenance executable 0500 and bundle
0600. Do not chmod/chown /data or /data/techo5-linux; exact root-owned 0777 stock
parents are accepted. No Python, jq, downloader or bootstrap runs on Echo.

## CLI

All commands return JSON. Refusals print a diagnostic to stderr and exit 2;
success exits 0. Production writes require UID0. Read commands require normal
read/search access to the private deployment and owner registry; inspect does
not access the destination and can run unprivileged.

~~~sh
./asp2-install-arm32 --version
./asp2-install-arm32 inspect --bundle B7080.tar.gz
./asp2-install-arm32 dry-run --bundle B7080.tar.gz
./asp2-install-arm32 install --bundle B7080.tar.gz --opt-in --confirm-inactive
./asp2-install-arm32 status
./asp2-install-arm32 rollback --generation EXACT_UUID --opt-in --confirm-inactive
./asp2-install-arm32 uninstall --generation EXACT_UUID --opt-in --confirm-inactive
~~~

Production destination is fixed at /data/techo5-linux/external-asp.
Only fixture tests can use BOTH --local-root /tmp/PRIVATE_0700 and
--destination /tmp/PRIVATE_0700/external-asp. The local root must already exist,
belong to the current UID, and have mode0700; symlink ancestors are refused.
Local A tests additionally supply --live-vendor /private/extracted-vendor.
Production A always reads the existing /vendor and requires it already RO.
A bundle's vendor directory remains empty; B never falls back to host vendor.

inspect/dry-run decompress into bounded memory and never extract or create
lock/registry/staging files. TAR bounds: 2048 entries, 16MiB/file, 48MiB logical
payload, 52MiB decompressed archive including headers/padding; compressed file
at most48MiB. Paths, duplicate entries, exact aliases, inode kinds, ELF32 ARM
EABI5/interpreters, executable modes, map/profile and small own-artifact hashes
are checked. The prepared dependency paths are checked for presence. Factory
dependency resolution and factory-file authentication are not reimplemented.
Corrupt/truncated gzip is refused even after the final TAR entry.

## Transactions and recovery

The names and JSON schemas are the Python I2-S contract:

- .external-asp-owner.json, schema ASP2-OWNERSHIP-V1, generations indexed by UUID
  with dev/ino/uid identity, aggregate files/directories/symlinks/bytes footprint.
- .external-asp-installer.lock, mode0600, nonblocking flock, no symlink/hardlink.
- .external-asp-generation-UUID, private staged/previous generation directory.
- etc/installer-receipt.json, schema ASP2-INSTALLER-V1; installation_id is added
  only to the staged receipt.

Staging is registered as preparation_incomplete before writing. Files and
directories are fsynced, then the complete footprint is registered before
publication. First publication uses renameat2 RENAME_NOREPLACE; update and
rollback use RENAME_EXCHANGE. Unsupported kernels/filesystems produce an error;
there is no non-atomic overwrite fallback. The parent is fsynced after rename.
Registry replacement is atomic and fsynced. Actual inode identities determine
which UUID is current, including interruption just after exchange.

status identifies previous and incomplete/removal-pending generations, missing
registry identities, and activity blockers. Incomplete stages can be explicitly
uninstalled by their UUID but cannot be rolled back. A fully registered candidate
left before publication can be rolled back. Unknown directories, changed content
or inode identity cause refusal and are kept. A directory created before a
failed first registry save remains unknown and requires owner review; it is
never automatically deleted. A crash after removal but before registry save
leaves a missing registry identity, reported by status; no filesystem object is
guessed or recreated. Registry/lock are retained after removing all generations.

No blanket process-name ban exists. Confirmed executable/cwd/root/FD/mmap and
related mounts block updates, rollback and removal, including unknown users
pinning a generation. Unreadable/unstable production state blocks safely.
Stock TECHO5 continues during first inactive installation. The installer never
starts a launcher, child or TECHO5.

## Explicit helper maintenance

First select Built-in through the existing owner UI and prevent new external
requests. There is no invented selector API. Stop is a separate command:

~~~sh
./asp2-install-arm32 helpers status
./asp2-install-arm32 helpers status --r1-host /trusted/techo5
./asp2-install-arm32 helpers stop --opt-in --maintenance-ack
./asp2-install-arm32 helpers stop --opt-in --maintenance-ack --force-kill
./asp2-install-arm32 helpers stop --opt-in --maintenance-ack --force-kill --force-unmount
~~~

The update commands deliberately do not hide a stop inside install. Force flags
are accepted only on helpers stop. Only registered launcher/Bionic child
executable inodes, or an explicitly selected R1 host parent with pinned helper/
root plus distinct IPC pipes, grant signal authority. Parent identity is checked
again before signalling the latter. Names never grant authority. Stock/parent
hosts and unrelated processes are preserved. pidfd is preferred; old-kernel
fallback immediately rechecks PID starttime, parent, executable, root and mount
namespace. SIGTERM waits2s; only explicit --force-kill permits SIGKILL survivors.
A restarted helper blocks completion; it is not hunted in a loop.

--force-unmount pins only a verified private namespace and its root anchor before
stopping. Exact owned rootfs/system/vendor sources and approved pseudo mounts
are checked; shared/stacked/foreign mounts, foreign owners and namespace FD
keepers block cleanup. A separate invocation locks its thread, unshares CLONE_FS,
enters that namespace and pinned root, rechecks the exact mount table, and
unmounts deepest first. MNT_DETACH is only a fallback on the same approved
target after normal unmount fails. The parent installer namespace never changes.
Host /vendor,/system,/proc,/sys,/store are never cleanup targets.
An unverified orphan namespace FD is kept and blocks mutation. The installer's
own explicitly verified namespace pins are accounted for during cleanup.
Unsupported permissions/kernel context return a real error, not success.

All control flags are implemented and adapter-tested. Actual privileged setns/
unmount and device helper stop remain UNQUALIFIED: the trainer cannot create a
disposable user/mount namespace. Offline tests do not prove native Echo behavior.

## Resource bounds and offline qualification

The accepted B payload is about13.3MB uncompressed, about6.6MB compressed.
A is about5.6MB /2.6MB. dry-run requires one new payload plus16MiB free reserve;
previous generations consume additional space. Bundle, installer and retained
generations coexist. The report records measured allocation, startup/transaction
RSS/time and a conservative double-generation capacity estimate. No /store use.

~~~sh
cd tools/external-asp/device-installer
GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off go test -count=1 ./...
GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off go test -race -count=1 ./...
~~~

Source tests use synthetic payloads and fake /proc/syscall adapters. Private
D1-B0 evidence additionally covers real A/B7080/7081/7082 prepare/pack,
byte/mode/symlink comparison, bidirectional Python transactions, native Linux
renameat2 and ARM32 CLI under existing QEMU. No factory payload enters Git.
Native device runtime, crash durability on Echo, helper namespace cleanup,
launcher/Bionic execution, 500ms/25ms audio exchange and acoustics require
separate authorization and testing.

## Proposed future D1-B trial

After explicit DEVICE GO, recheck official echod SHA
1923ef475b021af8e5fcec85e0484b1e318bd745ae7336e5a6de53633e422a9e,
slots A GOOD v1.6.9/B GOOD v1.6.0, auto_install=false, free space, no external
helpers and original RO /vendor. Copy only the private Go executable and compact
B7080 bundle into the private maintenance directory. Inspect, dry-run, install
INACTIVE, status; if testing retained-generation rollback, install the same bundle
as a second inactive generation, roll back the exact first UUID, inspect status,
then explicitly uninstall both UUIDs. Leave stock TECHO5 running throughout.
No host swap/restart, launcher execution, audio, helper stop or rootfs mount
cleanup is included in that proposed GO. Any such action needs a DIFFERENT GO.

STOP after offline qualification. No Echo connection or device operation follows.
