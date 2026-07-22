# Subagent Approval Cycling Design

## Status

**Implemented for the dedicated legacy IDE renderer.**

This document describes three recovery paths: exact registered subagent rows
that Cursor virtualized out of the parent transcript, exact entries under the
`N subagents running` composer tray, and active pinned top-level conversations
in the bound Agent Window sidebar. Pinned conversations are visited
sequentially because Cursor mounts only the selected chat.

The shipped CLI is:

```text
caa cycle --on|--off|--once [-w <workspace>]
caa subagents [--json] [-w <workspace>]
```

Automatic cycling starts ON for new `caa launch` and `caa launch-ssh`
sessions. `caa cycle --off` is the explicit opt-out, and `--on` re-enables it.
Runtime snapshots are cached and every cycle is bounded by task count and
elapsed time. Scan-duration and JavaScript-heap circuit breakers turn the gate
off if renderer work becomes unsafe.

## Why This Is Needed

Cursor 3.12.17 allows the parent agent to continue producing transcript rows
while subagents run. The parent conversation uses a TanStack virtual list:

- a live 112-row conversation mounted only 10 rows
- the virtualizer reported six overscan rows
- an approval card in an unmounted row does not exist in the DOM
- selector changes and `scrollIntoView()` cannot find an unmounted card

The current injector also treats a dispatched `el.click()` as success without
confirming that the card resolved. Repeated `allow|stop` entries at the
eight-second cooldown cadence showed why attempt and confirmation must be
separate events.

### Managed-permissions probe

A temporary project `.cursor/permissions.json` allowlisted one unique harmless
compound command. The DOM clicker was paused and a delayed fail-safe was
scheduled to turn it back on. The command remained pending until the fail-safe
restored the clicker, and command history recorded a normal DOM-approved `Run`.

The test cannot distinguish team policy from session-reload behavior, but it
does establish the product requirement: this workflow cannot depend on users
being able to change effective Cursor permissions. The temporary permissions
file was removed after the test.

## Scope

### Phase 1

- dedicated legacy IDE target already pinned by the launcher
- nested subagent cards in the selected parent conversation
- record task identity while its row is mounted
- revisit registered running tasks when their rows are unmounted
- click only an eligible approval inside the exact registered row
- visit exact running-subagent tray entries when parent-row recovery is
  unavailable, then scope matching to the selected child agent editor
- visit uniquely titled active pinned top-level agents only while the window is
  unfocused, then restore the original selected agent
- verify the approval resolved
- restore the user's selected tabs, scroll position, and focus

### Deferred

- cycling unpinned history conversations
- approving hidden conversations simultaneously
- invoking private Cursor approval services or replaying internal RPC

## Design Principles

1. **Identity before labels**: `Allow` is not unique. Bind every attempt to a
   workspace, CDP target, parent conversation, tool-use ID, and transcript row.
2. **Record before unmount**: collect task identity as soon as Cursor inserts a
   subagent row.
3. **Materialize narrowly**: navigate directly to known rows instead of scanning
   the entire transcript when possible.
4. **Confirm outcomes**: a dispatched click is an attempt, not proof.
5. **Fail closed**: ambiguous identity, target drift, or selector drift disables
   cycling instead of clicking a broader surface.
6. **Restore context**: preserve the selected conversation and scroll position.
7. **Keep normal scanning**: immediate visible-prompt handling remains the fast
   path; cycling is recovery.
8. **Navigate narrowly**: tray recovery must resolve one exact row title to one
   selected agent tab/resource before relaxing the editor-zone exclusion.
9. **Background-only top-level navigation**: automatic pinned cycling must not
   change the selected conversation in a focused Agent Window.

## Identity Model

Cursor hook events may expose:

- `conversation_id`
- `generation_id`
- `session_id`
- `tool_use_id`
- `tool_name`
- `transcript_path`

The design must not require hooks because managed environments may restrict
them. Hook metadata is an optional identity enrichment source.

Mounted transcript rows expose private attributes such as:

- `data-index`
- `data-find-row-key`
- `data-find-bubble-ids`

Observed tool row keys resemble:

```text
tool-placeholder:<bubble-id>:tool:<tool-use-id>
```

The DOM injector should record the row key and bubble IDs whenever a row
contains a `task-subagent` surface. It should also keep the tool-use ID when it
can be parsed without guessing.

### Stable task key

Use a compound key:

```text
<workspace>|<cdp-target-id>|<parent-composer-id>|<tool-use-id-or-row-key>
```

