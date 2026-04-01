# Implementation Details

## Summary

`launch-cursor-autoapprove` keeps the design intentionally narrow:

- one dedicated Cursor process
- one injected DOM auto-clicker
- one small state file on disk
- no global shell hooks
- no macOS Accessibility watcher
- no process-wide keystroke spam

That narrower scope is the main reason this skill is the supported path in this
repo.

## Components

### `scripts/launcher.py`

The launcher owns process lifecycle and CDP communication:

- `launch` starts a new Cursor process with its own `--user-data-dir`
- `launch` syncs `settings.json` and `keybindings.json` from the default
  Cursor profile before starting the process
- `on` / `off` / `status` / `stop` talk back to that same process
- state is stored in `~/.cursor/launch-autoapprove/state.json`
- the launcher passes the repo slug to the injector so the script can
  self-maintain the window title

### `scripts/devtools_auto_accept.js`

The DOM injector runs inside the dedicated Cursor window's renderer process:

- scans the DOM every 2 seconds
- looks for visible, clickable approval elements
- clicks them with pointer, mouse, focus, and Enter events
- tracks click count plus recent click history
- continuously maintains the window title (`autoapprove ✅/⏸ <repo>`)
  via a separate 3-second interval, so title recovers automatically if
  Cursor resets it

### `scripts/install.sh`

The installer copies the launcher runtime plus the human-facing docs:

- `~/.cursor/launch-autoapprove/launcher.py`
- `~/.cursor/launch-autoapprove/devtools_auto_accept.js`
- `~/.cursor/skills/global-launch-cursor-autoapprove/`

That means the global slash command and the terminal helper stay in sync after
reinstall.

## Runtime Layout

After a global install, the relevant files are:

| Path | Purpose |
|------|---------|
| `~/.cursor/launch-autoapprove/launcher.py` | Runtime launcher |
| `~/.cursor/launch-autoapprove/devtools_auto_accept.js` | Runtime injector |
| `~/.cursor/launch-autoapprove/state.json` | Current PID / CDP port / workspace |
| `~/.cursor/launch-autoapprove/dedicated-profile/` | Separate Cursor profile for the dedicated window |
| `~/.cursor/skills/global-launch-cursor-autoapprove/` | Installed slash-command docs |

## Launch Flow

When you run `aa launch ~/code/my-project`, the launcher:

1. Finds a free CDP port near `9222`.
2. Syncs `settings.json` and `keybindings.json` from the default Cursor profile
   (`~/Library/Application Support/Cursor/User/`) into the dedicated profile so
   editor preferences carry over.
3. Records the set of current Cursor main-process PIDs.
4. Launches a new Cursor process with:
   - `--remote-debugging-port=<port>`
   - `--user-data-dir ~/.cursor/launch-autoapprove/dedicated-profile`
   - the requested workspace path
5. Waits for a new Cursor main PID to appear.
6. Saves the PID, port, workspace, and timestamp to `state.json`.
7. Loads `devtools_auto_accept.js`, computes a short content hash, prepends the
   hash and the repo slug as globals, and injects the script via CDP
   `Runtime.evaluate`.
8. Calls `startAccept()`. The injected script continuously maintains the window
   title to `autoapprove ✅ <repo>` (or `⏸` when paused).

The dedicated profile is important. It keeps the launched window separate from
your normal Cursor profile and makes the process boundary obvious.

## Settings Sync

The dedicated Cursor instance uses a separate `--user-data-dir`, which means it
starts with a blank profile. To avoid losing your editor preferences, the
launcher copies these files from your default Cursor profile at each launch:

- `User/settings.json` (editor preferences, terminal config, git path, etc.)
- `User/keybindings.json`

Cursor-specific state like model preferences and agent mode live in
`User/globalStorage/state.vscdb`, a SQLite database that also holds auth tokens
and workspace-specific state. This database is **not** copied because merging it
is fragile and risks auth conflicts. The dedicated profile persists between
launches, so once you set your model preference or agent mode in the dedicated
window, it stays.

## Why `on` Can Refresh Stale Code

The in-window injector is just JavaScript living in the renderer process. If
you edit `devtools_auto_accept.js` on disk and reinstall the skill, an already
running window still has the old code loaded in memory.

To fix that drift, `launcher.py on` now:

1. Calls `acceptStatus()` in the window.
2. Compares the in-window injector hash with the current on-disk injector hash.
3. If they differ, clears the old globals, re-injects the new script, and then
   starts the timer again.

This gives you a clean way to refresh a running dedicated window after a skill
update without manually opening DevTools and pasting code again.

## Continuous Title Maintenance

Cursor's own title management resets `document.title` on file changes, workspace
switches, and focus events. A one-shot title update via CDP would be overwritten
within seconds.

To solve this, the injected script runs a separate `setInterval` (every 3s) that
continuously sets the window title based on its own running/paused state:

- `autoapprove ✅ <repo>` when the approval timer is running
- `autoapprove ⏸ <repo>` when paused

The repo slug is passed from the launcher as
`globalThis.__cursorAutoAcceptRepoSlug` during injection. The title interval
starts on script load (even before `startAccept()` is called), so the window
always shows its auto-approve status. `start()` and `stop()` also call
`_syncTitle()` immediately for instant visual feedback.

On cleanup (`force_reload` or manual clear), the title interval is stopped
alongside the approval timer.

## DOM Matching Strategy

The injector is intentionally simple:

1. Search the siblings above `div.full-input-box` first.
2. If nothing is found, fall back to a broader button scan.
3. Also look for:
   - resume links
   - connection retry prompts

The approval pattern list is ordered from specific to general. For example:

- `accept all` before `accept`
- `always allow` before `allow`

That avoids misclassifying a more specific button as its shorter substring.

## Supported Prompt Labels

The current injector explicitly matches labels such as:

- `Accept`
- `Accept all`
- `Allow`
- `Always allow`
- `Run`
- `Run command`
- `Apply`
- `Execute`
- resume / retry surfaces handled by dedicated logic

The click log returned by `acceptStatus()` records which label family matched.

## Why CDP + DOM Instead of Older Approaches

This skill acts inside the Chromium renderer where Cursor actually renders the
approval buttons. That has several advantages:

- the buttons are real DOM nodes there
- the scope is one renderer / one window
- no dependency on macOS Accessibility exposing Electron internals
- no dependency on shell-hook timing
- no blind process-wide keystrokes

For the full history, see
[`retired-approaches.md`](retired-approaches.md).

## Status Output

`aa status` reports:

- whether the dedicated PID is still alive
- the CDP port
- the workspace
- gate ON/OFF state
- click count
- injector hash
- current window title
- recent click log entries

That output is the fastest way to confirm whether the right window is running
the right injector version.
