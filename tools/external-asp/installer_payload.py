"""Build one immutable private rootfs; prepare never touches a device."""
import contextlib
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from installer_sources import (BUNDLE, LIVE, Directory, Ext4, Refusal, ZipTree, closure,
                               digest, digest_bytes, elf, json_file, ota_open, pair, require)

WARNING = ("TIMING GATE OPEN: genuine I1 QEMU HELLO 6.49-8.52s exceeds 500ms; "
           "PCM exceeds 25ms. Native Athena latency UNKNOWN. Deadlines unchanged. "
           "Preparation never authorizes activation; future DEVICE GO required.")
ALIASES = {"self": "/.realproc/self", "sys": "/.realproc/sys",
           "cpuinfo": "/.realproc/cpuinfo", "device-tree": "/sys/firmware/devicetree/base",
           **{"idme/miccal." + str(i): "/proc/device-tree/idme/miccal." + str(i) + "/value"
              for i in range(4)}}
RECEIPT = "etc/installer-receipt.json"
PROFILE = "etc/launcher.profile"


def profile(mode):
    require(mode in (LIVE, BUNDLE), "invalid explicit vendor mode")
    return ("F2B_LAUNCHER_V1\nplatform=athena\nvendor_mode=" + mode +
            "\nsource_pair=INSTALLER_VERIFIED\n").encode()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    path.chmod(0o600)


def channel_map(raw):
    require(len(raw) <= 128, "oversized channel-map")
    try:
        lines = raw.decode("ascii").splitlines(keepends=True)
        require(len(lines) == 3 and lines[0] == "ASP2-CHANNEL-MAP-V1\n",
                "invalid channel-map header")
        mic = [int(x) for x in lines[1].removeprefix("mic=").strip().split(",")]
        ref = [int(x) for x in lines[2].removeprefix("ref=").strip().split(",")]
        require(sorted(mic) == [0, 1, 2, 3] and sorted(ref) == [0, 1],
                "channel-map must contain explicit MIC4/REF2 permutations")
        canonical = ("ASP2-CHANNEL-MAP-V1\nmic=" + ",".join(map(str, mic)) +
                     "\nref=" + ",".join(map(str, ref)) + "\n").encode()
        require(raw == canonical, "channel-map must use exact I1 syntax")
    except (UnicodeError, ValueError) as e:
        raise Refusal("invalid strict I1 channel-map") from e
    return {"mic": mic, "ref": ref}


def check_mapping(a, raw, fingerprint, scope):
    require(a.get("schema") == "ASP2-MAPPING-AUTHORITY-V1" and a.get("authority") and
            a.get("channel_map_sha256") == digest_bytes(raw) and
            a.get("captured_slot_idme_association") in ("CONFIRMED", "OWNER_APPROVED_ALSA_ORDER") and a.get("scope") == scope,
            "mapping lacks owner approval and captured-slot IDME confirmation")
    if a["captured_slot_idme_association"] == "OWNER_APPROVED_ALSA_ORDER":
        require(channel_map(raw) == {"mic": [0, 1, 2, 3], "ref": [0, 1]},
                "owner-approved default ALSA authority applies only to identity map")
    return a


def mapping_authority(path, raw, fingerprint, scope):
    return check_mapping(json_file(path), raw, fingerprint, scope)


def source_a(args):
    backup = getattr(args, "backup_dir", None)
    require(not getattr(args, "expected_sha256", None), "--expected-sha256 applies to an OTA only; backup images are never hashed")
    require(not args.ota and not getattr(args, "ota_url", None), "A never accepts an OTA source")
    if backup:
        require(not args.system_image and not args.vendor_reference,
                "--backup-dir cannot be mixed with explicit image paths")
        system_path = Path(backup) / "p21-system.img"
        vendor_path = Path(backup) / "p12-vendor.img"
    else:
        require(args.system_image and args.vendor_reference,
                "A requires --backup-dir or --system-image and --vendor-reference")
        system_path, vendor_path = args.system_image, args.vendor_reference
    system = Ext4(system_path, "system")
    p = Path(vendor_path)
    vendor = Directory(p) if p.is_dir() else Ext4(p, "")
    return system, vendor


