---
name: launch-cursor-autoapprove
description: >-
  Launch a dedicated Cursor window with auto-approval pre-injected via CDP.
  Provides dead-simple on/off gate toggle. Use when the user wants a
  dedicated auto-approve Cursor instance, or says "launch auto-approve
  cursor", "open a cursor that auto-approves", or "I don't want to click
  accept."
---

> **AGENT: REINSTALL AFTER EVERY CODE CHANGE.**
> After editing ANY file under `scripts/` (launcher.py, devtools_auto_accept.js,
> install.sh) or SKILL.md, you MUST re-run the global installer before the
> change takes effect at runtime:
>
> ```bash
> bash "$(git rev-parse --show-toplevel)/.cursor/skills/launch-cursor-autoapprove/scripts/install.sh" --target global --force
> ```
>
> The global install at `~/.cursor/launch-autoapprove/` and
> `~/.cursor/skills/global-launch-cursor-autoapprove/` is what Cursor actually
> executes. Forgetting this step means the user runs stale code. There is no
> auto-sync -- the installer is the only mechanism.

# Launch Cursor Auto-Approve

Open a dedicated Cursor window with the DOM auto-accept script injected and the
gate ON. Approval prompts in that window are auto-clicked. Simple `on` / `off`
commands toggle the gate later.

This is the supported auto-approval skill in this repo. The older
`cursor-autoapprove` and `personal-cursor-quickapprove` experiments were
retired after repeated safety and reliability failures; see
[`references/retired-approaches.md`](references/retired-approaches.md) for the
details.

## Prerequisites

- macOS, Python 3.10+, Cursor IDE
- For the alias shortcut: `alias caa='/usr/bin/python3 "$HOME/.cursor/launch-autoapprove/launcher.py"'` in shell profile

## Install (First Time)

```bash
bash "$(git rev-parse --show-toplevel)/.cursor/skills/launch-cursor-autoapprove/scripts/install.sh" --target global --force
```

These install snippets assume you are running from this repo checkout, since
they use `git rev-parse --show-toplevel` to locate the repo root.

Useful flags:

- `--target global` or `--target /path/to/repo`
- `--force` to overwrite existing installed files
- `--dry-run` to preview install actions

Global installs appear in Cursor as `/global-launch-cursor-autoapprove`.
The runtime helper stays at `~/.cursor/launch-autoapprove/launcher.py`; `caa` is
the optional short alias for later `on`/`off`/`status`/`stop`/`help` commands.

Repo-local installs are also supported:

```bash
bash "$(git rev-parse --show-toplevel)/.cursor/skills/launch-cursor-autoapprove/scripts/install.sh" --target /path/to/repo --force
```

That copies the skill docs plus a launcher entrypoint into the target repo's
`.cursor/`, while the dedicated runtime state and dedicated profile remain under
`~/.cursor/launch-autoapprove/`.

## Agent Workflow

When the user asks for auto-approval, run:

```bash
/usr/bin/python3 "$HOME/.cursor/launch-autoapprove/launcher.py" launch --workspace "$PWD"
```

Then tell the user:

> A dedicated Cursor window has opened for this project with auto-approval ON.
> Move your agent work to that window. Use `caa off` to pause, `caa on` to resume,
> and `caa stop` to close the dedicated auto-approve window when done.

The agent does NOT need to deactivate at end of task. The user controls the
lifecycle with `on`/`off`/`stop`.

## Commands

