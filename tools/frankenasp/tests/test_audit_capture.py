"""Synthetic-only tests for read-only prerecorded PCM audit."""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "audit_capture.py"
spec = importlib.util.spec_from_file_location("audit_capture", SOURCE)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class ExistingCaptureAuditTests(unittest.TestCase):
    def test_valid_nonzero_awb_and_left_aligned_mics(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            # One synthetic 32-frame chunk; no private captured audio.
            frames = 32
            (root/"m.raw").write_bytes(
                struct.pack("<4i", 1 << 22, -(1 << 22), 0, (1 << 24)) * frames
            )
            (root/"r.raw").write_bytes(struct.pack("<2h", 100, -200) * frames)
            summary = audit.inspect_capture(root/"m.raw", root/"r.raw")
            self.assertEqual(summary["assessment"], "input_format_preflight_pass")
            self.assertTrue(summary["awb_signal_present"])
            self.assertFalse(summary["problems"])
            self.assertAlmostEqual(summary["duration_seconds"], frames/96000, places=6)
            self.assertEqual(summary["microphones"][0]["aligned_fraction"], 1.0)
            self.assertEqual(summary["awb_stereo"][0]["samples"], frames)

    def test_detect_zeros_and_misalignment(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root/"m.raw").write_bytes(struct.pack("<4i", 0x123401, 0, 0, 0) * 4)
            (root/"r.raw").write_bytes(b"\0" * 4 * 4)
            summary = audit.inspect_capture(root/"m.raw", root/"r.raw")
            self.assertFalse(summary["awb_signal_present"])
            self.assertTrue(summary["warnings"])
            self.assertIn("ch0", summary["problems"][0])
            self.assertEqual(summary["assessment"], "needs_manual_review")

    def test_reject_frame_count_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root/"m.raw").write_bytes(struct.pack("<4i", 0, 0, 0, 0) * 8)
            (root/"r.raw").write_bytes(struct.pack("<2h", 0, 0) * 7)
            summary = audit.inspect_capture(root/"m.raw", root/"r.raw")
            self.assertTrue(any("frame counts differ" in x for x in summary["problems"]))

    def test_detect_wrong_reference_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root/"m.raw").write_bytes(struct.pack("<4i", 0, 0, 0, 0) * 6)
            (root/"r.raw").write_bytes(struct.pack("<2h", 0, 0) * 6)
            (root/"capture.json").write_text(json.dumps({
                "reference_source": "software_ref",
                "mic_channels": 4, "ref_channels": 2,
                "mic_rate": 96000, "ref_rate": 96000,
                "written_frames16": 1, "dropped_frames16": 2,
            }))
            summary = audit.inspect_capture(root/"m.raw", root/"r.raw", root/"capture.json")
            self.assertTrue(any("hardware AWB" in x for x in summary["problems"]))
            self.assertTrue(any("dropped" in x for x in summary["problems"]))


if __name__ == "__main__":
    unittest.main()
