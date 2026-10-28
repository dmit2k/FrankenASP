#!/usr/bin/env python3
"""Offline deterministic pack and portable link representation regression."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import installer_pack
import installer_payload
import test_installer as fixtures


class Pack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.Installer.setUpClass()

    @classmethod
    def tearDownClass(cls):
        fixtures.Installer.tearDownClass()

    def setUp(self):
        self.fixture = fixtures.Installer()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.payload = self.fixture.prepared()
        self.work = self.fixture.work

    def pack(self, name="bundle.tar.gz"):
        output = self.work / name
        installer_pack.pack(argparse.Namespace(payload=self.payload, output=output))
        return output

    def test_deterministic_and_exact_bytes_modes_symlinks(self):
        first, second = self.pack(), self.pack("second.tar.gz")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with tarfile.open(first, "r:gz") as archive:
            members = archive.getmembers()
            names = [x.name for x in members]
            self.assertEqual(names, sorted(names))
            for member in members:
                self.assertEqual((member.uid, member.gid, member.mtime), (0, 0, 0))
                p = self.payload / member.name
                if member.issym():
                    self.assertEqual(member.linkname, os.readlink(p))
                elif member.isfile():
                    self.assertEqual(archive.extractfile(member).read(), p.read_bytes())
                    self.assertEqual(member.mode, p.stat().st_mode & 0o7777)
        self.assertFalse((self.payload / "SHA256SUMS").exists())

    def test_aliases_need_no_host_symlink_privilege(self):
        for name in installer_payload.ALIASES:
            (self.payload / "lib/rootfs/proc" / name).unlink()
        output = self.pack()
        with tarfile.open(output) as archive:
            for name, target in installer_payload.ALIASES.items():
                entry = archive.getmember("lib/rootfs/proc/" + name)
                self.assertTrue(entry.issym())
                self.assertEqual(entry.linkname, target)

    def test_unknown_alias_and_existing_output_preserved(self):
        p = self.payload / "lib/rootfs/proc/self"
        p.unlink()
        p.symlink_to("/etc/passwd")
        with self.assertRaises(ValueError):
            self.pack()
        p.unlink()
        p.symlink_to(installer_payload.ALIASES["self"])
        output = self.pack()
        before = output.read_bytes()
        with self.assertRaises(ValueError):
            self.pack()
        self.assertEqual(output.read_bytes(), before)

    def test_prepare_pack_roundtrip_command(self):
        out = self.work / "new-payload"
        packed = self.work / "prepared.tar.gz"
        a = self.fixture.args(output=out, pack_output=packed)
        installer_payload.prepare(a)
        self.assertTrue(packed.is_file())
        installer_payload.validate(out)
        self.assertNotIn("installation_id", json.loads((out / installer_payload.RECEIPT).read_text()))

    def test_no_output_inside_payload(self):
        with self.assertRaises(ValueError):
            installer_pack.pack(argparse.Namespace(payload=self.payload,
                                                   output=self.payload / "unsafe.tar.gz"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
