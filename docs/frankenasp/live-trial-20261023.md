# Franken ASP guarded live test — 2026-10-23

The owner-authorized Echo Show 8 Gen 2 test used a temporary bind-mounted experimental ARM64 TECHO5 daemon and a native ARM32/Bionic Amazon ASP worker. The device's current speaker volume, audio settings and music playback were not changed by the test.

- Trial began at 00:27:42 (Europe/Riga), with an independently running rollback watchdog and a 90-second timeout.
- Native ASP worker PID 5300 was confirmed in the running process, with factory audio capture using four microphones and stereo hardware AWB.
- One capture overrun was logged at initialization; no sustained overrun series was established during the observation.
- Watchdog initiated the timeout rollback at 00:29:12 and completed it at 00:29:14.
- The temporary bind mount, requested-mode marker and runtime arming marker were gone. The official TECHO5 binary SHA-256 matched its pretest checksum, and the official service respawned as PID 9883.
- Both UL2/DL1 AWB recording routes were verified off after rollback.

This confirms the first time-limited native worker activation and timed stock recovery. It does **not** establish production readiness, AEC superiority, wake-word quality, thermal stability or successful deliberate worker-crash recovery. The guard and IPC-hardening changes have been tested locally but are not part of this documentation-only commit.