def bundle_readers(z, fmt, label):
    from installer_ext4 import ZipRaw
    if fmt == "ZIP_FULL_BLOCK_BROTLI_V4":
        from installer_block_ota import plans, SelectiveBlocks
        plan = plans(z)
        return tuple(Ext4(None, "system" if part == "system" else "",
                          source=SelectiveBlocks(z, part, plan[part]),
                          label=label + ":" + part + " (selective blocks)")
                     for part in ("system", "vendor"))
    if fmt == "ZIP_RAW_EXT4_IMAGES":
        return tuple(Ext4(None, "system" if part == "system" else "",
                          source=ZipRaw(z, part + ".img"), label=label + ":" + part + ".img")
                     for part in ("system", "vendor"))
    return ZipTree(z, "system"), ZipTree(z, "vendor")


def inspect(args):
    # Local inspect never writes. An explicitly requested URL uses a temporary download.
    if args.source_authority:
        json_file(args.source_authority)  # Legacy optional diagnostic, not source authentication.
    if args.mode == LIVE:
        system, vendor = source_a(args)
        identity = pair(system, vendor)
        from installer_ext4 import resolve
        elf(resolve([(system, "read", "bin/linker")])[0])
        return {"mode": LIVE, "source_validation": identity,
                "vendor_reference": vendor.label,
                "live_vendor_revalidation_required": True, "device_verified_now": False,
                "warning": WARNING}
    require(not args.system_image and not args.vendor_reference and not getattr(args, "backup_dir", None),
            "B refuses mixed-source inputs")
    from installer_download import selected_ota
    with selected_ota(args) as path:
        z, metadata, fmt = ota_open(path)
        with contextlib.closing(z):
            block_summary = {}
            if fmt == "ZIP_FULL_BLOCK_BROTLI_V4":
                from installer_block_ota import plans, summary
                block_summary = {part: summary(plan) for part, plan in plans(z).items()}
            identity = pair(ZipTree(z, "system"), ZipTree(z, "vendor")) if fmt == "ZIP_FULL_FILE_TREE" else None
            return {"mode": BUNDLE, "format": fmt, "metadata": metadata,
                    "source_validation": identity or "EXTRACTION_REQUIRED",
                    "selective_plan": block_summary, "official_signature_verified": False,
                    "source_authenticated": False, "warning": WARNING}


def safe_output(path):
    path = Path(path).absolute()
    require(not path.exists() and not path.is_symlink(), "output already exists; refusing overwrite")
    require(path.parent.is_dir() and not path.parent.is_symlink(), "output parent must exist")
    for p in [path.parent, *path.parent.parents]:
        require(not p.is_symlink(), "output ancestor symlink")
    return path


