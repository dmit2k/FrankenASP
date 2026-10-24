#!/usr/bin/env python3
"""Extract original factory audio-algorithms from p12-vendor.img (read-only source)."""
import hashlib
import json
import re
import subprocess
from pathlib import Path
import argparse
args_parser = argparse.ArgumentParser(description="Extract owner-supplied FireOS ASP audio configurations")
args_parser.add_argument("--vendor-image", required=True, type=Path)
args_parser.add_argument("--output", required=True, type=Path, help="ARM32 runtime root")
args = args_parser.parse_args()
P = args.vendor_image.resolve()
OUT = args.output.resolve() / "vendor/etc/audio-algorithms"
if not P.is_file() or not P.stat().st_size:
    args_parser.error(f"missing or empty vendor backup: {P}")
def debugfs(command):
    p = subprocess.run(["debugfs", "-R", command, str(P)], capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr[-300:])
    return p.stdout
OUT.mkdir(parents=True, exist_ok=True)
manifest = []
for line in debugfs("ls -p /etc/audio-algorithms").splitlines():
    match = re.match(r"^/\d+/(100[0-7]{3})/\d+/\d+/(.+?)/(\d+)/$", line.strip())
    if not match:
        continue
    name = match.group(2)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise RuntimeError(f"unsafe factory filename: {name!r}")
    target = OUT / name
    if not target.exists():
        debugfs("dump /etc/audio-algorithms/" + name + " " + str(target))
    if target.stat().st_size != int(match.group(3)):
        raise RuntimeError("size mismatch " + name)
    hashval = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest.append(dict(name=name, size=target.stat().st_size,
                         sha256=hashval))
report = dict(source="user-supplied vendor backup", files=manifest, count=len(manifest))
(OUT.parent / "ORIGINAL_AUDIO_CFG_SHA256.json").write_text(json.dumps(report, indent=2)+"\n")
print(json.dumps(dict(count=report["count"], total_bytes=sum(x["size"] for x in manifest),
                      important=[x for x in manifest if x["name"] in ("asp.cfg","AFE.cfg","vad_lite.tflite","coefs_FBFV2_LowLatency_8beams.cfg")]), indent=2))
