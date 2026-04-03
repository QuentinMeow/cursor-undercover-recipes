# Implementation Details

## Scope and Design

`launch-cursor-autoapprove` intentionally does one thing: run approval clicking
inside a dedicated Cursor process.

Design constraints:

- one-or-more dedicated Cursor processes (one per workspace, each with its own `--user-data-dir`)
- one DOM injector per dedicated process
- one multi-session state file tracking all active sessions
- no global shell hook
- no AX watcher
- no process-wide keystroke spam

This narrow scope is why this is the supported approach and older approaches
were retired.

## CLI Surface (`launcher.py`)

| Command | Flags | Behavior |
|---|---|---|
| `launch` | `--workspace`/`-w`, positional `PATH` | Start dedicated Cursor for workspace, inject script, turn gate ON. |
| `on` | `-w PATH\|SLUG` (optional) | Turn gate ON; reload script if hash drift is detected. |
| `off` | `-w PATH\|SLUG` (optional) | Turn gate OFF; keep dedicated window open. |
| `status` | `-w PATH\|SLUG` (optional) | Print session details. Shows all sessions if `-w` omitted; ambiguous slugs use the picker. |
| `stop` | `-w PATH\|SLUG` (optional), `--all` | Turn gate OFF, terminate dedicated process, and remove session entry when shutdown succeeds. `--all` must not be combined with `-w` or a positional workspace. |
| `help` | optional `COMMAND` topic | Print usage examples, command help, and deeper-doc paths. |

Behavior notes:

- Multiple workspaces can run simultaneously, each with its own PID, CDP port,
  and profile directory.
- `launch` only blocks if the same workspace is already running.
- `on` / `off` auto-detect the target when one running session matches.
- `stop` prefers running sessions when any are alive, but `stop -w ...` can
  still target a stale session entry for cleanup.
- With multiple matches in an interactive terminal, the launcher opens an
  arrow-key picker instead of hard-failing.
- In non-interactive shells, ambiguous `on` / `off` / `stop`, plus
  `status -w <slug>` when that slug matches multiple sessions, still require a
  full path or other disambiguation so the command exits cleanly instead of
  hanging.
- `help` resolves docs by checking `SCRIPT_DIR.parent / "SKILL.md"` first,
  then `SCRIPT_DIR.parent / "skills" / "launch-cursor-autoapprove" / "SKILL.md"`,
  and finally `~/.cursor/skills/global-launch-cursor-autoapprove/SKILL.md`.
- If two sessions share the same slug, `-w <slug>` is treated as ambiguous; use
  the full workspace path instead.
- There is no supported `inject --restart` or same-profile mode in this
  launcher.

## Installer Surface (`install.sh`)

| Flag | Meaning |
|---|---|
| `--target global` | Install runtime to `~/.cursor/launch-autoapprove/` and skill docs to `~/.cursor/skills/global-launch-cursor-autoapprove/`. |
| `--target /path/to/repo` | Install skill docs and launcher entrypoint into that repo's `.cursor/`. Runtime still uses `~/.cursor/launch-autoapprove/`. |
| `--force` | Overwrite existing installed files. |
| `--dry-run` | Print actions without writing files. |

## Runtime Layout

After global install:

| Path | Purpose |
|---|---|
| `~/.cursor/launch-autoapprove/launcher.py` | Runtime launcher |
| `~/.cursor/launch-autoapprove/devtools_auto_accept.js` | Runtime injector script |
| `~/.cursor/launch-autoapprove/state.json` | Persisted multi-session state (may include stale entries until cleaned up) |
| `~/.cursor/launch-autoapprove/history.jsonl` | Append-only NDJSON event log (rotates at 5 MB) |
| `~/.cursor/launch-autoapprove/dedicated-profile-<slug>/` | Per-workspace Cursor profile |
| `~/.cursor/skills/global-launch-cursor-autoapprove/` | Global slash-command docs |

`state.json` structure:

```json
{
  "sessions": {
    "<workspace-path>": {
      "pid": 12345,
      "cdp_port": 9222,
      "workspace": "<workspace-path>",
      "slug": "<directory-name>",
      "launched_at": "<UTC ISO timestamp>",
      "cdp_target_id": "<CDP page target ID>"
    }
  }
}
```

### Event History (`history.jsonl`)

`~/.cursor/launch-autoapprove/history.jsonl` is an append-only NDJSON log
of session lifecycle and gate events. It rotates at 5 MB. Each line is a
JSON object with at least `ts`, `record_type`, `workspace`, and `slug`.

Recorded event types:
- `session` — launch, stop
- `gate` — on, off
- `click` — auto-click events (when reported by injector)

View with `caa history [-w SLUG] [-n LIMIT] [--json]`.

Legacy single-session format (flat `{pid, cdp_port, workspace}`) is auto-migrated
on first read. The legacy `dedicated-profile/` directory is renamed to
`dedicated-profile-<slug>/` during migration.

## Launch Flow (Step-by-Step)

When you run `caa launch --workspace <path>`:

1. Check if this workspace already has a running session; block if so.
2. Compute slug (handle collision by appending path hash if needed).
3. Create runtime and per-slug profile directories if missing.
4. Copy `settings.json` and `keybindings.json` from default Cursor profile.
5. Select an available local CDP port (starting near `9222`).
6. Snapshot existing Cursor main PIDs.
7. Launch Cursor with:
   - `--remote-debugging-port=<port>`
   - `--user-data-dir ~/.cursor/launch-autoapprove/dedicated-profile-<slug>`
   - `<workspace>`
8. Wait for a new Cursor main PID that includes the expected launch args.
9. Save session to `state.json` under the workspace path key.
10. Inject `devtools_auto_accept.js` via CDP `Runtime.evaluate`.
11. Call `startAccept()` and sync title to `autoapprove ✅ <repo>`.

