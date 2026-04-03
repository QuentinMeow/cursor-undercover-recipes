# Worklog: Autoapprove Targeting And Evidence

## Summary

Implemented the `launch-cursor-autoapprove` stabilization plan on a clean branch from `main`. The main change is stable CDP target binding so each session pins one renderer instead of re-picking the first workbench page on every command, plus stronger status/history evidence and updated skill/rule documentation.

## Files Changed

- `.cursor/skills/launch-cursor-autoapprove/scripts/launcher.py`
- `.cursor/skills/launch-cursor-autoapprove/scripts/devtools_auto_accept.js`
- `.cursor/skills/launch-cursor-autoapprove/README.md`
- `.cursor/skills/launch-cursor-autoapprove/SKILL.md`
- `.cursor/skills/launch-cursor-autoapprove/LESSONS.md`
- `.cursor/skills/launch-cursor-autoapprove/references/implementation.md`
- `.cursor/skills/launch-cursor-autoapprove/references/manual-testing.md`
- `.cursor/skills/launch-cursor-autoapprove/issues/004-cdp-targets-wrong-workbench-in-multi-window.md`
- `.cursor/rules/agent-harness/RULE.md`
- `.cursor/rules/repo-discovery/RULE.md`
- `.cursor/MEMORY.md`
- `.agents/worklog/20260402-1844-PDT-autoapprove-targeting-and-evidence.md`

## Decisions Made

- Pin `cdp_target_id` in `state.json` and use it for `on`/`off`/`status`/`stop` so the launcher fails closed instead of silently controlling the wrong workbench page.
- Add durable event evidence via `history.jsonl` and `caa history` rather than relying on window title or click count alone.
- Extend the injector with conservative mode-switch approval patterns only alongside tighter selector safety and stronger excluded-zone rules.
- Force-add repo-local memory/worklog files into this branch because the user explicitly asked for the artifacts to live in the PR even though the repo normally ignores them.

## Open Items

- `gh pr create` is still blocked by current `gh` auth (`qmiao_pins` has GraphQL access denied for the personal repo) even though git push over personal SSH works.
- Full manual reproduction of the multi-workbench warning path was not executed from this CLI session because it requires creating an extra workbench window inside the dedicated Cursor process without disrupting the user's active windows.
