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
5. `.cursor/rules/agent-harness/RULE.md` for evidence-first harness engineering when building or operating agent automation tools.
6. `.cursor/rules/debug-escalation/RULE.md` for the mandatory escalation ladder when debugging (never repeat a failed approach).
7. `.cursor/rules/assumption-guard/RULE.md` for verifying environmental assumptions before acting on them.
8. `.cursor/rules/instrument-first/RULE.md` for deploying instrumentation before forming hypotheses.
9. `.cursor/rules/autonomous-recovery/RULE.md` for the self-correction loop when stuck (step back without human coaching).
10. `.cursor/rules/version-coupling-guard/RULE.md` when skills depend on external software versions (DOM selectors, APIs, CLIs).
11. `.cursor/rules/undercover-discipline/RULE.md` when work visibility, screen sharing, or secrecy around personal rules/automation matters.
