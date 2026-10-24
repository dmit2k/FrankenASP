#!/usr/bin/env bash
set -euo pipefail
# Requires the Android NDK. The script uses no extracted proprietary headers or libraries.
DIR="$(cd "$(dirname "$0")" && pwd)"
: "$ANDROID_NDK_HOME"
HOST_TAG="linux-x86_64"
CC="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/$HOST_TAG/bin/armv7a-linux-androideabi28-clang"
[[ -x "$CC" ]] || { echo "Missing Android ARMv7 clang: $CC" >&2; exit 2; }
OUT="$DIR/vendor-local/build/libasp_stream_worker.so"
if (( $# )); then OUT="$1"; fi
mkdir -p "$(dirname "$OUT")"
"$CC" -std=c11 -O2 -fPIC -shared -Wall -Wextra -Werror   -Wl,-soname,libasp_stream_worker.so "$DIR/asp_stream_worker.c" -ldl -o "$OUT"
file "$OUT"
readelf -h "$OUT" | grep -E 'Class:|Machine:'
if readelf --version-info "$OUT" | grep -q 'GLIBC_'; then
  echo "ERROR: glibc-linked worker; expected Android/Bionic. Refusing." >&2
  exit 3
fi
echo "Built local-only worker: $OUT"
