#!/usr/bin/env bash
# F2-A offline native asset closure only; no mount/chroot or runtime enablement.
set -euo pipefail
D=$(cd "$(dirname "$0")/.." && pwd)
: "${OUT_DIR:?Set OUT_DIR outside repository}"
REPO=$(git -C "$D" rev-parse --show-toplevel)
BUILD=$(realpath -m "$OUT_DIR")
case "$BUILD/" in "$REPO/"*) echo 'OUT_DIR must be outside repository' >&2; exit 2;; esac
mkdir -p "$BUILD"
FLAGS=(-std=c11 -O2 -Wall -Wextra -Werror -pedantic -I"$D/assets")
SRC=("$D/assets/closure.c" "$D/assets/sha256.c" "$D/assets/preflight.c")
cc "${FLAGS[@]}" "${SRC[@]}" -o "$BUILD/asset-preflight-root"
cc "${FLAGS[@]}" -DAC_TESTING "${SRC[@]}" -o "$BUILD/asset-preflight-test"
cc "${FLAGS[@]}" -DAC_TESTING -O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined -fno-pie -no-pie "${SRC[@]}" -o "$BUILD/asset-preflight-sanitized"
WRAP=(-Wl,--wrap=fstat,--wrap=pread,--wrap=write,--wrap=memfd_create)
cc "${FLAGS[@]}" -DAC_TESTING "${SRC[@]}" "$D/tests/asset_faults.c" "${WRAP[@]}" -o "$BUILD/asset-faults"
cc "${FLAGS[@]}" -DAC_TESTING -O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined -fno-pie -no-pie "${SRC[@]}" "$D/tests/asset_faults.c" "${WRAP[@]}" -o "$BUILD/asset-faults-sanitized"
cc "${FLAGS[@]}" -fanalyzer -c "$D/assets/closure.c" -o "$BUILD/closure-analyzer.o"
if nm "$BUILD/asset-preflight-root" | grep -q ac_test_; then exit 3; fi
export OUT_DIR="$BUILD" PYTHONDONTWRITEBYTECODE=1
python3 "$D/tests/test_assets.py"
export ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1
ASSET_SANITIZED=1 python3 "$D/tests/test_assets.py"
echo 'PASS F2-A FD4 closure native/ASan/UBSan; offline synthetic ELF only'
