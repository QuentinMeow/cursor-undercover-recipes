# Launch Cursor Auto-Approve

## Summary

`launch-cursor-autoapprove` is the supported auto-approval workflow in this
repo. It launches a dedicated Cursor process, injects a DOM auto-accept script
via CDP, and lets you toggle the gate with simple `on` / `off` commands.

The dedicated window is isolated at process level, so auto-clicking does not
spill into your normal Cursor windows.

## Quick Start

### Prerequisites

- macOS
- Python 3.10+
- Cursor IDE

### Install

```bash
bash "$(git rev-parse --show-toplevel)/.cursor/skills/launch-cursor-autoapprove/scripts/install.sh" --target global --force
```

These install snippets assume you are running from this repo checkout, since
they use `git rev-parse --show-toplevel` to locate the repo root.

Global installs appear in Cursor as `/global-launch-cursor-autoapprove`.
Runtime files live under `~/.cursor/launch-autoapprove/`.

Useful install flags:

- `--target global` installs for your user profile.
- `--target /path/to/repo` installs docs/entrypoint into another repo.
- `--force` overwrites existing installed files.
- `--dry-run` shows planned changes without writing files.

### Optional Alias

```bash
alias caa='/usr/bin/python3 "$HOME/.cursor/launch-autoapprove/launcher.py"'
```

### Launch and Control

```bash
/usr/bin/python3 "$HOME/.cursor/launch-autoapprove/launcher.py" launch --workspace ~/code/my-project
```

If you set the alias:

```bash
caa launch ~/code/my-project
caa on
caa off
caa status
caa stop
caa help
```

Use `caa --help` (or the full launcher path with `--help`) for the short
built-in usage summary, `caa help` for examples and doc paths, or
`caa <command> --help` for command flags.

### Command Reference

| Command | Behavior |
|---|---|
| `launch [--workspace PATH] [PATH]` | Start dedicated Cursor process, inject script, gate ON. Blocks only if the same workspace is already running; other workspaces can run in parallel. |
| `on` | Turn gate ON. Reloads injector code when in-window hash differs from the current injector file. Auto-detects if one session is active, otherwise opens a picker in an interactive terminal. |
| `off` | Turn gate OFF without closing the dedicated window. Auto-detects if one session is active, otherwise opens a picker in an interactive terminal. |
| `status` | Show PID, CDP port, workspace, gate state, click count, injector hash, current title, and recent clicks. Shows all sessions if `-w` is omitted; if `-w <slug>` is ambiguous, the picker is used. |
| `stop` | Turn gate OFF, close the dedicated Cursor process, and clear local session state when shutdown succeeds. Without `-w`, it prefers running sessions when any are alive; if none are running, it falls back to stale entries for cleanup. Use `--all` to stop every session, and do not combine `--all` with `-w` or a positional workspace. |
| `help [COMMAND]` | Show usage examples, command-specific help, and deeper doc paths. |

## Important Behavior

- Uses a dedicated profile at `~/.cursor/launch-autoapprove/dedicated-profile-<slug>/`.
- Copies only `settings.json` and `keybindings.json` from your default profile.
- Does **not** copy `state.vscdb` (chat history/account/model state remain profile-specific).
- There is no `inject --restart` command in this supported launcher.
- `stop` ends the session and closes the dedicated process; the dedicated profile
  folder persists for reuse on the next `launch`.
- If two sessions share the same folder name, use `-w <full-path>` instead of a
  slug to avoid ambiguity.

## Safety and Limits

- Matching now uses exact normalized labels (not substring matching), with
  keyboard-hint stripping and excluded zones for explorer/editor to reduce
  false clicks.
- The script still relies on Cursor's DOM structure; major UI changes can break
  matching or require pattern updates.
- Keep the gate OFF (`caa off`) when doing sensitive UI actions in the dedicated
  window that are unrelated to approvals.

## Migration Note (Retired Approach Cleanup)

If you previously used the retired `cursor-autoapprove` workflow, remove stale
artifacts to avoid conflicts:

- `~/.cursor/skills/global-cursor-autoapprove/`
- `~/.cursor/auto-approval/`
- old `beforeShellExecution` entries in `~/.cursor/hooks.json` that point to
  `~/.cursor/auto-approval/cursor_auto_approval.py`

## Deep Dive

- [Implementation details](references/implementation.md)
- [Manual testing guide](references/manual-testing.md)
- [Why older approaches were retired](references/retired-approaches.md)
