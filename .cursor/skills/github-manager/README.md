# GitHub Manager

## Summary

`github-manager` helps agents and humans work safely with GitHub when `git`
and `gh` can point at different identities. It provides a repo-local `gh`
identity helper plus concise guidance for evidence-first PR analysis, review,
and cleanup.

## Quick Start

### Prerequisites

- `git`
- `gh`
- The target GitHub account authenticated in Cursor at least once with
  `gh auth login`

### Identity Commands

```bash
python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" status --target-user QuentinMeow
python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" enter --target-user QuentinMeow
python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" leave
```

If `enter` says the target user is not logged into `gh`, run `gh auth login`
once in Cursor's terminal and retry.

## How It Works

- `gh_identity.py` records the previously active `gh` login inside the repo's
  git directory, so `leave` can restore it later without touching `git config`.
- `status` shows the current `gh` login, origin remote URL, and any saved
  restore state.
- PR guidance in this skill follows a simple rule: get the right diff first,
  then review, summarize, split, or merge based on evidence.

## Deep Dive

- [GitHub identity switching](references/gh-identity.md)
- [PR workflows](references/pr-workflows.md)
- [Review checklist](references/review-checklist.md)
