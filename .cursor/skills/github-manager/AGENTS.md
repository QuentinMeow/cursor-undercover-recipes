---
description:
alwaysApply: true
---

# GitHub Manager Agent Guide

## Summary

This folder owns the `github-manager` skill: repo-local `gh` identity switching,
evidence-first PR workflows, stacked-PR operations (Aviator), and review hygiene.
The **comprehensive** PR stack content lives in
`references/pr-workflows-comprehensive.md` (superset of an internal company
`github-pr-manager` skill). Keep human onboarding in `README.md`, agent rules
here, and overflow in `references/`.

## Folder Structure

- `README.md` — human-facing overview and quick start.
- `AGENTS.md` — this file.
- `SKILL.md` — agent entrypoint (identity + links; keep under ~500 lines).
- `LESSONS.md` — generic lessons; read before behavior changes.
- `references/gh-identity.md` — identity switching workflow and recovery.
- `references/pr-workflows.md` — short right-diff-first cheat sheet.
- `references/pr-workflows-comprehensive.md` — Section 1, scenarios A–E, `av`, merge strategies, troubleshooting (large).
- `references/pr-summary-format.md` — PR body templates and TODO markers.
- `references/code-review-checklist.md` — full review + Conventional Comments.
- `references/review-checklist.md` — shorter review lens.
- `references/splitting-strategy.md` — how to split large PRs.
- `references/analysis-commands.md` — numstat / classification helpers.
- `references/reviewer-best-practices.md` — research-backed review tips.
- `scripts/gh_identity.py` — `gh` identity helper.
- `scripts/install.sh` — install to `~/.cursor/skills/global-github-manager/` or another repo.
- `tests/test_gh_identity.py` — unit tests for identity state.
- `logs/<run-id>/` — gitignored PR-body scratch (see SKILL.md).

## Handy Commands

```bash
python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" status --target-user QuentinMeow
python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" enter --target-user QuentinMeow --dry-run
python3 -m unittest discover -s "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/tests"
bash "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/install.sh" --target global --dry-run
```

## Guidance To AI Agent Tasks

### Read Order

1. Read `LESSONS.md` before changing identity or PR workflow behavior.
2. Read `README.md` before changing public-facing docs.
3. Read `SKILL.md` before changing invocation or workflow routing.
4. Read `references/pr-workflows-comprehensive.md` before changing stacked-PR or Section 1 claims.
5. Read `scripts/gh_identity.py` before changing identity behavior.
6. Read `tests/test_gh_identity.py` before changing switch or restore logic.

### Edit Rules

- Never commit tokens, private hostnames, work-account identifiers, or other
  sensitive account details.
- Never change `git config` from this skill.
- Identity helpers must fail closed on ambiguous state.
- Generalize employer-specific tool names in the comprehensive reference; keep
  optional `.agent-files/pr` paths as **org convention**, with personal default
  under `logs/` per `SKILL.md`.
- Keep scripts self-contained; no cross-skill imports.
- Treat `.agents/worklog/*.md` (except `.gitkeep`), `.cursor/MEMORY.md`,
  `logs/**`, and ad hoc PR-body files as local-only unless the user explicitly
  asks to version them.
- `QuentinMeow` in examples is intentional for this repo’s personal remote;
  update the target login when forking the skill elsewhere.

### Verification

- After `gh_identity.py` changes: `unittest` + `status` / `enter --dry-run`.
- After `install.sh` changes: `--dry-run` for global and repo targets.
- After doc edits: keep `README.md` and `SKILL.md` short; push detail into
  `references/`.