Never use button labels as task identity.

## Runtime Registry

The authoritative live registry belongs in injected renderer state because the
cycling scheduler also runs in the renderer:

```javascript
state.subagents = new Map();
```

Representative serialized record:

```json
{
  "taskKey": "workspace|target|composer|tool-use-id",
  "workspace": "/path/to/workspace",
  "targetId": "CDP_TARGET_ID",
  "parentComposerId": "composer-id",
  "parentConversationId": "optional-conversation-id",
  "toolUseId": "tool-use-id",
  "rowKey": "tool-placeholder:...:tool:...",
  "bubbleIds": ["bubble-id"],
  "rowIndexHint": 42,
  "rowStartHint": 6140,
  "title": "Research API behavior",
  "status": "running",
  "firstSeenAt": "ISO-8601",
  "lastSeenAt": "ISO-8601",
  "lastProgressAt": "ISO-8601",
  "lastAttemptAt": null,
  "confirmedAt": null,
  "attempts": 0,
  "failure": null
}
```

Allowed statuses:

- `discovered`
- `running`
- `approval_pending`
- `approval_attempted`
- `approved`
- `completed`
- `failed`
- `stale`

Do not store command text, prompt bodies, credentials, or model reasoning in
this registry.

## Persistence

The injected page cannot write a normal filesystem file directly. Use two
layers:

1. Mirror the registry into profile-local `localStorage` after each state
   transition. Namespace by workspace and pinned target.
2. Expose `exportSubagentRegistry()` so `launcher.py` can persist a sanitized
   snapshot atomically to:

```text
~/.cursor/launch-autoapprove/subagents.json
```

`status`, `on`, `off`, and explicit subagent commands should drain the snapshot.
The file is for observability and recovery; the renderer map remains
authoritative while the window is alive.

On injector reload:

1. load the namespaced `localStorage` snapshot
2. discard records for another workspace or target
3. mark old `running` records as `stale`
4. reconcile records against the current composer and virtualizer rows

All filesystem writes must use a temporary file plus atomic replace.

## Discovery

### Immediate DOM path

Replace the observer's trailing-only behavior with a leading-edge pass over
`MutationRecord.addedNodes`.

For each added subtree:

1. find the nearest `.virtualized-composer-messages-row`
2. detect a `task-subagent` card
3. read row identity attributes
4. read a short task title and status only
5. create or refresh the registry record
6. scan the row immediately for approvals

Keep the debounced full scan and fallback poll as safety nets.

Observe `characterData` as well as child and attribute mutations because task
status may change through text updates.

### Virtualizer reconciliation

Cursor 3.12.17 exposes the private object:

```text
globalThis.__cursorComposerVirtualizationDebug
```

When present, a snapshot provides:

- composer ID
- row keys and indices
- row start offsets and measured sizes
- mounted and visible state
- viewport height and current scroll position
- whether the list is at the bottom

This API is private. Version-gate its shape and fail closed if required fields
are missing. Do not mutate the debug object.

Reconcile cached `rowKey` values with snapshot rows. Refresh index and start
hints without changing task identity.

### Hook enrichment

If hooks are permitted, `preToolUse`, `subagentStart`, and child tool events may
append conversation and tool-use IDs. Hook data can improve matching but must
not be required for basic cycling.

## Cycle Scheduler

Cycling is enabled by default for new launch sessions:

```text
caa cycle --off -w <workspace>
caa cycle --on -w <workspace>   # re-enable after opting out
caa cycle --once -w <workspace>
```

Only one cycle may run at a time. `caa off` must stop both normal auto-clicking
and cycling.

### Trigger policy

Run a recovery cycle when all are true:

- gate is ON
- cycling is enabled
- at least one registered task is active or one exact running-tray entry exists
- or at least one unselected pinned row has Cursor's active spinner while the
  window is unfocused
- no cycle is already active
- no approval was confirmed for that task during its cooldown

Use adaptive timing:

- immediate scan when a task is first discovered or updated
- short retry after an unconfirmed click
- slower round-robin recovery while tasks remain running

Avoid a constant full-transcript sweep.

### Running-subagent tray fallback

Some selected child agent editors contain `div.conversations` but no
`div.full-input-box`, so the input-anchored direct path cannot trust them.
Recovery matches the exact `N subagents running` header, visits at most eight
`.composer-toolbar-background-job-item-clickable` rows per round-robin pass,
and requires exactly one selected agent tab with matching title and a mounted
conversation. The tab's resource UUID becomes the target identity.

