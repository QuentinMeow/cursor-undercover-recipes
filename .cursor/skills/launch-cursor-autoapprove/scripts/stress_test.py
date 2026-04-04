#!/usr/bin/env python3
"""Auto-approve harness: synthetic suite, real snapshot, and replay modes.

Modes:
  - synthetic: inject probe prompts and assert click behavior.
  - snapshot: capture live UI snapshots only (no synthetic prompt injection).
  - replay: load sanitized real-prompt fixture files and replay them as probes.

Defaults:
  - mode=snapshot (real UI, artifact-first)
  - synthetic suite=meaningful (short set of high-signal cases)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Reuse launcher's CDP helpers.
LAUNCHER = Path(__file__).parent / "launcher.py"
sys.path.insert(0, str(LAUNCHER.parent))

import launcher  # noqa: E402

POLL_INTERVAL = 3.0
SNAPSHOT_INTERVAL = 2.5
SNAPSHOT_DURATION = 60.0


def _run_id(suffix: str) -> str:
    return datetime.now(timezone.utc).strftime(f"%Y%m%d-%H%M-UTC-{suffix}")


def _btn(var: str, text: str, **kwargs: object) -> dict:
    return {"var": var, "text": text, **kwargs}


# Full matrix (kept for optional deep checks).
TEST_CASES: list[tuple[str, dict, bool, str | None]] = [
    # --- Category 1: Compound approval surfaces (dismiss + approval) ---
    ("dismiss+allow: Cancel+Allow",
     {"buttons": [_btn("a", "Cancel"), _btn("b", "Allow")]}, True, "allow"),
    ("dismiss+run: Skip+Run",
     {"buttons": [_btn("a", "Skip"), _btn("b", "Run")]}, True, "run"),
    ("dismiss+accept: Dismiss+Accept",
     {"buttons": [_btn("a", "Dismiss"), _btn("b", "Accept")]}, True, "accept"),
    ("dismiss+approve: Deny+Approve",
     {"buttons": [_btn("a", "Deny"), _btn("b", "Approve")]}, True, "approve"),
    ("dismiss+accept_all: Cancel+Accept All",
     {"buttons": [_btn("a", "Cancel"), _btn("b", "Accept All")]}, True, "accept_all"),
    ("dismiss+always_allow: Not Now+Always Allow",
     {"buttons": [_btn("a", "Not Now"), _btn("b", "Always Allow")]}, True, "always_allow"),
    ("dismiss+run_this_time: Close+Run This Time Only",
     {"buttons": [_btn("a", "Close"), _btn("b", "Run This Time Only")]}, True, "run_this_time"),
    ("dismiss+run_command: Cancel+Run Command",
     {"buttons": [_btn("a", "Cancel"), _btn("b", "Run Command")]}, True, "run_command"),
    ("dismiss+apply: Skip+Apply",
     {"buttons": [_btn("a", "Skip"), _btn("b", "Apply")]}, True, "apply"),
    ("dismiss+execute: Cancel+Execute",
     {"buttons": [_btn("a", "Cancel"), _btn("b", "Execute")]}, True, "execute"),

    # --- Companion + approval ---
    ("companion+allow: View+Allow",
     {"buttons": [_btn("a", "View"), _btn("b", "Allow")]}, True, "allow"),
    ("companion+run: Stop+Run",
     {"buttons": [_btn("a", "Stop"), _btn("b", "Run")]}, True, "run"),
    ("companion+accept: Details+Accept",
     {"buttons": [_btn("a", "Details"), _btn("b", "Accept")]}, True, "accept"),
    ("companion+approve: Show Details+Approve",
     {"buttons": [_btn("a", "Show Details"), _btn("b", "Approve")]}, True, "approve"),
    ("companion+continue: View+Continue",
     {"buttons": [_btn("a", "View"), _btn("b", "Continue")]}, True, "continue"),
    ("new_dismiss+allow: Reject+Allow",
     {"buttons": [_btn("a", "Reject"), _btn("b", "Allow")]}, True, "allow"),
    ("new_dismiss+run: Don't Allow+Run",
     {"buttons": [_btn("a", "Don\\'t Allow"), _btn("b", "Run")]}, True, "run"),
    ("new_dismiss+approve: Decline+Approve",
     {"buttons": [_btn("a", "Decline"), _btn("b", "Approve")]}, True, "approve"),
    ("companion+confirm: View+Confirm",
     {"buttons": [_btn("a", "View"), _btn("b", "Confirm")]}, True, "confirm"),
    ("companion+switch: Details+Switch Mode",
     {"buttons": [_btn("a", "Details"), _btn("b", "Switch Mode")]}, True, "switch_mode_explicit"),

    # --- Category 2: Single-action modals (approve* only) ---
    ("modal_approve: Approve (solo)",
     {"buttons": [_btn("a", "Approve")]}, True, "approve"),
    ("modal_approve_request: Approve Request (solo)",
     {"role": "alertdialog", "buttons": [_btn("a", "Approve Request")]}, True, "approve_request"),
    ("modal_approve_terminal: Approve Terminal Command (solo)",
     {"buttons": [_btn("a", "Approve Terminal Command")]}, True, "approve_terminal_command"),
    ("modal_approve_with_view: Approve+View (2 controls)",
     {"buttons": [_btn("a", "View"), _btn("b", "Approve")]}, True, "approve"),
    ("modal_approve_with_cancel: Cancel+Approve (dismiss path)",
     {"buttons": [_btn("a", "Cancel"), _btn("b", "Approve")]}, True, "approve"),
    ("modal_approve_3controls: Cancel+View+Approve",
     {"buttons": [_btn("a", "Cancel"), _btn("b", "View"), _btn("c", "Approve")]}, True, "approve"),

    # Non-approve* alone should NOT click
    ("modal_allow_solo: Allow (solo, no guard)",
     {"buttons": [_btn("a", "Allow")]}, False, None),
    ("modal_run_solo: Run (solo, no guard)",
     {"buttons": [_btn("a", "Run")]}, False, None),
    ("modal_accept_solo: Accept (solo, no guard)",
     {"buttons": [_btn("a", "Accept")]}, False, None),
    ("modal_continue_solo: Continue (solo, no guard)",
     {"buttons": [_btn("a", "Continue")]}, False, None),

    # --- Category 3: False-positive guards ---
    ("fp_excluded_sidebar: Allow in sidebar",
     {"excluded_zone": "workbench.parts.sidebar",
      "buttons": [_btn("a", "Cancel"), _btn("b", "Allow")]}, False, None),
    ("fp_excluded_editor: Run in editor",
     {"excluded_zone": "workbench.parts.editor",
      "buttons": [_btn("a", "Cancel"), _btn("b", "Run")]}, False, None),
    ("fp_excluded_panel: Accept in panel",
     {"excluded_zone": "workbench.parts.panel",
      "buttons": [_btn("a", "Skip"), _btn("b", "Accept")]}, False, None),
    ("fp_no_guard: Allow alone (no dismiss/companion)",
     {"role": None, "modal": False,
      "buttons": [_btn("a", "Allow")]}, False, None),
    ("fp_no_guard_run: Run alone (no guard)",
     {"role": None, "modal": False,
      "buttons": [_btn("a", "Run")]}, False, None),
    ("fp_invisible: Allow+Cancel but hidden",
     {"root_visible": False,
      "buttons": [_btn("a", "Cancel"), _btn("b", "Allow")]}, False, None),
    ("fp_disabled: Allow disabled+Cancel",
     {"buttons": [_btn("a", "Cancel"), _btn("b", "Allow", disabled=True)]}, False, None),
    ("fp_long_label: Very long approval label (>60 chars)",
     {"buttons": [_btn("a", "Cancel"),
      _btn("b", "Allow this very long permission request that exceeds the sixty character limit threshold")]},
     False, None),
    ("fp_unrelated_companion: View alone (no approval)",
     {"buttons": [_btn("a", "View")]}, False, None),
    ("fp_excluded_statusbar: Allow in statusbar",
     {"excluded_zone": "workbench.parts.statusbar",
      "buttons": [_btn("a", "Cancel"), _btn("b", "Allow")]}, False, None),

    # --- Category 4: Edge cases ---
    ("edge_keyboard_hint: Allow (⌃⏎)",
     {"buttons": [_btn("a", "Cancel"), _btn("b", "Allow (⌃⏎)")]}, True, "allow"),
    ("edge_keyboard_hint_run: Run ↩",
     {"buttons": [_btn("a", "Skip"), _btn("b", "Run ↩")]}, True, "run"),
    ("edge_mixed_case: ALLOW (uppercase)",
     {"buttons": [_btn("a", "Cancel"), _btn("b", "ALLOW")]}, True, "allow"),
    ("edge_whitespace: '  Allow  '",
     {"buttons": [_btn("a", "Cancel"), _btn("b", "  Allow  ")]}, True, "allow"),
    ("edge_role_button: span[role=button]+Cancel",
     {"buttons": [_btn("a", "Cancel"), _btn("b", "Allow", tag="span", role="button")]},
     True, "allow"),
    ("edge_pointer_events_none: Allow unclickable",
     {"buttons": [_btn("a", "Cancel"), _btn("b", "Allow", style="pointer-events:none")]},
     False, None),
    ("edge_opacity_zero: Allow invisible (opacity:0)",
     {"buttons": [_btn("a", "Cancel"), _btn("b", "Allow", style="opacity:0")]},
     False, None),
    ("edge_zero_size: Allow with 0 width/height (flex layout overrides to min-content)",
     {"buttons": [_btn("a", "Cancel"), _btn("b", "Allow", style="width:0;height:0;overflow:hidden")]},
     True, "allow"),
    ("edge_change_mode: Cancel+Change Mode",
     {"buttons": [_btn("a", "Cancel"), _btn("b", "Change Mode")]}, True, "change_mode"),
    ("edge_approve_terminal_with_view: View+Approve Terminal Command",
     {"buttons": [_btn("a", "View"), _btn("b", "Approve Terminal Command")]},
     True, "approve_terminal_command"),
    ("edge_plain_text_esc_hint: Skip Esc+Run ↩",
     {"buttons": [_btn("a", "Skip Esc"), _btn("b", "Run ↩")]}, True, "run"),
]

# 1-indexed into TEST_CASES.
MEANINGFUL_CASE_INDEXES = [
    1, 2, 11, 20, 23, 27, 32, 34, 37, 41, 43, 46, 50, 51
]


def _build_probe_js(spec: dict, probe_id: str) -> str:
    root_role = spec.get("role", "dialog")
    root_modal = spec.get("modal", True)
    root_style = spec.get(
        "style",
        "position:fixed;z-index:2147483647;top:10px;right:10px;background:#333;padding:8px;display:flex;gap:4px",
    )
    buttons = spec.get("buttons", [])
    excluded_zone = spec.get("excluded_zone")
    root_visible = spec.get("root_visible", True)

    lines = [f"const old = document.getElementById('{probe_id}');", "if (old) old.remove();"]
    if excluded_zone:
        lines.append("const zone = document.createElement('div');")
        lines.append(f"zone.id = '{excluded_zone}';")
    lines.append("const d = document.createElement('div');")
    lines.append(f"d.id = '{probe_id}';")
    if root_role:
        lines.append(f"d.setAttribute('role', '{root_role}');")
    if root_modal:
        lines.append("d.setAttribute('aria-modal', 'true');")
    if root_style:
        lines.append(f"d.style.cssText = '{root_style}';")
    if not root_visible:
        lines.append("d.style.display = 'none';")

    for btn in buttons:
        tag = btn.get("tag", "button")
        text = btn.get("text", "")
        role = btn.get("role")
        disabled = btn.get("disabled", False)
        style = btn.get("style", "")
        lines.append(f"const b_{btn['var']} = document.createElement('{tag}');")
        lines.append(f"b_{btn['var']}.textContent = '{text}';")
        lines.append(f"b_{btn['var']}.setAttribute('data-probe-button', '{btn['var']}');")
        lines.append(
            f"b_{btn['var']}.addEventListener('click', () => {{ d.setAttribute('data-clicked', '{btn['var']}'); d.remove(); }}, {{ once: true }});"
        )
        if role:
            lines.append(f"b_{btn['var']}.setAttribute('role', '{role}');")
        if disabled:
            lines.append(f"b_{btn['var']}.disabled = true;")
        if style:
            lines.append(f"b_{btn['var']}.style.cssText = '{style}';")
        lines.append(f"d.appendChild(b_{btn['var']});")

    content = spec.get("content")
    if content:
        escaped = json.dumps(content)
        lines.append(f"const pre = document.createElement('pre');")
        lines.append(f"const code = document.createElement('code');")
        lines.append(f"code.textContent = {escaped};")
        lines.append("pre.appendChild(code);")
        lines.append("d.insertBefore(pre, d.firstChild);")

    if excluded_zone:
        lines.append("zone.appendChild(d);")
        lines.append("document.body.appendChild(zone);")
    else:
        lines.append("document.body.appendChild(d);")
    lines.append("return true;")
    return "(() => {" + "\n".join(lines) + "})()"


def _inject_probe(port: int, target_id: str | None, spec: dict, probe_id: str) -> None:
    launcher._cdp_evaluate(port, _build_probe_js(spec, probe_id), target_id=target_id)


def _remove_probe(port: int, target_id: str | None, probe_id: str) -> None:
    launcher._cdp_evaluate(
        port,
        f"(() => {{ document.getElementById('{probe_id}')?.remove(); return true; }})()",
        target_id=target_id,
    )


def _get_clicks(port: int, target_id: str | None) -> int:
    result = launcher._cdp_evaluate(
        port,
        "typeof acceptStatus === 'function' ? acceptStatus().totalClicks : -1",
        target_id=target_id,
    )
    return int(result.get("result", {}).get("result", {}).get("value", -1))


def _get_recent(port: int, target_id: str | None) -> list[dict]:
    result = launcher._cdp_evaluate(
        port,
        "typeof acceptStatus === 'function' ? JSON.stringify(acceptStatus().recentClicks) : '[]'",
        target_id=target_id,
    )
    raw = result.get("result", {}).get("result", {}).get("value", "[]")
    return json.loads(raw)


def _get_injector_interval_seconds(port: int, target_id: str | None) -> float:
    result = launcher._cdp_evaluate(
        port,
        "typeof acceptStatus === 'function' ? acceptStatus().interval : 2000",
        target_id=target_id,
    )
    ms = result.get("result", {}).get("result", {}).get("value", 2000)
    try:
        value = float(ms)
    except (TypeError, ValueError):
        value = 2000.0
    if value <= 0:
        value = 2000.0
    return value / 1000.0


def _get_debug_snapshot(port: int, target_id: str | None) -> dict:
    result = launcher._cdp_evaluate(
        port,
        "typeof acceptDebugSnapshot === 'function' ? JSON.stringify(acceptDebugSnapshot()) : '{}'",
        target_id=target_id,
    )
    raw = result.get("result", {}).get("result", {}).get("value", "{}")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _clear_fingerprint_cooldowns(port: int, target_id: str | None) -> None:
    launcher._cdp_evaluate(
        port,
        """
