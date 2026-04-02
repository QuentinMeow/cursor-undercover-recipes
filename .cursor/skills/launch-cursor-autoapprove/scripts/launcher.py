#!/usr/bin/env python3
"""
Launch a dedicated Cursor window with DOM auto-accept injected via CDP.

Subcommands:
    launch  Open dedicated Cursor, inject DOM script, gate ON
    on      Resume auto-clicking (startAccept via CDP)
    off     Pause auto-clicking (stopAccept via CDP)
    status  Show gate state and click count
    stop    Pause gate and end session
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

CURSOR_APP_PATH = Path("/Applications/Cursor.app")
CURSOR_EXECUTABLE = CURSOR_APP_PATH / "Contents" / "MacOS" / "Cursor"

RUNTIME_DIR = Path.home() / ".cursor" / "launch-autoapprove"
STATE_PATH = RUNTIME_DIR / "state.json"
PROFILE_DIR = RUNTIME_DIR / "dedicated-profile"

SCRIPT_DIR = Path(__file__).resolve().parent
DOM_INJECTOR_PATH = SCRIPT_DIR / "devtools_auto_accept.js"
INSTALLED_DOM_INJECTOR_PATH = RUNTIME_DIR / "devtools_auto_accept.js"

CURSOR_DEFAULT_USER_DATA = Path.home() / "Library" / "Application Support" / "Cursor"

CDP_DEFAULT_PORT = 9222
LAUNCH_TIMEOUT = 30.0
CDP_INJECT_DELAY = 5.0
CDP_INJECT_RETRIES = 6

# ---------------------------------------------------------------------------
# State file helpers
# ---------------------------------------------------------------------------


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_state(state: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _clear_state() -> None:
    try:
        STATE_PATH.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        _save_state({})


def _dom_injector_path() -> Path:
    # Installed launcher should prefer installed injector copy.
    # Repo launcher should prefer repo-local injector for development/testing.
    if SCRIPT_DIR == RUNTIME_DIR and INSTALLED_DOM_INJECTOR_PATH.exists():
        return INSTALLED_DOM_INJECTOR_PATH
    if DOM_INJECTOR_PATH.exists():
        return DOM_INJECTOR_PATH
    return INSTALLED_DOM_INJECTOR_PATH


def _load_dom_injector_script() -> tuple[str, str, Path]:
    js_path = _dom_injector_path()
    script = js_path.read_text(encoding="utf-8")
    script_hash = hashlib.sha256(script.encode("utf-8")).hexdigest()[:12]
    wrapped = f"globalThis.__cursorAutoAcceptScriptHash = {json.dumps(script_hash)};\n{script}"
    return wrapped, script_hash, js_path


def _clear_injector_expression() -> str:
    return """
