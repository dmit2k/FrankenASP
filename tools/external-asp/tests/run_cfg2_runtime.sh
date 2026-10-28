#!/usr/bin/env bash
# F1-A host-native only; build products and mutable fixtures outside source.
set -euo pipefail
D=$(cd "$(dirname "$0")/.." && pwd)
: "${OUT_DIR:?Set OUT_DIR outside FrankenASP}"
BUILD=$(realpath -m "$OUT_DIR")
REPO=$(git -C "$D" rev-parse --show-toplevel)
case "$BUILD/" in "$REPO/"*) echo "OUT_DIR must be outside repository" >&2; exit 2;; esac
export OUT_DIR="$BUILD" ASP2_BUILD_DIR="$BUILD" PYTHONDONTWRITEBYTECODE=1
mkdir -p "$BUILD"
bash "$D/build.sh" native-test
bash "$D/build.sh" cfg2-synthetic
CC=${CC:-cc}
FLAGS=(-std=c11 -Wall -Wextra -Werror -I"$D" -DASP2_TEST_BACKEND)
"$CC" "${FLAGS[@]}" -O2 "$D"/{cfg2_runtime,cfg2,core,io}.c "$D/tests/"{backend_cfg2,test_cfg2_runtime}.c -o "$BUILD/test-cfg2-runtime"
"$BUILD/test-cfg2-runtime" "$D/tests/cfg2_v2/athena_confirmed_complete_4mic.cfg2"
python3 "$D/tests/test_cfg2_runtime.py"
if [[ ${CFG2_RUNTIME_SANITIZE:-1} == 1 ]]; then
 # Non-PIE sanitizer probes avoid ASan shadow/PIE address collisions on hosts.
 SAN=(-O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined -fno-pie -no-pie)
 "$CC" "${FLAGS[@]}" "${SAN[@]}" "$D"/{cfg2_runtime,cfg2,core,io}.c "$D/tests/"{backend_cfg2,test_cfg2_runtime}.c -o "$BUILD/test-cfg2-runtime-sanitized"
 "$CC" "${FLAGS[@]}" "${SAN[@]}" "$D"/{cfg2_child,cfg2_runtime,cfg2,core,io}.c "$D/tests/backend_cfg2.c" -o "$BUILD/test-cfg2-synthetic-sanitized"
 "$CC" "${FLAGS[@]}" "${SAN[@]}" "$D"/{cfg2_child,cfg2_runtime,cfg2,core,io}.c "$D/tests/"{backend_cfg2,short_syscalls}.c -Wl,--wrap=read,--wrap=write -o "$BUILD/test-cfg2-synthetic-fragmented-sanitized"
 export ASAN_OPTIONS=detect_leaks=1:halt_on_error=1
 export UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1
 "$BUILD/test-cfg2-runtime-sanitized" "$D/tests/cfg2_v2/athena_confirmed_complete_4mic.cfg2"
 ASP2_CFG2_SANITIZED=1 python3 "$D/tests/test_cfg2_runtime.py"
fi
echo "PASS: F1-A CFG2 runtime (synthetic only)"
