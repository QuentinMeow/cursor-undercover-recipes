# Memory

## Decisions

- `launch-cursor-autoapprove` must bind each session to a specific CDP `target_id`; port-scoped "first workbench wins" evaluation is not trustworthy when one dedicated Cursor process hosts multiple workbench windows.
- Dedicated auto-approve sessions intentionally use per-workspace `--user-data-dir` profiles. Only `settings.json` and `keybindings.json` are synced; `state.vscdb`, login state, and chat/model state remain profile-specific.

## Conventions

- Substantive rule/skill changes should update the affected docs plus `LESSONS.md`, repo-local `.cursor/MEMORY.md`, and a worklog artifact in the same branch when the user wants the artifacts tracked.
- For auto-approve validation, treat `caa status` and `caa history` as the source of truth; window titles are convenience labels, not proof that the right renderer is bound.

## Gotchas

- On this machine, git pushes use the personal SSH identity `QuentinMeow`, but `gh` is currently authenticated as enterprise account `qmiao_pins`; `gh pr create` can fail with GraphQL unauthorized even after a successful push.
