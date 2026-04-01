---
description: Skill conventions — structure, naming, authoring, and placement for all skills
globs: ".cursor/skills/**"
alwaysApply: false
---
## Directory Structure

Every skill is a directory under `.cursor/skills/<skill-name>/` containing:

| File | Required | Purpose |
|------|----------|---------|
| `README.md` | Yes | Short human-facing overview for new users: what the skill does, how to use it, and how it works in short |
| `AGENTS.md` | Yes | Agent-facing ownership, read order, edit rules, and verification expectations for this skill folder |
| `SKILL.md` | Yes | Agent-facing entry point with YAML frontmatter (`name`, `description`) used for skill discovery and invocation |
| `reference.md` | No | A single detailed reference doc linked from `README.md` or `SKILL.md` |
| `references/` | No | Load-on-demand docs when a skill grows multiple deep guides or references |
| `examples.md` | No | Concrete usage examples |
| `scripts/` | No | Utility scripts owned by the skill |
| `tests/` | No | Validation scripts and fixtures for skills with automated coverage |
| `logs/<run-id>/` | No | Local artifacts from skill runs (gitignored) |

## Audience Split

- `README.md` is public and human-facing. Keep it brief and precise.
- Every skill `README.md` should include: what the skill does, how to use it, and how it works internally in short form.
- `AGENTS.md` is agent-only. Put folder ownership, read order, guardrails, and verification steps there.
- `SKILL.md` remains the executable skill entrypoint for the agent. Link to deeper docs instead of copying large sections of public-facing content.

## SKILL.md Frontmatter

```yaml
---
name: kebab-case-skill-name    # max 64 chars, lowercase + hyphens
description: >-
  What the skill does and when to use it.
  Write in third person. Include trigger terms.
---
```

The `description` drives skill discovery -- the agent uses it to decide when to apply the skill. Include both WHAT it does and WHEN to use it.

## Testing Declaration

Every skill's `SKILL.md` should include a short `## Testing` section that does
one of the following:

1. Lists the canonical automated test command(s) or script location and when to
   run them.
2. Says `No automated tests required for this skill.` and gives a short reason.

This section is the canonical place for future agents to decide whether to run
tests or ask the user about adding them.

## Naming

- Use lowercase kebab-case for directory names.
- `personal-` prefix indicates personal-use skills. In this repo they are still committed and shared.

## Authoring Guidelines

- Keep `README.md` concise and skimmable; push deep troubleshooting and edge
  cases into `reference.md` or `references/`.
- Keep `AGENTS.md` focused on maintenance guidance rather than user onboarding.
- Keep `SKILL.md` under 500 lines. Offload detail to `reference.md` for a
  single deep doc, or to `references/` when the skill has multiple deep docs.
- Keep file references one level deep from SKILL.md (no nested chains).
- Assume the agent is smart -- only add context it would not already have.
- Provide concrete examples over abstract explanations.
- Use consistent terminology throughout (pick one term and stick with it).
- If the skill includes scripts, make clear whether the agent should execute or read them.

## Progressive Disclosure

Put essential instructions in SKILL.md. Link to deeper material:

```markdown
## Additional Reference
- For full API details, see [reference.md](reference.md)
- For multi-guide skills, it is also fine to link to [references/foo.md](references/foo.md)
- For usage examples, see [examples.md](examples.md)
```

## Installable Skills

Skills that support cross-repo installation should include a `scripts/install.sh` that:
- Accepts `--target global` (install to `~/.cursor/`) or `--target /path/to/repo`.
- Supports `--dry-run` to preview changes.
- Supports `--force` to overwrite existing files.
- Prints verification steps after installation.

## Read Order

1. Read `.cursor/skills/README.md` for the skill library overview.
2. Read `.cursor/skills/AGENTS.md` for edit/ownership rules.
3. Read the target skill's `README.md` before editing public-facing skill docs.
4. Read the target skill's `AGENTS.md` before modifying anything inside that skill folder.
5. Read the target skill's `SKILL.md` before changing skill behavior or invocation instructions.

## Maintenance

- Update `.cursor/skills/README.md` when adding or removing a skill.
- Update `.cursor/skills/AGENTS.md` when changing edit or artifact conventions.
- Create or backfill `README.md` and `AGENTS.md` for legacy skill folders when touching them.
- Backfill a `## Testing` section in `SKILL.md` when touching a legacy skill
  that lacks one.
