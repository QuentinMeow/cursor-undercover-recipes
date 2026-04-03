# Memory

## Decisions

- `launch-cursor-autoapprove` must bind each session to a specific CDP `target_id`; port-scoped "first workbench wins" evaluation is not trustworthy when one dedicated Cursor process hosts multiple workbench windows.
- Dedicated auto-approve sessions intentionally use per-workspace `--user-data-dir` profiles. Only `settings.json` and `keybindings.json` are synced; `state.vscdb`, login state, and chat/model state remain profile-specific.

## Conventions

- Substantive rule/skill changes should update the affected docs plus `LESSONS.md`, repo-local `.cursor/MEMORY.md`, and a worklog artifact in the same branch when the user wants the artifacts tracked.
- For auto-approve validation, treat `caa status` and `caa history` as the source of truth; window titles are convenience labels, not proof that the right renderer is bound.
- Before any `gh` command in this repo, switch to the personal GitHub login with `github-manager/scripts/gh_identity.py enter --target-user QuentinMeow`, then restore the previously active login with `leave` when the work is done. Do not change `git config` as part of that flow.
- For non-trivial work in this repo, prefer independent agent perspectives such as goal-auditor, step-back reviewer, design skeptic, and test skeptic before locking in a solution.

## Gotchas

- Git SSH auth and `gh` API auth are independent on this machine, so a push can succeed while `gh` still points at the wrong GitHub account.
