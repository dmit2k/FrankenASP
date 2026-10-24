"""Synthetic, isolated persistence tests: no device mounts or boot edits."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1]
SYSTEM_SHA = shutil.which("sha256sum")


class PersistentSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="frankenasp-persistence-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.trial = self.data / "frankenasp-trial"
        self.runtime = self.data / "amazon-arm32"
        self.run = self.root / "run"
        self.store = self.root / "store"
        self.rootfs = self.store / "slots/b"
        self.runner = self.rootfs / "usr/local/sbin/techo5-run"
        self.live = self.root / "running/techo5-run"
        self.vendor = self.root / "vendor/lib/libasp.so"
        self.bin = self.root / "fake-bin"
        for parent in (self.trial, self.runtime / "system/bin",
                       self.run, self.runner.parent, self.live.parent,
                       self.vendor.parent, self.bin):
            parent.mkdir(parents=True, exist_ok=True)
        (self.run / "slot").write_text("b\n")
        (self.store / "active").write_text("b\n")
        (self.store / "slots/b.state").write_text("good\n")
        self.runner.write_text(
            "#!/bin/sh\nLOG=/tmp/test.log\n"
            "exec /usr/local/bin/techo5 run >> $LOG 2>&1\n"
        )
        self.runner.chmod(0o755)
        self.live.symlink_to(self.runner)
        (self.runtime / "system/bin/sh-native").write_text("#!/bin/sh\nexit 0\n")
        (self.runtime / "system/bin/sh-native").chmod(0o755)
        self.vendor.write_text("synthetic")
        binfile = self.trial / "techo5-experimental"
        binfile.write_text(
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            "  --version) echo 'echod version v1.6.0_frankenasp.test (synthetic)';;\n"
            "  run) echo EXPERIMENT_RAN;;\n"
            "esac\n"
        )
        binfile.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bin) + ":" + os.environ["PATH"])
        for name, body in {
            "uname": "#!/bin/sh\nif [ \"$1\" = -m ]; then echo aarch64; else echo 6.18-athena; fi\n",
            "mount": "#!/bin/sh\nexit 0\n",
            "sync": "#!/bin/sh\nexit 0\n",
            "sha256sum": "#!/bin/sh\n"
                         "if [ \"$1\" = " + str(self.vendor) + " ]; then\n"
                         " echo bf2a0b569d8bfb7482b2d0a4b5dfffc2601c60a92b6389e5b8839160b3119bb9"
                         "  " + str(self.vendor) + "\n"
                         "else exec " + SYSTEM_SHA + " \"$@\"; fi\n",
        }.items():
            path = self.bin / name
            path.write_text(body)
            path.chmod(0o755)
        for src in ("persist.sh", "persistent-run.sh", "persist-watch.sh"):
            text = (SOURCE / src).read_text()
            text = text.replace("/data/techo5-linux", str(self.data))
            text = text.replace("/run/techo5", str(self.run))
            text = text.replace("/store", str(self.store))
            text = text.replace("sha256sum /usr/local/sbin/techo5-run", "sha256sum " + str(self.live))
            text = text.replace("/vendor/lib/libasp.so", str(self.vendor))
            dest = self.trial / src
            if src == "persist-watch.sh":
                text = "#!/bin/sh\nexit 0\n"
            dest.write_text(text)
            dest.chmod(0o755)
        self.make_checksums(self.trial, ("techo5-experimental", "persist.sh", "persistent-run.sh", "persist-watch.sh"))
        self.make_checksums(self.runtime, ("system/bin/sh-native",))
        self.log = self.root / "techo5.log"

    def make_checksums(self, directory, names):
        parts = []
        for name in names:
            data = (directory / name).read_bytes()
            import hashlib
            parts.append(hashlib.sha256(data).hexdigest() + "  " + name)
        (directory / "SHA256SUMS").write_text("\n".join(parts) + "\n")

    def control(self, command):
        return subprocess.run(
            ["sh", str(self.trial / "persist.sh"), command],
            env=self.env, cwd=self.root, capture_output=True, text=True,
        )

    def launch(self):
        return subprocess.run(
            ["sh", "-c", ". " + str(self.trial/"persistent-run.sh") +
             "; printf 'STOCK_STARTED\\n'"],
            env=dict(self.env, LOG=str(self.log)), cwd=self.root,
            capture_output=True, text=True,
        )

    def test_install_enable_disable_and_restore(self):
        before = self.runner.read_bytes()
        self.assertEqual(self.control("status").returncode, 0)
        p = self.control("install-hook")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("FrankenASP persistent slot-local hook", self.runner.read_text())
        self.assertEqual(self.control("install-hook").returncode, 1)
        self.assertEqual(self.control("enable").returncode, 0)
        self.assertTrue((self.data / "frankenasp-persistent.enabled").exists())
        self.assertEqual(self.control("disable").returncode, 0)
        self.assertFalse((self.data / "frankenasp-persistent.enabled").exists())
        self.assertEqual(self.control("uninstall-hook").returncode, 0)
        self.assertEqual(before, self.runner.read_bytes())
        # Reinstall after clean removal reuses only an identical backup.
        self.assertEqual(self.control("install-hook").returncode, 0)

    def test_fork_once_per_boot_and_fallback_after_crash(self):
        self.assertEqual(self.launch().stdout, "STOCK_STARTED\n")
        (self.data / "frankenasp-persistent.enabled").touch()
        first = self.launch()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("EXPERIMENT_RAN", self.log.read_text())
        self.assertTrue((self.run / "frankenasp-persistent-active").exists())
        self.assertTrue((self.run / "frankenasp-persistent-attempted").exists())
        second = self.launch()
        self.assertEqual(second.stdout, "STOCK_STARTED\n")
        self.assertFalse((self.run / "frankenasp-persistent-active").exists())

    def test_prior_unconfirmed_boot_disables_persistence(self):
        (self.data / "frankenasp-persistent.enabled").touch()
        (self.data / "frankenasp-persistent-startup.pending").write_text("old-boot-id\n")
        launch = self.launch()
        self.assertEqual(launch.stdout, "STOCK_STARTED\n")
        self.assertFalse((self.data / "frankenasp-persistent.enabled").exists())
        self.assertFalse((self.run / "frankenasp-armed").exists())
        self.assertIn("previous_boot_unconfirmed", self.log.read_text())

    def test_corrupt_worker_fails_closed(self):
        (self.data / "frankenasp-persistent.enabled").touch()
        (self.runtime / "system/bin/sh-native").write_text("malformed")
        self.assertEqual(self.launch().stdout, "STOCK_STARTED\n")
        self.assertFalse((self.run / "frankenasp-armed").exists())
        self.assertIn("checksum_mismatch", self.log.read_text())

    def test_reject_unsettled_slot_and_preserve_original(self):
        original = self.runner.read_bytes()
        (self.store / "slots/b.state").write_text("trial 3\n")
        self.assertNotEqual(self.control("install-hook").returncode, 0)
        self.assertEqual(self.runner.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
