#!/usr/bin/env sh
# Read-only diagnosis. A persistent marker is a REQUEST, not evidence of active ASP.
set -eu
ROOT=/data/techo5-linux
FLAG="$ROOT/fireos-asp.enabled"
[ -e "$FLAG" ] && requested=yes || requested=no
printf 'requested=%s\n' "$requested"
[ -e /run/techo5/frankenasp-armed ] && armed=yes || armed=no
printf 'tmpfs_armed=%s\n' "$armed"
found=no
for p in /proc/[0-9]*; do
    [ -r "$p/maps" ] || continue
    # The active worker must actually map both native ASP and our worker.
    if grep -q '/libasp_stream_worker.so' "$p/maps" 2>/dev/null &&
       grep -q '/libasp.so' "$p/maps" 2>/dev/null; then
        found=yes
        printf 'worker_pid=%s\n' "$(basename "$p")"
        break
    fi
done
printf 'native_asp_mapped=%s\n' "$found"
[ "$requested" = yes ] && [ "$armed" = yes ] && [ "$found" = yes ] && exit 0
exit 1
