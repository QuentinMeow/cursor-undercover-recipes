# Shared Skills

## Purpose

`.cursor/skills/` is the home for reusable Cursor skills in this repo. Each
skill is a self-contained directory with a short public `README.md`, an
agent-only `AGENTS.md`, a `SKILL.md` entrypoint, and any supporting reference
material or setup scripts it needs.

## What Lives Here

- `README.md` -- this file (human-facing guide to the skill library).
- `AGENTS.md` -- agent-only editing and ownership guardrails.
- `<skill-name>/README.md` -- short public overview for new users.
- `<skill-name>/AGENTS.md` -- skill-specific agent maintenance guide.
- `<skill-name>/SKILL.md` -- workflow-specific agent instructions for one skill.
- `<skill-name>/reference.md` -- a single detailed reference doc for smaller skills.
- `<skill-name>/references/` -- load-on-demand docs for skills with multiple deep references or guides.
- `<skill-name>/scripts/` -- utility scripts owned by that skill.
- `<skill-name>/logs/` -- local artifacts for that skill (gitignored).

## Available Skills

| Skill | Description |
|-------|-------------|
| `launch-cursor-autoapprove` | Launch a dedicated Cursor window with DOM auto-accept injected via CDP. Simple `on`/`off` gate toggle for a dedicated agent window. |

Each skill keeps its public `README.md` short. When a user wants deeper
implementation details, validation steps, or design history, look for linked
docs under that skill's `references/` directory.

## Adding a New Skill

1. Create a directory: `.cursor/skills/<skill-name>/`
2. Add a short `README.md` for new users that explains what the skill does, how to use it, and how it works in short form.
3. Add an `AGENTS.md` with agent-only guardrails, read order, and verification expectations.
4. Add a `SKILL.md` with YAML frontmatter (`name`, `description`) and concise invocation instructions.
5. Keep `SKILL.md` under 500 lines. Use `reference.md` for one deep doc, or
   `references/` when the skill grows multiple load-on-demand docs.
6. If the skill needs scripts, put them in `scripts/` and reference them from the docs that own that level of detail.
7. Update this README with a row in the "Available Skills" table.

## Installing Skills Into Other Repos

Skills that support cross-repo installation include an `install.sh` script:

```bash
# Install globally into ~/.cursor/skills/
.cursor/skills/<skill-name>/scripts/install.sh --target global

# Install into a specific repo
.cursor/skills/<skill-name>/scripts/install.sh --target /path/to/repo
```

Some skills intentionally rename their global copy to `global-<skill-name>` so the global slash command stays distinct from a repo-local install of the same skill.
