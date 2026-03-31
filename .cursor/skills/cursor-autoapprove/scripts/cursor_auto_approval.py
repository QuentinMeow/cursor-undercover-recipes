#!/usr/bin/env python3

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import json
import os
import signal
import subprocess
import sys
import time
from ctypes import POINTER, byref, c_int32, c_void_p, c_uint64
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Native macOS Accessibility API via ctypes
# Chromium/Electron apps only expose their full AX tree when
# AXEnhancedUserInterface is set to true on the application element.
# The AppleScript `entire contents of` approach is too slow for the
# resulting large tree, so we use the C API directly.
# ---------------------------------------------------------------------------

_CF = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
_AX = ctypes.cdll.LoadLibrary(
    "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
)

_CFTypeRef = c_void_p
_CFStringRef = c_void_p
_CFArrayRef = c_void_p
_CFIndex = ctypes.c_long
_AXUIElementRef = c_void_p
_AXError = c_int32

_kAXErrorSuccess = 0
_kCFStringEncodingUTF8 = 0x08000100

_CF.CFRelease.argtypes = [_CFTypeRef]
_CF.CFRelease.restype = None
_CF.CFStringCreateWithCString.argtypes = [c_void_p, ctypes.c_char_p, ctypes.c_uint32]
_CF.CFStringCreateWithCString.restype = _CFStringRef
_CF.CFStringGetLength.argtypes = [_CFStringRef]
_CF.CFStringGetLength.restype = _CFIndex
_CF.CFStringGetCString.argtypes = [_CFStringRef, ctypes.c_char_p, _CFIndex, ctypes.c_uint32]
_CF.CFStringGetCString.restype = ctypes.c_bool
_CF.CFArrayGetCount.argtypes = [_CFArrayRef]
_CF.CFArrayGetCount.restype = _CFIndex
_CF.CFArrayGetValueAtIndex.argtypes = [_CFArrayRef, _CFIndex]
_CF.CFArrayGetValueAtIndex.restype = c_void_p
_CF.CFGetTypeID.argtypes = [_CFTypeRef]
_CF.CFGetTypeID.restype = c_uint64
_CF.CFStringGetTypeID.argtypes = []
_CF.CFStringGetTypeID.restype = c_uint64
_CF.CFArrayGetTypeID.argtypes = []
_CF.CFArrayGetTypeID.restype = c_uint64
_CF.CFBooleanGetTypeID.argtypes = []
_CF.CFBooleanGetTypeID.restype = c_uint64
_CF.CFBooleanGetValue.argtypes = [_CFTypeRef]
_CF.CFBooleanGetValue.restype = ctypes.c_bool

_AX.AXUIElementCreateApplication.argtypes = [c_int32]
_AX.AXUIElementCreateApplication.restype = _AXUIElementRef
_AX.AXUIElementCopyAttributeValue.argtypes = [_AXUIElementRef, _CFStringRef, POINTER(_CFTypeRef)]
_AX.AXUIElementCopyAttributeValue.restype = _AXError
_AX.AXUIElementSetAttributeValue.argtypes = [_AXUIElementRef, _CFStringRef, _CFTypeRef]
_AX.AXUIElementSetAttributeValue.restype = _AXError
_AX.AXUIElementPerformAction.argtypes = [_AXUIElementRef, _CFStringRef]
_AX.AXUIElementPerformAction.restype = _AXError
_AX.AXUIElementCopyActionNames.argtypes = [_AXUIElementRef, POINTER(_CFArrayRef)]
_AX.AXUIElementCopyActionNames.restype = _AXError

_kCFBooleanTrue = c_void_p.in_dll(_CF, "kCFBooleanTrue")
_STRING_TYPE_ID = _CF.CFStringGetTypeID()
_ARRAY_TYPE_ID = _CF.CFArrayGetTypeID()
_BOOL_TYPE_ID = _CF.CFBooleanGetTypeID()


