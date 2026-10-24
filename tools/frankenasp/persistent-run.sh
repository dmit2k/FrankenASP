#!/bin/sh
# Sourced by a minimally patched TECHO5 per-slot launcher.
# No action unless persistent opt-in exists. An attempted fork gets only
# ONE start per boot; any crash/restart falls back to the official TECHO5.
BASE=/data/techo5-linux
PERSIST=$BASE/frankenasp-persistent.enabled
TRIAL=$BASE/frankenasp-trial
RUNTIME=$BASE/amazon-arm32
ARMED=/run/techo5/frankenasp-armed
ACTIVE=/run/techo5/frankenasp-persistent-active
ATTEMPTED=/run/techo5/frankenasp-persistent-attempted
REQUEST=$BASE/fireos-asp.enabled
PENDING=$BASE/frankenasp-persistent-startup.pending
WATCHER=$TRIAL/persist-watch.sh
VENDOR_SHA=bf2a0b569d8bfb7482b2d0a4b5dfffc2601c60a92b6389e5b8839160b3119bb9

if [ -e "$PERSIST" ] && [ ! -e /run/techo5/frankenasp-trial-active ]; then
    ok=yes
    reason=
    if [ -e "$ATTEMPTED" ]; then
        # The experimental daemon already exited once this boot: never
        # relaunch a broken fork. Disable future boot persistence as well.
        rm -f "$PERSIST" "$PENDING"
        ok=no
        reason=fork_exited_this_boot
    fi
    if [ -e "$PENDING" ] && [ ! -e "$ATTEMPTED" ]; then
        # Prior boot never reached its verified-startup probation checkpoint.
        # Disable opt-in, so even repeated kernel reboots cannot loop forever.
        rm -f "$PERSIST" "$PENDING"
        ok=no
        reason=previous_boot_unconfirmed
    fi
    [ ! -e /run/techo5/hold ] || { ok=no; reason=maintenance_hold; }
    grep -q ' /usr/local/bin/techo5 ' /proc/mounts 2>/dev/null &&
        { ok=no; reason=official_binary_bind_mounted; }
    [ -x "$TRIAL/techo5-experimental" ] || { ok=no; reason=missing_experimental_binary; }
    [ -x "$RUNTIME/system/bin/sh-native" ] || { ok=no; reason=missing_arm32_shell; }
    [ -f "$TRIAL/SHA256SUMS" ] || { ok=no; reason=missing_trial_checksums; }
    [ -f "$RUNTIME/SHA256SUMS" ] || { ok=no; reason=missing_runtime_checksums; }
    [ -x "$WATCHER" ] || { ok=no; reason=missing_startup_watchdog; }
    [ "$ok" = no ] || (cd "$TRIAL" && sha256sum -c SHA256SUMS >/dev/null 2>&1) ||
        { ok=no; reason=trial_checksum_mismatch; }
    [ "$ok" = no ] || (cd "$RUNTIME" && sha256sum -c SHA256SUMS >/dev/null 2>&1) ||
        { ok=no; reason=runtime_checksum_mismatch; }
    if [ "$ok" = yes ]; then
        observed=$(sha256sum /vendor/lib/libasp.so 2>/dev/null | cut -d' ' -f1)
        [ "$observed" = "$VENDOR_SHA" ] || { ok=no; reason=vendor_revision_mismatch; }
    fi
    if [ "$ok" = yes ]; then
        v=$("$TRIAL/techo5-experimental" --version 2>/dev/null | head -1)
        case "$v" in
            "echod version v"*"_frankenasp"*) : ;;
            *) ok=no; reason=experimental_version_not_stamped ;;
        esac
    fi
    if [ "$ok" = yes ]; then
        # The sentinel is NOT an updater hook, just explicit owner intent.
        # /run is tmpfs, so each reboot must revalidate before rearming.
        touch "$ATTEMPTED"
        if touch "$REQUEST" "$ARMED" "$ACTIVE"; then
            boot_id=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || echo unknown)
            printf '%s\n' "$boot_id" > "$PENDING" || { reason=failed_pending_record; ok=no; }
            if [ "$ok" = yes ]; then
                # A background verifier clears the persistent pending marker
                # only after 120s with a mapped native factory worker.
                sh "$WATCHER" "$boot_id" "$LOG" >/dev/null 2>&1 </dev/null &
                echo "FrankenASP persistent: starting validated owner fork" >> "$LOG"
                exec "$TRIAL/techo5-experimental" run >> "$LOG" 2>&1
            fi
        fi
        reason=failed_to_arm
    fi
    # A missing file, crash or bad version NEVER prevents stock boot.
    # If the fork already ran earlier this boot, this clears its markers.
    rm -f "$ARMED" "$ACTIVE" "$REQUEST"
    echo "FrankenASP persistent: fallback to stock TECHO5 ($reason)" >> "$LOG"
fi
