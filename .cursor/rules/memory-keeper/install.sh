#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RULE_NAME="memory-keeper"

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Install the memory-keeper rule and seed MEMORY.md template.

Options:
  --target global          Install rule into ~/.cursor/rules/ and seed ~/.cursor/MEMORY.md
  --target /path/to/repo   Install rule into a repo's .cursor/rules/ and seed .cursor/MEMORY.md
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
    MEMORY_SCOPE="global"
else
    if [[ ! -d "$TARGET" ]]; then
        echo "Error: target directory does not exist: $TARGET" >&2
        exit 1
    fi
    DEST_BASE="$TARGET/.cursor"
    MEMORY_SCOPE="local"
fi

DEST_RULE="$DEST_BASE/rules/$RULE_NAME"
DEST_MEMORY="$DEST_BASE/MEMORY.md"

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

seed_memory() {
    local dst="$1"
    local scope="$2"
    if [[ -f "$dst" ]] && ! $FORCE; then
        if $DRY_RUN; then
            echo "[dry-run] exists: $dst (would skip)"
        else
            echo "  exists: $dst (use --force to overwrite)"
        fi
        return
    fi
    if $DRY_RUN; then
        echo "[dry-run] seed $dst (scope: $scope)"
        return
    fi
    local dst_dir
    dst_dir="$(dirname "$dst")"
    mkdir -p "$dst_dir"

    local template="$SCRIPT_DIR/templates/MEMORY.md"
    if [[ "$scope" == "global" ]]; then
        # Strip local-only sections, keep global sections
        /usr/bin/python3 - "$template" "$dst" "global" <<'PY'
import sys
from pathlib import Path

template = Path(sys.argv[1]).read_text(encoding="utf-8")
dst = Path(sys.argv[2])
scope = sys.argv[3]

global_sections = {"User Preferences", "Cross-Project Patterns", "Environment"}
local_sections = {"Project Context", "Decisions", "Conventions", "Gotchas", "Active Context"}

keep = global_sections if scope == "global" else local_sections

lines = template.splitlines(keepends=True)
out = []
skip = False
for line in lines:
    if line.startswith("## "):
        heading = line.strip().removeprefix("## ")
        skip = heading not in keep
    if line.startswith("<!-- This is the seed template"):
        skip = True
    if line.startswith("     Delete the sections"):
        skip = False
        continue
    if not skip:
        out.append(line)

dst.write_text("".join(out), encoding="utf-8")
PY
    else
        /usr/bin/python3 - "$template" "$dst" "local" <<'PY'
import sys
from pathlib import Path

template = Path(sys.argv[1]).read_text(encoding="utf-8")
dst = Path(sys.argv[2])
scope = sys.argv[3]

global_sections = {"User Preferences", "Cross-Project Patterns", "Environment"}
local_sections = {"Project Context", "Decisions", "Conventions", "Gotchas", "Active Context"}

keep = global_sections if scope == "global" else local_sections

lines = template.splitlines(keepends=True)
out = []
skip = False
for line in lines:
    if line.startswith("## "):
        heading = line.strip().removeprefix("## ")
        skip = heading not in keep
    if line.startswith("<!-- This is the seed template"):
        skip = True
    if line.startswith("     Delete the sections"):
        skip = False
        continue
    if not skip:
        out.append(line)

dst.write_text("".join(out), encoding="utf-8")
PY
    fi
    echo "  seeded: $dst (scope: $scope)"
}

echo "=== Memory Keeper Installer ==="
echo "Source: $SCRIPT_DIR"
echo "Target: $DEST_BASE"
echo ""

echo "--- Rule ---"
copy_file "$SCRIPT_DIR/RULE.md" "$DEST_RULE/RULE.md"

echo "--- Template ---"
copy_file "$SCRIPT_DIR/templates/MEMORY.md" "$DEST_RULE/templates/MEMORY.md"

echo "--- MEMORY.md ---"
seed_memory "$DEST_MEMORY" "$MEMORY_SCOPE"

echo ""
echo "=== Done ==="
if $DRY_RUN; then
    echo "[dry-run] No files were changed."
else
    echo "Rule installed at: $DEST_RULE/RULE.md"
    echo "MEMORY.md at:      $DEST_MEMORY"
fi
echo ""
echo "=== Next Steps ==="
echo "1. Open Cursor in a workspace — the rule will auto-apply."
echo "2. The agent will read $DEST_MEMORY at session start."
echo "3. After substantive conversations, the agent will update it automatically."
