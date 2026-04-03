---
name: github-manager
description: >-
  Manage GitHub CLI workflows safely: switch `gh` identity without touching git
  config, analyze PRs from the correct diff, review code with a structured
  checklist, and clean up branches or worktrees carefully. Use when working
  with `gh` auth, PR summaries, PR reviews, stacked PR planning, or repo GitHub
  identity mismatches.
---

# GitHub Manager

Use this skill when GitHub CLI auth or PR workflow needs more structure than
ad-hoc `gh` commands.

## Quick Start

1. Inspect the current state:

   ```bash
   python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" status --target-user QuentinMeow
   ```

2. Switch `gh` to the repo's intended user before GitHub API work:

   ```bash
   python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" enter --target-user QuentinMeow
   ```

3. Run the `gh` work.
4. Restore the previously active account afterward:

   ```bash
   python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" leave
   ```

## Identity Workflow

- `git` over SSH and `gh` API auth are independent. A push can succeed while
  `gh pr create` fails or targets the wrong account.
- The helper stores restore state in the repo's git directory. `leave`
  restores the previously active `gh` user without touching `git config`.
- `enter` fails closed if the target user is not already logged into `gh`.
  The one-time bootstrap is `gh auth login` in Cursor's terminal.
- This skill never edits `git config`. If commit author settings also need to
  change, stop and ask the user.

## PR Workflow

Follow this order:

1. Resolve the real base and head from GitHub before diffing anything.
2. Use GitHub or remote-tracking refs for file counts and line counts.
3. Read the full diff before writing summaries or split plans.
4. Read all review-comment surfaces before claiming feedback is addressed.
5. Back up PR bodies to a local scratch file before overwriting them.
6. Split by concern first. Treat line counts as a prompt to think, not a hard
   law.

See:

- [GitHub identity switching](references/gh-identity.md)
- [PR workflows](references/pr-workflows.md)
- [Review checklist](references/review-checklist.md)

## Critical Rules

- Never assume `main` or `master` is the PR base.
- Never substitute a working-tree diff for the PR diff.
- Never publish counts or claims that are not grounded in GitHub data or the
  actual diff.
- Never hardcode or commit work-account identifiers, private hostnames, or
  tokens.
- Never use this skill to change `git config`.

## Testing

Run the unit tests after changing the identity helper:

```bash
python3 -m unittest discover -s "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/tests"
```

Also run these lightweight checks after script changes:

```bash
python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" status --target-user QuentinMeow
python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" enter --target-user QuentinMeow --dry-run
```