(() => {
  try {
    if (globalThis.__cursorAutoAccept) {
      if (typeof globalThis.__cursorAutoAccept.stop === "function") {
        globalThis.__cursorAutoAccept.stop();
      }
      const st = globalThis.__cursorAutoAccept.state;
      if (st && st.titleTimer) clearInterval(st.titleTimer);
    }
  } catch (_) {}
  delete globalThis.__cursorAutoAccept;
  delete globalThis.startAccept;
  delete globalThis.stopAccept;
  delete globalThis.acceptStatus;
  delete globalThis.__cursorAutoAcceptScriptHash;
  delete globalThis.__cursorAutoAcceptRepoSlug;
})()
""".strip()


# ---------------------------------------------------------------------------
# Settings sync
# ---------------------------------------------------------------------------


def _sync_user_settings() -> None:
    """Copy settings.json and keybindings.json from default Cursor profile."""
    src_user = CURSOR_DEFAULT_USER_DATA / "User"
    dst_user = PROFILE_DIR / "User"

    if not src_user.is_dir():
        print(f"  Default Cursor profile not found at {src_user}, skipping settings sync.")
        return

    dst_user.mkdir(parents=True, exist_ok=True)

    for filename in ("settings.json", "keybindings.json"):
        src = src_user / filename
        dst = dst_user / filename
        if src.is_file():
            shutil.copy2(src, dst)
            print(f"  Synced {filename} from default profile")


# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _cursor_main_processes() -> list[tuple[int, str]]:
    """Find Cursor main processes as (pid, args)."""
    try:
        result = subprocess.run(
            ["ps", "-ax", "-o", "pid=,args="],
            capture_output=True, text=True, check=False,
        )
    except OSError:
        return []
    if result.returncode != 0:
        return []
    exe = str(CURSOR_EXECUTABLE)
    processes: list[tuple[int, str]] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        args = parts[1]
        if args == exe or (args.startswith(exe + " ") and "--type=" not in args):
            processes.append((int(parts[0]), args))
    return sorted(processes, key=lambda pair: pair[0])


def _cursor_main_pids() -> list[int]:
    """Find Cursor main process PIDs, excluding helper/GPU/renderer children."""
    return [pid for pid, _ in _cursor_main_processes()]


def _wait_for_new_pid(existing: set[int], timeout: float, required_args: list[str] | None = None) -> int:
    required_args = required_args or []
    deadline = time.time() + timeout
    while time.time() < deadline:
        for pid, args in _cursor_main_processes():
            if pid not in existing:
                if required_args and not all(token in args for token in required_args):
                    continue
                return pid
        time.sleep(0.5)
    raise RuntimeError("Timed out waiting for dedicated Cursor process")


def _terminate_pid(pid: int, timeout: float = 5.0) -> bool:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except OSError:
        return False

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _pid_is_alive(pid):
            return True
        time.sleep(0.2)
    return not _pid_is_alive(pid)


def _repo_slug(workspace: str | Path) -> str:
    raw = Path(workspace).name.strip() or "workspace"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-")
    return slug or "workspace"


def _window_title(workspace: str | Path, gate_on: bool) -> str:
    state = "✅" if gate_on else "⏸"
    return f"autoapprove {state} {_repo_slug(workspace)}"


# ---------------------------------------------------------------------------
# CDP helpers (minimal websocket client)
# ---------------------------------------------------------------------------


def _cdp_find_port(start: int = CDP_DEFAULT_PORT, max_tries: int = 20) -> int:
    for port in range(start, start + max_tries):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    raise RuntimeError(f"No available CDP port in range {start}-{start + max_tries - 1}")


def _ws_recv_exact(sock: socket.socket, n: int) -> bytes:
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise RuntimeError("CDP websocket closed unexpectedly")
        data += chunk
    return data


def _ws_send_text(sock: socket.socket, text: str) -> None:
    payload = text.encode("utf-8")
    mask_key = os.urandom(4)
    frame = bytearray([0x81])
    length = len(payload)
    if length < 126:
        frame.append(0x80 | length)
    elif length < 65536:
        frame.append(0x80 | 126)
        frame.extend(struct.pack(">H", length))
    else:
        frame.append(0x80 | 127)
        frame.extend(struct.pack(">Q", length))
    frame.extend(mask_key)
    masked = bytearray(length)
    for i in range(length):
        masked[i] = payload[i] ^ mask_key[i % 4]
    frame.extend(masked)
    sock.sendall(frame)


def _ws_recv_text(sock: socket.socket) -> str:
    header = _ws_recv_exact(sock, 2)
    is_masked = bool(header[1] & 0x80)
    length = header[1] & 0x7F
    if length == 126:
        length = struct.unpack(">H", _ws_recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack(">Q", _ws_recv_exact(sock, 8))[0]
    mask_key = _ws_recv_exact(sock, 4) if is_masked else None
    raw = bytearray(_ws_recv_exact(sock, length))
    if mask_key:
        for i in range(len(raw)):
            raw[i] ^= mask_key[i % 4]
    return bytes(raw).decode("utf-8")


def _cdp_evaluate_ws(ws_url: str, expression: str, timeout: float = 10.0) -> dict:
    """Evaluate JS against a specific websocket debugger target."""
    parsed = urllib.parse.urlparse(ws_url)
    sock = socket.create_connection((parsed.hostname, parsed.port), timeout=timeout)
    sock.settimeout(timeout)
    try:
        key = base64.b64encode(os.urandom(16)).decode()
        handshake = (
            f"GET {parsed.path} HTTP/1.1\r\n"
            f"Host: {parsed.hostname}:{parsed.port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        sock.sendall(handshake.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            response += sock.recv(4096)
        if b"101" not in response.split(b"\r\n")[0]:
            raise RuntimeError("CDP websocket handshake failed")

        msg = json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "returnByValue": True},
        })
        _ws_send_text(sock, msg)
        deadline = time.time() + timeout
        while time.time() < deadline:
            payload = json.loads(_ws_recv_text(sock))
            if payload.get("id") != 1:
                continue
            if payload.get("error"):
                message = payload["error"].get("message", "CDP evaluate error")
                raise RuntimeError(message)
            return payload
    except socket.timeout as exc:
        raise RuntimeError("Timed out waiting for CDP response") from exc
    finally:
        try:
            sock.close()
        except OSError:
            pass
    raise RuntimeError("Timed out waiting for CDP response")


def _cdp_evaluate(port: int, expression: str, timeout: float = 10.0) -> dict:
    """Evaluate JS in the first usable page target via CDP websocket."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    conn.request("GET", "/json")
    resp = conn.getresponse()
    targets = json.loads(resp.read().decode("utf-8"))
    conn.close()

    page_targets = [
        t.get("webSocketDebuggerUrl")
        for t in targets
        if t.get("type") == "page" and t.get("webSocketDebuggerUrl")
    ]
    if not page_targets:
        raise RuntimeError(f"No page target found on CDP port {port}")
    last_error: RuntimeError | None = None
    for ws_url in page_targets:
        try:
            return _cdp_evaluate_ws(ws_url, expression, timeout=timeout)
        except RuntimeError as exc:
            last_error = exc
            continue
    raise RuntimeError(
        f"No usable page target on CDP port {port}: {last_error or 'unknown error'}"
    )


