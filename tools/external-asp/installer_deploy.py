"""Local opt-in atomic installation. No SSH, activation, service or firmware code."""
import contextlib
import ctypes
import errno
import fcntl
import json
import os
import re
import shutil
import stat
import tempfile
import time
import uuid
from pathlib import Path

from installer_payload import (ALIASES, RECEIPT, WARNING, sync_dir, sync_tree, validate, write_json)
from installer_sources import (LIVE, Directory, Refusal, closure, digest, pair, require)

DEST = Path("/data/techo5-linux/external-asp")
REGISTRY = ".external-asp-owner.json"
PREFIX = ".external-asp-generation-"


def identity(path):
    st = Path(path).lstat()
    return {"dev": st.st_dev, "ino": st.st_ino, "uid": st.st_uid}


def unescape_mount(text):
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), text)


def active_check(roots, proc=Path("/proc"), local=False):
    """Check FD3/FD4, executable, cwd, mmap and covering/subtree mounts."""
    prefixes = [str(p.absolute()) for p in roots]
    def under(value):
        value = value.removesuffix(" (deleted)")
        return any(value == p or value.startswith(p + "/") for p in prefixes)
    mounts = (proc / "self/mountinfo").read_text()
    for line in mounts.splitlines():
        fields = line.split()
        require(len(fields) >= 6, "cannot parse mountinfo")
        require(not under(unescape_mount(fields[4])), "active runtime mount")
    namespaces, namespace_fds = set(), set()
    deadline, inspected = time.monotonic() + 15, 0
    for entry in proc.iterdir():
        require(time.monotonic() < deadline and inspected < 32768, "inactive process scan time/count bound exceeded")
        if not entry.name.isdigit():
            continue
        try:
            inspected += 1
            # Local sandbox runs cannot inspect other owners; production root must.
            if local and entry.stat().st_uid != os.geteuid():
                continue
            from installer_helpers import stat_fields, inode, mounts, bounded_text
            before = stat_fields(entry)
            if before[0] == "Z":
                continue
            ns = inode(entry / "ns/mnt")
            exe_before = inode(entry / "exe")
            root_before = inode(entry / "root")
            process_root = os.readlink(entry / "root")
            require(not under(process_root), "active process rootfs")
            for m in mounts(bounded_text(entry / "mountinfo"), process_root):
                require(not under(m["target"]) and not under(m["root"]), "active runtime mount namespace")
            for node in (entry / "exe", entry / "cwd"):
                try:
                    require(not under(os.readlink(node)), "active executable/cwd")
                except FileNotFoundError:
                    pass
            for count, fd in enumerate((entry / "fd").iterdir()):
                require(count < 8192, "inactive process FD count exceeds bound")
                try:
                    value = os.readlink(fd)
                    require(not under(value), "active pinned deployment FD")
                    if value.startswith("mnt:["):
                        namespace_fds.add(inode(fd))
                except FileNotFoundError:
                    pass
            for line in bounded_text(entry / "maps").splitlines():
                fields = line.split(None, 5)
                require(len(fields) < 6 or not under(fields[5]), "active mapped runtime file")
            require(stat_fields(entry)[2] == before[2] and inode(entry / "ns/mnt") == ns and
                    inode(entry / "exe") == exe_before and inode(entry / "root") == root_before,
                    "process changed while establishing inactive state")
            namespaces.add(ns)
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            require(local, "cannot establish inactive state: unreadable /proc process")
    require(not namespace_fds - namespaces,
            "cannot establish inactive state: orphan mount namespace FD has unverifiable root ownership; kept")


def target(args):
    dest = Path(args.destination).absolute()
    if args.local_root:
        base = Path(args.local_root).absolute()
        require(dest == base / "external-asp" and base.is_dir() and
                str(base).startswith(("/tmp/", "/var/tmp/")) and
                base.stat().st_uid == os.geteuid() and base.stat().st_mode & 0o7777 == 0o700,
                "local mode requires a private existing /tmp sandbox and exact child external-asp")
    else:
        require(dest == DEST and os.geteuid() == 0, "production destination requires root at exact deployment path")
    require(dest.parent.is_dir(), "deployment parent must already exist; installer never creates/chmods it")
    for p in [dest, *dest.parents]:
        require(not p.is_symlink(), "deployment symlink forbidden")
    return dest


