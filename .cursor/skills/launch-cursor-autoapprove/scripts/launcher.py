#!/usr/bin/env python3
"""
Launch and control dedicated Cursor IDE windows with DOM auto-accept and
bounded agent recovery injected via CDP.

Subcommands:
    launch      Open local dedicated Cursor, inject DOM script, gate/recovery ON
    launch-ssh  Open SSH dedicated Cursor, inject DOM script, gate/recovery ON
    on          Resume auto-clicking (startAccept via CDP)
    off         Pause auto-clicking (stopAccept via CDP)
    cycle       Enable, disable, or run bounded agent approval cycling
    subagents   Show the renderer-local subagent task registry
    status      Show verified mode, gate/recovery state, and session diagnostics
    alias       Manage workspace aliases
    history     Show persisted session/gate/click history
    screenshot  Capture a screenshot via CDP
    diagnose    Run a self-contained CDP diagnostic
    share-safe  Toggle discreet window title for screen sharing
    stop        Pause gate and end session
    help        Show usage examples and deeper docs
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
import shlex
import shutil
import signal
import sqlite3
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
CURSOR_CLI = CURSOR_APP_PATH / "Contents" / "Resources" / "app" / "bin" / "cursor"
CURSOR_CLASSIC_MODE_ARG = "--classic"
CURSOR_IDE_WINDOW_ARG = "--new-window"

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
DEFAULT_POLL_INTERVAL_SECONDS = 0.5
MIN_POLL_INTERVAL_SECONDS = 0.25
MAX_POLL_INTERVAL_SECONDS = 60.0

HISTORY_PATH = RUNTIME_DIR / "history.jsonl"
HISTORY_MAX_BYTES = 5 * 1024 * 1024  # rotate at 5 MB

COMMAND_LEDGER_PATH = RUNTIME_DIR / "commands.jsonl"
COMMAND_LEDGER_MAX_BYTES = 10 * 1024 * 1024  # rotate at 10 MB

SUBAGENTS_PATH = RUNTIME_DIR / "subagents.json"

CONFIG_PATH = RUNTIME_DIR / "config.json"

STALE_HOOK_PATTERNS = [
    "auto-approval/cursor_auto_approval.py",
    "cursor-autoapprove",
    "personal-cursor-quickapprove",
]

SSH_REMOTE_PREFIX = "vscode-remote://ssh-remote+"


def _poll_interval_arg(value: str) -> float:
    """Parse a CLI polling interval in seconds."""
    try:
        interval = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("interval must be a number of seconds") from exc
    if not MIN_POLL_INTERVAL_SECONDS <= interval <= MAX_POLL_INTERVAL_SECONDS:
        raise argparse.ArgumentTypeError(
            f"interval must be between {MIN_POLL_INTERVAL_SECONDS:g} "
            f"and {MAX_POLL_INTERVAL_SECONDS:g} seconds"
        )
    return interval


def _session_poll_interval(session: dict, requested: float | None = None) -> float:
    """Resolve a validated requested or persisted per-session poll interval."""
    raw = requested if requested is not None else session.get(
        "poll_interval_seconds", DEFAULT_POLL_INTERVAL_SECONDS
    )
    try:
        interval = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_POLL_INTERVAL_SECONDS
    if not MIN_POLL_INTERVAL_SECONDS <= interval <= MAX_POLL_INTERVAL_SECONDS:
        return DEFAULT_POLL_INTERVAL_SECONDS
    return interval


def _start_accept_expr(interval_seconds: float | None = None) -> str:
    """Build a startAccept call with an optional validated millisecond interval."""
    if interval_seconds is None:
        return "startAccept()"
    milliseconds = round(interval_seconds * 1000)
    return f"startAccept({milliseconds})"


# ---------------------------------------------------------------------------
# SSH workspace helpers
# ---------------------------------------------------------------------------


def _is_ssh_workspace(ws_key: str) -> bool:
    """Return True if the workspace key is a Remote SSH folder URI."""
    return ws_key.startswith(SSH_REMOTE_PREFIX)


def _ssh_folder_uri(host: str, remote_path: str = "/") -> str:
    """Build a vscode-remote folder URI for an SSH host."""
    quoted_host = urllib.parse.quote(host, safe="")
    clean = (remote_path or "/").lstrip("/")
    quoted_path = urllib.parse.quote(clean, safe="/")
    return f"{SSH_REMOTE_PREFIX}{quoted_host}/{quoted_path}"


def _ssh_slug(host: str, remote_path: str = "/") -> str:
    """Derive a display slug from an SSH host and optional remote path."""
    path_part = (
        remote_path.rstrip("/").rsplit("/", 1)[-1]
        if remote_path and remote_path != "/"
        else ""
    )
    if path_part:
        raw = f"{host}-{path_part}"
    else:
        raw = host
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-")
    return slug or "workspace"


def _parse_ssh_workspace(ws_key: str) -> tuple[str, str] | None:
    """Parse a vscode-remote SSH URI into (host, remote_path)."""
    if not _is_ssh_workspace(ws_key):
        return None
    remainder = ws_key[len(SSH_REMOTE_PREFIX):]
    parts = remainder.split("/", 1)
    host = urllib.parse.unquote(parts[0])
    remote_path = "/" + urllib.parse.unquote(parts[1]) if len(parts) > 1 else "/"
    return host, remote_path


def _ssh_config_hosts() -> list[str]:
    """Return concrete Host aliases from ~/.ssh/config for helpful diagnostics."""
    config_path = Path.home() / ".ssh" / "config"
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    hosts: list[str] = []
    seen: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if not parts or parts[0].lower() != "host":
            continue
        for pattern in parts[1:]:
            if any(ch in pattern for ch in "*?[]!"):
                continue
            if pattern not in seen:
                seen.add(pattern)
                hosts.append(pattern)
    return hosts


def _verify_ssh_remote_path(host: str, remote_path: str) -> tuple[bool, str | None]:
    """Check that a path-specific SSH launch points at an existing directory."""
    if remote_path == "/":
        return True, None

    ssh_exe = shutil.which("ssh") or "ssh"
    remote_test = f"test -d {shlex.quote(remote_path)}"
    command = [
        ssh_exe,
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        host,
        remote_test,
    ]

    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        return False, "Could not find the ssh executable on PATH."
    except subprocess.TimeoutExpired:
        return (
            False,
            f"Timed out while checking {host}:{remote_path} via ssh.",
        )

    if result.returncode == 0:
        return True, None

    detail = "\n".join(
        line for line in (result.stderr.strip(), result.stdout.strip()) if line
    )
    if not detail:
        detail = "ssh exited non-zero; the directory may be missing or inaccessible."

    known_hosts = _ssh_config_hosts()
    host_tip = ""
    if known_hosts and host not in known_hosts:
        preview = ", ".join(known_hosts[:20])
        if len(known_hosts) > 20:
            preview += ", ..."
        host_tip = (
            "\n\nKnown concrete hosts in ~/.ssh/config: "
            f"{preview}\n"
            "launch-ssh expects the SSH config host name, not a Cursor session alias."
        )

    return (
        False,
        "SSH preflight failed while checking the remote workspace directory.\n"
        f"  host: {host}\n"
        f"  path: {remote_path}\n"
        f"  check: {ssh_exe} -o BatchMode=yes -o ConnectTimeout=10 "
        f"{host} {remote_test}\n\n"
        f"{detail}"
        f"{host_tip}",
    )


# ---------------------------------------------------------------------------
# Stale-hook detection
# ---------------------------------------------------------------------------


def _check_stale_hooks(workspace: str | Path | None = None) -> list[str]:
    """Return warning lines if any repo or global hooks.json contains retired approval hooks."""
    warnings: list[str] = []
    candidates: list[Path] = [Path.home() / ".cursor" / "hooks.json"]
    if workspace and not _is_ssh_workspace(str(workspace)):
        candidates.append(Path(workspace) / ".cursor" / "hooks.json")
    for hooks_path in candidates:
        if not hooks_path.is_file():
            continue
        try:
            data = json.loads(hooks_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for hook_list in data.get("hooks", {}).values():
            if not isinstance(hook_list, list):
                continue
            for entry in hook_list:
                cmd = entry.get("command", "") if isinstance(entry, dict) else ""
                for pattern in STALE_HOOK_PATTERNS:
                    if pattern in cmd:
                        warnings.append(
                            f"  WARNING: Stale approval hook detected in {hooks_path}:\n"
                            f"           {cmd}\n"
                            f"           This conflicts with launch-cursor-autoapprove. "
                            f"Remove the hook entry or delete the file."
                        )
    return warnings


# ---------------------------------------------------------------------------
# State file helpers
# ---------------------------------------------------------------------------


def _profile_dir(slug: str) -> Path:
    """Per-workspace dedicated profile directory."""
    return RUNTIME_DIR / f"dedicated-profile-{slug}"


def _load_state(gc: bool = True) -> dict:
    """Load multi-session state. Auto-migrates legacy single-session format.

    When *gc* is True (the default), stale sessions whose PIDs are dead
    are pruned automatically so they never accumulate on disk.
    """
    if not STATE_PATH.exists():
        return {"sessions": {}}
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"sessions": {}}
    if "sessions" in raw:
        if not isinstance(raw["sessions"], dict):
            raw["sessions"] = {}
        if gc:
            return _gc_stale_sessions(raw)
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
        if gc:
            return _gc_stale_sessions(new_state)
        return new_state
    return {"sessions": {}}


def _save_state(state: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def _gc_stale_sessions(state: dict) -> dict:
    """Remove sessions that are stale or invalid and persist the change.

    A session is removed when ANY of these is true:
    - PID is no longer alive (process exited)
    - Workspace path does not exist as a directory (ghost session from a
      bad launch path; the Cursor process is terminated if still alive)
    """
    sessions = state.get("sessions", {})
    keep: dict[str, dict] = {}
    for ws, s in sessions.items():
        pid = s.get("pid")
        pid_alive = pid and _pid_is_alive(pid)

        if _is_ssh_workspace(ws):
            if pid_alive:
                keep[ws] = s
        else:
            ws_exists = Path(ws).is_dir()
            if pid_alive and ws_exists:
                keep[ws] = s
            elif pid_alive and not ws_exists:
                _terminate_pid(pid, timeout=3.0)
        # else: pid dead — just drop the entry

    if len(keep) != len(sessions):
        state["sessions"] = keep
        if keep:
            _save_state(state)
        else:
            _clear_all_state()
        _prune_subagent_snapshots(set(keep))
    return state


def _remove_session(workspace: str) -> None:
    """Remove a single session entry from state."""
    state = _load_state(gc=False)
    state["sessions"].pop(workspace, None)
    if state["sessions"]:
        _save_state(state)
    else:
        _clear_all_state()
    _prune_subagent_snapshots(set(state["sessions"]))


def _clear_all_state() -> None:
    try:
        STATE_PATH.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        _save_state({"sessions": {}})
    with contextlib.suppress(OSError):
        SUBAGENTS_PATH.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Config file helpers (aliases)
# ---------------------------------------------------------------------------


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {"aliases": {}}
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"aliases": {}}
    if not isinstance(raw.get("aliases"), dict):
        raw["aliases"] = {}
    return raw


def _save_config(config: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def _get_alias(name: str) -> str | None:
    """Look up a workspace alias. Returns a local path or SSH folder URI."""
    config = _load_config()
    return config.get("aliases", {}).get(name)


def _set_alias(name: str, workspace_path: str) -> str | None:
    """Register an alias. Returns an error message on collision, else None."""
    config = _load_config()
    aliases = config.get("aliases", {})
    existing = aliases.get(name)
    if existing and existing != workspace_path:
        return (
            f"Alias '{name}' already points to {existing}. "
            f"Run 'caa alias remove {name}' first, or choose a different alias."
        )
    aliases[name] = workspace_path
    config["aliases"] = aliases
    _save_config(config)
    return None


def _remove_alias(name: str) -> bool:
    """Remove an alias. Returns True if it existed."""
    config = _load_config()
    aliases = config.get("aliases", {})
    if name not in aliases:
        return False
    del aliases[name]
    config["aliases"] = aliases
    _save_config(config)
    return True


def _list_aliases() -> dict[str, str]:
    return _load_config().get("aliases", {})


def _auto_register_alias(workspace: str | Path) -> None:
    """Auto-register the directory basename (or SSH slug) as an alias after a successful launch."""
    slug = _repo_slug(workspace)
    ws_str = str(workspace)
    config = _load_config()
    aliases = config.get("aliases", {})
    existing = aliases.get(slug)
    if existing and existing != ws_str:
        return
    if existing == ws_str:
        return
    aliases[slug] = ws_str
    config["aliases"] = aliases
    _save_config(config)


# ---------------------------------------------------------------------------
# DOM injector helpers
# ---------------------------------------------------------------------------


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
  delete globalThis.acceptDebugSnapshot;
  delete globalThis.setShareSafeTitle;
  delete globalThis.setSubagentCycle;
  delete globalThis.runSubagentCycle;
  delete globalThis.exportSubagentRegistry;
  delete globalThis.__cursorAutoAcceptScriptHash;
  delete globalThis.__cursorAutoAcceptRepoSlug;
  delete globalThis.__cursorAutoAcceptWorkspace;
  delete globalThis.__cursorAutoAcceptTargetId;
})()
""".strip()


