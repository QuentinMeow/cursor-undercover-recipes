# GitHub Manager

## Summary

`github-manager` is a **personal superset** skill: repo-local **`gh` identity
switching** (without touching `git` config) plus an evidence-first **PR
lifecycle** guide merged from an internal company `github-pr-manager` workflow.
Use it for summaries, reviews, stacked PRs (Aviator), merge strategy, and safe
cleanup.

## Quick Start

### Identity

```bash
python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" status --target-user QuentinMeow
python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" enter --target-user QuentinMeow
python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" leave
```

### Deep PR workflows

Open [SKILL.md](SKILL.md), then follow links into
[references/pr-workflows-comprehensive.md](references/pr-workflows-comprehensive.md)
for Section 1 (always get the real PR base) and scenarios A–E.

### Global copy on another machine

```bash
bash "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/install.sh" --target global --force
```

Then use Cursor slash command **`/global-github-manager`**.

## How It Works

- **`scripts/gh_identity.py`** — saves the active `gh` user before `enter`,
  restores it on `leave`, using state under the repo’s `.git/` directory.
- **Comprehensive reference** — stacked PRs, AIO-merge vs stacked-merge,
  `av` CLI, merge queues, and troubleshooting live in
  `references/pr-workflows-comprehensive.md`.
- **PR summaries** — templates and TODO markers in
  `references/pr-summary-format.md`.

## Deep Dive

- [SKILL.md](SKILL.md) — entrypoint and scenario routing
- [references/gh-identity.md](references/gh-identity.md)
- [references/pr-workflows-comprehensive.md](references/pr-workflows-comprehensive.md)
- [references/pr-summary-format.md](references/pr-summary-format.md)
