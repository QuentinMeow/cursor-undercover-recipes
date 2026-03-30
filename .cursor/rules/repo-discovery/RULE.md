---
description: Repo discovery — where rules, skills, inputs, and outputs live
alwaysApply: true
---
## Repo Layout

| Path | What lives here |
|------|-----------------|
| `.cursor/rules/<name>/RULE.md` | Cursor project rules (always-on or glob-scoped) |
| `.cursor/skills/<name>/SKILL.md` | Shared skills with optional `reference.md`, `scripts/`, `logs/` |
| `.agents/inputs/` | Seed material, conversation exports, design notes |
| `.agents/worklog/` | Per-conversation artifacts and reports (gitignored) |
| `README.md` | Human-facing docs at any level |
| `AGENTS.md` | Agent-facing contracts at any level |

## Navigation

- Start with `AGENTS.md` at repo root for the agent contract.
- Start with `README.md` at repo root for human orientation.
- Read a skill's `SKILL.md` before modifying anything inside that skill folder.
- Read the nearest `AGENTS.md` before editing agent-facing docs at any level.
