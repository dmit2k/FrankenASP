# F2-A: FD4 asset closure, OFFLINE ONLY

This is a separate C11 Linux preflight library and a synthetic native launcher.
It does not call the factory adapter, change ASP2 wire data, load a vendor file,
execute a Bionic loader, mount anything, create a namespace or chroot. Factory
admission remains disabled. No change to the legacy path-based secure_open.

## Trust and API

The S1-B host owns verification and pinning of the executable (FD3) and root
(FD4). `ac_open(4, &closure)` borrows a caller-owned validated root descriptor;
the caller must exclusively own it until the call returns. The library checks
its opened duplicate again. No pathname root, cwd, environment owner override,
visible root lookup, absolute asset path or host-library fallback exists.

Production-owner API accepts UID 0 only. All directories and files reject
any group/other write and setuid/setgid/sticky bits. Directories require owner
search; files require owner read, regular inode and exactly one hard link.
Readable 0600 data and 0700 directories are the fixture defaults; the policy
also admits stronger read/execute permissions without group/other write.

Every directory is opened component by component from its retained parent via
openat(O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC). Files use O_NOFOLLOW|O_CLOEXEC|
O_NONBLOCK and fstat before any read, so FIFOs cannot block preflight. A fixed
allowlist is stricter than arbitrary relative path normalization: only exact
lowercase paths can open. No empty, absolute, dot/dotdot, repeated/trailing
slash, whitespace, NUL, uppercase/case alias or unknown path is accepted from
the length-delimited manifest. Internal `openat(dirfd, ".", ...)` creates an
independent enumeration description, never a path supplied by an asset.

All source file descriptors, root and directories remain pinned until close.
Read bounds are profile 256 bytes, manifest 4096, each other file 1 MiB, total
4 MiB, at most 8 files (this profile uses 6 required and 1 optional); path max
159 bytes and component max80. Positive file sizes are required. SHA256 is the
existing independent byte algorithm, separated from legacy pathname I/O.

The opaque closure also retains **sealed memfd snapshots** of metadata and
all assets. Copy source bytes with pread, compare pre/post fstat
(dev/ino/size/owner/group/mode/nlink/mtime/ctime), hash, then seal against
write/grow/shrink and further seal changes. A manifested file is accepted only
if its snapshot SHA matches the pinned manifest. Consumers receive copies of
snapshot bytes through `ac_read`; public indices are contiguous in sorted path
order, 0..ac_count-1. `ac_identity` records the original source dev/ino/size/hash.
It does not expose mutable source or snapshot descriptors. No output object
escapes on any failure. `ac_close(&closure)` is idempotent; the borrowed FD4 is
never closed or repositioned. Failed read results must be discarded by caller.
All held descriptors are CLOEXEC; test hook and snapshot-FD accessors exist
only under AC_TESTING and are absent from the root-owner binary.

Rename of the visible root cannot affect its FD4. In-flight descendant changes
may yield original verified bytes or terminal rejection; final directory scans
compare remaining visible entries against pinned identities and reject typed
unexpected entries under etc/lib, unmanifested optional files, symlinks and
inode replacement. A later mutation of an original inode cannot change a sealed
snapshot. This is a frozen **verified file set**, not a filesystem transaction
against an actively malicious root writer. The pinned manifest inside the
already trusted root is the hash authority. A root writer can replace both the
manifest and assets before preflight; hashes do not authenticate untrusted roots.

## Narrow deterministic offline profile

`etc/profile.conf` must equal these bytes, including final LF:

```
ASP2-FD4-OFFLINE-V1
platform=athena
backend=synthetic
factory_admission=disabled
manifest=etc/assets.sha256
```

`etc/assets.sha256` is nonempty, ASCII, sorted unique exact relative paths.
Each line is 64 lowercase hex characters, two spaces, path and LF. No comments,
blank lines, CR, duplicate/order ambiguity or unrecognized entries. The manifest
itself is pinned/sealed but excluded from its own hash list. Required files:

