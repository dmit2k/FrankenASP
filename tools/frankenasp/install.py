#!/usr/bin/env python3
"""Prepare and optionally stage owner-supplied Athena factory voice DSP.

Default mode is READ-ONLY verification. Requires --install for writes.
Reads p21-system.img ONLY in --backup-partitions (no recursive discovery).
Uses the owner's intact, read-only /vendor on the Echo. Never flashes
partitions, replaces the running TECHO5 binary or activates factory mode.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile

import preflight as pf

BASE = "/data/techo5-linux"
RUNTIME = BASE + "/amazon-arm32"
TRIAL = BASE + "/frankenasp-trial"
GUARD_FILES = (BASE + "/fireos-asp.enabled", "/run/techo5/frankenasp-armed",
               "/run/techo5/frankenasp-trial-active", "/run/techo5/hold")
EXPECTED_BUILD = "PS75741.7080N"
EXPECTED_DEVICE = "athena"
EXPECTED_SDK = "28"
# 41 system ELF libraries + original linker and sh; four auxiliary
# provenance files. Never copy factory vendor payloads from backups.
FACTORY_SYSTEM_FILES = pf.REQUIRED_SYSTEM + pf.OPTIONAL_SYSTEM


def run(argv, *, timeout=120, env=None, input=None):
    result = subprocess.run(argv, input=input, capture_output=True,
                            timeout=timeout, env=env, check=False)
    if result.returncode:
        stderr = result.stderr.decode(errors="replace")
        raise RuntimeError(f"{argv[0]} failed (exit {result.returncode}): {stderr[-600:]}")
    return result.stdout


def require_tool(name):
    if shutil.which(name) is None:
        raise RuntimeError(f"required host executable missing: {name}")


def read_backup(path, *, accept_unverified=False):
    if not path.is_dir():
        raise ValueError("--backup-partitions must be an existing directory")
    image = path / "p21-system.img"
    if not image.is_file() or image.is_symlink() or image.stat().st_size < (64 << 20):
        raise ValueError("original p21-system.img is missing, a symlink, or unusually small")
    sha = path / "SHA256SUMS"
    verified = False
    if sha.is_file():
        expected = None
        for line in sha.read_text().splitlines():
            m = re.fullmatch(r"([a-fA-F0-9]{64})\s+\*?p21-system\.img", line.strip())
            if m:
                expected = m.group(1).lower()
                break
        if expected is None:
            raise ValueError("SHA256SUMS exists but has no p21-system.img entry")
        if pf.sha256_file(image) != expected:
            raise ValueError("p21-system.img SHA256 does not match owner's backup ledger")
        verified = True
    elif not accept_unverified:
        raise ValueError("missing SHA256SUMS; explicitly pass --accept-unverified-backup if no ledger exists")
    return image, verified


def debugfs(image, op, name):
    # All filesystem paths are fixed constants; no user-provided ELF names.
    return run(["debugfs", "-R", op + " /system/" + name, str(image)],
               timeout=45).decode(errors="replace")


def verify_factory_image(image):
    # Android p21 has a /system directory INSIDE the ext4 filesystem.
    raw = debugfs(image, "cat", "build.prop")
    props = {}
    for line in raw.splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            props[k.strip()] = v.strip()
    observed = {k: props.get(k) for k in
                ("ro.build.id", "ro.product.device", "ro.build.version.sdk")}
    required = {"ro.build.id": EXPECTED_BUILD,
                "ro.product.device": EXPECTED_DEVICE,
                "ro.build.version.sdk": EXPECTED_SDK}
    if observed != required:
        raise ValueError("factory system firmware identity differs from tested Athena profile: " +
                         json.dumps(observed, sort_keys=True))
    missing = [name for name, ok in
               pf.original_system_image(image, FACTORY_SYSTEM_FILES).items() if not ok]
    if missing:
        raise ValueError("factory p21 is missing required files: " + ", ".join(missing))
    return observed


def validate_device(target):
    vendor, digest = pf.ssh_vendor(target)
    inventory = pf.evaluate(vendor, sha=digest)
    if inventory["next_action"] != "find_first_install_fireos_p21_system_backup":
        # First-install source image is checked separately by verify_factory_image.
        if not inventory["vendor_complete"]:
            raise ValueError("original /vendor incomplete: " + ", ".join(inventory["vendor_missing"]))
        raise ValueError("factory /vendor identity does not match tested Athena libasp.so")
    remote = (
        "uname -m; uname -r; "
        "awk '$2==\"/vendor\" {print $4}' /proc/mounts; "
        "for p in " + " ".join(GUARD_FILES) + "; do "
        "if test -e \"$p\"; then echo ACTIVE; else echo CLEAR; fi; done; "
        "for p in " + RUNTIME + " " + TRIAL + "; do "
        "if test -e \"$p\"; then echo EXISTS; else echo ABSENT; fi; done"
    )
    lines = ssh(target, remote).decode(errors="replace").splitlines()
    if len(lines) != 3 + len(GUARD_FILES) + 2:
        raise ValueError("unexpected device identity/state output")
    if lines[0] != "aarch64" or "athena" not in lines[1].lower():
        raise ValueError("expected Echo Show 8 Gen 2 Athena AArch64 mainline")
    if "ro" not in lines[2].split(","):
        raise ValueError("original vendor must be mounted read-only")
    return {
        "device_arch": lines[0], "kernel": lines[1], "vendor_readonly": True,
        "factory_libasp_sha256_verified": True,
        "active_guard_present": "ACTIVE" in lines[3:3+len(GUARD_FILES)],
        "runtime_already_exists": lines[-2] == "EXISTS",
        "trial_already_exists": lines[-1] == "EXISTS",
    }


def ssh(target, command, *, input=None, timeout=120):
    # No untrusted input enters the remote shell command.
    return run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                "--", target, command], input=input, timeout=timeout)


def assert_arm_elf(path, *, arch):
    header = run(["readelf", "-h", str(path)], timeout=15).decode(errors="replace")
    required = (("ELF32", "ARM") if arch == "arm32" else ("ELF64", "AArch64"))
    if required[0] not in header or not re.search(r"Machine:\s*" + required[1] + r"\b", header):
        raise ValueError(f"wrong ELF target for {path.name}: expected {arch}")
    if arch == "arm32":
        versions = run(["readelf", "--version-info", str(path)], timeout=15)
        if b"GLIBC_" in versions:
            raise ValueError("glibc-linked ARM32 worker is incompatible with Bionic")


def extract_system(image, out):
    system = out / "amazon-arm32" / "system"
    for name in FACTORY_SYSTEM_FILES:
        dest = system / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        # debugfs dump is a source read; output path is a new private staging tree.
        if any(x.isspace() for x in str(dest)):
            raise ValueError("staging path contains whitespace; debugfs dump cannot safely handle it")
        debugfs(image, "dump", name + " " + str(dest))
        if not dest.is_file() or dest.stat().st_size == 0:
            raise RuntimeError("empty or missing extracted original /system/" + name)
    for name in ("bin/linker", "bin/sh"):
        assert_arm_elf(system / name, arch="arm32")
        (system / name).chmod(0o755)
    return system


def make_worker(out, worker, ndk):
    target = out / "amazon-arm32" / "libasp_stream_worker.so"
    if worker:
        source = worker.resolve()
        if not source.is_file():
            raise ValueError("prebuilt worker does not exist")
        shutil.copyfile(source, target)
    else:
        if not ndk:
            raise ValueError("--install requires --worker or --android-ndk")
        builder = Path(__file__).resolve().parent / "build_worker.sh"
        env = dict(os.environ, ANDROID_NDK_HOME=str(ndk.resolve()))
        run(["bash", str(builder), str(target)], env=env, timeout=180)
    assert_arm_elf(target, arch="arm32")
    target.chmod(0o755)


def make_native_shell(out):
    shell = out / "amazon-arm32" / "system/bin/sh"
    native = out / "amazon-arm32" / "system/bin/sh-native"
    shutil.copyfile(shell, native)
    run(["patchelf", "--set-interpreter", RUNTIME + "/system/bin/linker",
         str(native)], timeout=30)
    assert_arm_elf(native, arch="arm32")
    interp = run(["readelf", "-l", str(native)], timeout=15).decode(errors="replace")
    if RUNTIME + "/system/bin/linker" not in interp:
        raise RuntimeError("patched shell ELF interpreter verification failed")
    native.chmod(0o755)


def checksums(folder):
    entries = []
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            rel = path.relative_to(folder).as_posix()
            if path.is_symlink():
                raise ValueError("unexpected symlink in staged private runtime")
            entries.append(f"{pf.sha256_file(path)}  {rel}")
    (folder / "SHA256SUMS").write_text("\n".join(entries) + "\n")


def prepare(image, stage, worker, ndk, binary):
    payload = stage / "device"
    payload.mkdir(mode=0o700, parents=True)
    runtime = payload / "amazon-arm32"
    runtime.mkdir(mode=0o700)
    extract_system(image, payload)
    make_worker(payload, worker, ndk)
    make_native_shell(payload)
    checksums(runtime)
    trial = payload / "frankenasp-trial"
    trial.mkdir(mode=0o700)
    experimental = trial / "techo5-experimental"
    shutil.copyfile(binary.resolve(), experimental)
    assert_arm_elf(experimental, arch="arm64")
    experimental.chmod(0o700)
    trials = Path(__file__).resolve().parent / "trial.sh"
    shutil.copyfile(trials, trial / "trial.sh")
    (trial / "trial.sh").chmod(0o700)
    # Persistency is opt-in through a separate device-local control script.
    # The installer NEVER patches the boot launcher or sets persistent flags.
    for filename in ("persist.sh", "persistent-run.sh", "persist-watch.sh"):
        src = Path(__file__).resolve().parent / filename
        shutil.copyfile(src, trial / filename)
        (trial / filename).chmod(0o700)
    checksums(trial)
    return payload


def install(target, payload, *, nonce):
    incoming = BASE + "/.frankenasp-incoming-" + nonce
    # Refuse modifying a unit already staged/running experiments.
    ensure = (
        "set -eu; "
        "test ! -e " + RUNTIME + "; test ! -e " + TRIAL + "; "
        + "; ".join("test ! -e " + x for x in GUARD_FILES) + "; "
        "test ! -e " + incoming + "; "
        "mkdir -m 700 " + incoming
    )
    ssh(target, ensure)
    # Tar in memory-bounded streaming mode; the source tree remains private.
    try:
        tarpath = payload.parent / "device-payload.tar"
        # The host account may have a different numeric UID than root on
        # the Echo. Force private payload ownership to root on extraction.
        def root_owned(info):
            if not (info.isfile() or info.isdir()):
                raise ValueError("refusing non-regular file in staged runtime tar")
            info.uid, info.gid = 0, 0
            info.uname, info.gname = "root", "root"
            return info
        with tarfile.open(tarpath, "w") as tf:
            for name in ("amazon-arm32", "frankenasp-trial"):
                tf.add(payload / name, arcname=name, recursive=True,
                       filter=root_owned)
        with tarpath.open("rb") as fd:
            proc = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                 "--", target, "tar -C " + incoming + " -xf -"],
                stdin=fd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=180, check=False,
            )
        if proc.returncode:
            raise RuntimeError("remote tar unpack failed: " + proc.stderr.decode(errors="replace")[-450:])
        ssh(target, "set -eu; cd " + incoming +
            "/amazon-arm32 && sha256sum -c SHA256SUMS >/dev/null; "
            "cd " + incoming + "/frankenasp-trial && sha256sum -c SHA256SUMS >/dev/null")
        # Not atomically activating a service: only renaming new private dirs.
        ssh(target, "set -eu; test ! -e " + RUNTIME + "; test ! -e " + TRIAL +
            "; test ! -e " + GUARD_FILES[0] +
            "; mv " + incoming + "/amazon-arm32 " + RUNTIME +
            "; mv " + incoming + "/frankenasp-trial " + TRIAL +
            "; rmdir " + incoming +
            "; test ! -e " + GUARD_FILES[0] +
            "; test ! -e " + GUARD_FILES[1])
    except Exception as e:
        raise RuntimeError(str(e) + "; private incoming directory (if present): " + incoming +
                           "; inspect/clean it manually after confirming nothing is running") from e
    return {"runtime_directory": RUNTIME, "trial_directory": TRIAL,
            "activated": False, "official_daemon_modified": False,
            "firmware_partitions_modified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-partitions", type=Path, required=True,
                        help="EXACT directory containing p21-system.img (never recursively searched)")
    parser.add_argument("--device", required=True, help="owner's root SSH endpoint, e.g. root@echo-ip")
    parser.add_argument("--install", action="store_true", help="explicitly stage private files on device; never activate")
    parser.add_argument("--android-ndk", type=Path, help="official Android NDK with ARMv7 API 28 clang")
    parser.add_argument("--worker", type=Path, help="already built private ARM32/Bionic worker (.so)")
    parser.add_argument("--experimental-binary", type=Path,
                        help="self-built AArch64 experimental TECHO5 daemon (mandatory for --install)")
    parser.add_argument("--stage-dir", type=Path,
                        help="keep a NEW private staging directory instead of disposable temporary staging")
    parser.add_argument("--accept-unverified-backup", action="store_true",
                        help="explicitly accept a backup missing the installer's SHA256SUMS ledger")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.@:-]+", args.device) or args.device.startswith("-"):
        parser.error("invalid SSH target")
    if args.worker and args.android_ndk:
        parser.error("use --worker OR --android-ndk, not both")
    if args.stage_dir and not args.install:
        parser.error("--stage-dir only has meaning with --install")
    if args.install and (not args.experimental_binary or not (args.worker or args.android_ndk)):
        parser.error("--install requires --experimental-binary and one of --worker / --android-ndk")
    if args.install and not args.experimental_binary.is_file():
        parser.error("--experimental-binary does not exist")
    if args.install and args.stage_dir and args.stage_dir.exists():
        parser.error("--stage-dir already exists; refusing to reuse private staging output")
    require_tool("debugfs")
    require_tool("ssh")
    image, checksum_verified = read_backup(
        args.backup_partitions, accept_unverified=args.accept_unverified_backup)
    identity = verify_factory_image(image)
    device = validate_device(args.device)
    report = {
        "mode": "install" if args.install else "check_only",
        "backup_image": "p21-system.img",
        "backup_sha256_verified": checksum_verified,
        "factory_firmware": identity["ro.build.id"],
        "factory_sdk": identity["ro.build.version.sdk"],
        "device": device,
        "extract_system_files": len(FACTORY_SYSTEM_FILES),
        "vendor_source": "existing_ro_device_partition",
        "native_runtime_target": RUNTIME,
        "will_overwrite_firmware_or_daemon": False,
        "will_activate_frankenasp": False,
    }
    if not args.install:
        print(json.dumps(report, indent=2, sort_keys=True))
        return
    if device["active_guard_present"] or device["runtime_already_exists"] or device["trial_already_exists"]:
        raise RuntimeError("device already has active/staged FrankenASP or a hold; no existing files changed")
    for tool in ("patchelf", "readelf"):
        require_tool(tool)
    if not args.worker:
        require_tool("bash")
    if args.stage_dir:
        directory = args.stage_dir.resolve()
        directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        context = contextlib.nullcontext(directory)
    else:
        context = tempfile.TemporaryDirectory(prefix="frankenasp-private-", dir=None)
    with context as loc:
        stage = Path(loc)
        try:
            payload = prepare(image, stage, args.worker, args.android_ndk, args.experimental_binary)
            report["installation"] = install(args.device, payload, nonce=secrets.token_hex(8))
        finally:
            if args.stage_dir:
                print("Private factory staging tree retained at explicitly requested --stage-dir", file=sys.stderr)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print("FrankenASP setup: " + str(exc), file=sys.stderr)
        sys.exit(2)
