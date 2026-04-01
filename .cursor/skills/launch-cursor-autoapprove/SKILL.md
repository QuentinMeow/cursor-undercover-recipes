---
name: launch-cursor-autoapprove
description: >-
  Launch a dedicated Cursor window with auto-approval pre-injected via CDP.
  Provides dead-simple on/off gate toggle. Use when the user wants a
  dedicated auto-approve Cursor instance, or says "launch auto-approve
  cursor", "open a cursor that auto-approves", or "I don't want to click
  accept."
---

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

- macOS, Python 3.9+, Cursor IDE
- For the alias shortcut: `alias aa='/usr/bin/python3 "$HOME/.cursor/launch-autoapprove/launcher.py"'` in shell profile

## Install (First Time)

```bash
bash "$(git rev-parse --show-toplevel)/.cursor/skills/launch-cursor-autoapprove/scripts/install.sh" --target global --force
```

Global installs appear in Cursor as `/global-launch-cursor-autoapprove`.
The runtime helper stays at `~/.cursor/launch-autoapprove/launcher.py`; `aa` is
the optional short alias for later `on`/`off`/`status`/`stop` toggles.

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
> Move your agent work to that window. Use `aa off` to pause, `aa on` to resume,
> and `aa stop` to close the dedicated auto-approve window when done.

The agent does NOT need to deactivate at end of task. The user controls the
lifecycle with `on`/`off`/`stop`.

## Commands

| Command | What it does |
|---------|-------------|
| `launch [--workspace PATH] [PATH]` | Open dedicated Cursor, inject DOM script, gate ON |
| `on` | Resume auto-clicking (`startAccept()` via CDP) |
| `off` | Pause auto-clicking (`stopAccept()` via CDP) |
| `status` | Show gate state and click count |
| `stop` | Pause gate and close the dedicated Cursor |

## How It Works

1. `launch` syncs `settings.json` and `keybindings.json` from your default
   Cursor profile so editor preferences carry over to the dedicated window.
2. `launch` starts a new Cursor process with `--remote-debugging-port` and
   `--user-data-dir` (separate profile).
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

## Testing

No automated tests required for this skill. Verification is manual because the
behavior depends on a live Cursor window plus approval prompts.

Minimum verification after executable changes:

```bash
bash "$(git rev-parse --show-toplevel)/.cursor/skills/launch-cursor-autoapprove/scripts/install.sh" --target global --force
/usr/bin/python3 "$HOME/.cursor/launch-autoapprove/launcher.py" status
```

If a dedicated window is already running, also verify `on` can refresh stale
injector code and that `status` reports a hash plus click count.

## Additional Reference

- [Implementation details](references/implementation.md)
- [Manual testing guide](references/manual-testing.md)
- [Why older approaches were retired](references/retired-approaches.md)
