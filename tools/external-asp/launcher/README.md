# F2-B minimal Athena launcher (offline implementation)

This separate Linux ARM32 target prepares the approved native filesystem shell
and execs an owner-supplied ARM32/Bionic child. It does not implement the factory
DSP backend or ASP2 session admission. R1 main.c and the F1-A/F1-B offline
children are unchanged. Nothing here installs, activates or qualifies a device.

## Build

Use an existing Linux arm-linux-gnueabihf GCC toolchain with Linux libc headers
and static libc; never use Android/Bionic headers for this target:

```sh
OUT_DIR=/absolute/private/build \
  ARM32_CC=arm-linux-gnueabihf-gcc \
  bash tools/external-asp/launcher/build.sh
```

ARM32_SYSROOT optionally names an unpacked Debian/Ubuntu cross-libc sysroot;
ARM32_BINUTILS optionally names its target bin directory containing as and ld.
ARM32_READELF defaults to readelf. No download or package installation occurs.
The build rejects non-ARM32 targets at compile time and inspects the output for
ELF32/LE/ARM with no PT_INTERP or DT_NEEDED. Target is ARMv7-A hard-float,
VFPv3-D16; linked libc can also contain NEON. Exact compiled ELF attributes and
compiler/libc provenance belong in the per-build offline receipt.

## Host and installed-tree contract

The unchanged TECHO5 host executes its verified FD3 and supplies FD4 as the
pinned external-asp deployment directory. Invocation has no arguments or
environment-selected mode. UID0, root ownership, FD3 == /proc/self/exe inode,
static ARM32 ELF and FD4 mode0700 are mandatory. No resolution through the
world-writable /data or /data/techo5-linux ancestors occurs.

The later installer must supply exactly one owner-private tree:

- external-asp/lib/rootfs and external-asp/etc: real directories, UID0, mode0700;
  external-asp/lib is also mode0700.
- etc/launcher.profile: root-owned regular file, no group/other write or special
  bits. It must contain exactly one of the two profiles below, including LF.
- lib/rootfs/system: owner-extracted matching original Bionic/VNDK files;
  system/bin/linker is the original ARM32 ELF with no interpreter.
- lib/rootfs/factory/asp2-child: owner-supplied ARM32 ET_EXEC/ET_DYN executable,
  original PT_INTERP=/system/bin/linker. The descriptor remains pinned to exec.
  Building the real factory CFG2/TLV child is a separate integration stage.
- lib/rootfs/{vendor,sys,.realproc,dev,data,proc}: precreated real mountpoint
  directories. Every opened component is UID0, rejects symlinks, special bits
  and group/other write. Runtime files need not have a per-file SHA manifest.
- lib/rootfs/proc/idme: ordinary real directory. Root-owned symlinks must be:
  self -> /.realproc/self; sys -> /.realproc/sys; cpuinfo -> /.realproc/cpuinfo;
  device-tree -> /sys/firmware/devicetree/base; idme/miccal.N ->
  /proc/device-tree/idme/miccal.N/value for all N=0..3.

The installer must stage atomically and never mutate the active trusted tree
in place. Original /system and /vendor ELF bytes stay unchanged. No copy of
either runtime is created at launch.

LIVE_VENDOR_MATCHED profile:

```text
F2B_LAUNCHER_V1
platform=athena
vendor_mode=LIVE_VENDOR_MATCHED
source_pair=INSTALLER_VERIFIED
```

OTA_VENDOR_BUNDLED_MATCHED profile:

```text
F2B_LAUNCHER_V1
platform=athena
vendor_mode=OTA_VENDOR_BUNDLED_MATCHED
source_pair=INSTALLER_VERIFIED
```

I2-S defines source_pair=INSTALLER_VERIFIED as required runtime structure and
resolving dependency closure verification only. Source trust is the user's
choice; no source-origin receipt, full image/OTA hash, libasp fingerprint or
cross-build fingerprint is required. Explicit single-archive acquisition and
vendor mode selection remain mandatory. See ../INSTALLER.md. This changes
installer source qualification, not the launcher's ownership/mount/FD contract.

Live mode opens the trusted host / then the literal vendor component, requires
its existing VFS mount to be read-only and uses only that source. Bundled mode
opens rootfs/vendor and never tries host /vendor. Both require ARM32 lib/libasp.so
and nonempty etc/audio-algorithms/{asp.cfg,AFE.cfg}. These are minimal sanity
checks, not a dependency closure or a universal compatibility matrix. Original
Bionic linker resolves dependencies/symbols; loader failures terminate without
HELLO and the existing host falls back. Firmware pairing, all required vendor
configuration dependencies and actual DSP ABI need later qualification.

## Mount and exec path

After unshare(CLONE_NEWNS), the very next operation sets MS_REC|MS_PRIVATE on /.
A non-recursive self-bind of the installed rootfs creates its private mount;
the launcher reopens rootfs from the pinned lib FD, compares inode identity and
re-enters the new mount. This matters: retaining cwd below a covering bind would
bypass the final root read-only remount. Sources stay FD-pinned, target resolution
uses only this trusted tree.

system and the explicitly selected vendor source are non-recursive RO bind
mounts (nosuid,nodev). The launcher mounts actual sysfs RO/noexec at sys and actual
procfs RO/nosuid/nodev/noexec at .realproc. proc remains an ordinary directory.
dev is a private 256KiB tmpfs with null/zero/random/urandom nodes mode0600 and
fd/stdin/stdout/stderr symlinks. data is a private 16MiB tmpfs, mode0700,
nosuid/nodev/noexec. The installed rootfs bind is finally remounted RO; only dev
and data are writable scratch. This does not change any host /data permissions.

After chroot and chdir(/), all four miccal aliases must open as regular sysfs
files. No calibration byte is read, parsed, copied or logged. The factory
Calibrator remains the single gain authority; the launcher touches no PCM/Q30.
Signals are unblocked, standard cancellation signals restored to default, every
FD>=3 is marked CLOEXEC via close_range and execveat(AT_EMPTY_PATH) executes
the pinned child. All host directory/executable FDs close on successful exec.
Child argv0 is /factory/asp2-child; its environment is fixed LANG/LC_ALL/PATH
and the prototype's original Bionic/VNDK LD_LIBRARY_PATH. No LD_PRELOAD or host
environment is inherited.

There is no fork, supervisor, pipe relay, mount daemon or namespace keeper.
The child replaces the launcher PID and keeps stdin/stdout/stderr. Launcher
errors emit stderr only and exit126; normal exit, exec error or host Kill/Wait
releases its FDs and namespace mounts. The trusted child must not daemonize or
pass namespace FDs to other processes. Chroot is filesystem presentation, not a
sandbox against malicious root/vendor code. Root-equivalent attackers are
excluded by the approved architecture.

## Offline limits and next gate

No launcher execution, privileged mounts, mount/chroot tests, CI/mock/emulation
framework, Echo access or hardware PASS is part of this delivery. Source review,
ARM32 crosscompile/ELF inspection and the existing nonprivileged asset/CFG2/mock
regressions are the offline checks. Historical assets/closure.c is neither
linked nor imported.

A separate DEVICE GO must qualify this actual ELF with the original Bionic
linker, execveat/AT_EXECFN and proc/self/exe behavior, genuine four calibration
aliases, both selected-source policies as available, mount cleanup/error
fallback, signal/host-kill behavior and the unchanged 500ms HELLO / 25ms exchange
budgets. Athena kernel6.18 supplies execveat and close_range; other kernels or
platforms are unqualified. Production factory admission remains disabled.
