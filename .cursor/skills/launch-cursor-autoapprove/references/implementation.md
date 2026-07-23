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

1. **Surface Observer**: A `MutationObserver` detects DOM changes after a 300ms
   debounce. A configurable fallback poll (`setInterval`, 0.5 seconds by default)
   catches anything the observer misses.
2. **Policy Engine**: Separates candidate discovery (finding buttons) from
   click decisions (eligibility guards, fingerprint cooldown).
3. **Event Sink**: All decisions (click, blocked, unknown) are queued in
   `state.eventQueue`. The launcher drains this queue via CDP and persists
   events to `history.jsonl` and per-prompt artifact files under
   `~/.cursor/launch-autoapprove/prompt-artifacts/`.
4. **Subagent Recovery**: The default-on bounded cycle has two paths. It
   rematerializes registered `task-subagent` rows by exact
   workspace/target/composer/tool identity. It also visits exact entries under
   the `N subagents running` composer tray, expanding a collapsed exact header
   when its child rows are unmounted. It mounts each read-only child agent
   editor, scans that selected editor, restores the parent between visits, and
   restores the prior tray expansion/tabs/focus state.
   Tray visits run before row confirmation with separate six- and ten-second
   budgets, so either nested path can make progress. `cycle --off` disables
   both nested paths plus pinned-agent recovery below.
5. **Pinned Agent Recovery**: Active pinned top-level Agent Window rows are
   visited sequentially because Cursor mounts only the selected conversation.
   Automatic navigation runs only while the window is unfocused. Explicit
   `cycle --once` visits up to two uniquely titled pinned rows, including
   completed rows, per round-robin pass. Both modes restore the original agent, editor
   selections, transcript scroll, and focus.

Prompt fingerprinting (sorted button labels within the prompt root) prevents
the same unresolved prompt from being clicked repeatedly every poll cycle.
Fingerprints have an 8-second cooldown.

A feature-flagged state probe (`state.enableStateProbe`) can check for
internal Cursor approval indicators before DOM scanning. This is off by
default and intended for future hardening as internal APIs stabilize.

## CLI Surface (`launcher.py`)

