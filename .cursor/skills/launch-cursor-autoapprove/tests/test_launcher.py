from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


LAUNCHER_PATH = Path(__file__).parents[1] / "scripts" / "launcher.py"
SPEC = importlib.util.spec_from_file_location("launch_autoapprove_launcher", LAUNCHER_PATH)
assert SPEC and SPEC.loader
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class ParserTests(unittest.TestCase):
    def test_default_poll_interval_is_half_second(self) -> None:
        parser, _ = launcher.build_parser()

        launch = parser.parse_args(["launch", "/workspace"])
        launch_ssh = parser.parse_args(["launch-ssh", "devbox"])

        self.assertEqual(launcher.DEFAULT_POLL_INTERVAL_SECONDS, 0.5)
        self.assertEqual(launch.interval, 0.5)
        self.assertEqual(launch_ssh.interval, 0.5)
        self.assertEqual(launcher._session_poll_interval({}), 0.5)
        self.assertEqual(
            launcher._session_poll_interval({"poll_interval_seconds": "invalid"}),
            0.5,
        )

    def test_cycle_modes_and_subagents_json(self) -> None:
        parser, _ = launcher.build_parser()
        cycle = parser.parse_args(["cycle", "--once", "-w", "repo"])
        self.assertEqual(cycle.cycle_mode, "once")
        self.assertEqual(cycle.workspace, "repo")

        subagents = parser.parse_args(["subagents", "--json", "repo"])
        self.assertTrue(subagents.json_output)
        self.assertEqual(subagents.workspace_pos, "repo")

    def test_cycle_requires_exactly_one_mode(self) -> None:
        parser, _ = launcher.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["cycle"])
        with self.assertRaises(SystemExit):
            parser.parse_args(["cycle", "--on", "--once"])


class SubagentSnapshotTests(unittest.TestCase):
    def test_snapshot_sanitizer_removes_prompt_and_command_content(self) -> None:
        raw = {
            "version": 1,
            "scriptHash": "abc",
            "workspace": "/wrong",
            "targetId": "target",
            "cycleEnabled": True,
            "counts": {"active": 1},
            "tasks": [{
                "taskKey": "task",
                "rowKey": "row",
                "status": "running",
                "title": "Safe title",
                "command": "secret-token",
                "prompt": {"text": "secret prompt"},
            }],
            "command": "top-level-secret",
        }

        clean = launcher._sanitize_subagent_snapshot(raw, "/workspace", "repo")

        self.assertEqual(clean["workspace"], "/workspace")
        self.assertEqual(clean["slug"], "repo")
        self.assertNotIn("command", clean)
        self.assertNotIn("command", clean["tasks"][0])
        self.assertNotIn("prompt", clean["tasks"][0])
        self.assertEqual(clean["tasks"][0]["title"], "Safe title")

    def test_sync_writes_atomic_multi_session_snapshot(self) -> None:
        exported = {
            "version": 1,
            "targetId": "target",
            "cycleEnabled": False,
            "counts": {"active": 1},
            "tasks": [{"taskKey": "task", "rowKey": "row", "status": "running"}],
        }
        cdp_result = {
            "result": {
                "result": {
                    "value": json.dumps(exported),
                },
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = Path(tmpdir)
            with (
                mock.patch.object(launcher, "RUNTIME_DIR", runtime),
                mock.patch.object(launcher, "SUBAGENTS_PATH", runtime / "subagents.json"),
                mock.patch.object(launcher, "_cdp_evaluate", return_value=cdp_result),
            ):
                snapshot = launcher._sync_subagent_registry(
                    9222, "target", "/workspace", "repo",
                )
                saved = json.loads((runtime / "subagents.json").read_text())

        self.assertIsNotNone(snapshot)
        self.assertEqual(saved["sessions"]["/workspace"]["tasks"][0]["taskKey"], "task")


class CdpJsonTests(unittest.TestCase):
    def test_json_expression_requests_promise_awaiting(self) -> None:
        cdp_result = {
            "result": {
                "result": {
                    "value": json.dumps({"ok": True}),
                },
            },
        }
        with mock.patch.object(launcher, "_cdp_evaluate", return_value=cdp_result) as evaluate:
            result = launcher._cdp_json_expression(
                9222,
                "(async () => ({ok:true}))()",
                "target",
                await_promise=True,
            )

        self.assertEqual(result, {"ok": True})
        self.assertTrue(evaluate.call_args.kwargs["await_promise"])


class TargetRebindTests(unittest.TestCase):
    def test_rebinds_only_unique_replacement_workbench(self) -> None:
        session = {
            "workspace": "/workspace",
            "cdp_port": 9222,
            "cdp_target_id": "old",
        }
        state = {"sessions": {"/workspace": dict(session)}}
        with (
            mock.patch.object(
                launcher,
                "_cdp_list_page_targets",
                return_value=[{"id": "new", "type": "page"}],
            ),
            mock.patch.object(launcher, "_is_workbench", return_value=True),
            mock.patch.object(launcher, "_load_state", return_value=state),
            mock.patch.object(launcher, "_save_state") as save_state,
        ):
            target, changed = launcher._rebind_session_target_if_unique(session)

        self.assertTrue(changed)
        self.assertEqual(target, "new")
        self.assertEqual(session["cdp_target_id"], "new")
        save_state.assert_called_once()

    def test_does_not_rebind_ambiguous_workbenches(self) -> None:
        session = {
            "workspace": "/workspace",
            "cdp_port": 9222,
            "cdp_target_id": "old",
        }
        with (
            mock.patch.object(
                launcher,
                "_cdp_list_page_targets",
                return_value=[{"id": "one"}, {"id": "two"}],
            ),
            mock.patch.object(launcher, "_is_workbench", return_value=True),
        ):
            target, changed = launcher._rebind_session_target_if_unique(session)

        self.assertFalse(changed)
        self.assertEqual(target, "old")


if __name__ == "__main__":
    unittest.main()
