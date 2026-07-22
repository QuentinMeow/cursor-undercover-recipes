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
caa launch ~/code/my-project --interval 5
caa launch-ssh my-devbox /home/user/code/project
caa on --interval 0.5
caa cycle --on
caa subagents
caa off
caa status
caa stop
caa history
caa help
```

Use `caa --help` (or the full launcher path with `--help`) for the short
built-in usage summary, `caa help` for examples and doc paths, or
`caa <command> --help` for command flags.

### Command Reference

| Command | Behavior |
|---|---|
| `launch [--workspace PATH] [PATH] [--interval SECONDS]` | Start dedicated Cursor process for a local workspace, inject script, gate ON. The fallback scan defaults to 0.5 seconds; supported range is 0.25–60 seconds. Blocks only if the same workspace is already running; other workspaces can run in parallel. |
| `launch-ssh <host> [/absolute/remote/path] [--no-preflight] [--interval SECONDS]` | Start dedicated Cursor connected to an SSH remote host from `~/.ssh/config`, inject script, gate ON. Path-specific launches verify the remote directory with `ssh <host> test -d <path>` before creating a profile or alias. |
| `on [--interval SECONDS]` | Turn gate ON and optionally change/persist the session's fallback scan interval. Reloads injector code when in-window hash differs from the current injector file. Auto-detects if one session is active, otherwise opens a picker in an interactive terminal. |
| `off` | Turn gate OFF without closing the dedicated window. Auto-detects if one session is active, otherwise opens a picker in an interactive terminal. |
| `cycle --on\|--off\|--once` | Opt-in recovery for registered nested-subagent approval rows that were virtualized out of the DOM. |
| `subagents [--json]` | Show the sanitized task registry, row hints, attempts, and confirmations. |
| `status` | Show PID, CDP port, workspace, gate state, click count, injector hash, current title, recent clicks, and last approved command preview. Shows all sessions if `-w` is omitted; if `-w <slug>` is ambiguous, the picker is used. |
| `stop` | Turn gate OFF, close the dedicated Cursor process, and clear local session state when shutdown succeeds. Without `-w`, it prefers running sessions when any are alive; if none are running, it falls back to stale entries for cleanup. Use `--all` to stop every session, and do not combine `--all` with `-w` or a positional workspace. |
| `history [-w SLUG] [-n N] [--json] [--commands]` | Show durable event log (session/gate/click events). Use `--commands` to show only approved commands with readable multiline formatting from the dedicated command ledger. |
| `alias [set\|remove\|list]` | Manage workspace aliases stored in `config.json`. Auto-registered on launch. |
| `screenshot [-w SLUG] [-o FILE]` | Capture PNG screenshot of the dedicated window via CDP. |
| `diagnose [-w SLUG]` | Self-debug: screenshot + DOM snapshot + synthetic probe + summary. |
| `share-safe [--on\|--off] [-w SLUG]` | Discreet title bar for screen sharing (restores title from inject time; workspace name may still appear). Persists until `stop` or session removal. Omit flags to toggle. |
| `help [COMMAND]` | Show usage examples, command-specific help, and deeper doc paths. |

## Important Behavior

- Uses a dedicated profile at `~/.cursor/launch-autoapprove/dedicated-profile-<slug>/`.
- Copies `settings.json`, `keybindings.json`, and `cursorAuth/*` auth tokens from your default profile.
- Does **not** copy non-auth `state.vscdb` rows (chat history/model state remain profile-specific).
- There is no `inject --restart` command in this supported launcher.
- The observer reacts to DOM changes after a 300ms debounce. `--interval`
  controls the fallback scan, defaults to 0.5 seconds, and can be changed while
  the gate is already ON. A scan clicks at most one eligible candidate, and the
  fingerprint cooldown still prevents repeated clicks on one unresolved card.
- Subagent cycling is OFF by default. It targets only exact task rows inside the
  selected parent conversation and restores the original scroll/focus state.
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
- Broad mutation work is rate-limited. Repeated scans over 250ms or JavaScript
  heap above 768 MiB trips the gate OFF and appears under `status`.
- Keep the gate OFF (`caa off`) when doing sensitive UI actions in the dedicated
  window that are unrelated to approvals.
- A non-focused but still visible dedicated window continued auto-clicking in
  Cursor 3.12.17 (`document.hasFocus() === false`). Minimized/hidden renderers
  may still be throttled, so verify with `status` for unattended workflows.
  Each dedicated window handles its one mounted, selected conversation.
- Inactive sidebar conversations are not mounted in the workbench DOM. The
  injector can approve the selected conversation, but cannot directly click
  prompts in every pinned/sidebar agent at the same time.

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
- [Subagent approval cycling design](references/subagent-approval-cycling.md)
- [Why older approaches were retired](references/retired-approaches.md)