PROMPT_ARTIFACTS_DIR = RUNTIME_DIR / "prompt-artifacts"


def _log_event(record_type: str, workspace: str = "", slug: str = "",
               **extra: object) -> None:
    """Append an NDJSON event to the history log."""
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "record_type": record_type,
            "workspace": workspace,
            "slug": slug,
        }
        entry.update(extra)
        line = json.dumps(entry, default=str) + "\n"
        if HISTORY_PATH.exists() and HISTORY_PATH.stat().st_size > HISTORY_MAX_BYTES:
            rotated = HISTORY_PATH.with_suffix(".1.jsonl")
            with contextlib.suppress(OSError):
                rotated.unlink(missing_ok=True)
            HISTORY_PATH.rename(rotated)
        with open(HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def _save_prompt_artifact(event: dict, slug: str) -> str | None:
    """Write a per-prompt JSON artifact file. Returns the path or None."""
    try:
        PROMPT_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = event.get("ts", datetime.now(timezone.utc).isoformat())
        ts_safe = ts.replace(":", "").replace("+", "p")[:20]
        kind = event.get("record_type", "unknown")
        fingerprint = event.get("fingerprint", "nofp")[:16]
        fname = f"{ts_safe}-{slug}-{kind}-{fingerprint}.json"
        path = PROMPT_ARTIFACTS_DIR / fname
        path.write_text(json.dumps(event, indent=2, default=str), encoding="utf-8")
        return str(path)
    except OSError:
        return None


def _log_command(event: dict, workspace: str = "", slug: str = "") -> None:
    """Append a command approval record to the dedicated command ledger.

    Only writes an entry when the event carries a non-empty command payload.
    The command ledger is separate from the general history.jsonl so
    terminal-command records are not diluted by gate/session noise and
    can have a longer retention window.
    """
    command_data = event.get("command")
    if not command_data or not isinstance(command_data, dict):
        return
    command_text = command_data.get("text", "")
    if not command_text:
        return
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": event.get("ts", datetime.now(timezone.utc).isoformat()),
            "workspace": workspace,
            "slug": slug,
            "pattern_id": event.get("pattern_id", ""),
            "reason": event.get("reason", ""),
            "command": command_text,
            "lineCount": command_data.get("lineCount", 1),
            "preview": command_data.get("preview", command_text.split("\n")[0][:120]),
            "source": command_data.get("source", "unknown"),
        }
        line = json.dumps(entry, default=str) + "\n"
        if COMMAND_LEDGER_PATH.exists() and COMMAND_LEDGER_PATH.stat().st_size > COMMAND_LEDGER_MAX_BYTES:
            rotated = COMMAND_LEDGER_PATH.with_suffix(".1.jsonl")
            with contextlib.suppress(OSError):
                rotated.unlink(missing_ok=True)
            COMMAND_LEDGER_PATH.rename(rotated)
        with open(COMMAND_LEDGER_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


_DRAIN_EVENTS_EXPR = r"""
(() => {
  if (typeof globalThis.__cursorAutoAccept === 'undefined') return '[]';
  const q = globalThis.__cursorAutoAccept.state.eventQueue || [];
  globalThis.__cursorAutoAccept.state.eventQueue = [];
  return JSON.stringify(q);
})()
""".strip()


def _load_subagent_snapshots() -> dict:
    """Load sanitized per-workspace registry snapshots."""
    if not SUBAGENTS_PATH.exists():
        return {"sessions": {}}
    try:
        raw = json.loads(SUBAGENTS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"sessions": {}}
    if not isinstance(raw, dict) or not isinstance(raw.get("sessions"), dict):
        return {"sessions": {}}
    return raw


def _save_subagent_snapshots(data: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SUBAGENTS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(SUBAGENTS_PATH)


def _prune_subagent_snapshots(valid_workspaces: set[str]) -> None:
    data = _load_subagent_snapshots()
    sessions = data.get("sessions", {})
    keep = {ws: snapshot for ws, snapshot in sessions.items() if ws in valid_workspaces}
    if keep == sessions:
        return
    if keep:
        data["sessions"] = keep
        _save_subagent_snapshots(data)
    else:
        with contextlib.suppress(OSError):
            SUBAGENTS_PATH.unlink(missing_ok=True)


_SUBAGENT_TASK_FIELDS = {
    "taskKey",
    "workspace",
    "targetId",
    "parentComposerId",
    "parentConversationId",
    "toolUseId",
    "rowKey",
    "bubbleIds",
    "rowIndexHint",
    "rowStartHint",
    "title",
    "status",
    "firstSeenAt",
    "lastSeenAt",
    "lastProgressAt",
    "lastAttemptAt",
    "confirmedAt",
    "attempts",
    "failure",
}


def _sanitize_subagent_snapshot(snapshot: dict, workspace: str, slug: str) -> dict:
    """Whitelist registry fields so prompt/command content never reaches disk."""
    raw_tasks = snapshot.get("tasks", [])
    tasks = []
    if isinstance(raw_tasks, list):
        for raw_task in raw_tasks[:500]:
            if not isinstance(raw_task, dict):
                continue
            tasks.append({
                key: raw_task.get(key)
                for key in _SUBAGENT_TASK_FIELDS
                if key in raw_task
            })
    return {
        "version": snapshot.get("version", 1),
        "scriptHash": snapshot.get("scriptHash"),
        "workspace": workspace,
        "slug": slug,
        "targetId": snapshot.get("targetId"),
        "cycleEnabled": snapshot.get("cycleEnabled") is True,
        "cycleActive": snapshot.get("cycleActive") is True,
        "counts": snapshot.get("counts") if isinstance(snapshot.get("counts"), dict) else {},
        "tray": (
            {
                key: value
                for key, value in snapshot.get("tray", {}).items()
                if key in {
                    "running",
                    "mounted",
                    "advertised",
                    "headers",
                    "collapsed",
                    "unknown",
                    "visits",
                    "attempts",
                    "confirmed",
                    "failed",
                }
                and isinstance(value, int)
            }
            if isinstance(snapshot.get("tray"), dict)
            else {}
        ),
        "pinned": (
            {
                **{
                    key: value
                    for key, value in snapshot.get("pinned", {}).items()
                    if key in {
                        "total",
                        "active",
                        "eligible",
                        "ambiguous",
                        "visits",
                        "attempts",
                        "confirmed",
                        "failed",
                    }
                    and isinstance(value, int)
                },
                "lastRestore": (
                    {
                        key: value
                        for key, value in snapshot.get("pinned", {})
                        .get("lastRestore", {})
                        .items()
                        if key in {"ok", "reason", "ts"}
                        and isinstance(value, (bool, str))
                    }
                    if isinstance(
                        snapshot.get("pinned", {}).get("lastRestore"), dict
                    )
                    else None
                ),
            }
            if isinstance(snapshot.get("pinned"), dict)
            else {}
        ),
        "lastCycle": (
            snapshot.get("lastCycle")
            if isinstance(snapshot.get("lastCycle"), dict)
            else None
        ),
        "virtualizer": (
            snapshot.get("virtualizer")
            if isinstance(snapshot.get("virtualizer"), dict)
            else {}
        ),
        "tasks": tasks,
        "exportedAt": snapshot.get("exportedAt"),
    }


def _sync_subagent_registry(port: int, target_id: str | None,
                            workspace: str = "", slug: str = "") -> dict | None:
    """Export the renderer registry and atomically persist its sanitized snapshot."""
    expression = (
        "typeof exportSubagentRegistry === 'function' "
        "? JSON.stringify(exportSubagentRegistry()) : null"
    )
    try:
        result = _cdp_evaluate(port, expression, target_id=target_id)
        raw = result.get("result", {}).get("result", {}).get("value")
        snapshot = json.loads(raw) if isinstance(raw, str) else None
    except (ConnectionRefusedError, OSError, RuntimeError, json.JSONDecodeError):
        return None
    if not isinstance(snapshot, dict):
        return None

    snapshot = _sanitize_subagent_snapshot(
        snapshot,
        workspace or str(snapshot.get("workspace", "")),
        slug,
    )
    data = _load_subagent_snapshots()
    data.setdefault("sessions", {})[snapshot["workspace"]] = snapshot
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        _save_subagent_snapshots(data)
    except OSError:
        return snapshot
    return snapshot


def _drain_injector_events(port: int, target_id: str | None,
                           workspace: str = "", slug: str = "") -> list[dict]:
    """Pull queued events from the injector and persist them durably."""
    try:
        result = _cdp_evaluate(port, _DRAIN_EVENTS_EXPR, target_id=target_id)
        raw = result.get("result", {}).get("result", {}).get("value", "[]")
        events = json.loads(raw) if isinstance(raw, str) else []
    except (ConnectionRefusedError, OSError, RuntimeError, json.JSONDecodeError):
        return []

    persisted: list[dict] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        record_type = ev.get("type", "unknown")
        ev["record_type"] = record_type
        _log_event(
            record_type, workspace, slug,
            **{k: v for k, v in ev.items() if k not in ("type", "record_type")},
        )
        if record_type in ("blocked_candidate", "unknown_prompt"):
            _save_prompt_artifact(ev, slug)
        if record_type in (
            "click",
            "approval_confirmed",
            "tray_approval_confirmed",
            "pinned_approval_confirmed",
        ):
            _log_command(ev, workspace, slug)
        persisted.append(ev)
    return persisted


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
            f"  Agent cycling: {doc_dir / 'references' / 'subagent-approval-cycling.md'}",
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
            "  caa launch ~/code/my-project --interval 5",
            "  caa launch my-project          # if alias exists",
            "  caa launch -w ~/code/another-project",
        ],
        "launch-ssh": [
            "Examples:",
            "  caa launch-ssh my-devbox",
            "  caa launch-ssh my-devbox /home/user/code/project",
            "  caa launch-ssh my-devbox /home/user/code/project --interval 5",
        ],
        "on": [
            "Examples:",
            "  caa on",
            "  caa on -w my-project",
            "  caa on -w my-project --interval 0.5",
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
        "cycle": [
            "Examples:",
            "  caa cycle --on -w my-project",
            "  caa cycle --once -w my-project",
            "  caa cycle --off -w my-project",
        ],
        "subagents": [
            "Examples:",
            "  caa subagents",
            "  caa subagents -w my-project",
            "  caa subagents -w my-project --json",
        ],
        "stop": [
            "Examples:",
            "  caa stop",
            "  caa stop --all",
        ],
        "history": [
            "Examples:",
            "  caa history",
            "  caa history -w my-project",
            "  caa history -n 50 --json",
            "  caa history --commands",
            "  caa history --commands -w my-project --json",
        ],
        "help": [
            "Examples:",
            "  caa help",
            "  caa help off",
        ],
        "share-safe": [
            "Examples:",
            "  caa share-safe              # toggle discreet vs branded title",
            "  caa share-safe --on         # discreet (hide autoapprove in title bar)",
            "  caa share-safe --off        # branded title again",
            "  caa share-safe -w my-project --on",
        ],
    }
    if topic in topic_examples:
        return topic_examples[topic]
    return [
        "Examples:",
        "  caa launch ~/code/my-project",
        "  caa launch ~/code/my-project --interval 5",
        "  caa launch my-project          # uses alias if set",
        "  caa launch-ssh my-devbox",
        "  caa launch-ssh my-devbox /home/user/code/project",
        "  caa alias set mp ~/code/my-project",
        "  caa alias list",
        "  caa off",
        "  caa on -w my-project --interval 0.5",
        "  caa status",
        "  caa cycle --on",
        "  caa subagents",
        "  caa stop --all",
        "  caa history -w my-project",
        "  caa history --commands",
        "  caa share-safe --on",
        "  caa help off",
        "",
        "Aliases:",
        "  - 'launch' and 'launch-ssh' auto-register the slug as an alias",
        "  - use 'caa alias set <name> <path-or-ssh-uri>' to add a custom alias",
        "  - use 'caa alias list' to see all aliases",
        "",
        "Multi-session behavior:",
        "  - 'on', 'off', 'stop', and 'share-safe' open an arrow-key picker in an interactive terminal",
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
            topics = ", ".join(sorted(command_parsers.keys()))
            print(f"Available topics: {topics}", file=sys.stderr)
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


_AUTH_KEY_PREFIX = "cursorAuth/"


def _sync_auth_tokens(profile_dir: Path) -> None:
    """Copy cursorAuth/* rows from the default profile's state.vscdb.

    This bootstraps authentication in dedicated profiles so the user
    does not have to re-login for every new workspace.  Only auth-prefixed
    keys are copied; all other per-workspace state is left untouched.
    """
    src_db = CURSOR_DEFAULT_USER_DATA / "User" / "globalStorage" / "state.vscdb"
    if not src_db.is_file():
        return

    dst_gs = profile_dir / "User" / "globalStorage"
    dst_gs.mkdir(parents=True, exist_ok=True)
    dst_db = dst_gs / "state.vscdb"

    src_conn: sqlite3.Connection | None = None
    try:
        src_conn = sqlite3.connect(f"file:{src_db}?mode=ro", uri=True)
        rows = src_conn.execute(
            "SELECT key, value FROM ItemTable WHERE key LIKE ?",
            (f"{_AUTH_KEY_PREFIX}%",),
        ).fetchall()
    except (sqlite3.Error, OSError) as exc:
        print(f"  Could not read auth tokens from default profile: {exc}")
        return
    finally:
        if src_conn:
            src_conn.close()

    if not rows:
        return

    dst_conn: sqlite3.Connection | None = None
    try:
        dst_conn = sqlite3.connect(str(dst_db))
        dst_conn.execute(
            "CREATE TABLE IF NOT EXISTS ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)"
        )
        dst_conn.executemany(
            "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
            rows,
        )
        dst_conn.commit()
        print(f"  Synced {len(rows)} auth token(s) from default profile")
    except (sqlite3.Error, OSError) as exc:
        print(f"  Could not write auth tokens to dedicated profile: {exc}")
    finally:
        if dst_conn:
            dst_conn.close()


def _sync_user_settings(profile_dir: Path) -> None:
    """Copy settings, keybindings, and auth tokens from default Cursor profile."""
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

    _sync_auth_tokens(profile_dir)


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
    ws_str = str(workspace)
    parsed = _parse_ssh_workspace(ws_str)
    if parsed:
        return _ssh_slug(parsed[0], parsed[1])
    raw = Path(workspace).name.strip() or "workspace"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-")
    return slug or "workspace"


def _window_title(workspace: str | Path, gate_on: bool) -> str:
    emoji, status = ("🟢", "multi-window") if gate_on else ("🔴", "off")
    return (
        f"{_repo_slug(workspace)} - autoapprove {emoji} {status} - "
        "active agents: 0"
    )


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


def _cdp_evaluate_ws(ws_url: str, expression: str, timeout: float = 10.0,
                     await_promise: bool = False) -> dict:
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
            "params": {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
            },
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


def _cdp_send_method(ws_url: str, method: str, params: dict | None = None,
                     timeout: float = 30.0) -> dict:
    """Send an arbitrary CDP method and return the response payload."""
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
            "id": 2,
            "method": method,
            "params": params or {},
        })
        _ws_send_text(sock, msg)
        deadline = time.time() + timeout
        while time.time() < deadline:
            payload = json.loads(_ws_recv_text(sock))
            if payload.get("id") != 2:
                continue
            if payload.get("error"):
                message = payload["error"].get("message", f"CDP {method} error")
                raise RuntimeError(message)
            return payload
    except socket.timeout as exc:
        raise RuntimeError(f"Timed out waiting for CDP {method} response") from exc
    finally:
        try:
            sock.close()
        except OSError:
            pass
    raise RuntimeError(f"Timed out waiting for CDP {method} response")


