"""Standalone FrankenASP / TECHO5 adapter source-version stamp regression tests.

Uses tiny isolated Git repositories and a fake Go toolchain. Does not build
firmware, access any Echo or read owner-local factory components.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


SOURCE_SCRIPT = Path(__file__).resolve().parents[1] / "build_experimental.sh"


class BuildVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="frankenasp-version-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.franken = self.root / "frankenasp"
        self.adapter = self.root / "techo5-adapter"
        self.franken.mkdir()
        (self.adapter / "echod/internal/hardware/mic").mkdir(parents=True)
        (self.franken / "tools/frankenasp").mkdir(parents=True)
        shutil.copyfile(SOURCE_SCRIPT, self.franken / "tools/frankenasp/build_experimental.sh")
        (self.franken / "README.md").write_text("Research toolkit\n", encoding="utf-8")
        (self.adapter / "echod/internal/hardware/mic/factory_asp_athena.go").write_text(
            "package mic\n", encoding="utf-8"
        )
        self.frankensha = self.init_repo(self.franken)
        self.adaptersha = self.init_repo(self.adapter)
        self.git(self.franken, "tag", "-a", "v1.0.0-dev.1", "-m", "test release")
        self.fakebin = self.root / "fakebin"
        self.fakebin.mkdir()
        go = self.fakebin / "go"
        go.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$@" > "$GO_ARGS_LOG"\n'
            'while [ "$#" -gt 0 ]; do\n'
            '  if [ "$1" = "-o" ]; then shift; printf "fake test output\\n" > "$1"; fi\n'
            '  shift\n'
            'done\n', encoding="utf-8"
        )
        go.chmod(0o755)
        self.output = self.root / "built" / "techo5-experimental"
        self.log = self.root / "go-argv.txt"

    def git(self, root, *args):
        env = dict(os.environ, GIT_AUTHOR_NAME="CI Tester", GIT_AUTHOR_EMAIL="ci@example.invalid",
                   GIT_COMMITTER_NAME="CI Tester", GIT_COMMITTER_EMAIL="ci@example.invalid")
        return subprocess.check_output(["git", "-C", str(root), *args], env=env, text=True).strip()

    def init_repo(self, root):
        self.git(root, "init", "-q")
        self.git(root, "add", "-A")
        self.git(root, "commit", "-qm", "fixture baseline")
        return self.git(root, "rev-parse", "HEAD")

    def run_build(self, base="v1.6.0", adapter_root=None):
        env = os.environ.copy()
        env["TECHO5_ADAPTER_ROOT"] = str(adapter_root or self.adapter)
        env["PATH"] = str(self.fakebin) + os.pathsep + env.get("PATH", "")
        env["GO_ARGS_LOG"] = str(self.log)
        return subprocess.run(
            ["bash", str(self.franken / "tools/frankenasp/build_experimental.sh"), base, str(self.output)],
            capture_output=True, text=True, env=env, cwd=self.root
        )

    def test_exact_release_tag_and_full_provenance(self):
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = f"v1.6.0_frankenasp-1.0.0-dev.1.f{self.frankensha[:10]}.a{self.adaptersha[:10]}"
        self.assertIn("Staged software version: " + expected, result.stdout)
        self.assertTrue(self.output.exists())
        go_args = self.log.read_text(encoding="utf-8")
        self.assertIn("Version=" + expected, go_args)
        self.assertIn("frankenasp=" + self.frankensha + ",adapter=" + self.adaptersha, go_args)

    def test_next_commit_cannot_claim_same_release(self):
        (self.franken / "README.md").write_text("Next development\n", encoding="utf-8")
        self.git(self.franken, "add", "README.md")
        self.git(self.franken, "commit", "-qm", "next commit")
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"frankenasp-1\.0\.0-dev\.1\.next1\.f[0-9a-f]{10}\.a")

    def test_dirty_in_each_checkout_has_independent_digest(self):
        (self.franken / "README.md").write_text("Uncommitted wrapper source changes\n")
        (self.adapter / "echod/internal/hardware/mic/factory_asp_athena.go").write_text(
            "package mic\n// uncommitted adapter patch\n"
        )
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"\.fd[0-9a-f]{12}\.ad[0-9a-f]{12}")
        self.assertIn("WARNING", result.stderr)

    def test_invalid_base_is_rejected(self):
        result = self.run_build("v9999")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())

    def test_adapter_without_factory_glue_is_rejected(self):
        bogus = self.root / "bogus"
        bogus.mkdir()
        result = self.run_build(adapter_root=bogus)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Not a FrankenASP-enabled", result.stderr)


if __name__ == "__main__":
    unittest.main()
