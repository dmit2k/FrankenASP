# F1-B factory-facing adapter: OFFLINE mock only

This target is host-native, experimental and unqualified. It cannot load a
vendor library, read IDME or activate production factory admission. It requires
ASP2_FACTORY_MOCK and rejects ASP2_BIONIC at compile time. R1 shares the sole C0-C CFG2/TLV decoder and aligned FIFO with F1-A.
The factory-facing entry rejects admission; factory.c remains preserved and unlinked.

## Build and explicit selection

Set OUT_DIR to a private directory outside the repository:

```sh
OUT_DIR=/absolute/private/build bash tools/external-asp/build.sh cfg2-factory-mock
/absolute/private/build/test-cfg2-factory-mock --offline-factory-mock-cfg2
/absolute/private/build/test-cfg2-factory-mock --offline-factory-mock-cfg2 2,0,3,1 1,0
```

MIC/REF identity maps are defaults for numerical experiments only; optional
maps are explicit destination-to-captured permutations. They do not identify
physical capsules, vendor logical calibration indices or real REF wiring.
No selector, the synthetic selector, invalid maps or extra arguments reject
with ACK 524. HELLO never negotiates a format or downgrades to legacy.

The shared F1-A admission policy requires CONFIRMED athena, synchronized
hardware 4MIC/2REF at 96000 Hz/1920 capture frames, MIC S32 signed24 LOW24
exponent23 or HIGH24 exponent31, REF S16 low exponent15, and COMPLETE positive
INT32-bounded Q30 metadata with mask 0xf, IDME provenance and applied_to_pcm=0.
Missing/NONE/PARTIAL/inferred metadata rejects. Decoder success alone is
insufficient. Metadata and maps are owned immutable session copies.

## Calibration authority

Captured-slot Q30 is metadata only. logical_gain[d] associates
captured_gain[mic_map[d]]; no coefficient is multiplied into PCM, passed as a
gain argument, defaulted to unity or printed. The only future factory gain
executor is the real vendor Calibrator. No real Calibrator executes in this
mock. Its internal logical-index binding to captured slots and physical
capsules, and access to genuine owner IDME, remain unqualified.

The adapter receives exactly the shared bridge_step_aligned output: 768x6
signed32 words per 8ms quantum, four unchanged low signed24 MIC words then
two independent S16 REF words multiplied by 65536. HIGH24 uses arithmetic
shift by 8; out-of-range LOW24 is terminal. There is no extra gain or resampling.
The 20ms FIFO returns NotReady/UINT64_MAX first, then 320 S16 mono samples
with origins 0,320,640,...; sequence remains host controlled.

## ABI boundary and lifecycle

factory_adapter.h independently declares the opaque recovered function shapes:
asp_init, asp_create_pipeline, asp_set_ext_ref_sync_status, asp_process,
asp_destroy_pipeline and asp_deinit. This is a static function table, not a
loader. The mock in tests/mock_vendor.c is independently authored; no vendor
source, algorithms, proprietary assets or authentic coefficients are included.

All six functions must exist before init. Order is init -> create
(0,4,6,96000,1,1,16000) -> ref_sync(status2) -> process* -> destroy -> deinit.
An init failure owns nothing; a create failure deinitializes; a ref failure
destroys and deinitializes. Process failure latches terminal. Destroy error is
reported by exit2, with deinit still called exactly once. Close is idempotent.
Callers close an opened adapter before reopening it. One child owns one adapter.

Each process call has independently aligned, copied input and output storage,
32-byte canaries on BOTH sides, exact frame counts 768/128, flags0 and
timespec32 by value. Input mutation also rejects. Output is copied to the FIFO
only after all checks succeed. These bounded canaries detect tested nearby
writes; they do not sandbox arbitrary vendor memory corruption.
Timestamps start at zero, advance by exactly 8000000ns and are checked before
signed seconds overflow. Failure after earlier quanta suppresses all PCM for
that request. Framing/configuration/processing failures use terminal 523/522/503.

Initialization completes before HELLO. ACK299 says
"Experimental factory mock; unqualified". Stdout is reserved for wire bytes;
vendor stdout chatter is redirected to stderr before initialization.
Diagnostics contain static policy/authority and optional mock lifecycle counts.
EOF discards carry. SIGINT/SIGTERM/SIGPIPE set a cancellation flag and interrupt
input; teardown runs synchronously. The cooperative mock hang observes that
flag. SIGKILL/crash cannot run cleanup; host Kill/Wait and OS reclaim resources.
A real uncooperative vendor call is not qualified by this cancellation test.

## Verification

```sh
OUT_DIR=/absolute/private/build bash tools/external-asp/tests/run_factory_mock.sh
```

Strict C11 -Wall -Wextra -Werror -pedantic and ASan/UBSan run 672 full ABI
numerical cases (24 MIC x 2 REF x LOW/HIGH x 7 extrema), including nonzero
HIGH24 low bits; every quantum word is compared independently. Q30 association,
invalid LOW24, missing ABI entries, init/create/ref/process/destroy errors,
partial counts, input mutation, all four canaries, timestamp overflow,
idempotent cleanup and 100000 capture ticks/250000 quanta are checked.

Python reuses the independent F1-A per-sample oracle and immutable wire corpus
against the new backend, adds lifecycle/fault/cancellation/chatter tests, and
runs both native and sanitized real pipes. It verifies all maps, extrema,
metadata admission, no second gain, EOF/restart, malformed input, no PCM after
terminal errors, fragmentation/EINTR and fixed-packet rejection without downgrade.

tests/run_s1b_factory.sh uses the pinned read-only S1-B checkout through a Go
compiler overlay only. It exercises real host deadlines, exact PCM,
NotReady/origins, crash/hang/fatal, stock fallback in the failing current tick,
no implicit restart and child reaping; it repeats under -race three times.
Existing C0-C, F1-A, TLV 100k, golden and FrankenASP native tests remain gates.

All numbers are x86_64 trainer evidence, not device real-time guarantees.
No factory/asset, ARM32/Bionic, real vendor ABI or acoustic qualification follows.
Production remains disabled; launcher/mount/chroot work belongs to a later stage.