def _format_injector_hash(script_hash: str | None) -> str:
    return script_hash or "unknown"


def _cdp_inject(port: int, auto_start: bool = True, force_reload: bool = False,
                 repo_slug: str = "workspace") -> bool:
    """Inject the DOM auto-accept script via CDP. Returns True on success."""
    js_path = _dom_injector_path()
    if not js_path.exists():
        print(f"DOM injector not found at {js_path}", file=sys.stderr)
        return False

    script, _script_hash, script_path = _load_dom_injector_script()
    slug_preamble = f"globalThis.__cursorAutoAcceptRepoSlug = {json.dumps(repo_slug)};\n"
    script = slug_preamble + script
    if force_reload:
        script = _clear_injector_expression() + "\n" + script
    if auto_start:
        script += "\n; startAccept();"

    for attempt in range(CDP_INJECT_RETRIES):
        try:
            result = _cdp_evaluate(port, script, timeout=10.0)
            exc = result.get("result", {}).get("exceptionDetails")
            if exc:
                print(f"DOM injection error: {exc.get('text', '')}", file=sys.stderr)
                return False
            print(f"Injected script from {script_path}")
            return True
        except (ConnectionRefusedError, OSError, RuntimeError):
            if attempt < CDP_INJECT_RETRIES - 1:
                time.sleep(2 * (attempt + 1))
            else:
                return False
    return False


def _cdp_title(port: int) -> str | None:
    try:
        result = _cdp_evaluate(
            port,
            """
(() => {
  const titleButton = document.querySelector('[id="workbench.parts.titlebar"] .window-title-text');
  return titleButton?.textContent || document.title;
})()
""".strip(),
        )
        value = result.get("result", {}).get("result", {}).get("value")
        return value if isinstance(value, str) else None
    except (ConnectionRefusedError, OSError, RuntimeError):
        return None


def _title_sync_expr(title: str) -> str:
    title_json = json.dumps(title)
    return f"""
document.title = {title_json};
(() => {{
  const titleButton = document.querySelector('[id="workbench.parts.titlebar"] .window-title-text');
  if (titleButton) {{
    titleButton.textContent = {title_json};
    titleButton.title = {title_json};
    titleButton.setAttribute("aria-label", {title_json});
  }}
  const titleContainer = document.querySelector('[id="workbench.parts.titlebar"] .window-title');
  if (titleContainer) titleContainer.title = {title_json};
}})();
""".strip()


