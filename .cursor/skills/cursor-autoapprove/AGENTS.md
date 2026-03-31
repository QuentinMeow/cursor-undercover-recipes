# Cursor Auto-Approval Agent Guide

## Summary

This folder owns the `cursor-autoapprove` skill's public docs, agent entrypoint, reference material, and install/runtime scripts. Keep public onboarding in `README.md`, agent maintenance rules in this file, and deep technical detail in `reference.md`.

## Folder Structure

- `README.md` -- short public overview and quick start.
- `AGENTS.md` -- this file.
- `SKILL.md` -- agent skill entrypoint.
- `reference.md` -- deeper technical reference and limitations.
- `scripts/install.sh` -- installs a global or repo-local copy.
- `scripts/reset.sh` -- removes a global or repo-local install.
- `scripts/cursor_auto_approval.py` -- main controller, hook handler, watcher, and CLI.
- `scripts/ax_tree_dump.py` -- Accessibility tree debug helper.
- `applescripts/` -- notification helper scripts copied during install.
- `logs/<run-id>/` -- smoke-test artifacts and sandbox copies.

## Handy Commands

```bash
bash .cursor/skills/cursor-autoapprove/scripts/install.sh --target global --dry-run
bash .cursor/skills/cursor-autoapprove/scripts/reset.sh --target global --dry-run
```

## Guidance to AI Agent Tasks

### Read Order
1. Read this file for ownership and maintenance rules.
2. Read `README.md` before changing public-facing user docs.
3. Read `SKILL.md` before changing invocation flow or high-level usage instructions.
4. Read `reference.md` before changing technical claims, limitations, or failure modes.
5. Read the relevant files under `scripts/` before changing documented commands or install behavior.

### Edit Rules
- Keep `README.md` short and user-facing. It should explain what the skill does, how to use it, and how it works in short form.
- Keep `AGENTS.md` agent-only. Do not turn it into another user guide.
- Keep deep troubleshooting, edge cases, and failure analysis in `reference.md`.
- When install behavior or naming changes, update all affected docs in the same pass.
- Do not treat files under `logs/` as the source of truth for the skill.

### Verification
- Verify documented flags against `scripts/install.sh` and `scripts/reset.sh`.
- If install paths or the global skill name change, update `README.md`, `SKILL.md`, and `reference.md` where relevant.
