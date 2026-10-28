# ASP2 selective installer (I2-S; OFFLINE qualification)

Prepare never activates TECHO5. The exact deployment remains
/data/techo5-linux/external-asp/{bin,etc,lib}, with one lib/rootfs.
FD3 pins the launcher, FD4 the deployment directory. Factory Calibrator alone
applies gain; Q30 remains metadata. CFG2/TLV, explicit MIC4/REF2 routing,
500ms HELLO and 25ms PCM budgets are unchanged.
I1 QEMU HELLO 6.49–8.52s and PCM >25ms FAIL emulated deadlines. Native Echo
latency, compiled launcher, real helper cleanup and device installation remain
UNQUALIFIED and require separate DEVICE GO.

## User-selected sources

The user chooses and trusts the input. No manufacturer signature, source-origin
attestation, official URL, full OTA/image SHA256, SHA256SUMS ledger, timestamp,
libasp hash inventory or exact firmware fingerprint is required.
--source-authority is an optional legacy diagnostic; provenance fields are ignored.
Its optional SYNTHETIC_FIXTURE scope restricts synthetic payloads to local tests;
--fixture provides that restriction without a receipt.
A downloaded file is not authenticated; source trust is the user's choice.

Required runtime files must exist and parse: ARM32 little-endian EABI5 Bionic
loader/DSOs, child PT_INTERP=/system/bin/linker, all flat audio-algorithms files
including asp.cfg/AFE.cfg and a resolving DT_NEEDED closure. Invalid preferred
libraries fail without falling back. Build properties are informational copies.
These checks do not prove DSP semantics, symbol versions, acoustics or timing.

A: --mode LIVE_VENDOR_MATCHED --backup-dir EXACT_DIRECTORY

Read exactly p21-system.img and p12-vendor.img inside that directory. TECHO5
backups/SERIAL/partitions and research preunlock-7080 use the SAME raw format.
No serial search, parent traversal, latest selection, format guessing, ledger,
image hashing or unrelated partition access. Bad/store images fail on format
or missing runtime files, without speculative origin errors.
Advanced --system-image FILE --vendor-reference FILE_OR_DIRECTORY remains;
it cannot be mixed with --backup-dir. System image contains /system; vendor
image is rooted at /. Mode A reads vendor only for offline closure preparation,
persists ZERO vendor files and later uses live original read-only /vendor.
Install/dry-run revalidate actual required live vendor files/dependencies and,
in production, require exactly /vendor already RO. No partition fingerprint gate.

B: --mode OTA_VENDOR_BUNDLED_MATCHED with ONE of --ota FILE or
--ota-url HTTP(S)://HOST/update.bin. Both components come from that ONE archive;
separate images/backup-dir or a live-vendor fallback are refused.
A local path never triggers a network request.

| Supported ZIP encoding (.bin names are fine) | Contents |
| --- | --- |
| ZIP_FULL_BLOCK_BROTLI_V4 | system/vendor.transfer.list v4 + .new.dat.br; complete new/zero/erase coverage, zero stash, empty/absent patch |
| ZIP_RAW_EXT4_IMAGES | system.img and vendor.img, raw ext4 |
| ZIP_FULL_FILE_TREE | regular system/... and vendor/... files |

Android metadata identifies encoding via ota-type=BLOCK/FILE.
Unsupported: incremental/pre-build/base-dependent transfers, move/stash/patch,
range gaps/overlap, nonempty patch.dat, other transfer versions, plain new.dat,
payload.bin, Android sparse/EROFS/dynamic images and non-ZIP wrappers.
Recovery scripts are never executed. ZIP names/types/duplicates/encryption,
sizes and CRCs of consumed members are checked.

## Selective storage / portable reader

Full Brotli prepare NEVER creates complete system/vendor images, including sparse
ones. Python parses requested ext4 superblocks/group descriptors, inodes,
directories/extents and selected data. Independent requests batch missing blocks
into sequential Brotli passes; compressed streams are never randomly sought.
Each pass checks complete stream/ZIP CRC and exact decompressed length, retaining
only requested blocks in memory. No debugfs, root or kernel mount is needed.