The selected editor can appear before a long virtualized transcript mounts its
tail, so recovery observes that exact group and waits one to 1.5 seconds for an
eligible candidate. Within that group, exact approval labels still require a
nearby dismissal/companion or narrow modal rule. Unrelated modals and covered
controls block the click. Each prompt gets at most two attempts and is confirmed
only when the raw control remains absent across consecutive final checks;
temporary disabled, hidden, or covered states remain unconfirmed. The cycle then restores every previously
selected editor tab and focus; Cursor's tab widget requires
`mousedown`/`mouseup` before `click` for reliable restoration.

### Pinned top-level Agent Window fallback

The bound workbench exposes pinned conversations under the exact `Pinned`
`.agent-sidebar-section`. Each `.agent-sidebar-cell` has a stable title for the
current mount, `data-selected`, and an active `.spinning-loader` marker.
Automatic cycles visit only active unselected rows while
`document.hasFocus() === false`. Normalized titles duplicated anywhere in the
currently rendered Agent sidebar are skipped because exact selected-tab
confirmation would be ambiguous.

Each visit requires one selected editor tab whose title exactly matches the
sidebar row, the exact pinned row to remain selected, and its group to contain
`div.conversations`. Candidate matching, raw-control confirmation, and the
two-attempt cap reuse the tray-scoped policy. Restoration re-resolves the
captured globally unique title and requires the selected tab's resource key to
match before restoring transcript scroll, editor selection, and focus.
Every later pinned entry is re-resolved inside the Pinned section immediately
before navigation so an earlier remount cannot leave a stale/recycled row.
Navigation ownership starts before the row click and ends only after selected
sidebar/resource and tab state are observed restored. While it is active, all
ordinary-scanner candidates are withheld because body-level portal controls
cannot be safely attributed to an editor group.
Pinned navigation has a separate 3.5-second budget with at most two visits per
round-robin pass, leaving the nested path its full 10-second budget.
`cycle --once` includes completed pinned rows so navigation/restoration can be
tested without two live prompts.

If the user focuses or interacts with the window during automatic navigation,
abort the whole cycle across pinned, tray, and virtual-row paths. Restore only
if no newer user interaction occurred; otherwise preserve the newer
sidebar/tab/scroll selection and skip all remaining recovery.
Virtual-row materialization rolls back only its recorded programmatic scroll
delta on takeover, preserving relative movement added by the user.

### User-interaction guard

Postpone automatic cycling when:

- the dedicated window is focused and the user typed, scrolled, or clicked
  within the last two seconds
- the focused window has its integrated terminal or another non-composer
  editable surface active, even if the last keystroke was more than two seconds
  ago
- the composer input contains unsent text
- a modal unrelated to the registered row is active

`cycle --once` is explicit and may bypass the recent-scroll delay, but it must
still preserve input and modal safety.

## Row Materialization Algorithm

For each active registry record:

1. Capture:
   - selected composer/conversation identity
   - scroll container
   - `scrollTop`
   - distance from bottom
   - focused element
2. Resolve the row from the current DOM by exact `rowKey`.
3. If absent, resolve its current start offset from the virtualizer snapshot.
4. Set `scrollTop` near the row start, leaving approximately 30% of the viewport
   above the row.
5. Dispatch a scroll event and wait for a bounded mount signal:
   - two animation frames, or
   - a matching added row, or
   - 200 ms timeout
6. Re-query the row by exact identity. Never retain a recycled row element
   reference across scrolling.
7. Scan only that row for approval candidates.
8. If no matching row mounts, record a miss and continue.

### Fallback sweep

If the debug snapshot is absent or stale:

1. start near the cached row index or last position
2. move by at most 45% of viewport height per step
3. scan after each mount
4. cap the sweep by elapsed time and distance
5. restore the original position

A live experiment covered all 112 rows with 48 samples in about four seconds.
This is acceptable as a bounded fallback, not as a continuous loop.

### Full-materialization pulse

Temporarily expanding the virtual viewport mounted all 112 rows in testing, but
the technique scales memory and layout work with transcript length. Keep it as
a diagnostic or final fallback with strict row-count and total-height caps.
Never leave the expanded style installed.

## Scoped Approval Policy

A cycle candidate is eligible only when:

- it is inside the exact registered row
- the row still represents the same task key
- the task is not completed, failed, or stale
- the label exactly matches an approval pattern
- the existing dismissal, companion, or modal guard passes
- the control is visible inside the actual chat scroll viewport
- no unrelated modal overlays it

