#!/bin/sh
# Boot-scoped 120s probation. Only a working native factory worker
# clears the persistent cross-boot pending marker.
set -eu
BOOT_ID=${1:-}
LOG=${2:-/data/techo5-linux/techo5.log}
BASE=/data/techo5-linux
PENDING=$BASE/frankenasp-persistent-startup.pending
ACTIVE=/run/techo5/frankenasp-persistent-active
[ -n "$BOOT_ID" ] || exit 1
sleep 120
[ -e "$ACTIVE" ] || exit 0
[ -r "$PENDING" ] || exit 0
[ "$(cat "$PENDING")" = "$BOOT_ID" ] || exit 0
[ "$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)" = "$BOOT_ID" ] || exit 0
for maps in /proc/[0-9]*/maps; do
    [ -r "$maps" ] || continue
    if grep -q '/libasp_stream_worker.so' "$maps" 2>/dev/null &&
       grep -q '/libasp.so' "$maps" 2>/dev/null; then
        rm -f "$PENDING"
        echo "FrankenASP persistent: worker confirmed after startup probation" >> "$LOG"
        exit 0
    fi
done
echo "FrankenASP persistent: startup probation unconfirmed; next boot falls back to stock" >> "$LOG"