| Command | Flags | Behavior |
|---|---|---|
| `launch` | `--workspace`/`-w`, positional `PATH\|ALIAS`, `--interval SECONDS` | Start dedicated Cursor for a local workspace or registered alias, inject script, and turn the gate plus nested/pinned-agent cycling ON. SSH folder URI aliases dispatch through the SSH launch flow. The fallback scan defaults to 0.5 seconds. |
| `launch-ssh` | positional `HOST`, optional absolute `PATH`, `--no-preflight`, `--interval SECONDS` | Start dedicated Cursor connected to an SSH remote host via `--folder-uri`, inject script, and turn the gate plus nested/pinned-agent cycling ON. Path-specific launches preflight the remote directory with `ssh <host> test -d <path>` before profile/session creation. |
| `on` | `-w PATH\|SLUG`, `--interval SECONDS` (both optional) | Turn gate ON; optionally update and persist the running session's fallback scan interval; reload script if hash drift is detected. |
| `off` | `-w PATH\|SLUG` (optional) | Turn gate OFF; keep dedicated window open. |
| `cycle` | exactly one of `--on`, `--off`, `--once`; optional `-w PATH\|SLUG` | Opt out of default-on nested and pinned-agent recovery, re-enable it, or run one explicit bounded cycle. |
| `subagents` | `-w PATH\|SLUG`, `--json` (both optional) | Show the sanitized renderer registry and persisted row/status hints. |
| `status` | `-w PATH\|SLUG` (optional) | Print session details. Shows all sessions if `-w` omitted; ambiguous slugs use the picker. |
| `stop` | `-w PATH\|SLUG` (optional), `--all` | Turn gate OFF, terminate dedicated process, and remove session entry when shutdown succeeds. `--all` must not be combined with `-w` or a positional workspace. |
| `alias` | `set <name> <path>`, `remove <name>`, `list` | Manage workspace aliases stored in `config.json`. See [Workspace Aliases](#workspace-aliases-configjson) below. |
| `history` | `-w SLUG`, `-n LIMIT`, `--json`, `--commands` | Show persisted event log (session/gate/click events). `--commands` reads the dedicated command ledger with readable multiline output. |
| `screenshot` | `-w PATH\|SLUG`, `-o FILE` | Capture PNG screenshot of the dedicated window via CDP. |
| `diagnose` | `-w PATH\|SLUG` | Self-debug: screenshot + DOM snapshot + synthetic probe + summary. |
| `share-safe` | `--on`, `--off`, `-w PATH\|SLUG` | Toggle a discreet window title for screen sharing, or set it explicitly with `--on` / `--off`. |
| `help` | optional `COMMAND` topic | Print usage examples, command help, and deeper-doc paths. |

Behavior notes:

- Multiple workspaces can run simultaneously, each with its own PID, CDP port,
  and profile directory.
- Poll intervals are per-session, accept values from 0.25 through 60 seconds,
  default to 0.5 seconds, and can be changed while the gate is already ON.
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
| `~/.cursor/launch-autoapprove/commands.jsonl` | Dedicated command-approval ledger (rotates at 10 MB) |
| `~/.cursor/launch-autoapprove/subagents.json` | Atomic, sanitized per-session registry snapshots; no prompt or command bodies |
| `~/.cursor/launch-autoapprove/dedicated-profile-<slug>/` | Per-workspace Cursor profile |
| `~/.cursor/skills/global-launch-cursor-autoapprove/` | Global slash-command docs |

`state.json` structure:

```json
{
  "sessions": {
    "<workspace-path-or-ssh-uri>": {
      "pid": 12345,
      "cdp_port": 9222,
      "workspace": "<workspace-path-or-ssh-uri>",
      "slug": "<directory-name-or-ssh-slug>",
      "launched_at": "<UTC ISO timestamp>",
      "cdp_target_id": "<CDP page target ID>",
      "poll_interval_seconds": 0.5,
      "kind": "ssh",
      "ssh_host": "<ssh-config-host>",
      "remote_path": "/path/on/remote"
    }
  }
}
```

For local workspace sessions, `kind`, `ssh_host`, and `remote_path` are absent.
For SSH sessions, the key is a `vscode-remote://ssh-remote+<host>/<path>` URI.

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
- `subagent_discovered`, `subagent_status` — task registry transitions
- `cycle_started`, `row_materialized`, `cycle_miss`, `cycle_finished` — bounded
  recovery evidence
- `approval_attempted`, `approval_confirmed`, `approval_unconfirmed` — separate
  dispatch from proven resolution
- `safety_trip` — the injector turned itself off after scan/heap limits

The `click`, `blocked_candidate`, and `unknown_prompt` events include a
`fingerprint` field (sorted button labels within the prompt root), a `prompt`
subtree capture, the eligibility `reason`, and a `command` object when terminal
command text was extractable from the prompt surface.

Per-prompt artifact files are also written to
`~/.cursor/launch-autoapprove/prompt-artifacts/` for blocked and unknown events.

View with `caa history [-w SLUG] [-n LIMIT] [--json]`.

### Command Ledger (`commands.jsonl`)

`~/.cursor/launch-autoapprove/commands.jsonl` is a dedicated append-only NDJSON
log of approved terminal commands. It rotates at 10 MB (separate from the
general event history). Each line contains:

- `ts` — UTC ISO timestamp
- `workspace`, `slug` — session context
- `pattern_id`, `reason` — which approval pattern matched and why it was eligible
- `command` — the full command text with original newlines preserved
- `lineCount` — number of lines in the command
- `preview` — first line of the command, capped at 120 chars
- `source` — where the text was extracted from (`code_block` or `prompt_text`)

View with `caa history --commands [-w SLUG] [-n LIMIT] [--json]`.

**Privacy note**: approved commands may contain secrets, tokens, or sensitive
paths. The command ledger is a diagnostic record stored locally under
`~/.cursor/launch-autoapprove/`. Do not share ledger contents without
sanitizing first.

Legacy single-session format (flat `{pid, cdp_port, workspace}`) is auto-migrated
on first read. The legacy `dedicated-profile/` directory is renamed to
`dedicated-profile-<slug>/` during migration.

### Automatic Session Garbage Collection

Every call to `_load_state()` prunes invalid sessions. A session is removed
when ANY of these conditions is true:

- **PID dead** — the Cursor process exited (a dead PID cannot be revived).
- **Workspace path missing** (local sessions only) — the directory in the
  session key no longer exists on disk. This catches ghost sessions from bad
  launch paths. If the Cursor process is still alive, it is terminated first
  since a window on a non-existent path is always broken.

SSH sessions skip the workspace-path-exists check since the path is remote.
They are only pruned when their PID is dead.

### Workspace Resolution

`caa launch <arg>` resolves the workspace argument in this order:

1. If `<arg>` is omitted, use the current working directory.
2. If `<arg>` is a `vscode-remote://ssh-remote+...` folder URI, use the SSH
   launch flow.
3. Expand `~` and resolve to an absolute path. If the result is an existing
   directory, use it.
4. Treat `<arg>` as an alias name — look it up in `config.json`. Alias targets
   may be local directories or `vscode-remote://ssh-remote+...` folder URIs.
5. If no match is found, error out with a list of known aliases.

This prevents ghost sessions from bare-name arguments (e.g.
`caa launch example-lib` from the home directory resolving to the
non-existent `~/example-lib`).

### Workspace Aliases (`config.json`)

`~/.cursor/launch-autoapprove/config.json` stores user-defined workspace
aliases:

```json
{
  "aliases": {
    "example-lib": "/Users/you/code/example-lib",
    "demo-repo": "/Users/you/code/demo-repo",
    "devbox-demo": "vscode-remote://ssh-remote+devbox/home/you/code/demo"
  }
}
```

Aliases are populated two ways:

- **Automatic**: Every successful `caa launch <path>` auto-registers the
  directory basename as an alias (e.g. launching `/Users/you/code/example-lib`
  registers `example-lib`). It does not overwrite if the name already points
  to a different path.
- **Explicit**: `caa alias set <name> <path-or-ssh-uri>` registers a custom
  name. Local paths must exist; SSH folder URIs are accepted as-is. The name
  must not collide with an existing alias for a different target.

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
   - `--classic` (after verifying Cursor CLI help still advertises it)
   - `--new-window`
   - `<workspace>` (local launch) or `--folder-uri <vscode-remote URI>` (SSH launch)
9. Wait for a new Cursor main PID that includes the expected launch args.
10. Save session to `state.json` under the workspace path (local) or folder URI (SSH) key.
11. Probe CDP targets and require the mode-specific
    `workbench.desktop.main.css/js` bundle. `workbench.glass.main.css/js` is
    Agents mode; generic editor/panel/status/navigation parts are diagnostics,
    not mode proof. A non-IDE target is never injected; a new mismatched process
    is closed and its session removed.
12. Inject `devtools_auto_accept.js` via CDP `Runtime.evaluate`.
13. Call `startAccept(<interval-ms>)`, which starts the gate and the default-on
    bounded scheduler for registered nested-subagent rows, running children,
    and active pinned agents, then sync title to `autoapprove ✅ <repo>`.

If `open -na` path detection fails, the launcher falls back to direct executable
launch and repeats PID detection.

For `caa launch-ssh <host> <remote-path>`, absolute path validation happens
first. If `<remote-path>` is not `/`, the launcher also runs a bounded
`ssh <host> test -d <remote-path>` preflight before creating the profile,
session, or alias. `--no-preflight` skips this check and lets Cursor Remote SSH
handle the connection.

For `caa launch <alias>` where the alias target is an SSH folder URI, the
launcher parses the URI into `<host>` and `<remote-path>` and reuses the same
SSH launch flow, including the bounded remote directory preflight.

## CDP Target Selection and Stable Binding

At launch time, `_cdp_select_workbench_target()` requires exactly one verified
full IDE page target from `/json` and stores its `id` in `state.json` as
`cdp_target_id`. All subsequent commands (`on`, `off`, `status`, `stop`) pass
this ID to `_cdp_evaluate()`, which looks up the specific target by ID rather
than iterating through all pages.

The launcher requests `--classic --new-window` with a path or folder URI and
never passes standalone `--chat` or `--glass`. Because Cursor 3.12.30 labels
`--classic` dev-only, `_cursor_classic_mode_support()` checks CLI help before
every new local or SSH launch and fails closed if the flag disappears.
URL/title matching and generic workbench parts are insufficient because both
product modes use the renderer. `_cdp_target_surface()` requires a loaded
`workbench.desktop.main.css/js` and rejects `workbench.glass.main.css/js` before
initial injection, rebind, `on`, or cycling. Status prints
`Mode: IDE (verified)`; a non-IDE bound target produces a warning and is not
enabled.

If the bound target ID is not found in the current `/json` listing, the
command normally fails closed. `on`, `off`, `cycle`, and `subagents` may rebind
after a renderer reload only when the same CDP port exposes exactly one
workbench target; ambiguous target sets still fail closed. If `target_id` is
`None` (backward compatibility or fresh launch before the target is pinned),
the legacy workbench-first heuristic is used.

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

- `MutationObserver` on `document.body` filters ordinary streamed text and
  reacts immediately only to task-row or approval-control changes. Approval
  scans use a 300ms debounce plus a 500ms minimum scan gap.
- Fallback poll interval: `500ms` by default (`state.interval`), configurable
  per session from 250–60000ms
- Calling `startAccept(<milliseconds>)` while already running replaces the
  existing fallback timer immediately instead of returning early
- Title sync interval: `3000ms` (`state.titleTimer`)
- Tracks click history in memory (`state.clicks`, max 100 entries)
- Event queue (`state.eventQueue`, max 200 entries) for launcher to drain
- Fingerprint cooldown map (`state.fingerprintCooldowns`, 8s per fingerprint)
- Per-task registry (`state.subagents`) mirrored to namespaced `localStorage`
- Nested-subagent recovery starts with `state.cycleEnabled: true`; `cycle --off`
  disables it explicitly and `cycle --on` re-enables it
- Running-subagent tray visits are round-robin bounded to eight entries, exact
  collapsed headers receive an 800 ms materialization bound, tray navigation
  is capped at six seconds, and registered-row recovery receives a separate
  10-second budget
- Pinned-agent visits have a separate 3.5-second budget and are round-robin
  bounded to two active, unselected rows per automatic cycle, so top-level
  navigation cannot consume the nested recovery budget; focused windows never
  receive automatic top-level navigation
- Tray approvals use exact selected-tab resource identity, confirmation, and a
  two-attempt limit; aggregate visits/attempts/confirmations appear in status
- Real user interactions increment a monotonic generation and retain the latest
  terminal/editor target for focus-safe restoration
- Cached private virtualizer snapshot (5-second TTL; one forced refresh per
  cycle instead of toggling the debug API per mutation)
- Safety telemetry for scan duration, JavaScript heap, and circuit-breaker state

### Registered Subagent Click Ownership

The ordinary mounted-composer scanner and registered-row recovery are redundant
paths. A visible `Allow` in the parent transcript remains eligible for the
ordinary fast path even when cycling is enabled, with one direct attempt per
task-scoped prompt fingerprint. Registered-row recovery leases ownership only
after it has materialized the exact row and selected one exact candidate; the
lease is released in `finally`.

Both paths use `_promptFingerprint()` for the same task-scoped eight-second
cooldown. A click by either path therefore suppresses an immediate duplicate
from the other while still allowing the other mechanism to recover a prompt
that remains unresolved after cooldown. A direct-attempt map prevents the
confirmation-blind scanner from bypassing exhausted cycle retries indefinitely.
Tray and pinned navigation keep
exclusive ownership from mount through verified restoration because ordinary
body-level portal controls cannot be safely attributed during navigation.

`acceptDebugSnapshot()` includes `cycleOwned` and excludes only candidates with
an active registered-task lease or navigation owner from its `eligible` list.

Live Cursor 3.12.30 validation launched a harness subagent that ran one harmless
Python command. The mounted parent `Allow | Stop` card was clicked by the direct
scanner (`reason: companion`) and completed without individual-child
navigation.

### Running-Subagent Tray Fallback

The ordinary direct path now inspects every mounted input-backed composer, not
only the first `div.full-input-box`. Some child agent editors are read-only,
however, and contain `div.conversations` with no input. The tray fallback
handles those surfaces:

1. Match an exact visible header such as `1 subagent running` independently of
   whether its child rows are mounted.
2. Read the chevron expansion state. If collapsed, activate only that exact
   header and wait up to 800 ms for the advertised rows; partial mounts fail
   the pass and repeated misses use capped exponential backoff before
   exhausting after five failures for the same parent/count identity.
   Ambiguous headers or unknown expansion state fail closed.
3. Collect only uniquely titled, clickable
   `.composer-toolbar-background-job-item-clickable` descendants of that
   header's section, up to eight per round-robin pass. Preliminary discovery
   does not advance the cursor; each pass advances only by rows actually
   processed before its deadline.
4. Save selected tabs, focused element, the existing scroll context, the
   parent tab resource identity, and the tray's original expansion state.
5. Re-resolve one unique child title immediately before each visit because a
   previous selection remounts and collapses the parent tray.
6. Select one tray row and require exactly one selected agent tab whose title
   matches the row and whose group contains `div.conversations`.
7. Use the tab's agent resource UUID as approval identity.
8. Wait for the selected child's transcript tail to materialize: observe only
   that editor group, poll for an eligible candidate for at least one second, finish
   after 250 ms of DOM quiet, and stop after 1.5 seconds or if tab identity
   changes.
9. Scan only that editor group. The editor workbench exclusion is relaxed only
   in this exact scope; exact labels, dismissal/companion evidence, unrelated
   modal blocking, and hit coverage remain required.
10. Confirm the raw control is absent across the final consecutive checks and
   allow at most two attempts for the same resource/prompt fingerprint.
   Disabled, hidden, covered, or temporarily context-less controls remain
   present and therefore do not produce false confirmations. Connected nodes
   are checked for their current label/prompt identity so a node reused for a
   completed state does not remain falsely pending.
11. Restore the original parent tab before resolving the next child. Cursor's
   tab widget requires
   `mousedown`/`mouseup` before `click`; plain `HTMLElement.click()` did not
   restore selection in live testing.
12. Restore the tray's original collapsed/expanded state unless newer user
    interaction took ownership, then settle focus through the shared focus
    owner described below.

Tray materialization emits `tray_expand`, `tray_expand_miss`, and
`tray_restore`. Attempts emit `tray_visit`, `tray_visit_miss`,
`tray_approval_attempted`, `tray_approval_confirmed`, and
`tray_approval_unconfirmed`. A visit that mounts the child but finds no eligible
candidate emits `tray_no_candidate` with its bounded wait reason, duration, and
raw approval-control count. The normal mounted-composer scanner remains active
as the fast path. Navigation acquires editor-group ownership before dispatching
the row/tab click and retains it until selected sidebar/resource and tab state
are observed restored. Acquiring only after mount or releasing when the attempt
promise returns would let mutation-driven direct scanning race the mount or
retry an unconfirmed control during restoration. Because portaled modals can
live under `document.body` without an editor-group ancestor, all ordinary
scanner candidates are withheld while navigation ownership is active; an
unattributable portal fails closed instead of racing the scoped path.

### Pinned Top-Level Agent Cycling

Cursor 3.12.17 exposes pinned conversations as `.agent-sidebar-cell` rows
inside the exact `Pinned` `.agent-sidebar-section`, but mounts only one
`div.conversations` and one composer. The injector therefore uses bounded
navigation rather than pretending inactive chats are simultaneously clickable:

1. Discover exact `.agent-sidebar-cell-text` titles under the `Pinned` section.
2. Reject normalized titles duplicated inside the exact `Pinned` section.
   Cursor 3.12.30 legitimately projects one pinned conversation again in its
   date-based history section, so cross-section duplicates are not ambiguous.
3. For automatic cycles, keep only unselected rows with Cursor's
   `.spinning-loader` active marker and require `document.hasFocus() === false`;
   recheck focus before selection and while waiting for the mounted candidate.
4. Save the selected sidebar row, selected editor tabs, transcript scroll, and
   focus context.
5. Select each row with the same mouse event sequence used for editor tabs.
   Re-resolve its section-unique title, exact Pinned-section membership,
   active state, and row node immediately before every click; never reuse a
   later entry captured before an earlier conversation switch.
6. Require one selected agent tab with an exact matching title and one mounted
   conversations surface; wait up to 1.5 seconds for the editor and another
   bounded interval for a candidate at the transcript tail.
7. Scope approval discovery to that exact editor group, require the exact
   pinned row to remain selected, confirm raw-control disappearance, and cap
   retries at two.
8. Re-resolve the original title inside its captured sidebar section, require
   its selected-tab resource to match the captured resource, then restore
   transcript scroll, editor tabs, and focus before nested recovery continues.
9. If a real user interaction or window-focus transition occurs during an
   automatic visit, abort the entire cycle. A newer user sidebar/tab/scroll
   selection is preserved and all remaining pinned, tray, and virtual-row
   navigation is skipped; restoration runs only while the selection remains
   automation-owned.

`cycle --once` deliberately includes completed pinned rows so a two-row
navigation/restoration test does not require two live approvals. Automatic
cycles do not visit completed rows and do not switch top-level agents while the
window is focused. Events use `pinned_visit`, `pinned_no_candidate`,
`pinned_approval_attempted`, `pinned_approval_confirmed`,
`pinned_approval_unconfirmed`, and `pinned_restore`.

Live validation on Cursor 3.12.17 with injector `538f6927c92e` visited two
pinned rows, clicked and confirmed one scoped synthetic `View` + `Allow`
approval in the completed history conversation, and restored the exact
original sidebar row and selected agent tab. An automatic-mode probe with
`document.hasFocus() === false` and a temporary active marker visited only the
unselected row once and restored the original; after the marker was removed,
later automatic passes reported zero pinned visits. Follow-up race probes
confirmed that a temporarily disabled/hidden control was clicked once but not
confirmed or retried, and that a newer simulated user selection was preserved
with `abortedReason: new_user_interaction`.

### Focus-Safe Recovery

Automatic row/tray recovery pauses while the focused Cursor window has
`textarea.xterm-helper-textarea` or another non-composer editable surface
focused. This focus guard is independent of the two-second recent-interaction
timeout, so pausing while typing does not allow navigation to resume underneath
an idle terminal.

The interaction generation and an unfocused-to-focused transition are also
checked during pinned mounts, tray mounts, virtual-row materialization,
confirmation waits, and restoration. A takeover aborts the whole cycle rather
than only the current path. Tab restoration is asynchronous and ownership is
released only after the captured selections are observed selected again.
Virtual-row materialization records its actual programmatic scroll delta; if a
takeover occurs while mounting or confirming, that delta is subtracted from the
current position so automation is rolled back without discarding relative user
scroll movement.

Every real pointer, keyboard, or wheel interaction increments
`state.interactionGeneration`. Cycle contexts save that generation and their
starting focus. Native `scroll` events are excluded because Cursor auto-follow
can emit trusted scrolls without user input. Scroll and tab restoration never
call `focus()` directly.
After restoration, one focus owner chooses:

- the starting target if no newer user interaction occurred
- the latest terminal/editor target if the user changed focus during the cycle
- no target if the newer interaction was not an editable focus choice

The chosen target is restored immediately and after 300 ms. The delayed pass
re-resolves the latest interaction before acting, which corrects Cursor's
asynchronous post-approval focus without overwriting a newer user choice.
The direct mounted-prompt scanner captures the same focus context around its
click and uses this owner as well. `focus_restored` is emitted only when the
delayed pass actually corrects focus.

### Renderer Safety Circuit

The injector fails closed when its own renderer work becomes pathological:

- delete-file fallback scans mounted virtual rows plus at most 100 deduplicated
  `.composer-tool-former-message` roots, never `document.body`
- pinned visits stop after 3.5 seconds; tray navigation receives six seconds,
  then registered-row recovery receives a separate 10-second budget and visits
  at most 20 tasks
- an unconfirmed subagent click is retried once, then remains `failed` while
  the same approval card is visible; mutation discovery cannot reactivate it,
  and normal status derivation resumes after the approval clears so changed
  row state can be observed
- three consecutive approval scans above 250ms turn the gate OFF
- JavaScript heap above 768 MiB turns the gate OFF when Chromium exposes
  `performance.memory`
- `status` reports last/max scan duration, heap, and any safety trip

Cursor can still consume substantial memory while rendering a large transcript
with no injector loaded. The circuit limits injector contribution; it cannot
prevent a product-level workbench crash.

### Half-Second Concurrent Stress Evidence

On Cursor 3.12.17, four concurrent subagents each requested permission and then
slept for 60 seconds while the parent emitted enough output to move their task
rows offscreen. The live event ledger recorded four distinct `Allow|Stop`
approvals, including two consecutive clicks 0.5 seconds apart. All four tasks
later transitioned to `completed` after offscreen row revisits.

A simultaneous 90-second snapshot run recorded 43 samples and two additional
parent-command clicks. After 339 scans, the maximum scan duration was 48.4ms,
JavaScript heap was 247.7 MiB, and the safety circuit did not trip. This
validates the faster fallback cadence for the tested transcript, but the
250ms/768 MiB fail-safe bounds remain necessary for larger product workloads.

The first real-prompt replay after this stress run exposed a delete-file
regression from the earlier row-only fallback scope (11/12 fixtures passed).
Adding the capped exact former-message surface restored the preserved editor
card without restoring broad scanning; the rerun passed 12/12.

### Candidate Discovery

Approval candidates are collected in this order:

1. Siblings above every mounted `div.full-input-box` (chat-adjacent scan,
   depth <= 5 per composer)
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
    `approve terminal command`, `always allow`, `allow`, `allow scripts`
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
- `mountedComposerCount` and `mountedConversationCount` for detecting whether
  multiple agent chats exist in the current renderer DOM

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

Each scan selects the first prioritized candidate whose fingerprint is not
cooling down, and clicks at most one candidate. A cooling higher-priority
prompt is skipped so a distinct eligible prompt can be clicked on the next
0.5-second fallback scan (or an observer-triggered scan).

### Click Deduplication (Fingerprint Cooldown)

Each prompt's fingerprint is computed from the sorted normalized labels of
all buttons within the prompt root. After a click, the fingerprint enters an
8-second cooldown. During cooldown, the same prompt cannot be clicked again.
This per-prompt cooldown prevents an unresolved prompt from being clicked on
every scan without throttling other distinct eligible prompts.

### Command Text Extraction

When an approval button is about to be clicked, the injector attempts to
extract the associated terminal command text from the prompt surface:

1. Walk up from the button to the nearest prompt root or a parent containing
   `<pre>`/`<code>` elements.
2. If a code block is found, capture its `innerText` (preserves newlines).
3. Otherwise, capture the root's `innerText` with button labels filtered out.
4. The result is capped at 5000 characters.

The extracted `command` object (`text`, `lineCount`, `preview`, `source`) is
attached to click, blocked, and unknown events. A short `commandPreview` and
`commandLines` are also stored in the in-memory click history for `status`
display.

### Event Queue and Launcher Drain

All click, blocked, and unknown events are pushed to `state.eventQueue`.
The launcher drains this queue via CDP `Runtime.evaluate` during `status`,
`on`, and periodic checks. Drained events are persisted to `history.jsonl`
and (for blocked/unknown) to per-prompt artifact files. Click events with
command text are also written to the dedicated `commands.jsonl` ledger.

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
- verified product mode (`IDE (verified)` or a non-IDE warning)
- gate ON/OFF
- click count
- injector hash (with drift warning if mismatched)
- current window title
- fallback poll interval
- recent click entries (last 3 printed)
- last approved command preview (first line + line count) when available
- click attempts versus confirmed cycle approvals
- registered parent prompts that have consumed their one direct-scanner attempt
- cycle toggle/activity, task counts, and last-cycle outcome
- running-subagent tray advertised/mounted/collapsed counts plus visits,
  attempts, confirmations, and failed retry states
- pinned-agent total/active/ambiguous count, visits, attempts, confirmations,
  failures, last restoration result, and any cycle-abort reason
- active focus kind, any focus reason pausing automatic cycles, and the last
  focus-settle outcome
- last/max scan duration, JavaScript heap, and safety-trip reason
- WARNING if multiple workbench targets exist on the port
- WARNING if the bound target is missing

Use this output as primary evidence during manual validation.

`caa history` provides a durable event log complementing the in-memory
status — even after sessions are stopped or the process crashes.
`caa history --commands` reads the dedicated command ledger and renders
approved commands with preserved multiline formatting.

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
   membership, command text candidates from active dialogs, and the current
   injector `acceptStatus()`
3. **Synthetic probe** — injects a View+Allow dialog, waits about 4 seconds,
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
- **Background visibility matters more than OS focus**: On Cursor 3.12.17, a
  non-focused dedicated window reported `document.visibilityState ===
  "visible"` and continued clicking real `Run` prompts. Parallel visible
  dedicated windows can work. Minimized/hidden renderers may still be
  throttled and require separate validation.
- **Inactive top-level sidebar agents are not mounted chat surfaces**: Direct
  inspection on Cursor 3.12.17 found one `div.full-input-box` and one
  `div.conversations` before and after selecting a pinned row. Selection
  replaces the mounted chat instead of revealing hidden chats. Pinned-agent
  support is therefore sequential, automatic only for active background rows,
  and title-identity dependent. Duplicate titles inside `Pinned` fail closed;
  the same conversation projected once in Pinned and once in history is
  accepted and confirmed through selected-tab resource identity. This remains
  distinct from the `N subagents running` tray, which indexes nested children.

## Related Docs

- [Manual testing guide](manual-testing.md)
- [Subagent approval cycling design](subagent-approval-cycling.md)
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

