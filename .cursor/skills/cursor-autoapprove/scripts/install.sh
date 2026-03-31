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

Install the Cursor auto-approval skill into a target location.

Options:
  --target global          Install into ~/.cursor/ as skill name $GLOBAL_SKILL_NAME
  --target /path/to/repo   Install into a specific repo's .cursor/ directory
  --dry-run                Show what would be done without making changes
  --force                  Overwrite existing files without prompting
  -h, --help               Show this help message

Examples:
  $(basename "$0") --target global
  $(basename "$0") --target global --dry-run
  $(basename "$0") --target /Users/me/code/my-repo
EOF
}

TARGET=""
DRY_RUN=false
FORCE=false

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
        --force)
            FORCE=true
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
    DEST_SKILL_NAME="$GLOBAL_SKILL_NAME"
else
    if [[ ! -d "$TARGET" ]]; then
        echo "Error: target directory does not exist: $TARGET" >&2
        exit 1
    fi
    DEST_BASE="$TARGET/.cursor"
    DEST_SKILL_NAME="$SKILL_NAME"
fi

DEST_APPROVAL="$DEST_BASE/auto-approval"
DEST_HOOKS="$DEST_BASE/hooks.json"
DEST_SKILL="$DEST_BASE/skills/$DEST_SKILL_NAME"

copy_file() {
    local src="$1"
    local dst="$2"
    if $DRY_RUN; then
        echo "[dry-run] copy $src -> $dst"
        return
    fi
    local dst_dir
    dst_dir="$(dirname "$dst")"
    mkdir -p "$dst_dir"
    if [[ -f "$dst" ]] && ! $FORCE; then
        echo "  exists: $dst (use --force to overwrite)"
    else
        cp "$src" "$dst"
        echo "  copied: $dst"
    fi
}

remove_path() {
    local path="$1"
    if [[ ! -e "$path" ]]; then
        return
    fi
    if $DRY_RUN; then
        echo "[dry-run] remove $path"
        return
    fi
    rm -rf "$path"
    echo "  removed: $path"
}

render_skill_file() {
    local src="$1"
    local dst="$2"
    local installed_name="$3"
    if $DRY_RUN; then
        echo "[dry-run] render $src -> $dst"
        return
    fi
    local dst_dir
    dst_dir="$(dirname "$dst")"
    mkdir -p "$dst_dir"
    if [[ -f "$dst" ]] && ! $FORCE; then
        echo "  exists: $dst (use --force to overwrite)"
        return
    fi
    /usr/bin/python3 - "$src" "$dst" "$installed_name" <<'PY'
from pathlib import Path
import sys

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
installed_name = sys.argv[3]
lines = src.read_text(encoding="utf-8").splitlines(keepends=True)

if lines and lines[0].strip() == "---":
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            break
        if lines[index].startswith("name:"):
            lines[index] = f"name: {installed_name}\n"
            break

dst.write_text("".join(lines), encoding="utf-8")
PY
    echo "  rendered: $dst"
}

cleanup_legacy_global_skill_dirs() {
    local skills_dir="$1"
    local current_skill_dir="$2"
    local legacy_paths=(
        "$skills_dir/$SKILL_NAME"
        "$skills_dir/$PERSONAL_SKILL_NAME"
    )
    for legacy_path in "${legacy_paths[@]}"; do
        if [[ "$legacy_path" == "$current_skill_dir" ]]; then
            continue
        fi
        remove_path "$legacy_path"
    done
}

write_file() {
    local dst="$1"
    local content="$2"
    if $DRY_RUN; then
        echo "[dry-run] write $dst"
        return
    fi
    local dst_dir
    dst_dir="$(dirname "$dst")"
    mkdir -p "$dst_dir"
    if [[ -f "$dst" ]] && ! $FORCE; then
        echo "  exists: $dst (use --force to overwrite)"
    else
        echo "$content" > "$dst"
        echo "  wrote: $dst"
    fi
}