- etc/profile.conf
- lib/rootfs/opt/external-asp/offline-child.elf
- lib/rootfs/system/bin/linker
- lib/rootfs/system/lib/libfixture-base.so
- lib/rootfs/vendor/etc/fixture.conf
- lib/rootfs/vendor/lib/libfixture-top.so

Only `lib/rootfs/vendor/etc/optional.conf` is optional, and it must be manifested
if present. `etc`, `lib`, `lib/rootfs`, system/{bin,lib}, vendor/{etc,lib} and
opt/external-asp must all be real checked directories. Asset closure scans all
of etc/lib; other root entries, including host-owned bin/external-asp, are
outside its scope and confer no authority. Extension to real file lists/profile
formats requires a later explicitly reviewed policy; this cannot qualify a
production bundle.

## ELF closure and limits

A bounded memcpy-based parser inspects snapshots, never dlopen/ldd. Its narrow
supported format is ELF64, little endian, x86_64, ET_DYN/ET_EXEC, at most 32
program headers, 256 dynamic entries and 8 DT_NEEDED entries per file. It bounds
all file offsets/ranges, maps DT_STRTAB only through a unique file-backed
PT_LOAD, validates NUL-terminated needed names and rejects duplicates, slashes,
RPATH/RUNPATH, audit/depaudit/filter/auxiliary redirection. The only admitted
PT_INTERP is the child's `/system/bin/linker`; other ELF files cannot carry an
interpreter. Each declared needed name must identify exactly one allowlisted,
hash-pinned system/lib or vendor/lib file. Every library and loader placeholder
is parsed as well, covering transitive/cyclic declared edges without recursion.
This inspects dependency metadata, not symbol/relocation/version correctness or
all Linux loader semantics; it is not a general ELF loader validator.

The tests build original tiny -nostdlib Linux objects:
child -> vendor/lib/libfixture-top.so -> system/lib/libfixture-base.so.
The system/bin/linker is a self-built **ELF placeholder, not a working loader**.
No trainer libc is copied. A separately built native libc-linked child is
rejected even when its manifest hash is correct. Missing dependency, malformed
ELF, interpreter drift and out-of-range offsets reject. Executing the synthetic
child directly on trainer returns ENOENT for its missing host interpreter;
this intentional failure is not Bionic execution. The real preflight ELF is
executed as a read-only consumer in native tests with inherited FD4; its own
Linux interpreter/libc are trainer dependencies and are not qualified by this
closure.

**F2-B prerequisite:** a future runtime that opens paths must consume the
verified snapshot FDs, or construct a reproducible immutable sealed staging
from them and pin that staging. Reopening original paths (even after a passing
manifest) reintroduces TOCTOU. The original source/rootfs directory descriptors
alone are not an immutable mount source. Mount isolation, private namespace,
RO binds, chroot, ARM32/Bionic runtime, real private assets and loader ABI all
remain unqualified. F2-A creates none of those mechanisms.

## Reproduction

```
OUT_DIR=/absolute/private/build bash tools/external-asp/tests/run_assets.sh
```

Strict C11 -Wall -Wextra -Werror -pedantic, GCC -fanalyzer, native and ASan/UBSan.
Python fixture launcher passes a real already opened root through FD4, with
compile-time expected-owner injection for unprivileged fixtures. The production
root-owner binary is separately built and rejects them. Test-only syscall
wrappers simulate UID mismatch at every directory/file fstat, read/write errors,
short/EINTR, and exhausted memfd resources; no chown/root is used. Tests cover
all component symlinks/types/modes, manifest/profile/path limits, hashes,
hardlinks/FIFOs/unexpected entries, pre/post-open swaps, actual original inode
identity, concurrent library swaps, sealed consumption after in-place mutation,
and repeated success/error teardown with exact FD counts and stable cwd.
