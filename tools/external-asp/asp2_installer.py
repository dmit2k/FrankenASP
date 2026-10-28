#!/usr/bin/env python3
"""FrankenASP ASP2 owner installer/builder. User-selected sources; never activates TECHO5."""
import argparse
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

# Avoid even bytecode/cache writes during inspect/status/dry-run.
sys.dont_write_bytecode = True
from installer_sources import BUNDLE, LIVE, Refusal, digest, elf, json_file, require
from installer_payload import WARNING, inspect, prepare, safe_output, write_json
# Linux-only deployment dependencies must not prevent portable source preparation.
DEST = Path("/data/techo5-linux/external-asp")


def deploy_action(args):
    require(sys.platform.startswith("linux"), "deployment/helpers require Linux; prepare on this host and transfer payload")
    import installer_deploy
    if args.command == "helpers":
        from installer_helpers import helpers
        return helpers(args)
    return getattr(installer_deploy, args.command.replace("-", "_"))(args)


def build(args):
    out = safe_output(args.output)
    config = json_file(args.config)
    allowed = {"ARM32_CC", "ARM32_SYSROOT", "ARM32_BINUTILS", "BIONIC_CC",
               "BIONIC_LD", "BIONIC_ROOT", "LD_LIBRARY_PATH"}
    require(set(config) <= allowed and all(isinstance(v, str) for v in config.values()),
            "build config contains unsupported keys")
    require({"ARM32_CC", "BIONIC_CC", "BIONIC_LD", "BIONIC_ROOT"} <= set(config),
            "build config requires existing ARM32 Linux and Bionic toolchain paths")
    out.mkdir(mode=0o700)
    source = Path(__file__).resolve().parent
    results = {}
    for name, script, artifact in (
            ("launcher", source / "launcher/build.sh", "external-asp-launcher-arm32"),
            ("bionic", source / "build_bionic.sh", "asp2-child")):
        env = {k: v for k, v in os.environ.items()
               if k in ("PATH", "LANG", "LC_ALL", "TMPDIR")}
        env.update(config)
        env["OUT_DIR"] = str(out / name)
        with (out / (name + ".log")).open("w") as log:
            p = subprocess.run(["bash", str(script)], env=env, stdout=log,
                               stderr=subprocess.STDOUT, timeout=180, check=False)
        require(p.returncode == 0, "build failed; inspect private " + name + ".log")
        path = out / name / artifact
        needed = elf(path.read_bytes(), "/system/bin/linker" if name == "bionic" else None,
                     native_static=name == "launcher")
        require(name != "launcher" or not needed, "launcher not static")
        results[name] = {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size}
    write_json(out / "build-receipt.json", {"artifacts": results, "config": config, "warning": WARNING})
    return results


def helper_flags(q, mutation=False):
    if mutation:
        q.add_argument("--stop-helpers", action="store_true", help="invoke the same opted-in helpers stop routine")
        q.add_argument("--r1-host", type=Path, action="append", default=[])
    else:
        q.add_argument("--opt-in", action="store_true")
    q.add_argument("--maintenance-ack", action="store_true",
                   help="owner has selected Built-in and prevents new external helper requests")
    q.add_argument("--force-kill", action="store_true", help="SIGKILL verified survivors only after bounded SIGTERM")
    q.add_argument("--force-unmount", action="store_true", help="cleanup exact owned mounts in pinned private namespace only")


