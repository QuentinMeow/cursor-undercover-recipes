#!/usr/bin/env python3
"""
Launch a dedicated Cursor window with DOM auto-accept injected via CDP.

Subcommands:
    launch  Open dedicated Cursor, inject DOM script, gate ON
    on      Resume auto-clicking (startAccept via CDP)
    off     Pause auto-clicking (stopAccept via CDP)
    status  Show gate state and click count
    stop    Pause gate and end session
    help    Show usage examples and deeper docs
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import http.client
import json
import os
import re
import select
import shutil
import signal
import socket
import struct
import subprocess
import sys
import termios
import time
import tty
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
GLOBAL_SKILL_DIR = Path.home() / ".cursor" / "skills" / "global-launch-cursor-autoapprove"

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


def _profile_dir(slug: str) -> Path:
    """Per-workspace dedicated profile directory."""
    return RUNTIME_DIR / f"dedicated-profile-{slug}"


def _load_state() -> dict:
    """Load multi-session state. Auto-migrates legacy single-session format."""
    if not STATE_PATH.exists():
        return {"sessions": {}}
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"sessions": {}}
    if "sessions" in raw:
        return raw
    # Legacy single-session format: wrap into multi-session and migrate profile dir
    if "pid" in raw and "workspace" in raw:
        ws = raw["workspace"]
        slug = _repo_slug(ws)
        raw["slug"] = slug
        new_state = {"sessions": {ws: raw}}
        legacy_profile = RUNTIME_DIR / "dedicated-profile"
        target_profile = _profile_dir(slug)
        if legacy_profile.is_dir() and not target_profile.exists():
            legacy_profile.rename(target_profile)
        _save_state(new_state)
        return new_state
    return {"sessions": {}}


def _save_state(state: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def _remove_session(workspace: str) -> None:
    """Remove a single session entry from state."""
    state = _load_state()
    state["sessions"].pop(workspace, None)
    if state["sessions"]:
        _save_state(state)
    else:
        _clear_all_state()


def _clear_all_state() -> None:
    try:
        STATE_PATH.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        _save_state({"sessions": {}})


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


def _skill_doc_dir() -> Path | None:
    local_skill_dir = SCRIPT_DIR.parent
    if (local_skill_dir / "SKILL.md").is_file():
        return local_skill_dir
    repo_target_skill_dir = SCRIPT_DIR.parent / "skills" / "launch-cursor-autoapprove"
    if (repo_target_skill_dir / "SKILL.md").is_file():
        return repo_target_skill_dir
    if (GLOBAL_SKILL_DIR / "SKILL.md").is_file():
        return GLOBAL_SKILL_DIR
    return None


def _help_doc_lines() -> list[str]:
    lines = [
        "Dive deeper:",
        "  caa <command> --help",
    ]
    doc_dir = _skill_doc_dir()
    if doc_dir:
        lines.extend([
            f"  README: {doc_dir / 'README.md'}",
            f"  Implementation: {doc_dir / 'references' / 'implementation.md'}",
            f"  Manual testing: {doc_dir / 'references' / 'manual-testing.md'}",
            f"  Skill guide: {doc_dir / 'SKILL.md'}",
        ])
    else:
        lines.append(
            "  Skill docs: repo/.cursor/skills/launch-cursor-autoapprove/ "
            "or ~/.cursor/skills/global-launch-cursor-autoapprove/"
        )
    return lines


def _help_examples(topic: str | None = None) -> list[str]:
    topic_examples = {
        "launch": [
            "Examples:",
            "  caa launch ~/code/my-project",
            "  caa launch -w ~/code/another-project",
        ],
        "on": [
            "Examples:",
            "  caa on",
            "  caa on -w my-project",
        ],
        "off": [
            "Examples:",
            "  caa off",
            "  caa off -w my-project",
        ],
        "status": [
            "Examples:",
            "  caa status",
            "  caa status -w my-project",
        ],
        "stop": [
            "Examples:",
            "  caa stop",
            "  caa stop --all",
        ],
        "help": [
            "Examples:",
            "  caa help",
            "  caa help off",
        ],
    }
    if topic in topic_examples:
        return topic_examples[topic]
    return [
        "Examples:",
        "  caa launch ~/code/my-project",
        "  caa off",
        "  caa on -w my-project",
        "  caa status",
        "  caa stop --all",
        "  caa help off",
        "",
        "Multi-session behavior:",
        "  - 'on', 'off', and 'stop' open an arrow-key picker in an interactive terminal",
        "  - 'status -w <slug>' also uses the picker when that slug matches multiple sessions",
        "  - use -w <slug> or -w <full-path> to skip the picker",
        "",
        'If you do not use the alias, replace "caa" with:',
        '  /usr/bin/python3 "$HOME/.cursor/launch-autoapprove/launcher.py"',
    ]


def _print_help_block(lines: list[str]) -> None:
    for line in lines:
        print(line)


def cmd_help(args: argparse.Namespace) -> int:
    parser: argparse.ArgumentParser = args.parser
    command_parsers: dict[str, argparse.ArgumentParser] = args.command_parsers
    topic = getattr(args, "topic", None)

    if topic:
        target = command_parsers.get(topic)
        if target is None:
            print(f"Unknown help topic '{topic}'.", file=sys.stderr)
            print("Available topics: launch, on, off, status, stop, help", file=sys.stderr)
            return 1
        target.print_help()
    else:
        parser.print_help()

    print()
    _print_help_block(_help_examples(topic))
    print()
    _print_help_block(_help_doc_lines())
    return 0


# ---------------------------------------------------------------------------
# Settings sync
# ---------------------------------------------------------------------------


def _sync_user_settings(profile_dir: Path) -> None:
    """Copy settings.json and keybindings.json from default Cursor profile."""
    src_user = CURSOR_DEFAULT_USER_DATA / "User"
    dst_user = profile_dir / "User"

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


def _pid_is_cursor(pid: int) -> bool:
    """Check if a PID belongs to a Cursor main process."""
    for p, _ in _cursor_main_processes():
        if p == pid:
            return True
    return False


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
    if not _pid_is_cursor(pid):
        return not _pid_is_alive(pid)

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
    """Evaluate JS in the main workbench page target via CDP websocket."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    conn.request("GET", "/json")
    resp = conn.getresponse()
    targets = json.loads(resp.read().decode("utf-8"))
    conn.close()

    page_targets = [
        t for t in targets
        if t.get("type") == "page" and t.get("webSocketDebuggerUrl")
    ]
    if not page_targets:
        raise RuntimeError(f"No page target found on CDP port {port}")

    def _is_workbench(t: dict) -> bool:
        url = (t.get("url") or "").lower()
        title = (t.get("title") or "").lower()
        return "workbench" in url or "workbench" in title

    preferred = [t for t in page_targets if _is_workbench(t)]
    ordered = preferred + [t for t in page_targets if t not in preferred]

    last_error: RuntimeError | None = None
    for t in ordered:
        try:
            return _cdp_evaluate_ws(t["webSocketDebuggerUrl"], expression, timeout=timeout)
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
# Session resolution helpers
# ---------------------------------------------------------------------------