def read_registry(base):
    p = base / REGISTRY
    if not p.exists():
        return {"schema": "ASP2-OWNERSHIP-V1", "generations": {}}
    require(p.is_file() and not p.is_symlink() and p.stat().st_uid == os.geteuid() and
            p.stat().st_mode & 0o7777 == 0o600 and p.stat().st_nlink == 1,
            "unrecognized ownership registry")
    r = json.loads(p.read_text())
    require(isinstance(r, dict) and r.get("schema") == "ASP2-OWNERSHIP-V1" and isinstance(r.get("generations"), dict),
            "unrecognized registry schema")
    return r


def save_registry(base, registry):
    fd, name = tempfile.mkstemp(prefix=".external-asp-receipt-", dir=base)
    os.close(fd)
    p = Path(name)
    try:
        write_json(p, registry)
        with p.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(p, base / REGISTRY)
        sync_dir(base)
    finally:
        p.unlink(missing_ok=True)


@contextlib.contextmanager
def locked(base):
    path = base / ".external-asp-installer.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        st = os.fstat(fd)
        require(stat.S_ISREG(st.st_mode) and st.st_uid == os.geteuid() and
                st.st_mode & 0o7777 == 0o600 and st.st_nlink == 1, "unrecognized installer lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise ValueError("another installer owns the deployment lock") from e
        yield
    finally:
        os.close(fd)


def check_partial_removal(path):
    # Registry identity proves this inode was validated before deletion began.
    # Never follow links or cross mounts; active_check runs before any deletion.
    for base, dirs, files in os.walk(path, followlinks=False):
        for name in [".", *dirs, *files]:
            p = Path(base) / name
            st = p.lstat()
            require(st.st_uid == os.geteuid() and st.st_gid == os.geteuid(),
                    "partial removal ownership changed")
            if p.is_symlink():
                rel = p.relative_to(path / "lib/rootfs/proc").as_posix() if p.is_relative_to(path / "lib/rootfs/proc") else ""
                require(rel in ALIASES and os.readlink(p) == ALIASES[rel],
                        "partial removal unknown symlink")
            else:
                require((p.is_dir() or p.is_file()) and st.st_mode & 0o7022 == 0,
                        "partial removal unsafe inode")


def footprint(path):
    # Aggregate ownership receipt, never a per-file manifest or runtime hash policy.
    result = {"files": 0, "directories": 1, "symlinks": 0, "bytes": 0}
    for base, dirs, files in os.walk(path, followlinks=False):
        for name in [*dirs, *files]:
            p = Path(base) / name
            st = p.lstat()
            if p.is_symlink():
                result["symlinks"] += 1
            elif p.is_dir():
                result["directories"] += 1
            else:
                result["files"] += 1
                result["bytes"] += st.st_size
    return result


def generation(path, registry):
    require(path.is_dir() and not path.is_symlink(), "unrecognized/partial deployment")
    current_identity = identity(path)
    matches = [(k, v) for k, v in registry["generations"].items()
               if v["identity"] == current_identity]
    require(len(matches) == 1, "original generation ownership/inode identity not recognized")
    key, record = matches[0]
    if record.get("removal_authorized") or record.get("preparation_incomplete"):
        check_partial_removal(path)
        return key, {"mode": record["mode"], "removal_pending": bool(record.get("removal_authorized")),
                     "preparation_pending": bool(record.get("preparation_incomplete"))}
    r = validate(path, required_uid=os.geteuid())
    require(record.get("footprint") == footprint(path), "unrecognized generation content/size changed")
    require(r.get("installation_id") == key, "generation receipt identity mismatch")
    return key, r


def discover(dest, registry):
    roots = ([dest] if dest.exists() or dest.is_symlink() else [])
    roots += sorted(dest.parent.glob(PREFIX + "*"))
    result = {}
    for p in roots:
        key, r = generation(p, registry)
        require(key not in result, "duplicate generation identity")
        result[key] = {"path": str(p), "current": p == dest, "receipt": r}
    return result


def preflight_payload(payload, args):
    r = validate(payload)
    if not args.local_root:
        require(r["scope"] == "OWNER_CONFIRMED", "synthetic fixtures cannot be installed on a device")
    if r["mode"] == LIVE:
        require(args.live_vendor, "A install/dry-run requires fresh --live-vendor reference")
        vendor = Path(args.live_vendor).absolute()
        if not args.local_root:
            require(vendor == Path("/vendor") and
                    os.statvfs(vendor).f_flag & os.ST_RDONLY, "original /vendor must already be RO")
        pair(Directory(Path(payload) / "lib/rootfs/system"), Directory(vendor))
        closure(Directory(Path(payload) / "lib/rootfs/system"), Directory(vendor),
                (Path(payload) / "lib/rootfs/factory/asp2-child").read_bytes())
    return r


def dry_run(args):
    dest = target(args)
    registry = read_registry(dest.parent)
    found = discover(dest, registry)
    require(not any(v["receipt"].get("removal_pending") or v["receipt"].get("preparation_pending")
                    for v in found.values()), "finish interrupted generation removal/preparation first")
    r = preflight_payload(Path(args.payload), args)
    active_check([dest, *(Path(x["path"]) for x in found.values())], local=bool(args.local_root))
    size = sum(p.stat().st_size for p in Path(args.payload).rglob("*") if p.is_file() and not p.is_symlink())
    available = shutil.disk_usage(dest.parent).free
    require(available >= size + 16 * 1024 * 1024, "insufficient storage for staged generation")
    return {"destination": str(dest), "bytes": size, "free_bytes": available,
            "operation": "ATOMIC_EXCHANGE" if dest.exists() else "ATOMIC_RENAME_NOREPLACE",
            "current": next((k for k, v in found.items() if v["current"]), None),
            "root_ownership_required": not bool(args.local_root), "mode": r["mode"],
            "active": False, "activation": False, "parent_permissions_modified": False,
            "warning": WARNING}


def rename_atomic(source, dest, flags):
    # Linux renameat2: never replace an unexpected new root, exchange updates atomically.
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    require(rename is not None, "renameat2 unavailable; refusing non-atomic fallback")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(dest), flags):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def quiesce(args, roots):
    stop_requested = getattr(args, "stop_helpers", False)
    require(stop_requested or not (getattr(args, "force_kill", False) or getattr(args, "force_unmount", False)),
            "helper force flags require --stop-helpers")
    if stop_requested:
        from installer_helpers import stop
        stop(args, [Path(p) for p in roots if Path(p).exists()])


