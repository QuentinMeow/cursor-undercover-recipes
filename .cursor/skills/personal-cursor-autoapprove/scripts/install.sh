#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Install the Cursor auto-approval skill into a target location.

Options:
  --target global          Install into ~/.cursor/ (personal global)
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
else
    if [[ ! -d "$TARGET" ]]; then
        echo "Error: target directory does not exist: $TARGET" >&2
        exit 1
    fi
    DEST_BASE="$TARGET/.cursor"
fi

DEST_APPROVAL="$DEST_BASE/auto-approval"
DEST_HOOKS="$DEST_BASE/hooks.json"
DEST_SKILL="$DEST_BASE/skills/personal-cursor-autoapprove"

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
HOOKS_CONTENT='{
  "version": 1,
  "hooks": {
    "beforeShellExecution": [
      {
        "command": "/usr/bin/python3 '"$DEST_APPROVAL"'/cursor_auto_approval.py hook-shell"
      }
    ]
  }
}'

if [[ -f "$DEST_HOOKS" ]] && ! $FORCE; then
    echo "  exists: $DEST_HOOKS (use --force to overwrite)"
    echo "  NOTE: verify that hooks.json includes the beforeShellExecution hook pointing to:"
    echo "        /usr/bin/python3 $DEST_APPROVAL/cursor_auto_approval.py hook-shell"
else
    write_file "$DEST_HOOKS" "$HOOKS_CONTENT"
fi

if [[ "$TARGET" != "global" ]]; then
    echo "--- Skill Files (for repo-local Cursor discovery) ---"
    copy_file "$SKILL_DIR/SKILL.md" "$DEST_SKILL/SKILL.md"
    copy_file "$SKILL_DIR/reference.md" "$DEST_SKILL/reference.md"
fi

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