Bounds: 4GiB logical image per partition; 96MiB cache and 64 passes per partition;
600s per pass; 64MiB per file; 128MiB batch/closure; 256 ELF closure nodes;
512 config files; bounded extent depth/directory counts.
Common extent-based ext4, FILETYPE, 64BIT/FLEX_BG and standard read-only metadata
features work. Recovery-required, meta_bg, compression, encryption, inline data,
casefold, bigalloc, indexed directories and non-extent inodes fail clearly. This is not fsck/repair;
ext4 metadata checksums are not independently verified.
Raw backups use only requested random reads. Raw ZIP-image encoding additionally
streams each embedded member once to check its ZIP CRC (no SHA or image output),
then uses Python ZIP seeks for requested reads; this can be slow. Brotli and
file-tree members check CRC during their complete streaming/file reads.

Original local 7080: 83 factory files, 37 configs, 294 dependency edges match
accepted I2 exactly; about 13.3MB payload, 65MiB peak RSS, 28 system/15 vendor
passes and 5m08s on anfisa-trainer. All three original 7080/7081/7082 comparisons
and final metrics are in the private I2-S result. These do not predict Echo speed.
Local OTA adds no copied archive. HTTP(S) temporarily stores ONE complete
download until prepare finishes; it adds no second archive or partition images.
Low free space (<128MiB) emits a conservative preparation warning. Download
reserves 64MiB; install needs payload +16MiB. Rollback generations also use space.
Nothing uses /store by default.

## HTTP(S)

Plain HTTP and ANY HTTPS certificate are accepted by default, including private,
self-signed, expired/untrusted and hostname mismatches. No --insecure or CA setup.
Python standard-library streaming; no shell, automatic packages or external tools.
Limits: 5 HTTP(S)-only redirects, default 2GiB, 30s socket timeout, 1800s total
deadline (a blocked read can add one socket timeout). Optional bounds:
--download-max-bytes, --download-timeout, --download-total-timeout.
Checks cover status, body encoding, length/truncation and free space.
A fsynced .partial file is atomically renamed only when complete. Errors/SIGINT
clean the new source/stage; SIGKILL/power loss can leave a private diagnostic
directory. URL credentials never enter diagnostics/receipts and earlier credentials
are not forwarded on redirects. URL fragments are ignored. Environment HTTP proxies are not used.
ONLY explicit --expected-sha256 HEX hashes the chosen OTA. Absence never hashes
it. Backup images are never hashed.

## Preparation examples / platforms

Python3.9+; existing Python brotli >=1.2 bounded-output API only for block OTAs.
Optional build uses the unchanged native Linux ARM32 launcher and separate ARM32
Bionic build scripts and existing toolchains:
~~~sh
python3 -B tools/external-asp/asp2_installer.py build --config /private/build-config.json --output /private/new-build
~~~
Build config keys: ARM32_CC, ARM32_SYSROOT, ARM32_BINUTILS, BIONIC_CC,
BIONIC_LD, BIONIC_ROOT, optional LD_LIBRARY_PATH. No factory ELF patching.

Always supply an explicit channel-map:
~~~text
ASP2-CHANNEL-MAP-V1
mic=0,1,2,3
ref=0,1
~~~
The separate mapping receipt records the owner's approved captured-slot choice,
not source origin. A source fingerprint is not required:
~~~json
{"schema":"ASP2-MAPPING-AUTHORITY-V1","scope":"OWNER_CONFIRMED","authority":"Owner approves TECHO5 ALSA captured order","channel_map_sha256":"SHA256_OF_SMALL_CHANNEL_MAP","captured_slot_idme_association":"OWNER_APPROVED_ALSA_ORDER"}
~~~
OWNER_APPROVED_ALSA_ORDER permits identity only. Nonidentity needs CONFIRMED.
Physical/acoustic qualification stays separate. --allow-unqualified-map creates
a NONINSTALLABLE research preview without launcher.profile.

