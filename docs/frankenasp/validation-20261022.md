# Franken ASP validation checkpoint — 2026-10-22

**Historical validation checkpoint:** the original list of "still unverified" steps below reflects **22 October 2026**, before the later native-device and [controlled wake-word comparison](acoustic-results-20261023.md). It is retained as dated engineering evidence, not the current research qualification or a replacement for the independent [research mission](README.md).

This document records **only checks actually executed** for the first
research-preview branch. It must not be read as live-device qualification.

## Base and scope

- Upstream TECHO5 base: `f523881099c958a77d1b31730050c585018f1488`.
- Development branch: `experimental/athena-factory-asp`.
- Existing Athena AFE DI2 and hardware AWB kernel patches are inherited.
- The former custom stereo patch was not transferred.
- No original factory binaries, recordings, IDME coefficient values, or
  complete Bionic runtime were committed.

## Passed checks

| Check | Result |
|---|---|
| Go mic package: `go test -p 1 -vet=off ./internal/hardware/mic -count=1` | PASS |
| Full echod module: `go test -p 1 -vet=off ./... -count=1` | PASS |
| Linux/arm64 static cross-build of `./cmd/echod` | PASS |
| Python synthetic IPC/Q30-format unit tests | 3/3 PASS |
| Python script compilation and shell syntax checks | PASS |
| Owner-image dependency extraction replay | 53 ELF objects; 0 unresolved sonames |
| Owner-image audio config extraction replay | 37 files |
| Local `sh-native` preparation via `patchelf` | PASS: expected interpreter |
| Public branch file inventory | Only authored text sources, tests and Markdown |

The compiled ARM64 test executable was **not distributed**. For local evidence
only, its SHA-256 is:

`bee258c2a86ed048ffa2fad3103e036019bff3e67bbf4ca2047f3da90cc01df2`

## Read-only device inspection

The test device was left running the official daemon from
`/usr/local/bin/techo5`. The experimental enable marker was absent.
The checked hardware AWB UL2_CH1/DL1_CH1 switch was off. Existing Bionic
runtime files were present. No installed binary, system setting, partition
or kernel was changed during this checkpoint.

## Still unverified / blocking live opt-in

1. Compile the ARM32 worker with the published Android NDK script on a clean
   participant machine; exercise original Bionic loader and native exports.
2. Validate on-device `libasp.so` startup and the exact 6-channel capture
   with 8-ms worker IPC on the newly built ARM64 daemon.
3. Add an **atomic, auditable, reversible** binary/service selection mechanism,
   with stock binary preserved and effective runtime status verified.
4. Validate clean ALSA AWB unroute, worker timeout/crash recovery and watchdog;
   investigate the earlier unexplained MT8183 AFE IRQ anomaly.
5. Measure CPU, XRUN, reference latency and real-world controlled MWW/ASR
   performance without publishing private audio.

**No live Franken DSP activation is approved by these checks.**