def _matching_sessions(state: dict, require_alive: bool = True) -> dict[str, dict]:
    sessions = state.get("sessions", {})
    if not require_alive:
        return sessions
    return {
        ws: session
        for ws, session in sessions.items()
        if session.get("pid") and _pid_is_alive(session["pid"])
    }


def _session_summary(session: dict) -> str:
    workspace = session.get("workspace", "unknown")
    slug = session.get("slug", _repo_slug(workspace))
    pid = session.get("pid") or "none"
    alive = _pid_is_alive(session["pid"]) if session.get("pid") else False
    state = "running" if alive else "stopped"
    return f"{slug:30s} {workspace} ({state}, PID {pid})"


def _picker_stream() -> object:
    if sys.stderr.isatty():
        return sys.stderr
    if sys.stdout.isatty():
        return sys.stdout
    return sys.stderr


def _print_session_choices(sessions: dict[str, dict], *,
                           heading: str = "Matching sessions:",
                           stream: object | None = None) -> None:
    if stream is None:
        stream = _picker_stream()
    print(heading, file=stream)
    for _, session in _ordered_session_items(sessions):
        print(f"  {_session_summary(session)}", file=stream)


def _ordered_session_items(sessions: dict[str, dict]) -> list[tuple[str, dict]]:
    return sorted(
        sessions.items(),
        key=lambda item: (item[1].get("slug", _repo_slug(item[0])), item[0]),
    )


