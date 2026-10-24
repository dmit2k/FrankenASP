#!/usr/bin/env python3
"""Read-only Athena Franken ASP input inventory; never extracts or stages firmware.

Checks the intact factory /vendor (via local files or SSH), an optional
pre-TECHO5 p21-system.img using debugfs, and optional owner-local runtime.
Does not execute native code, read IDME, change mixer state or install anything.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

VENDOR_FILES = (
    "lib/libasp.so", "lib/libamazonlog.so",
    "lib/libtensorflowlite_c.so", "lib/libedgeflow_core_neon.so",
    "etc/audio-algorithms/asp.cfg",
    "etc/audio-algorithms/AFE.cfg",
    "etc/audio-algorithms/coefs_FBFV2_LowLatency_8beams.cfg",
)
# Conservative tested factory DT_NEEDED closure; not a guaranteed minimal set.
SYSTEM_LIBS = (
    "vndk-28/libmedia_helper.so", "vndk-28/libspeexresampler.so",
    "vndk-28/libaudioutils.so",
    "vndk-sp-28/libutils.so", "vndk-sp-28/libcutils.so",
    "vndk-sp-28/libc++.so",
    "liblog.so", "libc.so", "libm.so", "libdl.so",
    "libvndksupport.so", "libc++.so", "libEGL.so",
    "libGLESv2.so", "ld-android.so", "libcutils.so",
    "libgraphicsenv.so", "libnativewindow.so", "libbacktrace.so",
    "android.hardware.configstore@1.0.so",
    "android.hardware.configstore-utils.so",
    "libhidlbase.so", "libhidltransport.so", "libutils.so",
    "libhardware.so", "libui.so",
    "android.hardware.graphics.common@1.1.so",
    "libbase.so", "libunwind.so", "libunwindstack.so",
    "libdexfile.so", "libhwbinder.so",
    "android.hardware.configstore@1.1.so",
    "android.hardware.graphics.allocator@2.0.so",
    "android.hardware.graphics.mapper@2.0.so",
    "android.hardware.graphics.mapper@2.1.so",
    "libsync.so", "libutilscallstack.so",
    "android.hardware.graphics.common@1.0.so",
    "liblzma.so", "libz.so",
)
REQUIRED_SYSTEM = ("bin/linker", "bin/sh") + tuple("lib/" + name for name in SYSTEM_LIBS)
OPTIONAL_SYSTEM = (
    "etc/ld.config.28.txt", "etc/public.libraries.txt",
    "etc/public.libraries-AMAZON.txt", "build.prop",
)
TESTED_ASP_SHA256 = "bf2a0b569d8bfb7482b2d0a4b5dfffc2601c60a92b6389e5b8839160b3119bb9"


def local_files(root, files, prefix=""):
    return {f: (root / prefix / f).is_file() and (root / prefix / f).stat().st_size > 0
            for f in files}


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as fd:
        for block in iter(lambda: fd.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def ssh_vendor(target):
    if not re.fullmatch(r"[a-zA-Z0-9_.@:-]+", target) or target.startswith("-"):
        raise ValueError("invalid SSH target")
    # Interpolated filenames are all constants declared in VENDOR_FILES.
    remote = "; ".join(
        ("if test -r /vendor/" + f + "; then printf '1\\n';"
         " else printf '0\\n'; fi") for f in VENDOR_FILES
    )
    p = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=7",
         "--", target, remote],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if p.returncode or len(p.stdout.splitlines()) != len(VENDOR_FILES):
        raise RuntimeError("SSH /vendor read-only check failed")
    lines = p.stdout.splitlines()
    if any(v not in ("1", "0") for v in lines):
        raise RuntimeError("unexpected SSH inventory response")
    found = dict(zip(VENDOR_FILES, (v == "1" for v in lines)))
    # Only the identity hash of the stock ASP binary; no IDME or config content.
    p = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=7",
         "--", target, "sha256sum /vendor/lib/libasp.so"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    digest = p.stdout.split()[0] if not p.returncode and p.stdout else None
    if digest is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        digest = None
    return found, digest


def original_system_image(image, files):
    if not image.is_file() or not image.stat().st_size:
        raise ValueError("system image absent or empty")
    out = {}
    for f in files:
        # Athena original p21 ext4 contains a /system directory at its root.
        proc = subprocess.run(
            ["debugfs", "-R", "stat /system/" + f, str(image)],
            capture_output=True, text=True, timeout=15, check=False,
        )
        out[f] = "Inode:" in proc.stdout and "Size:" in proc.stdout
    return out


def evaluate(vendor, system_backup=None, runtime=None, sha=None):
    missing_vendor = sorted(name for name, ok in vendor.items() if not ok)
    missing_image = sorted(name for name, ok in (system_backup or {}).items() if not ok)
    missing_runtime = sorted(name for name, ok in (runtime or {}).items() if not ok)
    vendor_ok = not missing_vendor
    backup_ok = system_backup is not None and not missing_image
    runtime_ok = runtime is not None and not missing_runtime
    if not vendor_ok:
        next_action = "investigate_vendor_partition_without_writing"
    elif sha is None or sha.lower() != TESTED_ASP_SHA256:
        next_action = "factory_revision_unvalidated_do_not_enable"
    elif runtime_ok:
        next_action = "static_files_present_review_abi_and_trial_guards"
    elif backup_ok:
        next_action = "extract_matching_arm32_system_to_owner_private_runtime"
    else:
        next_action = "find_first_install_fireos_p21_system_backup"
    return {
        "profile": "athena_factory_android9_arm32_research",
        "vendor_checked": len(vendor),
        "vendor_complete": vendor_ok,
        "vendor_missing": missing_vendor,
        "tested_factory_libasp_sha256_match":
            None if sha is None else (sha.lower() == TESTED_ASP_SHA256),
        "system_backup_checked": system_backup is not None,
        "system_backup_complete": backup_ok if system_backup is not None else None,
        "system_backup_missing": missing_image,
        "isolated_runtime_checked": runtime is not None,
        "isolated_runtime_complete": runtime_ok if runtime is not None else None,
        "isolated_runtime_missing": missing_runtime,
        "next_action": next_action,
        "note": "File inventory only: does not prove native ABI, license, runtime startup, or acoustic behavior",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sources = p.add_mutually_exclusive_group(required=True)
    sources.add_argument("--vendor-root", type=Path, help="local directory corresponding to /vendor")
    sources.add_argument("--ssh-target", help="SSH name of user's Echo, checks /vendor read-only")
    p.add_argument("--system-image", type=Path, help="owner's original Fire OS p21-system.img, read only")
    p.add_argument("--runtime-root", type=Path, help="private staging root containing system/lib/ and system/bin/")
    a = p.parse_args()
    try:
        if a.ssh_target:
            vendor, digest = ssh_vendor(a.ssh_target)
        else:
            vendor = local_files(a.vendor_root, VENDOR_FILES)
            lib = a.vendor_root / "lib/libasp.so"
            digest = sha256_file(lib) if vendor["lib/libasp.so"] else None
        backup = original_system_image(a.system_image, REQUIRED_SYSTEM) if a.system_image else None
        runtime = local_files(a.runtime_root, REQUIRED_SYSTEM, "system") if a.runtime_root else None
        result = evaluate(vendor, backup, runtime, digest)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as e:
        p.error(str(e))
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["vendor_complete"] or (a.system_image and not result["system_backup_complete"]):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