def install(args):
    require(args.opt_in and args.confirm_inactive, "install requires --opt-in --confirm-inactive")
    dest = target(args)
    with locked(dest.parent):
        registry = read_registry(dest.parent)
        found = discover(dest, registry)
        quiesce(args, [dest, *(Path(x["path"]) for x in found.values())])
        plan = dry_run(args)
        registry = read_registry(dest.parent)
        key = str(uuid.uuid4())
        stage = dest.parent / (PREFIX + key)
        # This process exclusively owns the freshly created stage, even before registration.
        stage.mkdir(mode=0o700)
        original = identity(stage)
        registered = False
        committed = False
        try:
            registry["generations"][key] = {"identity": original,
                "preparation_incomplete": True, "mode": plan["mode"]}
            save_registry(dest.parent, registry)
            registered = True
            shutil.copytree(args.payload, stage, dirs_exist_ok=True, symlinks=True)
            if not args.local_root:
                for base, dirs, files in os.walk(stage, followlinks=False):
                    for name in [".", *dirs, *files]:
                        os.chown(Path(base) / name, 0, 0, follow_symlinks=False)
            receipt = validate(stage, required_uid=os.geteuid())
            receipt["installation_id"] = key
            write_json(stage / RECEIPT, receipt)
            validate(stage, required_uid=os.geteuid())
            sync_tree(stage)
            # Register before publication. Hard interruption leaves an identifiable inactive
            # candidate or an old generation at stage; status discovers actual inode identities.
            registry["generations"][key] = {"identity": identity(stage), "footprint": footprint(stage)}
            save_registry(dest.parent, registry)
            registered = True
            found = discover(dest, registry)
            active_check([dest, stage, *(Path(x["path"]) for x in found.values())],
                         local=bool(args.local_root))
            if plan["current"]:
                require(generation(dest, registry)[0] == plan["current"], "current generation changed")
                rename_atomic(stage, dest, 2)  # RENAME_EXCHANGE
            else:
                rename_atomic(stage, dest, 1)  # RENAME_NOREPLACE
            committed = True
            sync_dir(dest.parent)
            return {"installed": key, "previous": plan["current"],
                    "activation": False, "destination": str(dest), "warning": WARNING}
        finally:
            incomplete = registry["generations"].get(key, {}).get("preparation_incomplete")
            if not committed and (not registered or incomplete) and stage.exists() and identity(stage) == original:
                shutil.rmtree(stage)
                if registered:
                    del registry["generations"][key]
                    save_registry(dest.parent, registry)
                sync_dir(dest.parent)
            # Once registered, retain on any error for status/rollback/uninstall;
            # no uncertain deletion after a failed atomic operation.


