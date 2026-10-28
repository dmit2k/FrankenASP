#!/usr/bin/env python3
"""Full v4/Brotli OTA regression. Requires existing optional Python brotli 1.2+."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_installer as fixtures
import installer_block_ota as block
import installer_payload as payload
import installer_sources as sources
import brotli


def archive(path, system, vendor, metadata=None, mutate=None):
    values = {"ota-type": "BLOCK", "pre-device": "athena",
              "post-build": fixtures.FINGERPRINT, "post-build-incremental": "1"}
    if metadata:
        values.update(metadata)
    contents = {sources.META: "".join(k + "=" + v + "\n" for k, v in values.items()).encode()}
    for part, image in (("system", system), ("vendor", vendor)):
        raw = Path(image).read_bytes()
        contents[part + ".transfer.list"] = ("4\n" + str(len(raw) // block.BLOCK) +
                                            "\n0\n0\nnew 2,0," + str(len(raw) // block.BLOCK) + "\n").encode()
        contents[part + ".new.dat.br"] = brotli.compress(raw, quality=1)
        contents[part + ".patch.dat"] = b""
    if mutate:
        mutate(contents)
    with zipfile.ZipFile(path, "w") as z:
        for name, raw in contents.items():
            z.writestr(name, raw)


class FullBlock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.Installer.setUpClass()

    @classmethod
    def tearDownClass(cls):
        fixtures.Installer.tearDownClass()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="asp2-block-")
        self.work = Path(self.tmp.name)
        self.f = fixtures.Installer()
        self.f.work = self.work
        self.ota = self.work / "full.bin"

    def tearDown(self):
        self.tmp.cleanup()

    def package(self, mutate=None):
        archive(self.ota, self.f.system_image, self.f.vendor_image, mutate=mutate)
        authority = dict(self.f.authority, official_ota_sha256=sources.digest(self.ota))
        a = self.work / "authority.json"
        payload.write_json(a, authority)
        return self.f.args(ota=self.ota, source_authority=a)

    def test_01_full_brotli_cli_prepare(self):
        a = self.package()
        r = self.f.command("prepare", "--mode", sources.BUNDLE, "--ota", a.ota,
                           "--source-authority", a.source_authority, "--launcher", a.launcher,
                           "--child", a.child, "--channel-map", a.channel_map,
                           "--mapping-authority", a.mapping_authority, "--output", a.output)
        self.assertEqual(r.returncode, 0, r.stderr)
        receipt = payload.validate(a.output)
        self.assertEqual(receipt["source"]["format"], "ZIP_FULL_BLOCK_BROTLI_V4")
        self.assertFalse(receipt["source"]["reconstruction"]["system"]["base_required"])
        self.assertTrue((a.output / "lib/rootfs/vendor/lib/libasp.so").is_file())
        self.assertEqual((a.output / payload.PROFILE).read_bytes(), payload.profile(sources.BUNDLE))
        self.assertFalse(list(self.work.glob(".asp2-prepare-*")))

    def test_02_inspect_does_not_reconstruct_or_write(self):
        a = self.package()
        before = sorted(str(p) for p in self.work.rglob("*"))
        with patch.object(block, "reconstruct", side_effect=AssertionError("inspect must not extract")):
            r = payload.inspect(a)
        self.assertEqual(r["format"], "ZIP_FULL_BLOCK_BROTLI_V4")
        self.assertEqual(r["source_validation"], "EXTRACTION_REQUIRED")
        self.assertEqual(before, sorted(str(p) for p in self.work.rglob("*")))

    def test_03_new_zero_erase_reconstruction_exact_bytes(self):
        raw = b"A" * block.BLOCK + b"B" * (2 * block.BLOCK)
        plan = block.transfer(b"4\n5\n0\n0\nerase 2,5,8\nnew 4,0,1,3,5\nzero 2,1,3\n")
        archive_path = self.work / "tiny.zip"
        with zipfile.ZipFile(archive_path, "w") as z:
            z.writestr("system.new.dat.br", brotli.compress(raw))
        with zipfile.ZipFile(archive_path) as z:
            out = self.work / "new.img"
            block.reconstruct(z, "system", out, plan)
        self.assertEqual(out.read_bytes(), b"A" * block.BLOCK + b"\0" * (2 * block.BLOCK) +
                         b"B" * (2 * block.BLOCK) + b"\0" * (3 * block.BLOCK))

    def test_04_missing_vendor_refused(self):
        self.package(lambda d: d.pop("vendor.new.dat.br"))
        with self.assertRaisesRegex(ValueError, "both components"):
            sources.ota_open(self.ota)

    def test_05_source_move_refused(self):
        with self.assertRaisesRegex(ValueError, "source-dependent"):
            block.transfer(b"4\n1\n0\n0\nmove 2,0,1\n")

    def test_06_stash_refused(self):
        with self.assertRaisesRegex(ValueError, "stash"):
            block.transfer(b"4\n1\n1\n1\nnew 2,0,1\n")

    def test_07_overlap_and_gap_refused(self):
        for raw in (b"4\n3\n0\n0\nnew 4,0,2,1,2\n",
                    b"4\n2\n0\n0\nnew 4,0,1,2,3\n"):
            with self.assertRaises(ValueError):
                block.transfer(raw)

    def test_08_declared_count_refused(self):
        with self.assertRaisesRegex(ValueError, "declared"):
            block.transfer(b"4\n2\n0\n0\nnew 2,0,1\n")

    def test_09_image_bound_refused(self):
        with self.assertRaisesRegex(ValueError, "bound"):
            block.transfer(b"4\n1\n0\n0\nnew 2,0,999999999\n")

    def test_10_damaged_brotli_leaves_no_usable_output(self):
        a = self.package(lambda d: d.update({"system.new.dat.br": b"CORRUPT"}))
        with self.assertRaises(ValueError):
            payload.prepare(a)
        self.assertFalse(a.output.exists())
        self.assertFalse(list(self.work.glob(".asp2-prepare-*")))

    def test_11_truncated_brotli_refused(self):
        a = self.package(lambda d: d.update({"system.new.dat.br": d["system.new.dat.br"][:-3]}))
        with self.assertRaisesRegex(ValueError, "truncated|damaged"):
            payload.prepare(a)
        self.assertFalse(a.output.exists())

    def test_12_decoded_size_overflow_refused(self):
        a = self.package(lambda d: d.update({"system.transfer.list": b"4\n1\n0\n0\nnew 2,0,1\n"}))
        with self.assertRaisesRegex(ValueError, "exceeds"):
            payload.prepare(a)
        self.assertFalse(a.output.exists())

    def test_13_nonempty_patch_refused(self):
        self.package(lambda d: d.update({"vendor.patch.dat": b"BASE_PATCH"}))
        with self.assertRaisesRegex(ValueError, "incremental"):
            sources.ota_open(self.ota)

    def test_14_transfer_v3_refused(self):
        with self.assertRaisesRegex(ValueError, "v4"):
            block.transfer(b"3\n1\n0\n0\nnew 2,0,1\n")

    def test_15_old_brotli_api_refused(self):
        a = self.package()
        class OldAPI:
            class Decompressor:
                pass
        with patch.object(block.importlib, "import_module", return_value=OldAPI):
            with self.assertRaisesRegex(ValueError, "bounded streaming"):
                payload.prepare(a)

    def test_16_trailing_compressed_stream_refused(self):
        a = self.package(lambda d: d.update({"system.new.dat.br": d["system.new.dat.br"] + b"TRAILING"}))
        with self.assertRaises(ValueError):
            payload.prepare(a)
        self.assertFalse(a.output.exists())

    def test_17_full_block_never_accepts_live_vendor_mix(self):
        a = self.package()
        a.vendor_reference = self.f.src / "vendor"
        with self.assertRaisesRegex(ValueError, "mixed"):
            payload.prepare(a)

    def test_18_high_ratio_stream_complete_at_archive_eof(self):
        raw = b"\0" * (16 * 1024 * 1024)
        packed = self.work / "high-ratio.zip"
        with zipfile.ZipFile(packed, "w") as z:
            z.writestr("system.new.dat.br", brotli.compress(raw, quality=1))
        plan = block.transfer(b"4\n4096\n0\n0\nnew 2,0,4096\n")
        with zipfile.ZipFile(packed) as z:
            out = self.work / "decoded.img"
            block.reconstruct(z, "system", out, plan)
        self.assertEqual(out.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
