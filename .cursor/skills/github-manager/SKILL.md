---
name: github-manager
description: >-
  Personal superset of GitHub workflows: switch `gh` identity without touching
  git config; evidence-first PR diffs; PR summaries (format + upload); systematic
  code review; stacked PRs with Aviator (`av`); AIO-merge vs stacked-merge; merge
  queues and post-merge cleanup. Use for `gh` auth mismatches, PR descriptions,
  reviews, splitting stacks, addressing feedback, or merging stacked work.
---

# GitHub Manager

This skill combines **repo-local `gh` identity switching** (personal) with the
full **PR lifecycle** content from an internal `github-pr-manager` workflow
(company-oriented): same rigor, generalized org-specific examples, and paths
suited to this repository.

| Layer | What |
|-------|------|
| **This file** | Quick start, identity, where to read next, critical rules |
| **[pr-workflows-comprehensive.md](references/pr-workflows-comprehensive.md)** | Section 1 (get the right diff), scenarios A–E, Aviator, merge strategies, troubleshooting |
| **Focused references** | Summary format, review checklists, splitting, analysis commands |

---

## Quick Start (identity)

Before any `gh pr` / `gh api` work that must land on the right GitHub user:

1. Inspect state:

   ```bash
   python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" status --target-user QuentinMeow
   ```

2. Switch `gh` to the intended account:

   ```bash
   python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" enter --target-user QuentinMeow
   ```

3. Run PR commands (`gh pr view`, `gh pr create`, etc.).
4. Restore the previous `gh` user when done:

   ```bash
   python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" leave
   ```

`git` over SSH and `gh` API auth are independent. This skill **never** edits
`git config`. See [gh-identity.md](references/gh-identity.md).

---

## Scenario routing

Use **[pr-workflows-comprehensive.md](references/pr-workflows-comprehensive.md)**
for detail. Every scenario **starts with Section 1** there (resolve real base/head
from GitHub — never assume `main`).

| Scenario | When |
|----------|------|
| **A** | Write or update a PR summary, or perform a structured review |
| **B** | Split a large PR into stacked PRs (`av`) |
| **C** | Address review feedback across a stack |
| **D** | Merge (AIO-merge default vs stacked-merge) |
| **E** | Post-merge branch/worktree cleanup |

**Most common path:** Prerequisites in the comprehensive doc → Section 1 →
Scenario A → [pr-summary-format.md](references/pr-summary-format.md).

---

## Prerequisites (short)

| Tool | Need |
|------|------|
| `gh` | Always — install and `gh auth login` **inside Cursor's terminal** if agents lack auth |
| `git` | Always |
| `av` (Aviator) | Scenarios B–E only — `brew install aviator-co/tap/av`, then `av init` in repo root |

SSH **certificate**-based org remotes: use your organization's documented cert
tooling; `gh auth login` alone does not replace SSH for `git push`. See the
comprehensive doc.

---

## Focused references

| Doc | Role |
|-----|------|
| [pr-workflows-comprehensive.md](references/pr-workflows-comprehensive.md) | Section 1, API limits, PR body backup paths, scenarios A–E, troubleshooting |
| [pr-summary-format.md](references/pr-summary-format.md) | TL;DR, Goal, collapsed sections, TODO markers, test plan |
| [pr-workflows.md](references/pr-workflows.md) | Right-diff-first cheat sheet (still read Section 1 for stacks) |
| [code-review-checklist.md](references/code-review-checklist.md) | Full review checklist + Conventional Comments |
| [review-checklist.md](references/review-checklist.md) | Shorter review + safety lens |
| [splitting-strategy.md](references/splitting-strategy.md) | How to split by concern |
| [analysis-commands.md](references/analysis-commands.md) | Classification script and numstat helpers |
| [reviewer-best-practices.md](references/reviewer-best-practices.md) | Research-backed review guidance |

---

## PR body backups (personal default)

Prefer gitignored files under:

`.cursor/skills/github-manager/logs/<YYYYMMDD-HHMM-TZ>-<slug>.md`

Some org repos use `.agent-files/pr/` instead; never commit draft bodies. See
Section 3 in the comprehensive reference.

---

## Global install (other machines)

Install a copy under `~/.cursor/skills/global-github-manager/` so Cursor can
invoke **`/global-github-manager`**:

```bash
bash "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/install.sh" --target global --force
```

Repo-local skill path stays `.cursor/skills/github-manager/` when working in
this repository.

---

## Critical rules

- Never assume the PR base branch; always read `baseRefName` from GitHub.
- Never use the working tree as a substitute for `gh pr diff` / remote refs.
- Never fabricate line counts — use `gh api .../pulls/<PR>/files` as documented.
- Never pass PR bodies via shell heredocs; write a file, then `-F body=@file.md`.
- Never `git add -f` skill logs, worklogs, or scratch PR files unless the user
  explicitly wants them committed.

---

## Testing

After changing `gh_identity.py`:

```bash
python3 -m unittest discover -s "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/tests"
python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" status --target-user QuentinMeow
```
