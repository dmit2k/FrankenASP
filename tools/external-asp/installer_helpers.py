"""Explicit scoped helper control. No service API, host kill, or global unmount."""
import ctypes
import errno
import json
import os
from pathlib import Path
import select
import signal
import stat
import subprocess
import sys
import time

from installer_sources import Refusal, require, elf, LIVE, BUNDLE

PROC = Path("/proc")
WAIT = 2.0
SETTLE = .5


def inode(path):
    st = Path(path).stat()
    return (st.st_dev, st.st_ino)


def link(path):
    return os.readlink(path).removesuffix(" (deleted)")


def under(value, root):
    return value == str(root) or value.startswith(str(root) + "/")


def secure(path, directory=False):
    path = Path(path)
    st = path.lstat()
    require(not path.is_symlink() and st.st_uid == os.geteuid() and st.st_mode & 0o7022 == 0 and
            (stat.S_ISDIR(st.st_mode) if directory else stat.S_ISREG(st.st_mode)),
            "untrusted helper ownership/type/permissions: " + str(path))
    return inode(path)


def bounded_text(path, limit=8 * 1024**2):
    with Path(path).open("r") as stream:
        value = stream.read(limit + 1)
    require(len(value) <= limit, "process metadata exceeds inspection bound")
    return value


def stat_fields(entry):
    text = bounded_text(entry / "stat", 8192)
    tail = text[text.rindex(")") + 2:].split()
    require(len(tail) >= 20, "unreadable/malformed process stat")
    return tail[0], int(tail[1]), int(tail[19])


def snapshot(entry):
    state, parent, start = stat_fields(entry)
    if state == "Z":
        return None
    value = {"pid": int(entry.name), "ppid": parent, "start": start,
             "exe": inode(entry / "exe"), "exe_path": link(entry / "exe"),
             "namespace": inode(entry / "ns/mnt"), "root": inode(entry / "root"),
             "root_path": link(entry / "root"), "cwd": link(entry / "cwd"),
             "comm": bounded_text(entry / "comm", 256).strip(), "fds": {}, "fd_ids": {}}
    for count, fd in enumerate((entry / "fd").iterdir()):
        require(count < 8192, "process FD count exceeds inspection bound")
        try:
            value["fds"][fd.name] = link(fd)
            value["fd_ids"][fd.name] = inode(fd)
        except FileNotFoundError:
            continue
    value["maps"] = bounded_text(entry / "maps")
    value["mountinfo"] = bounded_text(entry / "mountinfo")
    require(stat_fields(entry)[2] == start and inode(entry / "exe") == value["exe"] and
            inode(entry / "ns/mnt") == value["namespace"], "process changed during inspection")
    return value


def mounts(text, root_path="/"):
    from installer_deploy import unescape_mount
    result = []
    for line in text.splitlines():
        f = line.split()
        require(len(f) >= 10 and "-" in f, "cannot parse mountinfo")
        sep = f.index("-")
        require(sep >= 6 and len(f) >= sep + 4, "cannot parse mountinfo separator")
        target = unescape_mount(f[4])
        if root_path != "/":
            target = str(Path(root_path) / target.lstrip("/"))
        result.append({"id": int(f[0]), "target": target, "root": unescape_mount(f[3]),
                       "options": f[5].split(","), "propagation": f[6:sep],
                       "fstype": f[sep + 1], "source": unescape_mount(f[sep + 2])})
    return result


def owned_roots(args):
    from installer_deploy import target, read_registry, discover
    dest = target(args)
    found = discover(dest, read_registry(dest.parent))
    return [Path(v["path"]) for v in found.values()]


