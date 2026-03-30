---
description: README.md and AGENTS.md authoring guide
globs: "**/README.md,**/AGENTS.md"
alwaysApply: false
---
## Audience Split

- **README.md** is for humans: what it is, how to use it, how to debug it.
- **AGENTS.md** is for AI agents: invariants, verification expectations, guardrails, read order.
- Do not put agent instructions in README. Do not put human usage guides in AGENTS.

## Anti-Duplication

- Child docs own their folder's details.
- Parent docs provide a short summary and link to children.
- Never copy the same procedures into multiple levels. If content must move, treat it as a move (keep it in one canonical location and leave a pointer).

## README Structure

1. **Summary** -- what the component is and why it exists.
2. **Quick Start** -- minimal setup and copy-pasteable commands.
3. **How it works** -- architecture or behavior details (optional, for complex components).

Keep the first screen scannable. Prefer runnable commands from repo root.

## AGENTS.md Structure

1. **Summary** -- what this folder owns; key concepts for agents.
2. **Folder structure** -- high-level purpose of files/subfolders.
3. **Handy commands** -- exact commands runnable from repo root.
4. **Guidance to AI agent tasks** -- read order, edit rules, verification expectations.

## Change Safety

- Before editing, read the current content.
- After editing, verify all original sections still exist.
- Do not invent or simplify commands you cannot verify. Tag unverified commands for human review.
- When removing content, explain why and cite evidence.