def _terminal_size(stream: object) -> os.terminal_size:
    try:
        fd = stream.fileno()
    except (AttributeError, OSError, ValueError):
        return os.terminal_size((100, 20))
    try:
        return os.get_terminal_size(fd)
    except OSError:
        return os.terminal_size((100, 20))


def _interactive_picker_supported() -> bool:
    if not sys.stdin.isatty():
        return False
    stream = _picker_stream()
    if not hasattr(stream, "isatty") or not stream.isatty():
        return False
    return os.environ.get("TERM", "").lower() != "dumb"


@contextlib.contextmanager
def _raw_terminal(fd: int):
    previous = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)


def _picker_key(fd: int) -> str:
    chunk = os.read(fd, 1)
    if not chunk:
        return "quit"
    if chunk in (b"\r", b"\n"):
        return "enter"
    if chunk == b"\x03":
        raise KeyboardInterrupt
    if chunk in (b"q", b"Q"):
        return "quit"
    if chunk in (b"j", b"J"):
        return "down"
    if chunk in (b"k", b"K"):
        return "up"
    if chunk != b"\x1b":
        return "other"

    seq = b""
    deadline = time.time() + 0.05
    while time.time() < deadline:
        ready, _, _ = select.select([fd], [], [], max(0.0, deadline - time.time()))
        if not ready:
            break
        seq += os.read(fd, 1)
        if seq in (b"[A", b"OA"):
            return "up"
        if seq in (b"[B", b"OB"):
            return "down"
        if seq.startswith((b"[", b"O")) and seq[-1:] in (b"A", b"B"):
            return "up" if seq.endswith(b"A") else "down"
        if len(seq) >= 8:
            break

    if not seq:
        return "quit"
    return "other"