def _cfstr(s: str) -> _CFStringRef:
    return _CF.CFStringCreateWithCString(None, s.encode("utf-8"), _kCFStringEncodingUTF8)


def _cfstr_to_py(ref: _CFStringRef) -> str:
    if not ref:
        return ""
    length = _CF.CFStringGetLength(ref)
    buf_size = length * 4 + 1
    buf = ctypes.create_string_buffer(buf_size)
    if _CF.CFStringGetCString(ref, buf, buf_size, _kCFStringEncodingUTF8):
        return buf.value.decode("utf-8", errors="replace")
    return ""


def _ax_get(element: _AXUIElementRef, attr: str):
    cf_attr = _cfstr(attr)
    value = _CFTypeRef()
    err = _AX.AXUIElementCopyAttributeValue(element, cf_attr, byref(value))
    _CF.CFRelease(cf_attr)
    if err != _kAXErrorSuccess:
        return None
    return value.value


def _ax_get_str(element: _AXUIElementRef, attr: str) -> str:
    val = _ax_get(element, attr)
    if val is None:
        return ""
    try:
        if _CF.CFGetTypeID(val) == _STRING_TYPE_ID:
            return _cfstr_to_py(val)
    except Exception:
        pass
    return ""


def _ax_get_bool(element: _AXUIElementRef, attr: str):
    val = _ax_get(element, attr)
    if val is None:
        return None
    try:
        if _CF.CFGetTypeID(val) == _BOOL_TYPE_ID:
            return _CF.CFBooleanGetValue(val)
    except Exception:
        pass
    return None


def _ax_children(element: _AXUIElementRef) -> list:
    val = _ax_get(element, "AXChildren")
    if val is None:
        return []
    try:
        if _CF.CFGetTypeID(val) == _ARRAY_TYPE_ID:
            count = _CF.CFArrayGetCount(val)
            return [_CF.CFArrayGetValueAtIndex(val, i) for i in range(count)]
    except Exception:
        pass
    return []


def _ax_app(pid: int) -> _AXUIElementRef:
    return _AX.AXUIElementCreateApplication(pid)


def _ax_enable_enhanced_ui(pid: int) -> bool:
    """Enable AXEnhancedUserInterface so Chromium exposes its full AX tree."""
    app = _ax_app(pid)
    if not app:
        return False
    attr = _cfstr("AXEnhancedUserInterface")
    _AX.AXUIElementSetAttributeValue(app, attr, _kCFBooleanTrue)
    _CF.CFRelease(attr)
    return True


def _ax_windows(pid: int) -> list:
    app = _ax_app(pid)
    if not app:
        return []
    val = _ax_get(app, "AXWindows")
    if val is None:
        return []
    try:
        if _CF.CFGetTypeID(val) == _ARRAY_TYPE_ID:
            count = _CF.CFArrayGetCount(val)
            return [_CF.CFArrayGetValueAtIndex(val, i) for i in range(count)]
    except Exception:
        pass
    return []


def _ax_find_window(pid: int, title_hint: str = "", index: int = 0):
    """Find a window by title hint or index."""
    windows = _ax_windows(pid)
    if not windows:
        return None
    if title_hint:
        for w in windows:
            t = _ax_get_str(w, "AXTitle")
            if title_hint in t:
                return w
    if 0 <= index < len(windows):
        return windows[index]
    return windows[0] if windows else None


def _ax_has_press(element) -> bool:
    """Check whether an element supports the AXPress action."""
    names = _CFArrayRef()
    err = _AX.AXUIElementCopyActionNames(element, ctypes.byref(names))
    if err != _kAXErrorSuccess or not names.value:
        return False
    count = _CF.CFArrayGetCount(names)
    for i in range(count):
        item = _CF.CFArrayGetValueAtIndex(names, i)
        if _CF.CFGetTypeID(item) == _STRING_TYPE_ID and _cfstr_to_py(item) == "AXPress":
            _CF.CFRelease(names)
            return True
    _CF.CFRelease(names)
    return False