(() => {
  const state = globalThis.__cursorAutoAccept?.state;
  if (!state) return false;
  state.fingerprintCooldowns = new Map();
  return true;
})()
""".strip(),
        target_id=target_id,
    )


def _save_png(port: int, target_id: str | None, out_path: Path) -> str | None:
    try:
        png = launcher._cdp_screenshot(port, target_id=target_id, timeout=20.0)
    except (ConnectionRefusedError, OSError, RuntimeError):
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(png)
    return str(out_path)


def _select_cases(suite: str) -> list[tuple[str, dict, bool, str | None]]:
    if suite == "full":
        return TEST_CASES
    return [TEST_CASES[i - 1] for i in MEANINGFUL_CASE_INDEXES]


def _run_synthetic(args: argparse.Namespace, port: int, target: str | None, out_dir: Path) -> int:
    selected = _select_cases(args.suite)
    total = len(selected)
    passed = 0
    failed = 0
    results: list[dict] = []

    screenshots_dir = out_dir / "screenshots"
    case_dir = out_dir / "cases"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    case_dir.mkdir(parents=True, exist_ok=True)

    injector_interval = _get_injector_interval_seconds(port, target)
    effective_wait = max(args.poll_interval or 0.0, injector_interval + 0.4)

    print(f"Running {total} synthetic case(s) on port {port}, target {target or 'auto'}", flush=True)
    print(f"Suite: {args.suite}", flush=True)
    print(f"Injector interval: {injector_interval:.2f}s; per-case wait: {effective_wait:.2f}s", flush=True)
    print(f"Artifacts: {out_dir}", flush=True)
    print("=" * 72, flush=True)

    for i, (name, spec, expect_click, expect_id) in enumerate(selected, 1):
        probe_id = f"__aa_stress_{i}"
        _clear_fingerprint_cooldowns(port, target)
        clicks_before = _get_clicks(port, target)
        before_debug = _get_debug_snapshot(port, target)
        before_png = _save_png(port, target, screenshots_dir / f"{i:02d}-before.png")

        _inject_probe(port, target, spec, probe_id)
        time.sleep(effective_wait)

        clicks_after = _get_clicks(port, target)
        delta = clicks_after - clicks_before
        clicked = delta > 0
        recent = _get_recent(port, target)
        last_id = recent[-1]["id"] if recent else None
        after_debug = _get_debug_snapshot(port, target)
        after_png = _save_png(port, target, screenshots_dir / f"{i:02d}-after.png")
        _remove_probe(port, target, probe_id)

        ok = clicked == expect_click
        if ok and expect_click and expect_id:
            ok = last_id == expect_id
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1

        results.append({
            "case": i,
            "name": name,
            "status": status,
            "expected_click": expect_click,
            "actual_click": clicked,
            "expected_id": expect_id,
            "actual_id": last_id if clicked else None,
            "delta": delta,
            "before_screenshot": before_png,
            "after_screenshot": after_png,
            "buttons_seen_before": len(before_debug.get("visibleButtons", [])),
            "buttons_seen_after": len(after_debug.get("visibleButtons", [])),
            "eligible_seen_after": len(after_debug.get("eligible", [])),
        })

        print(f"  [{i:2d}/{total}] {'✓' if ok else '✗'} {status:4s}  {name}", flush=True)
        if not ok:
            print(
                f"         expected click={expect_click} id={expect_id}, got click={clicked} id={last_id} delta={delta}",
                flush=True,
            )

        (case_dir / f"{i:02d}.json").write_text(
            json.dumps(
                {
                    "case": i,
                    "name": name,
                    "spec": spec,
                    "status": status,
                    "expected_click": expect_click,
                    "expected_id": expect_id,
                    "actual_click": clicked,
                    "actual_id": last_id if clicked else None,
                    "delta": delta,
                    "before_screenshot": before_png,
                    "after_screenshot": after_png,
                    "debug_before": before_debug,
                    "debug_after": after_debug,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    print("=" * 72, flush=True)
    print(f"Results: {passed}/{total} passed, {failed} failed", flush=True)
    (out_dir / "stress-test-results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Results saved to: {out_dir / 'stress-test-results.json'}", flush=True)
    print(f"Screenshots saved to: {screenshots_dir}", flush=True)
    print(f"Per-case debug JSON saved to: {case_dir}", flush=True)
    return 0 if failed == 0 else 1


def _run_snapshot(args: argparse.Namespace, port: int, target: str | None, out_dir: Path) -> int:
    snapshots_dir = out_dir / "snapshots"
    screenshots_dir = out_dir / "screenshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    duration = max(5.0, float(args.duration))
    interval = max(0.8, float(args.interval))
    deadline = time.time() + duration
    start_clicks = _get_clicks(port, target)
    previous_clicks = start_clicks
    tick = 0
    events: list[dict] = []

    print(f"Running real snapshot mode for {duration:.1f}s (interval {interval:.1f}s)", flush=True)
    print(f"Artifacts: {out_dir}", flush=True)
    print("=" * 72, flush=True)

    while time.time() < deadline:
        tick += 1
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        debug = _get_debug_snapshot(port, target)
        clicks = _get_clicks(port, target)
        delta = clicks - previous_clicks
        screenshot = _save_png(port, target, screenshots_dir / f"{tick:03d}-{stamp}.png")

        row = {
            "tick": tick,
            "ts": datetime.now(timezone.utc).isoformat(),
            "clicks": clicks,
            "delta": delta,
            "eligible_count": len(debug.get("eligible", [])),
            "candidate_count": len(debug.get("candidates", [])),
            "strategyVersion": debug.get("strategyVersion"),
            "screenshot": screenshot,
            "debug": debug,
        }
        (snapshots_dir / f"{tick:03d}.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
        if delta > 0 or row["eligible_count"] > 0:
            events.append({
                "tick": tick,
                "delta": delta,
                "eligible_count": row["eligible_count"],
                "screenshot": screenshot,
            })
        print(
            f"  [{tick:03d}] clicks={clicks} delta={delta} eligible={row['eligible_count']} candidates={row['candidate_count']}",
            flush=True,
        )
        previous_clicks = clicks
        time.sleep(interval)

    end_clicks = _get_clicks(port, target)
    summary = {
        "mode": "snapshot",
        "duration_seconds": duration,
        "interval_seconds": interval,
        "ticks": tick,
        "start_clicks": start_clicks,
        "end_clicks": end_clicks,
        "delta_clicks": end_clicks - start_clicks,
        "event_count": len(events),
        "events": events,
    }
    (out_dir / "snapshot-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("=" * 72, flush=True)
    print(f"Snapshot summary: clicks {start_clicks} -> {end_clicks} (delta {end_clicks - start_clicks})", flush=True)
    print(f"Summary saved to: {out_dir / 'snapshot-summary.json'}", flush=True)
    print(f"Snapshots saved to: {snapshots_dir}", flush=True)
    print(f"Screenshots saved to: {screenshots_dir}", flush=True)
    return 0


FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures" / "real-prompts"


def _load_fixtures(fixtures_dir: Path | None = None) -> list[dict]:
    """Load real-prompt fixture JSON files from the fixtures directory."""
    fdir = fixtures_dir or FIXTURES_DIR
    if not fdir.is_dir():
        return []
    fixtures = []
    for p in sorted(fdir.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            data["_source_file"] = str(p)
            fixtures.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return fixtures


def _run_replay(args: argparse.Namespace, port: int, target: str | None, out_dir: Path) -> int:
    """Replay sanitized real-prompt fixtures as probes and validate click behavior."""
    fixtures_dir = Path(args.fixtures_dir) if args.fixtures_dir else FIXTURES_DIR
    fixtures = _load_fixtures(fixtures_dir)
    if not fixtures:
        print(f"No fixtures found in {fixtures_dir}", file=sys.stderr)
        return 1

    total = len(fixtures)
    passed = 0
    failed = 0
    results: list[dict] = []

    screenshots_dir = out_dir / "screenshots"
    case_dir = out_dir / "cases"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    case_dir.mkdir(parents=True, exist_ok=True)

    injector_interval = _get_injector_interval_seconds(port, target)
    effective_wait = max(args.poll_interval or 0.0, injector_interval + 0.4)

    print(f"Replaying {total} real-prompt fixture(s) on port {port}, target {target or 'auto'}", flush=True)
    print(f"Fixtures dir: {fixtures_dir}", flush=True)
    print(f"Injector interval: {injector_interval:.2f}s; per-case wait: {effective_wait:.2f}s", flush=True)
    print(f"Artifacts: {out_dir}", flush=True)
    print("=" * 72, flush=True)

    for i, fixture in enumerate(fixtures, 1):
        name = fixture.get("name", f"fixture-{i}")
        spec = fixture.get("spec", {})
        expect_click = fixture.get("expect_click", True)
        expect_id = fixture.get("expect_id")
        expect_single = fixture.get("expect_single_click", False)
        probe_id = f"__aa_replay_{i}"

        _clear_fingerprint_cooldowns(port, target)
        clicks_before = _get_clicks(port, target)
        before_debug = _get_debug_snapshot(port, target)
        before_png = _save_png(port, target, screenshots_dir / f"{i:02d}-before.png")

        _inject_probe(port, target, spec, probe_id)
        time.sleep(effective_wait)

        clicks_after = _get_clicks(port, target)
        delta = clicks_after - clicks_before
        clicked = delta > 0
        recent = _get_recent(port, target)
        last_id = recent[-1]["id"] if recent else None
        after_debug = _get_debug_snapshot(port, target)
        after_png = _save_png(port, target, screenshots_dir / f"{i:02d}-after.png")

        if expect_single and delta > 1:
            time.sleep(effective_wait)
            clicks_recheck = _get_clicks(port, target)
            extra_delta = clicks_recheck - clicks_after
        else:
            extra_delta = 0

        last_command = None
        if recent:
            last_command = {
                "preview": recent[-1].get("commandPreview"),
                "lines": recent[-1].get("commandLines"),
            }

        _remove_probe(port, target, probe_id)

        ok = clicked == expect_click
        if ok and expect_click and expect_id:
            ok = last_id == expect_id
        single_ok = True
        if ok and expect_single and delta > 1:
            single_ok = False
            ok = False

        expect_command_preview = fixture.get("expect_command_preview")
        command_ok = True
        if ok and expect_command_preview and last_command:
            actual_preview = last_command.get("preview") or ""
            if expect_command_preview not in actual_preview:
                command_ok = False
                ok = False

        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1

        result_entry = {
            "case": i,
            "name": name,
            "status": status,
            "expected_click": expect_click,
            "actual_click": clicked,
            "expected_id": expect_id,
            "actual_id": last_id if clicked else None,
            "delta": delta,
            "single_click_ok": single_ok,
            "command_ok": command_ok,
            "last_command": last_command,
            "extra_delta": extra_delta,
            "source_file": fixture.get("_source_file", ""),
            "before_screenshot": before_png,
            "after_screenshot": after_png,
            "buttons_seen_before": len(before_debug.get("visibleButtons", [])),
            "buttons_seen_after": len(after_debug.get("visibleButtons", [])),
            "eligible_seen_after": len(after_debug.get("eligible", [])),
        }
        results.append(result_entry)

        print(f"  [{i:2d}/{total}] {'✓' if ok else '✗'} {status:4s}  {name}", flush=True)
        if not ok:
            detail = f"expected click={expect_click} id={expect_id}, got click={clicked} id={last_id} delta={delta}"
            if not single_ok:
                detail += f" (MULTI-CLICK: {delta} clicks, expected single)"
            if not command_ok:
                actual_preview = (last_command or {}).get("preview") or ""
                detail += f" (COMMAND: expected '{expect_command_preview}' in '{actual_preview}')"
            print(f"         {detail}", flush=True)

        (case_dir / f"{i:02d}.json").write_text(
            json.dumps(
                {
                    **result_entry,
                    "spec": spec,
                    "debug_before": before_debug,
                    "debug_after": after_debug,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    print("=" * 72, flush=True)
    print(f"Results: {passed}/{total} passed, {failed} failed", flush=True)
    (out_dir / "replay-results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Results saved to: {out_dir / 'replay-results.json'}", flush=True)
    return 0 if failed == 0 else 1


def _resolve_target(port: int, target: str | None) -> str | None:
    if target:
        return target
    state = launcher._load_state()
    sessions_dict = state.get("sessions", {})
    for _key, sess in sessions_dict.items():
        if isinstance(sess, dict) and sess.get("cdp_port") == port:
            return sess.get("cdp_target_id")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-approve harness")
    parser.add_argument("--mode", choices=["snapshot", "synthetic", "replay"], default="snapshot")
    parser.add_argument("--suite", choices=["meaningful", "full"], default="meaningful")
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--target", help="CDP target ID")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=None,
        help="Synthetic/replay mode: probe settle wait in seconds (default: injector interval + margin)",
    )
    parser.add_argument("--duration", type=float, default=SNAPSHOT_DURATION, help="Snapshot mode duration in seconds")
    parser.add_argument("--interval", type=float, default=SNAPSHOT_INTERVAL, help="Snapshot mode sample interval in seconds")
    parser.add_argument("--outdir", help="Output run directory (default: logs/<run-id>-<mode>)")
    parser.add_argument("--fixtures-dir", help="Replay mode: path to fixtures directory")
    args = parser.parse_args()

    port = args.port
    target = _resolve_target(port, args.target)

    if args.outdir:
        out_dir = Path(args.outdir).expanduser().resolve()
    else:
        out_dir = Path(__file__).parent.parent / "logs" / _run_id(f"harness-{args.mode}")

    if args.mode == "snapshot":
        return _run_snapshot(args, port, target, out_dir)
    if args.mode == "replay":
        return _run_replay(args, port, target, out_dir)
    return _run_synthetic(args, port, target, out_dir)


if __name__ == "__main__":
    raise SystemExit(main())
