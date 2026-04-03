# Implementation Details

## Scope and Design

`launch-cursor-autoapprove` intentionally does one thing: run approval clicking
inside a dedicated Cursor process.

Design constraints:

- one-or-more dedicated Cursor processes (one per workspace, each with its own `--user-data-dir`)
- one DOM injector per dedicated process
- one multi-session state file tracking all active sessions
- no global shell hook (stale hooks are detected and warned)
- no AX watcher
- no process-wide keystroke spam

This narrow scope is why this is the supported approach and older approaches
were retired.

## Architecture (Observer + Policy + Event Sink)

The injector uses a three-layer architecture:

1. **Surface Observer**: A `MutationObserver` detects DOM changes immediately.
   A fallback poll (`setInterval` at 2s) catches anything the observer misses.
2. **Policy Engine**: Separates candidate discovery (finding buttons) from
   click decisions (eligibility guards, fingerprint cooldown).
3. **Event Sink**: All decisions (click, blocked, unknown) are queued in
   `state.eventQueue`. The launcher drains this queue via CDP and persists
   events to `history.jsonl` and per-prompt artifact files under
   `~/.cursor/launch-autoapprove/prompt-artifacts/`.

Prompt fingerprinting (sorted button labels within the prompt root) prevents
the same unresolved prompt from being clicked repeatedly every poll cycle.
Fingerprints have an 8-second cooldown.

A feature-flagged state probe (`state.enableStateProbe`) can check for
internal Cursor approval indicators before DOM scanning. This is off by
default and intended for future hardening as internal APIs stabilize.

## CLI Surface (`launcher.py`)

