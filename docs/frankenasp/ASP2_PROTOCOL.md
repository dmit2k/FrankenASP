# External ASP2: session configuration and PCM transport (draft protocol revision)

**Status: DESIGN SPECIFICATION ONLY — NOT IMPLEMENTED.** Dated 2026-10-27.
Protocol identity remains **ASP2**, wire version **2**. This is a one-time
pre-release incompatible update to the previous fixed 40-byte CFG2.
Do not use this document to claim that existing TECHO5 or FrankenASP binaries
already implement these rules. Rebuild and test all participants together.

The canonical copy is held in TECHO5 (`docs/external-asp/ASP2_PROTOCOL.md`).
A byte-identical snapshot is included in FrankenASP
(`docs/frankenasp/ASP2_PROTOCOL.md`) for independently authored providers.
Update both copies as one change and verify SHA-256 equality.

## 1. Ownership and invariant audio contract

TECHO5 is the **sole hardware capture owner**. An ASP2 child receives unchanged
native MIC PCM and, when present, native playback-reference PCM, together with
a fixed description of their stream formats, channel order, platform codename
(where known) and available factory calibration metadata. TECHO5 does not apply factory microphone gain/Q30, alter
interchannel ratios, reorder captured slots, resample, run extra AEC or silently
synthesize a reference before sending input.

Channel positions in all metadata refer to **captured MIC slots**, numbered
0..N-1 in the MIC PCM stream. A helper is free to permute MIC slots internally,
but MUST carry each slot's associated calibration along with it. Hardware
capture order is not a claim of physical microphone geometry. Optional or
unknown calibration never becomes an implied gain of one.

All integer wire fields are little-endian. Sessions are immutable: one CFG2,
one accepted ACK2, then an ordered sequence of INP2/RSP2 exchanges. A helper
MUST NOT reinterpret subsequent PCM based on changes to filesystem profiles or
device metadata during a session.

## 2. Startup and transport

- Stdin/stdout are exact, byte-oriented, full-duplex local pipes. Stderr is
  diagnostic only; stdout MUST contain exclusively protocol bytes.
- Child emits four bytes `ASP2` within the existing 500 ms startup deadline.
- TECHO5 sends one bounded CFG2 with all relevant session descriptors. Child
  responds with the existing ACK2 or a terminal REJECT, then processing begins.
- Existing INP2 and RSP2 envelopes, PCM-origin/sequence rules, 20 ms capture
  frame semantics, 320-sample 16 kHz mono output, and the 25 ms per-exchange
  deadline remain unchanged for the current Athena implementation.
- CFG2 parsing, ACK2 and the first INP2/RSP2 exchange are subject to the
  existing single 25 ms first-exchange budget. A helper with expensive DSP
  initialization MUST preinitialize before HELLO or use a separately designed
  future non-capture-thread readiness mechanism. Do not relax these budgets
  or block the capture loop while loading vendor DSP.
- A helper that only understands the *previous* 40-byte CFG2 is **not**
  compatible with this revision, despite sharing the name ASP2. It must be
  rebuilt. The new header deliberately distinguishes old/new lengths.

## 3. CFG2 binary envelope

Header is exactly **16 bytes**:

| Offset | Type | Field | Rule |
|---:|---|---|---|
| 0 | char[4] | magic | ASCII `CFG2` |
| 4 | u16 | version | 2 |
| 6 | u16 | header_bytes | 16 |
| 8 | u32 | total_bytes | 16..8192, includes header and all TLVs |
| 12 | u32 | stream_flags | bit 0 interleaved, bit 1 synchronized, bit 2 hardware REF; unknown bits MUST reject |

The receiver first reads 16 bytes, validates length and flags **before any
variable allocation**, then reads exactly `total_bytes-16`. Limits:
`MAX_CFG_BYTES=8192` and `MAX_TLVS=64`. No padding, CRC, JSON, reserved tail,
nested TLVs or indefinite lengths in this revision.

Each following TLV has an eight-byte header:

| Offset within TLV | Type | Field | Rule |
|---:|---|---|---|
| 0 | u16 | type | registered type ID, not zero or 0xffff |
| 2 | u16 | flags | bit 0 = REQUIRED; all other bits MUST be zero |
| 4 | u32 | value_bytes | exact following payload length |
| 8 | byte[] | value | bounded by remaining CFG2 bytes |

TLVs MUST appear in **strictly increasing numerical type order**: no
duplicates or out-of-order entries, including unknown optional types.
Unknown OPTIONAL TLVs are safely skipped. Unknown REQUIRED TLVs cause
an explicit terminal configuration REJECT. A recognized TLV with an
invalid length/version/representation always causes REJECT, regardless of
its REQUIRED bit. A recognized required core TLV MUST be present exactly
once. Unrecognized bytes after the declared total length belong to the
next protocol message and are never consumed by CFG2 parsing.

