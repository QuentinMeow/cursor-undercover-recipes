#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
BASE_DIR = SCRIPT_PATH.parent
STATE_PATH = BASE_DIR / "state.json"
SESSION_PATH = BASE_DIR / "session.json"
WATCHER_PID_PATH = BASE_DIR / "watcher.pid"
LOG_PATH = BASE_DIR / "events.log"
BANNER_SCRIPT_PATH = BASE_DIR / "open_notification_banner.applescript"
ALERT_PRIMARY_SCRIPT_PATH = BASE_DIR / "click_notification_primary_button.applescript"
DEDICATED_PROFILE_DIR = BASE_DIR / "dedicated-profile"
CURSOR_APP_PATH = Path("/Applications/Cursor.app")
CURSOR_EXECUTABLE = CURSOR_APP_PATH / "Contents" / "MacOS" / "Cursor"
CURSOR_APP_NAME = "Cursor"

DEFAULT_STATE = {
    "hook_enabled": True,
    "watch_interval_seconds": 1.0,
    "session_ttl_seconds": 14400.0,
    "idle_timeout_seconds": 1800.0,
    "launch_timeout_seconds": 30.0,
    "approval_button_labels": [
        "Run",
        "Run command",
        "Continue",
        "Allow",
        "Approve",
        "Trust",
        "Trust Workspace & Continue",
        "Open",
        "Install",
    ],
    "prompt_text_keywords": [
        "agent",
        "allow",
        "approve",
        "command",
        "continue",
        "permission",
        "run",
        "shell",
        "terminal",
        "tool",
        "trust",
        "workspace",
    ],
}

DEFAULT_SESSION = {
    "active": False,
    "reason": "inactive",
    "launch_mode": None,
    "workspace_path": None,
    "target_pid": None,
    "target_window": {},
    "watcher_pid": None,
    "ttl_seconds": None,
    "idle_timeout_seconds": None,
    "created_at": None,
    "expires_at": None,
    "last_activity_at": None,
    "last_activity_reason": None,
}

SHOULD_STOP = False


def ensure_base_dir() -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)


def log_event(message: str) -> None:
    ensure_base_dir()
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {message}\n")


def load_json_file(path: Path, defaults: dict[str, Any]) -> dict[str, Any]:
    ensure_base_dir()
    if not path.exists():
        save_json_file(path, defaults)
        return dict(defaults)

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        payload = {}

    merged = dict(defaults)
    merged.update(payload)
    return merged


def save_json_file(path: Path, payload: dict[str, Any]) -> None:
    ensure_base_dir()
    merged = dict(payload)
    path.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_state() -> dict[str, Any]:
    return load_json_file(STATE_PATH, DEFAULT_STATE)


def save_state(state: dict[str, Any]) -> None:
    merged = dict(DEFAULT_STATE)
    merged.update(state)
    save_json_file(STATE_PATH, merged)


def update_state(**updates: Any) -> dict[str, Any]:
    state = load_state()
    state.update(updates)
    save_state(state)
    return state


def load_session() -> dict[str, Any]:
    return load_json_file(SESSION_PATH, DEFAULT_SESSION)


def save_session(session: dict[str, Any]) -> None:
    merged = dict(DEFAULT_SESSION)
    merged.update(session)
    save_json_file(SESSION_PATH, merged)


def now_ts() -> float:
    return time.time()


def pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def read_pid_file(path: Path) -> "int | None":
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def write_pid_file(path: Path, pid: int) -> None:
    ensure_base_dir()
    path.write_text(f"{pid}\n", encoding="utf-8")


def remove_pid_file(path: Path) -> None:
    if path.exists():
        path.unlink()


def normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def unique_non_empty(values: "list[str]") -> "list[str]":
    seen: "set[str]" = set()
    output: "list[str]" = []
    for value in values:
        stripped = value.strip()
        if not stripped:
            continue
        if stripped in seen:
            continue
        seen.add(stripped)
        output.append(stripped)
    return output