Linux/macOS examples (outputs must be new):
~~~sh
python3 -B tools/external-asp/asp2_installer.py inspect --mode LIVE_VENDOR_MATCHED --backup-dir /private/backups/SERIAL/partitions
python3 -B tools/external-asp/asp2_installer.py prepare --mode LIVE_VENDOR_MATCHED --backup-dir /private/preunlock-7080 --launcher /private/launcher --child /private/asp2-child --channel-map /private/channel-map --mapping-authority /private/mapping.json --output /private/new-A
python3 -B tools/external-asp/asp2_installer.py prepare --mode OTA_VENDOR_BUNDLED_MATCHED --ota /private/update.bin --launcher /private/launcher --child /private/asp2-child --channel-map /private/channel-map --mapping-authority /private/mapping.json --output /private/new-B
python3 -B tools/external-asp/asp2_installer.py prepare --mode OTA_VENDOR_BUNDLED_MATCHED --ota-url https://owner-server.local/update.bin --launcher /private/launcher --child /private/asp2-child --channel-map /private/channel-map --mapping-authority /private/mapping.json --output /private/new-HTTPS
# Only if the user explicitly wants a comparison:
python3 -B tools/external-asp/asp2_installer.py inspect --mode OTA_VENDOR_BUNDLED_MATCHED --ota /private/update.bin --expected-sha256 USER_SUPPLIED_64_HEX
~~~
PowerShell (self-signed HTTPS needs no special flag):
~~~powershell
py -3 tools/external-asp/asp2_installer.py inspect --mode LIVE_VENDOR_MATCHED --backup-dir 'C:\Backups\SERIAL\partitions'
py -3 tools/external-asp/asp2_installer.py prepare --mode OTA_VENDOR_BUNDLED_MATCHED --ota-url 'https://owner-server.local/update.bin' --launcher 'C:\ASP\launcher' --child 'C:\ASP\asp2-child' --channel-map 'C:\ASP\channel-map' --mapping-authority 'C:\ASP\mapping.json' --output 'C:\ASP\new-payload'
~~~
Actually tested: Linux x86-64/Python3.12. Windows/macOS preparation is implemented
with portable APIs but NOT tested. Windows needs symlink permission (e.g.
Developer Mode); directory fsync/POSIX modes are unavailable there. Transferred
payloads must preserve/restore documented symlinks/private POSIX modes; Linux
deployment rechecks them. Echo Python/Brotli/storage/durability remains unqualified.
Deployment/helpers require Linux /proc, root at the production path, renameat2.
No claim of Windows/macOS device installation.

## Transactions with stock TECHO5 running

There is NO global TECHO5 comm/name ban. Ordinary stock TECHO5 can remain running
during inspect/prepare/dry-run/install/status/uninstall of inactive external-asp.
Actual executable/cwd/chroot/FD/mmap references, covering/private runtime mounts
and PID/namespace races block mutation; unreadable production state fails closed.
Status reports activity/blockers read-only.
~~~sh
python3 -B asp2_installer.py dry-run --payload /private/new-A --live-vendor /vendor
python3 -B asp2_installer.py install --payload /private/new-A --live-vendor /vendor --opt-in --confirm-inactive
python3 -B asp2_installer.py status
python3 -B asp2_installer.py rollback --generation EXACT_OLD_UUID --live-vendor /vendor --opt-in --confirm-inactive
python3 -B asp2_installer.py uninstall --generation EXACT_UUID --opt-in --confirm-inactive
~~~
B needs no --live-vendor. No service/boot/firmware/parent-permission changes.
A nonblocking lock and original UUID/dev/inode/uid/aggregate footprint registry
retain exact generation ownership (not source provenance/per-file factory hashes).
New immutable generations publish with renameat2 NOREPLACE/EXCHANGE. Previous
generations remain for rollback. Interrupted copy/publication/removal is
identifiable/resumable. Unknown content/unsafe ownership or pinned generations
cannot be deleted/exchanged. Local tests use --local-root /tmp/PRIVATE_0700
--destination /tmp/PRIVATE_0700/external-asp. No automatic activation.

## Explicit helper stop / private cleanup

