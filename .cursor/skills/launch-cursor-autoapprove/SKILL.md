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
gate ON. Bounded agent recovery also starts ON: registered parent-transcript
rows, exact navigation through the `N subagents running` tray, and sequential
cycling across active pinned Agent Window conversations. Collapsed running
trays are materialized within a fixed bound. Simple commands can pause either
behavior later.

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

When the user asks for auto-approval on a **local** workspace, run:

```bash
/usr/bin/python3 "$HOME/.cursor/launch-autoapprove/launcher.py" launch --workspace "$PWD"
/usr/bin/python3 "$HOME/.cursor/launch-autoapprove/launcher.py" status --workspace "$PWD"
```

When the user asks for auto-approval on an **SSH remote** host, run:

```bash
/usr/bin/python3 "$HOME/.cursor/launch-autoapprove/launcher.py" launch-ssh <ssh-host> [/absolute/remote/path]
/usr/bin/python3 "$HOME/.cursor/launch-autoapprove/launcher.py" status -w <workspace-slug>
```

**Always verify `Mode: IDE (verified)` before telling the user launch
succeeded.** The launcher forces Cursor's `--classic` mode, verifies the loaded
`workbench.desktop.main.css/js` bundle, and refuses to inject, enable, or cycle
on a glass/Agents surface. If mode verification fails, report it; do not treat
a workbench URL, generic workbench parts, window title, or successful process
start as proof of IDE mode.

Then tell the user:

> A dedicated Cursor window has opened for this project with auto-approval ON.
> Bounded nested and pinned-agent recovery is also ON. Move your agent work to
> that window. Use `caa off` to pause the gate, `caa on` to resume it,
> `caa cycle --off` to opt out of cycling, and `caa stop` to close the
> dedicated window when done.

The agent does NOT need to deactivate at end of task. The user controls the
lifecycle with `on`/`off`/`stop`.

## Commands

| Command | What it does |
|---------|-------------|
| `launch [-w PATH] [PATH\|ALIAS] [--interval SECONDS]` | Open dedicated Cursor, inject DOM script, and turn the gate plus nested/pinned-agent cycling ON. Accepts a concrete path, a registered local alias, or a registered SSH folder URI alias. The fallback scan defaults to 0.5 seconds (range: 0.25–60). Auto-registers the workspace slug as an alias. Blocks only if the same workspace is already running. Multiple workspaces can run simultaneously. |
| `launch-ssh <host> [/absolute/remote/path] [--no-preflight] [--interval SECONDS]` | Open dedicated Cursor connected to an SSH remote host (from `~/.ssh/config`), inject script, and turn the gate plus nested/pinned-agent cycling ON. Path-specific launches first verify the remote directory with `ssh <host> test -d <path>` so bad host/path pairs fail before creating a profile or alias. |
| `on [-w PATH\|SLUG] [--interval SECONDS]` | Resume auto-clicking (`startAccept()` via CDP). An interval supplied while already ON takes effect immediately and persists for the session. Reloads stale in-window injector code when hash differs. Auto-detected if only one session, otherwise opens an interactive picker in a TTY. |
| `off [-w PATH\|SLUG]` | Pause auto-clicking (`stopAccept()` via CDP) while keeping the dedicated window open. Auto-detected if only one session, otherwise opens an interactive picker in a TTY. |
| `cycle --on\|--off\|--once [-w PATH\|SLUG]` | Control registered parent-transcript rows, exact `N subagents running` tray entries, and pinned top-level agents. Automatic pinned navigation visits active unselected rows in round-robin passes of up to two while the Agent Window is unfocused. `--once` runs one bounded pass, including completed rows. Confirms results, caps retries, restores the original agent/tabs/scroll/focus, and fails closed on drift. |
| `subagents [-w PATH\|SLUG] [--json]` | Show the sanitized renderer task registry, row hints, statuses, attempts, and confirmation timestamps. |
| `status [-w PATH\|SLUG]` | Show verified IDE mode plus session details including last approved command preview, tray advertised/mounted/collapsed state, and nested/pinned visit/confirmation totals. Shows all sessions if `-w` is omitted; if `-w <slug>` is ambiguous, the picker is used. |
| `stop [-w PATH\|SLUG] [--all]` | Pause gate, close dedicated Cursor process, and remove session when shutdown succeeds. Without `-w`, it prefers running sessions when any are alive; if none are running, it falls back to stale entries for cleanup. Use `--all` to stop every session, but do not combine `--all` with `-w` or a positional workspace. |
| `alias [set\|remove\|list]` | Manage workspace aliases stored in `config.json`. `set <name> <path>` registers a new alias (validates the path exists and the name is not already taken). `remove <name>` deletes one. `list` shows all. |
| `history [-w SLUG] [-n LIMIT] [--json] [--commands]` | Show durable event log of session/gate/click events. Persisted across sessions. Use `--commands` for a dedicated command-approval view with readable multiline formatting. |
| `screenshot [-w PATH\|SLUG] [-o FILE]` | Capture PNG screenshot of the dedicated Cursor window via CDP. |
| `diagnose [-w PATH\|SLUG]` | Self-debug: screenshot + DOM snapshot + synthetic probe. Saves artifacts to a timestamped directory. |
| `share-safe [--on\|--off] [-w PATH\|SLUG]` | Discreet window title for screen sharing: restores the title captured at injector load instead of `autoapprove … <repo>`. Cursor’s usual title often still includes the workspace or file name—this mode only removes the autoapprove branding. Toggle with no flags, or set `--on` / `--off`. Preference is stored on the **current session** (cleared when you `stop` or the session is garbage-collected) and reapplied after `on` / injector reload. |
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