def _fit_terminal_line(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def _render_picker(lines: list[str], previous_lines: int) -> int:
    stream = _picker_stream()
    width = max(_terminal_size(stream).columns - 1, 1)
    if previous_lines:
        stream.write(f"\x1b[{previous_lines}A\r")
    for line in lines:
        fitted = _fit_terminal_line(line, width)
        stream.write("\r" + fitted.ljust(width) + "\x1b[K\n")
    stream.flush()
    return len(lines)


def _clear_picker(previous_lines: int) -> None:
    if previous_lines <= 0:
        return
    stream = _picker_stream()
    width = max(_terminal_size(stream).columns - 1, 1)
    stream.write(f"\x1b[{previous_lines}A\r")
    for _ in range(previous_lines):
        stream.write(" " * width + "\x1b[K\n")
    stream.write(f"\x1b[{previous_lines}A\r")
    stream.flush()


def _pick_session_interactively(command_name: str,
                                sessions: dict[str, dict]) -> dict | None:
    options = [session for _, session in _ordered_session_items(sessions)]
    if len(options) <= 1:
        return options[0] if options else None
    if not _interactive_picker_supported():
        return None

    selected = 0
    previous_lines = 0
    fd = sys.stdin.fileno()
    hint = "Use arrow keys to choose, Enter to confirm, q or Esc to cancel."

    try:
        with _raw_terminal(fd):
            while True:
                lines = [f"Select a session for '{command_name}'. {hint}"]
                for index, session in enumerate(options):
                    prefix = ">" if index == selected else " "
                    lines.append(f"{prefix} {_session_summary(session)}")
                lines.append("Hint: use -w <slug|path> next time to skip the picker.")
                previous_lines = _render_picker(lines, previous_lines)
                key = _picker_key(fd)
                if key == "up":
                    selected = (selected - 1) % len(options)
                elif key == "down":
                    selected = (selected + 1) % len(options)
                elif key == "enter":
                    _clear_picker(previous_lines)
                    return options[selected]
                elif key == "quit":
                    _clear_picker(previous_lines)
                    print("Selection cancelled.", file=_picker_stream())
                    return None
    except KeyboardInterrupt:
        _clear_picker(previous_lines)
        print("\nSelection cancelled.", file=_picker_stream())
        return None


def _resolve_session(args: argparse.Namespace, state: dict,
                     require_alive: bool = True,
                     allow_interactive: bool = False,
                     command_name: str = "command") -> dict | None:
    """Find the target session from -w flag, positional slug, or auto-detect.

    Returns the session dict or None (prints diagnostics to stderr).
    """
    sessions = _matching_sessions(state, require_alive=require_alive)
    diag_stream = _picker_stream()

    workspace_arg = getattr(args, "workspace", None)
    if workspace_arg:
        workspace_path = Path(workspace_arg).expanduser()
        path_like = (
            workspace_arg.startswith(("~", ".", "..")) or
            os.sep in workspace_arg or
            workspace_path.exists()
        )
        matches = {
            ws: s for ws, s in sessions.items()
            if s.get("slug") == workspace_arg or _repo_slug(ws) == workspace_arg
        }
        if not path_like and len(matches) == 1:
            return next(iter(matches.values()))
        if not path_like and len(matches) > 1:
            if allow_interactive:
                picked = _pick_session_interactively(command_name, matches)
                if picked is not None:
                    return picked
            print(
                f"Multiple sessions match '{workspace_arg}'. "
                "Use the full workspace path or pick interactively.",
                file=diag_stream,
            )
            _print_session_choices(matches)
            return None
        resolved = str(workspace_path.resolve())
        if resolved in sessions:
            return sessions[resolved]
        session_label = "active session" if require_alive else "matching session"
        print(f"No {session_label} for '{workspace_arg}'.", file=diag_stream)
        if sessions:
            _print_session_choices(sessions)
        return None

    if len(sessions) == 1:
        return next(iter(sessions.values()))

    if not sessions:
        print("No active sessions. Run 'launch' first.", file=diag_stream)
        return None

    if allow_interactive:
        picked = _pick_session_interactively(command_name, sessions)
        if picked is not None:
            return picked

    print(
        f"Multiple matching sessions for '{command_name}' ({len(sessions)}). "
        "Use -w <slug|path> or re-run in an interactive terminal for a picker.",
        file=diag_stream,
    )
    _print_session_choices(sessions)
    return None


def _print_session_status(session: dict) -> None:
    """Print status for a single session."""
    pid = session.get("pid")
    port = session.get("cdp_port")
    workspace = session.get("workspace", "unknown")
    slug = session.get("slug", _repo_slug(workspace))
    alive = _pid_is_alive(pid) if pid else False

    print(f"Session:   {slug}")
    print(f"PID:       {pid or 'none'} ({'running' if alive else 'stopped'})")
    print(f"CDP port:  {port or 'none'}")
    print(f"Workspace: {workspace}")
    print(f"Launched:  {session.get('launched_at', 'unknown')}")

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


def _stop_session(session: dict) -> bool:
    """Stop a single session's Cursor process.

    Returns True when the session can be removed from state.
    """
    port = session.get("cdp_port")
    pid = session.get("pid")
    workspace = session.get("workspace", "workspace")
    slug = session.get("slug", _repo_slug(workspace))
    disabled_title = _window_title(workspace, gate_on=False)

    if pid and _pid_is_alive(pid):
        if port:
            _cdp_gate(port, "off", title=disabled_title)
        if _terminate_pid(pid):
            print(f"[{slug}] Auto-approve OFF. Dedicated Cursor (PID {pid}) closed.")
            return True
        print(f"[{slug}] Auto-approve OFF, but Cursor (PID {pid}) is still running.")
        print("Close it manually if you want a fully clean stop.")
        return False
    if pid and not _pid_is_alive(pid):
        print(f"[{slug}] Dedicated Cursor (PID {pid}) already exited.")
        return True
    print(f"[{slug}] No active process.")
    return True


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_launch(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve() if args.workspace else Path.cwd()
    ws_key = str(workspace)
    slug = _repo_slug(workspace)
    enabled_title = _window_title(workspace, gate_on=True)

    state = _load_state()
    sessions = state.get("sessions", {})

    existing = sessions.get(ws_key)
    if existing and existing.get("pid") and _pid_is_alive(existing["pid"]):
        print(f"A dedicated Cursor is already running for {slug} (PID {existing['pid']}).")
        print("Use 'on'/'off' to toggle, or 'stop -w' first to relaunch.")
        return 1

    # Handle slug collision with a different workspace
    for ws, s in sessions.items():
        if ws != ws_key and s.get("slug") == slug and s.get("pid") and _pid_is_alive(s["pid"]):
            slug = slug + "-" + hashlib.sha256(ws_key.encode()).hexdigest()[:6]
            break

    profile = _profile_dir(slug)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    profile.mkdir(parents=True, exist_ok=True)

    print("Syncing user settings from default Cursor profile...")
    _sync_user_settings(profile)

    try:
        cdp_port = _cdp_find_port()
    except RuntimeError as exc:
        print(f"Could not find an available CDP port: {exc}", file=sys.stderr)
        return 1

    existing_pids = set(_cursor_main_pids())
    required_args = [
        f"--remote-debugging-port={cdp_port}",
        "--user-data-dir",
        str(profile),
    ]

    command = [
        "open", "-na", str(CURSOR_APP_PATH), "--args",
        f"--remote-debugging-port={cdp_port}",
        "--user-data-dir", str(profile),
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
             "--user-data-dir", str(profile),
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

    sessions[ws_key] = {
        "pid": pid,
        "cdp_port": cdp_port,
        "workspace": ws_key,
        "slug": slug,
        "launched_at": datetime.now(timezone.utc).isoformat(),
    }
    state["sessions"] = sessions
    _save_state(state)

    print(f"Cursor started (PID {pid}). Waiting for CDP to become ready...")
    time.sleep(CDP_INJECT_DELAY)

    if _cdp_inject(cdp_port, auto_start=False, force_reload=True, repo_slug=slug):
        result = _cdp_gate(cdp_port, "on", title=enabled_title)
        print("\nAuto-approve ON.")
        print(f"Window title target: {enabled_title}")
        if result and result.get("scriptHash"):
            print(f"Injector hash: {result['scriptHash']}")
    else:
        print(
            "\nCDP injection failed. Retry by running this launcher with 'on' "
            "(for example: caa on).",
            file=sys.stderr,
        )
        print("Or paste the DOM script manually into DevTools.", file=sys.stderr)

    print("  'caa off'    pause auto-clicking")
    print("  'caa on'     resume auto-clicking")
    print("  'caa status' check state")
    print("  'caa stop'   end session")
    print("  'caa help'   usage examples and docs")
    return 0


def cmd_on(args: argparse.Namespace) -> int:
    state = _load_state()
    session = _resolve_session(args, state, allow_interactive=True, command_name="on")
    if not session:
        return 1

    port = session["cdp_port"]
    pid = session["pid"]
    workspace = session["workspace"]
    enabled_title = _window_title(workspace, gate_on=True)

    if not _pid_is_alive(pid):
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
    slug = session.get("slug", _repo_slug(workspace))
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


def cmd_off(args: argparse.Namespace) -> int:
    state = _load_state()
    session = _resolve_session(args, state, allow_interactive=True, command_name="off")
    if not session:
        return 1

    port = session["cdp_port"]
    pid = session["pid"]
    workspace = session["workspace"]
    disabled_title = _window_title(workspace, gate_on=False)

    if not _pid_is_alive(pid):
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


def cmd_status(args: argparse.Namespace) -> int:
    state = _load_state()
    sessions = state.get("sessions", {})

    if not sessions:
        print("No active sessions.")
        return 0

    workspace_arg = getattr(args, "workspace", None)
    if workspace_arg:
        session = _resolve_session(args, state, require_alive=False, allow_interactive=True, command_name="status")
        if not session:
            return 1
        _print_session_status(session)
        return 0

    alive_count = 0
    for i, (ws, session) in enumerate(sessions.items()):
        if i > 0:
            print()
        _print_session_status(session)
        if session.get("pid") and _pid_is_alive(session["pid"]):
            alive_count += 1

    if len(sessions) > 1:
        print(f"\nTotal: {len(sessions)} session(s), {alive_count} running.")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    state = _load_state()
    sessions = state.get("sessions", {})

    if getattr(args, "all", False):
        if getattr(args, "workspace", None):
            print("Do not combine --all with -w or a positional workspace.", file=sys.stderr)
            return 1
        if not sessions:
            print("No active sessions.")
            return 0
        remaining: dict[str, dict] = {}
        for ws, session in list(sessions.items()):
            if not _stop_session(session):
                remaining[ws] = session
        if remaining:
            _save_state({"sessions": remaining})
            return 1
        _clear_all_state()
        return 0

    if not sessions:
        print("No active session.")
        return 0

    workspace_arg = getattr(args, "workspace", None)
    if workspace_arg:
        session = _resolve_session(
            args,
            state,
            require_alive=False,
            allow_interactive=True,
            command_name="stop",
        )
    else:
        live_candidates = _matching_sessions(state, require_alive=True)
        candidate_state = {"sessions": live_candidates or sessions}
        session = _resolve_session(
            args,
            candidate_state,
            require_alive=False,
            allow_interactive=True,
            command_name="stop",
        )
    if not session:
        return 1

    if _stop_session(session):
        _remove_session(session["workspace"])
        return 0
    return 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> tuple[argparse.ArgumentParser, dict[str, argparse.ArgumentParser]]:
    parser = argparse.ArgumentParser(
        description="Launch and control dedicated auto-approve Cursor instances",
    )
    sub = parser.add_subparsers(dest="command")
    command_parsers: dict[str, argparse.ArgumentParser] = {}

    ws_help = "Workspace path or slug (auto-detected if only one session)"

    p_launch = sub.add_parser("launch", help="Open dedicated Cursor with auto-approve")
    p_launch.add_argument("--workspace", "-w", help="Workspace path (default: cwd)")
    p_launch.add_argument("workspace_pos", nargs="?", help="Workspace path (positional)")
    p_launch.set_defaults(func=cmd_launch)
    command_parsers["launch"] = p_launch

    p_on = sub.add_parser("on", help="Resume auto-clicking")
    p_on.add_argument("--workspace", "-w", help=ws_help)
    p_on.add_argument("workspace_pos", nargs="?", help=ws_help)
    p_on.set_defaults(func=cmd_on)
    command_parsers["on"] = p_on

    p_off = sub.add_parser("off", help="Pause auto-clicking")
    p_off.add_argument("--workspace", "-w", help=ws_help)
    p_off.add_argument("workspace_pos", nargs="?", help=ws_help)
    p_off.set_defaults(func=cmd_off)
    command_parsers["off"] = p_off

    p_status = sub.add_parser("status", help="Show gate state and click count")
    p_status.add_argument("--workspace", "-w", help="Workspace path or slug (shows all if omitted)")
    p_status.add_argument("workspace_pos", nargs="?", help="Workspace path or slug")
    p_status.set_defaults(func=cmd_status)
    command_parsers["status"] = p_status

    p_stop = sub.add_parser("stop", help="Pause gate and end session")
    p_stop.add_argument("--workspace", "-w", help=ws_help)
    p_stop.add_argument("workspace_pos", nargs="?", help=ws_help)
    p_stop.add_argument("--all", action="store_true", help="Stop all active sessions")
    p_stop.set_defaults(func=cmd_stop)
    command_parsers["stop"] = p_stop

    p_help = sub.add_parser("help", help="Show examples and deeper docs", add_help=False)
    p_help.add_argument("-h", "--help", action="store_true", help="Show examples and deeper docs")
    p_help.add_argument("topic", nargs="?", help="Optional command name")
    p_help.set_defaults(func=cmd_help, parser=parser, command_parsers=command_parsers)
    command_parsers["help"] = p_help

    return parser, command_parsers


def main() -> None:
    parser, _ = build_parser()

    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        print("\nRun this launcher with 'help' for examples and deeper docs.")
        sys.exit(1)

    if hasattr(args, "workspace_pos") and args.workspace and args.workspace_pos:
        print("Do not pass both -w/--workspace and a positional workspace.", file=sys.stderr)
        sys.exit(1)

    if hasattr(args, "workspace_pos") and not args.workspace and args.workspace_pos:
        args.workspace = args.workspace_pos

    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
