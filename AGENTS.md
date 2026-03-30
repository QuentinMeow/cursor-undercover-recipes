# Agent Contract

## Summary

This repo is a library of reusable Cursor rules and skills. It is the versioned source of truth; runtime artifacts go in `.agents/worklog/` (gitignored). Rules live under `.cursor/rules/`, skills under `.cursor/skills/`.

## Folder Structure

| Path | Purpose |
|------|---------|
| `.cursor/rules/<name>/RULE.md` | Committed Cursor project rules |
| `.cursor/skills/<name>/SKILL.md` | Committed shared skills |
| `.cursor/skills/<name>/scripts/` | Utility scripts owned by a skill |
| `.cursor/skills/<name>/reference.md` | Detailed reference for a skill |
| `.agents/inputs/` | Seed material, conversation exports, design notes |
| `.agents/worklog/<timestamp>-<slug>.md` | Per-conversation artifacts (gitignored) |
| `README.md` | Human-facing repo overview |
| `AGENTS.md` | This file (agent-facing contract) |

## Handy Commands

```bash
# List all rules
ls .cursor/rules/

# List all skills
ls .cursor/skills/

# Run the auto-approval installer in dry-run mode
.cursor/skills/cursor-autoapprove/scripts/install.sh --dry-run --target global
```

## Guidance to AI Agent Tasks

### Read Order
1. Read this file first for repo-level orientation.
2. Read `.cursor/rules/repo-discovery/RULE.md` for the repo layout and active rule routing.
3. Read the target skill's `SKILL.md` before modifying skill-specific content.
4. Read the nearest `README.md` or `AGENTS.md` before editing docs at any level.

### Worklog Convention
Every substantive conversation must produce a worklog artifact at:
```
.agents/worklog/<YYYYMMDD-HHMM-TZ>-<descriptive-work-item>.md
```
Example: `.agents/worklog/20260330-1430-PDT-bootstrap-repo-structure.md`

### Doc Ownership
- `README.md` is human-facing. Do not add agent instructions to it.
- `AGENTS.md` is agent-facing. Do not add human usage guides to it.
- Child docs own their own details; parent docs summarize and link.
- Never duplicate the same information across levels.

### Change Safety
- Before editing any `README.md` or `AGENTS.md`, read the current content first.
- After editing, verify all original sections still exist or document where content moved.
- Do not invent commands you cannot verify. Tag unverified commands for human review.
