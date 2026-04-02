---
description: Repo discovery and routing — canonical entrypoint for repo layout and related rules
alwaysApply: true
---
## Repo Layout

| Path | What lives here |
|------|-----------------|
| `.cursor/rules/<name>/RULE.md` | Cursor project rules (always-on or glob-scoped) |
| `.cursor/skills/<name>/SKILL.md` | Shared skills with optional `reference.md` or `references/`, plus `scripts/` and `logs/` |
| `.agents/inputs/` | Seed material, conversation exports, design notes |
| `.agents/worklog/` | Per-conversation artifacts and reports (gitignored) |
| `README.md` | Human-facing docs at any level |
| `AGENTS.md` | Agent-facing contracts at any level |

## Navigation

- Start with `AGENTS.md` at repo root for the agent contract.
- Start with `README.md` at repo root for human orientation.
- Read a skill's `SKILL.md` before modifying anything inside that skill folder.
- Read the nearest `AGENTS.md` before editing agent-facing docs at any level.
- Read the nearest `README.md` before editing human-facing docs at any level.

## Related Rules

Use these supporting rules as the task demands:

1. `.cursor/rules/readme-and-agents-guide/RULE.md` when editing any `README.md` or `AGENTS.md`.
2. `.cursor/rules/worklog-enforcer/RULE.md` for substantive conversations that create, modify, or analyze code/docs.
3. `.cursor/rules/skill-conventions/RULE.md` when working inside `.cursor/skills/**`.
4. `.cursor/rules/memory-keeper/RULE.md` for reading and updating persistent cross-session knowledge in `MEMORY.md`.
