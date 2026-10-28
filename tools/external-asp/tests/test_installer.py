#!/usr/bin/env python3
"""Autonomous unprivileged offline installer regression; all firmware is synthetic."""
import argparse
import contextlib
import dataclasses
import importlib
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.dont_write_bytecode = True
TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import asp2_installer as cli
import installer_sources as sources
import installer_payload as payload
import installer_deploy as deploy

FINGERPRINT = "Amazon/athena/athena:9/SYNTHETIC/1:user/test-keys"
MAP = b"ASP2-CHANNEL-MAP-V1\nmic=0,1,2,3\nref=0,1\n"


def elf_fixture(interpreter=None, needed=(), shared=False):
    """Structurally valid parser fixture, never executable or a factory substitute."""
    data = bytearray(1024)
    data[:16] = b"\x7fELF\x01\x01\x01" + b"\0" * 9
    count = 1 + bool(interpreter) + bool(needed)
    struct.pack_into("<HHIIIIIHHHHHH", data, 16, 3 if shared or interpreter else 2,
                     40, 1, 0, 52, 0, 0x05000000, 52, 32, count, 0, 0, 0)
    struct.pack_into("<8I", data, 52, 1, 0, 0x10000, 0, len(data), len(data), 5, 4096)
    at = 84
    if interpreter:
        raw = interpreter.encode() + b"\0"
        data[512:512 + len(raw)] = raw
        struct.pack_into("<8I", data, at, 3, 512, 0x10200, 0, len(raw), len(raw), 4, 1)
        at += 32
    if needed:
        strings = b"\0" + b"".join(x.encode() + b"\0" for x in needed)
        data[768:768 + len(strings)] = strings
        entries = [(5, 0x10300), (10, len(strings))]
        offset = 1
        for n in needed:
            entries.append((1, offset))
            offset += len(n) + 1
        entries.append((0, 0))
        for i, entry in enumerate(entries):
            struct.pack_into("<II", data, 256 + i * 8, *entry)
        struct.pack_into("<8I", data, at, 2, 256, 0x10100, 0, len(entries) * 8,
                         len(entries) * 8, 4, 4)
    return bytes(data)


