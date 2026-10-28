# External ASP2 (offline qualification only)

The genuine ARM32/Bionic child is now built by `build.sh bionic-factory`.
See [BIONIC_FACTORY.md](BIONIC_FACTORY.md) for original-runtime requirements,
explicit captured-slot routing, single Calibrator gain authority, wire behavior
and limits. It reuses the CFG2/TLV decoder, FIFO and guarded factory adapter.
Actual original-libasp execution is evidenced in the private I1 QEMU lab;
no Echo deployment, native deadline or acoustic qualification is implied.

The separate `native-test` target retains the closed `main.c` diagnostic
(ACK524 for valid sessions, ACK522 for malformed CFG2). It never loads vendor
DSP. `cfg2-synthetic` and `cfg2-factory-mock` remain independent native test
executables; their explicit test flags cannot select a backend in the Bionic
child. Native/sanitized numerical, ABI-fault, FIFO and host fallback suites
remain under tests/. Use OUT_DIR, CFG2_BUILD_DIR, ASP2_BUILD_DIR and ASP2_TEST_DIR
outside the repository; ASP2_LONG=1 enables 100k synthetic TLV exchanges.

The only wire configuration is CFG2/TLV as described in the byte-identical
protocol snapshot ../../docs/frankenasp/ASP2_PROTOCOL.md. No fixed40 downgrade.
The native Linux ARM32 launcher is documented in launcher/README.md; its source
is unchanged in I1. It does not link the historical FD4 asset closure. No
runtime-wide SHA manifest, snapshots or duplicate runtime copies are required.
Installation and hardware activation remain separate stages.

## I2-S selective owner installer (offline only)

See [INSTALLER.md](INSTALLER.md) for the new ASP2 inspect/build/prepare/dry-run/
install/status/rollback/uninstall/helpers CLI, selective ext4/Brotli extraction,
explicit backup-dir or local/HTTP(S) OTA, opted-in helper maintenance and open
timing/device gates. Source trust belongs to the user; no mandatory source
SHA/origin/fingerprint or HTTPS certificate gate. This does not activate external ASP.
