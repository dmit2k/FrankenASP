# Independent C11 CFG2 decoder (C0-C, offline only)

This module is the **new variable-length CFG2/TLV** decoder for ASP2 wire revision 2. The canonical design is `docs/frankenasp/ASP2_PROTOCOL.md`. The factory-facing entry and both offline test children use this sole decoder; factory admission remains closed.

## Public API

Include `tools/external-asp/cfg2.h` and link `cfg2.c` directly. Call `cfg2_decode(const uint8_t *bytes, size_t n, cfg2_descriptor *out)` with a complete, exactly framed packet. Success returns `CFG2_OK`, failure returns a specific `cfg2_error` and zeroes the output (unless the output pointer is NULL). All codename bytes and normalized Q30 coefficients are copied into fixed-size arrays; neither pointers into input buffers nor allocations are retained. The caller must keep input and output regions disjoint. No filesystem, DSP, PCM mutation, network or vendor dependencies.

Supported registered tags: REQUIRED 0x0001 MIC_STREAM and 0x0002 REF_STREAM; OPTIONAL 0x0003 PLATFORM_INFO and 0x0101 MIC_FACTORY_GAIN. Unknown OPTIONAL tags are skipped, unknown REQUIRED rejected. Ordered, unique TLVs, strict lengths/schema/flags, 8192-byte and 64-tag caps are enforced. Old 40-byte CFG2 is rejected. Absent gain metadata has `present=0`, distinct from explicit NONE (`present=1, availability=0`). Hardware REF requires flags=7; absent REF requires all-zero descriptor and flags=1. Board confidence is advisory and does not authorize any vendor assets. Factory coefficients are captured-slot-aligned and **never applied to PCM here**.

## Portable host tests

```sh
CFG2_BUILD_DIR=/absolute/path/outside/repository/build \
  bash tools/external-asp/tests/run_cfg2.sh
```

The script builds C11 with `-O2 -Wall -Wextra -Werror -pedantic`, checks six frozen synthetic Go C0-A/B fixture SHA-256s, runs a Python ctypes suite against compiled C, and runs an independent C executable through the six expected decoded records, all truncation prefixes and 30,000 bounded hostile-input mutations. ASan/UBSan builds and execution are on by default (`CFG2_SANITIZE=0` disables on platforms without sanitizer support). The decoder itself needs only the standard C11 headers and has no runtime Python or Go dependency. All build products go outside the repository.

Existing synthetic native regression remains separately runnable with `OUT_DIR=... tools/external-asp/build.sh native-test` plus `ASP2_BUILD_DIR=... ASP2_TEST_DIR=... python3 tools/external-asp/tests/test_bridge.py`; this stage does **not** amend factory `build.sh`, Bionic worker, FIFO, `main.c` or installed binaries.