If `open -na` path detection fails, the launcher falls back to direct executable
launch and repeats PID detection.

## CDP Target Selection and Stable Binding

At launch time, `_cdp_select_workbench_target()` picks the best workbench
page target from `/json` and stores its `id` in `state.json` as
`cdp_target_id`. All subsequent commands (`on`, `off`, `status`, `stop`) pass
this ID to `_cdp_evaluate()`, which looks up the specific target by ID rather
than iterating through all pages.

If the bound target ID is not found in the current `/json` listing, the
command fails closed with a clear error. If `target_id` is `None` (backward
compatibility or fresh launch before the target is pinned), the legacy
workbench-first heuristic is used.

`caa status` reports:
- The bound target ID
- Total page target count on the port
- A WARNING if multiple workbench targets exist (indicating a possible extra
  manual window in the same process)
- A WARNING if the bound target is missing (indicating the session needs
  rebinding via `caa on`)
- Injector hash drift detection (in-window hash vs on-disk hash)

## Injector Path Selection (Repo vs Installed)

`_dom_injector_path()` resolves injector source this way:

1. If running installed launcher (`SCRIPT_DIR == RUNTIME_DIR`) and installed
   injector exists, use installed injector.
2. Else, if repo-local injector exists next to the launcher script, use that.
3. Else fallback to installed injector path.

This prevents development confusion where running the repo launcher silently
loads stale installed JS.

## DOM Injector Internals (`devtools_auto_accept.js`)

### Timers and State

- Poll interval: `2000ms` (`state.interval`)
- Title sync interval: `3000ms` (`state.titleTimer`)
- Tracks click history in memory (`state.clicks`, max 100 entries)

### Candidate Discovery

Approval candidates are collected in this order:

1. Siblings above `div.full-input-box` (chat-adjacent scan, depth <= 5)
2. If step 1 found nothing, prompt roots (`role=dialog`, `role=alertdialog`,
   `aria-modal`) -- excludes class-based selectors
3. If steps 1-2 found nothing, fallback to the nearest composer/chat root from
   input box ancestry
4. Always append optional resume links (`command:composer.resumeCurrentChat`)
5. Always append optional connection retry in modal dialogs containing
   "connection failed" / "connection error"

### Matching Rules

Approval labels are matched by exact normalized text:

- Normalize by lowercasing, trimming, stripping trailing shortcut hints:
  - parenthesized hints, e.g. `(⌃⏎)`
  - trailing glyphs, e.g. `↩`
- Compare with `===` against known patterns:
  - `accept all`, `accept`, `always allow`, `allow`
  - `run this time only`, `run command`, `run`
  - `apply`, `execute`, `continue`
  - `switch`, `switch mode`, `change mode`, `confirm`

Safety filters:

- ignore elements in excluded zones:
  - `workbench.parts.sidebar`
  - `workbench.parts.editor`
  - `workbench.parts.panel`
  - `workbench.parts.statusbar`
  - `workbench.parts.activitybar`
  - `workbench.parts.auxiliarybar`
- ignore labels longer than 60 chars
- require `isVisible()` and `isClickable()`

### Dismissal Proximity Guard

For approval and connection candidates, the injector requires a nearby dismissal
control (`skip`, `cancel`, `dismiss`, `deny`, `not now`, `close`) within
ancestor depth <= 3 before clicking. The guard stops ascending at workbench part
boundaries to avoid cross-region false matches.

Resume links bypass the guard since they use a specific `data-link` attribute.

### Click Strategy

Clicking is intentionally conservative:

1. call native `el.click()` when available
2. fallback to dispatching a single mouse click event

No `el.focus()` is called to avoid stealing OS focus from the user's normal
Cursor window. No synthetic Enter keydowns are dispatched.

### Click Prioritization

Candidates are prioritized by `kind`:

1. `approval`
2. `connection`
3. `resume`

Only one candidate is clicked per poll interval.

## Hash Handshake and Reload

`on` performs drift detection:

1. call `acceptStatus()` in-window
2. load current injector file + hash
3. if hash mismatches (or status is unavailable), clear old globals, re-inject,
   then call `startAccept()`

This is the fix from issue `001-running-window-keeps-stale-injector`.

## Dedicated Profile Behavior

Each dedicated process uses a per-workspace `--user-data-dir` profile at
`~/.cursor/launch-autoapprove/dedicated-profile-<slug>/`.

Copied each launch:

- `User/settings.json`
- `User/keybindings.json`

Not copied:

- `User/globalStorage/state.vscdb` (chat/account/model state)
- extension runtime state

Each per-workspace profile persists between launches, so dedicated-window-specific
settings remain there until manually removed.

## Status Output and Evidence

`caa status` includes:

- PID + running/stopped state
- CDP port
- workspace
- bound CDP target ID
- page target count on port
- gate ON/OFF
- click count
- injector hash (with drift warning if mismatched)
- current window title
- recent click entries (last 3 printed)
- WARNING if multiple workbench targets exist on the port
- WARNING if the bound target is missing

Use this output as primary evidence during manual validation.

`caa history` provides a durable event log complementing the in-memory
status — even after sessions are stopped or the process crashes.

## Known Limits

- DOM selectors are best-effort against a changing product UI.
- Connection retry detection still uses container text heuristics.
- Excluded zones prevent known false positives, but may need tuning if Cursor
  changes where prompts are rendered.
- CDP port allocation uses a local free-port probe and can race on very busy
  hosts (rare).

## Related Docs

- [Manual testing guide](manual-testing.md)
- [Retired approaches and migration context](retired-approaches.md)