def _cdp_gate(port: int, action: str, title: str | None = None) -> dict | None:
    """Call startAccept/stopAccept/acceptStatus via CDP. Returns parsed status or None."""
    title_expr = _title_sync_expr(title) if title else ""
    if action == "on":
        expr = f"{title_expr} startAccept(); JSON.stringify(acceptStatus())"
    elif action == "off":
        expr = f"stopAccept(); {title_expr} JSON.stringify(acceptStatus())"
    elif action == "status":
        expr = "JSON.stringify(acceptStatus())"
    else:
        return None

    try:
        result = _cdp_evaluate(port, expr)
        value = result.get("result", {}).get("result", {}).get("value")
        if isinstance(value, str):
            return json.loads(value)
        return value
    except (ConnectionRefusedError, OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"CDP error: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_launch(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve() if args.workspace else Path.cwd()
    enabled_title = _window_title(workspace, gate_on=True)

    state = _load_state()
    existing_pid = state.get("pid")
    if existing_pid and _pid_is_alive(existing_pid):
        print(f"A dedicated Cursor is already running (PID {existing_pid}).")
        print("Use 'on'/'off' to toggle, or 'stop' first to start a new one.")
        return 1

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    print("Syncing user settings from default Cursor profile...")
    _sync_user_settings()

    try:
        cdp_port = _cdp_find_port()
    except RuntimeError as exc:
        print(f"Could not find an available CDP port: {exc}", file=sys.stderr)
        return 1

    existing_pids = set(_cursor_main_pids())
    required_args = [
        f"--remote-debugging-port={cdp_port}",
        "--user-data-dir",
        str(PROFILE_DIR),
    ]

    command = [
        "open", "-na", str(CURSOR_APP_PATH), "--args",
        f"--remote-debugging-port={cdp_port}",
        "--user-data-dir", str(PROFILE_DIR),
        str(workspace),
    ]
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    print(f"Launching dedicated Cursor for {workspace} (CDP port {cdp_port})...")

    try:
        pid = _wait_for_new_pid(existing_pids, LAUNCH_TIMEOUT, required_args=required_args)
    except RuntimeError:
        print("Falling back to direct executable launch...")
        subprocess.Popen(
            [str(CURSOR_EXECUTABLE),
             f"--remote-debugging-port={cdp_port}",
             "--user-data-dir", str(PROFILE_DIR),
             str(workspace)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        try:
            pid = _wait_for_new_pid(existing_pids, LAUNCH_TIMEOUT, required_args=required_args)
        except RuntimeError:
            print("Failed to detect new Cursor process.", file=sys.stderr)
            return 1

    _save_state({
        "pid": pid,
        "cdp_port": cdp_port,
        "workspace": str(workspace),
        "launched_at": datetime.now(timezone.utc).isoformat(),
    })

    print(f"Cursor started (PID {pid}). Waiting for CDP to become ready...")
    time.sleep(CDP_INJECT_DELAY)

    slug = _repo_slug(workspace)
    if _cdp_inject(cdp_port, auto_start=False, force_reload=True, repo_slug=slug):
        result = _cdp_gate(cdp_port, "on", title=enabled_title)
        print("\nAuto-approve ON.")
        print(f"Window title target: {enabled_title}")
        if result and result.get("scriptHash"):
            print(f"Injector hash: {result['scriptHash']}")
    else:
        print("\nCDP injection failed. You can retry with: aa on", file=sys.stderr)
        print("Or paste the DOM script manually into DevTools.", file=sys.stderr)

    print("  'aa off'    pause auto-clicking")
    print("  'aa on'     resume auto-clicking")
    print("  'aa status' check state")
    print("  'aa stop'   end session")
    return 0


def cmd_on(_args: argparse.Namespace) -> int:
    state = _load_state()
    port = state.get("cdp_port")
    pid = state.get("pid")
    workspace = state.get("workspace", "workspace")
    enabled_title = _window_title(workspace, gate_on=True)

    if not port:
        print("No active session. Run 'launch' first.", file=sys.stderr)
        return 1
    if pid and not _pid_is_alive(pid):
        print(f"Dedicated Cursor (PID {pid}) is no longer running.", file=sys.stderr)
        return 1

    check = _cdp_gate(port, "status")
    expected_hash: str | None = None
    expected_path: Path | None = None
    try:
        _, expected_hash, expected_path = _load_dom_injector_script()
    except OSError:
        pass

    current_hash = check.get("scriptHash") if isinstance(check, dict) else None
    needs_reload = check is None or (expected_hash is not None and current_hash != expected_hash)
    slug = _repo_slug(workspace)
    if needs_reload:
        if check is None:
            print(
                "Could not read injector status via CDP "
                "(unreachable, wrong target, or missing injector). Re-injecting DOM script..."
            )
        else:
            print(
                "Reloading DOM script to match the current injector file "
                f"(window={_format_injector_hash(current_hash)}, local={expected_hash}, "
                f"path={expected_path})."
            )
        if not _cdp_inject(port, auto_start=False, force_reload=True, repo_slug=slug):
            print("Injection failed.", file=sys.stderr)
            return 1

    result = _cdp_gate(port, "on", title=enabled_title)
    if result:
        print(f"Auto-approve ON (total clicks so far: {result.get('totalClicks', 0)})")
        print(f"Window title target: {enabled_title}")
        if result.get("scriptHash"):
            print(f"Injector hash: {result['scriptHash']}")
    else:
        print("Failed to start auto-approve.", file=sys.stderr)
        return 1
    return 0


def cmd_off(_args: argparse.Namespace) -> int:
    state = _load_state()
    port = state.get("cdp_port")
    pid = state.get("pid")
    workspace = state.get("workspace", "workspace")
    disabled_title = _window_title(workspace, gate_on=False)

    if not port:
        print("No active session. Run 'launch' first.", file=sys.stderr)
        return 1
    if pid and not _pid_is_alive(pid):
        print(f"Dedicated Cursor (PID {pid}) is no longer running.", file=sys.stderr)
        return 1

    result = _cdp_gate(port, "off", title=disabled_title)
    if result:
        print(f"Auto-approve OFF (total clicks: {result.get('totalClicks', 0)})")
        print(f"Window title target: {disabled_title}")
    else:
        print("Failed to stop auto-approve.", file=sys.stderr)
        return 1
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    state = _load_state()
    if not state:
        print("No active session.")
        return 0

    pid = state.get("pid")
    port = state.get("cdp_port")
    alive = _pid_is_alive(pid) if pid else False

    print(f"PID:       {pid or 'none'} ({'running' if alive else 'stopped'})")
    print(f"CDP port:  {port or 'none'}")
    print(f"Workspace: {state.get('workspace', 'unknown')}")
    print(f"Launched:  {state.get('launched_at', 'unknown')}")

    if alive and port:
        gate = _cdp_gate(port, "status")
        if gate:
            running = gate.get("running", False)
            clicks = gate.get("totalClicks", 0)
            label = "ON" if running else "OFF"
            title = _cdp_title(port)
            print(f"Gate:      {label}")
            print(f"Clicks:    {clicks}")
            print(f"Injector:  {_format_injector_hash(gate.get('scriptHash'))}")
            if title:
                print(f"Window:    {title}")
            recent = gate.get("recentClicks", [])
            if recent:
                print(f"Recent:    {json.dumps(recent[-3:])}")
        else:
            print("Gate:      unknown (CDP or injector status unavailable)")
    elif not alive:
        print("Gate:      N/A (process not running)")

    return 0


def cmd_stop(_args: argparse.Namespace) -> int:
    state = _load_state()
    port = state.get("cdp_port")
    pid = state.get("pid")
    workspace = state.get("workspace", "workspace")
    disabled_title = _window_title(workspace, gate_on=False)

    if port and pid and _pid_is_alive(pid):
        _cdp_gate(port, "off", title=disabled_title)
        if _terminate_pid(pid):
            print(f"Auto-approve OFF. Dedicated Cursor (PID {pid}) closed.")
        else:
            print(f"Auto-approve OFF, but dedicated Cursor (PID {pid}) is still running.")
            print("Close it manually if you want a fully clean stop.")
    elif pid and not _pid_is_alive(pid):
        print(f"Dedicated Cursor (PID {pid}) already exited.")
    else:
        print("No active session.")

    _clear_state()
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Launch and control a dedicated auto-approve Cursor instance",
    )
    sub = parser.add_subparsers(dest="command")

    p_launch = sub.add_parser("launch", help="Open dedicated Cursor with auto-approve")
    p_launch.add_argument("--workspace", "-w", help="Workspace path (default: cwd)")
    p_launch.add_argument("workspace_pos", nargs="?", help="Workspace path (positional)")
    p_launch.set_defaults(func=cmd_launch)

    p_on = sub.add_parser("on", help="Resume auto-clicking")
    p_on.set_defaults(func=cmd_on)

    p_off = sub.add_parser("off", help="Pause auto-clicking")
    p_off.set_defaults(func=cmd_off)

    p_status = sub.add_parser("status", help="Show gate state and click count")
    p_status.set_defaults(func=cmd_status)

    p_stop = sub.add_parser("stop", help="Pause gate and end session")
    p_stop.set_defaults(func=cmd_stop)

    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    # Allow positional workspace for launch
    if args.command == "launch" and not args.workspace and args.workspace_pos:
        args.workspace = args.workspace_pos

    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