For subagent launch cards, `Allow` is eligible and `Stop` is only a companion
signal. Never click `Stop`, `View`, or another task's `Allow`.

### Fingerprint

Use:

```text
<task-key>|<row-key>|<pattern-id>|<button-normalized-label>
```

This prevents identical `Allow|Stop` cards from sharing one cooldown. When one
candidate is cooling down, continue evaluating other tasks.

## Click and Confirmation

Registered subagent approvals have one click owner. While cycling is enabled,
an eligible candidate tied to an exact registry row is `cycleOwned`; the
ordinary fallback scanner excludes it from clicks and blocked/unknown telemetry.
The confirmation-aware cycle path alone may click it and consume its retry
budget. Debug snapshots expose the flag and exclude owned candidates from
`eligible`. With cycling OFF or no registered task identity, ordinary visible
card handling remains available.

1. Bring the exact button inside the scroll viewport.
2. Re-query after scrolling to avoid a recycled element.
3. Capture pre-click task status and row identity.
4. Dispatch the conservative DOM click.
5. Mark `approval_attempted`; do not increment confirmed approvals yet.
6. Verify at bounded intervals:
   - candidate disappeared, or
   - task status advanced, or
   - row content changed from waiting to running/completed
7. Mark `approved` only after confirmation.

If the first attempt is unconfirmed:

- rematerialize the same row once
- confirm identity again
- retry once
- then mark the task `failed` with `unconfirmed_click`

While that approval remains visible, mutation discovery must preserve the
`failed` status rather than returning the task to `approval_pending`. Normal
status derivation may resume after the approval clears, allowing changed row
state to be observed. Do not retry forever at the fingerprint cooldown cadence.

## Scroll Restoration

After each task or cycle:

- if the user was near the bottom, restore to the new bottom
- otherwise restore the saved `scrollTop`, adjusted for bounded list-size drift
- restore tabs and scroll without calling `focus()` from either subsystem
- settle focus through one owner using an interaction generation: keep the
  starting target only when no newer interaction exists; otherwise follow the
  latest user-selected terminal/editor target
- repeat the guarded focus settle after 300 ms so Cursor's asynchronous
  post-approval focus cannot overwrite the user
- do not focus the composer automatically

Record whether Cursor's auto-follow changed the position during the cycle.

## Event and Status Surface

Add event types:

- `subagent_discovered`
- `subagent_status`
- `cycle_started`
- `row_materialized`
- `cycle_miss`
- `approval_attempted`
- `approval_confirmed`
- `approval_unconfirmed`
- `tray_visit`, `tray_visit_miss`, `tray_no_candidate`
- `tray_approval_attempted`, `tray_approval_confirmed`,
  `tray_approval_unconfirmed`
- `pinned_visit`, `pinned_visit_miss`, `pinned_no_candidate`
- `pinned_approval_attempted`, `pinned_approval_confirmed`,
  `pinned_approval_unconfirmed`, `pinned_restore`
- `cycle_finished`

`caa status` should show:

```text
Cycle:      ON
Subagents:  3 active, 1 waiting, 7 completed
LastCycle:  2026-07-21T23:40:00Z (3 rows, 1 confirmed, 0 failed)
```

Add:

```text
caa subagents
caa subagents --json
caa cycle --once
caa cycle --off
caa cycle --on  # re-enable after opting out
```

`caa subagents` should report IDs, short titles, status, row hints, attempts,
confirmation state, and last-seen timestamps. It must not print prompt or
command contents by default.

## Code Changes

### `scripts/devtools_auto_accept.js`

- immediate mutation-record scanning
- task registry and state transitions
- localStorage mirror and export API
- virtualizer adapter with shape/version validation
- targeted row materialization
- scoped candidate matching
- per-task fingerprints
- click confirmation
- cycle scheduler and interaction guard
- cycle/subagent status fields and event records
- pinned-section discovery, exact selected-tab mounting, and original-agent
  restoration

### `scripts/launcher.py`

- persist sanitized registry snapshots
- `cycle` and `subagents` commands
- status rendering and event draining
- session cleanup for stale registry entries
- injector APIs for enabling, disabling, and running one cycle

### `scripts/stress_test.py`

- virtualized transcript fixture mode
- multiple identical subagent-card cases
- row unmount/remount assertions
- scroll restoration assertions
- attempted-versus-confirmed click assertions

## Delivery Phases

### Phase A: observability only — implemented

