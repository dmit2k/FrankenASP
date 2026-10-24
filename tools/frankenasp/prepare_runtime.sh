#!/usr/bin/env bash
# Prepare an owner-local staging tree only. Never modifies an original factory image.
set -euo pipefail
if (( $# != 2 )); then
    echo "Usage: $0 /path/to/extracted/runtime /path/to/self-built/libasp_stream_worker.so" >&2
    exit 2
fi
ROOT="$1"
WORKER="$2"
DEVICE_PREFIX="/data/techo5-linux/amazon-arm32"
command -v readelf >/dev/null || { echo "readelf required" >&2; exit 2; }
command -v patchelf >/dev/null || { echo "patchelf required" >&2; exit 2; }
for rel in system/bin/sh system/bin/linker system/lib/libc.so vendor/lib/libasp.so; do
    [[ -s "$ROOT/$rel" ]] || { echo "Missing owner-local: $rel" >&2; exit 2; }
done
[[ -s "$WORKER" ]] || { echo "Missing self-built worker" >&2; exit 2; }
for f in "$ROOT/system/bin/sh" "$ROOT/system/bin/linker" "$WORKER"; do
    readelf -h "$f" | grep -q 'Class:.*ELF32' ||
        { echo "Expected ELF32: $f" >&2; exit 3; }
    readelf -h "$f" | grep -q 'Machine:.*ARM' ||
        { echo "Expected ARM ELF: $f" >&2; exit 3; }
done
# Keep the factory shell untouched. Prepare an isolated copy with device-local interpreter.
patchelf --set-interpreter "$DEVICE_PREFIX/system/bin/linker"     --output "$ROOT/system/bin/sh-native" "$ROOT/system/bin/sh"
chmod 0755 "$ROOT/system/bin/sh-native" "$ROOT/system/bin/linker"
cp -- "$WORKER" "$ROOT/libasp_stream_worker.so"
chmod 0755 "$ROOT/libasp_stream_worker.so"
readelf -l "$ROOT/system/bin/sh-native" |
    grep -F "$DEVICE_PREFIX/system/bin/linker" >/dev/null ||
    { echo "ELF interpreter check failed" >&2; exit 3; }
if readelf --version-info "$ROOT/libasp_stream_worker.so" |
    grep -q 'GLIBC_'; then
    echo "A glibc-linked worker cannot run with Bionic" >&2
    exit 3
fi
printf 'Local staging complete: %s\n' "$ROOT"
printf 'Only owner-private payloads live in this directory. Do NOT git add or publish it.\n'
printf 'No device files or services were touched.\n'
