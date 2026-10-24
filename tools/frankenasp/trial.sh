#!/bin/sh
# Nonpersistent, time-limited research run on Athena. Does not adjust volume,
# speaker settings, Sendspin, music, TTS, or the system's A/B slots.
set -eu
BASE=/data/techo5-linux
BIN=/usr/local/bin/techo5
DIR=$BASE/frankenasp-trial
ALT=$DIR/techo5-experimental
BACKUP=$DIR/techo5-official-baseline
HOLD=/run/techo5/hold
ARMED=/run/techo5/frankenasp-armed
FLAG=$BASE/fireos-asp.enabled
ACTIVE=/run/techo5/frankenasp-trial-active
LOCK=/run/techo5/frankenasp-trial-lock
LOG=$DIR/trial-events.log

log() { printf '%s %s\n' "$(date -Iseconds)" "$*" >> "$LOG"; }
fail() { log "ERROR: $*"; printf 'ERROR: %s\n' "$*" >&2; exit 1; }
mounted() { awk -v target="$BIN" '$2==target{f=1} END{exit !f}' /proc/mounts; }
worker_pid() {
  for p in /proc/[0-9]*; do
    [ -r "$p/maps" ] || continue
    if grep -q '/libasp_stream_worker.so' "$p/maps" 2>/dev/null &&
       grep -q '/libasp.so' "$p/maps" 2>/dev/null; then
      basename "$p"
      return 0
    fi
  done
  return 1
}
stop_daemon() {
  for pid in $(pidof techo5 2>/dev/null || :); do kill -TERM "$pid" 2>/dev/null || :; done
  n=0
  while pidof techo5 >/dev/null 2>&1; do
    [ "$n" -lt 12 ] || return 1
    sleep 1
    n=$((n+1))
  done
}
route_off() {
  # AWB capture routes only; do not touch TAS5805M volume or playback.
  amixer -q -c 0 cset name='UL2_CH1 DL1_CH1' off >/dev/null 2>&1 || :
  amixer -q -c 0 cset name='UL2_CH2 DL1_CH2' off >/dev/null 2>&1 || :
}
rollback() {
  mkdir "$LOCK" 2>/dev/null || { log "rollback lock busy"; return 1; }
  if [ ! -e "$ACTIVE" ] && ! mounted; then
    rmdir "$LOCK" || :
    return 0
  fi
  log "rollback start"
  touch "$HOLD"
  if ! stop_daemon; then
    log "CRITICAL: daemon cannot stop; hold retained"
    rmdir "$LOCK" || :
    return 1
  fi
  if mounted; then
    if ! umount "$BIN"; then
      log "CRITICAL: unmount failed; hold retained"
      rmdir "$LOCK" || :
      return 1
    fi
  fi
  rm -f "$FLAG" "$ARMED" "$ACTIVE"
  route_off
  rm -f "$HOLD"
  rmdir "$LOCK" || :
  log "rollback complete; official launcher resumed"
}
start() {
  seconds=$1
  case "$seconds" in *[!0-9]*|'') fail "duration must be 30..180 seconds";; esac
  [ "$seconds" -ge 30 ] && [ "$seconds" -le 180 ] || fail "duration 30..180 seconds"
  [ ! -e "$FLAG" ] && [ ! -e "$ARMED" ] && [ ! -e "$ACTIVE" ] || fail "old marker still exists"
  [ ! -e "$HOLD" ] && ! mounted || fail "another operation holds or overlays the daemon"
  [ -x "$ALT" ] && [ -x "$BIN" ] || fail "daemon binary missing"
  [ -x "$BASE/amazon-arm32/system/bin/sh-native" ] || fail "native shell absent"
  [ -s "$BASE/amazon-arm32/libasp_stream_worker.so" ] || fail "worker missing"
  [ -s /vendor/lib/libasp.so ] || fail "factory ASP missing"
  [ "$(uname -m)" = aarch64 ] || fail "not AArch64"
  case "$(uname -r)" in *athena*) :;; *) fail "not Athena";; esac
  mkdir "$LOCK" 2>/dev/null || fail "trial locked"
  if [ ! -e "$BACKUP" ]; then
    cp "$BIN" "$BACKUP" || { rmdir "$LOCK" || :; fail "could not save official backup"; }
    chmod 700 "$BACKUP"
  fi
  if [ "$(sha256sum "$BIN" | awk '{print $1}')" != "$(sha256sum "$BACKUP" | awk '{print $1}')" ]; then
    rmdir "$LOCK" || :
    fail "official binary differs from preserved baseline"
  fi
  log "starting nonpersistent trial duration=$seconds"
  deadline=$(($(date +%s) + seconds))
  nohup sh "$0" watch "$deadline" > "$DIR/watchdog.log" 2>&1 </dev/null &
  log "watchdog pid=$! deadline=$deadline"
  touch "$HOLD"
  if ! stop_daemon; then
    log "cannot stop daemon; clearing hold without mounting"
    rm -f "$HOLD"
    rmdir "$LOCK" || :
    fail "daemon stop timed out"
  fi
  if ! mount --bind "$ALT" "$BIN"; then
    rm -f "$HOLD"
    rmdir "$LOCK" || :
    fail "experimental bind mount failed"
  fi
  touch "$ACTIVE" "$ARMED" "$FLAG"
  rm -f "$HOLD"
  rmdir "$LOCK" || :
  log "experimental launcher released"
  n=0
  while [ "$n" -lt 15 ]; do
    if worker_pid >/dev/null 2>&1; then
      log "worker mapped pid=$(worker_pid)"
      printf 'LIVE_TRIAL=ACTIVE duration=%ss worker_pid=%s\n' "$seconds" "$(worker_pid)"
      return 0
    fi
    sleep 1
    n=$((n+1))
  done
  log "worker not mapped within 15 seconds; rollback"
  rollback || :
  fail "worker startup failed"
}
watch() {
  deadline=$1
  startsec=$(date +%s)
  seen=no
  original_worker=
  misses=0
  while [ "$(date +%s)" -lt "$deadline" ]; do
    [ -e "$ACTIVE" ] || { sleep 2; continue; }
    current_worker=$(worker_pid || :)
    if [ -n "$current_worker" ]; then
      if [ "$seen" = yes ] && [ "$current_worker" != "$original_worker" ]; then
        log "native worker PID changed from $original_worker to $current_worker; emergency rollback"
        rollback
        exit
      fi
      if [ "$seen" = no ]; then
        original_worker=$current_worker
        log "watchdog pinned native worker PID=$original_worker"
      fi
      seen=yes
      misses=0
    elif [ "$seen" = yes ]; then
      misses=$((misses + 1))
      if [ "$misses" -ge 2 ]; then log "worker lost; emergency rollback"; rollback; exit; fi
    elif [ "$(date +%s)" -ge $((startsec + 24)) ]; then
      log "startup timeout; emergency rollback"
      rollback
      exit
    fi
    sleep 2
  done
  log "trial deadline; automatic rollback"
  rollback
}
status() {
  printf 'requested=%s\n' "$([ -e "$FLAG" ] && echo yes || echo no)"
  printf 'armed=%s\n' "$([ -e "$ARMED" ] && echo yes || echo no)"
  printf 'bind_mount=%s\n' "$(mounted && echo yes || echo no)"
  printf 'worker_pid=%s\n' "$(worker_pid || echo none)"
  printf 'daemon_pid=%s\n' "$(pidof techo5 2>/dev/null || echo none)"
  printf 'binary_sha256=%s\n' "$(sha256sum "$BIN" | awk '{print $1}')"
}
case "$1" in
  start) start "$2" ;;
  rollback) rollback ;;
  watch) watch "$2" ;;
  status) status ;;
  *) echo "Usage: $0 {start seconds(30..180)|rollback|status}" >&2; exit 2 ;;
esac