ensure_shell_hook() {
    local hooks_path="$1"
    local controller_path="$2"
    local mode="apply"
    if $DRY_RUN; then
        mode="dry-run"
    fi

    /usr/bin/python3 - "$hooks_path" "$controller_path" "$mode" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

hooks_path = Path(sys.argv[1])
controller_path = sys.argv[2]
mode = sys.argv[3]

desired_entry = {"command": f"/usr/bin/python3 {controller_path} hook-shell"}
existing_payload: dict[str, object]

if hooks_path.exists():
    try:
        raw_payload = json.loads(hooks_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raw_payload = {}
    existing_payload = raw_payload if isinstance(raw_payload, dict) else {}
else:
    existing_payload = {}

payload = dict(existing_payload)
payload["version"] = 1

hooks = payload.get("hooks")
if not isinstance(hooks, dict):
    hooks = {}

before_shell = hooks.get("beforeShellExecution")
if not isinstance(before_shell, list):
    before_shell = []

removed_count = 0
kept_entries: list[object] = []
for entry in before_shell:
    command = entry.get("command") if isinstance(entry, dict) else None
    if isinstance(command, str) and "cursor_auto_approval.py hook-shell" in command and "/auto-approval/" in command:
        removed_count += 1
        continue
    kept_entries.append(entry)

kept_entries.append(desired_entry)
hooks["beforeShellExecution"] = kept_entries
payload["hooks"] = hooks

if mode == "dry-run":
    action = "update" if hooks_path.exists() else "write"
    print(f"[dry-run] {action} {hooks_path}")
    if removed_count:
        print(f"[dry-run] replace {removed_count} existing auto-approval hook(s)")
    print(f"[dry-run] ensure hook -> {desired_entry['command']}")
    raise SystemExit(0)

hooks_path.parent.mkdir(parents=True, exist_ok=True)
hooks_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

if removed_count:
    print(f"  replaced: {removed_count} existing auto-approval hook(s)")
print(f"  wrote: {hooks_path}")
print(f"  ensured hook: {desired_entry['command']}")
PY
}

echo "=== Cursor Auto-Approval Installer ==="
echo "Source: $SKILL_DIR"
echo "Target: $DEST_BASE"
echo ""

echo "--- Controller ---"
copy_file "$SKILL_DIR/scripts/cursor_auto_approval.py" "$DEST_APPROVAL/cursor_auto_approval.py"

echo "--- AppleScripts ---"
copy_file "$SKILL_DIR/applescripts/open_notification_banner.applescript" "$DEST_APPROVAL/open_notification_banner.applescript"
copy_file "$SKILL_DIR/applescripts/click_notification_primary_button.applescript" "$DEST_APPROVAL/click_notification_primary_button.applescript"

echo "--- Hooks ---"
ensure_shell_hook "$DEST_HOOKS" "$DEST_APPROVAL/cursor_auto_approval.py"

echo "--- Skill Files ---"
if [[ "$TARGET" == "global" ]]; then
    cleanup_legacy_global_skill_dirs "$DEST_BASE/skills" "$DEST_SKILL"
fi
render_skill_file "$SKILL_DIR/SKILL.md" "$DEST_SKILL/SKILL.md" "$DEST_SKILL_NAME"
copy_file "$SKILL_DIR/reference.md" "$DEST_SKILL/reference.md"

echo ""
echo "=== Verification ==="
if $DRY_RUN; then
    echo "[dry-run] would run: /usr/bin/python3 $DEST_APPROVAL/cursor_auto_approval.py status"
else
    if /usr/bin/python3 "$DEST_APPROVAL/cursor_auto_approval.py" status 2>/dev/null | head -5; then
        echo ""
        echo "Installation successful. Controller is responding."
    else
        echo ""
        echo "WARNING: controller did not respond. Check that Python 3.9+ is available at /usr/bin/python3"
    fi
fi

echo ""
echo "=== Next Steps ==="
echo "1. Grant Cursor Accessibility permission in System Settings > Privacy & Security > Accessibility"
echo "2. Focus the Cursor window you want to auto-approve, then run:"
echo "   /usr/bin/python3 $DEST_APPROVAL/cursor_auto_approval.py activate --workspace \"\$PWD\""
echo "3. When done, stop with:"
echo "   /usr/bin/python3 $DEST_APPROVAL/cursor_auto_approval.py deactivate"
if [[ "$TARGET" == "global" ]]; then
    echo "4. In Cursor, the global skill now appears as: /$DEST_SKILL_NAME"
fi
