# Owner-local Franken ASP tools

**Purpose:** provide the worker and guarded staging/recovery utilities for
**independent, reproducible objective and subjective A/B comparisons** of
TECHO5's open microphone frontend and Athena's original factory ASP.
They are **measurement-enabling tools, not a recommended replacement
voice stack**. Only limited wake-word experiments have been completed;
subjective listening and post-wake STT comparisons remain future work.

See [research documentation](../../docs/frankenasp/README.md).
Keep all extracted factory components in gitignored vendor-local/.
These tools do not enable the live native DSP by themselves.
Use prepare_runtime.sh only for owner-local staging; it does not install to an Echo.

For the currently supported Athena research configuration, use `python3 install.py --backup-partitions DIR --device root@ECHO` for a read-only compatibility check; use `--install` **only** when deliberately staging your own ELF runtime and independently built worker/TECHO5 experimental binary. It does not activate the ASP. Full instructions: [installation.md](../../docs/frankenasp/installation.md).

Optional *reboot-persistent* Athena operation is a separate, explicit stage:
`build_experimental.sh` stamps a comparable version, and on-device
`persist.sh {install-hook|enable|disable|uninstall-hook|status}` manages a
reversible hook for the current A/B slot only. The guard rejects stock
rootfs updates until the owner disables persistence and reboots. See the
installation guide; no hook or persistent marker is installed by default.

The optional TECHO5 integration daemon is now built from the separate `frankenasp-adapter` branch. Pass `TECHO5_ADAPTER_ROOT=/absolute/path/to/techo5-adapter` to `build_experimental.sh`. See [the split contract](../../docs/frankenasp/adapter.md).
