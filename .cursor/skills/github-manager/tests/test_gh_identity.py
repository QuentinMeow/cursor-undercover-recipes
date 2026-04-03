from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "gh_identity.py"
SPEC = importlib.util.spec_from_file_location("gh_identity", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
gh_identity = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gh_identity
SPEC.loader.exec_module(gh_identity)


def completed(
    command: list[str], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], dict[str, object]]):
        self.responses = responses
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        key = tuple(command)
        self.calls.append(key)
        if key not in self.responses:
            raise AssertionError(f"Unexpected command: {command}")
        payload = self.responses[key]
        return completed(
            command,
            returncode=int(payload.get("returncode", 0)),
            stdout=str(payload.get("stdout", "")),
            stderr=str(payload.get("stderr", "")),
        )


def base_responses(repo_root: Path, active_login: str) -> dict[tuple[str, ...], dict[str, object]]:
    return {
        ("git", "rev-parse", "--show-toplevel"): {"stdout": f"{repo_root}\n"},
        ("git", "rev-parse", "--git-dir"): {"stdout": ".git\n"},
        ("git", "remote", "get-url", "origin"): {
            "stdout": "git@github.com-personal:QuentinMeow/cursor-undercover-recipes.git\n"
        },
        ("gh", "api", "--hostname", "github.com", "user", "-q", ".login"): {
            "stdout": f"{active_login}\n"
        },
    }


class GhIdentityTests(unittest.TestCase):
    def test_enter_switches_and_saves_previous_login(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            responses = base_responses(repo_root, "workuser")
            responses[("gh", "auth", "switch", "--hostname", "github.com", "--user", "QuentinMeow")] = {
                "stdout": ""
            }
            runner = FakeRunner(responses)

            payload = gh_identity.enter_identity(
                cwd=repo_root,
                hostname="github.com",
                target_user="QuentinMeow",
                state_path=None,
                dry_run=False,
                runner=runner,
            )

            self.assertEqual(payload["action"], "switched")
            state_path = repo_root / ".git" / "github-manager" / "gh_identity_state.json"
            self.assertTrue(state_path.exists())
            state = json.loads(state_path.read_text())
            self.assertEqual(state["previous_login"], "workuser")
            self.assertEqual(state["target_login"], "QuentinMeow")

    def test_enter_rolls_back_state_when_switch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            responses = base_responses(repo_root, "workuser")
            responses[("gh", "auth", "switch", "--hostname", "github.com", "--user", "QuentinMeow")] = {
                "returncode": 1,
                "stderr": "not logged in to github.com account QuentinMeow",
            }
            runner = FakeRunner(responses)

            with self.assertRaises(gh_identity.IdentityError):
                gh_identity.enter_identity(
                    cwd=repo_root,
                    hostname="github.com",
                    target_user="QuentinMeow",
                    state_path=None,
                    dry_run=False,
                    runner=runner,
                )

            state_path = repo_root / ".git" / "github-manager" / "gh_identity_state.json"
            self.assertFalse(state_path.exists())

    def test_nested_enter_increments_depth_without_switching_again(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            state_path = repo_root / ".git" / "github-manager" / "gh_identity_state.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "depth": 1,
                        "previous_login": "workuser",
                        "target_login": "QuentinMeow",
                        "hostname": "github.com",
                    }
                )
            )
            runner = FakeRunner(base_responses(repo_root, "QuentinMeow"))

            payload = gh_identity.enter_identity(
                cwd=repo_root,
                hostname="github.com",
                target_user="QuentinMeow",
                state_path=None,
                dry_run=False,
                runner=runner,
            )

            self.assertEqual(payload["action"], "incremented-depth")
            state = json.loads(state_path.read_text())
            self.assertEqual(state["depth"], 2)
            switch_command = (
                "gh",
                "auth",
                "switch",
                "--hostname",
                "github.com",
                "--user",
                "QuentinMeow",
            )
            self.assertNotIn(switch_command, runner.calls)

    def test_leave_restores_previous_login_and_clears_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            state_path = repo_root / ".git" / "github-manager" / "gh_identity_state.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "depth": 1,
                        "previous_login": "workuser",
                        "target_login": "QuentinMeow",
                        "hostname": "github.com",
                    }
                )
            )
            responses = base_responses(repo_root, "QuentinMeow")
            responses[("gh", "auth", "switch", "--hostname", "github.com", "--user", "workuser")] = {
                "stdout": ""
            }
            runner = FakeRunner(responses)

            payload = gh_identity.leave_identity(
                cwd=repo_root,
                hostname="github.com",
                state_path=None,
                dry_run=False,
                runner=runner,
            )

            self.assertEqual(payload["action"], "restored")
            self.assertFalse(state_path.exists())

    def test_leave_refuses_to_guess_when_active_login_is_unexpected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            state_path = repo_root / ".git" / "github-manager" / "gh_identity_state.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "depth": 1,
                        "previous_login": "workuser",
                        "target_login": "QuentinMeow",
                        "hostname": "github.com",
                    }
                )
            )
            runner = FakeRunner(base_responses(repo_root, "somebody-else"))

            with self.assertRaises(gh_identity.IdentityError):
                gh_identity.leave_identity(
                    cwd=repo_root,
                    hostname="github.com",
                    state_path=None,
                    dry_run=False,
                    runner=runner,
                )


if __name__ == "__main__":
    unittest.main()
