#!/usr/bin/env bash
set -euo pipefail
D=$(cd "$(dirname "$0")" && pwd)
: "${OUT_DIR:?set private OUT_DIR outside source tree}"
mkdir -p "$OUT_DIR"
CFLAGS=(-std=c11 -O2 -fno-strict-aliasing -Wall -Wextra -Werror -pedantic -I"$D")
if [[ ${1:-native-test} == bionic-factory ]]; then
 exec bash "$D/build_bionic.sh"
elif [[ ${1:-native-test} == cfg2-factory-mock ]]; then
 # Statically bound host-only mock ABI; no dlopen, factory.c or vendor assets.
 CFLAGS+=(-DASP2_TEST_BACKEND -DASP2_FACTORY_MOCK)
 cc "${CFLAGS[@]}" "$D"/{factory_child,cfg2_runtime,cfg2,core,io,factory_adapter}.c "$D/tests/mock_vendor.c" -o "$OUT_DIR/test-cfg2-factory-mock"
 cc "${CFLAGS[@]}" "$D"/{factory_child,cfg2_runtime,cfg2,core,io,factory_adapter}.c "$D/tests/"{mock_vendor,short_syscalls}.c -Wl,--wrap=read,--wrap=write -o "$OUT_DIR/test-cfg2-factory-mock-fragmented"
elif [[ ${1:-native-test} == cfg2-synthetic ]]; then
 # Independent host-only target; no factory.c, assets, Bionic or legacy entry.
 cc "${CFLAGS[@]}" -DASP2_TEST_BACKEND "$D"/{cfg2_child,cfg2_runtime,cfg2,core,io}.c "$D/tests/backend_cfg2.c" -o "$OUT_DIR/test-cfg2-synthetic"
 cc "${CFLAGS[@]}" -DASP2_TEST_BACKEND "$D"/{cfg2_child,cfg2_runtime,cfg2,core,io}.c "$D/tests/"{backend_cfg2,short_syscalls}.c -Wl,--wrap=read,--wrap=write -o "$OUT_DIR/test-cfg2-synthetic-fragmented"
 cc "${CFLAGS[@]}" -fPIC -shared -DASP2_TEST_BACKEND "$D"/{cfg2_runtime,cfg2,core,io}.c "$D/tests/backend_cfg2.c" -o "$OUT_DIR/libcfg2-runtime-test.so"
elif [[ ${1:-native-test} == native-test ]]; then
 cc "${CFLAGS[@]}" -DASP2_TEST_BACKEND "$D"/{main,cfg2_runtime,cfg2,core,io}.c "$D/tests/backend.c" -o "$OUT_DIR/test-external-asp"
 cc "${CFLAGS[@]}" -DASP2_TEST_BACKEND "$D"/{main,cfg2_runtime,cfg2,core,io}.c "$D/tests/backend.c" "$D/tests/short_syscalls.c" -Wl,--wrap=read,--wrap=write -o "$OUT_DIR/test-external-asp-fragmented"
 cc "${CFLAGS[@]}" -DASP2_TEST_BACKEND "$D"/{core,io}.c "$D/tests/backend.c" "$D/tests/test_fifo.c" -o "$OUT_DIR/test-fifo"
 cc "${CFLAGS[@]}" -fPIC -shared -DASP2_TEST_BACKEND "$D"/{core,io,sha256}.c "$D/tests/backend.c" -o "$OUT_DIR/libbridge-test.so"
 cc "${CFLAGS[@]}" "$D"/{main,cfg2_runtime,cfg2,core,io}.c "$D/tests/backend.c" -o "$OUT_DIR/external-asp-host-diagnostic"
else
 echo "Unknown offline target; vendor/Bionic build remains unqualified" >&2
 exit 2
fi
