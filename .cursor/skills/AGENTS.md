# Shared Skills Agent Guide

## Summary

Use this file when editing anything under `.cursor/skills/`. This is the canonical home for shared skills in this repo.

## Folder Structure

- `README.md` -- human-facing guide to the skill library.
- `AGENTS.md` -- this file (agent-only guardrails).
- `<skill-name>/README.md` -- short public overview for new users.
- `<skill-name>/AGENTS.md` -- skill-specific agent maintenance guide.
- `<skill-name>/SKILL.md` -- one skill's agent instructions.
- `<skill-name>/reference.md` -- a single deeper reference doc for smaller skills.
- `<skill-name>/references/` -- load-on-demand docs for skills with multiple deep guides or references.
- `<skill-name>/scripts/` -- utility scripts owned by that skill.
- `<skill-name>/logs/<run-id>/` -- local artifacts (gitignored).

## Handy Commands

```bash
ls .cursor/skills/
```

## Guidance to AI Agent Tasks

### Read Order
1. Read this file for ownership and edit rules.
2. Read `.cursor/skills/README.md` for the human-facing library overview.
3. Read the target skill's `README.md` before changing public-facing skill docs.
4. Read the target skill's `AGENTS.md` before changing anything inside that skill folder.
5. Read the target skill's `SKILL.md` before changing skill-specific behavior or invocation instructions.

### Edit Rules
- Create skills only under `.cursor/skills/<skill-name>/`.
- Every skill directory should include `README.md`, `AGENTS.md`, and `SKILL.md`.
- Keep each skill `README.md` short and public-facing: what it does, how to use it, and how it works in short.
- Keep each skill `AGENTS.md` agent-only: ownership, read order, edit guardrails, and verification.
- Keep `SKILL.md` under 500 lines; use `reference.md` for a single overflow doc
  or `references/` when the skill has multiple deep docs.
- Keep file references one level deep from SKILL.md.
- Update `README.md` when adding or removing a skill.
- Do not restate the same policy in multiple places.

### Artifact Rules
- Write local outputs under `.cursor/skills/<skill-name>/logs/<run-id>/`.
- Format `run-id` as `<YYYYMMDD-HHMM-TZ>-<slug>`.
- Do not write standalone files directly under `logs/`.

### Naming
- Use lowercase kebab-case for skill directory names.
- `personal-` prefix indicates personal-use skills; they are still committed and shared from this repo.
