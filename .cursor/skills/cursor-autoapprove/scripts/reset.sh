#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILL_NAME="$(basename "$SKILL_DIR")"
GLOBAL_SKILL_NAME="global-$SKILL_NAME"
PERSONAL_SKILL_NAME="personal-$SKILL_NAME"

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Remove Cursor auto-approval artifacts from a target location.

Options:
  --target global          Reset ~/.cursor/ and remove $GLOBAL_SKILL_NAME plus legacy aliases
  --target /path/to/repo   Reset a specific repo's .cursor/ directory
  --dry-run                Show what would be removed without making changes
  -h, --help               Show this help message

Examples:
  $(basename "$0") --target global
  $(basename "$0") --target global --dry-run
  $(basename "$0") --target /Users/me/code/my-repo
EOF
}

TARGET=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)
            TARGET="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [[ -z "$TARGET" ]]; then
    echo "Error: --target is required" >&2
    usage >&2
    exit 1
fi

if [[ "$TARGET" == "global" ]]; then
    DEST_BASE="$HOME/.cursor"
else
    if [[ ! -d "$TARGET" ]]; then
        echo "Error: target directory does not exist: $TARGET" >&2
        exit 1
    fi
    DEST_BASE="$TARGET/.cursor"
fi

DEST_APPROVAL="$DEST_BASE/auto-approval"
DEST_HOOKS="$DEST_BASE/hooks.json"
DEST_SKILLS_DIR="$DEST_BASE/skills"

stop_active_session() {
    local controller_path="$DEST_APPROVAL/cursor_auto_approval.py"
    local watcher_pid_path="$DEST_APPROVAL/watcher.pid"

    if [[ ! -f "$controller_path" && ! -f "$watcher_pid_path" ]]; then
        echo "  no active controller state found"
        return
    fi

    if $DRY_RUN; then
        if [[ -f "$controller_path" ]]; then
            echo "[dry-run] deactivate $controller_path"
        fi
        if [[ -f "$watcher_pid_path" ]]; then
            echo "[dry-run] kill watcher from $watcher_pid_path if still running"
        fi
        return
    fi

    if [[ -f "$controller_path" ]]; then
        if /usr/bin/python3 "$controller_path" deactivate >/dev/null 2>&1; then
            echo "  deactivated: $controller_path"
        else
            echo "  warning: deactivate failed for $controller_path"
        fi
    fi

    if [[ -f "$watcher_pid_path" ]]; then
        local watcher_pid
        watcher_pid="$(tr -d '[:space:]' < "$watcher_pid_path" || true)"
        if [[ "$watcher_pid" =~ ^[0-9]+$ ]] && kill -0 "$watcher_pid" 2>/dev/null; then
            kill "$watcher_pid" 2>/dev/null || true
            echo "  stopped watcher pid: $watcher_pid"
        fi
    fi
}

remove_path() {
    local path="$1"
    if [[ ! -e "$path" ]]; then
        echo "  missing: $path"
        return
    fi

    if $DRY_RUN; then
        echo "[dry-run] remove $path"
    else
        rm -rf "$path"
        echo "  removed: $path"
    fi
}

remove_hook_entry() {
    if [[ ! -f "$DEST_HOOKS" ]]; then
        echo "  missing: $DEST_HOOKS"
        return
    fi

    local mode="apply"
    if $DRY_RUN; then
        mode="dry-run"
    fi

    /usr/bin/python3 - "$DEST_HOOKS" "$mode" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

hooks_path = Path(sys.argv[1])
mode = sys.argv[2]

payload = json.loads(hooks_path.read_text(encoding="utf-8"))
hooks = payload.get("hooks")
if not isinstance(hooks, dict):
    print("  no hooks object to update")
    raise SystemExit(0)

before_shell = hooks.get("beforeShellExecution")
if not isinstance(before_shell, list):
    print("  no beforeShellExecution hooks to update")
    raise SystemExit(0)

removed: list[str] = []
kept: list[object] = []
for entry in before_shell:
    command = entry.get("command") if isinstance(entry, dict) else None
    if isinstance(command, str) and "cursor_auto_approval.py hook-shell" in command and "/auto-approval/" in command:
        removed.append(command)
    else:
        kept.append(entry)

if not removed:
    print("  no auto-approval hook entry found")
    raise SystemExit(0)

prefix = "[dry-run] would remove" if mode == "dry-run" else "  removed"
for command in removed:
    print(f"{prefix} hook: {command}")

if mode == "dry-run":
    raise SystemExit(0)

if kept:
    hooks["beforeShellExecution"] = kept
else:
    hooks.pop("beforeShellExecution", None)

if not hooks:
    hooks_path.unlink()
    print(f"  deleted: {hooks_path}")
else:
    payload["hooks"] = hooks
    hooks_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"  updated: {hooks_path}")
PY
}

echo "=== Cursor Auto-Approval Reset ==="
echo "Target: $DEST_BASE"
echo ""

echo "--- Active Session ---"
stop_active_session

echo "--- Hooks ---"
remove_hook_entry

echo "--- Auto-Approval Runtime ---"
remove_path "$DEST_APPROVAL"

echo "--- Skill Files ---"
remove_path "$DEST_SKILLS_DIR/$GLOBAL_SKILL_NAME"
remove_path "$DEST_SKILLS_DIR/$SKILL_NAME"
remove_path "$DEST_SKILLS_DIR/$PERSONAL_SKILL_NAME"

echo ""
echo "Reset complete."