- record mounted task rows
- expose `caa subagents`
- log virtualizer row hints
- do not scroll or click

Exit criteria: task discovery remains accurate through unmount, remount,
completion, and injector reload.

### Phase B: explicit one-shot cycle — implemented

- implement `caa cycle --once`
- target exact registered rows
- scan without clicking by default in development diagnostics
- enable scoped click after evidence review

Exit criteria: a real unmounted waiting card is materialized, clicked once,
confirmed, and the original scroll position is restored.

### Phase C: automatic cycling — implemented

- add adaptive scheduler
- interaction guard
- bounded retry and failure states

Exit criteria: two or more concurrent subagents with identical `Allow|Stop`
labels all progress without cooldown collisions or false clicks.

### Phase D: running-subagent tray fallback — implemented

- exact running-tray discovery and round-robin bounds
- selected child tab/resource identity
- read-only child editor approval scope
- confirmation, two-attempt cap, and tab/focus restoration

Live validation on Cursor 3.12.17 mounted a child with one conversations
surface and no input, confirmed a real `Run` approval in 101 ms, and restored
the previous editor tab across repeated cycles.

### Phase E: pinned Agent Window cycling — implemented

- discover exact uniquely titled rows under the `Pinned` section
- visit active unselected rows only when the window is unfocused
- use exact selected-tab/editor identity and scoped approval policy
- restore original row, transcript scroll, editor tabs, and focus
- let explicit `cycle --once` visit one round-robin pass of up to two pinned
  rows for bounded validation

## Verification Matrix

Required live cases:

1. Two subagents start while the parent continues streaming.
2. A subagent approval row becomes unmounted before approval.
3. Two simultaneous cards have identical `Allow|Stop` labels.
4. The user is scrolled away from the bottom.
5. The user types in the composer during a scheduled cycle.
6. A row index changes after transcript compaction or insertion.
7. A subagent completes before its scheduled visit.
8. A click dispatches but the card does not resolve.
9. The private virtualizer API is absent or changes shape.
10. The pinned CDP target disappears.
11. Gate OFF prevents every cycle and click.
12. A non-subagent `Allow` elsewhere in the workbench is never clicked.
13. A running tray child has a read-only editor with no composer input.
14. Multiple tray rows are visited round-robin and the original tabs are
    restored.
15. Two pinned top-level rows are visited by an explicit cycle and the original
    selected row is restored.
16. Automatic pinned cycling skips completed rows and every focused window.

For each case save:

- before/after screenshot
- registry snapshot
- virtualizer snapshot summary
- exact targeted row identity
- attempt and confirmation events
- restored scroll/focus result

### 2026-07-21 concurrent stress result

Four concurrent real subagents produced identical `Allow|Stop` labels, slept
for 60 seconds, and all completed while the parent continued adding transcript
rows. Task-scoped fingerprints allowed all four permission cards to progress;
two different cards were clicked exactly 500ms apart at the new default
fallback cadence. Their rows were later revisited offscreen and the registry
finished at 0 active, 10 completed, and 0 failed (including prior completed
tasks retained in the same renderer registry).

This validates the Phase C identical-card exit criterion and completion after
unmount. The timing-dependent matrix case where an approval first appears only
after its row is already unmounted was not deterministically reproduced.

## Acceptance Criteria

- Every active task has a stable identity independent of button labels.
- A registered unmounted row can be revisited without a full permanent render.
- Multiple identical cards do not block one another.
- Confirmed counts represent resolved cards, not dispatched clicks.
- Scroll and focus are restored within a bounded tolerance.
- Gate OFF disables normal and cycling paths.
- Ambiguous identity or selector drift causes no click.
- No prompt or command text is persisted in the registry.
- Tray recovery is bounded, confirms disappearance, caps retries, and restores
  the selected editor tabs.
- Pinned Agent Window recovery is bounded, background-only when automatic,
  rejects duplicate titles, and restores the original selected agent.

## Known Risks

- All row attributes and the virtualizer debug object are private Cursor APIs.
- Cursor may recycle rows or change row-key grammar between releases.
- Auto-follow can race programmatic scrolling.
- A child subagent conversation ID may not be available at parent launch time.
- Managed policy may create prompts that differ from personal configurations.
- Hidden or minimized renderers may throttle timers.
- Pinned-title identity and active-spinner selectors may drift between Cursor
  versions.

Mitigate with Cursor-version recording, injector hash checks, private-API shape
validation, real-prompt fixtures, bounded retries, and fail-closed behavior.
