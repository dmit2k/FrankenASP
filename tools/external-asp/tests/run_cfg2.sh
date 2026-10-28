#!/usr/bin/env bash
# Host-only portable C11 conformance. No Bionic, DSP, host integration or Echo.
set -euo pipefail
D=$(cd "$(dirname "$0")/.." && pwd)
FIX="$D/tests/cfg2_v2"
: "${CFG2_BUILD_DIR:?Set CFG2_BUILD_DIR outside FrankenASP source tree}"
mkdir -p "$CFG2_BUILD_DIR"
BUILD=$(cd "$CFG2_BUILD_DIR" && pwd)
case "$BUILD/" in "$D/"*) echo "Build directory must be outside source" >&2; exit 2;; esac
(cd "$FIX" && sha256sum -c SHA256SUMS)
CC="${CC:-cc}"
PYTHON="${PYTHON:-python3}"
CFLAGS=(-std=c11 -Wall -Wextra -Werror -pedantic)
"$CC" "${CFLAGS[@]}" -O2 -fPIC -shared "$D/cfg2.c" -o "$BUILD/libcfg2.so"
"$CC" "${CFLAGS[@]}" -O2 "$D/cfg2.c" "$D/tests/cfg2_smoke.c" -o "$BUILD/cfg2-smoke"
PYTHONDONTWRITEBYTECODE=1 CFG2_BUILD_DIR="$BUILD" "$PYTHON" -m unittest discover -v -s "$D/tests" -p test_cfg2.py
"$BUILD/cfg2-smoke" "$FIX"
if [[ "${CFG2_SANITIZE:-1}" == 1 ]]; then
 "$CC" "${CFLAGS[@]}" -O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined \
  "$D/cfg2.c" "$D/tests/cfg2_smoke.c" -o "$BUILD/cfg2-smoke-sanitized"
 ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
  "$BUILD/cfg2-smoke-sanitized" "$FIX"
fi
echo "PASS: independent CFG2 C11 Go/C conformance"