def prepare(args):
    out = safe_output(args.output)
    require(args.launcher and args.child and args.channel_map,
            "prepare requires launcher, child and explicit channel-map")
    legacy = json_file(args.source_authority) if args.source_authority else {}
    scope = "SYNTHETIC_FIXTURE" if legacy.get("scope") == "SYNTHETIC_FIXTURE" or getattr(args, "fixture", False) else "OWNER_CONFIRMED"
    authority = None
    launcher, child, mapping = (Path(p).read_bytes() for p in
                               (args.launcher, args.child, args.channel_map))
    require(not elf(launcher, native_static=True), "launcher must be static with no DT_NEEDED")
    elf(child, "/system/bin/linker")
    channel_map(mapping)
    require(args.mapping_authority or args.allow_unqualified_map,
            "no mapping authority; use --allow-unqualified-map for NONINSTALLABLE preview")
    # All work is in a private sibling. Exceptions remove only this new directory.
    stage = Path(tempfile.mkdtemp(prefix=".asp2-prepare-", dir=out.parent))
    os.chmod(stage, 0o700)
    try:
        with contextlib.ExitStack() as stack:
            package_sha, metadata, fmt = None, None, "RAW_EXT4_BACKUP"
            reconstruction = None
            if shutil.disk_usage(stage).free < 128 * 1024**2:
                print("Storage warning: less than 128MiB free for selected payload and reserve.", file=__import__("sys").stderr)
            if args.mode == LIVE:
                system, vendor = source_a(args)
            else:
                require(not args.system_image and not args.vendor_reference and not getattr(args, "backup_dir", None),
                        "B refuses mixed-source inputs")
                from installer_download import selected_ota
                path = stack.enter_context(selected_ota(args, stage))
                z, metadata, fmt = ota_open(path)
                stack.callback(z.close)
                label = "user-selected HTTP(S) download" if getattr(args, "ota_url", None) else str(path)
                system, vendor = bundle_readers(z, fmt, label)
            contents, edges = closure(system, vendor, child)
            identity = pair(system, vendor)
            ma = (mapping_authority(args.mapping_authority, mapping, identity["fingerprint"], scope)
                  if args.mapping_authority else None)
            if fmt == "ZIP_FULL_BLOCK_BROTLI_V4":
                reconstruction = {part: reader.source.metrics() for part, reader in (("system", system), ("vendor", vendor))}
            source = {"system": system.label, "vendor": vendor.label, "format": fmt,
                      "identity": identity, "reconstruction": reconstruction,
                      "authenticated": False, "download_stored_locally": bool(getattr(args, "ota_url", None))}
            payload = stage / "payload"
            payload.mkdir(mode=0o700)
            root = payload / "lib/rootfs"
            for d in ("bin", "etc", "lib", "lib/rootfs"):
                (payload / d).mkdir(parents=True, exist_ok=True, mode=0o700)
            for d in ("factory", "system", "vendor", "proc/idme", "sys", ".realproc", "dev", "data"):
                (root / d).mkdir(parents=True, exist_ok=True, mode=0o700)
            for name, data in contents.items():
                if args.mode == LIVE and name.startswith("vendor/"):
                    continue
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                p.write_bytes(data)
                p.chmod(0o500 if name == "system/bin/linker" else 0o400)
            (payload / "bin/external-asp").write_bytes(launcher)
            (payload / "bin/external-asp").chmod(0o500)
            (root / "factory/asp2-child").write_bytes(child)
            (root / "factory/asp2-child").chmod(0o500)
            (root / "factory/channel-map").write_bytes(mapping)
            (root / "factory/channel-map").chmod(0o400)
            for name, target in ALIASES.items():
                if os.name != "nt" or not getattr(args, "pack_output", None):
                    (root / "proc" / name).symlink_to(target)
            if ma:
                (payload / PROFILE).write_bytes(profile(args.mode))
                (payload / PROFILE).chmod(0o400)
            receipt = {"schema": "ASP2-INSTALLER-V1", "payload_id": str(uuid.uuid4()),
                       "mode": args.mode, "scope": scope, "source": source,
                       "source_authority": authority, "mapping_authority": ma,
                       "installable": bool(ma), "required_uid": 0, "required_gid": 0,
                       "local_uid": getattr(os, "geteuid", lambda: None)(), "calibrator": "FACTORY_ONLY",
                       "q30": "METADATA_ONLY", "warning": WARNING,
                       "launcher_sha256": digest_bytes(launcher), "child_sha256": digest_bytes(child),
                       "channel_map_sha256": digest_bytes(mapping),
                       "live_vendor_revalidation_required": args.mode == LIVE,
                       "device_verified_now": False, "dependencies": edges}
            write_json(payload / RECEIPT, receipt)
            validate(payload, allow_preview=True, virtual_aliases=bool(getattr(args, "pack_output", None)))
            sync_tree(payload)
            os.rename(payload, out)
            sync_dir(out.parent)
            if getattr(args, "pack_output", None):
                from installer_pack import pack
                from argparse import Namespace
                pack(Namespace(payload=out, output=args.pack_output))
            return receipt
    finally:
        if os.name == "nt":
            def writable_remove(function, path, exc_info):
                os.chmod(path, 0o700)
                function(path)
            shutil.rmtree(stage, onerror=writable_remove)
        else:
            shutil.rmtree(stage)


def sync_dir(path):
    if os.name == "nt":
        return  # Directory fsync is not exposed by Python on Windows.
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def sync_tree(path):
    for base, dirs, files in os.walk(path, followlinks=False):
        for name in files:
            p = Path(base) / name
            if not p.is_symlink():
                with p.open("rb") as f:
                    os.fsync(f.fileno())
        sync_dir(base)