1. `launch` resolves the argument as a local path or alias. If the alias target
   is a `vscode-remote://ssh-remote+...` folder URI, it uses the SSH launch flow.
2. `launch` syncs `settings.json`, `keybindings.json`, and auth tokens from
   your default Cursor profile so editor preferences and login carry over to
   the dedicated window. It also auto-registers the workspace slug as an alias
   in `config.json` for quick future launches.
3. `launch` first requires Cursor CLI help to advertise the version-coupled
   `--classic` flag, then starts a full IDE window with
   `--remote-debugging-port`, `--user-data-dir`, `--classic`, `--new-window`,
   and an explicit local path or SSH folder URI. It never requests `--chat` or
   `--glass`. Each workspace gets its own persistent profile at
   `~/.cursor/launch-autoapprove/dedicated-profile-<slug>/`.
4. Before injection, the launcher requires a CDP target that loaded
   `workbench.desktop.main.css/js`; `workbench.glass.main.css/js` is rejected.
   Generic workbench parts are only secondary diagnostics. A new process that
   exposes Agents/unknown UI is closed and removed from session state.
5. The launcher injects `devtools_auto_accept.js` via CDP `Runtime.evaluate`,
   passing the repo slug so the script knows the project name. The chosen
   CDP target is pinned by ID in `state.json` so all subsequent commands
   (`on`/`off`/`status`/`stop`) address exactly that page.
6. The injector uses a MutationObserver (300ms debounce) for fast detection,
   with a configurable fallback poll (0.5 seconds by default), and clicks at
   most one eligible candidate per scan. Distinct prompts can be clicked on
   consecutive scans; the same unresolved prompt stays deduped for eight
   seconds.
7. The injector continuously maintains the window title
   (`autoapprove ✅ <repo>` or `autoapprove ⏸ <repo>`) via a 3-second
   interval, so the title self-heals if Cursor resets it — unless
   **share-safe** mode is on (`caa share-safe --on`), in which case the
   title bar reuses the text captured when the script was first injected
   (normal Cursor-style title for that moment).
8. `on`/`off` call `startAccept()`/`stopAccept()` via CDP -- no manual
   DevTools interaction needed.
9. Process-level isolation: the dedicated window is a separate OS process,
   so auto-clicking cannot leak to your normal Cursor windows.
10. If the installed injector changed after the window was launched, `on`
   reloads the in-window script so the running window picks up the latest
   pattern fixes.
