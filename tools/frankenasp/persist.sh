#!/bin/sh
# Explicitly opt into boot-persistent Athena factory voice processing.
# Only one minimally patched launcher in the CURRENT A/B slot is modified.
# Never touches boot/vendor partitions, the official daemon or volume.
set -eu
BASE=/data/techo5-linux
TRIAL=$BASE/frankenasp-trial
FLAG=$BASE/frankenasp-persistent.enabled
SLOT_FILE=/run/techo5/slot
HELPER=$TRIAL/persistent-run.sh
ANCHOR='exec /usr/local/bin/techo5 run >> $LOG 2>&1'
MARKER='# FrankenASP persistent slot-local hook (owner opt-in)'
die() { echo "FrankenASP persistent: $*" >&2; exit 1; }
slot_path() {
    [ "$(uname -m)" = aarch64 ] || die "not arm64"
    case "$(uname -r)" in *athena*) : ;; *) die "not Athena" ;; esac
    [ -s "$SLOT_FILE" ] || die "slot identifier absent"
    slot=$(cat "$SLOT_FILE")
    case "$slot" in a|b) : ;; *) die "invalid slot" ;; esac
    # Never patch a rootfs on trial or an inactive slot. These files are
    # exactly what init will boot next; do not surprise slotctl rollback.
    [ "$(cat /store/active 2>/dev/null)" = "$slot" ] ||
        die "store active slot differs from the booted slot"
    [ "$(cat "/store/slots/$slot.state" 2>/dev/null)" = good ] ||
        die "active slot is not settled/good; refusing persistence modifications"
    root="/store/slots/$slot"
    runner="$root/usr/local/sbin/techo5-run"
    stock="$root/usr/local/sbin/techo5-run.frankenasp.stock"
    [ -f "$runner" ] && [ ! -L "$runner" ] || die "active slot runner absent/unsafe"
    [ "$(sha256sum "$runner" | cut -d' ' -f1)" = "$(sha256sum /usr/local/sbin/techo5-run | cut -d' ' -f1)" ] ||
        die "active slot runner differs from executing rootfs"
}
inactive() {
    [ ! -e /run/techo5/frankenasp-trial-active ] || die "time-limited trial active"
    [ ! -e /run/techo5/frankenasp-trial-lock ] || die "trial lock active"
    [ ! -e /run/techo5/hold ] || die "maintenance hold active"
    if grep -q ' /usr/local/bin/techo5 ' /proc/mounts 2>/dev/null; then
        die "another binary is bind-mounted"
    fi
}
require_payload() {
    [ -f "$HELPER" ] && [ -f "$TRIAL/SHA256SUMS" ] || die "persistence hook or checksum manifest missing"
    [ -x "$TRIAL/techo5-experimental" ] || die "experimental binary missing"
    [ -x "$BASE/amazon-arm32/system/bin/sh-native" ] || die "native runtime missing"
    (cd "$TRIAL" && sha256sum -c SHA256SUMS >/dev/null 2>&1) || die "experimental manifest mismatch"
    (cd "$BASE/amazon-arm32" && sha256sum -c SHA256SUMS >/dev/null 2>&1) || die "native runtime manifest mismatch"
    ver=$("$TRIAL/techo5-experimental" --version 2>/dev/null | head -1)
    case "$ver" in "echod version v"*"_"frankenasp*) : ;; *) die "rebuild experimental daemon with FrankenASP version stamp (not v0.0.0-dev)" ;; esac
}
patch_runner() {
    [ "$(grep -Fxc "$ANCHOR" "$runner")" -eq 1 ] || die "unknown stock launcher; refusing patch"
    ! grep -Fq "$MARKER" "$runner" || die "hook already present"
    if [ -e "$stock" ]; then
        # An earlier uninstall kept its original snapshot. Reuse it only
        # when the current launcher is IDENTICAL to that snapshot.
        [ -f "$stock" ] && cmp -s "$stock" "$runner" ||
            die "preexisting launcher backup differs; review manually"
    else
        cp -p "$runner" "$stock" || die "failed backing up launcher"
    fi
    file="$runner.frankenasp.new"
    awk -v anchor="$ANCHOR" -v marker="$MARKER" '
       $0 == anchor {
         print marker
         print "if [ -r /data/techo5-linux/frankenasp-trial/persistent-run.sh ]; then"
         print "    . /data/techo5-linux/frankenasp-trial/persistent-run.sh"
         print "fi"
       }
       { print }
    ' "$stock" > "$file" || die "cannot generate launcher"
    chmod 755 "$file"
    sh -n "$file" || die "new launcher shell syntax invalid"
    mv "$file" "$runner" || die "cannot install launcher hook"
}
writable_slot() {
    mount -o remount,rw /store || die "cannot remount slot store rw"
    trap 'mount -o remount,ro /store || echo "CRITICAL: store remained rw" >&2' EXIT
}
readonly_slot() {
    sync
    mount -o remount,ro /store || die "CRITICAL: cannot remount slot store read-only"
    trap - EXIT
}
action=${1:-status}
case "$action" in
  status)
    slot_path
    echo "slot=$slot"
    if grep -Fq "$MARKER" "$runner"; then echo "slot_hook=installed"; else echo "slot_hook=absent"; fi
    [ -e "$FLAG" ] && echo "persistent_requested=yes" || echo "persistent_requested=no"
    [ -e /run/techo5/frankenasp-persistent-active ] && echo "active_this_boot=yes" || echo "active_this_boot=no"
    [ -e /run/techo5/frankenasp-persistent-attempted ] && echo "attempted_this_boot=yes" || echo "attempted_this_boot=no"
    ;;
  install-hook)
    slot_path; inactive; require_payload
    [ ! -e "$FLAG" ] || die "already requested"
    writable_slot
    patch_runner
    readonly_slot
    echo "Hook installed ONLY in current slot $slot; factory mode still DISABLED"
    ;;
  enable)
    slot_path; inactive; require_payload
    grep -Fq "$MARKER" "$runner" || die "first run install-hook"
    # Explicit opt-in stored in /data, no restart or active-mode mutation now.
    (umask 077; : > "$FLAG") || die "cannot enable persistent flag"
    echo "Persistent flag set; reboot manually to activate after safety checks"
    ;;
  disable)
    # Deliberately does not stop a running daemon or alter /usr/local/bin.
    # Do not clear the live markers: the updater remains blocked until
    # the user has rebooted into stock TECHO5.
    [ ! -e /run/techo5/frankenasp-trial-active ] || die "trial active"
    rm -f "$FLAG" "$BASE/fireos-asp.enabled" "$BASE/frankenasp-persistent-startup.pending"
    echo "Persistent flag cleared; reboot manually to start stock TECHO5"
    echo "Do not update until the restart completes: active process may still be experimental."
    ;;
  uninstall-hook)
    slot_path; inactive
    [ ! -e "$FLAG" ] || die "run disable and reboot before uninstall"
    [ ! -e /run/techo5/frankenasp-persistent-active ] || die "experimental process active; reboot first"
    [ -s "$stock" ] || die "slot-local original launcher backup missing"
    grep -Fq "$MARKER" "$runner" || die "slot launcher was not patched by this tool"
    writable_slot
    # Repair only a runner still matching the inserted hook structure.
    [ "$(grep -Fxc "$ANCHOR" "$runner")" -eq 1 ] || die "launcher differs; review manually"
    cp "$stock" "$runner.frankenasp.restore"
    chmod 755 "$runner.frankenasp.restore"
    mv "$runner.frankenasp.restore" "$runner"
    # Back up the backup? Leave it for provenance; a manual operator can
    # remove it after separate verification. It won't be executed.
    readonly_slot
    echo "Original slot launcher restored; old snapshot retained: $stock"
    ;;
  *) die "usage: sh $0 {status|install-hook|enable|disable|uninstall-hook}" ;;
esac