~~~sh
python3 -B asp2_installer.py helpers status
python3 -B asp2_installer.py helpers status --r1-host /trusted/R1/techo5
python3 -B asp2_installer.py helpers stop --opt-in --maintenance-ack
python3 -B asp2_installer.py helpers stop --opt-in --maintenance-ack --force-kill --force-unmount
python3 -B asp2_installer.py install --payload /private/new-B --opt-in --confirm-inactive --stop-helpers --maintenance-ack --force-kill --force-unmount
~~~
First select Built-in via existing owner TECHO5 UI and prevent new external
requests/restarts. --maintenance-ack acknowledges that maintenance condition.
No authenticated local selector interface/credentials are available to this
installer; it invents no API. R1 itself does not auto-restart failed instances;
other controllers/user requests can. Respawns BLOCK completion, never a kill loop.
Stock audio service and host processes are NEVER terminated.

Read-only plan lists PID/starttime, executable inode/path, provenance, namespace,
mounts and blockers. Kill authority: verified launcher/child executable inode
inside registered current/previous installer generations, including orphan child;
or explicit trusted --r1-host inode plus verified parent, both IPC pipes,
executable and FD3==exe/FD4==secure asset root. After CLOEXEC, a Bionic child
outside current generation can qualify via the same trusted parent/IPC proof,
exact child/root inode, private namespace and exact launcher profile. Protocol
output may be a duplicated FD3+ after I1 redirects stdout to diagnostic stderr;
it must still be a distinct pipe jointly owned by the verified host parent.
Unattributable orphans/unrelated external-asp names never grant authority.
Ambiguous related/unreadable state blocks destructive action.
pidfd is preferred; fallback immediately revalidates PID starttime/executable/
parent/root/namespace before signals. No process-group/user-wide kill.
SIGTERM waits 2s; separately requested --force-kill SIGKILLs verified survivors
and waits another 2s. The real host stays sole child reaper; installer verifies
death/zombie and namespace release instead of waitpid on foreign children.

Death normally releases private mounts. --force-unmount pins a verified PRIVATE
namespace before stop and cleans only exact registered rootfs mounts afterward:
rootfs/system/vendor/sys/.realproc/proc (genuine procfs)/dev/data.
A separate bounded subprocess enters THAT namespace and its pinned root mount,
then verifies exact mounts,
unmounts reverse-depth and may use MNT_DETACH only for those SAME owned targets
after normal failure. Parent namespace never changes. Unknown/shared/stacked
mounts, other owners/namespace-FD keepers, foreign roots and permission failures
BLOCK cleanup. An orphan namespace FD with no verifiable living namespace/root
owner blocks mutation and is kept; no mount root is guessed. Unregistered custom R1 roots can be stopped by R1 proof but cannot
have forced mount cleanup without installer ownership.
Never host /vendor,/system,/sys,/proc,/store or arbitrary subtree unmount.
No generation mutation resumes with unresolved pins/mounts or restarted helpers.
Process inspections are bounded (15s/32768 processes, 8192 FDs per process,
8MiB per maps/mountinfo read, 128MiB aggregate snapshot, 256 helper targets).
Signals/setns/unmount tested only with fake /proc and controlled syscall mocks;
actual namespace/kernel/R1 supervision races require later device qualification.
The disposable user/mount namespace capability probe on this trainer failed
with uid_map Operation not permitted, so destructive namespace integration is SKIP.

## Regression

~~~sh
python3 -B tools/external-asp/tests/test_installer.py
python3 -B tools/external-asp/tests/test_block_ota.py
python3 -B tools/external-asp/tests/test_selective.py
python3 -B tools/external-asp/tests/test_download.py
python3 -B tools/external-asp/tests/test_helpers.py
~~~
Original 76 cases retained with updated source-trust expectations; additional
direct backup, portable reader, download, helper/race/cleanup and interrupted
transaction coverage. Fixture generation needs existing mke2fs only for tests.
Network fixtures bind loopback only; self-signed wrong-hostname certificates
use existing openssl. No external OTA download. All three real local originals
compare 83 factory files/37 configs/294 edges plus own launcher/child/map/profile.
Private comparison hashes are diagnostics, never runtime manifests.

## Native device installer and compact transfer

Echo stock has no Python runtime. Keep this Python tool on the computer and
use `pack --payload PREPARED --output FILE.tar.gz`, or add
`--pack-output FILE.tar.gz` to `prepare`. The separate Go ARM32 device CLI,
portable packing details, offline build and future authorized SCP examples are
in [GO_DEVICE_INSTALLER.md](GO_DEVICE_INSTALLER.md). No device action is automatic.
