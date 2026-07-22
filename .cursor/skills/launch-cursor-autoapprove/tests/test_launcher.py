from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


LAUNCHER_PATH = Path(__file__).parents[1] / "scripts" / "launcher.py"
INJECTOR_PATH = Path(__file__).parents[1] / "scripts" / "devtools_auto_accept.js"
SPEC = importlib.util.spec_from_file_location("launch_autoapprove_launcher", LAUNCHER_PATH)
assert SPEC and SPEC.loader
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class InjectorSourceTests(unittest.TestCase):
    def test_subagent_cycling_is_enabled_in_initial_renderer_state(self) -> None:
        source = INJECTOR_PATH.read_text()
        state_start = source.index("const state = {")
        state_end = source.index("\n  };", state_start)
        initial_state = source[state_start:state_end]

        self.assertIn("cycleEnabled: true,", initial_state)
        self.assertNotIn("cycleEnabled: false,", initial_state)

    def test_failed_task_stays_failed_while_approval_remains_visible(self) -> None:
        source = INJECTOR_PATH.read_text()
        function_start = source.index("function _deriveTaskStatus(")
        function_end = source.index("\n  function ", function_start)
        derive_status = source[function_start:function_end]

        self.assertIn(
            'return existingStatus === "failed" ? "failed" : "approval_pending";',
            derive_status,
        )
        self.assertNotIn(
            'if (_visibleRowApproval(row)) return "approval_pending";',
            derive_status,
        )

    def test_cycle_owned_subagents_bypass_normal_and_debug_eligible_paths(self) -> None:
        source = INJECTOR_PATH.read_text()

        ownership_start = source.index("function _isCycleOwnedSubagentCandidate(")
        ownership_end = source.index("\n  function ", ownership_start)
        ownership = source[ownership_start:ownership_end]
        self.assertIn(
            "if (!state.cycleEnabled || !btn?.el) return false;",
            ownership,
        )
        self.assertIn("return !!_taskForRow(row);", ownership)

        scanner_start = source.index("function _checkAndClickImpl(")
        scanner_end = source.index("\n  function ", scanner_start)
        scanner = source[scanner_start:scanner_end]
        self.assertIn(
            "cycleOwned: _isCycleOwnedSubagentCandidate(btn),",
            scanner,
        )
        self.assertIn(
            ".filter((btn) => btn.reason !== null && !btn.cycleOwned)",
            scanner,
        )
        self.assertEqual(
            scanner.count("!btn.cycleOwned && btn.reason === null"),
            2,
        )

        debug_start = source.index("function debugSnapshot(")
        debug_end = source.index("\n  function ", debug_start)
        debug_snapshot = source[debug_start:debug_end]
        self.assertIn(
            "cycleOwned: _isCycleOwnedSubagentCandidate(btn),",
            debug_snapshot,
        )
        self.assertIn(
            "eligible: candidates.filter((c) => c.reason !== null && !c.cycleOwned),",
            debug_snapshot,
        )

    def test_scanner_skips_cooling_candidates_before_selecting_one(self) -> None:
        source = INJECTOR_PATH.read_text()
        scanner_start = source.index("function _checkAndClickImpl(")
        scanner_end = source.index("\n  function ", scanner_start)
        scanner = source[scanner_start:scanner_end]

        self.assertIn(
            "const btn = eligible.find((candidate) => "
            "!_isCoolingDown(candidate.fingerprint));",
            scanner,
        )
        self.assertIn("if (!btn) return;", scanner)
        self.assertNotIn("const btn = eligible[0];", scanner)
        self.assertNotIn("if (_isCoolingDown(btn.fingerprint))", scanner)


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