Helpers MUST reject configuration and suppress PCM output when required
capabilities, stream shape, calibration or metadata interpretations
cannot be supported. Support for optional calibration is NOT compulsory
for a generic ASP2 helper.

## 4. Registered TLV types (this revision)

| Type | Name | Required by protocol | Value |
|---|---|---|---|
| 0x0001 | MIC_STREAM | yes; REQUIRED flag=1 | 16-byte Stream descriptor |
| 0x0002 | REF_STREAM | yes; REQUIRED flag=1 | 16-byte Stream descriptor, all zero when REF absent |
| 0x0003 | PLATFORM_INFO | no; REQUIRED flag=0 | Board/platform codename and detection confidence (not a unique ID) |
| 0x0101 | MIC_FACTORY_GAIN | no; REQUIRED flag=0 | Explicit factory gain availability and channel-aligned values |

All other type IDs are unassigned. Future authors MUST reserve identifiers
without reinterpretation. Suggested future categories: 0x1000..0x1fff
array geometry/orientation; 0x2000..0x2fff timing/reference properties;
0x3000..0x3fff factory diagnostics or extensions. Experimental vendor-specific
extensions must be uniquely namespaced in their payload and documented.
No factory DSP model blobs, proprietary library payloads or arbitrary
filesystem paths are sent in the handshake.

### Stream descriptor (16 bytes each)

| Offset | Type | Meaning |
|---:|---|---|
| 0 | u16 | channel count |
| 2 | u16 | PCM frames per 20 ms |
| 4 | u32 | sample rate in Hz |
| 8 | u8 | sample format: 1=S16, 2=S32 |
| 9 | u8 | full_bits (signed magnitude exponent; current definition) |
| 10 | u8 | alignment: 0=low, 1=high |
| 11 | u8 | valid_bits |
| 12 | u32 | reserved; MUST be zero |

MIC channels must be 1..16, REF channels 0..8. Rate 8000..192000,
divisible by 50; frames must equal rate/50. Existing valid-bits and
full-bits rules from TECHO5 `internal/asp/protocol.go` remain in force:
for low alignment, full_bits=valid_bits-1; for high alignment,
full_bits=storage_width-1. All sample sizes/payloads MUST be checked
against the existing 256 KiB INP2 cap.

An absent REF is represented explicitly by 16 zero bytes in REF_STREAM
and stream_flags=1. A present native hardware REF requires
stream_flags=7 and a fully valid descriptor. Helpers can refuse absent
REF (e.g. real AEC), but cannot invent hardware reference samples.

### PLATFORM_INFO schema v1

Platform identification is optional **routing metadata**, not an audio
format guarantee and not an authentication/security principal. The host
SHOULD emit it when its device identification is available. The helper
MAY choose a profile, board-specific DSP model or algorithm family using
this field, but MUST still validate the actual MIC_STREAM, REF_STREAM,
reference synchronization and other capabilities independently.

The payload length is `4 + codename_bytes`, with a 4-byte prefix:

| Offset | Type | Meaning |
|---:|---|---|
| 0 | u8 | schema_version = 1 |
| 1 | u8 | detection: 1=CONFIRMED, 2=INFERRED/FALLBACK |
| 2 | u8 | codename_bytes = 1..32 |
| 3 | u8 | reserved = 0 |
| 4 | byte[] | codename as lowercase ASCII, exactly codename_bytes |

Codename characters are strictly `[a-z0-9_-]`. No terminating NUL,
no UTF-8 multibyte strings, no display names, serial numbers, MAC
addresses, product IDs, model-specific user settings or raw vendor data.
The identifier names a hardware board/platform (for example `athena`,
`cronos`, `crown`, `checkers`, `biscuit`, `radar`, `donut` or `rook`),
NOT the CPU architecture, operating system or current DSP backend.
An unknown-but-syntactically-valid codename is allowed. Absence of this
optional TLV means platform information was not advertised, **not** a
known default platform.

On TECHO5, `layout.Board` is the candidate codename. `layout.BoardDoubt`
can identify a fallback/guessed board where implemented. The host MUST
use INFERRED when it cannot substantiate board identification; do not
treat an absent BoardDoubt string as proof of identification for all
future device ports. Do not transmit the free-form BoardDoubt string.

Helpers that do not need board identity MUST be able to ignore this
optional TLV. A helper that requires a specific board (e.g. factory
Athena assets) MUST explicitly reject missing/unknown/inferred or
mismatched board identity according to its policy; it MUST NOT select a
different vendor blob merely because a user-supplied codename matches.
Platform name is advisory, not permission to load unverified assets.

### MIC_FACTORY_GAIN schema v1

TLV payload starts with **16 bytes**:

