# PR Analysis Commands

Reusable commands for analyzing a PR before splitting. All commands use the
GitHub API as the source of truth, consistent with
[`pr-workflows-comprehensive.md`](pr-workflows-comprehensive.md) Section 1.

> **Important**: This file supplements Section 1 of that reference. Always run Section 1
> first for any summary or published numbers. Use these commands for **split
> planning heuristics** only; published line counts must come from the
> Section 1 Step 3 API call.

## Step 0: Get PR metadata

```bash
gh pr view <PR> --json baseRefName,headRefName,changedFiles,additions,deletions,title,number
```

Store `baseRefName` and `headRefName` -- use them in all subsequent commands.
Never hardcode `master` or `main`.

## Step 1: File list and diff

```bash
# File list (source of truth)
gh pr diff <PR> --name-only

# Verify count
gh pr diff <PR> --name-only | wc -l

# Full diff
gh pr diff <PR>

# Top 20 files by additions
gh api repos/<OWNER>/<REPO>/pulls/<PR>/files --paginate \
  -q 'sort_by(.additions) | reverse | .[:20] | .[] | "\(.additions)\t\(.deletions)\t\(.filename)"'

# Local equivalent (3-dot merge-base diff)
git fetch origin <base> <head>
git diff origin/<base>...origin/<head>
```

## Step 2: Categorize files and count lines

Save the numstat and classify with Python.

```bash
git diff origin/<base>...origin/<head> --numstat > /tmp/pr_numstat.txt
```

### Python classification script

Adapt the category patterns to your project. This script separates LOGIC, TEST,
CONFIG, DOC, AUTOGEN, and MOCK, then reports per-area totals.

```python
import re
from collections import defaultdict

areas = defaultdict(lambda: {
    'logic_add': 0, 'logic_del': 0,
    'test_add': 0, 'test_del': 0,
    'config_add': 0, 'config_del': 0,
    'other_add': 0, 'other_del': 0,
    'files': 0,
})

def classify(path):
    lower = path.lower()
    if any(p in lower for p in ('_test.go', 'test_', '/tests/', '/fixtures/', '/testdata/')):
        return 'test'
    if '/mocks/' in lower:
        return 'other'
    if any(lower.endswith(ext) for ext in ('.md', '.html', '.rst')) or lower.startswith('docs/'):
        return 'other'
    if any(p in lower for p in ('swagger', '.pb.go', 'docs.go', '_generated')):
        return 'other'
    if any(lower.endswith(ext) for ext in ('.yaml', '.yml', '.toml', '.mod', '.sum', '.json')) \
       or lower == '.gitignore' or lower.endswith('__init__.py') or 'makefile' in lower:
        return 'config'
    return 'logic'

with open('/tmp/pr_numstat.txt') as f:
    for line in f:
        parts = line.strip().split('\t')
        if len(parts) != 3:
            continue
        add_s, del_s, path = parts
        if add_s == '-' or del_s == '-':
            continue
        add, dele = int(add_s), int(del_s)

        cat = classify(path)
        area = path.split('/')[0]

        areas[area][f'{cat}_add'] += add
        areas[area][f'{cat}_del'] += dele
        areas[area]['files'] += 1

# Summary
total_logic = total_test = total_config = total_other = 0
print(f"{'Area':40s} {'Files':>5s}  {'Logic':>12s}  {'Test':>12s}  {'Config':>12s}  {'Other':>12s}")
print("-" * 100)
for area, d in sorted(areas.items(), key=lambda x: x[1]['logic_add'] + x[1]['logic_del'], reverse=True):
    logic = d['logic_add'] + d['logic_del']
    test = d['test_add'] + d['test_del']
    config = d['config_add'] + d['config_del']
    other = d['other_add'] + d['other_del']
    total_logic += logic
    total_test += test
    total_config += config
    total_other += other
    print(f"{area:40s} {d['files']:5d}  +{d['logic_add']:<5d}/-{d['logic_del']:<5d}"
          f"  +{d['test_add']:<5d}/-{d['test_del']:<5d}"
          f"  +{d['config_add']:<5d}/-{d['config_del']:<5d}"
          f"  +{d['other_add']:<5d}/-{d['other_del']:<5d}")
print("-" * 100)
print(f"{'TOTAL':40s}       {total_logic:>12d}  {total_test:>12d}  {total_config:>12d}  {total_other:>12d}")
print()
print(f"Logic lines:  {total_logic}")
print(f"Test lines:   {total_test}")
print(f"Config lines: {total_config}")
print(f"Other lines:  {total_other}")
print(f"Nontrivial:   {total_logic + total_test + total_config}")
print()
if total_logic + total_test + total_config <= 300:
    print("VERDICT: Under 300 nontrivial lines. No split needed.")
else:
    print("VERDICT: Over 300 nontrivial lines. Consider splitting.")
    if total_test > 100:
        print(f"  -> Tests contribute {total_test} lines. Consider splitting into follow-up PR.")
    if total_config > 100:
        print(f"  -> Config contributes {total_config} lines. Consider splitting into follow-up PR.")
```

### Quick one-liner alternative

When you don't need the full script, a rough count by category:

```bash
# Logic files (non-test, non-config Go files)
git diff origin/<base>...origin/<head> --numstat \
  | grep -v '_test\.go' | grep -v '/mocks/' | grep -v '/testdata/' \
  | grep '\.go$' \
  | awk '{s+=$1+$2} END {print "Logic lines:", s}'

# Test files
git diff origin/<base>...origin/<head> --numstat \
  | grep '_test\.go' \
  | awk '{s+=$1+$2} END {print "Test lines:", s}'
```

## Step 3: Map dependencies between changed files

For Go projects, find cross-package imports among changed files:

```bash
# Note: uses perl instead of grep -oP for macOS compatibility
git diff origin/<base>...origin/<head> --name-only \
  | grep '\.go$' | grep -v '_test.go' | grep -v '/mocks/' \
  | while read f; do
      pkg=$(dirname "$f")
      imports=$(perl -nle 'print $1 while /"([^"]+)"/g' "$f" 2>/dev/null)
      for imp in $imports; do
        echo "$pkg -> $imp"
      done
    done | sort -u | grep -F "$(git diff origin/<base>...origin/<head> --name-only | xargs -I{} dirname {} | sort -u)"
```

This is a rough filter. For precise results, read the actual import statements
in the diff and build a dependency graph manually.

## Step 4: Estimate comment-only lines (optional refinement)

To exclude comment-only changes from the logic count, pipe the diff through:

```bash
git diff origin/<base>...origin/<head> \
  | grep '^[+-]' | grep -v '^[+-][+-][+-]' \
  | grep -cE '^\s*[+-]\s*(//|#|/\*|\*|"""|\x27\x27\x27)'
```

This gives a rough count of added/removed comment lines. Subtract from the
logic total for a more accurate threshold check.

## Step 5: Verify a split locally

After creating stacked branches, verify each compiles and tests independently:

```bash
# Go
go build ./...
go test ./...

# Python
python3 -m pytest <test_dir> -v
```
