# Implementation Details

## Scope and Design

`launch-cursor-autoapprove` intentionally does one thing: run approval clicking
inside a dedicated Cursor process.

Design constraints:

- one dedicated Cursor process (`--user-data-dir`)
- one DOM injector in that process
- one runtime state file
- no global shell hook
- no AX watcher
- no process-wide keystroke spam

This narrow scope is why this is the supported approach and older approaches
were retired.

## CLI Surface (`launcher.py`)

| Command | Flags | Behavior |
|---|---|---|
| `launch` | `--workspace`, `-w`, positional `PATH` | Start dedicated Cursor, inject script, turn gate ON. |
| `on` | none | Turn gate ON; reload script if hash drift is detected. |
| `off` | none | Turn gate OFF; keep dedicated window open. |
| `status` | none | Print PID/port/workspace/gate/hash/recent clicks. |
| `stop` | none | Turn gate OFF, terminate dedicated process, clear session file. |

Behavior notes:

- If an active dedicated PID already exists in `state.json`, `launch` exits and
  asks you to run `stop` first.
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
| `~/.cursor/launch-autoapprove/state.json` | Current session record |
| `~/.cursor/launch-autoapprove/dedicated-profile/` | Dedicated Cursor profile |
| `~/.cursor/skills/global-launch-cursor-autoapprove/` | Global slash-command docs |

`state.json` fields:

- `pid`: dedicated Cursor main process PID
- `cdp_port`: debugger port used for CDP
- `workspace`: absolute workspace path
- `launched_at`: UTC ISO timestamp

## Launch Flow (Step-by-Step)

When you run `aa launch --workspace <path>`:

1. Create runtime/profile directories if missing.
2. Copy `settings.json` and `keybindings.json` from default Cursor profile.
3. Select an available local CDP port (starting near `9222`).
4. Snapshot existing Cursor main PIDs.
5. Launch Cursor with:
   - `--remote-debugging-port=<port>`
   - `--user-data-dir ~/.cursor/launch-autoapprove/dedicated-profile`
   - `<workspace>`
6. Wait for a new Cursor main PID that includes the expected launch args.
7. Save `pid`, `cdp_port`, `workspace`, `launched_at` to `state.json`.
8. Inject `devtools_auto_accept.js` via CDP `Runtime.evaluate`.
9. Call `startAccept()` and sync title to `autoapprove ✅ <repo>`.

If `open -na` path detection fails, the launcher falls back to direct executable
launch and repeats PID detection.

## CDP Target Selection and Evaluation

`_cdp_evaluate()` requests `/json`, collects all `type == "page"` targets, and
tries each websocket target until one successfully evaluates the expression.

This avoids hard-failing when the first page target is not the active workbench
surface.

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

- Poll interval: `2000ms` (`state.timer`)
- Title sync interval: `3000ms` (`state.titleTimer`)
- Tracks click history in memory (`state.clicks`, max 100 entries)

### Candidate Discovery

Approval candidates are collected in this order:

1. Siblings above `div.full-input-box` (chat-adjacent scan, depth <= 5)
2. Prompt roots (`role=dialog`, `aria-modal`, popover/dropdown class roots)
3. Fallback to nearest composer/chat root from input box ancestry
4. Optional resume links (`command:composer.resumeCurrentChat`)
5. Optional connection retry prompts (`Resume` / `Try again`)

### Matching Rules

Approval labels are matched by exact normalized text:

- Normalize by lowercasing, trimming, stripping trailing shortcut hints:
  - parenthesized hints, e.g. `(⌃⏎)`
  - trailing glyphs, e.g. `↩`
- Compare with `===` against known patterns:
  - `accept all`, `accept`, `always allow`, `allow`
  - `run this time only`, `run command`, `run`
  - `apply`, `execute`, `continue`

Safety filters:

- ignore elements in excluded zones:
  - `workbench.parts.sidebar`
  - `workbench.parts.editor`
- ignore labels longer than 60 chars
- require `isVisible()` and `isClickable()`

### Dismissal Proximity Guard

For generic approval candidates (`kind == "approval"`), the injector requires a
nearby dismissal control (`skip`, `cancel`, `dismiss`, `deny`, `not now`,
`close`) within ancestor depth <= 6 before clicking.

This reduces false positives on unrelated `Run`/`Allow` controls.

### Click Strategy

Clicking is intentionally conservative:

1. focus target if possible
2. call native `el.click()` when available
3. fallback to dispatching a single mouse click event

It no longer sends synthetic Enter keydowns as a blind fallback.

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

The dedicated process uses a separate `--user-data-dir` profile.

Copied each launch:

- `User/settings.json`
- `User/keybindings.json`

Not copied:

- `User/globalStorage/state.vscdb` (chat/account/model state)
- extension runtime state

The dedicated profile persists between launches, so dedicated-window-specific
settings remain there until manually removed.

## Status Output and Evidence

`aa status` includes:

- PID + running/stopped state
- CDP port
- workspace
- gate ON/OFF
- click count
- injector hash
- current window title
- recent click entries (last 3 printed)

Use this output as primary evidence during manual validation.

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
