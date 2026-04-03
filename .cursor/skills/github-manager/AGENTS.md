---
description: 
alwaysApply: true
---

# GitHub Manager Agent Guide

## Summary

This folder owns the `github-manager` skill. It covers repo-local `gh`
identity switching, evidence-first PR workflows, and GitHub review hygiene.
Keep human onboarding in `README.md`, agent guardrails here, and deeper
workflow detail in `references/`.

## Folder Structure

- `README.md` -- human-facing overview and quick start.
- `AGENTS.md` -- this file.
- `SKILL.md` -- agent entrypoint and core workflow.
- `LESSONS.md` -- generic lessons that future agents should read first.
- `references/gh-identity.md` -- identity switching workflow and recovery.
- `references/pr-workflows.md` -- diff retrieval, summaries, and cleanup.
- `references/review-checklist.md` -- structured review checklist.
- `scripts/gh_identity.py` -- repo-local `gh` identity helper.
- `tests/test_gh_identity.py` -- unit tests for state handling and fail-closed
  behavior.

## Handy Commands

```bash
python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" status --target-user QuentinMeow
python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" enter --target-user QuentinMeow --dry-run
python3 -m unittest discover -s "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/tests"
```

## Guidance To AI Agent Tasks

### Read Order

1. Read `LESSONS.md` before changing identity or PR workflow behavior.
2. Read `README.md` before changing public-facing docs.
3. Read `SKILL.md` before changing invocation or workflow guidance.
4. Read the relevant file under `references/` before changing technical claims.
5. Read `scripts/gh_identity.py` before changing identity behavior.
6. Read `tests/test_gh_identity.py` before changing switch or restore logic.

### Edit Rules

- Never commit tokens, private hostnames, work-account identifiers, or other
  sensitive account details.
- This skill may inspect `gh` auth state, but it must never change `git
  config`.
- Identity helpers must fail closed on ambiguous state instead of guessing
  which account to restore.
- Keep PR workflow guidance generic and evidence-first; do not assume a
  specific employer, repo, or stack-management tool.
- Keep scripts self-contained; do not add cross-skill imports.
- Treat `.agents/worklog/*.md` (except `.gitkeep`), `.cursor/MEMORY.md`,
  `.cursor/skills/**/logs/**`, and ad hoc PR-body scratch files as local-only
  artifacts. Keep them out of commits unless the user explicitly asks for
  those exact paths to be versioned.
- If one of those ignored artifacts is already tracked, remember that
  `.gitignore` will not untrack it. Remove it from the index as part of the
  fix instead of assuming ignore rules are enough.
- `QuentinMeow` examples are intentional for this repo's personal remote. If
  this skill is copied elsewhere, update the target login rather than copying
  the literal username.

### Verification

- After changing `scripts/gh_identity.py`, run:
  `python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" status --target-user QuentinMeow`
- After changing switch logic, also run:
  `python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" enter --target-user QuentinMeow --dry-run`
- After changing tests or switch logic, run:
  `python3 -m unittest discover -s "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/tests"`
- After doc changes, keep `README.md` short and push overflow into
  `references/`.