def put(root, name, data):
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def image(root, out):
    with out.open("wb") as f:
        f.truncate(8 * 1024 * 1024)
    subprocess.run(["mke2fs", "-q", "-F", "-t", "ext4", "-d", str(root), str(out)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def zip_tree(root, output, metadata=None):
    meta = {"ota-type": "FILE", "pre-device": "athena", "post-build": FINGERPRINT,
            "post-build-incremental": "1"}
    if metadata:
        meta.update(metadata)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(sources.META, "".join(k + "=" + v + "\n" for k, v in meta.items()))
        for p in sorted(root.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(root).as_posix())


class Installer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix="asp2-fixtures-")
        cls.root = Path(cls.workspace.name)
        cls.src = cls.root / "source"
        system = cls.src / "system"
        vendor = cls.src / "vendor"
        s = {"ro.build.fingerprint": FINGERPRINT, "ro.build.id": "SYNTHETIC",
             "ro.build.version.sdk": "28", "ro.build.version.incremental": "1",
             "ro.product.device": "athena", "ro.product.cpu.abilist32": "armeabi-v7a,armeabi"}
        v = {"ro.vendor.build.fingerprint": FINGERPRINT,
             "ro.product.vendor.device": "athena",
             "ro.vendor.product.cpu.abilist32": "armeabi-v7a,armeabi"}
        for root, props in ((system, s), (vendor, v)):
            put(root, "build.prop", "".join(k + "=" + val + "\n" for k, val in props.items()).encode())
        put(system, "bin/linker", elf_fixture())
        for name in ("libc.so", "libdl.so", "ld-android.so"):
            put(system, "lib/" + name, elf_fixture(shared=True))
        for name in sources.SYSTEM_CONFIGS[1:]:
            put(system, name, b"# synthetic fixture only\n")
        put(vendor, "lib/libasp.so", elf_fixture(needed=("libc.so",), shared=True))
        put(vendor, "etc/audio-algorithms/asp.cfg", b"SYNTHETIC ASP\n")
        put(vendor, "etc/audio-algorithms/AFE.cfg", b"SYNTHETIC AFE\n")
        cls.launcher, cls.child, cls.map = [cls.root / n for n in ("launcher", "child", "channel-map")]
        cls.launcher.write_bytes(elf_fixture())
        cls.child.write_bytes(elf_fixture("/system/bin/linker", ("libdl.so", "libc.so")))
        cls.map.write_bytes(MAP)
        cls.authority = {"schema": "ASP2-SOURCE-AUTHORITY-V1", "scope": "SYNTHETIC_FIXTURE",
                         "authority": "autonomous synthetic fixture; no genuine Amazon claim",
                         "genuine_factory": True, "fingerprint": FINGERPRINT,
                         "libasp_sha256": sources.digest(vendor / "lib/libasp.so"),
                         "config_inventory": {"AFE.cfg": 14, "asp.cfg": 14},
                         "official_source": "https://example.invalid/synthetic-only"}
        cls.authority_path = cls.root / "source-authority.json"
        cls.mapping_path = cls.root / "mapping-authority.json"
        payload.write_json(cls.mapping_path, {
            "schema": "ASP2-MAPPING-AUTHORITY-V1", "scope": "SYNTHETIC_FIXTURE",
            "authority": "test fixture only", "fingerprint": FINGERPRINT,
            "channel_map_sha256": sources.digest(cls.map),
            "captured_slot_idme_association": "OWNER_APPROVED_ALSA_ORDER"})
        cls.ota = cls.root / "full-tree.zip"
        zip_tree(cls.src, cls.ota)
        cls.authority["official_ota_sha256"] = sources.digest(cls.ota)
        payload.write_json(cls.authority_path, cls.authority)
        cls.system_image = cls.root / "system.img"
        cls.vendor_image = cls.root / "vendor.img"
        sr = cls.root / "system-image-root"
        sr.mkdir()
        shutil.copytree(system, sr / "system")
        image(sr, cls.system_image)
        image(vendor, cls.vendor_image)
        cls.raw_ota = cls.root / "raw-images.zip"
        with zipfile.ZipFile(cls.raw_ota, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(sources.META, "ota-type=BLOCK\npre-device=athena\npost-build=" +
                       FINGERPRINT + "\npost-build-incremental=1\n")
            z.write(cls.system_image, "system.img")
            z.write(cls.vendor_image, "vendor.img")

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="asp2-test-")
        self.work = Path(self.temp.name)
        self.work.chmod(0o700)

    def tearDown(self):
        self.temp.cleanup()

    def args(self, mode=sources.BUNDLE, **changes):
        values = dict(mode=mode, system_image=None, vendor_reference=None, ota=self.ota,
                      source_authority=self.authority_path, output=self.work / "payload",
                      launcher=self.launcher, child=self.child, channel_map=self.map,
                      mapping_authority=self.mapping_path, allow_unqualified_map=False)
        if mode == sources.LIVE:
            values.update(system_image=self.system_image, vendor_reference=self.vendor_image, ota=None)
        values.update(changes)
        return argparse.Namespace(**values)

    def deployment(self, **changes):
        values = dict(destination=self.work / "external-asp", local_root=self.work,
                      payload=self.work / "payload", live_vendor=self.src / "vendor",
                      opt_in=True, confirm_inactive=True, generation=None)
        values.update(changes)
        return argparse.Namespace(**values)

    def prepared(self, **changes):
        a = self.args(**changes)
        payload.prepare(a)
        return a.output

    def command(self, *args):
        return subprocess.run([sys.executable, "-B", str(TOOLS / "asp2_installer.py"), *map(str, args)],
                              text=True, capture_output=True, timeout=60)

    def test_01_full_tree_prepare_exact_layout(self):
        p = self.prepared()
        r = payload.validate(p)
        self.assertTrue(r["installable"])
        self.assertEqual((p / payload.PROFILE).read_bytes(), payload.profile(sources.BUNDLE))
        self.assertEqual((p / "lib/rootfs/factory/channel-map").read_bytes(), MAP)
        for name, target in payload.ALIASES.items():
            self.assertEqual(os.readlink(p / "lib/rootfs/proc" / name), target)
        self.assertFalse((p / "SHA256SUMS").exists())

    def test_02_mode_a_raw_images_no_vendor_persistence(self):
        payload.prepare(self.args(sources.LIVE))
        p = self.work / "payload"
        self.assertEqual(list((p / "lib/rootfs/vendor").iterdir()), [])
        self.assertTrue(payload.validate(p)["live_vendor_revalidation_required"])
        deploy.dry_run(self.deployment())

    def test_03_raw_ext4_image_ota(self):
        authority = dict(self.authority, official_ota_sha256=sources.digest(self.raw_ota))
        a = self.work / "authority.json"
        payload.write_json(a, authority)
        p = self.prepared(ota=self.raw_ota, source_authority=a)
        self.assertEqual(payload.validate(p)["source"]["format"], "ZIP_RAW_EXT4_IMAGES")

    def test_04_inspect_is_read_only(self):
        before = sorted(str(p) for p in self.work.rglob("*"))
        sources_before = sorted(str(p) for p in TOOLS.rglob("__pycache__"))
        r = payload.inspect(self.args())
        self.assertEqual(r["format"], "ZIP_FULL_FILE_TREE")
        self.assertEqual(before, sorted(str(p) for p in self.work.rglob("*")))
        self.assertEqual(sources_before, sorted(str(p) for p in TOOLS.rglob("__pycache__")))
        self.assertEqual(payload.inspect(self.args(ota=self.raw_ota))["source_validation"],
                         "EXTRACTION_REQUIRED")

    def test_05_obsolete_source_fingerprint_ignored(self):
        authority = dict(self.authority, fingerprint="OTHER")
        self.assertTrue(sources.pair(sources.Directory(self.src / "system"),
                         sources.Directory(self.src / "vendor"), authority)["runtime_structure_verified"])

    def test_06_build_labels_are_informational(self):
        vendor = self.work / "vendor"
        shutil.copytree(self.src / "vendor", vendor)
        (vendor / "build.prop").write_text("ro.vendor.build.fingerprint=OTHER\n")
        self.assertTrue(sources.pair(sources.Directory(self.src / "system"), sources.Directory(vendor), None)["runtime_structure_verified"])

    def test_07_incremental_refused(self):
        p = self.work / "incremental.zip"
        zip_tree(self.src, p, {"pre-build": "BASE_REQUIRED"})
        with self.assertRaisesRegex(ValueError, "incremental"):
            sources.ota_open(p)

    def test_08_payload_bin_refused(self):
        p = self.work / "payload.zip"
        zip_tree(self.src, p)
        with zipfile.ZipFile(p, "a") as z:
            z.writestr("payload.bin", b"SYNTHETIC")
        with self.assertRaisesRegex(ValueError, "payload"):
            sources.ota_open(p)

    def test_09_damaged_ota(self):
        p = self.work / "broken.zip"
        p.write_bytes(b"PK\x03\x04TRUNCATED")
        with self.assertRaisesRegex(ValueError, "damaged"):
            sources.ota_open(p)

    def test_10_mixed_source_b_refused(self):
        with self.assertRaisesRegex(ValueError, "mixed"):
            payload.prepare(self.args(system_image=self.system_image))
        self.assertFalse((self.work / "payload").exists())
        self.assertFalse(list(self.work.glob(".asp2-prepare-*")))

    def test_11_duplicate_map_refused(self):
        p = self.work / "bad-map"
        p.write_bytes(MAP.replace(b"0,1,2,3", b"0,0,2,3"))
        with self.assertRaises(ValueError):
            self.prepared(channel_map=p)

    def test_12_no_mapping_authority(self):
        with self.assertRaisesRegex(ValueError, "mapping authority"):
            self.prepared(mapping_authority=None)

    def test_13_preview_has_no_profile_cannot_install(self):
        p = self.prepared(mapping_authority=None, allow_unqualified_map=True)
        self.assertFalse((p / payload.PROFILE).exists())
        with self.assertRaisesRegex(ValueError, "NONINSTALLABLE"):
            deploy.dry_run(self.deployment())

    def test_14_missing_dependency(self):
        system = self.work / "system"
        shutil.copytree(self.src / "system", system)
        (system / "lib/libc.so").unlink()
        with self.assertRaisesRegex(ValueError, "missing Bionic dependency"):
            sources.closure(sources.Directory(system), sources.Directory(self.src / "vendor"),
                            self.child.read_bytes())

    def test_15_wrong_child_interpreter(self):
        p = self.work / "bad-child"
        p.write_bytes(elf_fixture("/lib/ld-linux-armhf.so.3"))
        with self.assertRaisesRegex(ValueError, "interpreter"):
            self.prepared(child=p)

    def test_16_dynamic_linux_launcher_refused(self):
        with self.assertRaisesRegex(ValueError, "interpreter"):
            self.prepared(launcher=self.child)

    def test_17_no_required_libasp_hash(self):
        a = dict(self.authority, libasp_sha256="0" * 64)
        sources.pair(sources.Directory(self.src / "system"), sources.Directory(self.src / "vendor"), a)

    def test_18_no_required_config_manifest(self):
        a = dict(self.authority, config_inventory={})
        sources.pair(sources.Directory(self.src / "system"), sources.Directory(self.src / "vendor"), a)

    def test_19_unknown_destination_preserved(self):
        self.prepared()
        dest = self.work / "external-asp"
        dest.mkdir()
        (dest / "owner-data").write_text("KEEP")
        with self.assertRaises(ValueError):
            deploy.install(self.deployment())
        self.assertEqual((dest / "owner-data").read_text(), "KEEP")

    def test_20_atomic_update_rollback_uninstall(self):
        self.prepared()
        before = self.work.stat().st_mode
        a = self.deployment()
        first = deploy.install(a)["installed"]
        second = deploy.install(a)["installed"]
        self.assertNotEqual(first, second)
        s = deploy.status(a)
        self.assertEqual(len(s["generations"]), 2)
        a.generation = first
        deploy.rollback(a)
        self.assertTrue(deploy.status(a)["generations"][first]["current"])
        deploy.uninstall(a)
        a.generation = second
        deploy.uninstall(a)
        self.assertFalse(a.destination.exists())
        self.assertEqual(self.work.stat().st_mode, before)

    def test_21_install_requires_opt_in(self):
        self.prepared()
        with self.assertRaisesRegex(ValueError, "opt-in"):
            deploy.install(self.deployment(opt_in=False))

    def test_22_insufficient_storage(self):
        self.prepared()
        with patch.object(deploy.shutil, "disk_usage", return_value=argparse.Namespace(free=0)):
            with self.assertRaisesRegex(ValueError, "storage"):
                deploy.install(self.deployment())
        self.assertFalse((self.work / "external-asp").exists())

    def test_23_failed_prepare_cleans_new_stage(self):
        with patch.object(payload, "closure", side_effect=OSError("simulated ENOSPC")):
            with self.assertRaises(OSError):
                self.prepared()
        self.assertEqual(list(self.work.iterdir()), [])

    def test_24_failed_copy_cleans_only_own_stage(self):
        self.prepared()
        keep = self.work / "owner-data"
        keep.write_text("KEEP")
        with patch.object(deploy.shutil, "copytree", side_effect=OSError("copy interrupted")):
            with self.assertRaises(OSError):
                deploy.install(self.deployment())
        self.assertFalse(list(self.work.glob(deploy.PREFIX + "*")))
        self.assertEqual(keep.read_text(), "KEEP")

    def test_25_failed_exchange_retains_recoverable_generation(self):
        self.prepared()
        a = self.deployment()
        first = deploy.install(a)["installed"]
        with patch.object(deploy, "rename_atomic", side_effect=OSError("interrupted before exchange")):
            with self.assertRaises(OSError):
                deploy.install(a)
        s = deploy.status(a)
        self.assertTrue(s["generations"][first]["current"])
        other = next(k for k in s["generations"] if k != first)
        a.generation = other
        deploy.uninstall(a)
        self.assertEqual(len(deploy.status(a)["generations"]), 1)

    def test_26_active_fd4_refused(self):
        self.prepared()
        a = self.deployment()
        key = deploy.install(a)["installed"]
        fd = os.open(a.destination, os.O_RDONLY | os.O_DIRECTORY)
        try:
            a.generation = key
            with self.assertRaisesRegex(ValueError, "active pinned"):
                deploy.uninstall(a)
        finally:
            os.close(fd)
        deploy.uninstall(a)

    def test_27_root_symlink_refused(self):
        (self.work / "external-asp").symlink_to(self.src, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            deploy.status(self.deployment())

    def test_28_modified_generation_identity_refused(self):
        self.prepared()
        a = self.deployment()
        key = deploy.install(a)["installed"]
        p = a.destination / "bin/external-asp"
        p.chmod(0o700)
        p.write_bytes(b"CHANGED")
        a.generation = key
        with self.assertRaises(ValueError):
            deploy.uninstall(a)
        self.assertTrue(a.destination.exists())

    def test_29_no_network_in_inspect_prepare(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            self.prepared()
            payload.inspect(self.args())

    def test_30_cli_local_flow_and_no_writes_inspect(self):
        r = self.command("inspect", "--mode", sources.LIVE, "--system-image", self.system_image,
                         "--vendor-reference", self.vendor_image, "--source-authority", self.authority_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("live_vendor_revalidation_required", r.stdout)
        r = self.command("prepare", "--mode", sources.BUNDLE, "--ota", self.ota,
                         "--source-authority", self.authority_path, "--output", self.work / "payload",
                         "--launcher", self.launcher, "--child", self.child, "--channel-map", self.map,
                         "--mapping-authority", self.mapping_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        args = ("--local-root", self.work, "--destination", self.work / "external-asp")
        r = self.command("dry-run", *args, "--payload", self.work / "payload")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.command("install", *args, "--payload", self.work / "payload",
                         "--opt-in", "--confirm-inactive")
        self.assertEqual(r.returncode, 0, r.stderr)
        key = json.loads(r.stdout)["installed"]
        self.assertEqual(self.command("status", *args).returncode, 0)
        r = self.command("uninstall", *args, "--generation", key, "--opt-in", "--confirm-inactive")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_31_zip_traversal_and_duplicate_names(self):
        p = self.work / "unsafe.zip"
        zip_tree(self.src, p)
        with zipfile.ZipFile(p, "a") as z:
            z.writestr("../escape", b"NO")
        with self.assertRaisesRegex(ValueError, "unsafe"):
            sources.ota_open(p)

    def test_32_existing_output_preserved(self):
        p = self.prepared()
        original = (p / payload.RECEIPT).read_bytes()
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.prepared()
        self.assertEqual((p / payload.RECEIPT).read_bytes(), original)

    def test_33_fixture_cannot_enter_production(self):
        p = self.prepared()
        with self.assertRaisesRegex(ValueError, "synthetic"):
            deploy.preflight_payload(p, self.deployment(local_root=None))

    def test_34_mode_a_checks_runtime_not_fingerprint(self):
        self.prepared(mode=sources.LIVE)
        vendor = self.work / "vendor"
        shutil.copytree(self.src / "vendor", vendor)
        (vendor / "build.prop").write_text("ro.vendor.build.fingerprint=OTHER\n")
        deploy.dry_run(self.deployment(live_vendor=vendor))
        (vendor / "lib/libasp.so").write_bytes(b"CORRUPT")
        with self.assertRaisesRegex(ValueError, "ELF32"):
            deploy.dry_run(self.deployment(live_vendor=vendor))

    def test_35_no_required_archive_hash_or_origin(self):
        a = self.work / "authority.json"
        payload.write_json(a, dict(self.authority, official_ota_sha256="0" * 64))
        # Obsolete origin/SHA values are never a functional gate.
        self.prepared(source_authority=a)

    def test_36_url_is_not_downloaded(self):
        r = self.command("inspect", "--mode", sources.BUNDLE, "--ota",
                         "https://example.invalid/never-download.zip")
        self.assertEqual(r.returncode, 2)
        self.assertIn("local OTA file required", r.stderr)

    def test_37_hard_exit_before_publication_recoverable(self):
        self.prepared()
        script = """import sys,os,argparse
sys.dont_write_bytecode=True
sys.path.insert(0,sys.argv[1])
import installer_deploy as d
p=sys.argv[2]
a=argparse.Namespace(destination=__import__('pathlib').Path(p)/'external-asp',local_root=p,payload=p+'/payload',live_vendor=None,opt_in=True,confirm_inactive=True)
d.rename_atomic=lambda *args: os._exit(85)
d.install(a)
"""
        r = subprocess.run([sys.executable, "-B", "-c", script, str(TOOLS), str(self.work)])
        self.assertEqual(r.returncode, 85)
        a = self.deployment()
        s = deploy.status(a)
        key = next(iter(s["generations"]))
        self.assertFalse(s["installed"])
        a.generation = key
        deploy.rollback(a)
        self.assertTrue(deploy.status(a)["installed"])
        deploy.uninstall(a)

    def test_38_hard_exit_after_exchange_keeps_both_identities(self):
        self.prepared()
        a = self.deployment()
        first = deploy.install(a)["installed"]
        script = """import sys,os,argparse
sys.dont_write_bytecode=True
sys.path.insert(0,sys.argv[1])
import installer_deploy as d
p=sys.argv[2]
a=argparse.Namespace(destination=__import__('pathlib').Path(p)/'external-asp',local_root=p,payload=p+'/payload',live_vendor=None,opt_in=True,confirm_inactive=True)
original=d.rename_atomic
def exit_after(*args):
 original(*args)
 os._exit(86)
d.rename_atomic=exit_after
d.install(a)
"""
        r = subprocess.run([sys.executable, "-B", "-c", script, str(TOOLS), str(self.work)])
        self.assertEqual(r.returncode, 86)
        s = deploy.status(a)
        self.assertEqual(len(s["generations"]), 2)
        self.assertFalse(s["generations"][first]["current"])
        a.generation = first
        deploy.rollback(a)
        self.assertTrue(deploy.status(a)["generations"][first]["current"])

    def test_39_partial_uninstall_can_resume(self):
        self.prepared()
        a = self.deployment()
        a.generation = deploy.install(a)["installed"]
        def partial(path):
            (path / "bin/external-asp").unlink()
            raise OSError("simulated interruption during removal")
        with patch.object(deploy.shutil, "rmtree", side_effect=partial):
            with self.assertRaises(OSError):
                deploy.uninstall(a)
        self.assertTrue(deploy.status(a)["generations"][a.generation]["removal_pending"])
        with self.assertRaisesRegex(ValueError, "incomplete|removed"):
            deploy.rollback(a)
        deploy.uninstall(a)
        self.assertEqual(deploy.status(a)["generations"], {})

    def test_40_unknown_nested_content_not_deleted_as_control_file(self):
        self.prepared()
        a = self.deployment()
        a.generation = deploy.install(a)["installed"]
        (a.destination / "etc/owner-data").write_text("KEEP")
        with self.assertRaises(ValueError):
            deploy.uninstall(a)
        self.assertEqual((a.destination / "etc/owner-data").read_text(), "KEEP")

    def test_41_concurrent_installer_lock(self):
        self.prepared()
        with deploy.locked(self.work):
            with self.assertRaisesRegex(ValueError, "another installer"):
                deploy.install(self.deployment())

    def test_42_dry_run_has_no_destination_side_effect(self):
        self.prepared()
        before = sorted(p.relative_to(self.work).as_posix() for p in self.work.rglob("*"))
        deploy.dry_run(self.deployment())
        after = sorted(p.relative_to(self.work).as_posix() for p in self.work.rglob("*"))
        self.assertEqual(before, after)

    def test_43_bad_ota_crc_is_clear_cli_refusal(self):
        p = self.work / "badcrc.zip"
        with zipfile.ZipFile(p, "w", compression=zipfile.ZIP_STORED) as z:
            z.writestr(sources.META, "ota-type=FILE\npre-device=athena\npost-build=" +
                       FINGERPRINT + "\npost-build-incremental=1\n")
            for f in self.src.rglob("*"):
                if f.is_file():
                    z.write(f, f.relative_to(self.src).as_posix())
        raw = p.read_bytes()
        raw = raw.replace(b"SYNTHETIC ASP", b"CORRUPTED ASP", 1)
        p.write_bytes(raw)
        r = self.command("prepare", "--mode", sources.BUNDLE, "--ota", p,
                         "--source-authority", self.authority_path, "--output", self.work / "payload",
                         "--launcher", self.launcher, "--child", self.child, "--channel-map", self.map,
                         "--mapping-authority", self.mapping_path)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("REFUSED", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertFalse((self.work / "payload").exists())

    def test_44_sparse_image_refused(self):
        p = self.work / "sparse.img"
        p.write_bytes(b"\x3a\xff\x26\xed" + b"\0" * 2048)
        with self.assertRaisesRegex(ValueError, "raw ext4"):
            sources.Ext4(p, "system")

    def test_45_original_dso_bionic_interp_allowed_unchanged(self):
        raw = elf_fixture("/system/bin/linker", ("libc.so",), shared=True)
        self.assertEqual(sources.elf(raw, shared=True), ["libc.so"])
        with self.assertRaisesRegex(ValueError, "interpreter"):
            sources.elf(elf_fixture("/lib/ld-linux-armhf.so.3", shared=True), shared=True)

    def test_46_corrupt_preferred_dependency_does_not_fall_back(self):
        system = self.work / "system"
        shutil.copytree(self.src / "system", system)
        put(system, "lib/vndk-28/libc.so", b"CORRUPT")
        with self.assertRaisesRegex(ValueError, "ELF32"):
            sources.closure(sources.Directory(system), sources.Directory(self.src / "vendor"),
                            self.child.read_bytes())

    def test_47_owner_alsa_authority_is_identity_only(self):
        raw = MAP.replace(b"0,1,2,3", b"2,0,3,1")
        a = json.loads(self.mapping_path.read_text())
        a["channel_map_sha256"] = sources.digest_bytes(raw)
        with self.assertRaisesRegex(ValueError, "identity map"):
            payload.check_mapping(a, raw, FINGERPRINT, "SYNTHETIC_FIXTURE")
        a["captured_slot_idme_association"] = "CONFIRMED"
        payload.check_mapping(a, raw, FINGERPRINT, "SYNTHETIC_FIXTURE")

    def test_48_dynamic_linker_cannot_be_linux_launcher(self):
        raw = elf_fixture(needed=("libc.so",))
        with self.assertRaisesRegex(ValueError, "PT_DYNAMIC"):
            sources.elf(raw, native_static=True)

    def test_49_hard_exit_during_copy_is_explicitly_removable(self):
        self.prepared()
        script = """import sys,os,argparse
sys.dont_write_bytecode=True
sys.path.insert(0,sys.argv[1])
import installer_deploy as d
p=sys.argv[2]
a=argparse.Namespace(destination=__import__('pathlib').Path(p)/'external-asp',local_root=p,payload=p+'/payload',live_vendor=None,opt_in=True,confirm_inactive=True)
d.shutil.copytree=lambda *args,**kwargs: os._exit(87)
d.install(a)
"""
        r = subprocess.run([sys.executable, "-B", "-c", script, str(TOOLS), str(self.work)])
        self.assertEqual(r.returncode, 87)
        a = self.deployment()
        s = deploy.status(a)
        key = next(iter(s["generations"]))
        self.assertTrue(s["generations"][key]["preparation_pending"])
        with self.assertRaisesRegex(ValueError, "interrupted"):
            deploy.install(a)
        a.generation = key
        deploy.uninstall(a)
        self.assertEqual(deploy.status(a)["generations"], {})

    def test_50_active_mount_refused_without_mounting(self):
        proc = self.work / "proc"
        (proc / "self").mkdir(parents=True)
        (proc / "self/mountinfo").write_text("1 0 0:1 / " + str(self.work / "external-asp/lib/rootfs/sys") + " ro - sysfs sysfs ro\n")
        with self.assertRaisesRegex(ValueError, "active runtime mount"):
            deploy.active_check([self.work / "external-asp"], proc=proc, local=True)

    def test_51_unknown_sibling_preserved(self):
        p = self.work / (deploy.PREFIX + "owner-folder")
        p.mkdir()
        (p / "owner-data").write_text("KEEP")
        with self.assertRaisesRegex(ValueError, "not recognized"):
            deploy.status(self.deployment())
        self.assertEqual((p / "owner-data").read_text(), "KEEP")

    def test_52_missing_vendor_in_ota_refused(self):
        p = self.work / "incomplete.zip"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr(sources.META, "ota-type=FILE\npre-device=athena\npost-build=" + FINGERPRINT + "\npost-build-incremental=1\n")
            z.writestr("system/build.prop", (self.src / "system/build.prop").read_bytes())
        with self.assertRaisesRegex(ValueError, "incomplete"):
            sources.ota_open(p)

    def test_53_metadata_build_label_not_a_gate(self):
        p = self.work / "metadata-mismatch.zip"
        zip_tree(self.src, p, {"post-build": "OTHER_BUILD"})
        a = self.work / "authority.json"
        payload.write_json(a, dict(self.authority, official_ota_sha256=sources.digest(p)))
        self.prepared(ota=p, source_authority=None, fixture=True)
        self.assertTrue((self.work / "payload").exists())

    def test_54_source_symlink_not_followed(self):
        root = self.work / "source"
        root.mkdir()
        (root / "build.prop").symlink_to(self.src / "system/build.prop")
        with self.assertRaisesRegex(ValueError, "symlink"):
            sources.Directory(root).read("build.prop")

    def test_55_unsafe_installed_mode_refuses_deletion(self):
        self.prepared()
        a = self.deployment()
        a.generation = deploy.install(a)["installed"]
        (a.destination / "lib").chmod(0o777)
        with self.assertRaisesRegex(ValueError, "permissions"):
            deploy.uninstall(a)
        self.assertTrue(a.destination.exists())

    def test_56_unknown_nested_system_file_preserved(self):
        self.prepared()
        a = self.deployment()
        a.generation = deploy.install(a)["installed"]
        p = a.destination / "lib/rootfs/system/owner-data"
        p.write_text("KEEP")
        with self.assertRaisesRegex(ValueError, "content/size changed"):
            deploy.uninstall(a)
        self.assertEqual(p.read_text(), "KEEP")

    def test_57_duplicate_ota_member_refused(self):
        p = self.work / "duplicate.zip"
        zip_tree(self.src, p)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(p, "a") as z:
                z.writestr("system/build.prop", b"DUPLICATE")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            sources.ota_open(p)

    def test_58_malformed_authority_object_is_clear_refusal(self):
        p = self.work / "bad-authority.json"
        p.write_text("[]")
        r = self.command("inspect", "--mode", sources.BUNDLE, "--ota", self.ota,
                         "--source-authority", p)
        self.assertEqual(r.returncode, 2)
        self.assertIn("must be an object", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_59_interrupted_rollback_retains_exact_generations(self):
        self.prepared()
        a = self.deployment()
        first = deploy.install(a)["installed"]
        second = deploy.install(a)["installed"]
        a.generation = first
        with patch.object(deploy, "rename_atomic", side_effect=OSError("rollback interrupted")):
            with self.assertRaises(OSError):
                deploy.rollback(a)
        self.assertTrue(deploy.status(a)["generations"][second]["current"])
        deploy.rollback(a)
        self.assertTrue(deploy.status(a)["generations"][first]["current"])

    def test_60_helper_quiesce_failure_never_publishes(self):
        self.prepared()
        a = self.deployment(stop_helpers=True, maintenance_ack=True)
        with patch("installer_helpers.stop", side_effect=ValueError("helper restarted")):
            with self.assertRaisesRegex(ValueError, "restarted"):
                deploy.install(a)
        self.assertFalse(a.destination.exists())

    def test_61_stock_techo5_preserved_through_transactions(self):
        import test_helpers
        fake = test_helpers.Helpers()
        fake.setUp()
        try:
            stock = fake.process(exe=fake.stock, comm="techo5")
            before = (stock / "stat").read_bytes()
            self.prepared()
            a = self.deployment()
            original = deploy.active_check
            def check(roots, **kwargs):
                return original(roots, fake.proc, local=False)
            with patch.object(deploy, "active_check", side_effect=check):
                deploy.dry_run(a)
                first = deploy.install(a)["installed"]
                second = deploy.install(a)["installed"]
                self.assertTrue(deploy.status(a)["inactive"])
                a.generation = first
                deploy.rollback(a)
                deploy.uninstall(a)
                a.generation = second
                deploy.uninstall(a)
            self.assertEqual((stock / "stat").read_bytes(), before)
        finally:
            fake.tearDown()

    def test_62_no_hidden_source_authority_fingerprint_fields(self):
        self.prepared(mode=sources.LIVE)
        a = self.deployment()
        p = a.payload / payload.RECEIPT
        r = json.loads(p.read_text())
        del r["source_authority"]
        del r["source"]["identity"]["fingerprint"]
        payload.write_json(p, r)
        deploy.dry_run(a)


if __name__ == "__main__":
    unittest.main(verbosity=2)