def status(args):
    dest = target(args)
    registry = read_registry(dest.parent)
    found = discover(dest, registry)
    inactive, reason = True, None
    try:
        active_check([dest, *(Path(x["path"]) for x in found.values())], local=bool(args.local_root))
    except Refusal as e:
        inactive, reason = False, str(e)
    return {"installed": dest.exists(), "inactive": inactive, "activity_or_blocker": reason, "generations": {
        k: {"path": v["path"], "current": v["current"], "mode": v["receipt"]["mode"],
            "removal_pending": v["receipt"].get("removal_pending", False),
            "preparation_pending": v["receipt"].get("preparation_pending", False)}
        for k, v in found.items()}, "activation_managed": False, "warning": WARNING}


def rollback(args):
    require(args.opt_in and args.confirm_inactive and args.generation,
            "rollback requires explicit --generation --opt-in --confirm-inactive")
    dest = target(args)
    with locked(dest.parent):
        registry = read_registry(dest.parent)
        found = discover(dest, registry)
        quiesce(args, [dest, *(Path(x["path"]) for x in found.values())])
        require(args.generation in found and not found[args.generation]["current"],
                "rollback generation missing or already current")
        require(not (found[args.generation]["receipt"].get("removal_pending") or
                     found[args.generation]["receipt"].get("preparation_pending")), "generation is incomplete or being removed")
        old = Path(found[args.generation]["path"])
        preflight_payload(old, args)
        active_check([dest, *(Path(x["path"]) for x in found.values())], local=bool(args.local_root))
        rename_atomic(old, dest, 2 if dest.exists() else 1)
        sync_dir(dest.parent)
        return {"rolled_back_to": args.generation, "activation": False}


def uninstall(args):
    require(args.opt_in and args.confirm_inactive and args.generation,
            "uninstall requires explicit --generation --opt-in --confirm-inactive")
    dest = target(args)
    with locked(dest.parent):
        registry = read_registry(dest.parent)
        found = discover(dest, registry)
        quiesce(args, [dest, *(Path(x["path"]) for x in found.values())])
        require(args.generation in found, "unrecognized generation; nothing removed")
        victim = Path(found[args.generation]["path"])
        active_check([dest, *(Path(x["path"]) for x in found.values())], local=bool(args.local_root))
        _, old_receipt = generation(victim, registry)
        registry["generations"][args.generation].update(
            removal_authorized=True, mode=old_receipt["mode"])
        save_registry(dest.parent, registry)
        # Detach the recognized inode first; interrupted removal retains registry and
        # unique private path, never broad glob deletion or a user-data parent removal.
        if victim == dest:
            trash = dest.parent / (PREFIX + str(uuid.uuid4()))
            rename_atomic(victim, trash, 1)
            victim = trash
            sync_dir(dest.parent)
        shutil.rmtree(victim)
        del registry["generations"][args.generation]
        save_registry(dest.parent, registry)
        return {"removed": args.generation, "activation": False}
