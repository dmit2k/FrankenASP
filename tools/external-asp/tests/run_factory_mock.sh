#!/usr/bin/env bash
# F1-B offline-only native/sanitized ABI replay.
set -euo pipefail
D=$(cd "$(dirname "$0")/.." && pwd)
: "${OUT_DIR:?Use private directory outside source}"
export ASP2_BUILD_DIR="$OUT_DIR" PYTHONDONTWRITEBYTECODE=1
mkdir -p "$OUT_DIR"
bash "$D/build.sh" native-test
bash "$D/build.sh" cfg2-factory-mock
FLAGS=(-std=c11 -Wall -Wextra -Werror -pedantic -I"$D" -DASP2_TEST_BACKEND -DASP2_FACTORY_MOCK)
SRC=("$D"/{cfg2_runtime,cfg2,core,io,factory_adapter}.c "$D/tests/mock_vendor.c")
cc "${FLAGS[@]}" -O2 "${SRC[@]}" "$D/tests/test_factory_adapter.c" -o "$OUT_DIR/test-factory-adapter"
"$OUT_DIR/test-factory-adapter" "$D/tests/cfg2_v2/athena_confirmed_complete_4mic.cfg2"
python3 "$D/tests/test_factory_runtime.py"
SAN=(-O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined -fno-pie -no-pie)
cc "${FLAGS[@]}" "${SAN[@]}" "${SRC[@]}" "$D/tests/test_factory_adapter.c" -o "$OUT_DIR/test-factory-adapter-sanitized"
cc "${FLAGS[@]}" "${SAN[@]}" "${SRC[@]}" "$D/factory_child.c" -o "$OUT_DIR/test-cfg2-factory-mock-sanitized"
cc "${FLAGS[@]}" "${SAN[@]}" "${SRC[@]}" "$D/factory_child.c" "$D/tests/short_syscalls.c" -Wl,--wrap=read,--wrap=write -o "$OUT_DIR/test-cfg2-factory-mock-fragmented-sanitized"
export ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1
"$OUT_DIR/test-factory-adapter-sanitized" "$D/tests/cfg2_v2/athena_confirmed_complete_4mic.cfg2"
ASP2_CFG2_SANITIZED=1 python3 "$D/tests/test_factory_runtime.py"
echo "PASS F1-B factory mock: experimental/unqualified; no real vendor runtime"