def validate(path, allow_preview=False, required_uid=None, virtual_aliases=False):
    path = Path(path)
    require(path.is_dir() and not path.is_symlink(), "payload is not a real directory")
    r = json_file(path / RECEIPT)
    require(r.get("schema") == "ASP2-INSTALLER-V1" and r.get("mode") in (LIVE, BUNDLE) and
            r.get("scope") in ("OWNER_CONFIRMED", "SYNTHETIC_FIXTURE"),
            "unrecognized payload receipt")
    require(set(x.name for x in path.iterdir()) == {"bin", "etc", "lib"},
            "unrecognized deployment root content")
    require(set(x.name for x in (path / "bin").iterdir()) == {"external-asp"} and
            set(x.name for x in (path / "etc").iterdir()) ==
            ({"installer-receipt.json", "launcher.profile"} if r["installable"]
             else {"installer-receipt.json"}) and
            set(x.name for x in (path / "lib").iterdir()) == {"rootfs"},
            "unrecognized deployment control files")
    root = path / "lib/rootfs"
    require(set(x.name for x in root.iterdir()) ==
            {"factory", "system", "vendor", "proc", "sys", ".realproc", "dev", "data"},
            "unrecognized rootfs content")
    for base, dirs, files in os.walk(path, followlinks=False):
        for name in [".", *dirs, *files]:
            p = Path(base) / name
            st = p.lstat()
            if p.is_symlink():
                rel = p.relative_to(root / "proc").as_posix() if p.is_relative_to(root / "proc") else ""
                require(rel in ALIASES and os.readlink(p) == ALIASES[rel], "unexpected payload symlink")
            else:
                require(p.is_file() or p.is_dir(), "special payload inode")
                require(os.name == "nt" or st.st_mode & 0o7022 == 0, "unsafe payload permissions")
            if required_uid is not None:
                require(st.st_uid == required_uid and st.st_gid == required_uid,
                        "payload ownership mismatch")
    for d in (path, path / "etc", path / "lib", root):
        require(os.name == "nt" or d.stat().st_mode & 0o7777 == 0o700, "private deployment directory must be 0700")
    for name, target in ALIASES.items():
        if virtual_aliases and not (root / "proc" / name).is_symlink() and not (root / "proc" / name).exists():
            continue
        require((root / "proc" / name).is_symlink() and
                os.readlink(root / "proc" / name) == target, "missing proc/IDME alias")
    for d in ("sys", ".realproc", "dev", "data"):
        require((root / d).is_dir() and not any((root / d).iterdir()), "nonempty mountpoint")
    require(set(x.name for x in (root / "factory").iterdir()) == {"asp2-child", "channel-map"},
            "unrecognized factory content")
    rawmap = (root / "factory/channel-map").read_bytes()
    channel_map(rawmap)
    for name, key in (("bin/external-asp", "launcher_sha256"),
                      ("lib/rootfs/factory/asp2-child", "child_sha256"),
                      ("lib/rootfs/factory/channel-map", "channel_map_sha256")):
        require(digest(path / name) == r[key], "self-built artifact/map identity changed")
    require(not elf((path / "bin/external-asp").read_bytes(), native_static=True), "launcher must be static")
    elf((root / "factory/asp2-child").read_bytes(), "/system/bin/linker")
    elf((root / "system/bin/linker").read_bytes())
    if r["mode"] == LIVE:
        require(not any((root / "vendor").iterdir()), "mode A must not persist vendor")
    else:
        pair(Directory(root / "system"), Directory(root / "vendor"))
        closure(Directory(root / "system"), Directory(root / "vendor"),
                (root / "factory/asp2-child").read_bytes())
    if r["installable"]:
        require((path / PROFILE).read_bytes() == profile(r["mode"]), "launcher.profile not exact F2-B")
        check_mapping(r["mapping_authority"], rawmap, r["source"]["identity"].get("fingerprint"), r["scope"])
    else:
        require(allow_preview, "NONINSTALLABLE preview: mapping authority absent")
    return r
