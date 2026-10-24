"""Synthetic-only tests of Athena preflight inventory logic."""
import importlib.util
from pathlib import Path
from unittest import mock
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "preflight.py"
spec = importlib.util.spec_from_file_location("preflight", SOURCE)
pf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pf)


class PreflightTests(unittest.TestCase):
    def test_expected_athena_closure(self):
        self.assertEqual(len(pf.VENDOR_FILES), 7)
        self.assertEqual(len(pf.SYSTEM_LIBS), 41)
        self.assertEqual(len(pf.REQUIRED_SYSTEM), 43)
        self.assertEqual(len(set(pf.SYSTEM_LIBS)), 41)

    def test_fully_present_private_runtime(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for path in pf.REQUIRED_SYSTEM:
                full = root / "system" / path
                full.parent.mkdir(parents=True, exist_ok=True)
                full.write_bytes(b"synthetic content")
            vals = pf.local_files(root, pf.REQUIRED_SYSTEM, "system")
            self.assertTrue(all(vals.values()))
            summary = pf.evaluate(dict.fromkeys(pf.VENDOR_FILES, True), runtime=vals, sha=pf.TESTED_ASP_SHA256)
            self.assertEqual(summary["next_action"], "static_files_present_review_abi_and_trial_guards")

    def test_vendor_present_with_original_backup(self):
        vendor = dict.fromkeys(pf.VENDOR_FILES, True)
        backup = dict.fromkeys(pf.REQUIRED_SYSTEM, True)
        summary = pf.evaluate(vendor, system_backup=backup, sha=pf.TESTED_ASP_SHA256)
        self.assertEqual(summary["next_action"], "extract_matching_arm32_system_to_owner_private_runtime")
        self.assertEqual(summary["system_backup_missing"], [])

    def test_unknown_factory_hash_is_not_qualified(self):
        vendor = dict.fromkeys(pf.VENDOR_FILES, True)
        complete = dict.fromkeys(pf.REQUIRED_SYSTEM, True)
        result = pf.evaluate(vendor, runtime=complete, sha="a" * 64)
        self.assertEqual(result["next_action"], "factory_revision_unvalidated_do_not_enable")
        self.assertFalse(result["tested_factory_libasp_sha256_match"])

    def test_unreadable_factory_identity_is_not_qualified(self):
        vendor = dict.fromkeys(pf.VENDOR_FILES, True)
        complete = dict.fromkeys(pf.REQUIRED_SYSTEM, True)
        result = pf.evaluate(vendor, runtime=complete, sha=None)
        self.assertEqual(result["next_action"], "factory_revision_unvalidated_do_not_enable")
        self.assertIsNone(result["tested_factory_libasp_sha256_match"])

    def test_unavailable_original_system(self):
        summary = pf.evaluate(dict.fromkeys(pf.VENDOR_FILES, True), sha=pf.TESTED_ASP_SHA256)
        self.assertEqual(summary["next_action"], "find_first_install_fireos_p21_system_backup")
        self.assertFalse(summary["system_backup_checked"])

    def test_does_not_misreport_incomplete_vendor_as_ready(self):
        vendor = dict.fromkeys(pf.VENDOR_FILES, True)
        vendor["lib/libasp.so"] = False
        summary = pf.evaluate(vendor, runtime=dict.fromkeys(pf.REQUIRED_SYSTEM, True))
        self.assertEqual(summary["next_action"], "investigate_vendor_partition_without_writing")

    def test_debugfs_path_only_check_via_mock(self):
        # Does not open an actual Fire OS partition image.
        with tempfile.TemporaryDirectory() as d:
            image = Path(d) / "synthetic.img"
            image.write_bytes(b"test image mock")
            def fake_run(argv, **_kw):
                return mock.Mock(stdout="Inode: 8   Type: regular    Size: 1\n"
                                        if argv[2] == "stat /system/lib/libc.so" else "File not found")
            with mock.patch.object(pf.subprocess, "run", side_effect=fake_run):
                result = pf.original_system_image(image, ("lib/libc.so", "bin/linker"))
            self.assertTrue(result["lib/libc.so"])
            self.assertFalse(result["bin/linker"])


if __name__ == "__main__":
    unittest.main()
