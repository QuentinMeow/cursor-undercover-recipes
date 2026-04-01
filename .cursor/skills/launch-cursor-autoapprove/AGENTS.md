# Launch Cursor Auto-Approve Agent Guide

## Summary

This folder owns the `launch-cursor-autoapprove` skill. It launches a dedicated
Cursor instance with DOM auto-accept injected via CDP, and provides `on`/`off`
gate commands. This is the canonical auto-approval skill in the repo. Keep
public onboarding in `README.md`, deep user docs in `references/`, and agent
rules in this file.

## Folder Structure

- `README.md` -- human-facing overview and quick start.
- `AGENTS.md` -- this file.
- `SKILL.md` -- agent skill entrypoint.
- `LESSONS.md` -- accumulated generic lessons from resolved launch-skill issues.
- `issues/` -- structured issue records for launch-skill failures and fixes.
- `references/implementation.md` -- user-facing architecture and code-path deep dive.
- `references/manual-testing.md` -- user-facing smoke-test plan and evidence guide.
- `references/retired-approaches.md` -- why older auto-approval skills were removed.
- `scripts/launcher.py` -- main launcher script (launch, on, off, status, stop).
- `scripts/devtools_auto_accept.js` -- canonical DOM injector for this skill.
- `scripts/install.sh` -- installs globally to `~/.cursor/launch-autoapprove/` or copies the skill into another repo.

## Guidance to AI Agent Tasks

### Read Order
1. Read this file for ownership and edit rules.
2. Read `LESSONS.md` before modifying behavior or docs.
3. Check `issues/` for unresolved launch-skill bugs.
4. Read `README.md` before changing public-facing user docs.
5. Read `SKILL.md` before changing invocation flow.
6. Read the relevant file under `references/` before changing technical claims.
7. Read `scripts/launcher.py` before changing launch or toggle behavior.

### Edit Rules
- Keep `README.md` short and user-facing.
- Keep `AGENTS.md` agent-only.
- Put detailed user-facing implementation, testing, and failure-history material
  in `references/` instead of expanding `README.md`.
- `devtools_auto_accept.js` lives here as the canonical injector. Do not create
  a second source-of-truth copy under another skill.
- `launcher.py` is self-contained. Do not add cross-skill imports.
- If you retire or replace an older approach, preserve the lesson in
  `references/retired-approaches.md` before deleting the old files.

### Verification
- After changing `launcher.py`, test:
  `/usr/bin/python3 "$(git rev-parse --show-toplevel)/.cursor/skills/launch-cursor-autoapprove/scripts/launcher.py" status`
  (should report state or "no active session").
- After changing `devtools_auto_accept.js`, verify:
  `/usr/bin/python3 "$HOME/.cursor/launch-autoapprove/launcher.py" on`
  can refresh a running window and `status` shows the expected injector hash.
- After install changes, test:
  `bash "$(git rev-parse --show-toplevel)/.cursor/skills/launch-cursor-autoapprove/scripts/install.sh" --target global --dry-run`
- After doc changes, check that `README.md` still fits on one screen and links
  to deeper material instead of duplicating it.
