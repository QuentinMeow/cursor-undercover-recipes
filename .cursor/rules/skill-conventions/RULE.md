---
description: Skill conventions — structure, naming, authoring, and placement for all skills
globs: ".cursor/skills/**"
alwaysApply: false
---
## Directory Structure

Every skill is a directory under `.cursor/skills/<skill-name>/` containing:

| File | Required | Purpose |
|------|----------|---------|
| `SKILL.md` | Yes | Agent-facing entry point with YAML frontmatter (`name`, `description`) |
| `reference.md` | No | Detailed reference material linked from SKILL.md |
| `examples.md` | No | Concrete usage examples |
| `scripts/` | No | Utility scripts owned by the skill |
| `logs/<run-id>/` | No | Local artifacts from skill runs (gitignored) |

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

## Naming

- Use lowercase kebab-case for directory names.
- `personal-` prefix indicates personal-use skills. In this repo they are still committed and shared.

## Authoring Guidelines

- Keep `SKILL.md` under 500 lines. Offload detail to `reference.md`.
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
3. Read the target skill's `SKILL.md` before modifying anything inside that skill folder.

## Maintenance

- Update `.cursor/skills/README.md` when adding or removing a skill.
- Update `.cursor/skills/AGENTS.md` when changing edit or artifact conventions.