| Command | What it does |
|---------|-------------|
| `launch [-w PATH] [PATH]` | Open dedicated Cursor, inject DOM script, gate ON. Blocks only if the same workspace is already running. Multiple workspaces can run simultaneously. |
| `on [-w PATH\|SLUG]` | Resume auto-clicking (`startAccept()` via CDP). Reloads stale in-window injector code when hash differs. Auto-detected if only one session, otherwise opens an interactive picker in a TTY. |
| `off [-w PATH\|SLUG]` | Pause auto-clicking (`stopAccept()` via CDP) while keeping the dedicated window open. Auto-detected if only one session, otherwise opens an interactive picker in a TTY. |
| `status [-w PATH\|SLUG]` | Show session details. Shows all sessions if `-w` is omitted; if `-w <slug>` is ambiguous, the picker is used. |
| `stop [-w PATH\|SLUG] [--all]` | Pause gate, close dedicated Cursor process, and remove session when shutdown succeeds. Without `-w`, it prefers running sessions when any are alive; if none are running, it falls back to stale entries for cleanup. Use `--all` to stop every session, but do not combine `--all` with `-w` or a positional workspace. |
| `help [COMMAND]` | Show usage examples, subcommand help, and paths to the deeper docs. |

`on` and `off` auto-detect the target when only one running session is active.
`stop` prefers running sessions when any are alive, but `stop -w ...` can still
target a stale session entry for cleanup. With multiple matches in an
interactive terminal, the launcher opens an arrow-key picker. In
non-interactive shells, specify `-w <slug>` or `-w <full-path>`. If two
sessions share the same slug, use the full path. For a short built-in summary,
use `caa --help` (or the full launcher path with `--help`).

`inject` / `--restart` are not part of this supported launcher surface.

## How It Works

1. `launch` syncs `settings.json` and `keybindings.json` from your default
   Cursor profile so editor preferences carry over to the dedicated window.
2. `launch` starts a new Cursor process with `--remote-debugging-port` and
   `--user-data-dir` (a per-workspace profile directory). Each workspace gets
   its own persistent profile at `~/.cursor/launch-autoapprove/dedicated-profile-<slug>/`.
3. The launcher injects `devtools_auto_accept.js` via CDP `Runtime.evaluate`,
   passing the repo slug so the script knows the project name.
4. The injector polls for approval buttons every 2s and clicks matches.
5. The injector continuously maintains the window title
   (`autoapprove ✅ <repo>` or `autoapprove ⏸ <repo>`) via a 3-second
   interval, so the title self-heals if Cursor resets it.
6. `on`/`off` call `startAccept()`/`stopAccept()` via CDP -- no manual
   DevTools interaction needed.
7. Process-level isolation: the dedicated window is a separate OS process,
   so auto-clicking cannot leak to your normal Cursor windows.
8. If the installed injector changed after the window was launched, `on`
   reloads the in-window script so the running window picks up the latest
   pattern fixes.

**Note on Cursor-specific preferences**: Model selection, agent mode, and
similar UI state live in `state.vscdb` (a per-profile SQLite database) and
are not synced. The dedicated profile persists between launches, so set these
once in the dedicated window and they will stick.

If you previously used the retired `cursor-autoapprove` approach, remove stale
global artifacts (`~/.cursor/skills/global-cursor-autoapprove/`,
`~/.cursor/auto-approval/`, and old `beforeShellExecution` hook entries in
`~/.cursor/hooks.json`) to avoid conflicts.

## Testing

No automated tests required for this skill. Verification is manual because the
behavior depends on a live Cursor window plus approval prompts.

Minimum verification after executable changes:

```bash
bash "$(git rev-parse --show-toplevel)/.cursor/skills/launch-cursor-autoapprove/scripts/install.sh" --target global --force
/usr/bin/python3 "$HOME/.cursor/launch-autoapprove/launcher.py" help
/usr/bin/python3 "$HOME/.cursor/launch-autoapprove/launcher.py" status
```

If a dedicated window is already running, also verify `on` can refresh stale
injector code and that `status` reports a hash plus click count. If multiple
sessions are active, also verify the interactive picker works for
`on`/`off`/`stop`, plus `status -w <slug>` when a slug is ambiguous.

## Additional Reference

- [Implementation details](references/implementation.md)
- [Manual testing guide](references/manual-testing.md)
- [Why older approaches were retired](references/retired-approaches.md)
