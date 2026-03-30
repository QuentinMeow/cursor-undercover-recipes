# cursor-undercover-recipes (WIP)

A library of Cursor rules, skills, and toolkits for working effectively in large-company environments -- especially where Cursor usage is restricted. Designed to help individual contributors stay productive, write reliable code, and succeed in shared team repositories with minimal overhead.

## What This Is

This repo is the **versioned source of truth** for reusable Cursor configuration that you can install globally or sync into any project. It contains:

- **Rules** (`.cursor/rules/`) -- lightweight, always-on or glob-scoped Cursor project rules that enforce workflow standards.
- **Skills** (`.cursor/skills/`) -- self-contained agent workflows with setup scripts, reference docs, and helpers.
- **Inputs** (`.agents/inputs/`) -- seed material, conversation exports, and design notes that informed the skills.

## Quick Start

Clone the repo and open it in Cursor:

```bash
git clone git@github.com:QuentinMeow/cursor-undercover-recipes.git
cd cursor-undercover-recipes
```

Cursor automatically picks up rules from `.cursor/rules/` and skills from `.cursor/skills/` when the workspace is open.

### Install a skill globally or into another repo

Each skill under `.cursor/skills/<skill-name>/` includes its own setup instructions in `SKILL.md`. Skills that support cross-repo installation ship an `install.sh` helper:

```bash
# Install the auto-approval skill into your personal global Cursor config
.cursor/skills/personal-cursor-autoapprove/scripts/install.sh --target global

# Sync into another repo
.cursor/skills/personal-cursor-autoapprove/scripts/install.sh --target /path/to/other-repo
```

## Layout

```
.cursor/
  rules/          Committed project rules (always-on or glob-scoped)
  skills/         Committed shared skills (each skill is a directory)
.agents/
  inputs/         Seed material and conversation exports
  worklog/        Conversation artifacts and reports (gitignored)
LICENSE
README.md         This file (human-facing)
AGENTS.md         Agent-facing repo contract
```

## Contributing

Open an issue or PR. When adding a new skill, follow the structure documented in `[.cursor/skills/README.md](.cursor/skills/README.md)`. When modifying rules, keep them short and routing-oriented; detailed workflow logic belongs inside skill folders.

## License

See [LICENSE](LICENSE).