| Command | Flags | Behavior |
|---|---|---|
| `launch` | `--workspace`/`-w`, positional `PATH` | Start dedicated Cursor for workspace, inject script, turn gate ON. |
| `on` | `-w PATH\|SLUG` (optional) | Turn gate ON; reload script if hash drift is detected. |
| `off` | `-w PATH\|SLUG` (optional) | Turn gate OFF; keep dedicated window open. |
| `status` | `-w PATH\|SLUG` (optional) | Print session details. Shows all sessions if `-w` omitted; ambiguous slugs use the picker. |
| `stop` | `-w PATH\|SLUG` (optional), `--all` | Turn gate OFF, terminate dedicated process, and remove session entry when shutdown succeeds. `--all` must not be combined with `-w` or a positional workspace. |
| `alias` | `set <name> <path>`, `remove <name>`, `list` | Manage workspace aliases stored in `config.json`. See [Workspace Aliases](#workspace-aliases-configjson) below. |
| `history` | `-w SLUG`, `-n LIMIT`, `--json` | Show persisted event log (session/gate/click events). |
| `screenshot` | `-w PATH\|SLUG`, `-o FILE` | Capture PNG screenshot of the dedicated window via CDP. |
| `diagnose` | `-w PATH\|SLUG` | Self-debug: screenshot + DOM snapshot + synthetic probe + summary. |
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
| `~/.cursor/launch-autoapprove/state.json` | Persisted multi-session state (auto-GC'd on every load) |
| `~/.cursor/launch-autoapprove/config.json` | Workspace aliases and user configuration |
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
of all skill events. It rotates at 5 MB. Each line is a JSON object with at
least `ts`, `record_type`, `workspace`, and `slug`.

Recorded event types:
- `session` — launch, stop
- `gate` — on, off
- `click` — auto-click events (drained from injector queue by launcher)
- `blocked_candidate` — buttons in trusted context that failed eligibility
- `unknown_prompt` — buttons outside trusted context (potential missing patterns)
- `state_probe` — internal state probe results (when feature-flagged)

The `click`, `blocked_candidate`, and `unknown_prompt` events include a
`fingerprint` field (sorted button labels within the prompt root), a `prompt`
subtree capture, and the eligibility `reason`.

Per-prompt artifact files are also written to
`~/.cursor/launch-autoapprove/prompt-artifacts/` for blocked and unknown events.

View with `caa history [-w SLUG] [-n LIMIT] [--json]`.

Legacy single-session format (flat `{pid, cdp_port, workspace}`) is auto-migrated
on first read. The legacy `dedicated-profile/` directory is renamed to
`dedicated-profile-<slug>/` during migration.

### Automatic Session Garbage Collection

Every call to `_load_state()` prunes invalid sessions. A session is removed
when ANY of these conditions is true:

- **PID dead** — the Cursor process exited (a dead PID cannot be revived).
- **Workspace path missing** — the directory in the session key no longer
  exists on disk. This catches ghost sessions from bad launch paths. If the
  Cursor process is still alive, it is terminated first since a window on a
  non-existent path is always broken.

### Workspace Resolution

`caa launch <arg>` resolves the workspace argument in this order:

1. If `<arg>` is omitted, use the current working directory.
2. Expand `~` and resolve to an absolute path. If the result is an existing
   directory, use it.
3. Treat `<arg>` as an alias name — look it up in `config.json`.
4. If no match is found, error out with a list of known aliases.

This prevents ghost sessions from bare-name arguments (e.g. `caa launch gocmp`
from the home directory resolving to the non-existent `~/gocmp`).

### Workspace Aliases (`config.json`)

`~/.cursor/launch-autoapprove/config.json` stores user-defined workspace
aliases:

```json
{
  "aliases": {
    "gocmp": "/Users/qmiao/code/gocmp",
    "recipes": "/Users/qmiao/code/cursor-undercover-recipes"
  }
}
```

Aliases are populated two ways:

- **Automatic**: Every successful `caa launch <path>` auto-registers the
  directory basename as an alias (e.g. launching `/Users/qmiao/code/gocmp`
  registers `gocmp`). It does not overwrite if the name already points to a
  different path.
- **Explicit**: `caa alias set <name> <path>` registers a custom name. The
  path must exist and the name must not collide with an existing alias for a
  different path.

`caa alias list` shows all aliases. `caa alias remove <name>` deletes one.

## Launch Flow (Step-by-Step)

When you run `caa launch --workspace <path>`:

1. Resolve workspace path (see Workspace Resolution above).
2. Check if this workspace already has a running session; block if so.
3. Compute slug (handle collision by appending path hash if needed).
4. Create runtime and per-slug profile directories if missing.
5. Copy `settings.json`, `keybindings.json`, and auth tokens from default Cursor profile.
6. Select an available local CDP port (starting near `9222`).
7. Snapshot existing Cursor main PIDs.
8. Launch Cursor with:
   - `--remote-debugging-port=<port>`
   - `--user-data-dir ~/.cursor/launch-autoapprove/dedicated-profile-<slug>`
   - `<workspace>`
9. Wait for a new Cursor main PID that includes the expected launch args.
10. Save session to `state.json` under the workspace path key.
11. Inject `devtools_auto_accept.js` via CDP `Runtime.evaluate`.
12. Call `startAccept()` and sync title to `autoapprove ✅ <repo>`.

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

### Stale-Hook Detection

At launch and status time, the launcher scans for retired approval hooks in
`.cursor/hooks.json` (both repo-local and `~/.cursor/hooks.json`). If any
hook command matches patterns from retired skills (`auto-approval`,
`cursor-autoapprove`, `personal-cursor-quickapprove`), a WARNING is printed
to stderr. This prevents the split-brain scenario where two approval systems
run simultaneously.

## DOM Injector Internals (`devtools_auto_accept.js`)

### Timers, Observer, and State

- `MutationObserver` on `document.body` (childList, subtree, attributes)
  with 300ms debounce fires `checkAndClick` on DOM changes
- Fallback poll interval: `2000ms` (`state.interval`)
- Title sync interval: `3000ms` (`state.titleTimer`)
- Tracks click history in memory (`state.clicks`, max 100 entries)
- Event queue (`state.eventQueue`, max 200 entries) for launcher to drain
- Fingerprint cooldown map (`state.fingerprintCooldowns`, 8s per fingerprint)

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
  - trailing plain-text `Esc`/`Escape` hints on dismiss buttons, e.g. `Skip Esc`
- Compare with `===` against known patterns:
  - `accept all`, `accept`, `approve`, `approve request`,
    `approve terminal command`, `always allow`, `allow`
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

### Eligibility Guard

Approval buttons are only clicked if they pass one of four eligibility paths
(checked in order by `_eligibilityReason`):

0. **Trusted prompt context** — all non-resume/non-connection candidates must
   be inside a modal prompt root (`dialog`/`alertdialog`/`aria-modal`) or a
   composer/chat surface that contains `div.full-input-box`. This context gate
   avoids accepting generic labels in unrelated UI areas.
1. **Resume** — `btn.kind === "resume"` (specific `data-link` attribute)
2. **Dismissal proximity** — `hasNearbyDismissal(btn.el)`: a nearby control
   matching `DISMISS_PATTERNS` (`skip`, `cancel`, `dismiss`, `deny`, `not now`,
   `close`, `reject`, `don't allow`, `decline`) within ancestor depth <= 3.
   The guard stops ascending at `workbench.parts.*` boundaries.
3. **Companion proximity** — `hasNearbyCompanion(btn.el)`: a nearby control
   matching `COMPANION_PATTERNS` (`view`, `stop`, `details`, `show details`)
   within the same ancestor-depth walk. Companion controls indicate a real
   approval surface without being dismissals. Same hygiene: visibility,
   clickability, excluded-zone checks.
4. **Modal single-action** — `isModalSingleActionApprove(btn)`: allow
   `approve*` IDs without nearby dismissal only when:
   - candidate is inside modal prompt roots (`dialog`/`alertdialog`/`aria-modal`)
   - root is visible and not in excluded zones
   - root has no visible dismissal control
   - root has <= 2 short visible clickable controls

Both dismissal and companion checks use shared helpers (`_matchesLabelSet`,
`_hasNearbyMatch`) to ensure consistent safety logic.

Each click is logged with a `reason` field (`dismiss`, `companion`, `modal`,
`resume`) for post-hoc diagnostics.

### Debug Snapshot API (harness introspection)

The injector exposes `acceptDebugSnapshot()` for evidence-first harnesses.

Returned fields include:

- `strategyVersion` and `scriptHash`
- `visibleButtons` (normalized labels + surface classification + guard signals)
- `candidates` and `eligible` lists (with per-button eligibility reason)

This allows stress harnesses to capture machine-readable "why" evidence for
both clicked and non-clicked cases.

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

Only one candidate is clicked per poll interval (or observer-triggered cycle).

### Click Deduplication (Fingerprint Cooldown)

Each prompt's fingerprint is computed from the sorted normalized labels of
all buttons within the prompt root. After a click, the fingerprint enters an
8-second cooldown. During cooldown, the same prompt cannot be clicked again.
This prevents the double-click problem where a prompt that doesn't immediately
disappear gets clicked on every poll cycle.

### Event Queue and Launcher Drain

All click, blocked, and unknown events are pushed to `state.eventQueue`.
The launcher drains this queue via CDP `Runtime.evaluate` during `status`,
`on`, and periodic checks. Drained events are persisted to `history.jsonl`
and (for blocked/unknown) to per-prompt artifact files.

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
- `cursorAuth/*` rows from `User/globalStorage/state.vscdb` (auth tokens only)

Not copied:

- Non-auth rows in `User/globalStorage/state.vscdb` (model selection, chat state)
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

## Self-Debug Commands

### `caa screenshot`

Captures a PNG screenshot of the dedicated Cursor window via CDP
`Page.captureScreenshot`. Uses a generic `_cdp_send_method` helper that can
send arbitrary CDP methods against the bound target.

Output: timestamped PNG file in the runtime directory.

### `caa diagnose`

Runs a 4-step self-contained diagnostic without human involvement:

1. **Screenshot** — captures current window state as PNG
2. **DOM snapshot** — evaluates a JS expression that collects all visible
   button-like elements with their text, excluded-zone status, dialog
   membership, and the current injector `acceptStatus()`
3. **Synthetic probe** — injects a View+Allow dialog, waits one poll interval,
   checks if click count incremented and the probe was clicked
4. **Summary** — reports PASS/FAIL with all artifacts saved to a timestamped
   directory

This enables agents to self-debug auto-click failures by inspecting DOM state,
visual state, and click behavior without requiring human screenshots or
interaction.

### Stress Test

`scripts/stress_test.py` supports three harness modes:

- `--mode snapshot` (default): captures real live UI snapshots and screenshots.
- `--mode synthetic`: runs probe-based assertions.
  - `--suite meaningful` (default for synthetic): short, combined, high-signal cases.
  - `--suite full`: original full matrix for deep regression checks.
- `--mode replay`: loads sanitized real-prompt fixture JSON files from
  `tests/fixtures/real-prompts/` and replays them as CDP-injected probes.
  Asserts click correctness and single-click deduplication.

Each probe is injected via `createElement` + `setAttribute` (not `innerHTML`,
which unreliably sets ARIA attributes), waits one poll interval, and verifies
whether the injector clicked the correct button or correctly ignored it.
The harness clears injector fingerprint cooldowns before each synthetic or
replay case so repeated label sets do not contaminate later assertions.

Artifact-first output:

- snapshot mode:
  - `logs/<run-id>-harness-snapshot/snapshot-summary.json`
  - `logs/<run-id>-harness-snapshot/snapshots/<tick>.json`
  - `logs/<run-id>-harness-snapshot/screenshots/<tick>.png`
- synthetic mode:
  - `logs/<run-id>-harness-synthetic/stress-test-results.json`
  - `logs/<run-id>-harness-synthetic/screenshots/*-before.png` and `*-after.png`
  - `logs/<run-id>-harness-synthetic/cases/<N>.json` with spec, expected/actual result, and
  `acceptDebugSnapshot()` output before/after injection

### Real-Prompt Fixture Corpus

Sanitized real prompt captures live in
`tests/fixtures/real-prompts/*.json`. Each fixture specifies:

- `spec`: probe injection parameters (role, modal, buttons)
- `expect_click`: whether the injector should click
- `expect_id`: which pattern ID should match
- `expect_single_click`: whether only one click should occur (dedupe check)

New misses from production should be sanitized and added as fixtures to
prevent regression.

## Known Limits

- DOM selectors are best-effort against a changing product UI.
- Connection retry detection still uses container text heuristics.
- Excluded zones prevent known false positives, but may need tuning if Cursor
  changes where prompts are rendered.
- CDP port allocation uses a local free-port probe and can race on very busy
  hosts (rare).
- The state probe is experimental and off by default. Internal Cursor APIs
  may change without notice.
- **Window must be in foreground**: The DOM injector uses `el.click()` and
  MutationObserver, both of which require the Chromium renderer to be active.
  When the dedicated Cursor window is not the frontmost window (e.g., hidden
  behind other windows or minimized), Chromium throttles timers and may
  suspend DOM updates, so approval prompts will not be detected or clicked
  until the window is brought back to the foreground. This means running
  parallel agent chats across multiple windows is not currently supported --
  only the foreground auto-approve window will reliably click prompts.

## Related Docs

- [Manual testing guide](manual-testing.md)
- [Retired approaches and migration context](retired-approaches.md)

---

## Cursor 3.0.8 DOM Structure Changes (2026-04-03)

### Agent Chat in Auxiliary Bar

Starting with Cursor 3.0.8, the agent chat panel renders inside `workbench.parts.auxiliarybar`. Previous versions used a different workbench part. The DOM hierarchy is:

```
[id="workbench.parts.auxiliarybar"]
  └── ... (several layers)
      └── div.composer-bar.editor
            ├── div.conversations (chat messages + approval buttons)
            └── div (unnamed)
                └── div.composer-input-blur-wrapper
                      └── div.full-input-box (chat input)
```

Key change: `div.full-input-box` is no longer a sibling of `div.conversations`. They are cousins, separated by 2 DOM levels.

### Excluded Zone Escape Hatch

The injector's `isInExcludedZone()` now checks whether the excluded zone also hosts a chat surface:

```javascript
function isInExcludedZone(el) {
    for (const sel of EXCLUDED_ZONES) {
      const zone = el.closest(sel);
      if (zone) {
        if (zone.querySelector("div.full-input-box")) return false;
        return true;
      }
    }
    return false;
}
```

This makes the exclusion contextual: workbench parts that host the chat input are allowed, others remain excluded.

### Subagent Tool-Call Button Structure

Subagent approval cards use `<div>` elements instead of `<button>`:

```
div.composer-tool-call-block-wrapper
  └── div.task-tool-call-header
        └── div.view-allow-btn-container-v1
              └── div.view-allow-btn-container-inner
                    ├── div (text: "View") ← cursor: pointer, no role="button"
                    └── div (text: "Allow") ← cursor: pointer, no role="button"
```

The selector `.view-allow-btn-container-inner > div` was added to `BUTTON_SELECTORS` to discover these non-standard buttons. "Allow" matches `APPROVAL_PATTERNS`, "View" matches `COMPANION_PATTERNS`, giving eligibility reason `"companion"`.

### Keyboard Hint Concatenation

Cursor renders "Skip" and "Esc" in adjacent `<span>` elements. `textContent` concatenates them as "SkipEsc" without whitespace. The `stripKeyboardHints` function handles both forms:

```javascript
stripped = stripped.replace(/(.{2,}?)\s*(?:esc|escape)$/i, "$1").trim();
```

### Discovery Path: Ancestor Walk from InputBox

The sibling scan in `findApprovalButtons` walks up the input box's ancestor chain (4 levels) and scans siblings at each level, because `div.conversations` is a cousin of `div.full-input-box`, not a sibling.

### Composer Surface Detection: Walk from Known-Shallow Element

`_isComposerSurface()` walks UP from `div.full-input-box` (known-shallow, ~4 levels to composer root) and checks `node.contains(el)`. This is more robust than walking up from the deeply-nested target element (which can be 25+ levels deep).