def scan(roots, proc=PROC, local=False, host_paths=()):
    """Return evidence and blockers. Names are labels, never kill authority."""
    roots = [Path(r).absolute() for r in roots]
    trusted, blocked, processes = {}, [], {}
    for root in roots:
        secure(root, True)
        for sub, role in (("bin/external-asp", "linux-launcher"),
                          ("lib/rootfs/factory/asp2-child", "bionic-child")):
            p = root / sub
            if p.exists():
                trusted[secure(p)] = (str(root), role)
    hosts = {secure(Path(p)): str(Path(p).absolute()) for p in host_paths}
    self_ns = inode(proc / "self/ns/mnt")
    deadline, inspected, metadata_bytes = time.monotonic() + 15, 0, 0
    for entry in proc.iterdir():
        require(time.monotonic() < deadline and inspected < 32768, "process scan time/count bound exceeded")
        if not entry.name.isdigit():
            continue
        try:
            if local and entry.stat().st_uid != os.geteuid():
                continue
            value = snapshot(entry)
            inspected += 1
            if value:
                metadata_bytes += len(value["maps"]) + len(value["mountinfo"]) + sum(map(len, value["fds"].values()))
                require(metadata_bytes <= 128 * 1024**2, "process metadata exceeds 128MiB scan bound")
                processes[value["pid"]] = value
        except (FileNotFoundError, ProcessLookupError):
            continue
        except (OSError, ValueError) as e:
            blocked.append({"pid": int(entry.name), "reason": "unreadable/unstable process state: " + type(e).__name__})
    visible_namespaces = {self_ns, *(p["namespace"] for p in processes.values())}
    if roots or hosts:
        for p in processes.values():
            for number, value in p["fds"].items():
                ns = p["fd_ids"].get(number)
                if value.startswith("mnt:[") and ns not in visible_namespaces:
                    blocked.append({"pid": p["pid"], "fd": number,
                                    "reason": "orphan mount namespace FD has unverifiable root ownership; kept, no cleanup guessed"})
    targets, host_records, unrelated = [], [], []
    for p in processes.values():
        match = trusted.get(p["exe"])
        role = None
        if match:
            root, role = match
            # The executable inode and deployment directory must still match now.
            role = "orphan-" + role if p["ppid"] not in processes or p["ppid"] == 1 else role
            provenance = "installer-owned executable inode"
        else:
            # R1 FD3 executable + FD4 asset-root + verified selected host parent
            # and both actual IPC pipes support helpers outside our current generation.
            parent = processes.get(p["ppid"])
            fd_launch = p["fd_ids"].get("3") == p["exe"] and "4" in p["fds"]
            child_suffix = "/lib/rootfs/factory/asp2-child"
            bionic_child = p["exe_path"].endswith(child_suffix)
            if parent and parent["exe"] in hosts and (fd_launch or bionic_child):
                try:
                    if fd_launch:
                        root = p["fds"]["4"]
                        secure(root, True)
                        require(p["fd_ids"]["4"] == inode(root) and
                                p["exe"] == secure(Path(root) / "bin/external-asp"),
                                "R1 FD3/FD4 executable/root mismatch")
                        role = "r1-external-helper"
                    else:
                        root = p["exe_path"][:-len(child_suffix)]
                        for sub in ("", "lib", "lib/rootfs", "lib/rootfs/factory", "etc"):
                            secure(Path(root) / sub, True)
                        child = Path(root) / "lib/rootfs/factory/asp2-child"
                        require(p["exe"] == secure(child) and p["root"] == inode(Path(root) / "lib/rootfs") and
                                p["namespace"] != self_ns, "R1 Bionic child/root/namespace mismatch")
                        require(child.stat().st_size <= 1024**2, "oversized R1 Bionic helper")
                        elf(child.read_bytes(), "/system/bin/linker")
                        from installer_payload import profile
                        cfg = Path(root) / "etc/launcher.profile"
                        secure(cfg)
                        require(cfg.stat().st_size < 1024 and cfg.read_bytes() in (profile(LIVE), profile(BUNDLE)),
                                "R1 child lacks exact launcher profile")
                        role = "r1-bionic-child"
                    input_pipe = p["fds"].get("0", "")
                    parent_pipes = set(parent["fds"].values())
                    # I1 duplicates protocol stdout before redirecting FD1 to
                    # diagnostic stderr. The live wire may therefore be FD3+.
                    outputs = [v for number, v in p["fds"].items() if number not in ("0", "2") and
                               v.startswith("pipe:[") and v != input_pipe and v in parent_pipes]
                    require(input_pipe.startswith("pipe:[") and input_pipe in parent_pipes and outputs,
                            "R1 parent does not own distinct helper input/protocol pipes")
                    provenance = "selected R1 host inode + parent + pinned executable/root + IPC pipes"
                except (OSError, ValueError):
                    role = None
                    blocked.append({"pid": p["pid"], "reason": "ambiguous R1 executable/root/FD/parent provenance"})
        if role:
            target = {**p, "root_generation": root, "role": role, "provenance": provenance}
            target["mounts"] = mounts(p["mountinfo"], p["root_path"])
            target["private_namespace"] = p["namespace"] != self_ns
            targets.append(target)
            parent = processes.get(p["ppid"])
            if parent and parent["exe"] not in trusted:
                host_records.append({"pid": parent["pid"], "exe": parent["exe_path"],
                                     "role": "external-helper-parent; preserved",
                                     "selected_r1_host": parent["exe"] in hosts})
        elif p["exe"] in hosts:
            host_records.append({"pid": p["pid"], "exe": p["exe_path"], "role": "selected-r1-host; preserved"})
        elif p["comm"].startswith("techo5"):
            host_records.append({"pid": p["pid"], "exe": p["exe_path"], "role": "stock-or-unattributed-TECHO5; preserved"})
        elif "external-asp" in p["comm"]:
            unrelated.append({"pid": p["pid"], "reason": "unattributed name; never signalled"})
    return {"targets": targets, "hosts": host_records, "unrelated": unrelated,
            "blocked": blocked, "processes": processes, "self_namespace": self_ns,
            "control_interface": "No authenticated local R1 selector interface implemented; choose Built-in using the existing owner UI before maintenance."}