def parser():
    p = argparse.ArgumentParser(description=__doc__, epilog=WARNING)
    sub = p.add_subparsers(dest="command", required=True)
    for cmd in ("inspect", "prepare"):
        q = sub.add_parser(cmd, epilog=WARNING)
        q.add_argument("--mode", choices=(LIVE, BUNDLE), required=True)
        q.add_argument("--system-image", type=Path)
        q.add_argument("--vendor-reference", type=Path,
                       help="A: owner-hosted vendor directory or raw ext4 image, read only")
        q.add_argument("--backup-dir", type=Path, help="A: exact directory with p21-system.img and p12-vendor.img")
        group = q.add_mutually_exclusive_group()
        group.add_argument("--ota", type=Path, help="B: one local full OTA ZIP")
        group.add_argument("--ota-url", help="B: user-selected HTTP(S), arbitrary TLS certificates accepted")
        q.add_argument("--expected-sha256", help="optional explicit source hash comparison; otherwise no source hashing")
        q.add_argument("--download-max-bytes", type=int, default=2 * 1024**3)
        q.add_argument("--download-timeout", type=float, default=30)
        q.add_argument("--download-total-timeout", type=float, default=1800)
        q.add_argument("--fixture", action="store_true", help="synthetic input: restrict resulting payload to local sandbox")
        q.add_argument("--source-authority", type=Path, help="legacy optional diagnostic; source provenance fields ignored")
        if cmd == "prepare":
            q.add_argument("--output", type=Path, required=True)
            q.add_argument("--pack-output", type=Path, help="also pack payload, without Windows symlink privilege")
            q.add_argument("--launcher", type=Path, required=True)
            q.add_argument("--child", type=Path, required=True)
            q.add_argument("--channel-map", type=Path, required=True)
            q.add_argument("--mapping-authority", type=Path)
            q.add_argument("--allow-unqualified-map", action="store_true",
                           help="NONINSTALLABLE preview, no launcher.profile")
    q = sub.add_parser("pack", help="deterministic offline TAR; approved symlinks need not exist on host")
    q.add_argument("--payload", type=Path, required=True)
    q.add_argument("--output", type=Path, required=True)
    q = sub.add_parser("build", epilog=WARNING)
    q.add_argument("--config", type=Path, required=True)
    q.add_argument("--output", type=Path, required=True)
    for cmd in ("dry-run", "install", "status", "rollback", "uninstall"):
        q = sub.add_parser(cmd, epilog=WARNING)
        q.add_argument("--destination", type=Path, default=DEST)
        q.add_argument("--local-root", type=Path, help="throwaway private /tmp sandbox only")
        if cmd in ("dry-run", "install"):
            q.add_argument("--payload", type=Path, required=True)
        if cmd in ("dry-run", "install", "rollback"):
            q.add_argument("--live-vendor", type=Path)
        if cmd in ("install", "rollback", "uninstall"):
            q.add_argument("--opt-in", action="store_true")
            q.add_argument("--confirm-inactive", action="store_true")
            helper_flags(q, mutation=True)
        if cmd in ("rollback", "uninstall"):
            q.add_argument("--generation", required=True, help="exact generation UUID from status")
    q = sub.add_parser("helpers", help="read-only helper plan or explicitly opted-in scoped stop")
    h = q.add_subparsers(dest="helper_command", required=True)
    for action in ("status", "stop"):
        q = h.add_parser(action)
        q.add_argument("--destination", type=Path, default=DEST)
        q.add_argument("--local-root", type=Path)
        q.add_argument("--r1-host", type=Path, action="append", default=[],
                       help="explicit trusted R1 host executable for FD3/FD4 helpers outside registered generations")
        if action == "stop":
            helper_flags(q)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    print(WARNING, file=sys.stderr)
    if args.command in ("inspect", "prepare"):
        print("User-selected source; contents/download are not authenticated.", file=sys.stderr)
    from installer_pack import pack
    actions = {"pack": pack, "inspect": inspect, "prepare": prepare, "build": build,
               "dry-run": deploy_action, "install": deploy_action, "status": deploy_action,
               "rollback": deploy_action, "uninstall": deploy_action, "helpers": deploy_action}
    try:
        result = actions[args.command](args)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except KeyboardInterrupt:
        print("ASP2 installer cancelled.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, KeyError, TypeError, AttributeError, zipfile.BadZipFile) as e:
        print("ASP2 installer REFUSED: " + str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
