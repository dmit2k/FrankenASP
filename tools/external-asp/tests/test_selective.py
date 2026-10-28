#!/usr/bin/env python3
"""Portable ext4, direct backup, and truly selective OTA regression."""
import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_installer as f
import test_block_ota as b
import installer_block_ota as block
import installer_ext4 as ext
import installer_payload as payload
import installer_sources as sources
import installer_download as download


class Selective(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        f.Installer.setUpClass()

    @classmethod
    def tearDownClass(cls):
        f.Installer.tearDownClass()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="asp2-selective-")
        self.work = Path(self.tmp.name)
        self.fixture = f.Installer()
        self.fixture.work = self.work

    def tearDown(self):
        self.tmp.cleanup()

    def args(self, **kw):
        return self.fixture.args(source_authority=None, fixture=True, **kw)

    def backup(self, name="backups/SERIAL/partitions"):
        path = self.work / name
        path.mkdir(parents=True)
        for src, dst in ((self.fixture.system_image, "p21-system.img"),
                         (self.fixture.vendor_image, "p12-vendor.img")):
            os.link(src, path / dst)
        return path

    def a(self, path):
        return self.args(mode=sources.LIVE, system_image=None, vendor_reference=None,
                         backup_dir=path)

    def test_exact_techo5_directory_no_ledger_or_hash(self):
        a = self.a(self.backup())
        (a.backup_dir / "SHA256SUMS").write_text("INTENTIONALLY WRONG")
        with patch.object(sources, "digest", side_effect=AssertionError("no source hashing")), patch.object(
                sources.subprocess, "run", side_effect=AssertionError("no debugfs")):
            payload.prepare(a)
        self.assertFalse(list((a.output / "lib/rootfs/vendor").iterdir()))
        self.assertNotIn("sha256", json.dumps(payload.validate(a.output)["source"]))

    def test_exact_research_directory_same_format(self):
        payload.prepare(self.a(self.backup("preunlock-7080")))
        self.assertTrue(payload.validate(self.work / "payload")["installable"])

    def test_parent_not_crawled(self):
        path = self.backup()
        with self.assertRaisesRegex(ValueError, "p21-system.img"):
            payload.inspect(self.a(path.parent))

    def test_missing_vendor(self):
        path = self.backup()
        (path / "p12-vendor.img").unlink()
        with self.assertRaisesRegex(ValueError, "p12-vendor.img"):
            payload.prepare(self.a(path))

    def test_bad_ext4(self):
        path = self.backup()
        (path / "p21-system.img").unlink()
        (path / "p21-system.img").write_bytes(b"BAD" * 1024)
        with self.assertRaisesRegex(ValueError, "raw ext4"):
            payload.prepare(self.a(path))

    def make_bad_image(self, remove):
        root = self.work / "image-root"
        shutil.copytree(self.fixture.src, root)
        (root / remove).unlink()
        system = self.work / "system.img"
        vendor = self.work / "vendor.img"
        sr = self.work / "sr"
        sr.mkdir()
        shutil.copytree(root / "system", sr / "system")
        f.image(sr, system)
        f.image(root / "vendor", vendor)
        return self.args(mode=sources.LIVE, system_image=system, vendor_reference=vendor)

    def test_missing_linker_reports_file(self):
        with self.assertRaisesRegex(ValueError, "bin/linker"):
            payload.prepare(self.make_bad_image("system/bin/linker"))

    def test_missing_asp_reports_file(self):
        with self.assertRaisesRegex(ValueError, "lib/libasp.so"):
            payload.prepare(self.make_bad_image("vendor/lib/libasp.so"))

    def test_missing_config_reports_file(self):
        with self.assertRaisesRegex(ValueError, "asp.cfg"):
            payload.prepare(self.make_bad_image("vendor/etc/audio-algorithms/asp.cfg"))

    def test_missing_dependency(self):
        with self.assertRaisesRegex(ValueError, "libc.so"):
            payload.prepare(self.make_bad_image("system/lib/libc.so"))

    def test_selective_never_creates_partition_images(self):
        ota = self.work / "full.bin"
        b.archive(ota, self.fixture.system_image, self.fixture.vendor_image)
        a = self.args(ota=ota)
        with patch.object(block, "reconstruct", side_effect=AssertionError("full image forbidden")), patch.object(
                sources.subprocess, "run", side_effect=AssertionError("debugfs forbidden")):
            receipt = payload.prepare(a)
        self.assertTrue(all(v["selective"] and not v["complete_image_created"] and
                            v["temporary_image_bytes"] == 0 and v["retained_block_bytes"] < 1024**2
                            for v in receipt["source"]["reconstruction"].values()))
        expected, edges = sources.closure(sources.Directory(self.fixture.src / "system"),
                                         sources.Directory(self.fixture.src / "vendor"),
                                         self.fixture.child.read_bytes())
        for name, data in expected.items():
            self.assertEqual((a.output / "lib/rootfs" / name).read_bytes(), data, name)
        self.assertEqual(receipt["dependencies"], edges)
        self.assertFalse(list(self.work.glob(".asp2-prepare-*")))

    def test_backup_and_explicit_images_conflict(self):
        a = self.a(self.backup())
        a.system_image = self.fixture.system_image
        with self.assertRaisesRegex(ValueError, "mixed"):
            payload.prepare(a)

    def test_no_source_authority_normal_prepare_validate(self):
        a = self.args()
        with patch.object(sources, "digest", side_effect=AssertionError("source must not be hashed")), patch.object(download, "digest", side_effect=AssertionError("source must not be hashed")):
            payload.prepare(a)
        r = payload.validate(a.output)
        self.assertIsNone(r["source_authority"])
        self.assertTrue(r["source"]["identity"]["runtime_structure_verified"])

    def test_unknown_ext4_feature_fails(self):
        p = self.work / "feature.img"
        shutil.copyfile(self.fixture.system_image, p)
        with p.open("r+b") as out:
            out.seek(1024 + 96)
            flags = struct.unpack("<I", out.read(4))[0]
            out.seek(1024 + 96)
            out.write(struct.pack("<I", flags | 0x10000))  # encryption
        with self.assertRaisesRegex(ValueError, "feature"):
            sources.Ext4(p, "system")

    def test_truncated_geometry(self):
        p = self.work / "truncated.img"
        p.write_bytes(self.fixture.system_image.read_bytes()[:2048])
        with self.assertRaisesRegex(ValueError, "geometry"):
            sources.Ext4(p, "system")

    def test_extent_index_cycle_and_bounds(self):
        reader = sources.Ext4(self.fixture.system_image, "system")
        node = bytearray(60)
        struct.pack_into("<4H", node, 0, 0xf30a, 1, 4, 0)
        struct.pack_into("<III", node, 12, 0, 1, reader.blocks + 1)
        with self.assertRaisesRegex(ValueError, "outside"):
            reader.extents((0x8000, 100, 0x80000, node))

    def test_nonextent_refused(self):
        reader = sources.Ext4(self.fixture.system_image, "system")
        with self.assertRaisesRegex(ValueError, "non-extent"):
            reader.extents((0x8000, 100, 0, b"\0" * 60))

    def test_cache_bound_and_unseekable_stream(self):
        plan = block.transfer(b"4\n1\n0\n0\nnew 2,0,1\n")
        source = block.SelectiveBlocks(None, "system", plan)
        source.MAX_CACHE = 1
        with self.assertRaisesRegex(ValueError, "cache"):
            source.read_at(0, 1024)

    def test_unsupported_source_symlink_not_followed(self):
        root = self.work / "tree"
        shutil.copytree(self.fixture.src / "vendor", root)
        (root / "lib/libasp.so").unlink()
        (root / "lib/libasp.so").symlink_to("/etc/passwd")
        image = self.work / "symlink.img"
        f.image(root, image)
        with self.assertRaisesRegex(ValueError, "non-regular"):
            sources.Ext4(image, "").read("lib/libasp.so")

    def test_malformed_directory_entry(self):
        reader = sources.Ext4(self.fixture.vendor_image, "")
        with patch.object(reader, "data", return_value=b"\0" * reader.bs):
            with self.assertRaisesRegex(ValueError, "directory entry"):
                reader.entries((0x4000, 100, 0x80000, b""))

    def test_optional_hash_only_when_explicit(self):
        from installer_download import selected_ota
        a = self.args(expected_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "optional expected SHA256"):
            with selected_ota(a):
                pass

    def test_cli_mutually_exclusive_sources(self):
        p = self.fixture.command("inspect", "--mode", sources.BUNDLE, "--ota", self.fixture.ota,
                                 "--ota-url", "http://127.0.0.1/fixture")
        self.assertEqual(p.returncode, 2)
        self.assertIn("not allowed", p.stderr)

    def test_lower_priority_duplicate_data_is_never_read(self):
        root = self.work / "preferred-system"
        shutil.copytree(self.fixture.src / "system", root)
        f.put(root, "lib/vndk-28/libc.so", f.elf_fixture(shared=True))
        # This unused lower-priority duplicate must never be opened/validated.
        (root / "lib/libc.so").write_bytes(b"UNUSED CORRUPT DUPLICATE")
        reader = sources.Directory(root)
        with patch.object(reader, "read", wraps=reader.read) as read:
            contents, edges = sources.closure(reader, sources.Directory(self.fixture.src / "vendor"), self.fixture.child.read_bytes())
        self.assertIn("system/lib/vndk-28/libc.so", contents)
        self.assertNotIn("system/lib/libc.so", contents)
        self.assertNotIn(unittest.mock.call("lib/libc.so"), read.call_args_list)

    def test_raw_zip_crc_preserved_without_intermediate_image(self):
        ota = self.work / "raw-crc.zip"
        with zipfile.ZipFile(ota, "w", compression=zipfile.ZIP_STORED) as z:
            z.writestr(sources.META, "ota-type=BLOCK\n")
            z.write(self.fixture.system_image, "system.img")
            z.write(self.fixture.vendor_image, "vendor.img")
        raw = ota.read_bytes().replace(b"SYNTHETIC ASP", b"CORRUPTED ASP", 1)
        ota.write_bytes(raw)
        with self.assertRaises(zipfile.BadZipFile):
            payload.prepare(self.args(ota=ota))
        self.assertFalse(list(self.work.glob(".asp2-prepare-*")))

    def test_explicit_expected_hash_not_silently_ignored_for_backup(self):
        a = self.a(self.backup())
        a.expected_sha256 = "0" * 64
        with self.assertRaisesRegex(ValueError, "OTA only"):
            payload.prepare(a)


if __name__ == "__main__":
    unittest.main(verbosity=2)