def public_plan(plan):
    return {k: v for k, v in plan.items() if k not in ("processes", "self_namespace")} | {
        "targets": [{k: v for k, v in p.items() if k not in ("maps", "mountinfo", "fds", "fd_ids")}
                    for p in plan["targets"]]}


def same(p, proc=PROC):
    try:
        q = snapshot(proc / str(p["pid"]))
        if q is None:
            return False
        require(all(q[k] == p[k] for k in ("start", "exe", "namespace", "root", "ppid")),
                "PID/executable/parent/namespace identity changed; no signal sent")
        return True
    except (FileNotFoundError, ProcessLookupError):
        return False


class Handle:
    def __init__(self, p, proc=PROC):
        self.p, self.proc, self.fd = p, proc, None
        if not same(p, proc):
            return
        if proc == PROC and hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
            try:
                self.fd = os.pidfd_open(p["pid"], 0)
            except OSError as e:
                if e.errno == errno.ESRCH:
                    return
                if e.errno not in (errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP):
                    raise
        try:
            if not same(p, proc):
                self.close()
        except BaseException:
            self.close()
            raise

    def send(self, sig):
        if not same(self.p, self.proc):
            return False
        try:
            if self.fd is not None:
                signal.pidfd_send_signal(self.fd, sig)
            else:
                # Old kernels: immediate starttime/executable/namespace revalidation.
                os.kill(self.p["pid"], sig)
        except ProcessLookupError:
            return False
        return True

    def alive(self):
        if self.fd is not None and select.select([self.fd], [], [], 0)[0]:
            return False
        return same(self.p, self.proc)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def pins_generation(p, root):
    values = [p["exe_path"], p["cwd"], p["root_path"], *p["fds"].values()]
    values += [f[5] for line in p["maps"].splitlines() if len(f := line.split(None, 5)) == 6]
    return any(under(value.removesuffix(" (deleted)"), root) for value in values)


def cleanup_plan(p, plan, roots, proc=PROC):
    require(p["private_namespace"], "BLOCKED: host namespace is never a cleanup target")
    root = Path(p["root_generation"]) / "lib/rootfs"
    require(Path(p["root_generation"]) in roots and secure(root, True) == inode(root),
            "BLOCKED: cleanup requires installer-owned rootfs")
    require(p["root_path"] in ("/", str(root)), "BLOCKED: unknown chroot")
    allowed = {str(root): None, **{str(root / x): kind for x, kind in
               (("system", None), ("vendor", None), ("sys", "sysfs"),
                (".realproc", "proc"), ("proc", "proc"), ("dev", "tmpfs"), ("data", "tmpfs"))}}
    selected = [m for m in p["mounts"] if under(m["target"], root)]
    require(selected, "BLOCKED: private namespace has no verified owned mounts")
    for m in selected:
        require(m["target"] in allowed and not m["propagation"] and
                (allowed[m["target"]] is None or m["fstype"] == allowed[m["target"]]),
                "BLOCKED: unknown/protected/shared private mount")
        require(m["target"] in (str(root / "dev"), str(root / "data")) or "ro" in m["options"],
                "BLOCKED: expected read-only rootfs bind")
    require(len({m["target"] for m in selected}) == len(selected), "BLOCKED: stacked mounts")
    # Verify bind targets still resolve to the installer-owned source inodes.
    for m in selected:
        suffix = Path(m["target"]).relative_to(root).as_posix()
        if suffix not in (".", "system", "vendor"):
            require(m["root"] == "/" and m["source"] == m["fstype"],
                    "BLOCKED: unknown pseudo-filesystem mount origin")
            continue
        source = root if suffix == "." else root / suffix
        if suffix == "vendor":
            from installer_payload import profile
            cfg = Path(p["root_generation"]) / "etc/launcher.profile"
            require(cfg.is_file(), "BLOCKED: vendor mode profile missing")
            mode = cfg.read_bytes()
            require(mode in (profile(LIVE), profile(BUNDLE)), "BLOCKED: unknown vendor mode")
            if mode == profile(LIVE):
                source = Path("/vendor")
        viewed = Path(m["target"]).relative_to(p["root_path"]) if p["root_path"] != "/" else Path(m["target"]).relative_to("/")
        observed = proc / str(p["pid"]) / "root" / viewed
        require(inode(observed) == inode(source), "BLOCKED: foreign rootfs/system/vendor bind source")
    # No unrelated namespace or filesystem owner may be disrupted by unmounting.
    target_pids = {x["pid"] for x in plan["targets"]}
    require(not any(q["pid"] not in target_pids and
                    (q["namespace"] == p["namespace"] or pins_generation(q, Path(p["root_generation"])))
                    for q in plan["processes"].values()), "BLOCKED: private namespace/rootfs has another owner")
    return sorted(selected, key=lambda m: (m["target"].count("/"), m["target"]), reverse=True)


