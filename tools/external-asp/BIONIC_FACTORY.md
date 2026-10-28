# I1 genuine ARM32/Bionic factory child — offline qualified only

The bionic-factory target builds /factory/asp2-child with the original
/system/bin/linker interpreter. It loads unchanged /vendor/lib/libasp.so.
It has no CLI flags, mock selector or environment-controlled bypass.
The native Linux launcher remains separate and unchanged. Nothing installs,
activates or acoustically qualifies this child on an Echo.

## Private build

Use an existing ARM32 GCC/binutils toolchain and matching owner-extracted
Android 9 system/vendor runtime. No downloads, Android ELF patches, SDK libc
substitutes or Linux libc are involved.

    OUT_DIR=/absolute/private/build/bionic \
    BIONIC_ROOT=/absolute/private/original-runtime \
    BIONIC_CC=/absolute/toolchain/arm-linux-gnueabihf-gcc-13 \
    BIONIC_LD=/absolute/binutils/arm-linux-gnueabihf-ld \
    bash tools/external-asp/build.sh bionic-factory

Locally unpacked binutils may require its private host LD_LIBRARY_PATH while
building. BIONIC_ROOT/system/lib must contain the original libc.so, libdl.so
and ld-android.so. Preserve original dependency closure/configs at runtime.
The script uses freestanding GCC standard integer/size headers and our narrow
Android 9 libc declarations; it never uses Linux libc headers, CRT or libraries.
The C-only CRT calls original Bionic __libc_init. Output is ARMv7-A, softfp
AAPCS, PIE, ELF32 little-endian ARM EABI5, with the exact Bionic interpreter,
RELRO, immediate relocations and non-executable stack. The separate launcher
uses the native Linux ABI, not these flags. Save compiler/binutils/runtime
identity and child ELF/SHA with each private build; no runtime-wide hash policy
is added.

Only the real build links factory.c. It resolves all six exports before
asp_init and delegates lifecycle, canaries, exact counts and timestamp bounds
to the same factory_adapter used by the independent native mock. A failed
init has not acquired initialized ownership; successful init is deinitialized
once, and acquired pipelines are destroyed once even if later setup fails.
dlclose follows teardown. Fatal signals/host SIGKILL cannot promise teardown.

## Immutable captured-slot routing

The root-owned installed rootfs must additionally contain this strict regular
file at /factory/channel-map, without symlink components or group/world write.
It is read once before vendor initialization. Missing/invalid permutations
fail before HELLO; there is no default physical microphone mapping.

    ASP2-CHANNEL-MAP-V1
    mic=0,1,2,3
    ref=0,1

The example explicitly preserves captured slot order, not microphone geometry.
Each list means factory logical destination d receives captured slot list[d].
An owner-qualified nonidentity profile could instead use mic=2,0,3,1 and
ref=1,0. It must match the factory channel/IDME association; this code does not
discover physical positions or rewrite vendor calibration paths. I2 must stage
a qualified map together with the immutable runtime and launcher profile.

A single CFG2/TLV requires CONFIRMED athena, MIC4 S32 signed24 LOW or HIGH at
96k/1920 frames, REF2 S16 L/R at 96k/1920 frames, stream flags 7 and COMPLETE
captured-slot IDME normalized Q30 metadata. The existing strict decoder rejects
malformed known/unknown required fields and safely skips unknown optional TLVs.
No legacy fixed40 is accepted. Metadata and maps are snapshotted for the session.
Q30 association follows the MIC permutation in memory; Q30 NEVER multiplies PCM.
The factory Calibrator reads original /proc/idme/miccal.0..3 through the unchanged
launcher's verified aliases to read-only real sysfs. No gain values are logged,
normalized again, invented or written by the child.

## DSP and wire

The child preserves the original pipes, duplicates the binary wire descriptor,
then redirects fd1 to stderr BEFORE dlopen or any vendor init. Vendor stdout
chatter cannot enter the wire. asp_init, ASR pipeline creation and reference
status 2 complete before the four-byte ASP2 ready HELLO. Failure before readiness
exits without HELLO. Then CFG2 -> ACK2 -> immutable INP2/RSP2 uses the existing
reader, decoder, numerical conversion and FIFO, without an additional processor.

The recovered ASR ABI is type0, PCM8.24 format4, six interleaved signed32 words,
96kHz input -> PCM16 format1, mono16kHz output. MIC LOW is signed low24; HIGH
is arithmetic-shifted by 8 into low24. Each independently routed signed16 REF
is promoted by 65536 into full signed32, preserving both channels. Per call:
768 input frames ->128 output frames; both buffer boundaries and input mutation
are checked. A timespec32 value starts at zero and advances exactly 8ms with
overflow checks; delay argument remains the established research value zero.
Reference status2 does not synchronize physical clocks or establish real delay.

The first 20ms tick yields NotReady. Each later completed tick yields exactly
320 mono samples, with origin0 then increments of320 and unchanged request
sequence. Partial I/O/EINTR are handled by the shared pipe routines. Bad config,
framing/counts/vendor status/canary or timestamp failure is terminal. Cooperative
signal handling can stop work that returns to our code; it cannot interrupt a
hung proprietary function reliably. TECHO5 owns deadlines, SIGKILL and sole Wait.

## Validation and limits

The existing isolated full-system QEMU lab ran this executable directly through
the original Bionic interpreter, with unchanged original libasp/configs, real
stdin/stdout pipes and synthetic inputs/calibration fixtures only. Private I1
evidence records zero/nonzero MIC and independent REF, LOW/HIGH, explicit
permutations, NotReady/origins, optional/required TLVs, malformed config, fatal
framing/sample errors, missing map/library and host kill/reap.

Keep independent mock numerical/ABI/fault tests separate from real-vendor
execution evidence. Existing native/sanitizer/FIFO and accepted TECHO5 host
fallback tests remain applicable; mock fault injection cannot establish how an
arbitrary vendor hang responds to SIGTERM.

TECHO5's 500ms HELLO and 25ms exchange budgets are unchanged. QEMU observation
uses a separate slow lab driver and records initialization/exchange wall time;
the emulated factory exceeds these budgets, and the 500ms lab supervision case
kills/reaps it without an early HELLO. QEMU timings do not predict native Athena.
Actual compiled launcher/execveat, genuine hardware IDME association, timing,
live MIC/REF clock alignment and acoustic quality remain separate DEVICE GO
gates. I2 installer, OTA acquisition, device installation and public publication
are outside I1.
