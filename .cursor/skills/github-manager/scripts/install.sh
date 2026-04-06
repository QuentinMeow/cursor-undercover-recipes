#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILL_NAME="$(basename "$SKILL_DIR")"
GLOBAL_SKILL_NAME="global-$SKILL_NAME"

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Install the github-manager skill (identity helper + PR workflow references).

Options:
  --target global          Install into ~/.cursor/skills/$GLOBAL_SKILL_NAME/
  --target /path/to/repo   Install into that repo's .cursor/skills/$SKILL_NAME/
  --dry-run                Show actions without writing files
  --force                  Overwrite existing files
  -h, --help               Show this help

Examples:
  $(basename "$0") --target global --force
  $(basename "$0") --target /path/to/other-repo --force
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

DEST_SKILL="$DEST_BASE/skills/$DEST_SKILL_NAME"

copy_file() {
    local src="$1"
    local dst="$2"
    if $DRY_RUN; then
        echo "[dry-run] copy $src -> $dst"
        return
    fi
    mkdir -p "$(dirname "$dst")"
    if [[ -f "$dst" ]] && ! $FORCE; then
        echo "  exists: $dst (use --force to overwrite)"
    else
        cp "$src" "$dst"
        echo "  copied: $dst"
    fi
}

copy_tree_skip_logs() {
    local src_dir="$1"
    local dst_dir="$2"
    if $DRY_RUN; then
        echo "[dry-run] copy tree $src_dir -> $dst_dir (skip logs/)"
        return
    fi
    /usr/bin/python3 - "$src_dir" "$dst_dir" "$FORCE" <<'PY'
from pathlib import Path
import shutil
import sys

src_root = Path(sys.argv[1])
dst_root = Path(sys.argv[2])
force = sys.argv[3].lower() == "true"

for src in sorted(src_root.rglob("*")):
    if not src.is_file():
        continue
    try:
        rel = src.relative_to(src_root)
    except ValueError:
        continue
    if rel.parts and rel.parts[0] == "logs":
        continue
    dst = dst_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and not force:
        print(f"  exists: {dst} (use --force to overwrite)")
        continue
    shutil.copy2(src, dst)
    print(f"  copied: {dst}")
PY
}

render_skill_file() {
    local src="$1"
    local dst="$2"
    local installed_name="$3"
    if $DRY_RUN; then
        echo "[dry-run] render $src -> $dst (name=$installed_name)"
        return
    fi
    mkdir -p "$(dirname "$dst")"
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

echo "=== GitHub Manager skill installer ==="
echo "Source: $SKILL_DIR"
echo "Destination: $DEST_SKILL"
echo ""

echo "--- Core docs ---"
copy_file "$SKILL_DIR/README.md" "$DEST_SKILL/README.md"
copy_file "$SKILL_DIR/AGENTS.md" "$DEST_SKILL/AGENTS.md"
if [[ -f "$SKILL_DIR/LESSONS.md" ]]; then
    copy_file "$SKILL_DIR/LESSONS.md" "$DEST_SKILL/LESSONS.md"
fi
render_skill_file "$SKILL_DIR/SKILL.md" "$DEST_SKILL/SKILL.md" "$DEST_SKILL_NAME"

echo "--- references/ ---"
copy_tree_skip_logs "$SKILL_DIR/references" "$DEST_SKILL/references"

echo "--- scripts/ ---"
copy_tree_skip_logs "$SKILL_DIR/scripts" "$DEST_SKILL/scripts"

echo "--- tests/ ---"
if [[ -d "$SKILL_DIR/tests" ]]; then
    copy_tree_skip_logs "$SKILL_DIR/tests" "$DEST_SKILL/tests"
fi

echo ""
if $DRY_RUN; then
    echo "[dry-run] done."
else
    echo "Installation finished."
    if [[ "$TARGET" == "global" ]]; then
        echo "Invoke in Cursor as: /$DEST_SKILL_NAME"
    fi
fi
