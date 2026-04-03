#!/usr/bin/env python3
"""Stress test for the auto-approve injector.

Injects 50 synthetic approval prompts via CDP and verifies that the
injector clicks the right ones and ignores the wrong ones.

Categories:
  1-20:  Compound approval surfaces (approval + dismiss/companion combos)
  21-30: Temp-file-style single-action modals
  31-40: False-positive guards (should NOT be clicked)
  41-50: Edge cases (keyboard hints, long labels, excluded zones, etc.)

Usage:
  python3 stress_test.py [--port 9222] [--target TARGET_ID]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Reuse launcher's CDP helpers
LAUNCHER = Path(__file__).parent / "launcher.py"
sys.path.insert(0, str(LAUNCHER.parent))

import launcher  # noqa: E402

POLL_INTERVAL = 3.0

def _btn(var: str, text: str, **kwargs: object) -> dict:
    return {"var": var, "text": text, **kwargs}

# Each test case: (name, spec_dict, expected_click, expected_id_if_clicked)
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
]


def _build_probe_js(spec: dict, probe_id: str) -> str:
    """Build JS that creates a probe via createElement (innerHTML unreliable for role attrs)."""
    root_role = spec.get("role", "dialog")
    root_modal = spec.get("modal", True)
    root_style = spec.get("style", "position:fixed;z-index:2147483647;top:10px;right:10px;background:#333;padding:8px;display:flex;gap:4px")
    buttons = spec.get("buttons", [])
    excluded_zone = spec.get("excluded_zone")
    root_visible = spec.get("root_visible", True)

    lines = [f"const old = document.getElementById('{probe_id}');",
             "if (old) old.remove();"]

    if excluded_zone:
        lines.append(f"const zone = document.createElement('div');")
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
        if role:
            lines.append(f"b_{btn['var']}.setAttribute('role', '{role}');")
        if disabled:
            lines.append(f"b_{btn['var']}.disabled = true;")
        if style:
            lines.append(f"b_{btn['var']}.style.cssText = '{style}';")
        lines.append(f"d.appendChild(b_{btn['var']});")

    if excluded_zone:
        lines.append("zone.appendChild(d);")
        lines.append("document.body.appendChild(zone);")
    else:
        lines.append("document.body.appendChild(d);")
    lines.append("return true;")
    return "(() => {" + "\n".join(lines) + "})()"


def _inject_probe(port: int, target_id: str | None, spec: dict, probe_id: str) -> None:
    """Inject a synthetic approval prompt into the page."""
    js = _build_probe_js(spec, probe_id)
    launcher._cdp_evaluate(port, js, target_id=target_id)


def _remove_probe(port: int, target_id: str | None, probe_id: str) -> None:
    js = f"(() => {{ document.getElementById('{probe_id}')?.remove(); return true; }})()"
    launcher._cdp_evaluate(port, js, target_id=target_id)


def _get_clicks(port: int, target_id: str | None) -> int:
    result = launcher._cdp_evaluate(
        port, "typeof acceptStatus === 'function' ? acceptStatus().totalClicks : -1",
        target_id=target_id)
    return result.get("result", {}).get("result", {}).get("value", -1)


def _get_recent(port: int, target_id: str | None) -> list[dict]:
    result = launcher._cdp_evaluate(
        port,
        "typeof acceptStatus === 'function' ? JSON.stringify(acceptStatus().recentClicks) : '[]'",
        target_id=target_id)
    raw = result.get("result", {}).get("result", {}).get("value", "[]")
    return json.loads(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description="Stress test auto-approve injector")
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--target", help="CDP target ID")
    args = parser.parse_args()

    port = args.port
    target = args.target

    if not target:
        state = launcher._load_state()
        sessions_dict = state.get("sessions", {})
        for _key, sess in sessions_dict.items():
            if isinstance(sess, dict) and sess.get("cdp_port") == port:
                target = sess.get("cdp_target_id")
                break

    total = len(TEST_CASES)
    passed = 0
    failed = 0
    results: list[dict] = []

    print(f"Running {total} stress test cases on port {port}, target {target or 'auto'}")
    print("=" * 72)

    for i, (name, spec, expect_click, expect_id) in enumerate(TEST_CASES, 1):
        probe_id = f"__aa_stress_{i}"
        clicks_before = _get_clicks(port, target)

        _inject_probe(port, target, spec, probe_id)
        time.sleep(POLL_INTERVAL)

        clicks_after = _get_clicks(port, target)
        delta = clicks_after - clicks_before
        clicked = delta > 0

        recent = _get_recent(port, target)
        last_id = recent[-1]["id"] if recent else None

        _remove_probe(port, target, probe_id)

        ok = clicked == expect_click
        if ok and expect_click and expect_id:
            ok = last_id == expect_id

        status = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        else:
            passed += 1

        results.append({
            "case": i, "name": name, "status": status,
            "expected_click": expect_click, "actual_click": clicked,
            "expected_id": expect_id, "actual_id": last_id if clicked else None,
            "delta": delta,
        })

        marker = "✓" if ok else "✗"
        print(f"  [{i:2d}/{total}] {marker} {status:4s}  {name}")
        if not ok:
            print(f"         expected click={expect_click} id={expect_id}, got click={clicked} id={last_id} delta={delta}")

    print("=" * 72)
    print(f"Results: {passed}/{total} passed, {failed} failed")

    # Save results
    out_path = Path(__file__).parent.parent / "logs" / "stress-test-results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Results saved to: {out_path}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    main()
