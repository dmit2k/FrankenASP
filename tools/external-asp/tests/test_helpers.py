#!/usr/bin/env python3
"""Fake /proc and controlled syscall mocks only; never signal real services."""
import argparse
import contextlib
import io
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import installer_helpers as h
import installer_deploy as deploy


class Helpers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="asp2-helper-")
        self.base = Path(self.tmp.name)
        self.root = self.base / "external-asp"
        for sub in ("bin", "lib/rootfs/factory", "lib/rootfs/system", "lib/rootfs/vendor",
                    "lib/rootfs/sys", "lib/rootfs/.realproc", "lib/rootfs/dev", "lib/rootfs/data"):
            (self.root / sub).mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        for sub in ("bin/external-asp", "lib/rootfs/factory/asp2-child"):
            (self.root / sub).write_bytes(b"SYNTHETIC")
            (self.root / sub).chmod(0o500)
        self.stock = self.base / "techo5"
        self.stock.write_bytes(b"FAKE STOCK")
        self.stock.chmod(0o500)
        self.foreign = self.base / "foreign"
        self.foreign.write_bytes(b"UNRELATED")
        self.foreign.chmod(0o500)
        self.proc = self.base / "proc"
        (self.proc / "self/ns").mkdir(parents=True)
        self.host_ns = self.proc / "self/ns/mnt"
        self.host_ns.write_text("host")
        (self.proc / "self/mountinfo").write_text("1 0 0:1 / / rw - ext4 root rw\n")
        self.private_ns = self.base / "private-namespace"
        self.private_ns.write_text("private")
        self.args = argparse.Namespace(opt_in=True, maintenance_ack=True, local_root=self.base,
                                       force_kill=False, force_unmount=False, r1_host=[])
        self.signals = []
        # All process-root changes stay mocked; no real chroot/setns in tests.
        for name in ("fchdir", "chroot", "chdir"):
            mock = patch.object(h.os, name)
            mock.start()
            self.addCleanup(mock.stop)

    def tearDown(self):
        self.doCleanups()
        self.tmp.cleanup()

    def process(self, pid=100, exe=None, parent=1, comm="external-asp", private=False, chroot=False,
                start=123, mounts=None):
        p = self.proc / str(pid)
        p.mkdir()
        (p / "fd").mkdir()
        (p / "ns").mkdir()
        (p / "exe").symlink_to(exe or self.root / "bin/external-asp")
        (p / "root").symlink_to(self.root / "lib/rootfs" if chroot else "/")
        (p / "cwd").symlink_to("/")
        (p / "comm").write_text(comm)
        self.set_stat(p, start, parent)
        (p / "maps").write_text("")
        (p / "mountinfo").write_text(mounts or "1 0 0:1 / / rw - ext4 root rw\n")
        os.link(self.private_ns if private else self.host_ns, p / "ns/mnt")
        return p

    def set_stat(self, p, start, parent=1, state="S"):
        (p / "stat").write_text(p.name + " (name with spaces) " +
                               " ".join([state, str(parent)] + ["0"] * 17 + [str(start)] + ["0"] * 8))

    def scan(self):
        return h.scan([self.root], self.proc, True, self.args.r1_host)

    def test_stock_techo5_never_target_and_does_not_block_inactive(self):
        self.process(exe=self.stock, comm="techo5", parent=1)
        plan = self.scan()
        self.assertFalse(plan["targets"])
        self.assertIn("preserved", plan["hosts"][0]["role"])
        deploy.active_check([self.root], self.proc, local=False)

    def test_unrelated_name_never_target(self):
        self.process(exe=self.foreign, comm="external-asp")
        plan = self.scan()
        self.assertFalse(plan["targets"])
        self.assertEqual(len(plan["unrelated"]), 1)

    def test_owned_launcher_inode_and_orphan_child(self):
        self.process(pid=100)
        self.process(pid=101, exe=self.root / "lib/rootfs/factory/asp2-child", private=True, chroot=True)
        plan = self.scan()
        self.assertEqual(len(plan["targets"]), 2)
        self.assertIn("orphan-bionic-child", [p["role"] for p in plan["targets"]])

    def test_r1_helper_at_different_path_verified_by_parent_fds_and_pipes(self):
        other = self.base / "another-helper"
        (other / "bin").mkdir(parents=True, mode=0o700)
        other.chmod(0o700)
        (other / "bin/external-asp").write_bytes(b"OTHER OWNER HELPER")
        (other / "bin/external-asp").chmod(0o500)
        host = self.process(pid=50, exe=self.stock, comm="techo5")
        helper = self.process(pid=100, exe=other / "bin/external-asp", parent=50)
        for fd, target in (("3", other / "bin/external-asp"), ("4", other)):
            (helper / "fd" / fd).symlink_to(target)
        for fd, target in (("0", "pipe:[12345]"), ("1", "pipe:[12346]")):
            (helper / "fd" / fd).symlink_to(target)
            (host / "fd" / ("9" + fd)).symlink_to(target)
        self.args.r1_host = [self.stock]
        plan = self.scan()
        self.assertEqual(plan["targets"][0]["role"], "r1-external-helper")
        self.assertEqual(plan["targets"][0]["root_generation"], str(other))

    def test_r1_host_without_fd_parent_proof_is_not_authority(self):
        self.process(pid=50, exe=self.stock, comm="techo5")
        self.process(pid=100, exe=self.foreign, parent=50)
        self.args.r1_host = [self.stock]
        self.assertFalse(self.scan()["targets"])

    def test_pid_reuse_prevents_signal(self):
        entry = self.process()
        p = h.snapshot(entry)
        self.set_stat(entry, 124)
        with patch.object(h.os, "kill") as kill:
            with self.assertRaisesRegex(ValueError, "identity changed"):
                h.Handle(p, self.proc)
            kill.assert_not_called()

    def test_parent_race_prevents_signal(self):
        entry = self.process()
        p = h.snapshot(entry)
        self.set_stat(entry, 123, parent=44)
        with self.assertRaisesRegex(ValueError, "identity changed"):
            h.same(p, self.proc)

    def test_executable_race_prevents_signal(self):
        entry = self.process()
        p = h.snapshot(entry)
        (entry / "exe").unlink()
        (entry / "exe").symlink_to(self.foreign)
        with self.assertRaisesRegex(ValueError, "identity changed"):
            h.same(p, self.proc)

    def test_snapshot_race_fails_closed(self):
        entry = self.process()
        with patch.object(h, "stat_fields", side_effect=[("S", 1, 123), ("S", 1, 124)]):
            with self.assertRaisesRegex(ValueError, "changed during"):
                h.snapshot(entry)

    def test_already_dead_or_zombie_helper(self):
        entry = self.process()
        self.set_stat(entry, 123, state="Z")
        self.assertFalse(self.scan()["targets"])

    def test_active_pinned_fd_cwd_root_maps_and_namespace(self):
        entry = self.process(exe=self.foreign, comm="foreign")
        (entry / "fd/4").symlink_to(self.root)
        with self.assertRaisesRegex(ValueError, "active pinned"):
            deploy.active_check([self.root], self.proc, True)
        (entry / "fd/4").unlink()
        (entry / "maps").write_text("1-2 r-xp 0 0:1 1 " + str(self.root / "bin/external-asp") + "\n")
        with self.assertRaisesRegex(ValueError, "active mapped"):
            deploy.active_check([self.root], self.proc, True)
        (entry / "maps").write_text("")
        (entry / "root").unlink()
        (entry / "root").symlink_to(self.root / "lib/rootfs")
        with self.assertRaisesRegex(ValueError, "process rootfs"):
            deploy.active_check([self.root], self.proc, True)
        (entry / "root").unlink()
        (entry / "root").symlink_to("/")
        (entry / "mountinfo").write_text("2 1 0:1 / " + str(self.root / "lib/rootfs/sys") + " ro - sysfs sysfs ro\n")
        with self.assertRaisesRegex(ValueError, "mount namespace"):
            deploy.active_check([self.root], self.proc, True)

    def stop_plan(self):
        self.process()
        plan = self.scan()
        empty = dict(plan, targets=[], processes={})
        return plan, empty

    def run_stop(self, survival=False, respawn=False, blocked=False):
        plan, empty = self.stop_plan()
        if blocked:
            plan["blocked"] = [{"reason": "unreadable"}]
        scans = [plan, plan if respawn else empty, empty]
        signals = self.signals
        class FakeHandle:
            def __init__(self, p, proc):
                self.p, self.live = p, True
            def send(self, sig):
                signals.append(sig)
                if not survival or sig == signal.SIGKILL:
                    self.live = False
            def alive(self):
                return self.live
            def close(self):
                pass
        with patch.object(h, "WAIT", .001), patch.object(h, "SETTLE", 0), patch.object(h, "same", return_value=True), patch.object(
                deploy, "active_check") as active, contextlib.redirect_stderr(io.StringIO()):
            result = h.stop(self.args, [self.root], self.proc, scanner=Mock(side_effect=scans), handle_type=FakeHandle)
            active.assert_called_once()
            return result

    def test_term_only_success(self):
        self.assertTrue(self.run_stop()["stopped"])
        self.assertEqual(self.signals, [signal.SIGTERM])

    def test_partial_sigterm_no_force_blocks(self):
        with self.assertRaisesRegex(ValueError, "still alive"):
            self.run_stop(survival=True)
        self.assertEqual(self.signals, [signal.SIGTERM])

    def test_explicit_force_kill_after_term(self):
        self.args.force_kill = True
        self.run_stop(survival=True)
        self.assertEqual(self.signals, [signal.SIGTERM, signal.SIGKILL])

    def test_respawn_blocks_without_kill_loop(self):
        with self.assertRaisesRegex(ValueError, "restarted"):
            self.run_stop(respawn=True)
        self.assertEqual(self.signals, [signal.SIGTERM])

    def test_unreadable_plan_blocks_before_signal(self):
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.run_stop(blocked=True)
        self.assertFalse(self.signals)

    def test_stop_requires_separate_maintenance_ack(self):
        self.args.maintenance_ack = False
        with self.assertRaisesRegex(ValueError, "maintenance-ack"):
            h.stop(self.args, [self.root], self.proc)
        self.args.maintenance_ack, self.args.opt_in = True, False
        with self.assertRaisesRegex(ValueError, "opt-in"):
            h.stop(self.args, [self.root], self.proc)

    def mount_plan(self, unknown=False, propagation=""):
        root = str(self.root / "lib/rootfs")
        info = "2 1 0:1 / " + root + " ro - ext4 root ro\n"
        info += "3 2 0:1 / " + root + "/system ro - ext4 root ro\n"
        info += "4 2 0:2 / " + root + "/sys ro " + propagation + "- sysfs sysfs ro\n"
        if unknown:
            info += "5 2 0:3 / " + root + "/vendor/foreign ro - ext4 x ro\n"
        self.process(private=True, mounts=info)
        plan = self.scan()
        return plan, plan["targets"][0]

    def test_private_cleanup_reverse_order(self):
        plan, p = self.mount_plan()
        selected = h.cleanup_plan(p, plan, [self.root], self.proc)
        self.assertEqual(selected[-1]["target"], str(self.root / "lib/rootfs"))
        self.assertEqual(len(selected), 3)

    def test_unknown_mount_never_unmounted(self):
        plan, p = self.mount_plan(unknown=True)
        with self.assertRaisesRegex(ValueError, "unknown/protected"):
            h.cleanup_plan(p, plan, [self.root], self.proc)

    def test_shared_mount_never_unmounted(self):
        plan, p = self.mount_plan(propagation="shared:10 ")
        with self.assertRaisesRegex(ValueError, "unknown/protected"):
            h.cleanup_plan(p, plan, [self.root], self.proc)

    def test_host_namespace_never_unmounted(self):
        self.process()
        plan = self.scan()
        with self.assertRaisesRegex(ValueError, "host namespace"):
            h.cleanup_plan(plan["targets"][0], plan, [self.root], self.proc)

    def test_foreign_namespace_owner_blocks_cleanup(self):
        plan, p = self.mount_plan()
        plan["processes"][200] = dict(p, pid=200)
        with self.assertRaisesRegex(ValueError, "another owner"):
            h.cleanup_plan(p, plan, [self.root], self.proc)

    def test_other_namespace_fd_owner_detected(self):
        plan, p = self.mount_plan()
        plan["processes"][200] = dict(p, pid=200, namespace=(0, 1), fd_ids={"8": p["namespace"]})
        self.assertIn(200, h.namespace_users(plan, p["namespace"]))

    def test_mnt_detach_fallback_and_permission_failure(self):
        root = str(self.root / "lib/rootfs")
        m = {"id": 2, "target": root, "root": root, "options": ["ro"],
             "propagation": [], "fstype": "ext4", "source": "root"}
        libc = Mock()
        libc.setns.return_value = 0
        libc.umount2.side_effect = [1, 0]
        with patch.object(h, "inode", side_effect=[(0, 1), (0, 2)]), patch.object(
                h.ctypes, "CDLL", return_value=libc), patch.object(h, "mounts", side_effect=[[m], [m], []]):
            result = h.cleanup_child(10, (0, 2), [m], root, 11)
        self.assertTrue(result[0]["detached"])
        self.assertEqual([call.args[1] for call in libc.umount2.call_args_list], [0, 2])
        libc.umount2.side_effect = [1, 1]
        with patch.object(h, "inode", side_effect=[(0, 1), (0, 2)]), patch.object(
                h.ctypes, "CDLL", return_value=libc), patch.object(h, "mounts", return_value=[m]):
            with self.assertRaisesRegex(ValueError, "MNT_DETACH failed"):
                h.cleanup_child(10, (0, 2), [m], root, 11)

    def test_no_force_flags_without_stop_request(self):
        self.args.force_kill = True
        with self.assertRaisesRegex(ValueError, "stop-helpers"):
            deploy.quiesce(self.args, [self.root])

    def test_namespace_process_death_needs_no_global_cleanup(self):
        plan, empty = self.stop_plan()
        scanner = Mock(side_effect=[empty, empty, empty])
        self.args.force_unmount = True
        cleanup = Mock()
        with patch.object(h, "SETTLE", 0), patch.object(deploy, "active_check"), contextlib.redirect_stderr(io.StringIO()):
            result = h.stop(self.args, [self.root], self.proc, scanner=scanner, cleanup=cleanup)
        self.assertTrue(result["stopped"])
        cleanup.assert_not_called()

    def test_setns_permission_failure(self):
        libc = Mock()
        libc.setns.return_value = 1
        with patch.object(h, "inode", side_effect=[(0, 1), (0, 2)]), patch.object(
                h.ctypes, "CDLL", return_value=libc):
            with self.assertRaisesRegex(OSError, "setns refused"):
                h.cleanup_child(10, (0, 2), [], str(self.root / "lib/rootfs"), 11)
        libc.umount2.assert_not_called()

    def test_r1_bionic_child_after_fd3_fd4_close_outside_registry(self):
        import test_installer as fixtures
        from installer_payload import profile
        from installer_sources import BUNDLE
        other = self.base / "r1-other-generation"
        for sub in ("lib/rootfs/factory", "etc"):
            (other / sub).mkdir(parents=True, mode=0o700)
        other.chmod(0o700)
        child = other / "lib/rootfs/factory/asp2-child"
        child.write_bytes(fixtures.elf_fixture("/system/bin/linker"))
        child.chmod(0o500)
        (other / "etc/launcher.profile").write_bytes(profile(BUNDLE))
        host = self.process(pid=50, exe=self.stock, comm="techo5")
        child_proc = self.process(pid=100, exe=child, parent=50, private=True)
        (child_proc / "root").unlink()
        (child_proc / "root").symlink_to(other / "lib/rootfs")
        for fd, target in (("0", "pipe:[12345]"), ("1", "pipe:[12346]")):
            (child_proc / "fd" / fd).symlink_to(target)
            (host / "fd" / ("9" + fd)).symlink_to(target)
        # Real I1 wire is duplicated before stdout is redirected to stderr.
        (child_proc / "fd/1").unlink()
        (child_proc / "fd/1").symlink_to(self.foreign)
        (child_proc / "fd/9").symlink_to("pipe:[12346]")
        self.args.r1_host = [self.stock]
        plan = self.scan()
        self.assertEqual(plan["targets"][0]["role"], "r1-bionic-child")

    def test_pidfd_used_and_closed_without_numeric_signal(self):
        p = {"pid": 123, "start": 10}
        with patch.object(h, "same", return_value=True), patch.object(h.os, "pidfd_open", return_value=55), patch.object(
                h.signal, "pidfd_send_signal") as send, patch.object(h.os, "kill") as kill, patch.object(h.os, "close") as close:
            handle = h.Handle(p)
            handle.send(signal.SIGTERM)
            handle.close()
        send.assert_called_once_with(55, signal.SIGTERM)
        close.assert_called_once_with(55)
        kill.assert_not_called()

    def test_full_force_unmount_path_uses_pinned_private_namespace(self):
        plan, p = self.mount_plan()
        empty = dict(plan, targets=[], processes={})
        self.args.force_unmount = True
        cleanup = Mock(return_value=[{"target": str(self.root / "lib/rootfs"), "detached": False}])
        class DeadAfterTerm:
            def __init__(self, p, proc):
                self.p = p
            def send(self, sig):
                pass
            def alive(self):
                return False
            def close(self):
                pass
        with patch.object(h, "same", return_value=True), patch.object(h, "SETTLE", 0), patch.object(
                deploy, "active_check"), contextlib.redirect_stderr(io.StringIO()):
            result = h.stop(self.args, [self.root], self.proc, scanner=Mock(side_effect=[plan, empty, empty]),
                            handle_type=DeadAfterTerm, cleanup=cleanup)
        cleanup.assert_called_once()
        self.assertEqual(cleanup.call_args.args[1], p["namespace"])
        self.assertTrue(result["private_cleanup"])

    def test_new_mount_before_cleanup_blocks_without_umount(self):
        libc = Mock()
        libc.setns.return_value = 0
        with patch.object(h, "inode", side_effect=[(0, 1), (0, 2)]), patch.object(
                h.ctypes, "CDLL", return_value=libc), patch.object(h, "mounts", return_value=[{"target": "/unrelated"}]):
            with self.assertRaisesRegex(ValueError, "changed before cleanup"):
                h.cleanup_child(10, (0, 2), [{"target": str(self.root / "lib/rootfs")}], str(self.root / "lib/rootfs"), 11)
        libc.umount2.assert_not_called()

    def test_old_kernel_pidfd_fallback_revalidates_before_kill(self):
        import errno
        p = {"pid": 123, "start": 10}
        with patch.object(h, "same", return_value=True) as check, patch.object(
                h.os, "pidfd_open", side_effect=OSError(errno.ENOSYS, "unsupported")), patch.object(h.os, "kill") as kill:
            handle = h.Handle(p)
            handle.send(signal.SIGTERM)
            handle.close()
        self.assertEqual(check.call_count, 3)
        kill.assert_called_once_with(123, signal.SIGTERM)

    def test_dead_between_revalidation_and_signal_is_harmless(self):
        p = {"pid": 123, "start": 10}
        with patch.object(h, "same", return_value=True), patch.object(h.os, "pidfd_open", return_value=55), patch.object(
                h.signal, "pidfd_send_signal", side_effect=ProcessLookupError), patch.object(h.os, "close"):
            handle = h.Handle(p)
            self.assertFalse(handle.send(signal.SIGTERM))
            handle.close()

    def test_foreign_fd_pin_blocks_private_cleanup(self):
        plan, p = self.mount_plan()
        foreign = dict(p, pid=200, namespace=(0, 1), exe_path=str(self.foreign), cwd="/", root_path="/",
                       maps="", fds={"4": str(self.root)}, fd_ids={})
        plan["processes"][200] = foreign
        with self.assertRaisesRegex(ValueError, "another owner"):
            h.cleanup_plan(p, plan, [self.root], self.proc)

    def test_chrooted_namespace_root_anchor_is_pinned_and_released(self):
        entry = self.process(private=True, chroot=True)
        p = h.snapshot(entry)
        fd = h.pin_namespace_root(p, self.proc)
        try:
            self.assertEqual(h.inode("/proc/self/fd/" + str(fd)), h.inode("/"))
        finally:
            os.close(fd)

    def test_orphan_namespace_fd_is_blocked_kept_and_never_guessed(self):
        entry = self.process(exe=self.foreign, comm="foreign")
        fd = entry / "fd/8"
        fd.symlink_to(self.private_ns)
        original = os.readlink
        def readlink(path):
            return "mnt:[99999]" if Path(path) == fd else original(path)
        with patch.object(os, "readlink", side_effect=readlink):
            plan = self.scan()
            self.assertIn("orphan mount namespace", plan["blocked"][0]["reason"])
            with self.assertRaisesRegex(ValueError, "orphan mount namespace"):
                deploy.active_check([self.root], self.proc, True)
        self.assertTrue(fd.is_symlink())


if __name__ == "__main__":
    unittest.main(verbosity=2)