def _ax_find_pressable_ancestor(element, max_levels: int = 5):
    """Walk up the parent chain to find the nearest ancestor with AXPress."""
    current = element
    for _ in range(max_levels):
        parent = _ax_get(current, "AXParent")
        if not parent:
            return None
        if _ax_has_press(parent):
            return parent
        current = parent
    return None


def _ax_scan_tree(element, max_depth: int = 25, _depth: int = 0) -> dict:
    """Walk the AX tree under element, collecting buttons, texts, and clickable groups."""
    result: dict = {
        "buttons": [], "texts": [], "containers": [],
        "_button_refs": [], "_clickable_texts": [],
    }
    if _depth > max_depth:
        return result

    role = _ax_get_str(element, "AXRole")
    subrole = _ax_get_str(element, "AXSubrole")

    if role == "AXButton":
        label = _ax_get_str(element, "AXTitle") or _ax_get_str(element, "AXDescription")
        if label:
            result["buttons"].append(label)
            result["_button_refs"].append((label, element))
    elif role == "AXStaticText":
        text = _ax_get_str(element, "AXValue") or _ax_get_str(element, "AXTitle")
        if text:
            result["texts"].append(text)
            text_stripped = text.strip()
            if len(text_stripped) > 2 and ord(text_stripped[0]) < 0xE000:
                if _ax_has_press(element):
                    result["_clickable_texts"].append((text, element, None))
                else:
                    ancestor = _ax_find_pressable_ancestor(element, max_levels=3)
                    if ancestor:
                        result["_clickable_texts"].append((text, element, ancestor))
    elif role == "AXGroup":
        label = _ax_get_str(element, "AXTitle") or _ax_get_str(element, "AXDescription")
        if label and _ax_has_press(element):
            result["buttons"].append(label)
            result["_button_refs"].append((label, element))

    if role in ("AXDialog", "AXSheet") or "Dialog" in subrole or "Sheet" in subrole:
        result["containers"].append(f"{role}\t{subrole}")

    for child in _ax_children(element):
        if child:
            sub = _ax_scan_tree(child, max_depth, _depth + 1)
            result["buttons"].extend(sub["buttons"])
            result["texts"].extend(sub["texts"])
            result["containers"].extend(sub["containers"])
            result["_button_refs"].extend(sub["_button_refs"])
            result["_clickable_texts"].extend(sub["_clickable_texts"])

    return result


def _ax_press_button(button_ref: _AXUIElementRef) -> bool:
    """Perform AXPress on a button element reference."""
    action = _cfstr("AXPress")
    err = _AX.AXUIElementPerformAction(button_ref, action)
    _CF.CFRelease(action)
    return err == _kAXErrorSuccess


# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

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
        "Run this time only",
        "Continue",
        "Allow",
        "Approve",
        "Trust",
        "Trust Workspace & Continue",
        "Open",
        "Install",
        "Always allow",
    ],
    "prompt_text_keywords": [
        "agent wants",
        "allow",
        "approve",
        "are you sure",
        "do you want",
        "permission",
        "trust",
        "wants to run",
        "wants to execute",
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
    """Scan a Cursor window for buttons, text, and dialog containers.

    Uses the native macOS Accessibility C API for speed.
    AXEnhancedUserInterface must already be enabled on the target pid.
    """
    win = _ax_find_window(pid, index=window_index - 1)
    if not win:
        return {"buttons": [], "texts": [], "containers": [], "_button_refs": [], "_clickable_texts": []}
    raw = _ax_scan_tree(win, max_depth=25)
    return {
        "buttons": unique_non_empty(raw["buttons"]),
        "texts": unique_non_empty(raw["texts"]),
        "containers": unique_non_empty(raw["containers"]),
        "_button_refs": raw["_button_refs"],
        "_clickable_texts": raw["_clickable_texts"],
    }


def choose_approval_button(snapshot: dict[str, Any], state: dict[str, Any]) -> "tuple[str, Any] | tuple[None, None]":
    """Choose which button to click from a scan snapshot.

    Returns (label, clickable_ref) where clickable_ref is an AXUIElementRef
    that supports AXPress (either the button itself, a clickable text, or the
    nearest pressable ancestor of a text label).

    Safety gates:
    - Either a modal container is visible, OR prompt keywords appear in the text
    - The button/text label must match the known approval labels list
    - Exact label matches like "Allow" are prioritised over prefix matches
    """
    buttons = snapshot.get("buttons", [])
    button_refs = snapshot.get("_button_refs", [])
    clickable_texts = snapshot.get("_clickable_texts", [])

    if not buttons and not clickable_texts:
        return None, None

    text_blob = " ".join(text.lower() for text in snapshot.get("texts", []))
    prompt_keywords = get_state_list(state, "prompt_text_keywords")
    has_prompt_keyword = any(keyword.lower() in text_blob for keyword in prompt_keywords)
    has_modal_container = bool(snapshot.get("containers"))

    approval_labels = get_state_list(state, "approval_button_labels")
    approval_normalized = {normalize_text(label) for label in approval_labels}

    has_approval_button = any(
        normalize_text(b) in approval_normalized for b in buttons
    )

    has_approval_text = any(
        _text_matches_approval(text, approval_normalized)
        for text, _el, _ancestor in clickable_texts
    )

    if not has_modal_container and not has_prompt_keyword and not has_approval_button and not has_approval_text:
        return None, None

    ref_by_label: dict[str, Any] = {}
    for label, ref in button_refs:
        ref_by_label[label] = ref

    buttons_by_normalized = {normalize_text(button): button for button in buttons}

    # 1. Exact AXButton match
    for preferred in approval_labels:
        normalized = normalize_text(preferred)
        if normalized in buttons_by_normalized:
            label = buttons_by_normalized[normalized]
            return label, ref_by_label.get(label)

    # 2. Clickable text match (AXStaticText with AXPress or pressable ancestor)
    for preferred in approval_labels:
        normalized = normalize_text(preferred)
        for text, text_el, ancestor_el in clickable_texts:
            if _text_matches_approval(text, {normalized}):
                clickable = text_el if ancestor_el is None else ancestor_el
                return text, clickable

    # 3. Prefix match on AXButton labels
    for preferred in approval_labels:
        normalized = normalize_text(preferred)
        for button in buttons:
            if normalize_text(button).startswith(normalized + " "):
                return button, ref_by_label.get(button)

    # 4. Prefix match on clickable text labels
    for preferred in approval_labels:
        normalized = normalize_text(preferred)
        for text, text_el, ancestor_el in clickable_texts:
            clean = normalize_text(_strip_keyboard_hint(text))
            if clean.startswith(normalized + " ") or clean.startswith(normalized):
                clickable = text_el if ancestor_el is None else ancestor_el
                return text, clickable

    return None, None


def _text_matches_approval(text: str, approval_normalized: set) -> bool:
    """Check if a text label matches any approval pattern, ignoring keyboard hints."""
    clean = normalize_text(_strip_keyboard_hint(text))
    return clean in approval_normalized


def _strip_keyboard_hint(text: str) -> str:
    """Remove trailing keyboard shortcut hints like '(⏎)' or '(Enter)'."""
    text = text.strip()
    if text.endswith(")"):
        paren_idx = text.rfind("(")
        if paren_idx > 0:
            return text[:paren_idx].strip()
    return text


def click_button(pid: int, window_index: int, button_label: str, button_ref: Any = None) -> bool:
    """Click a button by its AX element reference or by rescanning.

    If button_ref is provided, performs AXPress directly (fast path).
    Otherwise falls back to a rescan to find the button among both
    AXButton elements and clickable text elements.
    """
    if button_ref is not None:
        return _ax_press_button(button_ref)

    win = _ax_find_window(pid, index=window_index - 1)
    if not win:
        return False
    raw = _ax_scan_tree(win, max_depth=25)
    for label, ref in raw["_button_refs"]:
        if label == button_label:
            return _ax_press_button(ref)
    for text, text_el, ancestor_el in raw["_clickable_texts"]:
        if text == button_label:
            clickable = text_el if ancestor_el is None else ancestor_el
            return _ax_press_button(clickable)
    return False


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
    workspace_mismatch = False

    if reason is None and not path_matches_workspace(cwd, session.get("workspace_path")):
        reason = f"cwd outside active workspace: {cwd!r}"
        workspace_mismatch = True

    if reason is None:
        touch_session("hook allow")
        log_event(f"hook allow command={command!r} cwd={cwd!r}")
        response = {"continue": True, "permission": "allow"}
    else:
        if session.get("active") and reason != "hook disabled" and not workspace_mismatch:
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

    enhanced_ui_set = False
    scan_count = 0
    last_diagnostic_at = 0.0

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

            if not enhanced_ui_set:
                _ax_enable_enhanced_ui(target_pid)
                enhanced_ui_set = True
                time.sleep(0.5)
                log_event(f"watcher enabled AXEnhancedUserInterface for pid {target_pid}")

            target_window = resolve_target_window(target_pid, session.get("target_window", {}))
            if target_window is None:
                mark_session_inactive("target Cursor window disappeared", stop_watcher=False)
                break

            try:
                snapshot = scan_window_elements(target_pid, int(target_window["index"]))
            except Exception as exc:
                log_event(f"watcher scan error: {exc}")
                time.sleep(2)
                continue

            scan_count += 1
            button_label, button_ref = choose_approval_button(snapshot, state)

            now = now_ts()
            if now - last_diagnostic_at >= 60.0:
                btn_list = snapshot.get("buttons", [])
                ct_list = snapshot.get("_clickable_texts", [])
                approval_labels_lower = {normalize_text(l) for l in get_state_list(state, "approval_button_labels")}
                notable_btns = [b for b in btn_list if normalize_text(b) in approval_labels_lower]
                notable_texts = [
                    t for t, _el, _anc in ct_list
                    if _text_matches_approval(t, approval_labels_lower)
                ]
                log_event(
                    f"watcher alive scans={scan_count} buttons={len(btn_list)}"
                    f" clickable_texts={len(ct_list)}"
                    f" texts={len(snapshot.get('texts', []))}"
                    f" notable_btns={notable_btns!r}"
                    f" notable_texts={notable_texts!r}"
                    f" chosen={button_label!r}"
                )
                last_diagnostic_at = now

            if button_label and click_button(target_pid, int(target_window["index"]), button_label, button_ref):
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

    _ax_enable_enhanced_ui(target_pid)

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


def command_scan_now(_args: argparse.Namespace) -> int:
    """One-off scan of the bound Cursor window for debugging."""
    session = load_session()
    state = load_state()
    target_pid = session.get("target_pid")
    if not target_pid:
        target_pid_raw = frontmost_cursor_pid()
        if not target_pid_raw:
            print("No Cursor PID found", file=sys.stderr)
            return 1
        target_pid = target_pid_raw

    _ax_enable_enhanced_ui(target_pid)
    time.sleep(0.3)

    target_window = session.get("target_window", {})
    win_index = int(target_window.get("index", 1))
    snapshot = scan_window_elements(target_pid, win_index)
    button_label, button_ref = choose_approval_button(snapshot, state)

    result = {
        "pid": target_pid,
        "window_index": win_index,
        "buttons": snapshot["buttons"],
        "button_count": len(snapshot["buttons"]),
        "text_count": len(snapshot["texts"]),
        "texts_sample": snapshot["texts"][:20],
        "containers": snapshot["containers"],
        "chosen_button": button_label,
        "chosen_ref_present": button_ref is not None,
    }
    print(json.dumps(result, indent=2))
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
    subparsers.add_parser("scan-now")
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
        "scan-now": command_scan_now,
        "press-once": command_press_once,
        "notification-banner-open": command_notification_banner_open,
        "notification-alert-primary": command_notification_alert_primary,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