11. Default-on nested recovery records exact mounted task-row identity and
    revisits registered unmounted rows through the TanStack virtualizer, scoped
    to the exact currently mounted parent composer. As a backup, it expands an
    exact collapsed running-subagent tray, re-resolves each entry after parent
    restoration, mounts each read-only child editor, handles eligible approvals
    there, and restores the original tray/tabs/focus state. Both paths count
    confirmations separately from click attempts.
    Automatic cycles pause while the focused window has its terminal or another
    non-composer editor active; focus settling follows newer user interaction
    instead of restoring a stale snapshot. Use `caa cycle --off` for the
    explicit opt-out.
    Child navigation keeps a long transcript selected while its exact
    virtualized tail is materialized for up to five seconds. Empty children and
    exhausted prompts then receive bounded probe backoff instead of being
    remounted every cycle.
    Mounted parent `Allow` cards remain eligible to the ordinary direct scanner;
    that path gets one attempt per task-scoped fingerprint. Registered-row
    recovery leases only the exact task it is actively confirming. Both paths
    share a task-scoped cooldown, while tray navigation remains an independent
    child-editor backup.
12. Active pinned Agent Window conversations are visited sequentially because
    Cursor mounts only the selected conversation. Automatic visits happen only
    while the window is unfocused, skip the selected row, reject duplicate
    titles inside Pinned, and restore the original agent and scroll position. Explicit
    `cycle --once` visits completed pinned rows too for bounded validation.
    Title identity is scoped to the exact Pinned section so Cursor's duplicate
    history projection does not block cycling; same-title duplicates inside
    Pinned still fail closed.
13. Renderer safety bounds rate-limit mutation scans, cache private
    virtualizer snapshots, cap cycle duration, and turn the gate OFF after
    repeated slow scans or JavaScript heap use above 4 GiB.

Inactive top-level sidebar agents are not mounted chat surfaces in Cursor
3.12.17, so the injector cycles pinned conversations sequentially rather than
clicking them simultaneously. The tray fallback remains distinct: it selects
nested children listed under `N subagents running` and scans their read-only
editors. Separate visible dedicated windows can also work in parallel even when
one is not OS-focused; minimized/hidden windows still need direct validation.

**Note on Cursor-specific preferences**: Model selection, agent mode, and
similar UI state live in `state.vscdb` (a per-profile SQLite database) and
are not synced. The dedicated profile persists between launches, so set these
once in the dedicated window and they will stick.

If you previously used the retired `cursor-autoapprove` approach, remove stale
global artifacts (`~/.cursor/skills/global-cursor-autoapprove/`,
`~/.cursor/auto-approval/`, and old `beforeShellExecution` hook entries in
`~/.cursor/hooks.json`) to avoid conflicts.

## Testing

Launcher behavior has unit coverage; DOM behavior still requires a live Cursor
window plus real approval prompts.

Minimum verification after executable changes:

```bash
bash "$(git rev-parse --show-toplevel)/.cursor/skills/launch-cursor-autoapprove/scripts/install.sh" --target global --force
/usr/bin/python3 -m unittest discover -s "$(git rev-parse --show-toplevel)/.cursor/skills/launch-cursor-autoapprove/tests" -p "test_*.py"
/usr/bin/python3 "$HOME/.cursor/launch-autoapprove/launcher.py" help
/usr/bin/python3 "$HOME/.cursor/launch-autoapprove/launcher.py" status
```

If a dedicated window is already running, also verify `on` can refresh stale
injector code and that `status` reports a hash, fallback poll interval, and
click count. Verify `on --interval 2` updates a running timer, then restore
the default with `on --interval 0.5`. If multiple
sessions are active, also verify the interactive picker works for
`on`/`off`/`stop`, plus `status -w <slug>` when a slug is ambiguous.

## Additional Reference

- [Implementation details](references/implementation.md)
- [Manual testing guide](references/manual-testing.md)
- [Subagent approval cycling design](references/subagent-approval-cycling.md)
- [Why older approaches were retired](references/retired-approaches.md)
