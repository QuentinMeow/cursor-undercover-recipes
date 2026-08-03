from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "branch_cleanup.py"
SPEC = importlib.util.spec_from_file_location("branch_cleanup", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
branch_cleanup = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = branch_cleanup
SPEC.loader.exec_module(branch_cleanup)


@unittest.skipUnless(shutil.which("git"), "git is required")
class BranchCleanupWorktreeTests(unittest.TestCase):
    def git(self, cwd: Path, *args: str) -> str:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, text=True, capture_output=True
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        return proc.stdout.strip()

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.remote = root / "origin.git"
        self.seed = root / "seed"
        self.primary = root / "primary"
        self.peer = root / "peer worktree"

        self.git(root, "init", "--bare", str(self.remote))
        self.git(self.remote, "symbolic-ref", "HEAD", "refs/heads/main")
        self.git(root, "init", str(self.seed))
        self.git(self.seed, "config", "user.name", "Branch Cleanup Test")
        self.git(self.seed, "config", "user.email", "branch-cleanup@example.test")
        self.git(self.seed, "checkout", "-b", "main")
        (self.seed / "tracked.txt").write_text("base\n", encoding="utf-8")
        self.git(self.seed, "add", "tracked.txt")
        self.git(self.seed, "commit", "-m", "base")
        self.git(self.seed, "remote", "add", "origin", str(self.remote))
        self.git(self.seed, "push", "-u", "origin", "main")

        self.git(root, "clone", str(self.remote), str(self.primary))
        self.git(self.primary, "config", "user.name", "Branch Cleanup Test")
        self.git(self.primary, "config", "user.email", "branch-cleanup@example.test")

    def run_main(self, *args: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(
            branch_cleanup, "repo_root", return_value=str(self.primary)
        ), mock.patch.object(
            branch_cleanup.shutil, "which", return_value=None
        ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = branch_cleanup.main(list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_fetch_refreshes_tracking_ref_without_moving_main_in_peer(self) -> None:
        old_main = self.git(self.primary, "rev-parse", "main")
        self.git(self.primary, "checkout", "-b", "runner")
        self.git(self.primary, "worktree", "add", str(self.peer), "main")

        (self.seed / "tracked.txt").write_text("base\nremote advance\n", encoding="utf-8")
        self.git(self.seed, "add", "tracked.txt")
        self.git(self.seed, "commit", "-m", "advance main")
        self.git(self.seed, "push", "origin", "main")
        remote_main = self.git(self.seed, "rev-parse", "main")

        calls: list[tuple[str, ...]] = []
        original_git = branch_cleanup.git

        def recording_git(cwd: str, args: list[str], check: bool = False):
            calls.append(tuple(args))
            return original_git(cwd, args, check)

        with mock.patch.object(branch_cleanup, "git", side_effect=recording_git):
            code, output, error = self.run_main("--dry-run")

        self.assertEqual(code, 0, error)
        self.assertIn("Base: `origin/main`", output)
        self.assertEqual(self.git(self.primary, "rev-parse", "origin/main"), remote_main)
        self.assertEqual(self.git(self.primary, "rev-parse", "main"), old_main)
        self.assertEqual(self.git(self.peer, "rev-parse", "HEAD"), old_main)
        self.assertFalse(any(call[:1] == ("pull",) for call in calls), calls)
        self.assertFalse(
            any(any(":refs/heads/" in arg for arg in call) for call in calls), calls
        )
        fetch_calls = [call for call in calls if call[:1] == ("fetch",)]
        self.assertEqual(len(fetch_calls), 1, fetch_calls)
        self.assertEqual(fetch_calls[0][:4], ("fetch", "--prune", "--no-tags", "origin"))
        self.assertEqual(fetch_calls[0][4:], ("+refs/heads/*:refs/remotes/origin/*",))

    def test_dirty_peer_files_and_index_are_unchanged(self) -> None:
        old_main = self.git(self.primary, "rev-parse", "main")
        self.git(self.primary, "checkout", "-b", "runner")
        self.git(self.primary, "worktree", "add", str(self.peer), "main")
        (self.peer / "tracked.txt").write_text("dirty peer\n", encoding="utf-8")
        before_status = self.git(self.peer, "status", "--porcelain=v1")

        (self.seed / "tracked.txt").write_text("base\nremote advance\n", encoding="utf-8")
        self.git(self.seed, "add", "tracked.txt")
        self.git(self.seed, "commit", "-m", "advance main")
        self.git(self.seed, "push", "origin", "main")

        code, _, error = self.run_main("--dry-run")

        self.assertEqual(code, 0, error)
        self.assertEqual(self.git(self.primary, "rev-parse", "main"), old_main)
        self.assertEqual(self.git(self.peer, "rev-parse", "HEAD"), old_main)
        self.assertEqual(self.git(self.peer, "status", "--porcelain=v1"), before_status)
        self.assertEqual((self.peer / "tracked.txt").read_text(), "dirty peer\n")

    def test_clean_skips_every_branch_checked_out_in_a_worktree(self) -> None:
        self.git(self.primary, "branch", "feature")
        self.git(self.primary, "branch", "stale")
        self.git(self.primary, "checkout", "-b", "runner")
        self.git(self.primary, "worktree", "add", str(self.peer), "feature")

        cleaned: list[str] = []
        original_clean = branch_cleanup.clean_branch

        def recording_clean(cwd: str, branch: str):
            cleaned.append(branch)
            return original_clean(cwd, branch)

        with mock.patch.object(branch_cleanup, "clean_branch", side_effect=recording_clean):
            code, output, error = self.run_main("--clean", "--no-fetch")

        self.assertEqual(code, 0, error)
        self.assertEqual(cleaned, ["stale"])
        self.assertEqual(
            self.git(self.primary, "rev-parse", "--verify", "refs/heads/feature"),
            self.git(self.peer, "rev-parse", "HEAD"),
        )
        self.assertEqual(self.git(self.primary, "branch", "--list", "runner"), "* runner")
        self.assertEqual(self.git(self.primary, "branch", "--list", "stale"), "")
        self.assertIn("merged; kept (checked out in worktree)", output)
        self.assertIn(str(self.peer), output)

    def test_detached_invoking_worktree_can_clean_unoccupied_branch(self) -> None:
        self.git(self.primary, "branch", "stale")
        self.git(self.primary, "checkout", "--detach", "main")

        code, output, error = self.run_main("--clean", "--no-fetch")

        self.assertEqual(code, 0, error)
        self.assertEqual(self.git(self.primary, "branch", "--list", "stale"), "")
        self.assertIn("merged and cleaned locally", output)
        self.assertNotIn("current branch", output)

    def test_clean_refuses_to_delete_when_fetch_fails(self) -> None:
        """A stale comparison base must never authorize destructive cleanup."""
        self.git(self.primary, "branch", "stale")
        self.git(self.primary, "checkout", "-b", "runner")

        cleaned: list[str] = []
        original_git = branch_cleanup.git
        original_clean = branch_cleanup.clean_branch

        def fetch_failure(cwd: str, args: list[str], check: bool = False):
            if args[:4] == ["fetch", "--prune", "--no-tags", "origin"]:
                return subprocess.CompletedProcess(["git", *args], 1, "", "network unavailable")
            return original_git(cwd, args, check)

        def recording_clean(cwd: str, branch: str):
            cleaned.append(branch)
            return original_clean(cwd, branch)

        with mock.patch.object(
            branch_cleanup, "git", side_effect=fetch_failure
        ), mock.patch.object(branch_cleanup, "clean_branch", side_effect=recording_clean):
            code, _, error = self.run_main("--clean")

        self.assertEqual(code, 1)
        self.assertEqual(cleaned, [])
        self.assertIn("refusing cleanup", error)
        self.assertNotEqual(self.git(self.primary, "branch", "--list", "stale"), "")

    def test_clean_refuses_to_delete_when_worktree_inventory_fails(self) -> None:
        self.git(self.primary, "branch", "stale")
        self.git(self.primary, "checkout", "-b", "runner")

        cleaned: list[str] = []
        original_clean = branch_cleanup.clean_branch

        def recording_clean(cwd: str, branch: str):
            cleaned.append(branch)
            return original_clean(cwd, branch)

        with mock.patch.object(
            branch_cleanup,
            "checked_out_branches",
            side_effect=RuntimeError("could not inventory worktrees"),
        ), mock.patch.object(branch_cleanup, "clean_branch", side_effect=recording_clean):
            code, _, error = self.run_main("--clean", "--no-fetch")

        self.assertEqual(code, 1)
        self.assertEqual(cleaned, [])
        self.assertIn("could not inventory worktrees", error)
        self.assertNotEqual(self.git(self.primary, "branch", "--list", "stale"), "")

    def test_clean_refuses_to_delete_when_worktree_inventory_is_malformed(self) -> None:
        """Partial porcelain output cannot prove that another worktree is safe."""
        self.git(self.primary, "branch", "stale")
        self.git(self.primary, "checkout", "-b", "runner")

        cleaned: list[str] = []
        original_git = branch_cleanup.git
        original_clean = branch_cleanup.clean_branch

        def malformed_inventory(cwd: str, args: list[str], check: bool = False):
            if args == ["worktree", "list", "--porcelain"]:
                return subprocess.CompletedProcess(
                    ["git", *args],
                    0,
                    "worktree /path with spaces\nbranch refs/heads/feature\n",
                    "",
                )
            return original_git(cwd, args, check)

        def recording_clean(cwd: str, branch: str):
            cleaned.append(branch)
            return original_clean(cwd, branch)

        with mock.patch.object(
            branch_cleanup, "git", side_effect=malformed_inventory
        ), mock.patch.object(branch_cleanup, "clean_branch", side_effect=recording_clean):
            code, _, error = self.run_main("--clean", "--no-fetch")

        self.assertEqual(code, 1)
        self.assertEqual(cleaned, [])
        self.assertIn("worktree", error)
        self.assertNotEqual(self.git(self.primary, "branch", "--list", "stale"), "")

    def test_clean_refuses_to_delete_when_worktree_inventory_has_unknown_fields(self) -> None:
        """Unknown porcelain state must not be silently treated as safe inventory."""
        self.git(self.primary, "branch", "stale")
        self.git(self.primary, "checkout", "-b", "runner")

        cleaned: list[str] = []
        original_git = branch_cleanup.git
        original_clean = branch_cleanup.clean_branch

        def malformed_inventory(cwd: str, args: list[str], check: bool = False):
            if args == ["worktree", "list", "--porcelain"]:
                return subprocess.CompletedProcess(
                    ["git", *args],
                    0,
                    (
                        "worktree /path with spaces\n"
                        "HEAD deadbeef\n"
                        "branch refs/heads/feature\n"
                        "unexpected-state value\n"
                    ),
                    "",
                )
            return original_git(cwd, args, check)

        def recording_clean(cwd: str, branch: str):
            cleaned.append(branch)
            return original_clean(cwd, branch)

        with mock.patch.object(
            branch_cleanup, "git", side_effect=malformed_inventory
        ), mock.patch.object(branch_cleanup, "clean_branch", side_effect=recording_clean):
            code, _, error = self.run_main("--clean", "--no-fetch")

        self.assertEqual(code, 1)
        self.assertEqual(cleaned, [])
        self.assertIn("worktree", error)
        self.assertNotEqual(self.git(self.primary, "branch", "--list", "stale"), "")


if __name__ == "__main__":
    unittest.main()