def namespace_users(plan, ns, exclude=()):
    return [p["pid"] for p in plan["processes"].values()
            if p["pid"] not in exclude and
            (p["namespace"] == ns or ns in p["fd_ids"].values())]


def pin_namespace_root(p, proc=PROC):
    """Pin the namespace's host-root mount before its last process exits.

    setns alone does not replace fs->root/cwd. A helper may already be chrooted;
    walk its verified mount path back to the namespace root while still using
    the observer's unrestricted root. Never infer an arbitrary orphan root.
    """
    fd = os.open(proc / str(p["pid"]) / "root", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        depth = len(Path(p["root_path"]).parts) - 1
        require(0 <= depth <= 128, "private namespace root depth exceeds bound")
        for _ in range(depth):
            parent = os.open("..", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = parent
        st = os.fstat(fd)
        require((st.st_dev, st.st_ino) == inode("/") and same(p, proc),
                "BLOCKED: cannot verify private namespace root anchor")
        return fd
    except BaseException:
        os.close(fd)
        raise


def run_cleanup(fd, namespace, expected, root, anchor_fd):
    """A separate process enters the pinned namespace; parent namespace never changes."""
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "_cleanup",
               str(fd), json.dumps(namespace), json.dumps(expected), str(root), str(anchor_fd)]
    result = subprocess.run(command, pass_fds=(fd, anchor_fd), capture_output=True, text=True, timeout=8)
    require(result.returncode == 0, "private cleanup failed: " + result.stderr.strip())
    return json.loads(result.stdout)


def cleanup_child(fd, namespace, expected, root, anchor_fd):
    require(inode("/proc/self/ns/mnt") != tuple(namespace) and inode("/proc/self/fd/" + str(fd)) == tuple(namespace),
            "cleanup refuses host/changed namespace")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.setns(fd, 0x00020000):
        raise OSError(ctypes.get_errno(), "setns refused")
    # Enter the pinned root mount from THAT namespace, not the inherited root
    # mount reference from the parent namespace. All later targets are absolute
    # below the known owned generation in this private namespace.
    os.fchdir(anchor_fd)
    os.chroot(".")
    os.chdir("/")
    def owned():
        return sorted([m for m in mounts(Path("/proc/self/mountinfo").read_text())
                       if under(m["target"], root)],
                      key=lambda m: (m["target"].count("/"), m["target"]), reverse=True)
    require(owned() == expected, "private mounts changed before cleanup")
    done = []
    for m in expected:
        require(owned() == expected[len(done):], "private mount changed during cleanup")
        raw = os.fsencode(m["target"])
        detached = False
        if libc.umount2(raw, 0):
            require(libc.umount2(raw, 2) == 0, "normal unmount and MNT_DETACH failed for owned target")
            detached = True
        done.append({"target": m["target"], "detached": detached})
    require(not owned(), "private mount leak after cleanup")
    return done


def stop(args, roots, proc=PROC, scanner=scan, handle_type=Handle, cleanup=run_cleanup):
    require(args.opt_in, "helpers stop requires --opt-in")
    require(getattr(args, "maintenance_ack", False),
            "helpers stop requires --maintenance-ack: select Built-in and prevent new external requests during maintenance")
    host_paths = getattr(args, "r1_host", ())
    local = bool(args.local_root)
    plan = scanner(roots, proc, local, host_paths)
    require(not plan["blocked"], "BLOCKED: unreadable/ambiguous process state; inspect helpers status")
    require(len(plan["targets"]) <= 256, "helper target count exceeds bound")
    # Make the concrete plan visible before any signal or mount action.
    print(json.dumps(public_plan(plan), sort_keys=True), file=sys.stderr)
    handles, namespaces, signals_sent, cleanup_results = [], {}, [], []
    try:
        if getattr(args, "force_unmount", False):
            for p in plan["targets"]:
                if not p["private_namespace"] or not any(under(m["target"], Path(p["root_generation"]) / "lib/rootfs") for m in p["mounts"]):
                    continue
                ns = tuple(p["namespace"])
                if ns in namespaces:
                    continue
                expected = cleanup_plan(p, plan, roots, proc)
                fd = os.open(proc / str(p["pid"]) / "ns/mnt", os.O_RDONLY | os.O_CLOEXEC)
                try:
                    anchor_fd = pin_namespace_root(p, proc)
                except BaseException:
                    os.close(fd)
                    raise
                namespaces[ns] = (fd, expected, str(Path(p["root_generation"]) / "lib/rootfs"), anchor_fd)
                require(inode(proc / str(p["pid"]) / "ns/mnt") == ns and same(p, proc),
                        "namespace/helper identity changed during pin")
        for p in plan["targets"]:
            if same(p, proc):
                handles.append(handle_type(p, proc))
        # Signal only exact verified PIDs, deepest descendants first; never a group.
        def depth(handle):
            number, seen = handle.p["pid"], set()
            while number in plan["processes"] and number not in seen:
                seen.add(number)
                number = plan["processes"][number]["ppid"]
            return len(seen)
        for h in sorted(handles, key=depth, reverse=True):
            if h.send(signal.SIGTERM) is not False:
                signals_sent.append({"pid": h.p["pid"], "signal": "SIGTERM"})
        def wait():
            deadline = time.monotonic() + WAIT
            while time.monotonic() < deadline:
                live = [h for h in handles if h.alive()]
                if not live:
                    return []
                time.sleep(.02)
            return [h for h in handles if h.alive()]
        live = wait()
        if live and getattr(args, "force_kill", False):
            for h in live:
                if h.send(signal.SIGKILL) is not False:
                    signals_sent.append({"pid": h.p["pid"], "signal": "SIGKILL"})
            live = wait()
        require(not live, "helpers still alive; no generation mutation/cleanup (optional --force-kill)")
        # Rescanning deliberately does not kill respawns or newly observed processes.
        latest = scanner(roots, proc, local, host_paths)
        require(not latest["blocked"] and not latest["targets"], "BLOCKED: helper restarted or state became ambiguous")
        for ns, (fd, expected, root, anchor_fd) in namespaces.items():
            require(not namespace_users(latest, ns, (os.getpid(),)), "BLOCKED: namespace pinned by another owner")
            cleanup_results += cleanup(fd, ns, expected, root, anchor_fd)
        # Closing our namespace pins releases any remaining namespace resources.
    finally:
        for h in handles:
            h.close()
        for fd, _, _, anchor_fd in namespaces.values():
            os.close(anchor_fd)
            os.close(fd)
    time.sleep(SETTLE)
    latest = scanner(roots, proc, local, host_paths)
    require(not latest["blocked"] and not latest["targets"], "BLOCKED: helper respawned after stop")
    from installer_deploy import active_check
    checked_roots = list(dict.fromkeys([*roots, *(Path(p["root_generation"]) for p in plan["targets"])]))
    active_check(checked_roots, proc, local)
    return {"stopped": True, "signals": signals_sent, "private_cleanup": cleanup_results,
            "host_processes_preserved": True, "activation": False}


def helpers(args):
    roots = owned_roots(args)
    if args.helper_command == "status":
        return public_plan(scan(roots, local=bool(args.local_root), host_paths=args.r1_host))
    from installer_deploy import locked, target
    with locked(target(args).parent):
        return stop(args, roots)


if __name__ == "__main__" and len(sys.argv) == 7 and sys.argv[1] == "_cleanup":
    try:
        print(json.dumps(cleanup_child(int(sys.argv[2]), json.loads(sys.argv[3]),
                                       json.loads(sys.argv[4]), sys.argv[5], int(sys.argv[6]))))
    except (OSError, ValueError) as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)
