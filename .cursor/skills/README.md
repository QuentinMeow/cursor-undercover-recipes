# Shared Skills

## Purpose

`.cursor/skills/` is the home for reusable Cursor skills in this repo. Each skill is a self-contained directory with agent instructions, optional reference material, and setup scripts.

## What Lives Here

- `README.md` -- this file (human-facing guide to the skill library).
- `AGENTS.md` -- agent-only editing and ownership guardrails.
- `<skill-name>/SKILL.md` -- workflow-specific agent instructions for one skill.
- `<skill-name>/reference.md` -- detailed reference material linked from SKILL.md.
- `<skill-name>/scripts/` -- utility scripts owned by that skill.
- `<skill-name>/logs/` -- local artifacts for that skill (gitignored).

## Available Skills

| Skill | Description |
|-------|-------------|
| `cursor-autoapprove` | Set up safer Cursor command auto-approval for any repo. Includes hooks, a window-scoped watcher, and install/reset scripts. |

## Adding a New Skill

1. Create a directory: `.cursor/skills/<skill-name>/`
2. Add a `SKILL.md` with YAML frontmatter (`name`, `description`) and concise instructions.
3. Keep `SKILL.md` under 500 lines. Use `reference.md` for detailed content.
4. If the skill needs scripts, put them in `scripts/` and reference them from SKILL.md.
5. Update this README with a row in the "Available Skills" table.

## Installing Skills Into Other Repos

Skills that support cross-repo installation include an `install.sh` script:

```bash
# Install globally into ~/.cursor/skills/
.cursor/skills/<skill-name>/scripts/install.sh --target global

# Install into a specific repo
.cursor/skills/<skill-name>/scripts/install.sh --target /path/to/repo
```
