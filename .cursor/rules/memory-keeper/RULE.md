---
description: Memory keeper — automatically read and update MEMORY.md files for persistent cross-session knowledge
alwaysApply: true
---

## Purpose

Maintain durable knowledge across conversations in two MEMORY.md files:

| Scope | Path | Content |
|-------|------|---------|
| Global | `~/.cursor/MEMORY.md` | User preferences, cross-project patterns, environment notes |
| Local | `.cursor/MEMORY.md` | Project architecture, decisions, conventions, gotchas, active context |

## Session Start

At the beginning of every conversation, silently read both files if they exist:

1. `~/.cursor/MEMORY.md` (global)
2. `.cursor/MEMORY.md` (local, repo-specific)

Do not mention reading them unless the user asks. Use their contents to inform your work.

## Session End

At the end of every **substantive** conversation (multi-step work, new discoveries, preference changes), update the appropriate MEMORY.md:

1. **Add** new entries that pass all three quality gates (see below).
2. **Remove** entries that are no longer true or have been superseded.
3. **Reorganize** sections if they have grown unwieldy.

Trivial conversations (single-line answers, typo fixes) do not require updates.

### Pre-Final Checklist (Required)

Before sending the final user response for a substantive conversation, complete
this checklist in order:

1. Re-read `~/.cursor/MEMORY.md` and `.cursor/MEMORY.md` (if present) so edits
   are based on the latest file state.
2. Decide whether there are new durable entries and/or stale entries to remove.
3. Apply memory updates (or intentionally skip because no entries passed quality
   gates).
4. Record the outcome in the conversation worklog:
   - which MEMORY file(s) were updated, or
   - why no memory update was made.

Do not skip this checklist. Missing memory maintenance on substantive work is a
process failure.

## Quality Gates

Every new entry must pass **all three** gates before being added:

| Gate | Passes | Fails |
|------|--------|-------|
| **Durable** — still true next month | "Project uses PostgreSQL 16 with pgvector" | "Currently debugging auth bug on line 42" |
| **Non-obvious** — agent wouldn't know from reading code | "Team prefers explicit error types over stringly-typed errors" | "The project has a README.md" |
| **Actionable** — changes how the agent should behave | "Always run `make lint` before committing" | "The codebase is large" |

## File Creation

If a MEMORY.md does not exist and you have entries that pass the quality gates, create it using the seed template at `.cursor/rules/memory-keeper/templates/MEMORY.md`. For global installs, see the install script.

For the repo-local file (`.cursor/MEMORY.md`), check existence during every
substantive conversation. If it is missing and at least one local entry passes
quality gates, create it in the same conversation before final response.

## Section Format

### Global (`~/.cursor/MEMORY.md`)

```
# Memory

## User Preferences
## Cross-Project Patterns
## Environment
```

### Local (`.cursor/MEMORY.md`)

```
# Memory

## Project Context
## Decisions
## Conventions
## Gotchas
## Active Context
```

Each entry is a markdown bullet under the appropriate section heading. Keep entries concise — one to two sentences. Group related entries and deduplicate.

## Scope Rules

- **User preferences, tool choices, coding style** → global
- **Project architecture, repo conventions, team decisions** → local
- When unsure, prefer local — it is easier to promote to global later than to demote
