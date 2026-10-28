#!/usr/bin/env bash
# Offline ARM32 Linux build only. Does not run, install or activate the launcher.
set -euo pipefail
D=$(cd "$(dirname "$0")" && pwd)
REPO=$(git -C "$D" rev-parse --show-toplevel)
: "${OUT_DIR:?Set OUT_DIR outside the repository}"
BUILD=$(realpath -m "$OUT_DIR")
case "$BUILD/" in "$REPO/"*) echo "OUT_DIR must be outside source" >&2; exit 2;; esac
CC=${ARM32_CC:-arm-linux-gnueabihf-gcc}
READELF=${ARM32_READELF:-readelf}
FLAGS=(-std=c11 -Os -Wall -Wextra -Werror -pedantic -fno-strict-aliasing
       -march=armv7-a -marm -mfpu=vfpv3-d16 -mfloat-abi=hard
       -static -no-pie -fstack-protector-strong -D_FORTIFY_SOURCE=2
       -ffile-prefix-map="$REPO"=. -Wl,-z,relro,-z,now,-z,noexecstack)
if [[ -n ${ARM32_SYSROOT:-} ]]; then
 FLAGS+=(--sysroot="$ARM32_SYSROOT")
 # Ubuntu/Debian cross-libc archives use this layout when unpacked privately.
 FLAGS+=(-isystem "$ARM32_SYSROOT/usr/arm-linux-gnueabihf/include"
         -B "$ARM32_SYSROOT/usr/arm-linux-gnueabihf/lib/"
         -L "$ARM32_SYSROOT/usr/arm-linux-gnueabihf/lib")
fi
if [[ -n ${ARM32_BINUTILS:-} ]]; then FLAGS+=(-B "$ARM32_BINUTILS/"); fi
mkdir -p "$BUILD"
"$CC" "${FLAGS[@]}" "$D/launcher.c" -o "$BUILD/external-asp-launcher-arm32"
"$READELF" -h -l -A -d "$BUILD/external-asp-launcher-arm32" > "$BUILD/launcher-elf.txt"
grep -Eq 'Class: +ELF32' "$BUILD/launcher-elf.txt"
grep -Eq 'Data: +2.s complement, little endian' "$BUILD/launcher-elf.txt"
grep -Eq 'Machine: +ARM$' "$BUILD/launcher-elf.txt"
if grep -Eq 'INTERP|NEEDED' "$BUILD/launcher-elf.txt"; then
 echo "Static ARM32 launcher unexpectedly needs an interpreter/library" >&2; exit 3
fi
cat "$BUILD/launcher-elf.txt"
sha256sum "$BUILD/external-asp-launcher-arm32"
