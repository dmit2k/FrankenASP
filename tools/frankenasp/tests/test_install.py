"""Synthetic installer checks: no real SSH writes, no factory payloads."""
import contextlib
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import install


class SetupTests(unittest.TestCase):
    def make_backup(self, folder, with_manifest=True):
        image = folder / "p21-system.img"
        with image.open("wb") as fd:
            fd.truncate(65 * (1 << 20))
        if with_manifest:
            digest = install.pf.sha256_file(image)
            (folder / "SHA256SUMS").write_text(digest + "  p21-system.img\n")
        return image

    def test_explicit_directory_with_valid_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            image = self.make_backup(p)
            returned, verified = install.read_backup(p)
            self.assertEqual(image, returned)
            self.assertTrue(verified)

    def test_no_image_autodiscovery(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            sub = root / "partitions"
            sub.mkdir()
            self.make_backup(sub)
            with self.assertRaisesRegex(ValueError, "p21-system.img"):
                install.read_backup(root)

    def test_refuses_wrong_checksum(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.make_backup(root)
            (root/"SHA256SUMS").write_text("0" * 64 + "  p21-system.img\n")
            with self.assertRaisesRegex(ValueError, "does not match"):
                install.read_backup(root)

    def test_missing_checksum_requires_explicit_override(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.make_backup(root, with_manifest=False)
            with self.assertRaisesRegex(ValueError, "accept-unverified-backup"):
                install.read_backup(root)
            _, verified = install.read_backup(root, accept_unverified=True)
            self.assertFalse(verified)

    def test_rejects_postflash_system_version(self):
        fake_prop = "ro.build.id=TECHO5\nro.product.device=athena\nro.build.version.sdk=28"
        with mock.patch.object(install, "debugfs", return_value=fake_prop):
            with self.assertRaisesRegex(ValueError, "differs"):
                install.verify_factory_image(Path("dummy"))

    def test_correct_p21_image_paths_and_inventory(self):
        fake_prop = ("ro.build.id=PS75741.7080N\n"
                     "ro.product.device=athena\nro.build.version.sdk=28")
        with mock.patch.object(install, "debugfs", return_value=fake_prop), \
             mock.patch.object(install.pf, "original_system_image",
                               return_value=dict.fromkeys(install.FACTORY_SYSTEM_FILES, True)):
            result = install.verify_factory_image(Path("unused"))
        self.assertEqual(result["ro.build.id"], "PS75741.7080N")
        self.assertEqual(len(install.FACTORY_SYSTEM_FILES), 47)

    def test_reject_unknown_vendor_revision(self):
        vendor = dict.fromkeys(install.pf.VENDOR_FILES, True)
        with mock.patch.object(install.pf, "ssh_vendor", return_value=(vendor, "a" * 64)):
            with self.assertRaisesRegex(ValueError, "identity"):
                install.validate_device("root@example")

    def test_refuses_non_athena_arch(self):
        vendor = dict.fromkeys(install.pf.VENDOR_FILES, True)
        responses = ("armv7l\n6.1-athena\nro,relatime\n" + "CLEAR\n" * 4 + "ABSENT\n" * 2).encode()
        with mock.patch.object(install.pf, "ssh_vendor",
                               return_value=(vendor, install.pf.TESTED_ASP_SHA256)), \
             mock.patch.object(install, "ssh", return_value=responses):
            with self.assertRaisesRegex(ValueError, "AArch64"):
                install.validate_device("root@example")

    def test_existing_stage_marks_install_unavailable(self):
        vendor = dict.fromkeys(install.pf.VENDOR_FILES, True)
        responses = ("aarch64\n6.18-athena\nro,relatime\n" +
                     "CLEAR\n" * 4 + "EXISTS\nABSENT\n").encode()
        with mock.patch.object(install.pf, "ssh_vendor",
                               return_value=(vendor, install.pf.TESTED_ASP_SHA256)), \
             mock.patch.object(install, "ssh", return_value=responses):
            result = install.validate_device("root@example")
        self.assertTrue(result["runtime_already_exists"])

    def test_prepare_bundles_disabled_persistence_and_hashes(self):
        # Only synthetic native sources; never extract real factory files.
        with tempfile.TemporaryDirectory() as d:
            stage = Path(d) / "stage"
            binary = Path(d) / "fake-arm64-binary"
            binary.write_text("synthetic fork")
            def fake_extract(_image, payload):
                sysroot = payload / "amazon-arm32/system/bin"
                sysroot.mkdir(parents=True)
                (sysroot/"sh-native").write_text("fake bionic")
            def fake_worker(payload, _worker, _ndk):
                (payload/"amazon-arm32/libasp_stream_worker.so").write_text("fake worker")
            with mock.patch.object(install, "extract_system", side_effect=fake_extract), \
                 mock.patch.object(install, "make_worker", side_effect=fake_worker), \
                 mock.patch.object(install, "make_native_shell"), \
                 mock.patch.object(install, "assert_arm_elf"):
                payload = install.prepare(Path("fake.img"), stage, None, None, binary)
            trial = payload / "frankenasp-trial"
            for name in ("persist.sh", "persistent-run.sh", "persist-watch.sh"):
                self.assertTrue((trial/name).is_file())
                self.assertIn(name, (trial/"SHA256SUMS").read_text())
            self.assertFalse((stage/"frankenasp-persistent.enabled").exists())
            self.assertFalse((payload/"fireos-asp.enabled").exists())

    def test_install_keeps_factory_mode_off(self):
        with tempfile.TemporaryDirectory() as d:
            payload = Path(d)/"device"
            (payload/"amazon-arm32").mkdir(parents=True)
            (payload/"frankenasp-trial").mkdir()
            (payload/"amazon-arm32"/"test").write_text("synthetic test bytes")
            (payload/"frankenasp-trial"/"test").write_text("synthetic test bytes")
            calls = []
            def fake_ssh(target, command, **kwargs):
                calls.append(command)
                return b""
            with mock.patch.object(install, "ssh", side_effect=fake_ssh), \
                 mock.patch.object(install.subprocess, "run",
                                   return_value=mock.Mock(returncode=0, stderr=b"")):
                result = install.install("root@example", payload, nonce="abcd1234")
            self.assertFalse(result["activated"])
            self.assertFalse(result["official_daemon_modified"])
            import tarfile
            with tarfile.open(payload.parent / "device-payload.tar") as arc:
                for member in arc.getmembers():
                    self.assertEqual((member.uid, member.gid), (0, 0))
            self.assertTrue(any("sha256sum -c" in command for command in calls))
            self.assertTrue(any("test ! -e" in command for command in calls))
            self.assertFalse(any("mount --bind" in command or "techo5-experimental start" in command
                                 or "touch " in command for command in calls))


if __name__ == "__main__":
    unittest.main()
