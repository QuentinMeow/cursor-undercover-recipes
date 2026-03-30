# Shared Skills Agent Guide

## Summary

Use this file when editing anything under `.cursor/skills/`. This is the canonical home for shared skills in this repo.

## Folder Structure

- `README.md` -- human-facing guide to the skill library.
- `AGENTS.md` -- this file (agent-only guardrails).
- `<skill-name>/SKILL.md` -- one skill's agent instructions.
- `<skill-name>/reference.md` -- deeper material linked from SKILL.md.
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
3. Read the target skill's `SKILL.md` before changing skill-specific content.

### Edit Rules
- Create skills only under `.cursor/skills/<skill-name>/`.
- Keep `SKILL.md` under 500 lines; use `reference.md` for overflow.
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
