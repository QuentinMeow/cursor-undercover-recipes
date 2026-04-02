#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILL_NAME="$(basename "$SKILL_DIR")"
GLOBAL_SKILL_NAME="global-$SKILL_NAME"

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Install the launch-cursor-autoapprove skill.

Options:
  --target global          Install into ~/.cursor/ (launcher at ~/.cursor/launch-autoapprove/)
  --target /path/to/repo   Install into a specific repo's .cursor/ directory
  --dry-run                Show what would be done without making changes
  --force                  Overwrite existing files without prompting
  -h, --help               Show this help message

Examples:
  $(basename "$0") --target global
  $(basename "$0") --target global --dry-run
  $(basename "$0") --target /path/to/repo --force
EOF
}

TARGET=""
DRY_RUN=false
FORCE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)
            if [[ $# -lt 2 || "$2" == -* ]]; then
                echo "Error: --target requires 'global' or /path/to/repo" >&2
                usage >&2
                exit 1
            fi
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

DEST_LAUNCHER="$DEST_BASE/launch-autoapprove"
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

copy_tree() {
    local src_dir="$1"
    local dst_dir="$2"
    if [[ ! -d "$src_dir" ]]; then
        return
    fi
    if $DRY_RUN; then
        echo "[dry-run] copy tree $src_dir -> $dst_dir"
        return
    fi
    /usr/bin/python3 - "$src_dir" "$dst_dir" "$FORCE" <<'PY'
from pathlib import Path
import shutil
import sys

src_dir = Path(sys.argv[1])
dst_dir = Path(sys.argv[2])
force = sys.argv[3].lower() == "true"

for src in sorted(path for path in src_dir.rglob("*") if path.is_file()):
    rel = src.relative_to(src_dir)
    dst = dst_dir / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and not force:
        print(f"  exists: {dst} (use --force to overwrite)")
        continue
    shutil.copy2(src, dst)
    print(f"  copied: {dst}")
PY
}

copy_skill_docs() {
    local skill_src_dir="$1"
    local skill_dst_dir="$2"
    copy_file "$skill_src_dir/README.md" "$skill_dst_dir/README.md"
    copy_file "$skill_src_dir/AGENTS.md" "$skill_dst_dir/AGENTS.md"
    if [[ -f "$skill_src_dir/LESSONS.md" ]]; then
        copy_file "$skill_src_dir/LESSONS.md" "$skill_dst_dir/LESSONS.md"
    fi
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

echo "=== Launch Cursor Auto-Approve Installer ==="
echo "Source: $SKILL_DIR"
echo "Target: $DEST_BASE"
echo ""

echo "--- Launcher ---"
copy_file "$SKILL_DIR/scripts/launcher.py" "$DEST_LAUNCHER/launcher.py"

echo "--- DOM Injector ---"
copy_file "$SKILL_DIR/scripts/devtools_auto_accept.js" "$DEST_LAUNCHER/devtools_auto_accept.js"

echo "--- Skill Files ---"
copy_skill_docs "$SKILL_DIR" "$DEST_SKILL"
render_skill_file "$SKILL_DIR/SKILL.md" "$DEST_SKILL/SKILL.md" "$DEST_SKILL_NAME"
copy_tree "$SKILL_DIR/issues" "$DEST_SKILL/issues"
copy_tree "$SKILL_DIR/references" "$DEST_SKILL/references"

echo ""
echo "=== Verification ==="
if $DRY_RUN; then
    echo "[dry-run] would run: /usr/bin/python3 $DEST_LAUNCHER/launcher.py help"
    echo "[dry-run] would run: /usr/bin/python3 $DEST_LAUNCHER/launcher.py status"
else
    if /usr/bin/python3 "$DEST_LAUNCHER/launcher.py" help >/dev/null && \
       /usr/bin/python3 "$DEST_LAUNCHER/launcher.py" status; then
        echo ""
        echo "Installation successful. Launcher help/status commands ran."
    else
        echo ""
        echo "WARNING: launcher help/status verification failed. Check that Python 3.10+ is available at /usr/bin/python3"
    fi
fi

echo ""
echo "=== Next Steps ==="
if [[ "$TARGET" == "global" ]]; then
    LAUNCH_STEP=2
    TOGGLE_STEP=3
    ALIAS_STEP=4
    echo "1. In Cursor, invoke the global skill as: /$DEST_SKILL_NAME"
    echo "   This tells the agent to open the dedicated auto-approve window for you."
    echo ""
    echo "$LAUNCH_STEP. Or launch directly from a terminal:"
else
    LAUNCH_STEP=1
    TOGGLE_STEP=2
    ALIAS_STEP=3
    echo "$LAUNCH_STEP. Launch directly from a terminal:"
fi
echo "   /usr/bin/python3 $DEST_LAUNCHER/launcher.py launch ~/code/my-project"
echo ""
echo "$TOGGLE_STEP. Toggle the dedicated window gate, inspect state, or open command help:"
echo "   /usr/bin/python3 $DEST_LAUNCHER/launcher.py on"
echo "   /usr/bin/python3 $DEST_LAUNCHER/launcher.py off"
echo "   /usr/bin/python3 $DEST_LAUNCHER/launcher.py status"
echo "   /usr/bin/python3 $DEST_LAUNCHER/launcher.py stop"
echo "   /usr/bin/python3 $DEST_LAUNCHER/launcher.py help"
echo ""
echo "$ALIAS_STEP. For quick access, add this alias to your ~/.zshrc or ~/.bashrc:"
echo "   alias caa='/usr/bin/python3 \"$DEST_LAUNCHER/launcher.py\"'"
echo ""
echo "   Then use:  caa launch ~/code/my-project"
echo "              caa on  |  caa off  |  caa status  |  caa stop  |  caa help"
if [[ "$TARGET" == "global" ]]; then
    echo ""
    echo "5. The global slash-command name is: /$DEST_SKILL_NAME"
fi