def _cdp_screenshot(port: int, target_id: str | None = None,
                    timeout: float = 30.0) -> bytes:
    """Capture a PNG screenshot of the target page via CDP Page.captureScreenshot."""
    page_targets = _cdp_list_page_targets(port, timeout=timeout)
    if not page_targets:
        raise RuntimeError(f"No page target found on CDP port {port}")
    if target_id:
        match = [t for t in page_targets if t.get("id") == target_id]
        if not match:
            raise RuntimeError(f"Bound CDP target {target_id} not found on port {port}")
        ws_url = match[0]["webSocketDebuggerUrl"]
    else:
        ws_url = page_targets[0]["webSocketDebuggerUrl"]
    payload = _cdp_send_method(ws_url, "Page.captureScreenshot",
                               {"format": "png"}, timeout=timeout)
    data_b64 = payload.get("result", {}).get("data", "")
    if not data_b64:
        raise RuntimeError("Page.captureScreenshot returned no data")
    return base64.b64decode(data_b64)


def _cdp_list_page_targets(port: int, timeout: float = 10.0) -> list[dict]:
    """List all page targets on a CDP port."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    conn.request("GET", "/json")
    resp = conn.getresponse()
    targets = json.loads(resp.read().decode("utf-8"))
    conn.close()
    return [
        t for t in targets
        if t.get("type") == "page" and t.get("webSocketDebuggerUrl")
    ]


def _is_workbench(t: dict) -> bool:
    url = (t.get("url") or "").lower()
    title = (t.get("title") or "").lower()
    return "workbench" in url or "workbench" in title


_CDP_SURFACE_MODE_EXPR = r"""(() => {
  const loaded = [
    ...Array.from(document.querySelectorAll('link[href], script[src]')).map(
      (node) => node.href || node.src || ""
    ),
    ...performance.getEntriesByType("resource").map((entry) => entry.name || ""),
  ];
  const desktopBundles = loaded.filter((url) =>
    /\/vs\/workbench\/workbench\.desktop\.main\.(css|js)(?:$|[?#])/.test(url)
  );
  const glassBundles = loaded.filter((url) =>
    /\/vs\/workbench\/workbench\.glass\.main\.(css|js)(?:$|[?#])/.test(url)
  );
  const has = (id) => !!document.querySelector(`[id="${id}"]`);
  const editor = document.querySelector('[id="workbench.parts.editor"]');
  const rect = editor?.getBoundingClientRect();
  const hasEditor = !!editor && !!rect && rect.width > 0 && rect.height > 0;
  const hasStatusbar = has("workbench.parts.statusbar");
  const hasPanel = has("workbench.parts.panel");
  const hasNavigation =
    has("workbench.parts.sidebar") ||
    has("workbench.parts.activitybar") ||
    has("workbench.parts.unifiedsidebar");
  const structuralIdeEvidence =
    hasEditor && hasStatusbar && hasPanel && hasNavigation;
  const desktopLoaded = desktopBundles.length > 0;
  const glassLoaded = glassBundles.length > 0;
  const mode =
    desktopLoaded && !glassLoaded
      ? "ide"
      : glassLoaded
        ? "agents"
        : "unknown";
  return {
    mode,
    modeEvidence:
      mode === "ide"
        ? "desktop_bundle"
        : mode === "agents"
          ? "glass_bundle"
          : "bundle_unknown",
    desktopBundles: desktopBundles.slice(0, 4),
    glassBundles: glassBundles.slice(0, 4),
    structuralIdeEvidence,
    hasEditor,
    hasStatusbar,
    hasPanel,
    hasNavigation,
    bodyClasses: String(document.body?.className || "").slice(0, 500),
    href: String(location.href || "").slice(0, 500),
  };
})()"""


def _cdp_target_surface(target: dict, timeout: float = 5.0) -> dict:
    """Classify IDE vs Agents from the target's loaded workbench bundle."""
    ws_url = target.get("webSocketDebuggerUrl")
    if not ws_url:
        return {"mode": "unknown", "reason": "missing_websocket"}
    try:
        payload = _cdp_evaluate_ws(
            ws_url, _CDP_SURFACE_MODE_EXPR, timeout=timeout,
        )
        value = payload.get("result", {}).get("result", {}).get("value")
        return value if isinstance(value, dict) else {
            "mode": "unknown",
            "reason": "invalid_surface_probe",
        }
    except (ConnectionRefusedError, OSError, RuntimeError) as exc:
        return {"mode": "unknown", "reason": str(exc)}


def _cdp_ide_targets(page_targets: list[dict], timeout: float = 5.0) -> list[dict]:
    """Return only targets loading Cursor's desktop IDE workbench bundle."""
    candidates = [target for target in page_targets if _is_workbench(target)]
    return [
        target for target in candidates
        if _cdp_target_surface(target, timeout=timeout).get("mode") == "ide"
    ]


def _cdp_bound_target_surface(port: int, target_id: str | None,
                              timeout: float = 5.0) -> dict:
    """Inspect the bound target without falling back to another page."""
    if not target_id:
        return {"mode": "unknown", "reason": "unbound_target"}
    try:
        page_targets = _cdp_list_page_targets(port, timeout=timeout)
    except (ConnectionRefusedError, OSError, RuntimeError) as exc:
        return {"mode": "unknown", "reason": str(exc)}
    matches = [target for target in page_targets if target.get("id") == target_id]
    if len(matches) != 1:
        return {"mode": "unknown", "reason": "bound_target_missing_or_ambiguous"}
    return _cdp_target_surface(matches[0], timeout=timeout)


def _cursor_ide_launch_args(cdp_port: int, profile: Path, *,
                            workspace: str | None = None,
                            folder_uri: str | None = None) -> list[str]:
    """Build explicit full-IDE launch args; standalone `--chat` is forbidden."""
    if (workspace is None) == (folder_uri is None):
        raise ValueError("exactly one of workspace or folder_uri is required")
    args = [
        f"--remote-debugging-port={cdp_port}",
        "--user-data-dir", str(profile),
        CURSOR_CLASSIC_MODE_ARG,
        CURSOR_IDE_WINDOW_ARG,
    ]
    if workspace is not None:
        args.append(workspace)
    else:
        args.extend(["--folder-uri", str(folder_uri)])
    return args


def _cursor_classic_mode_support(timeout: float = 5.0) -> tuple[bool, str]:
    """Require Cursor's version-coupled full-IDE forcing flag before launch."""
    if not CURSOR_CLI.is_file():
        return False, f"Cursor CLI not found at {CURSOR_CLI}"
    try:
        completed = subprocess.run(
            [str(CURSOR_CLI), "--help"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"could not inspect Cursor CLI help: {exc}"
    help_text = completed.stdout or ""
    if completed.returncode != 0:
        return False, f"Cursor CLI help exited {completed.returncode}"
    if CURSOR_CLASSIC_MODE_ARG not in help_text:
        return False, (
            f"Cursor CLI no longer advertises {CURSOR_CLASSIC_MODE_ARG}; "
            "refusing to guess the IDE-mode launch contract"
        )
    return True, "classic_mode_supported"


def _cdp_select_workbench_target(port: int, timeout: float = 10.0) -> dict:
    """Select exactly one full IDE target and return its /json metadata.

    Used at launch time to pick the initial target for pinning.
    """
    page_targets = _cdp_list_page_targets(port, timeout=timeout)
    if not page_targets:
        raise RuntimeError(f"No page target found on CDP port {port}")
    ide_targets = _cdp_ide_targets(page_targets, timeout=min(timeout, 5.0))
    if len(ide_targets) == 1:
        return ide_targets[0]
    if len(ide_targets) > 1:
        raise RuntimeError(
            f"Found {len(ide_targets)} IDE targets on CDP port {port}; "
            "refusing to bind ambiguously"
        )
    modes = [
        {
            "id": target.get("id"),
            **_cdp_target_surface(target, timeout=min(timeout, 5.0)),
        }
        for target in page_targets
        if _is_workbench(target)
    ]
    raise RuntimeError(
        "No full IDE target found; Cursor may have opened an Agents window "
        f"instead. Surface probes: {modes}"
    )


def _cdp_evaluate(port: int, expression: str, timeout: float = 10.0,
                  target_id: str | None = None,
                  await_promise: bool = False) -> dict:
    """Evaluate JS in a page target via CDP websocket.

    When target_id is set, only that specific target is used (pinned mode).
    When target_id is None, falls back to workbench-first heuristic.
    """
    page_targets = _cdp_list_page_targets(port, timeout=timeout)
    if not page_targets:
        raise RuntimeError(f"No page target found on CDP port {port}")

    if target_id:
        match = [t for t in page_targets if t.get("id") == target_id]
        if not match:
            available_ids = [t.get("id") for t in page_targets]
            raise RuntimeError(
                f"Bound CDP target {target_id} not found on port {port}. "
                f"Available targets: {available_ids}"
            )
        return _cdp_evaluate_ws(
            match[0]["webSocketDebuggerUrl"],
            expression,
            timeout=timeout,
            await_promise=await_promise,
        )

    preferred = [t for t in page_targets if _is_workbench(t)]
    ordered = preferred + [t for t in page_targets if t not in preferred]

    last_error: RuntimeError | None = None
    for t in ordered:
        try:
            return _cdp_evaluate_ws(
                t["webSocketDebuggerUrl"],
                expression,
                timeout=timeout,
                await_promise=await_promise,
            )
        except RuntimeError as exc:
            last_error = exc
            continue
    raise RuntimeError(
        f"No usable page target on CDP port {port}: {last_error or 'unknown error'}"
    )


def _format_injector_hash(script_hash: str | None) -> str:
    return script_hash or "unknown"


def _cdp_inject(port: int, auto_start: bool = True, force_reload: bool = False,
                 repo_slug: str = "workspace",
                 workspace: str | None = None,
                 target_id: str | None = None,
                 interval_seconds: float | None = None) -> tuple[bool, str | None]:
    """Inject the DOM auto-accept script via CDP.

    Returns (success, target_id_used). On first inject target_id may be None;
    the function will select a workbench target and return its id for pinning.
    """
    js_path = _dom_injector_path()
    if not js_path.exists():
        print(f"DOM injector not found at {js_path}", file=sys.stderr)
        return False, None

    base_script, _script_hash, script_path = _load_dom_injector_script()

    pinned_id = target_id
    for attempt in range(CDP_INJECT_RETRIES):
        try:
            if not pinned_id:
                chosen = _cdp_select_workbench_target(port, timeout=10.0)
                pinned_id = chosen.get("id")
            surface = _cdp_bound_target_surface(port, pinned_id, timeout=5.0)
            if surface.get("mode") != "ide":
                raise RuntimeError(
                    "Refusing to inject outside a verified IDE workbench "
                    f"(target={pinned_id}, surface={surface})"
                )
            preamble = (
                f"globalThis.__cursorAutoAcceptRepoSlug = {json.dumps(repo_slug)};\n"
                f"globalThis.__cursorAutoAcceptWorkspace = "
                f"{json.dumps(workspace or repo_slug)};\n"
                f"globalThis.__cursorAutoAcceptTargetId = {json.dumps(pinned_id)};\n"
            )
            script = preamble + base_script
            if force_reload:
                script = _clear_injector_expression() + "\n" + script
            if auto_start:
                script += f"\n; {_start_accept_expr(interval_seconds)};"
            result = _cdp_evaluate(port, script, timeout=10.0, target_id=pinned_id)
            exc = result.get("result", {}).get("exceptionDetails")
            if exc:
                print(f"DOM injection error: {exc.get('text', '')}", file=sys.stderr)
                return False, pinned_id
            print(f"Injected script from {script_path}")
            return True, pinned_id
        except (ConnectionRefusedError, OSError, RuntimeError) as exc:
            if attempt < CDP_INJECT_RETRIES - 1:
                time.sleep(2 * (attempt + 1))
            else:
                print(f"CDP injection target check failed: {exc}", file=sys.stderr)
                return False, pinned_id
    return False, pinned_id


def _cdp_title(port: int, target_id: str | None = None) -> str | None:
    try:
        result = _cdp_evaluate(
            port,
            """
(() => {
  const titleButton = document.querySelector('[id="workbench.parts.titlebar"] .window-title-text');
  return titleButton?.textContent || document.title;
})()
""".strip(),
            target_id=target_id,
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


def _cdp_gate(port: int, action: str, title: str | None = None,
              target_id: str | None = None, *,
              share_safe: bool = False,
              interval_seconds: float | None = None) -> dict | None:
    """Call startAccept/stopAccept/acceptStatus via CDP. Returns parsed status or None."""
    if action == "on":
        start_expr = _start_accept_expr(interval_seconds)
        if share_safe:
            expr = f"setShareSafeTitle(true); {start_expr}; JSON.stringify(acceptStatus())"
        else:
            title_expr = _title_sync_expr(title) if title else ""
            expr = f"{title_expr} {start_expr}; JSON.stringify(acceptStatus())"
    elif action == "off":
        if share_safe:
            expr = "setShareSafeTitle(true); stopAccept(); JSON.stringify(acceptStatus())"
        else:
            title_expr = _title_sync_expr(title) if title else ""
            expr = f"{title_expr} stopAccept(); JSON.stringify(acceptStatus())"
    elif action == "status":
        expr = "JSON.stringify(acceptStatus())"
    else:
        return None

    try:
        result = _cdp_evaluate(port, expr, target_id=target_id)
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


def _rebind_session_target_if_unique(session: dict) -> tuple[str | None, bool]:
    """Rebind a lost renderer target only when one verified IDE target exists."""
    port = session.get("cdp_port")
    bound_target = session.get("cdp_target_id")
    if not port:
        return bound_target, False
    try:
        page_targets = _cdp_list_page_targets(port, timeout=5.0)
    except (ConnectionRefusedError, OSError, RuntimeError):
        return bound_target, False
    if bound_target and any(target.get("id") == bound_target for target in page_targets):
        return bound_target, False
    ide_targets = _cdp_ide_targets(page_targets)
    if len(ide_targets) != 1:
        return bound_target, False
    replacement = ide_targets[0].get("id")
    if not replacement:
        return bound_target, False

    old_target = bound_target
    workspace = session.get("workspace")
    session["cdp_target_id"] = replacement
    state_data = _load_state(gc=False)
    if workspace in state_data.get("sessions", {}):
        state_data["sessions"][workspace]["cdp_target_id"] = replacement
        _save_state(state_data)
    print(
        "Renderer target changed after a reload/reopen; "
        f"rebinding {old_target or 'unbound'} -> {replacement}."
    )
    return replacement, True


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
        if workspace_arg in sessions:
            return sessions[workspace_arg]

        is_ssh = _is_ssh_workspace(workspace_arg)
        workspace_path = Path(workspace_arg).expanduser() if not is_ssh else None
        path_like = not is_ssh and (
            workspace_arg.startswith(("~", ".", "..")) or
            os.sep in workspace_arg or
            (workspace_path is not None and workspace_path.exists())
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
        if workspace_path is not None:
            resolved = str(workspace_path.resolve())
            if resolved in sessions:
                return sessions[resolved]
        if not path_like:
            alias_target = _get_alias(workspace_arg)
            if alias_target and alias_target in sessions:
                return sessions[alias_target]
        session_label = "active session" if require_alive else "matching session"
        print(f"No {session_label} for '{workspace_arg}'.", file=diag_stream)
        if sessions:
            _print_session_choices(sessions)
        return None

    if len(sessions) == 1:
        return next(iter(sessions.values()))

    if not sessions:
        print("No active sessions. Run 'launch' or 'launch-ssh' first.", file=diag_stream)
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


def _format_tray_status(tray: dict) -> str:
    """Format current and legacy tray telemetry consistently."""
    advertised = tray.get("advertised", tray.get("running", 0))
    mounted = tray.get("mounted", tray.get("running", 0))
    headers = tray.get("headers", 0)
    collapsed = tray.get("collapsed", 0)
    unknown = tray.get("unknown", 0)
    return (
        "Tray:      "
        f"{advertised} advertised, "
        f"{mounted} mounted, "
        f"{tray.get('running', 0)} eligible, "
        f"{collapsed}/{headers} collapsed, "
        f"{unknown} unknown, "
        f"{tray.get('visits', 0)} visits, "
        f"{tray.get('attempts', 0)} attempts, "
        f"{tray.get('confirmed', 0)} confirmed, "
        f"{tray.get('failed', 0)} failed"
    )


def _print_session_status(session: dict) -> None:
    """Print status for a single session with target-level diagnostics."""
    pid = session.get("pid")
    port = session.get("cdp_port")
    workspace = session.get("workspace", "unknown")
    slug = session.get("slug", _repo_slug(workspace))
    bound_target = session.get("cdp_target_id")
    alive = _pid_is_alive(pid) if pid else False

    print(f"Session:   {slug}")
    print(f"PID:       {pid or 'none'} ({'running' if alive else 'stopped'})")
    print(f"CDP port:  {port or 'none'}")
    print(f"Workspace: {workspace}")
    if session.get("kind") == "ssh":
        print(f"SSH Host:  {session.get('ssh_host', '?')}")
        rp = session.get("remote_path", "/")
        if rp and rp != "/":
            print(f"Remote:    {rp}")
    print(f"Launched:  {session.get('launched_at', 'unknown')}")
    if bound_target:
        print(f"Target:    {bound_target}")

    if alive and port:
        target_count = 0
        target_warning = ""
        target_surface: dict = {"mode": "unknown"}
        try:
            page_targets = _cdp_list_page_targets(port, timeout=5.0)
            target_count = len(page_targets)
            wb_targets = [t for t in page_targets if _is_workbench(t)]
            if len(wb_targets) > 1:
                target_warning = (
                    f"  WARNING: {len(wb_targets)} workbench targets on port {port}. "
                    "Extra windows in this dedicated process may receive wrong signals."
                )
            if bound_target:
                matches = [
                    target for target in page_targets
                    if target.get("id") == bound_target
                ]
                if len(matches) != 1:
                    target_warning = (
                        f"  WARNING: Bound target {bound_target} not found among "
                        f"{target_count} page target(s). Session needs rebinding (run 'on')."
                    )
                else:
                    target_surface = _cdp_target_surface(matches[0], timeout=5.0)
                    if target_surface.get("mode") != "ide":
                        target_warning = (
                            "  WARNING: Bound target is not a verified full IDE "
                            f"surface ({target_surface.get('mode', 'unknown')}). "
                            "Keep the gate OFF and relaunch the workspace."
                        )
        except (ConnectionRefusedError, OSError, RuntimeError):
            pass

        if target_count:
            print(f"Targets:   {target_count} page target(s) on port")
        mode = target_surface.get("mode", "unknown")
        print(f"Mode:      {'IDE (verified)' if mode == 'ide' else mode}")

        drained = _drain_injector_events(port, bound_target, workspace, slug)
        registry = _sync_subagent_registry(port, bound_target, workspace, slug)

        gate = _cdp_gate(port, "status", target_id=bound_target)
        if gate:
            running = gate.get("running", False)
            clicks = gate.get("totalClicks", 0)
            label = "ON" if running else "OFF"
            title = _cdp_title(port, target_id=bound_target)
            print(f"Gate:      {label}")
            interval_ms = gate.get("interval")
            if isinstance(interval_ms, (int, float)):
                print(f"Poll:      {interval_ms / 1000:g}s fallback interval")
            print(f"Clicks:    {clicks}")
            if isinstance(gate.get("totalClickAttempts"), int):
                print(f"Attempts:  {gate['totalClickAttempts']}")
            if isinstance(gate.get("directRegisteredAttempts"), int):
                print(
                    "DirectCaps:"
                    f" {gate['directRegisteredAttempts']} registered prompt(s)"
                )
            if isinstance(gate.get("totalConfirmedApprovals"), int):
                print(f"Confirmed: {gate['totalConfirmedApprovals']}")
            if isinstance(gate.get("lastScanDurationMs"), (int, float)):
                print(
                    f"Scan:      {gate['lastScanDurationMs']:g}ms last, "
                    f"{gate.get('maxScanDurationMs', 0):g}ms max "
                    f"({gate.get('totalScans', 0)} total)"
                )
            if isinstance(gate.get("usedJSHeapBytes"), (int, float)):
                heap_label = f"{gate['usedJSHeapBytes'] / (1024 * 1024):.1f} MiB"
                if isinstance(gate.get("maxJSHeapBytes"), (int, float)):
                    heap_label += (
                        f" / {gate['maxJSHeapBytes'] / (1024 * 1024):.1f} MiB limit"
                    )
                print(f"JS Heap:   {heap_label}")
            if gate.get("safetyTrip"):
                print(f"  SAFETY:  {json.dumps(gate['safetyTrip'])}")
            cycle_label = "ON" if gate.get("cycleEnabled") else "OFF"
            if gate.get("cycleActive"):
                cycle_label += " (running)"
            print(f"Cycle:     {cycle_label}")
            focus_label = str(gate.get("activeFocusKind") or "unknown")
            if gate.get("cycleFocusBlockReason"):
                focus_label += f" (cycle paused: {gate['cycleFocusBlockReason']})"
            print(f"Focus:     {focus_label}")
            if isinstance(gate.get("lastFocusRestore"), dict):
                focus_restore = gate["lastFocusRestore"]
                print(
                    "FocusLast: "
                    f"{focus_restore.get('outcome', 'unknown')} "
                    f"{focus_restore.get('targetKind', 'unknown')} "
                    f"({focus_restore.get('phase', 'unknown')})"
                )
            counts = (
                registry.get("counts", {})
                if isinstance(registry, dict)
                else gate.get("subagentCounts", {})
            )
            if isinstance(counts, dict):
                print(
                    "Subagents: "
                    f"{counts.get('active', 0)} active, "
                    f"{counts.get('waiting', 0)} waiting, "
                    f"{counts.get('completed', 0)} completed, "
                    f"{counts.get('failed', 0)} failed"
                )
            tray = (
                registry.get("tray", {})
                if isinstance(registry, dict)
                else gate.get("subagentTray", {})
            )
            if isinstance(tray, dict):
                print(_format_tray_status(tray))
            pinned = (
                registry.get("pinned", {})
                if isinstance(registry, dict)
                else gate.get("pinnedAgents", {})
            )
            if isinstance(pinned, dict):
                print(
                    "Pinned:    "
                    f"{pinned.get('active', 0)}/{pinned.get('total', 0)} active, "
                    f"{pinned.get('ambiguous', 0)} ambiguous, "
                    f"{pinned.get('visits', 0)} visits, "
                    f"{pinned.get('attempts', 0)} attempts, "
                    f"{pinned.get('confirmed', 0)} confirmed, "
                    f"{pinned.get('failed', 0)} failed"
                )
                if isinstance(pinned.get("lastRestore"), dict):
                    restore = pinned["lastRestore"]
                    print(
                        "PinnedLast:"
                        f" {restore.get('reason', 'unknown')} "
                        f"({restore.get('ts', '-')})"
                    )
            last_cycle = (
                registry.get("lastCycle")
                if isinstance(registry, dict)
                else gate.get("lastCycle")
            )
            if isinstance(last_cycle, dict) and last_cycle.get("ts"):
                aborted = (
                    f"; aborted={last_cycle['abortedReason']}"
                    if last_cycle.get("abortedReason")
                    else ""
                )
                print(
                    f"LastCycle: {last_cycle.get('ts')} "
                    f"({last_cycle.get('rows', 0)} rows, "
                    f"{last_cycle.get('confirmed', 0)} confirmed, "
                    f"{last_cycle.get('failed', 0)} failed; "
                    f"{last_cycle.get('trayVisits', 0)} tray visits, "
                    f"{last_cycle.get('trayConfirmed', 0)} tray confirmed; "
                    f"{last_cycle.get('pinnedVisits', 0)} pinned visits, "
                    f"{last_cycle.get('pinnedConfirmed', 0)} pinned confirmed"
                    f"{aborted})"
                )
            if "shareSafeTitle" in gate:
                tmode = "discreet" if gate.get("shareSafeTitle") else "branded"
                print(f"Title:     {tmode}")
            if gate.get("bannerState"):
                mode_reason = gate.get("bannerModeReason")
                if mode_reason is None:
                    mode_reason = gate.get("bannerPauseReason")
                reason_suffix = (
                    f" ({mode_reason})"
                    if mode_reason
                    else ""
                )
                print(
                    "Banner:    "
                    f"{str(gate['bannerState']).upper()}{reason_suffix}, "
                    f"{gate.get('activeAgentWindows', 0)} active agents"
                )
            dialog_roots = gate.get("dialogRoots")
            if isinstance(dialog_roots, dict):
                print(
                    "Dialogs:   "
                    f"{dialog_roots.get('blocking', 0)} blocking, "
                    f"{dialog_roots.get('ignoredNonModal', 0)} ignored non-modal"
                )
            print(f"Injector:  {_format_injector_hash(gate.get('scriptHash'))}")
            expected_hash: str | None = None
            try:
                _, expected_hash, _ = _load_dom_injector_script()
            except OSError:
                pass
            in_window = gate.get("scriptHash")
            if expected_hash and in_window and in_window != expected_hash:
                print(f"  DRIFT:   in-window={in_window}, on-disk={expected_hash} (run 'on' to reload)")
            if title:
                print(f"Window:    {title}")
            recent = gate.get("recentClicks", [])
            if recent:
                print(f"Recent:    {json.dumps(recent[-3:])}")
                for click in reversed(recent):
                    cmd_preview = click.get("commandPreview")
                    if cmd_preview:
                        cmd_lines = click.get("commandLines", 1)
                        cmd_ts = click.get("ts", "")[:19]
                        suffix = f" ({cmd_lines} lines)" if cmd_lines and cmd_lines > 1 else ""
                        print(f"LastCmd:   {cmd_preview}{suffix}")
                        break
        else:
            print("Gate:      unknown (CDP or injector status unavailable)")

        if drained:
            click_events = [e for e in drained if e.get("record_type") == "click"]
            unknown_events = [e for e in drained if e.get("record_type") == "unknown_prompt"]
            blocked_events = [e for e in drained if e.get("record_type") == "blocked_candidate"]
            if click_events:
                print(f"Drained:   {len(click_events)} click event(s) persisted to history")
            if unknown_events:
                last_unknown = unknown_events[-1]
                print(f"  UNKNOWN: Last unknown prompt: {last_unknown.get('text', '?')[:60]}")
            if blocked_events:
                print(f"  BLOCKED: {len(blocked_events)} blocked candidate(s) captured")

        if target_warning:
            print(target_warning)
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
            share_safe = bool(session.get("share_safe_title"))
            _cdp_gate(
                port,
                "off",
                title=disabled_title,
                target_id=session.get("cdp_target_id"),
                share_safe=share_safe,
            )
        _log_event("session", workspace, slug, action="stop", pid=pid)
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
# Workspace resolution
# ---------------------------------------------------------------------------


def _resolve_workspace_for_launch(raw: str | None) -> Path | str | None:
    """Resolve a user-supplied launch argument to a local directory or SSH URI.

    Resolution order:
    1. If *raw* is None, use CWD.
    2. If *raw* is a Remote SSH folder URI, use it.
    3. Expand ~ and resolve to an absolute path. If it is an existing
       directory, use it.
    4. Treat *raw* as an alias name from config.json. Aliases may point to
       local directories or Remote SSH folder URIs.
    5. Return None if nothing matches (caller should error).
    """
    if raw is None:
        return Path.cwd()

    if _is_ssh_workspace(raw):
        return raw

    candidate = Path(raw).expanduser().resolve()
    if candidate.is_dir():
        return candidate

    looks_like_path = (
        raw.startswith(("~", ".", ".."))
        or os.sep in raw
    )
    if not looks_like_path:
        alias_target = _get_alias(raw)
        if alias_target:
            if _is_ssh_workspace(alias_target):
                return alias_target
            p = Path(alias_target)
            if p.is_dir():
                return p

    return None


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_launch(args: argparse.Namespace) -> int:
    state = _load_state()
    sessions = state.get("sessions", {})
    interval_seconds = _session_poll_interval(
        {}, getattr(args, "interval", None)
    )

    workspace = _resolve_workspace_for_launch(args.workspace)
    if workspace is None:
        print(f"Workspace '{args.workspace}' is not a valid directory or alias.", file=sys.stderr)
        aliases = _list_aliases()
        if aliases:
            print("Known aliases:", file=sys.stderr)
            for name, path in sorted(aliases.items()):
                print(f"  {name:20s} {path}", file=sys.stderr)
        print("Pass a concrete path, SSH folder URI, or set an alias with: caa alias set <name> <path-or-ssh-uri>",
              file=sys.stderr)
        return 1

    if isinstance(workspace, str) and _is_ssh_workspace(workspace):
        parsed = _parse_ssh_workspace(workspace)
        if parsed is None:
            print(f"SSH workspace URI is malformed: {workspace}", file=sys.stderr)
            return 1
        host, remote_path = parsed
        return cmd_launch_ssh(argparse.Namespace(
            ssh_host=host,
            remote_path=remote_path,
            no_preflight=False,
            interval=interval_seconds,
        ))

    classic_supported, classic_reason = _cursor_classic_mode_support()
    if not classic_supported:
        print(
            f"Cannot launch a verified IDE window: {classic_reason}",
            file=sys.stderr,
        )
        return 1

    ws_key = str(workspace)
    slug = _repo_slug(workspace)
    enabled_title = _window_title(workspace, gate_on=True)

    for warn in _check_stale_hooks(workspace):
        print(warn, file=sys.stderr)

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
        CURSOR_CLASSIC_MODE_ARG,
    ]
    ide_args = _cursor_ide_launch_args(
        cdp_port, profile, workspace=str(workspace),
    )

    command = [
        "open", "-na", str(CURSOR_APP_PATH), "--args",
        *ide_args,
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
            [str(CURSOR_EXECUTABLE), *ide_args],
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
        "poll_interval_seconds": interval_seconds,
    }
    state["sessions"] = sessions
    _save_state(state)
    _auto_register_alias(workspace)

    print(f"Cursor started (PID {pid}). Waiting for CDP to become ready...")
    time.sleep(CDP_INJECT_DELAY)

    inject_ok, pinned_target = _cdp_inject(
        cdp_port, auto_start=False, force_reload=True, repo_slug=slug,
        workspace=ws_key,
    )
    if inject_ok and pinned_target:
        sessions[ws_key]["cdp_target_id"] = pinned_target
        _save_state(state)

    _log_event("session", ws_key, slug, action="launch", pid=pid,
               cdp_port=cdp_port, cdp_target_id=pinned_target,
               poll_interval_seconds=interval_seconds)

    if inject_ok:
        result = _cdp_gate(cdp_port, "on", title=enabled_title,
                           target_id=pinned_target,
                           interval_seconds=interval_seconds)
        print("\nAuto-approve ON.")
        print("Mode: IDE (verified)")
        print(f"Fallback poll interval: {interval_seconds:g}s")
        print(f"Window title target: {result.get('bannerTitle', enabled_title)}")
        if pinned_target:
            print(f"Bound target: {pinned_target}")
        if result and result.get("scriptHash"):
            print(f"Injector hash: {result['scriptHash']}")
        _log_event("gate", ws_key, slug, action="on",
                   cdp_target_id=pinned_target,
                   poll_interval_seconds=interval_seconds)
    else:
        surface = (
            _cdp_bound_target_surface(cdp_port, pinned_target, timeout=5.0)
            if pinned_target
            else {"mode": "unknown"}
        )
        if surface.get("mode") != "ide":
            _terminate_pid(pid)
            _remove_session(ws_key)
            print(
                "\nCursor did not open a verified IDE workbench. The dedicated "
                "process was closed instead of enabling auto-approve in an "
                f"Agents/incomplete window (surface={surface}).",
                file=sys.stderr,
            )
            return 1
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


def cmd_launch_ssh(args: argparse.Namespace) -> int:
    """Launch a dedicated Cursor window connected to an SSH remote host."""
    state = _load_state()
    sessions = state.get("sessions", {})
    interval_seconds = _session_poll_interval(
        {}, getattr(args, "interval", None)
    )

    host = args.ssh_host
    remote_path = getattr(args, "remote_path", None) or "/"
    if not remote_path.startswith("/"):
        print(
            "Remote path must be absolute (for example: /home/user/code/project).",
            file=sys.stderr,
        )
        return 1
    if remote_path != "/" and not getattr(args, "no_preflight", False):
        preflight_ok, preflight_error = _verify_ssh_remote_path(host, remote_path)
        if not preflight_ok:
            print(preflight_error, file=sys.stderr)
            print(
                "\nNo Cursor window was launched, so no dedicated profile or alias "
                "was created. Use --no-preflight only if you want Cursor Remote SSH "
                "to handle this check itself.",
                file=sys.stderr,
            )
            return 1
    classic_supported, classic_reason = _cursor_classic_mode_support()
    if not classic_supported:
        print(
            f"Cannot launch a verified IDE window: {classic_reason}",
            file=sys.stderr,
        )
        return 1
    folder_uri = _ssh_folder_uri(host, remote_path)
    ws_key = folder_uri
    slug = _ssh_slug(host, remote_path)
    enabled_title = _window_title(ws_key, gate_on=True)

    for warn in _check_stale_hooks():
        print(warn, file=sys.stderr)

    existing = sessions.get(ws_key)
    if existing and existing.get("pid") and _pid_is_alive(existing["pid"]):
        print(f"A dedicated Cursor is already running for {slug} (PID {existing['pid']}).")
        print("Use 'on'/'off' to toggle, or 'stop -w' first to relaunch.")
        return 1

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
        CURSOR_CLASSIC_MODE_ARG,
    ]
    ide_args = _cursor_ide_launch_args(
        cdp_port, profile, folder_uri=folder_uri,
    )

    command = [
        "open", "-na", str(CURSOR_APP_PATH), "--args",
        *ide_args,
    ]
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    display_path = remote_path if remote_path != "/" else ""
    print(f"Launching dedicated Cursor for ssh://{host}{display_path} (CDP port {cdp_port})...")

    try:
        pid = _wait_for_new_pid(existing_pids, LAUNCH_TIMEOUT, required_args=required_args)
    except RuntimeError:
        print("Falling back to direct executable launch...")
        subprocess.Popen(
            [str(CURSOR_EXECUTABLE), *ide_args],
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
        "kind": "ssh",
        "ssh_host": host,
        "remote_path": remote_path,
        "launched_at": datetime.now(timezone.utc).isoformat(),
        "poll_interval_seconds": interval_seconds,
    }
    state["sessions"] = sessions
    _save_state(state)
    _auto_register_alias(ws_key)

    print(f"Cursor started (PID {pid}). Waiting for CDP to become ready...")
    time.sleep(CDP_INJECT_DELAY)

    inject_ok, pinned_target = _cdp_inject(
        cdp_port, auto_start=False, force_reload=True, repo_slug=slug,
        workspace=ws_key,
    )
    if inject_ok and pinned_target:
        sessions[ws_key]["cdp_target_id"] = pinned_target
        _save_state(state)

    _log_event("session", ws_key, slug, action="launch", pid=pid,
               cdp_port=cdp_port, cdp_target_id=pinned_target, kind="ssh",
               ssh_host=host, remote_path=remote_path,
               poll_interval_seconds=interval_seconds)

    if inject_ok:
        result = _cdp_gate(cdp_port, "on", title=enabled_title,
                           target_id=pinned_target,
                           interval_seconds=interval_seconds)
        print("\nAuto-approve ON.")
        print("Mode: IDE (verified)")
        print(f"Fallback poll interval: {interval_seconds:g}s")
        print(f"Window title target: {result.get('bannerTitle', enabled_title)}")
        if pinned_target:
            print(f"Bound target: {pinned_target}")
        if result and result.get("scriptHash"):
            print(f"Injector hash: {result['scriptHash']}")
        _log_event("gate", ws_key, slug, action="on",
                   cdp_target_id=pinned_target,
                   poll_interval_seconds=interval_seconds)
    else:
        surface = (
            _cdp_bound_target_surface(cdp_port, pinned_target, timeout=5.0)
            if pinned_target
            else {"mode": "unknown"}
        )
        if surface.get("mode") != "ide":
            _terminate_pid(pid)
            _remove_session(ws_key)
            print(
                "\nCursor did not open a verified IDE workbench. The dedicated "
                "process was closed instead of enabling auto-approve in an "
                f"Agents/incomplete window (surface={surface}).",
                file=sys.stderr,
            )
            return 1
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
    slug = session.get("slug", _repo_slug(workspace))
    bound_target = session.get("cdp_target_id")
    enabled_title = _window_title(workspace, gate_on=True)
    interval_seconds = _session_poll_interval(
        session, getattr(args, "interval", None)
    )

    if not _pid_is_alive(pid):
        print(f"Dedicated Cursor (PID {pid}) is no longer running.", file=sys.stderr)
        return 1

    bound_target, _ = _rebind_session_target_if_unique(session)
    try:
        surface = _cdp_bound_target_surface(port, bound_target, timeout=5.0)
    except (ConnectionRefusedError, OSError, RuntimeError) as exc:
        print(f"Could not verify IDE mode: {exc}", file=sys.stderr)
        return 1
    if surface.get("mode") != "ide":
        print(
            "Refusing to enable auto-approve outside a verified IDE workbench "
            f"(surface={surface}). Relaunch the workspace with 'caa launch'.",
            file=sys.stderr,
        )
        return 1
    check = _cdp_gate(port, "status", target_id=bound_target)
    expected_hash: str | None = None
    expected_path: Path | None = None
    try:
        _, expected_hash, expected_path = _load_dom_injector_script()
    except OSError:
        pass

    current_hash = check.get("scriptHash") if isinstance(check, dict) else None
    needs_reload = check is None or (expected_hash is not None and current_hash != expected_hash)
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
        inject_ok, new_target = _cdp_inject(
            port, auto_start=False, force_reload=True, repo_slug=slug,
            workspace=workspace,
            target_id=bound_target,
        )
        if not inject_ok:
            print("Injection failed.", file=sys.stderr)
            return 1
        if new_target and new_target != bound_target:
            bound_target = new_target
            session["cdp_target_id"] = bound_target
            state_data = _load_state()
            ws_key = session["workspace"]
            if ws_key in state_data["sessions"]:
                state_data["sessions"][ws_key]["cdp_target_id"] = bound_target
                _save_state(state_data)

    share_safe = bool(session.get("share_safe_title"))
    result = _cdp_gate(
        port,
        "on",
        title=enabled_title,
        target_id=bound_target,
        share_safe=share_safe,
        interval_seconds=interval_seconds,
    )
    if result:
        print(f"Auto-approve ON (total clicks so far: {result.get('totalClicks', 0)})")
        print("Mode: IDE (verified)")
        print(f"Fallback poll interval: {interval_seconds:g}s")
        if share_safe:
            print("Window title: discreet (screen-share safe; captured at inject time)")
        else:
            print(f"Window title target: {result.get('bannerTitle', enabled_title)}")
        if bound_target:
            print(f"Bound target: {bound_target}")
        if result.get("scriptHash"):
            print(f"Injector hash: {result['scriptHash']}")
        current_state = _load_state()
        if workspace in current_state.get("sessions", {}):
            current_state["sessions"][workspace]["poll_interval_seconds"] = interval_seconds
            _save_state(current_state)
        _log_event("gate", workspace, slug, action="on",
                   cdp_target_id=bound_target,
                   poll_interval_seconds=interval_seconds)
        _drain_injector_events(port, bound_target, workspace, slug)
        _sync_subagent_registry(port, bound_target, workspace, slug)
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
    slug = session.get("slug", _repo_slug(workspace))
    bound_target = session.get("cdp_target_id")
    disabled_title = _window_title(workspace, gate_on=False)

    if not _pid_is_alive(pid):
        print(f"Dedicated Cursor (PID {pid}) is no longer running.", file=sys.stderr)
        return 1

    bound_target, _ = _rebind_session_target_if_unique(session)
    share_safe = bool(session.get("share_safe_title"))
    result = _cdp_gate(
        port,
        "off",
        title=disabled_title,
        target_id=bound_target,
        share_safe=share_safe,
    )
    if result:
        print(f"Auto-approve OFF (total clicks: {result.get('totalClicks', 0)})")
        if share_safe:
            print("Window title: discreet (screen-share safe; captured at inject time)")
        else:
            print(f"Window title target: {result.get('bannerTitle', disabled_title)}")
        _log_event("gate", workspace, slug, action="off",
                   cdp_target_id=bound_target)
        _drain_injector_events(port, bound_target, workspace, slug)
        _sync_subagent_registry(port, bound_target, workspace, slug)
    else:
        print("Failed to stop auto-approve.", file=sys.stderr)
        return 1
    return 0


def _cdp_json_expression(port: int, expression: str, target_id: str | None,
                         *, timeout: float = 30.0,
                         await_promise: bool = False) -> dict | None:
    try:
        result = _cdp_evaluate(
            port,
            expression,
            target_id=target_id,
            timeout=timeout,
            await_promise=await_promise,
        )
        exception = result.get("result", {}).get("exceptionDetails")
        if exception:
            description = exception.get("exception", {}).get("description")
            raise RuntimeError(description or exception.get("text", "JavaScript error"))
        raw = result.get("result", {}).get("result", {}).get("value")
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return parsed if isinstance(parsed, dict) else None
    except (ConnectionRefusedError, OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"CDP error: {exc}", file=sys.stderr)
        return None


def cmd_cycle(args: argparse.Namespace) -> int:
    """Enable, disable, or explicitly run bounded agent approval cycling."""
    state = _load_state()
    session = _resolve_session(
        args, state, allow_interactive=True, command_name="cycle",
    )
    if not session:
        return 1

    port = session["cdp_port"]
    workspace = session["workspace"]
    slug = session.get("slug", _repo_slug(workspace))
    target, _ = _rebind_session_target_if_unique(session)
    mode = args.cycle_mode
    try:
        surface = _cdp_bound_target_surface(port, target, timeout=5.0)
    except (ConnectionRefusedError, OSError, RuntimeError) as exc:
        print(f"Could not verify IDE mode: {exc}", file=sys.stderr)
        return 1
    if surface.get("mode") != "ide":
        print(
            "Refusing to cycle outside a verified IDE workbench "
            f"(surface={surface}). Relaunch the workspace with 'caa launch'.",
            file=sys.stderr,
        )
        return 1

    if mode == "once":
        expression = (
            "(async () => JSON.stringify("
            "await runSubagentCycle({explicit: true})"
            "))()"
        )
        result = _cdp_json_expression(
            port,
            expression,
            target,
            timeout=180.0,
            await_promise=True,
        )
    else:
        enabled = mode == "on"
        literal = "true" if enabled else "false"
        expression = (
            "typeof setSubagentCycle === 'function' "
            f"? JSON.stringify(setSubagentCycle({literal})) : null"
        )
        result = _cdp_json_expression(port, expression, target)

    if result is None:
        print(
            "Agent cycling API is unavailable. Reinstall globally and run "
            "'caa on' to reload the injector.",
            file=sys.stderr,
        )
        return 1

    drained = _drain_injector_events(port, target, workspace, slug)
    snapshot = _sync_subagent_registry(port, target, workspace, slug)
    if mode == "once":
        if result.get("ok"):
            print(
                f"[{slug}] Cycle finished: {result.get('rows', 0)} row(s), "
                f"{result.get('confirmed', 0)} confirmed, "
                f"{result.get('failed', 0)} failed, "
                f"{result.get('misses', 0)} missed; "
                f"{result.get('trayVisits', 0)} tray visit(s), "
                f"{result.get('trayConfirmed', 0)} confirmed; "
                f"{result.get('pinnedVisits', 0)} pinned visit(s), "
                f"{result.get('pinnedConfirmed', 0)} confirmed."
            )
        else:
            print(f"[{slug}] Cycle did not run: {result.get('reason', 'unknown')}")
            return 1
    else:
        print(f"[{slug}] Agent approval cycling {'ON' if mode == 'on' else 'OFF'}.")
        if mode == "on" and not result.get("cycleActive"):
            print("  The scheduler will run while the main auto-approve gate is ON.")
    if drained:
        print(f"  Persisted {len(drained)} cycle/event record(s).")
    if isinstance(snapshot, dict):
        counts = snapshot.get("counts", {})
        print(
            f"  Registry: {counts.get('active', 0)} active, "
            f"{counts.get('waiting', 0)} waiting, "
            f"{counts.get('completed', 0)} completed, "
            f"{counts.get('failed', 0)} failed."
        )
    return 0


def cmd_subagents(args: argparse.Namespace) -> int:
    """Show the sanitized renderer-local subagent registry."""
    state = _load_state()
    session = _resolve_session(
        args, state, allow_interactive=True, command_name="subagents",
    )
    if not session:
        return 1

    port = session["cdp_port"]
    workspace = session["workspace"]
    slug = session.get("slug", _repo_slug(workspace))
    target, _ = _rebind_session_target_if_unique(session)
    _drain_injector_events(port, target, workspace, slug)
    snapshot = _sync_subagent_registry(port, target, workspace, slug)
    if snapshot is None:
        print(
            "Subagent registry API is unavailable. Reinstall globally and run "
            "'caa on' to reload the injector.",
            file=sys.stderr,
        )
        return 1

    if args.json_output:
        print(json.dumps(snapshot, indent=2, default=str))
        return 0

    counts = snapshot.get("counts", {})
    cycle_label = "ON" if snapshot.get("cycleEnabled") else "OFF"
    if snapshot.get("cycleActive"):
        cycle_label += " (running)"
    print(f"Session:   {slug}")
    print(f"Cycle:     {cycle_label}")
    print(
        "Subagents: "
        f"{counts.get('active', 0)} active, "
        f"{counts.get('waiting', 0)} waiting, "
        f"{counts.get('completed', 0)} completed, "
        f"{counts.get('failed', 0)} failed, "
        f"{counts.get('stale', 0)} stale"
    )
    tray = snapshot.get("tray", {})
    if isinstance(tray, dict):
        print(_format_tray_status(tray))
    pinned = snapshot.get("pinned", {})
    if isinstance(pinned, dict):
        print(
            "Pinned:    "
            f"{pinned.get('active', 0)}/{pinned.get('total', 0)} active, "
            f"{pinned.get('ambiguous', 0)} ambiguous, "
            f"{pinned.get('visits', 0)} visits, "
            f"{pinned.get('attempts', 0)} attempts, "
            f"{pinned.get('confirmed', 0)} confirmed, "
            f"{pinned.get('failed', 0)} failed"
        )
    tasks = snapshot.get("tasks", [])
    if not tasks:
        print("No registered subagent task rows.")
        return 0
    for task in tasks:
        identity = task.get("toolUseId") or task.get("rowKey") or "unknown"
        confirmed = task.get("confirmedAt") or "-"
        print(
            f"- {task.get('status', 'unknown'):18s} "
            f"idx={str(task.get('rowIndexHint')):>4s} "
            f"attempts={task.get('attempts', 0):<2} "
            f"id={str(identity)[:36]}"
        )
        print(f"  {task.get('title', 'Subagent task')}")
        print(
            f"  seen={task.get('lastSeenAt') or '-'} "
            f"confirmed={confirmed}"
        )
        if task.get("failure"):
            print(f"  failure={task['failure']}")
    return 0


def _cdp_set_share_safe_title(port: int, enabled: bool,
                              target_id: str | None = None) -> dict | None:
    """Toggle injector title mode. Returns parsed acceptStatus or None."""
    lit = "true" if enabled else "false"
    expr = f"setShareSafeTitle({lit}); JSON.stringify(acceptStatus())"
    try:
        result = _cdp_evaluate(port, expr, target_id=target_id)
        value = result.get("result", {}).get("result", {}).get("value")
        if isinstance(value, str):
            return json.loads(value)
        return value
    except (ConnectionRefusedError, OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"CDP error: {exc}", file=sys.stderr)
        return None


def cmd_share_safe(args: argparse.Namespace) -> int:
    """Persist per-session preference and apply discreet vs branded window title."""
    state = _load_state()
    session = _resolve_session(
        args, state, allow_interactive=True, command_name="share-safe",
    )
    if not session:
        return 1

    port = session.get("cdp_port")
    pid = session.get("pid")
    workspace = session["workspace"]
    slug = session.get("slug", _repo_slug(workspace))
    bound_target = session.get("cdp_target_id")

    mode = getattr(args, "share_mode", None)
    current = bool(session.get("share_safe_title", False))
    if mode == "on":
        new_val = True
    elif mode == "off":
        new_val = False
    else:
        new_val = not current

    if not pid or not _pid_is_alive(pid) or not port:
        print(
            "Dedicated Cursor is not running; start it with 'launch' before "
            "changing the title mode.",
            file=sys.stderr,
        )
        return 1

    result = _cdp_set_share_safe_title(port, new_val, target_id=bound_target)
    if not result:
        print(
            "Could not set discreet/branded title mode (injector missing or too old). "
            "Re-run the global installer, then 'on' to reload the injector.",
            file=sys.stderr,
        )
        return 1

    state_data = _load_state(gc=False)
    ws_key = session["workspace"]
    if ws_key in state_data.get("sessions", {}):
        state_data["sessions"][ws_key]["share_safe_title"] = new_val
        _save_state(state_data)

    label = "discreet" if new_val else "branded"
    print(f"[{slug}] Window title mode: {label}")
    if new_val:
        print(
            "  Uses the title captured when the injector first loaded. "
            "Re-inject (run 'on' after an installer update) if the bar looks stale."
        )
    _log_event("gate", workspace, slug, action="share_safe_title",
               share_safe_title=new_val, cdp_target_id=bound_target)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    state = _load_state()
    sessions = state.get("sessions", {})

    if not sessions:
        print("No active sessions.")
        return 0

    for ws in sessions:
        for warn in _check_stale_hooks(ws):
            print(warn, file=sys.stderr)
        break  # only check once using the first workspace

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


def cmd_alias(args: argparse.Namespace) -> int:
    """Manage workspace aliases stored in config.json."""
    action = getattr(args, "alias_action", None)

    if action == "list" or action is None:
        aliases = _list_aliases()
        if not aliases:
            print("No aliases configured.")
            print("  caa alias set <name> <path-or-ssh-uri>")
            return 0
        for name, path in sorted(aliases.items()):
            if _is_ssh_workspace(path):
                marker = "  (ssh)"
            else:
                exists = Path(path).is_dir()
                marker = "" if exists else "  (path missing!)"
            print(f"  {name:30s} {path}{marker}")
        return 0

    if action == "set":
        name = args.alias_name
        raw_path = args.alias_path
        if not name or not raw_path:
            print("Usage: caa alias set <name> <path-or-ssh-uri>", file=sys.stderr)
            return 1
        if _is_ssh_workspace(raw_path):
            err = _set_alias(name, raw_path)
            if err:
                print(err, file=sys.stderr)
                return 1
            print(f"Alias '{name}' -> {raw_path}")
            return 0
        ws = Path(raw_path).expanduser().resolve()
        if not ws.is_dir():
            print(f"Path '{raw_path}' (resolved: {ws}) is not an existing directory.",
                  file=sys.stderr)
            return 1
        err = _set_alias(name, str(ws))
        if err:
            print(err, file=sys.stderr)
            return 1
        print(f"Alias '{name}' -> {ws}")
        return 0

    if action == "remove":
        name = args.alias_name
        if not name:
            print("Usage: caa alias remove <name>", file=sys.stderr)
            return 1
        if _remove_alias(name):
            print(f"Alias '{name}' removed.")
        else:
            print(f"Alias '{name}' does not exist.", file=sys.stderr)
            return 1
        return 0

    print("Unknown alias action. Use: list, set, remove", file=sys.stderr)
    return 1


def _show_command_history(args: argparse.Namespace) -> int:
    """Show command approval history with readable multiline formatting."""
    workspace_filter = getattr(args, "workspace", None)
    limit = getattr(args, "limit", 20) or 20
    as_json = getattr(args, "json_output", False)

    if not COMMAND_LEDGER_PATH.exists():
        print("No command history yet.")
        return 0

    raw_lines: list[str] = []
    try:
        with open(COMMAND_LEDGER_PATH, "r", encoding="utf-8") as f:
            raw_lines = f.readlines()
    except OSError as exc:
        print(f"Cannot read command ledger: {exc}", file=sys.stderr)
        return 1

    entries: list[dict] = []
    for raw_line in raw_lines:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if workspace_filter:
            ws = entry.get("workspace", "")
            sl = entry.get("slug", "")
            if workspace_filter not in (ws, sl) and _repo_slug(ws) != workspace_filter:
                continue
        entries.append(entry)

    entries = entries[-limit:]

    if as_json:
        for e in entries:
            print(json.dumps(e))
        return 0

    if not entries:
        print("No matching command entries.")
        return 0

    for i, e in enumerate(entries):
        if i > 0:
            print()
        ts = e.get("ts", "?")[:19]
        slug = e.get("slug", "?")
        pattern = e.get("pattern_id", "?")
        reason = e.get("reason", "")
        line_count = e.get("lineCount", 1)
        source = e.get("source", "")
        meta_parts = [f"[{reason}]"] if reason else []
        if line_count and line_count > 1:
            meta_parts.append(f"{line_count} lines")
        if source:
            meta_parts.append(source)
        meta = " ".join(meta_parts)
        print(f"{ts}  {slug}  {pattern} {meta}")
        command = e.get("command", "")
        if command:
            for j, line in enumerate(command.split("\n")):
                prefix = "  $ " if j == 0 else "    "
                print(f"{prefix}{line}")

    return 0


def cmd_history(args: argparse.Namespace) -> int:
    """Show persisted event history."""
    if getattr(args, "commands", False):
        return _show_command_history(args)

    workspace_filter = getattr(args, "workspace", None)
    limit = getattr(args, "limit", 20) or 20
    as_json = getattr(args, "json_output", False)

    if not HISTORY_PATH.exists():
        print("No history yet.")
        return 0

    raw_lines: list[str] = []
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            raw_lines = f.readlines()
    except OSError as exc:
        print(f"Cannot read history: {exc}", file=sys.stderr)
        return 1

    entries: list[dict] = []
    for raw_line in raw_lines:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if workspace_filter:
            ws = entry.get("workspace", "")
            sl = entry.get("slug", "")
            if workspace_filter not in (ws, sl) and _repo_slug(ws) != workspace_filter:
                continue
        entries.append(entry)

    entries = entries[-limit:]

    if as_json:
        for e in entries:
            print(json.dumps(e))
        return 0

    if not entries:
        print("No matching history entries.")
        return 0

    for e in entries:
        ts = e.get("ts", "?")[:19]
        rtype = e.get("record_type", "?")
        slug = e.get("slug", "?")
        action = e.get("action", "")
        detail = ""
        if rtype == "gate":
            detail = f"gate {action}"
        elif rtype == "session":
            pid_val = e.get("pid", "")
            detail = f"session {action} (PID {pid_val})"
        elif rtype == "click":
            cmd_preview = ""
            cmd_data = e.get("command")
            if isinstance(cmd_data, dict) and cmd_data.get("preview"):
                cmd_preview = f" | {cmd_data['preview']}"
            elif isinstance(cmd_data, dict) and cmd_data.get("text"):
                cmd_preview = f" | {cmd_data['text'].split(chr(10))[0][:80]}"
            detail = (
                f"click {e.get('kind', '?')} {e.get('pattern_id', '?')}: "
                f"{e.get('text', '')}{cmd_preview}"
            )
        elif rtype == "blocked_candidate":
            detail = f"blocked {e.get('reason', '?')}: {e.get('text', '')[:40]}"
        elif rtype == "unknown_prompt":
            detail = f"UNKNOWN: {e.get('text', '')[:50]}"
        else:
            detail = f"{rtype} {action}"
        target = e.get("cdp_target_id", "")
        target_str = f" [{target[:8]}]" if target else ""
        print(f"{ts}  {slug:25s}  {detail}{target_str}")

    return 0


def cmd_screenshot(args: argparse.Namespace) -> int:
    """Capture a PNG screenshot of the dedicated Cursor window."""
    state = _load_state()
    session = _resolve_session(args, state, require_alive=True,
                               allow_interactive=True, command_name="screenshot")
    if not session:
        return 1
    port = session.get("cdp_port")
    target = session.get("cdp_target_id")
    slug = session.get("slug", "workspace")
    if not port:
        print("No CDP port for session.", file=sys.stderr)
        return 1
    out_path = getattr(args, "output", None)
    if not out_path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = str(RUNTIME_DIR / f"screenshot-{slug}-{ts}.png")
    try:
        png = _cdp_screenshot(port, target_id=target)
    except (ConnectionRefusedError, OSError, RuntimeError) as exc:
        print(f"Screenshot failed: {exc}", file=sys.stderr)
        return 1
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_bytes(png)
    print(f"Screenshot saved: {out_path} ({len(png)} bytes)")
    return 0


_DIAGNOSE_DOM_EXPR = r"""(() => {
  const BUTTON_SELS = ['button','[role="button"]','a[role="button"]','[class*="primary-button"]','[class*="secondary-button"]','[class*="text-button"]','[class*="action-label"]'];
  const EXCLUDED = ['[id="workbench.parts.sidebar"]','[id="workbench.parts.editor"]','[id="workbench.parts.panel"]','[id="workbench.parts.statusbar"]','[id="workbench.parts.activitybar"]','[id="workbench.parts.auxiliarybar"]'];
  const isVis = (el) => { const s = getComputedStyle(el), r = el.getBoundingClientRect(); return s.display !== 'none' && s.visibility !== 'hidden' && parseFloat(s.opacity||'1') > 0.1 && r.width > 0 && r.height > 0; };
  const isExcl = (el) => EXCLUDED.some(s => el.closest(s));
  const rows = [];
  for (const sel of BUTTON_SELS) {
    for (const el of document.querySelectorAll(sel)) {
      const text = (el.textContent || '').trim().replace(/\s+/g, ' ');
      if (!text || text.length > 80 || !isVis(el)) continue;
      const inDialog = !!el.closest('[role="dialog"],[role="alertdialog"],[aria-modal="true"]');
      const excluded = isExcl(el);
      rows.push({ text, excluded, inDialog, tag: el.tagName.toLowerCase(), role: el.getAttribute('role') || '', aria: (el.getAttribute('aria-label') || '').slice(0, 80) });
    }
  }
  const commandCandidates = [];
  const dialogs = document.querySelectorAll('[role="dialog"],[role="alertdialog"],[aria-modal="true"]');
  for (const dialog of dialogs) {
    if (!isVis(dialog)) continue;
    let found = false;
    for (const sel of ['pre code', 'pre', 'code']) {
      for (const node of dialog.querySelectorAll(sel)) {
        const t = (node.innerText || node.textContent || '').trim();
        if (t.length >= 2 && t.length <= 5000) {
          commandCandidates.push({ text: t, lineCount: t.split('\n').length, source: 'code_block', dialogRole: dialog.getAttribute('role') || '' });
          found = true;
        }
      }
    }
    if (!found) {
      const ft = (dialog.innerText || '').trim();
      if (ft.length >= 2 && ft.length <= 5000) {
        commandCandidates.push({ text: ft.slice(0, 5000), lineCount: ft.split('\n').length, source: 'dialog_text', dialogRole: dialog.getAttribute('role') || '' });
      }
    }
  }
  const status = typeof acceptStatus === 'function' ? acceptStatus() : null;
  return { buttons: rows, commandCandidates: commandCandidates, injectorStatus: status, timestamp: new Date().toISOString() };
})()"""


def cmd_diagnose(args: argparse.Namespace) -> int:
    """Run a self-contained diagnostic: screenshot + DOM snapshot + synthetic probe."""
    state = _load_state()
    session = _resolve_session(args, state, require_alive=True,
                               allow_interactive=True, command_name="diagnose")
    if not session:
        return 1
    port = session.get("cdp_port")
    target = session.get("cdp_target_id")
    slug = session.get("slug", "workspace")
    if not port:
        print("No CDP port for session.", file=sys.stderr)
        return 1

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = RUNTIME_DIR / f"diagnose-{slug}-{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Screenshot
    try:
        png = _cdp_screenshot(port, target_id=target)
        (out_dir / "screenshot.png").write_bytes(png)
        print(f"[1/4] Screenshot: {out_dir / 'screenshot.png'} ({len(png)} bytes)")
    except (ConnectionRefusedError, OSError, RuntimeError) as exc:
        print(f"[1/4] Screenshot failed: {exc}")

    # Step 2: DOM snapshot
    try:
        result = _cdp_evaluate(port, _DIAGNOSE_DOM_EXPR, target_id=target)
        dom_data = result.get("result", {}).get("result", {}).get("value")
        (out_dir / "dom-snapshot.json").write_text(
            json.dumps(dom_data, indent=2) if dom_data else "{}", encoding="utf-8")
        btn_count = len(dom_data.get("buttons", [])) if isinstance(dom_data, dict) else 0
        cmd_count = len(dom_data.get("commandCandidates", [])) if isinstance(dom_data, dict) else 0
        cmd_suffix = f", {cmd_count} command candidate(s)" if cmd_count else ""
        print(f"[2/4] DOM snapshot: {btn_count} visible buttons captured{cmd_suffix}")
    except (ConnectionRefusedError, OSError, RuntimeError) as exc:
        print(f"[2/4] DOM snapshot failed: {exc}")

    # Step 3: Synthetic probes for companion and exact registered-row contexts.
    gate_before = _cdp_gate(port, "status", target_id=target) or {}
    clicks_before = gate_before.get("totalClicks", 0)
    probe_js = r"""(() => {
      const old = document.getElementById('__aa_diagnose_probe');
      if (old) old.remove();
      const d = document.createElement('div');
      d.id = '__aa_diagnose_probe';
      d.setAttribute('role', 'dialog');
      d.setAttribute('aria-modal', 'true');
      d.style.cssText = 'position:fixed;right:16px;top:20px;z-index:2147483647;background:#222;padding:10px;display:flex;gap:8px';
      const b1 = document.createElement('button');
      b1.textContent = 'View';
      const b2 = document.createElement('button');
      b2.textContent = 'Allow';
      b2.onclick = () => {
        d.setAttribute('data-clicked', 'allow');
        b2.remove();
      };
      d.appendChild(b1);
      d.appendChild(b2);
      document.body.appendChild(d);
      return true;
    })()"""
    try:
        _cdp_evaluate(port, probe_js, target_id=target)
        print("[3/4] Synthetic View+Allow probe injected, waiting 4s...")
        time.sleep(4.0)
        gate_after = _cdp_gate(port, "status", target_id=target) or {}
        clicks_after = gate_after.get("totalClicks", 0)
        clicked = _cdp_evaluate(port,
            "(() => document.getElementById('__aa_diagnose_probe')?.getAttribute('data-clicked') || 'no')()",
            target_id=target)
        probe_clicked = clicked.get("result", {}).get("result", {}).get("value", "unknown")
        _cdp_evaluate(port,
            "(() => { document.getElementById('__aa_diagnose_probe')?.remove(); return true; })()",
            target_id=target)
        companion_delta = clicks_after - clicks_before
        print(
            "[3/4] Companion probe result: "
            f"{'PASS' if companion_delta > 0 and probe_clicked != 'no' else 'FAIL'} "
            f"(clicks +{companion_delta}, probe={probe_clicked})"
        )

        registered_probe_js = r"""(() => {
          const state = globalThis.__cursorAutoAccept?.state;
          if (!state?.subagents) return false;
          const taskKey = '__aa_diagnose_registered_task';
          const old = document.getElementById('__aa_diagnose_registered_probe');
          old?.remove();
          state.subagents.delete(taskKey);
          for (const key of state.directRegisteredApprovalAttempts?.keys?.() || []) {
            if (key.startsWith(taskKey + '|')) {
              state.directRegisteredApprovalAttempts.delete(key);
            }
          }
          for (const key of state.fingerprintCooldowns?.keys?.() || []) {
            if (key.startsWith(taskKey + '|')) {
              state.fingerprintCooldowns.delete(key);
            }
          }
          const rowKey = 'tool-placeholder:__aa_diagnose__:tool:call_diagnose_singleton';
          const container = document.createElement('div');
          container.id = '__aa_diagnose_registered_probe';
          container.className = 'virtualized-composer-messages-scroll-container';
          container.setAttribute('data-task-key', taskKey);
          container.style.cssText = 'position:fixed;right:16px;top:20px;z-index:2147483647;background:#222;padding:10px;width:320px;height:96px;overflow:auto';
          const row = document.createElement('div');
          row.className = 'virtualized-composer-messages-row';
          row.setAttribute('data-find-row-key', rowKey);
          row.style.cssText = 'min-height:56px;display:flex;align-items:center';
          const surface = document.createElement('div');
          surface.className = 'subagent-task-card';
          surface.textContent = 'Synthetic registered subagent ';
          const allow = document.createElement('button');
          allow.textContent = 'Allow';
          allow.onclick = () => {
            container.setAttribute('data-clicked', 'allow');
            allow.remove();
          };
          surface.appendChild(allow);
          row.appendChild(surface);
          const input = document.createElement('div');
          input.className = 'full-input-box';
          input.style.cssText = 'height:1px';
          container.appendChild(row);
          container.appendChild(input);
          state.subagents.set(taskKey, {
            taskKey,
            rowKey,
            parentComposerId: '__aa_diagnose_composer',
            status: 'approval_pending',
          });
          document.body.appendChild(container);
          return true;
        })()"""
        registered_before = clicks_after
        registered_injected = _cdp_evaluate(
            port, registered_probe_js, target_id=target)
        injected_value = (
            registered_injected.get("result", {}).get("result", {}).get("value")
        )
        print("[3/4] Synthetic registered singleton Allow probe injected, waiting 4s...")
        time.sleep(4.0)
        registered_gate = _cdp_gate(port, "status", target_id=target) or {}
        registered_after = registered_gate.get("totalClicks", 0)
        registered_clicked_result = _cdp_evaluate(
            port,
            "(() => document.getElementById('__aa_diagnose_registered_probe')?.getAttribute('data-clicked') || 'no')()",
            target_id=target,
        )
        registered_clicked = (
            registered_clicked_result.get("result", {})
            .get("result", {})
            .get("value", "unknown")
        )
        _cdp_evaluate(
            port,
            """(() => {
              const probe = document.getElementById('__aa_diagnose_registered_probe');
              const taskKey = probe?.getAttribute('data-task-key');
              const state = globalThis.__cursorAutoAccept?.state;
              if (taskKey) {
                state?.subagents?.delete(taskKey);
                for (const key of state?.directRegisteredApprovalAttempts?.keys?.() || []) {
                  if (key.startsWith(taskKey + '|')) {
                    state.directRegisteredApprovalAttempts.delete(key);
                  }
                }
                for (const key of state?.fingerprintCooldowns?.keys?.() || []) {
                  if (key.startsWith(taskKey + '|')) {
                    state.fingerprintCooldowns.delete(key);
                  }
                }
              }
              probe?.remove();
              return true;
            })()""",
            target_id=target,
        )
        registered_delta = registered_after - registered_before
        registered_passed = (
            injected_value is True
            and registered_delta > 0
            and registered_clicked != "no"
        )
        print(
            "[3/4] Registered singleton probe result: "
            f"{'PASS' if registered_passed else 'FAIL'} "
            f"(clicks +{registered_delta}, probe={registered_clicked})"
        )
        recent = (registered_gate.get("recentClicks") or [])[-5:]
        result_data = {
            "clicks_before": clicks_before,
            "clicks_after": registered_after,
            "delta": registered_after - clicks_before,
            "companion_probe": {
                "delta": companion_delta,
                "clicked": probe_clicked,
            },
            "registered_singleton_probe": {
                "injected": injected_value,
                "delta": registered_delta,
                "clicked": registered_clicked,
            },
            "recent": recent,
        }
        (out_dir / "probe-result.json").write_text(
            json.dumps(result_data, indent=2), encoding="utf-8")
        verdict = (
            "PASS"
            if companion_delta > 0 and probe_clicked != "no" and registered_passed
            else "FAIL"
        )
    except (ConnectionRefusedError, OSError, RuntimeError) as exc:
        print(f"[3/4] Probe failed: {exc}")
        verdict = "ERROR"

    # Step 4: Summary
    print(f"[4/4] Artifacts saved to: {out_dir}")
    gate_final = _cdp_gate(port, "status", target_id=target) or {}
    print(f"       Gate: {'ON' if gate_final.get('running') else 'OFF'}")
    print(f"       Clicks: {gate_final.get('totalClicks', '?')}")
    print(f"       Injector: {_format_injector_hash(gate_final.get('scriptHash'))}")
    return 0 if verdict == "PASS" else 1


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
    p_launch.add_argument(
        "--interval",
        type=_poll_interval_arg,
        default=DEFAULT_POLL_INTERVAL_SECONDS,
        metavar="SECONDS",
        help="Fallback scan interval in seconds (default: 0.5; range: 0.25-60)",
    )
    p_launch.set_defaults(func=cmd_launch)
    command_parsers["launch"] = p_launch

    p_launch_ssh = sub.add_parser(
        "launch-ssh",
        help="Open dedicated Cursor to SSH remote with auto-approve",
    )
    p_launch_ssh.add_argument("ssh_host", help="SSH host (from ~/.ssh/config)")
    p_launch_ssh.add_argument(
        "remote_path",
        nargs="?",
        default="/",
        help="Absolute remote path on the host (default: /)",
    )
    p_launch_ssh.add_argument(
        "--no-preflight",
        action="store_true",
        help="Skip the ssh test -d check before launching a path-specific remote workspace",
    )
    p_launch_ssh.add_argument(
        "--interval",
        type=_poll_interval_arg,
        default=DEFAULT_POLL_INTERVAL_SECONDS,
        metavar="SECONDS",
        help="Fallback scan interval in seconds (default: 0.5; range: 0.25-60)",
    )
    p_launch_ssh.set_defaults(func=cmd_launch_ssh)
    command_parsers["launch-ssh"] = p_launch_ssh

    p_on = sub.add_parser("on", help="Resume auto-clicking")
    p_on.add_argument("--workspace", "-w", help=ws_help)
    p_on.add_argument("workspace_pos", nargs="?", help=ws_help)
    p_on.add_argument(
        "--interval",
        type=_poll_interval_arg,
        default=None,
        metavar="SECONDS",
        help="Set and persist this session's fallback scan interval (range: 0.25-60)",
    )
    p_on.set_defaults(func=cmd_on)
    command_parsers["on"] = p_on

    p_off = sub.add_parser("off", help="Pause auto-clicking")
    p_off.add_argument("--workspace", "-w", help=ws_help)
    p_off.add_argument("workspace_pos", nargs="?", help=ws_help)
    p_off.set_defaults(func=cmd_off)
    command_parsers["off"] = p_off

    p_cycle = sub.add_parser(
        "cycle",
        help="Enable, disable, or run bounded agent approval cycling",
    )
    p_cycle.add_argument("--workspace", "-w", help=ws_help)
    p_cycle.add_argument("workspace_pos", nargs="?", help=ws_help)
    cycle_group = p_cycle.add_mutually_exclusive_group(required=True)
    cycle_group.add_argument(
        "--on",
        dest="cycle_mode",
        action="store_const",
        const="on",
        help="Enable automatic bounded recovery cycles",
    )
    cycle_group.add_argument(
        "--off",
        dest="cycle_mode",
        action="store_const",
        const="off",
        help="Disable automatic recovery cycles",
    )
    cycle_group.add_argument(
        "--once",
        dest="cycle_mode",
        action="store_const",
        const="once",
        help="Run one explicit bounded cycle without changing the saved toggle",
    )
    p_cycle.set_defaults(func=cmd_cycle)
    command_parsers["cycle"] = p_cycle

    p_subagents = sub.add_parser(
        "subagents",
        help="Show the sanitized subagent task registry",
    )
    p_subagents.add_argument("--workspace", "-w", help=ws_help)
    p_subagents.add_argument("workspace_pos", nargs="?", help=ws_help)
    p_subagents.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Output the complete sanitized snapshot as JSON",
    )
    p_subagents.set_defaults(func=cmd_subagents)
    command_parsers["subagents"] = p_subagents

    p_share = sub.add_parser(
        "share-safe",
        help=(
            "Discreet window title for screen sharing (hides autoapprove branding). "
            "Omit --on/--off to toggle."
        ),
    )
    p_share.add_argument("--workspace", "-w", help=ws_help)
    p_share.add_argument("workspace_pos", nargs="?", help=ws_help)
    share_grp = p_share.add_mutually_exclusive_group()
    share_grp.add_argument(
        "--on",
        dest="share_mode",
        action="store_const",
        const="on",
        help="Use discreet title (restore native bar text from inject time)",
    )
    share_grp.add_argument(
        "--off",
        dest="share_mode",
        action="store_const",
        const="off",
        help="Use branded autoapprove title again",
    )
    p_share.set_defaults(func=cmd_share_safe, share_mode=None)
    command_parsers["share-safe"] = p_share

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

    p_alias = sub.add_parser("alias", help="Manage workspace aliases")
    alias_sub = p_alias.add_subparsers(dest="alias_action")
    alias_sub.add_parser("list", help="List all aliases")
    p_alias_set = alias_sub.add_parser("set", help="Create or update an alias")
    p_alias_set.add_argument("alias_name", help="Short alias name")
    p_alias_set.add_argument(
        "alias_path",
        help="Workspace directory path or SSH folder URI",
    )
    p_alias_rm = alias_sub.add_parser("remove", help="Remove an alias")
    p_alias_rm.add_argument("alias_name", help="Alias to remove")
    p_alias.set_defaults(func=cmd_alias)
    command_parsers["alias"] = p_alias

    p_history = sub.add_parser("history", help="Show event history log")
    p_history.add_argument("--workspace", "-w", help="Filter by workspace path or slug")
    p_history.add_argument("--limit", "-n", type=int, default=20, help="Max entries (default 20)")
    p_history.add_argument("--json", dest="json_output", action="store_true",
                           help="Output as NDJSON")
    p_history.add_argument("--commands", action="store_true",
                           help="Show only approved commands with readable multiline formatting")
    p_history.set_defaults(func=cmd_history)
    command_parsers["history"] = p_history

    p_screenshot = sub.add_parser("screenshot", help="Capture PNG screenshot of dedicated window")
    p_screenshot.add_argument("--workspace", "-w", help=ws_help)
    p_screenshot.add_argument("workspace_pos", nargs="?", help=ws_help)
    p_screenshot.add_argument("--output", "-o", help="Output file path (default: auto-named in runtime dir)")
    p_screenshot.set_defaults(func=cmd_screenshot)
    command_parsers["screenshot"] = p_screenshot

    p_diagnose = sub.add_parser("diagnose", help="Self-debug: screenshot + DOM snapshot + synthetic probe")
    p_diagnose.add_argument("--workspace", "-w", help=ws_help)
    p_diagnose.add_argument("workspace_pos", nargs="?", help=ws_help)
    p_diagnose.set_defaults(func=cmd_diagnose)
    command_parsers["diagnose"] = p_diagnose

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
