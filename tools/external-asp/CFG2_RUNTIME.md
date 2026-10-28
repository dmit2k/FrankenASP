# F1-A CFG2 runtime bridge: synthetic only

This is a new, explicitly selected **host-native offline synthetic experiment**.
It does not qualify the factory DSP, assets, physical microphone geometry, ARM32,
Bionic, secure launcher or any Echo deployment. F1-B is outside this change.

R1 removed the fixed codec and bridge wrapper. main.c now reads CFG2/TLV
through cfg2_read_fd and rejects production admission. The synthetic and mock
children retain explicit test-backend selectors and share this same reader and
bridge_step_aligned FIFO. factory.c is preserved but not linked by these targets.

## Build and select

Use OUT_DIR outside the repository:

```sh
OUT_DIR=/absolute/private/build bash tools/external-asp/build.sh cfg2-synthetic
/absolute/private/build/test-cfg2-synthetic --offline-synthetic-cfg2
```

Identity MIC and REF maps are the documented default. For a synthetic mapping
experiment, provide BOTH explicit destination-to-captured-source permutations:

```sh
/absolute/private/build/test-cfg2-synthetic --offline-synthetic-cfg2 2,0,3,1 1,0
```

No flag, wrong flag, extra arguments or invalid map produce terminal ACK 524.
There is no ENV-based format selection, autodetection, legacy downgrade,
filesystem profile, metadata reload, vendor loader or factory asset access in
this child. The only test ENV is ASP2_TEST_FAULT=fatal/crash/hang; it injects a
fault after 20 synthetic DSP quanta, never changes protocol or capability policy.
The target requires ASP2_TEST_BACKEND and refuses ASP2_BIONIC at compile time.
factory.c is never linked into this target.

## Admission and ownership

cfg2_read_fd() reads exactly 16 bytes into a fixed 8192-byte local buffer.
It checks magic/version/header length, total 16..8192 and flags 1/7 before
reading exactly the declared body. It allocates nothing and never consumes
bytes from a pipelined INP2. Truncation and all parser errors yield ACK REJECT
522 with no PCM. The accepted C0-C cfg2_decode() remains unchanged.

cfg2_runtime_init() takes only a successfully decoded descriptor. This narrow
factory-shaped synthetic mode requires **all** of:

- PLATFORM_INFO present, schema-valid CONFIRMED athena. This is advisory
  metadata and does not authorize assets or establish hardware authenticity.
- Hardware/synchronized/interleaved flags=7; 4 MIC x 1920 frames x 96000 Hz,
  S32 signed24, LOW24/full_bits=23 or HIGH24/full_bits=31.
- 2 REF x 1920 x 96000, S16/valid_bits=16/full_bits=15/low alignment.
- MIC_FACTORY_GAIN present, COMPLETE, IDME provenance, normalized signed-i64
  Q30 encoding, applied_to_pcm=0, channels=4, mask=15, positive coefficients
  bounded by INT32_MAX. NOT ADVERTISED, NONE and PARTIAL reject explicitly.

The generic parser still accepts all six golden vectors; only the confirmed
complete Athena vector is admitted by this mode. Optional metadata support in
the wire protocol does not oblige a factory-shaped helper to accept its absence.
No missing value becomes unity.

The runtime owns copies of the descriptor and explicit maps. The original
coefficients remain in **captured-slot order**, while logical_gain[d] carries
the association coefficient[mic_map[d]] for inspection/future work. Neither
array is applied to PCM. There is no Q30 multiplication, renormalization,
Calibrator, DSP calibration claim or hidden microphone permutation. Raw input
buffers are read-only. Existing LOW24 range checking, HIGH24 arithmetic shift
and independent S16 reference multiplication by 65536 prepare the DSP words.

## Exchange and terminal behavior

All synthetic DSP initialization is completed before HELLO. The child emits
ASP2, reads one CFG2, then ACK2 ACCEPT with state code **299** and text:
"Synthetic only; factory qualification unavailable". REJECT is terminal;
stdout contains protocol bytes only. Stderr logs static availability,
representation, channel counts, selection and gain authority, never coefficients.

The existing bounded 8 ms / 20 ms FIFO is shared. Sequence starts at zero.
The first reply is NotReady with origin UINT64_MAX and no PCM; subsequent DATA
contain 320 S16 samples with origins 0,320,640,..., one capture tick delayed.
The synthetic backend hashes all six converted channels of every native frame;
its deterministic output tests framing and association, not audio quality.

Wrong magic, sequence, repeated CFG2, changed lengths, partial input header or
payload produce one terminal RSP2 523, no PCM and exit. DSP failure or invalid
LOW24 PCM produces terminal 503, including a failure after earlier quanta in
the same request. Sequence/origin arithmetic is guarded before overflow.
A clean input EOF discards carry without a tail. SIGTERM/SIGPIPE stop the
process; crash/hang recovery, deadlines, reaping and stock fallback remain
host responsibilities. The child cannot enforce a deadline while its input
sender stalls. No automatic child restart occurs.

## Verification

```sh
CFG2_BUILD_DIR=/absolute/private/parser bash tools/external-asp/tests/run_cfg2.sh
OUT_DIR=/absolute/private/build bash tools/external-asp/tests/run_cfg2_runtime.sh
ASP2_BUILD_DIR=/absolute/private/build ASP2_TEST_DIR=/absolute/private/fixtures \
  ASP2_LONG=1 python3 tools/external-asp/tests/test_bridge.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -v -s tools/frankenasp/tests
```

Runtime tests include native C numerical/ownership assertions, all 24 MIC x 2
REF permutations x LOW/HIGH, an independent Python per-sample oracle, all six
goldens and every prefix truncation, header rejection without waiting for a body,
8192 bytes/64 TLVs, unknown optional/required tags, exact pipelining, short
syscalls/EINTR, immutable session, extreme Q30 and MIC/REF values, sequence/origin,
NotReady, terminal faults, fresh sessions and bounded IPC stress.
ASan/UBSan cover both C numerical tests and the complete real-pipe suite.
Native RSS stability is checked separately; ASan shadow-page growth is logged,
not compared to the native fixed-RSS threshold.

For integration, tests/run_s1b_cfg2.sh requires TECHO5_S1B_ROOT at pinned
1a5b0fefd2b2e19161ba7dadf6b6d8b92cd2362c, ASP2_BUILD_DIR, an explicit GO binary
and offline GOMODCACHE. A Go overlay adds the committed test to the compiler's
view only; it creates no file in TECHO5. Real S1-B host pipes/deadlines run
against this C ELF, including LOW/HIGH, identity/explicit maps, fragmented
syscalls, exact independent Go PCM oracle, ACK warning, NotReady/origins,
reject/fatal/crash/hang, reaping and fixed-packet rejection. It repeats under -race.
This exercises the internal CFG2 host seam, not production secure admission.

Native timing is trainer evidence only, never an ARM32 or device guarantee.
No production activation or real factory calibration authority is implemented.
