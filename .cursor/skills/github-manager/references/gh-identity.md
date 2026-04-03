# GitHub Identity Switching

## Why This Exists

`git` and `gh` can point at different identities on the same machine:

- `git fetch` / `git push` may use SSH host aliases and SSH keys.
- `gh pr`, `gh api`, and related commands use the currently active `gh`
  account for the host.

That mismatch is easy to miss because pushes can work while PR creation or PR
edits fail or target the wrong account.

## One-Time Bootstrap

`gh auth switch` can only select from accounts that are already logged in for a
host. If the target account is missing, a human must run `gh auth login` once
inside Cursor's terminal.

Suggested checks:

```bash
gh auth status --hostname github.com
gh auth login
gh auth switch --hostname github.com --user QuentinMeow
```

## Repo-Local Workflow

Use the helper instead of switching accounts by hand:

```bash
python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" status --target-user QuentinMeow
python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" enter --target-user QuentinMeow
python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" leave
```

Behavior:

- `status` shows the active `gh` user, origin remote, and any saved restore
  state.
- `enter` records the previously active `gh` user, then switches to the target.
- `leave` restores the recorded user and removes the saved state.
- Nested `enter` / `leave` calls are reference-counted so helpers can be reused
  in layered workflows without double-restoring.

## Failure Modes

| Problem | Safe behavior |
|---------|---------------|
| Target user not logged into `gh` | `enter` fails with a bootstrap message. |
| Saved state exists but current active user is neither the target nor the saved previous user | Refuse to guess; ask for manual intervention. |
| A previous session crashed after `enter` | `status` shows the stale state; run `leave` once to restore. |
| Git push works but `gh` fails | Treat it as an identity mismatch until proven otherwise. |

## Non-Goals

- This workflow does **not** edit `git config`.
- This workflow does **not** store tokens.
- This workflow does **not** guess a work-account fallback; it restores
  whichever account was active before `enter`.