| Offset | Type | Meaning |
|---:|---|---|
| 0 | u16 | schema_version = 1 |
| 2 | u8 | encoding: 0 when NONE, 1 = signed-i64 normalized Q30 |
| 3 | u8 | availability: 0=NONE, 1=COMPLETE, 2=PARTIAL |
| 4 | u8 | provenance: 0=none, 1=factory IDME |
| 5 | u8 | applied_to_pcm: MUST be 0 |
| 6 | u16 | mic_channels: MUST match MIC_STREAM |
| 8 | u32 | present_mask: bit i marks captured MIC slot i |
| 12 | u32 | reserved: MUST be 0 |

For NONE: encoding=0, provenance=0, present_mask=0, payload length 16.
For COMPLETE/PARTIAL: encoding=1, provenance=1, payload length
`16+8*mic_channels`; signed-i64 little-endian normalized-Q30 coefficients
follow in captured-slot order. Masked-out entries MUST be zero. Each
present value MUST be a positive Q30 gain valid for the platform.
A COMPLETE mask must contain all channel bits; PARTIAL must contain a
nonempty proper subset. Bits outside declared mic channel count reject.

The TLV can be absent entirely, meaning NOT ADVERTISED. This differs
from explicit NONE (the device reports no available factory gains).
Do not label unknown or fabricated unity gains as factory calibration.

On Athena, TECHO5 already exposes genuine miccal.0..3 via layout.Idme.
The four values were verified on 2026-10-27 against eMMC boot1 and
device-tree nodes. Normalize the factory representation **once**:
parse an authentic positive decimal signed-32 value; if
`(value & 0x7fff0000)==0`, convert with `value<<16`, else retain it
as normalized Q30. Reject out-of-range, zero, negative or malformed
source values rather than silently claiming full availability.
The schema's i64 container does not grant unlimited gain range:
this factory IDME v1 representation remains bounded by a positive
signed 32-bit result after normalization. No coefficient is used to
alter MIC PCM inside TECHO5.

A helper that cannot parse MIC_FACTORY_GAIN may skip it because it is
OPTIONAL; it still receives raw MIC samples. Helpers requiring gains
must explicitly reject NONE, PARTIAL, NOT ADVERTISED or unsupported
encodings as a helper-specific capability failure. A factory ASP
MUST avoid double application (helper and vendor Calibrator).

## 5. Channel mapping, telemetry and privacy

Factory coefficients describe captured-slot association, not
Amazon factory logical channels. A helper mapping `logical[d]=captured[s]`
must use the coefficient for captured slot `s` at that processing
position. Nonidentity MIC/REF maps and physical array geometry require
board-specific qualification; this wire contract does not establish
universal microphone placement or beamformer quality.

Log metadata availability, representation, parse success/failure,
number of channels, DSP selection and final processing authority,
but do NOT log actual owner-specific coefficients, all IDME entries,
serial numbers or calibration tables. Calibration data is shared only
with the locally launched helper, not sent to HA by default.

## 6. Rejection and compatibility contract

- Incomplete header, length overflow, bad version, unsupported header
  flags, overlong TLVs, reserved nonzero, out-of-order/duplicate TLVs,
  missing MIC/REF, unknown REQUIRED TLV or malformed calibration:
  terminal configuration rejection; do not proceed to INP2.
- Unknown OPTIONAL TLV: must skip safely, without changing PCM semantics.
- Unknown but otherwise valid board or unavailable factory gain:
  generic helper may accept raw MIC; factory-specific helper decides
  required capabilities and can reject.
- Helpers may require more than the generic minimum. They cannot
  advertise ACCEPT before satisfying their own required invariants.
- Configuration is snapshotted for a session; repeated config, mutable
  calibration, and midstream capability changes require a NEW session.
- No silent downgrade to the previous 40-byte layout. Match host/helper
  revisions in one deployment bundle and keep builtin stock fallback.

## 7. Required conformance tests before activation

Golden byte vectors and independent decoders in Go and C must cover:
minimum present/no-REF; 4MIC+2REF; complete/partial/absent factory
gain; PLATFORM_INFO confirmed Athena/inferred/absent/unknown and invalid
codename bytes, unsupported schema, duplicate PLATFORM_INFO; all 24 MIC permutations; 16-channel mask boundaries; differing
signed/legacy Q30 inputs; min/max sample amplitudes; unknown optional
TLV skipped; unknown required TLV rejected; duplicate/out-of-order
tags; truncation at each byte; total length 15, 16, 8192, 8193 and
integer overflow; unsupported streams; EINTR/partial pipe I/O;
HELLO and exchange deadlines; helper crash/restart and fallback;
exact PCM identity (no host Q30), one DSP calibration authority and
the existing 8 ms factory FIFO versus 20 ms capture tick.

The standard is a **draft specification** until the listed tests and
paired implementations pass. No hardware acceptance or GitHub release
is implied by drafting this file.
