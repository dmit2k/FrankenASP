#!/usr/bin/env python3
"""Read-only extraction of the *original* Athena FireOS 9 ARM32 ELF dependency closure.
No mounts, no writes to the source backup, no execution of extracted ARM ELF files.
"""
import hashlib
import json
import re
import subprocess
from collections import deque
import argparse
from pathlib import Path

ROOT = SYSTEM = VENDOR = None  # initialized from mandatory CLI paths

DIRECTORIES = [
    ("vendor", "/lib", "/vendor/lib"),
    ("vendor", "/lib/vndk", "/vendor/lib/vndk"),
    ("vendor", "/lib/vndk-sp", "/vendor/lib/vndk-sp"),
    ("system", "/system/lib", "/system/lib"),
    ("system", "/system/lib/vndk-28", "/system/lib/vndk-28"),
    ("system", "/system/lib/vndk-sp-28", "/system/lib/vndk-sp-28"),
]
SPECIAL = [
    ("system", "/system/bin/linker", "/system/bin/linker"),
    ("system", "/system/bin/sh", "/system/bin/sh"),
    ("system", "/system/etc/ld.config.28.txt", "/system/etc/ld.config.28.txt"),
    ("system", "/system/etc/public.libraries.txt", "/system/etc/public.libraries.txt"),
    ("system", "/system/etc/public.libraries-AMAZON.txt", "/system/etc/public.libraries-AMAZON.txt"),
    ("system", "/system/build.prop", "/system/build.prop"),
    ("vendor", "/build.prop", "/vendor/build.prop"),
    ("vendor", "/default.prop", "/vendor/default.prop"),
    ("vendor", "/lib/libasp.so", "/vendor/lib/libasp.so"),
]
SO_LIBS_SYSTEM = {"libc.so", "libdl.so", "libm.so", "liblog.so",
                  "libEGL.so", "libGLESv2.so", "libvndksupport.so",
                  "libsync.so", "libnativewindow.so"}
NO_ELF = {".txt", ".prop"}

def proc(*args):
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode:
        raise RuntimeError(f"{args}: {p.stderr[-250:]}")
    return p.stdout

def image(name):
    return str(SYSTEM if name == "system" else VENDOR)

def inventory():
    lookup = {}
    for part, srcdir, target in DIRECTORIES:
        out = proc("debugfs", "-R", "ls -p " + srcdir, image(part))
        for line in out.splitlines():
            match = re.match(r"^/\d+/([0-9]{6})/\d+/\d+/(.+?)/(\d+)/$", line.strip())
            if not match or not match.group(1).startswith("10"):
                continue
            name = match.group(2)
            lookup.setdefault(name, []).append((part, srcdir + "/" + name, target + "/" + name, int(match.group(3))))
    return lookup

def extract(part, src, target):
    out = ROOT / target.lstrip("/")
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        proc("debugfs", "-R", f"dump {src} {out}", image(part))
    if not out.is_file() or not out.stat().st_size:
        raise RuntimeError(f"empty extraction: {part} {src}")
    # debugfs dump does not preserve executable mode; factory image has both as 0755.
    if target in ("/system/bin/linker", "/system/bin/sh"):
        out.chmod(0o755)
    return out

def needed(path):
    try:
        txt = proc("readelf", "-d", str(path))
    except RuntimeError:
        return []
    return re.findall(r"\(NEEDED\).*?Shared library: \[(.*?)\]", txt)

def select(name, parent, lookup):
    entries = lookup.get(name, [])
    if not entries:
        return None, []
    def rank(e):
        part, src, path, _ = e
        if name in SO_LIBS_SYSTEM:
            return (0 if path.startswith("/system/lib/") and "/vndk" not in path else 9, path)
        if parent.startswith("/vendor"):
            order = ["/vendor/lib/", "/system/lib/vndk-sp-28/", "/system/lib/vndk-28/", "/system/lib/"]
        elif "/vndk" in parent:
            order = ["/system/lib/vndk-sp-28/", "/system/lib/vndk-28/", "/system/lib/", "/vendor/lib/"]
        else:
            order = ["/system/lib/", "/system/lib/vndk-sp-28/", "/system/lib/vndk-28/", "/vendor/lib/"]
        try:
            return (next(idx for idx, d in enumerate(order) if path.startswith(d)), path)
        except StopIteration:
            return (99, path)
    selected = min(entries, key=rank)
    return selected, [e[2] for e in entries]

def main():
    global ROOT, SYSTEM, VENDOR
    parser = argparse.ArgumentParser(description="Extract factory ARM32 dependencies from the owner's verified FireOS partition backups")
    parser.add_argument("--system-image", required=True, type=Path)
    parser.add_argument("--vendor-image", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    SYSTEM, VENDOR, ROOT = args.system_image.resolve(), args.vendor_image.resolve(), args.output.resolve()
    for image in (SYSTEM, VENDOR):
        if not image.is_file() or not image.stat().st_size:
            parser.error(f"missing or empty backup image: {image}")
    ROOT.mkdir(parents=True, exist_ok=True)
    lookup = inventory()
    items = []
    for part, src, target in SPECIAL:
        out = extract(part, src, target)
        items.append(dict(path=target, source_partition=part,
                          bytes=out.stat().st_size, sha256=hashlib.sha256(out.read_bytes()).hexdigest()))
    queue = deque(["/vendor/lib/libasp.so"])
    seen, unresolved, decisions, edges = set(), set(), [], []
    while queue:
        parent = queue.popleft()
        if parent in seen:
            continue
        seen.add(parent)
        for soname in needed(ROOT / parent.lstrip("/")):
            selected, candidates = select(soname, parent, lookup)
            if not selected:
                unresolved.add(soname)
                edges.append(dict(parent=parent, soname=soname, target=None))
                continue
            part, src, target, _ = selected
            dst = extract(part, src, target)
            edges.append(dict(parent=parent, soname=soname, target=target))
            if len(candidates) > 1:
                decisions.append(dict(parent=parent, soname=soname, selected=target, alternate_paths=candidates))
            if target not in {v["path"] for v in items}:
                items.append(dict(path=target, source_partition=part,
                                  bytes=dst.stat().st_size, sha256=hashlib.sha256(dst.read_bytes()).hexdigest()))
            if target not in seen:
                queue.append(target)
            if len(items) > 220:
                raise RuntimeError("dependency closure exceeded safe limit of 220 extracted objects")
    report = dict(source='user-supplied partition backups', copied_files=items,
                  edges=edges, ambiguous_candidates=decisions,
                  missing_sonames=sorted(unresolved), count=len(items),
                  total_bytes=sum(x["bytes"] for x in items))
    (ROOT / "ORIGINAL_ELF_CLOSURE.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(dict(count=report["count"], total_bytes=report["total_bytes"],
                          dependency_edges=len(edges), missing_sonames=report["missing_sonames"],
                          ambiguous_candidates=decisions[:18],
                          copied=[x["path"] for x in items]), indent=2))
    if unresolved:
        raise SystemExit(2)

if __name__ == "__main__":
    main()