def get_state_list(state: dict[str, Any], key: str) -> "list[str]":
    raw = state.get(key, DEFAULT_STATE[key])
    if not isinstance(raw, list):
        return list(DEFAULT_STATE[key])
    return [str(item) for item in raw if str(item).strip()]


def current_cursor_main_pids() -> "list[int]":
    try:
        result = subprocess.run(
            ["ps", "-ax", "-o", "pid=,args="],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    if result.returncode != 0:
        return []

    matches: "list[int]" = []
    executable = str(CURSOR_EXECUTABLE)
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        pid_text, args_text = parts
        if not pid_text.isdigit():
            continue
        if args_text == executable or args_text.startswith(executable + " "):
            matches.append(int(pid_text))
    return sorted(matches)


def run_osascript(source: str, timeout: float = 10.0) -> str:
    result = subprocess.run(
        ["osascript"],
        input=source,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip() or "osascript failed"
        raise RuntimeError(error)
    return result.stdout.strip()


def applescript_string(value: str) -> str:
    return json.dumps(value)


def frontmost_cursor_pid() -> "int | None":
    script = """
tell application "System Events"
    repeat with proc in application processes whose name is "Cursor"
        try
            if frontmost of proc then
                return (unix id of proc as text)
            end if
        end try
    end repeat
    return ""
end tell
"""
    output = run_osascript(script)
    if not output.isdigit():
        return None
    return int(output)


def list_windows_for_pid(pid: int) -> "list[dict[str, Any]]":
    script = f"""
on joinLines(itemsList)
    if (count of itemsList) is 0 then return ""
    set oldTID to AppleScript's text item delimiters
    set AppleScript's text item delimiters to linefeed
    set joinedText to itemsList as text
    set AppleScript's text item delimiters to oldTID
    return joinedText
end joinLines

tell application "System Events"
    set targetProc to first application process whose unix id is {pid}
    set outputLines to {{}}
    set idx to 0
    repeat with win in windows of targetProc
        set idx to idx + 1

        try
            set winName to (name of win as text)
        on error
            set winName to ""
        end try

        try
            set winPos to position of win
        on error
            set winPos to {{0, 0}}
        end try

        try
            set winSize to size of win
        on error
            set winSize to {{0, 0}}
        end try

        try
            set winRole to (role of win as text)
        on error
            set winRole to ""
        end try

        try
            set winSubrole to (subrole of win as text)
        on error
            set winSubrole to ""
        end try

        set lineText to (idx as text) & tab & winName & tab & (item 1 of winPos as text) & tab & (item 2 of winPos as text) & tab & (item 1 of winSize as text) & tab & (item 2 of winSize as text) & tab & winRole & tab & winSubrole
        set end of outputLines to lineText
    end repeat
    return my joinLines(outputLines)
end tell
"""
    output = run_osascript(script)
    windows: "list[dict[str, Any]]" = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 8:
            continue
        try:
            windows.append(
                {
                    "index": int(parts[0]),
                    "title": parts[1],
                    "position": [int(parts[2]), int(parts[3])],
                    "size": [int(parts[4]), int(parts[5])],
                    "role": parts[6],
                    "subrole": parts[7],
                }
            )
        except ValueError:
            continue
    return windows


def wait_for_window(pid: int, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        try:
            windows = list_windows_for_pid(pid)
            if windows:
                return windows[0]
        except RuntimeError as exc:
            last_error = str(exc)
        time.sleep(0.5)
    if last_error:
        raise RuntimeError(last_error)
    raise RuntimeError(f"Timed out waiting for a Cursor window for pid {pid}")


def window_matches_fingerprint(window: dict[str, Any], fingerprint: dict[str, Any]) -> bool:
    if not fingerprint:
        return False
    if fingerprint.get("title") and window.get("title") == fingerprint.get("title"):
        return True
    if (
        window.get("position") == fingerprint.get("position")
        and window.get("size") == fingerprint.get("size")
        and window.get("role") == fingerprint.get("role")
    ):
        return True
    return False


def resolve_target_window(pid: int, fingerprint: dict[str, Any]) -> "dict[str, Any] | None":
    windows = list_windows_for_pid(pid)
    if not windows:
        return None
    if len(windows) == 1:
        return windows[0]
    for window in windows:
        if window_matches_fingerprint(window, fingerprint):
            return window
    index = fingerprint.get("index")
    if isinstance(index, int):
        for window in windows:
            if window.get("index") == index:
                return window
    return windows[0]


def scan_window_elements(pid: int, window_index: int) -> dict[str, Any]:
    script = f"""
on joinLines(itemsList)
    if (count of itemsList) is 0 then return ""
    set oldTID to AppleScript's text item delimiters
    set AppleScript's text item delimiters to linefeed
    set joinedText to itemsList as text
    set AppleScript's text item delimiters to oldTID
    return joinedText
end joinLines

on preferredText(elem)
    try
        set elemText to (name of elem as text)
        if elemText is not "missing value" and elemText is not "" then return elemText
    end try
    try
        set elemText to (description of elem as text)
        if elemText is not "missing value" and elemText is not "" then return elemText
    end try
    try
        set elemText to (value of elem as text)
        if elemText is not "missing value" and elemText is not "" then return elemText
    end try
    return ""
end preferredText

tell application "System Events"
    set targetProc to first application process whose unix id is {pid}
    set targetWindow to window {window_index} of targetProc
    set outputLines to {{}}

    repeat with elem in entire contents of targetWindow
        try
            set elemRole to (role of elem as text)
        on error
            set elemRole to ""
        end try

        try
            set elemSubrole to (subrole of elem as text)
        on error
            set elemSubrole to ""
        end try

        if elemRole is "AXButton" then
            set buttonText to my preferredText(elem)
            if buttonText is not "" then
                set end of outputLines to "BUTTON" & tab & buttonText
            end if
        else if elemRole is "AXStaticText" then
            set textValue to my preferredText(elem)
            if textValue is not "" then
                set end of outputLines to "TEXT" & tab & textValue
            end if
        end if

        if elemRole is "AXDialog" or elemRole is "AXSheet" or elemSubrole contains "Dialog" or elemSubrole contains "Sheet" then
            set end of outputLines to "CONTAINER" & tab & elemRole & tab & elemSubrole
        end if
    end repeat
    return my joinLines(outputLines)
end tell
"""
    output = run_osascript(script, timeout=15.0)
    buttons: "list[str]" = []
    texts: "list[str]" = []
    containers: "list[str]" = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        kind = parts[0]
        if kind == "BUTTON" and len(parts) >= 2:
            buttons.append(parts[1])
        elif kind == "TEXT" and len(parts) >= 2:
            texts.append(parts[1])
        elif kind == "CONTAINER" and len(parts) >= 2:
            containers.append("\t".join(parts[1:]))
    return {
        "buttons": unique_non_empty(buttons),
        "texts": unique_non_empty(texts),
        "containers": unique_non_empty(containers),
    }


def choose_approval_button(snapshot: dict[str, Any], state: dict[str, Any]) -> "str | None":
    buttons = snapshot.get("buttons", [])
    if not buttons:
        return None

    text_blob = " ".join(text.lower() for text in snapshot.get("texts", []))
    prompt_keywords = get_state_list(state, "prompt_text_keywords")
    has_prompt_keyword = any(keyword.lower() in text_blob for keyword in prompt_keywords)
    has_modal_container = bool(snapshot.get("containers"))

    if not has_modal_container and not has_prompt_keyword:
        return None

    buttons_by_normalized = {normalize_text(button): button for button in buttons}
    for preferred in get_state_list(state, "approval_button_labels"):
        normalized = normalize_text(preferred)
        if normalized in buttons_by_normalized:
            return buttons_by_normalized[normalized]

    for preferred in get_state_list(state, "approval_button_labels"):
        normalized = normalize_text(preferred)
        for button in buttons:
            if normalize_text(button).startswith(normalized + " "):
                return button
    return None


def click_button(pid: int, window_index: int, button_label: str) -> bool:
    script = f"""
on preferredText(elem)
    try
        set elemText to (name of elem as text)
        if elemText is not "missing value" and elemText is not "" then return elemText
    end try
    try
        set elemText to (description of elem as text)
        if elemText is not "missing value" and elemText is not "" then return elemText
    end try
    try
        set elemText to (value of elem as text)
        if elemText is not "missing value" and elemText is not "" then return elemText
    end try
    return ""
end preferredText

tell application "System Events"
    set targetProc to first application process whose unix id is {pid}
    set targetWindow to window {window_index} of targetProc
    repeat with elem in entire contents of targetWindow
        try
            if (role of elem as text) is "AXButton" then
                set elemText to my preferredText(elem)
                if elemText is {applescript_string(button_label)} then
                    perform action "AXPress" of elem
                    return "clicked"
                end if
            end if
        end try
    end repeat
    return "not_found"
end tell
"""
    return run_osascript(script) == "clicked"


def run_applescript_file(path: Path) -> int:
    result = subprocess.run(["osascript", str(path)], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
    else:
        sys.stdout.write(result.stdout)
    return result.returncode


def path_matches_workspace(cwd: str, workspace_path: "str | None") -> bool:
    if not workspace_path:
        return True
    if not cwd:
        return False
    cwd_path = Path(cwd).expanduser()
    workspace = Path(workspace_path).expanduser()
    try:
        cwd_path = cwd_path.resolve()
    except FileNotFoundError:
        cwd_path = cwd_path.absolute()
    try:
        workspace = workspace.resolve()
    except FileNotFoundError:
        workspace = workspace.absolute()
    if cwd_path == workspace:
        return True
    try:
        cwd_path.relative_to(workspace)
        return True
    except ValueError:
        return False


def session_block_reason(session: dict[str, Any], state: dict[str, Any]) -> "str | None":
    now = now_ts()

    if not state.get("hook_enabled", True):
        return "hook disabled"
    if not session.get("active", False):
        return "session inactive"

    expires_at = session.get("expires_at")
    if isinstance(expires_at, (int, float)) and now >= float(expires_at):
        return "session expired"

    idle_timeout = session.get("idle_timeout_seconds", state.get("idle_timeout_seconds"))
    last_activity_at = session.get("last_activity_at") or session.get("created_at")
    if isinstance(idle_timeout, (int, float)) and idle_timeout > 0 and isinstance(last_activity_at, (int, float)):
        if now - float(last_activity_at) >= float(idle_timeout):
            return "session idle timeout reached"

    target_pid = session.get("target_pid")
    if isinstance(target_pid, int) and target_pid and not pid_is_alive(target_pid):
        return "target Cursor process exited"
    return None


def touch_session(reason: str) -> dict[str, Any]:
    session = load_session()
    if not session.get("active"):
        return session
    session["last_activity_at"] = now_ts()
    session["last_activity_reason"] = reason
    save_session(session)
    return session


def stop_watcher_process(exclude_current: bool = False) -> None:
    watcher_pid = read_pid_file(WATCHER_PID_PATH)
    if not watcher_pid:
        return
    if exclude_current and watcher_pid == os.getpid():
        return
    if not pid_is_alive(watcher_pid):
        remove_pid_file(WATCHER_PID_PATH)
        return
    os.kill(watcher_pid, signal.SIGTERM)
    for _ in range(20):
        if not pid_is_alive(watcher_pid):
            break
        time.sleep(0.1)
    if not pid_is_alive(watcher_pid):
        remove_pid_file(WATCHER_PID_PATH)


def mark_session_inactive(reason: str, *, stop_watcher: bool = True) -> dict[str, Any]:
    session = load_session()
    if stop_watcher:
        stop_watcher_process(exclude_current=True)

    inactive = dict(DEFAULT_SESSION)
    inactive.update(
        {
            "active": False,
            "reason": reason,
            "launch_mode": session.get("launch_mode"),
            "workspace_path": session.get("workspace_path"),
            "target_pid": session.get("target_pid"),
            "target_window": session.get("target_window", {}),
            "ttl_seconds": session.get("ttl_seconds"),
            "idle_timeout_seconds": session.get("idle_timeout_seconds"),
            "created_at": session.get("created_at"),
            "last_activity_at": now_ts(),
            "last_activity_reason": reason,
            "watcher_pid": None,
        }
    )
    save_session(inactive)
    if read_pid_file(WATCHER_PID_PATH) == os.getpid():
        remove_pid_file(WATCHER_PID_PATH)
    log_event(f"session inactive: {reason}")
    return inactive


def ensure_watcher_running() -> None:
    existing_pid = read_pid_file(WATCHER_PID_PATH)
    if existing_pid and pid_is_alive(existing_pid):
        log_event(f"watcher already running with pid {existing_pid}")
        return

    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "watch"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    time.sleep(0.25)
    log_event(f"watcher spawn requested with pid {process.pid}")


def set_stop_flag(_signum: int, _frame: Any) -> None:
    global SHOULD_STOP
    SHOULD_STOP = True


def wait_for_new_cursor_pid(existing_pids: "set[int]", timeout_seconds: float) -> int:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        new_pids = [pid for pid in current_cursor_main_pids() if pid not in existing_pids]
        if new_pids:
            return max(new_pids)
        time.sleep(0.5)
    raise RuntimeError("Timed out waiting for a dedicated Cursor instance")


def launch_dedicated_cursor(workspace_path: Path, timeout_seconds: float) -> int:
    ensure_base_dir()
    DEDICATED_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    existing_pids = set(current_cursor_main_pids())
    command = [
        "open",
        "-na",
        str(CURSOR_APP_PATH),
        "--args",
        "--user-data-dir",
        str(DEDICATED_PROFILE_DIR),
        str(workspace_path),
    ]
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    log_event(f"launch requested for dedicated Cursor instance at {workspace_path}")
    try:
        return wait_for_new_cursor_pid(existing_pids, timeout_seconds)
    except RuntimeError:
        subprocess.Popen(
            [str(CURSOR_EXECUTABLE), "--user-data-dir", str(DEDICATED_PROFILE_DIR), str(workspace_path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        log_event("falling back to direct Cursor executable launch")
        return wait_for_new_cursor_pid(existing_pids, timeout_seconds)


def build_session_payload(
    target_pid: int,
    target_window: dict[str, Any],
    workspace_path: Path,
    launch_mode: str,
    ttl_seconds: float,
    idle_timeout_seconds: float,
) -> dict[str, Any]:
    created_at = now_ts()
    return {
        "active": True,
        "reason": "active",
        "launch_mode": launch_mode,
        "workspace_path": str(workspace_path),
        "target_pid": target_pid,
        "target_window": target_window,
        "watcher_pid": None,
        "ttl_seconds": ttl_seconds,
        "idle_timeout_seconds": idle_timeout_seconds,
        "created_at": created_at,
        "expires_at": created_at + ttl_seconds,
        "last_activity_at": created_at,
        "last_activity_reason": "activate",
    }


def status_payload() -> dict[str, Any]:
    state = load_state()
    session = load_session()
    watcher_pid = read_pid_file(WATCHER_PID_PATH)
    watcher_running = bool(watcher_pid and pid_is_alive(watcher_pid))
    reason = session_block_reason(session, state)
    frontmost_pid: "int | None"
    frontmost_error: "str | None" = None
    try:
        frontmost_pid = frontmost_cursor_pid()
    except RuntimeError as exc:
        frontmost_pid = None
        frontmost_error = str(exc)
    payload = {
        "hook_enabled": bool(state.get("hook_enabled", True)),
        "frontmost_cursor_pid": frontmost_pid,
        "available_cursor_pids": current_cursor_main_pids(),
        "watcher_pid": watcher_pid if watcher_running else None,
        "watcher_running": watcher_running,
        "session_active": bool(session.get("active")) and reason is None,
        "session_reason": reason or session.get("reason"),
        "session": session,
        "log_file": str(LOG_PATH),
        "session_file": str(SESSION_PATH),
        "dedicated_profile_dir": str(DEDICATED_PROFILE_DIR),
    }
    if frontmost_error is not None:
        payload["frontmost_cursor_error"] = frontmost_error
    return payload


def shell_hook_payload() -> dict[str, Any]:
    try:
        return json.load(sys.stdin)
    except json.JSONDecodeError:
        return {}


def hook_shell() -> int:
    payload = shell_hook_payload()
    command = payload.get("command", "")
    cwd = payload.get("cwd", "")
    state = load_state()
    session = load_session()
    reason = session_block_reason(session, state)

    if reason is None and not path_matches_workspace(cwd, session.get("workspace_path")):
        reason = f"cwd outside active workspace: {cwd!r}"

    if reason is None:
        touch_session("hook allow")
        log_event(f"hook allow command={command!r} cwd={cwd!r}")
        response = {"continue": True, "permission": "allow"}
    else:
        if session.get("active") and reason != "hook disabled":
            mark_session_inactive(reason)
        log_event(f"hook ask command={command!r} cwd={cwd!r} reason={reason!r}")
        response = {
            "continue": True,
            "permission": "ask",
            "user_message": "Cursor auto approval is inactive for this command.",
            "agent_message": f"Shell auto approval is inactive: {reason}. Request manual confirmation.",
        }

    print(json.dumps(response))
    return 0


def run_watch_loop() -> int:
    ensure_base_dir()
    signal.signal(signal.SIGTERM, set_stop_flag)
    signal.signal(signal.SIGINT, set_stop_flag)
    write_pid_file(WATCHER_PID_PATH, os.getpid())
    log_event("watch loop started")

    session = load_session()
    if session.get("active"):
        session["watcher_pid"] = os.getpid()
        save_session(session)

    try:
        while not SHOULD_STOP:
            state = load_state()
            session = load_session()
            reason = session_block_reason(session, state)
            if reason is not None:
                if session.get("active"):
                    mark_session_inactive(reason, stop_watcher=False)
                break

            target_pid = int(session["target_pid"])
            target_window = resolve_target_window(target_pid, session.get("target_window", {}))
            if target_window is None:
                mark_session_inactive("target Cursor window disappeared", stop_watcher=False)
                break

            snapshot = scan_window_elements(target_pid, int(target_window["index"]))
            button_label = choose_approval_button(snapshot, state)
            if button_label and click_button(target_pid, int(target_window["index"]), button_label):
                touch_session(f"clicked {button_label}")
                log_event(
                    f"clicked button {button_label!r} in pid {target_pid} window {target_window.get('title', '')!r}"
                )

            interval = float(state.get("watch_interval_seconds", DEFAULT_STATE["watch_interval_seconds"]))
            time.sleep(max(0.2, interval))
    finally:
        pid = read_pid_file(WATCHER_PID_PATH)
        if pid == os.getpid():
            remove_pid_file(WATCHER_PID_PATH)
        session = load_session()
        if session.get("watcher_pid") == os.getpid():
            session["watcher_pid"] = None
            save_session(session)
        log_event("watch loop stopped")

    return 0


def command_status(_args: argparse.Namespace) -> int:
    print(json.dumps(status_payload(), indent=2, sort_keys=True))
    return 0


def command_activate(args: argparse.Namespace) -> int:
    state = load_state()
    workspace_path = Path(args.workspace).expanduser() if args.workspace else Path.cwd()
    workspace_path = workspace_path.resolve()
    ttl_seconds = float(args.ttl_seconds or state.get("session_ttl_seconds", DEFAULT_STATE["session_ttl_seconds"]))
    idle_timeout_seconds = float(
        args.idle_timeout_seconds or state.get("idle_timeout_seconds", DEFAULT_STATE["idle_timeout_seconds"])
    )
    launch_timeout_seconds = float(state.get("launch_timeout_seconds", DEFAULT_STATE["launch_timeout_seconds"]))

    if args.launch_dedicated:
        target_pid = launch_dedicated_cursor(workspace_path, launch_timeout_seconds)
        launch_mode = "launched-dedicated"
    elif args.pid is not None:
        target_pid = args.pid
        launch_mode = "pid"
    else:
        target_pid = frontmost_cursor_pid()
        if target_pid is None:
            print(
                "No frontmost Cursor instance found. Focus the Cursor window you want to own, or use --launch-dedicated.",
                file=sys.stderr,
            )
            return 1
        launch_mode = "frontmost"

    if not pid_is_alive(target_pid):
        print(f"Cursor pid {target_pid} is not running", file=sys.stderr)
        return 1

    existing_session = load_session()
    if existing_session.get("active"):
        mark_session_inactive("replaced by new session")

    target_window = wait_for_window(target_pid, launch_timeout_seconds)
    save_session(
        build_session_payload(
            target_pid=target_pid,
            target_window=target_window,
            workspace_path=workspace_path,
            launch_mode=launch_mode,
            ttl_seconds=ttl_seconds,
            idle_timeout_seconds=idle_timeout_seconds,
        )
    )
    update_state(hook_enabled=True)
    ensure_watcher_running()
    log_event(f"session activated for pid {target_pid} using {launch_mode}")
    print(json.dumps(status_payload(), indent=2, sort_keys=True))
    return 0


def command_deactivate(_args: argparse.Namespace) -> int:
    mark_session_inactive("manual stop")
    print(json.dumps(status_payload(), indent=2, sort_keys=True))
    return 0


def command_hook_on(_args: argparse.Namespace) -> int:
    update_state(hook_enabled=True)
    log_event("hook enabled")
    print("hook enabled")
    return 0


def command_hook_off(_args: argparse.Namespace) -> int:
    update_state(hook_enabled=False)
    mark_session_inactive("hook disabled by user")
    log_event("hook disabled")
    print("hook disabled")
    return 0


def command_press_once(_args: argparse.Namespace) -> int:
    print("Disabled for safety. Use `activate` to bind a window-scoped watcher instead.", file=sys.stderr)
    return 1


def command_notification_banner_open(_args: argparse.Namespace) -> int:
    log_event("notification banner AXPress requested")
    return run_applescript_file(BANNER_SCRIPT_PATH)


def command_notification_alert_primary(_args: argparse.Namespace) -> int:
    log_event("notification alert primary button requested")
    return run_applescript_file(ALERT_PRIMARY_SCRIPT_PATH)


def add_activate_parser(subparsers: Any, name: str) -> None:
    parser = subparsers.add_parser(name)
    parser.add_argument("--workspace", default=str(Path.cwd()))
    parser.add_argument("--ttl-seconds", type=float)
    parser.add_argument("--idle-timeout-seconds", type=float)
    target_group = parser.add_mutually_exclusive_group()
    target_group.add_argument("--launch-dedicated", action="store_true")
    target_group.add_argument("--pid", type=int)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cursor auto approval controller")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status")
    subparsers.add_parser("watch")
    subparsers.add_parser("hook-shell")
    subparsers.add_parser("hook-on")
    subparsers.add_parser("hook-off")
    add_activate_parser(subparsers, "activate")
    add_activate_parser(subparsers, "start")
    subparsers.add_parser("deactivate")
    subparsers.add_parser("stop")
    subparsers.add_parser("press-once")
    subparsers.add_parser("notification-banner-open")
    subparsers.add_parser("notification-alert-primary")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    commands = {
        "status": command_status,
        "watch": lambda _args: run_watch_loop(),
        "hook-shell": lambda _args: hook_shell(),
        "hook-on": command_hook_on,
        "hook-off": command_hook_off,
        "activate": command_activate,
        "start": command_activate,
        "deactivate": command_deactivate,
        "stop": command_deactivate,
        "press-once": command_press_once,
        "notification-banner-open": command_notification_banner_open,
        "notification-alert-primary": command_notification_alert_primary,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
