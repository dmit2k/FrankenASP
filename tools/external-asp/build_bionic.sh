#!/usr/bin/env bash
# Genuine Android 9 ARM32 child, using owner-private original Bionic libraries.
set -euo pipefail
D=$(cd "$(dirname "$0")" && pwd)
: "${OUT_DIR:?private output outside Git}" "${BIONIC_ROOT:?matching original system/vendor root}"
: "${BIONIC_CC:?existing ARM32 GCC}" "${BIONIC_LD:?existing ARM32 GNU ld}"
mkdir -p "$OUT_DIR/objects"
INCLUDE=$("$BIONIC_CC" -print-file-name=include)
FLAGS=(-B "$(dirname "$BIONIC_LD")/" -std=c11 -O2 -Wall -Wextra -Werror -pedantic -ffreestanding
 -fno-builtin -fno-stack-protector -fno-strict-aliasing -fPIC
 -march=armv7-a -marm -mfpu=neon -mfloat-abi=softfp
 -nostdinc -isystem "$INCLUDE" -I"$D" -DASP2_BIONIC -DASP2_FACTORY_REAL)
OBJ=()
for name in factory_child cfg2_runtime cfg2 core io factory_adapter factory bionic_entry start32; do
 ext=c; [[ $name == start32 ]] && ext=S
 "$BIONIC_CC" "${FLAGS[@]}" -c "$D/$name.$ext" -o "$OUT_DIR/objects/$name.o"
 OBJ+=("$OUT_DIR/objects/$name.o")
done
"$BIONIC_LD" -m armelf_linux_eabi -pie --no-undefined --hash-style=both \
 --dynamic-linker=/system/bin/linker -z now -z relro -z noexecstack \
 -e _start -o "$OUT_DIR/asp2-child" "${OBJ[@]}" \
 -rpath-link "$BIONIC_ROOT/system/lib" -L"$BIONIC_ROOT/system/lib" -l:libdl.so -l:libc.so
readelf -h -l -d -A "$OUT_DIR/asp2-child" > "$OUT_DIR/asp2-child.elf.txt"
python3 - "$OUT_DIR/asp2-child" <<'CHECK'
import struct,sys
b=open(sys.argv[1],'rb').read()
assert b[:7]==b'\x7fELF\x01\x01\x01'
assert struct.unpack_from('<H',b,18)[0]==40
p=struct.unpack_from('<I',b,28)[0]
size,count=struct.unpack_from('<HH',b,42)
interp=[]
for i in range(count):
 h=struct.unpack_from('<8I',b,p+i*size)
 if h[0]==3: interp.append(b[h[1]:h[1]+h[4]])
assert interp==[b'/system/bin/linker\0']
CHECK
sha256sum "$OUT_DIR/asp2-child"
