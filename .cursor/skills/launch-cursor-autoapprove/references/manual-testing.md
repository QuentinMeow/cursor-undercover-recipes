# Manual Testing Guide

## Goal

This guide is for users who want to verify that the dedicated auto-approve
window is actually clicking real Cursor approval prompts.

## Before You Start

1. Install the latest skill:

```bash
bash "$(git rev-parse --show-toplevel)/.cursor/skills/launch-cursor-autoapprove/scripts/install.sh" --target global --force
```

These repo-local install commands assume you are running from this repo
checkout, since they use `git rev-parse --show-toplevel` to locate the repo
root.

2. Define the installed launcher path:

```bash
LAUNCHER="$HOME/.cursor/launch-autoapprove/launcher.py"
```

3. Launch the dedicated window:

```bash
/usr/bin/python3 "$LAUNCHER" launch "$PWD"
```

4. Confirm the gate is on:

```bash
/usr/bin/python3 "$LAUNCHER" status
```

You should see:

- `Mode: IDE (verified)` — stop if status instead reports an Agents/incomplete
  surface
- `Gate: ON`
- `Cycle: ON`
- `Poll: 0.5s fallback interval` (unless you selected another interval)
- an `Injector:` hash
- a window title like `autoapprove ✅ <repo>`

5. Smoke-test the command help:

```bash
/usr/bin/python3 "$LAUNCHER" help
/usr/bin/python3 "$LAUNCHER" help off
```

Expected result:

- `help` shows example commands plus deeper doc paths
- `help off` shows the `off` usage plus examples

## Important Testing Note

Not every agent command will produce a visible approval prompt.

Some commands are silently auto-approved by Cursor's own allowlist, so command
completion alone does **not** prove the DOM injector clicked anything. Use
`/usr/bin/python3 "$LAUNCHER" status` before and after a prompt-producing action
to confirm the click count changed.

Also validate the opposite: non-prompt UI actions must **not** increase click
count (false-positive regression coverage).

If the chat shows `Waiting for Approval...` and click count stays unchanged, the
prompt text may not match the current injector patterns yet. Run `status` and
inspect `Recent:` plus the live prompt label (for example, `Approve` / `Allow`
/ `Run`) before concluding gate state is wrong.

Real shell-command cards can also append shortcut text to the button label,
for example `Skip Esc` next to `Run ↩`. Those suffixes should still normalize
to `skip` and `run`.

## Test 0: False-Positive Regression (Explorer / Editor)

With gate ON and no approval prompt visible:

1. Rename a file in explorer to include words like `allow`, `run`, `apply`.
2. Type similar words in an editor file.
3. Run `status` before and after.

Expected result:

- `Clicks:` should not increase
- `Recent:` should not get new entries from these actions

This test protects against issue 002 regressions.

## Test 1: Direct Compound Shell Command

Ask the agent to run a compound command such as:

```text
Run:
echo "step1" && echo "step2" && pwd && echo "__aa_direct_done__"
```

Expected result:

- the command completes
- `status` may show an extra `Run` click

## Test 1b: Shell Card With Plain-Text Shortcut Suffix

Some Cursor command approval cards render the dismiss action as `Skip Esc`
instead of plain `Skip`.

1. Trigger a shell command approval card in chat while gate is ON.
2. Confirm the card shows `Skip Esc` plus `Run ↩` (or another approval label
   with a keyboard hint).
3. Capture `status` before and after:

```bash
/usr/bin/python3 "$LAUNCHER" status
```

Expected result:

- the prompt is auto-clicked without manual interaction
- `Clicks:` increases
- `Recent:` includes a `run` entry

## Test 2: File Create + Delete

Ask the agent to run:

```text
Run:
TMPFILE="__aa_test_tmpfile.txt" &&
echo "auto-approve test" > "$TMPFILE" &&
cat "$TMPFILE" &&
rm -f "$TMPFILE" &&
! test -e "$TMPFILE" &&
echo "__aa_file_done__"
```

Expected result:

- the file is created and removed
- if Cursor shows a prompt, the click count increases

## Test 3: Prompt More Likely To Show UI

Subagent launches and permission-elevated commands are more likely to surface
real `Allow` buttons than ordinary in-workspace shell commands.

Ask the agent to launch a shell subagent or to run a command that needs
elevated permissions, for example:

```text
Launch a shell subagent that runs:
echo "step1" && python3 -c "print('subagent-ok')" && echo "__aa_subagent_done__"
```

Or:

```text
Run a command with elevated permissions that reads /etc/hosts and prints the
line count.
```

Expected result:

- the task completes without a manual click
- `status` shows new `Allow` or `Run` entries under `Recent`

## Test 3b: Approve-Labeled Prompt Coverage

Some Cursor surfaces use `Approve` wording instead of `Allow` / `Run`.

1. Trigger a command in chat that produces an `Approve ...` UI prompt.
2. Capture `status` before and after:

```bash
/usr/bin/python3 "$LAUNCHER" status
```

Expected result:

- `Clicks:` increases after the prompt appears
- `Recent:` includes an `approval` entry such as `approve`,
  `approve_request`, or `approve_terminal_command`

## Test 3c: Single-Action Approve Modal

Some permission prompts render as a single-action modal (approve button only,
no nearby dismissal control).

1. Trigger a command in chat that produces a single-action
   `Approve terminal command` style prompt.
2. Capture `status` before and after:

```bash
/usr/bin/python3 "$LAUNCHER" status
```

Expected result:

- prompt is auto-clicked without manual interaction
- `Clicks:` increases
- `Recent:` includes `approve_terminal_command` (or another `approve*` ID)

## Test 4: Interactive Session Picker

Launch a second workspace so two sessions are active, then verify ambiguous
commands open the picker instead of failing immediately:

1. Pick a second existing workspace, then run:

```bash
SECOND_WORKSPACE="$(git rev-parse --show-toplevel)/.cursor/skills/launch-cursor-autoapprove/references"
/usr/bin/python3 "$LAUNCHER" launch "$SECOND_WORKSPACE"
```

2. Confirm both sessions are visible:

```bash
/usr/bin/python3 "$LAUNCHER" status
```

3. Run each of these from an interactive terminal and use arrow keys plus Enter
   to choose a session:

```bash
/usr/bin/python3 "$LAUNCHER" off
/usr/bin/python3 "$LAUNCHER" on
/usr/bin/python3 "$LAUNCHER" stop
```

4. Re-launch a stopped session if needed, then try cancelling the picker with
   `q` or `Esc`.

5. Verify the non-interactive fallback does not hang:

```bash
printf '' | /usr/bin/python3 "$LAUNCHER" off
```

Expected result:

- the picker appears for ambiguous `on` / `off` / `stop`
- arrow keys move the selection and Enter runs the chosen action
- `q` or `Esc` cancels without changing session state
- bare `status` still shows all sessions
- if you intentionally create duplicate slugs, `status -w <slug>` also uses the
  picker
- with multiple running sessions, the piped `off` command exits quickly with a
  session list and guidance to use `-w` or an interactive terminal
- with exactly one running session, the piped `off` command succeeds without a
  picker

## Test 5: Multi-Window Target Binding

Verify that opening an extra window inside a dedicated process does not
corrupt CDP targeting.

1. Launch a dedicated session:

```bash
/usr/bin/python3 "$LAUNCHER" launch "$PWD"
```

2. Inside the dedicated Cursor process, manually open a second workspace
   (File → Open Folder) to create a second workbench page.

3. Run status:

```bash
/usr/bin/python3 "$LAUNCHER" status
```

Expected result:

- `Target:` shows the pinned target ID
- `Targets:` shows 2 (or more) page targets
- A WARNING about multiple workbench targets appears
- Gate ON/OFF reflects the originally launched session, not the extra window

4. Toggle the gate:

```bash
/usr/bin/python3 "$LAUNCHER" off
/usr/bin/python3 "$LAUNCHER" on
```

Expected result:

- Only the originally launched window changes title (not the manually opened one)

## Test 6: History Log

1. After running a few on/off/launch/stop operations:

```bash
/usr/bin/python3 "$LAUNCHER" history
```

Expected result:

- Shows timestamped entries for session launches, gate toggles
- Click entries now include a command preview when command text was extracted
- `-w <slug>` filters to a specific workspace
- `--json` outputs NDJSON for machine consumption

## Test 6b: Command History

1. After approving at least one terminal command (e.g. a shell command card):

```bash
/usr/bin/python3 "$LAUNCHER" history --commands
```

Expected result:

- Shows only approved commands with readable multiline formatting
- Each entry shows timestamp, slug, pattern ID, and the full command with `$` prefix
- Multiline commands display each line on its own row
- `--json` outputs NDJSON entries from `commands.jsonl`
- `status` also shows a `LastCmd:` line with the first-line preview

## Best Evidence

Run `/usr/bin/python3 "$LAUNCHER" status` after each burst and compare:

- `Clicks:` should increase
- `Recent:` should include entries such as `allow`, `run`, `run_this_time`,
  `connection_resume` depending on what prompt appeared

Example evidence:

```text
Clicks:    11
Recent:    [{"kind":"approval","id":"allow","text":"Allow"},{"kind":"approval","id":"run_this_time","text":"Run this time only (⌃⏎)"}]
```

## Refresh Test

If you changed the injector and reinstalled the skill while the dedicated window
was already running, verify refresh behavior:

```bash
/usr/bin/python3 "$LAUNCHER" on
/usr/bin/python3 "$LAUNCHER" status
```

Expected result:

- `on` succeeds
- `status` still reports `Gate: ON`
- the `Injector:` hash matches the newly installed script

## Configurable Poll Interval Test

The observer still handles normal DOM changes after its 300ms debounce.
`--interval` controls the fallback scan and can be changed without toggling the
gate off first.

```bash
/usr/bin/python3 "$LAUNCHER" on --interval 2
/usr/bin/python3 "$LAUNCHER" status
/usr/bin/python3 "$LAUNCHER" on --interval 0.5
/usr/bin/python3 "$LAUNCHER" status
```

Expected result:

- the first status shows `Poll: 2s fallback interval`
- the second status restores the default: `Poll: 0.5s fallback interval`
- both status checks show `Gate: ON`
- an invalid value such as `--interval 0` is rejected before contacting Cursor

## Pinned Agent Window Cycling

Pin at least two top-level conversations. One may be a completed history item;
explicit cycling intentionally includes completed pinned rows:

```bash
/usr/bin/python3 "$LAUNCHER" cycle --once
/usr/bin/python3 "$LAUNCHER" status
/usr/bin/python3 "$LAUNCHER" history -n 30 --json
```

Expected result:

- the current renderer still contains one `div.full-input-box` and one
  `div.conversations`; support is sequential, not truly simultaneous
- `cycle --once` reports two pinned visits when two section-unique rows are
  pinned; larger sets rotate through bounded two-row passes
- `pinned_visit` and `pinned_no_candidate` or
  `pinned_approval_confirmed` events identify each bounded visit
- the exact originally selected `.agent-sidebar-cell[data-selected="true"]`,
  selected agent tab, transcript scroll, and focus are restored
- `status` reports `Pinned: <active>/<total> active` plus ambiguous-title and
  cumulative visit/attempt/confirmation/failure totals
- a pinned conversation may also appear with the same title in `Today` or
  another history section without becoming ambiguous
- duplicate normalized titles inside `Pinned` still fail closed instead of
  selecting by position

For automatic behavior, start work in two pinned agents and move the dedicated
window to the background without minimizing it. Only unselected rows with
Cursor's active spinner should be visited. Refocus the Agent Window and confirm
automatic top-level navigation stops and no nested navigation follows that
aborted pass; direct selected-chat scanning continues. During another automatic
pass, manually select a different agent. The cycle must preserve that newer
selection and report `PinnedLast: preserved_new_user_selection`.

For confirmation safety, inject a scoped synthetic approval whose click handler
temporarily disables or hides the same control and then restores it. The attempt
must remain unconfirmed; loss of click eligibility alone is not approval
completion. In a second probe, keep the node connected but change its label from
`Allow` to a non-approval completed state; that attempt should confirm once.

Repeat the takeover test during tray or virtual-row recovery by selecting
another editor tab while a child is mounting. The whole cycle must abort,
preserve the newer tab/scroll state, skip later paths, and release navigation
ownership only after any automation-owned restoration is observed complete.

## Non-Focused Dedicated Window Test

With two dedicated sessions visible, leave one window non-focused while its
selected agent produces a real approval prompt. Compare `status` click counts
and inspect `document.visibilityState` / `document.hasFocus()` over CDP.

Validated on Cursor 3.12.17:

- the non-focused session reported `visibilityState: visible` and
  `hasFocus: false`
- its injector clicked the real `Run` prompt

This supports parallel selected chats in separate visible dedicated windows.
It does not prove reliability after a window is minimized or becomes hidden,
and it does not expose inactive sidebar chats that Cursor has not mounted.

## Optional: Panel/Alternate Surface Prompt Coverage

If your workflow surfaces prompts outside the main chat area (for example panel
or alternate composer surfaces), verify one such prompt while gate is ON.

Expected result:

- prompt is handled automatically, OR
- if not handled, document the exact surface and DOM context as a known
  limitation for selector tuning.

## Test 7: Companion Pattern (View+Allow)

Tool-call approval prompts pair `Allow` with `View` (not a dismiss action).
The companion guard should recognize `View` as evidence of a real approval surface.

1. Ask the agent to run a command that produces an `Allow` + `View` prompt
   (typically a shell command or file operation).
2. Capture `status` before and after:

```bash
/usr/bin/python3 "$LAUNCHER" status
```

Expected result:

- prompt is auto-clicked without manual interaction
- `Clicks:` increases
- `Recent:` includes an entry with `"reason": "companion"`
- for a mounted parent task row, the visible parent `Allow` is eligible through
  the ordinary direct scanner even while cycling is ON, with one direct attempt
  per task-scoped fingerprint
- if the parent card is unmounted or unresolved, registered-row or individual
  child navigation can still approve it; shared task fingerprints prevent the
  two paths from clicking concurrently

## Test 8: Self-Debug (diagnose command)

Run the built-in diagnostic to verify the injector can click synthetic probes:

```bash
/usr/bin/python3 "$LAUNCHER" diagnose
```

Expected result:

- `[1/4] Screenshot:` shows a saved PNG path
- `[2/4] DOM snapshot:` shows visible button count
- `[3/4] Probe result: PASS` with clicks > 0
- `[4/4] Artifacts saved to:` shows a directory with screenshot.png,
  dom-snapshot.json, and probe-result.json

## Test 9: Automated Harness (Short + Real Snapshot)

Prefer real snapshot mode (no synthetic prompt injection). Use the CDP port
shown by `/usr/bin/python3 "$LAUNCHER" status` for the target session:

```bash
CDP_PORT="<port-from-status>"
/usr/bin/python3 "$(git rev-parse --show-toplevel)/.cursor/skills/launch-cursor-autoapprove/scripts/stress_test.py" \
  --mode snapshot --duration 60 --interval 2.5 --port "$CDP_PORT"
```

Expected result:

- Saves artifacts under `logs/<run-id>-harness-snapshot/`
- Includes:
  - `snapshot-summary.json`
  - `snapshots/*.json` (live `acceptDebugSnapshot()` payloads)
  - `screenshots/*.png` (real UI frames)

If you want a fast synthetic smoke suite (combined, meaningful cases only):

```bash
/usr/bin/python3 "$(git rev-parse --show-toplevel)/.cursor/skills/launch-cursor-autoapprove/scripts/stress_test.py" \
  --mode synthetic --suite meaningful --port "$CDP_PORT"
```

Optional deep synthetic matrix:

```bash
/usr/bin/python3 "$(git rev-parse --show-toplevel)/.cursor/skills/launch-cursor-autoapprove/scripts/stress_test.py" \
  --mode synthetic --suite full --port "$CDP_PORT"
```

## Test 10: Real-Prompt Replay

Replay sanitized real-prompt fixtures (the end-to-end regression gate):

```bash
/usr/bin/python3 "$(git rev-parse --show-toplevel)/.cursor/skills/launch-cursor-autoapprove/scripts/stress_test.py" \
  --mode replay --port "$CDP_PORT"
```

Expected result:

- All fixtures pass (correct click behavior + single-click dedupe)
- `Results: <n>/<n> passed, 0 failed`
- Artifacts under `logs/<run-id>-harness-replay/`
- Per-case JSON with before/after debug snapshots and screenshots

To add new fixtures from a missed prompt, sanitize the captured prompt subtree
and save as `tests/fixtures/real-prompts/<descriptive-name>.json`.

## Test 11: Event Drain Verification

After running any approval-producing action:

```bash
/usr/bin/python3 "$LAUNCHER" status
```

Expected result:

- `Drained:` line shows click events persisted to history
- `history.jsonl` contains `click` records with `fingerprint`, `prompt`, and `command` fields
- `commands.jsonl` contains entries for clicks that had extractable command text
- `LastCmd:` line shows first-line preview of the most recently approved command
- If a prompt was missed: `UNKNOWN:` line shows the unmatched prompt text
- Artifact files in `~/.cursor/launch-autoapprove/prompt-artifacts/` for any
  blocked or unknown events

## Test 12: SSH Remote Launch

Verify the dedicated window can connect to an SSH remote host.

**Prerequisite**: An SSH host configured in `~/.ssh/config` (e.g. `my-devbox`).

1. Launch to the SSH host:

```bash
/usr/bin/python3 "$LAUNCHER" launch-ssh my-devbox
```

2. Confirm the gate is on:

```bash
/usr/bin/python3 "$LAUNCHER" status
```

Expected result:

- `Session:` shows the SSH host name as the slug
- `SSH Host:` shows `my-devbox`
- `Workspace:` shows the `vscode-remote://ssh-remote+my-devbox/` URI
- `Gate: ON`, `Cycle: ON`, and an `Injector:` hash

3. Toggle the gate:

```bash
/usr/bin/python3 "$LAUNCHER" off -w my-devbox
/usr/bin/python3 "$LAUNCHER" on -w my-devbox
```

Expected result:

- `-w` resolves the SSH session by slug
- gate toggles correctly

4. Launch with a specific remote path:

```bash
/usr/bin/python3 "$LAUNCHER" launch-ssh my-devbox /home/user/code/project
```

Expected result:

- slug includes the path tail (e.g. `my-devbox-project`)
- `Remote:` shows `/home/user/code/project`

5. Verify a bad path fails before launch:

```bash
/usr/bin/python3 "$LAUNCHER" launch-ssh my-devbox /definitely/not/a/real/path
```

Expected result:

- command exits non-zero with an SSH preflight error
- no Cursor window, session, profile, or alias is created for the bad path
- `--no-preflight` is available for environments where Cursor Remote SSH should
  handle the connection check itself

6. Stop the SSH session:

```bash
/usr/bin/python3 "$LAUNCHER" stop -w my-devbox
```

Expected result:

- session is removed cleanly

## Test 13: Virtualized Subagent Approval Cycling

1. Confirm a new launch started both the gate and cycle scheduler:

```bash
/usr/bin/python3 "$LAUNCHER" status
```

Expected result: `Gate: ON` and `Cycle: ON`. `cycle --on` is only needed to
re-enable cycling after an explicit `cycle --off`.

2. Start at least two subagents while the parent continues producing enough
   output to unmount their original task rows.
   For a sustained concurrency check, start four read-only subagents that each
   run `/bin/sleep 60` before printing a unique completion marker. Keep the
   parent producing useful inspection/test output during that minute.
3. Inspect the registry and run one explicit recovery pass:

```bash
/usr/bin/python3 "$LAUNCHER" subagents
/usr/bin/python3 "$LAUNCHER" cycle --once
/usr/bin/python3 "$LAUNCHER" status
```

4. Collapse the exact `N subagents running` tray so its child rows disappear.
   Run `status` and verify it reports the advertised count, zero mounted rows,
   and one collapsed header. Leave the tray collapsed for the next step.
5. Trigger a real approval in a child listed under `N subagents running`.
   Before the cycle, note the selected editor tab. After one automatic or
   explicit pass, inspect status/history:

```bash
/usr/bin/python3 "$LAUNCHER" status
/usr/bin/python3 "$LAUNCHER" history -n 30 --json
```

6. While recovery work remains, focus the integrated terminal and type. Pause
   for more than two seconds, then run `status` from another shell/window if
   possible. Also try moving into the terminal immediately after a cycle starts.

Expected focus result:

- terminal input remains focused
- `Focus: terminal (cycle paused: terminal_focused)` appears while the
  dedicated window and terminal are focused
- moving focus away allows automatic cycling to resume
- if the user changes focus during a cycle, `FocusLast` targets the newer
  terminal/editor choice instead of the stale cycle-start element

7. Verify the explicit opt-out and re-enable controls:

```bash
/usr/bin/python3 "$LAUNCHER" cycle --off
/usr/bin/python3 "$LAUNCHER" status
/usr/bin/python3 "$LAUNCHER" cycle --on
```

Expected result:

- a new session reports `Cycle: ON`; `cycle --off` reports `Cycle: OFF`, and
  `cycle --on` restores it
- a collapsed tray records `tray_expand`, mounts its exact advertised rows,
  visits the blocked child, and restores the tray's prior expansion state
- multiple children are re-resolved after each parent-editor restoration;
  later visits do not fail because a previously captured row disconnected
- a long selected child remains mounted for up to five seconds while its exact
  virtualized transcript container is repeatedly anchored to the growing tail;
  `tray_no_candidate` reports conversation, tail-container, tail-distance, and
  pulse telemetry when no button appears
- an empty child is deferred for 15–60 seconds and a two-attempt exhausted
  prompt is deferred for one to 15 minutes; deferred children are not remounted
  every two to five seconds and do not count as fresh cycle failures
- every task has a distinct task/row identity even when labels are identical
- registered parent-row recovery targets only records whose parent composer
  matches the currently mounted virtualizer; retained records from other
  parents do not emit `composer_identity_changed` every two seconds
- unmounted registered rows are revisited without permanently expanding the list
- `approval_attempted` is followed by `approval_confirmed` only after the card
  resolves
- tray recovery records `tray_visit`, then
  `tray_approval_attempted`/`tray_approval_confirmed` for a real child approval
- the tray line reports eligible rows plus visit/attempt/confirmation totals
- the tray line distinguishes advertised children, raw mounted children,
  eligible rows, collapsed/total exact headers, and unknown expansion states
- the pinned line reports active/total rows plus visit/attempt/confirmation
  totals
- the editor tab selected before tray recovery is selected again afterward;
  the child tab may remain open
- the original scroll position and focus are restored
- unsent composer text or an unrelated modal blocks the cycle
- `off` halts normal scans and cycling
- with the 0.5-second fallback, distinct mounted eligible prompts can be
  approved on consecutive scans even if the first clicked prompt remains
  mounted; the same unresolved fingerprint is not clicked again for eight
  seconds

## Test 14: Renderer Safety and Reload Rebinding

1. While a long transcript streams, watch `status`.
2. Confirm scan duration remains bounded and the JavaScript heap is shown.
3. Reopen/reload the dedicated renderer, then run:

```bash
/usr/bin/python3 "$LAUNCHER" on
```

Expected result:

- ordinary scans remain well below the 250ms circuit threshold
- three consecutive slow scans or heap above 4 GiB turns the gate OFF and
  records a `safety_trip`
- if exactly one replacement workbench target exists, `on` reports the old and
  new target IDs and reinjects successfully
- multiple possible workbench targets still fail closed

## Cleanup

Pause auto-clicking when you are done:

```bash
/usr/bin/python3 "$LAUNCHER" off
```

Or close the dedicated window completely:

```bash
/usr/bin/python3 "$LAUNCHER" stop
```

---

## CDP Diagnostic Harness

When the injector silently fails (zero clicks, no blocked/unknown events), deploy a live CDP polling diagnostic to capture the injector's perspective during real prompts.

### Quick-Start Diagnostic Script

Save the following as `/tmp/cdp_fix_diagnostic.py` and run with
`python3 /tmp/cdp_fix_diagnostic.py`:

```python
# Key technique: connect via raw WebSocket to the session CDP port from status,
# evaluate acceptDebugSnapshot() + custom DOM queries every 300ms,
# and capture per-button details during live prompts.
```

### What To Capture

For each button found during a prompt:

| Field | Why |
|-------|-----|
| `text` / `normalized` | Verify label normalization (SkipEsc vs Skip) |
| `zone` / `zoneHasInput` | Check excluded zone and chat surface escape hatch |
| `composerContains` / `composerDepth` | Verify `_isComposerSurface` walks far enough |
| `ancestry` (8 levels) | Identify which workbench part hosts the button |
| `tag` / `role` / `cursor` | Detect non-standard button elements (div with cursor:pointer) |

### Diagnostic Lessons

1. **Walk from the known-shallow element (inputBox), not the deeply-nested button**. Walking up from the button requires a depth limit that will eventually be too short.
2. **Check if the excluded zone hosts a chat surface** via `zone.querySelector("div.full-input-box")`. Don't blanket-exclude workbench parts.
3. **Capture the full element tag and cursor style**, not just button/role. Cursor may render actionable controls as `<div>` or `<span>` with `cursor: pointer`.
4. **Synthetic probes do NOT validate real behavior**. They inject `role="dialog"` elements that bypass excluded zone and sibling scan issues.

## Cursor Version Tracking

The injector's DOM selectors are coupled to specific Cursor versions. Always record the version when validating.

### Known Working Versions

| Cursor Version | Chrome Version | Injector Hash | Shell Run | Subagent Allow | Pinned Agent Cycle | Date Validated |
|---------------|----------------|---------------|-----------|----------------|--------------------|----------------|
| 3.0.8 | Chrome/142.0.7444.265 | 7e641c1041dd | OK | OK | Not tested | 2026-04-03 |
| 3.12.17 | Chrome/144.0.7559.236 | 460391c03c13 | OK (real Run) | OK (4 concurrent real Allow prompts; 60s tasks) | Not tested | 2026-07-21 |
| 3.12.17 | Chrome/144.0.7559.236 | 538f6927c92e | OK (real Run) | Not rerun | OK (2 rows; confirm, transient-control, user-selection, and restoration probes) | 2026-07-22 |
| 3.12.17 | Chrome/144.0.7559.236 | 8643e4bfc524 | OK (real Run) | OK (collapsed tray auto-expanded; two real Run prompts confirmed; parent identity/restoration confirmed) | Not rerun | 2026-07-22 |
| 3.12.30 | Chrome/144.0.7559.236 | 8b314b2e3196 | OK (real pinned and tray Run confirmations) | OK (real mounted parent Allow clicked directly with `reason: companion`) | OK (2 active rows despite history duplicate; visits, real confirmation, and restoration) | 2026-07-23 |

### Version Upgrade Checklist

When upgrading Cursor:

1. **Before upgrading**: Record current version and injector hash
2. **After upgrading**: Confirm `cursor --help` still advertises `--classic`
   (it is dev-only), then run `caa status`; require `Mode: IDE (verified)` and
   an injector hash before testing prompts
3. **Test shell commands**: Trigger a non-allowlisted command, verify auto-click
4. **Test subagent approval**: Launch a subagent with shell commands, verify View+Allow click
5. **Test pinned cycling**: Pin two agents, run `cycle --once`, and verify the
   original row/tab plus pinned confirmation telemetry
6. **If broken**: Run the CDP diagnostic harness to capture what changed
7. **Record results**: Update the version table above

### Key DOM Elements To Verify After Upgrade

- `div.full-input-box` — anchor for composer surface detection
- `div.conversations` — container for chat messages and prompts
- `workbench.desktop.main.css/js` — primary IDE-mode proof; reject
  `workbench.glass.main.css/js`
- `div.view-allow-btn-container-v1` — subagent tool-call button container
- `.agent-sidebar-section`, `.agent-sidebar-cell`, and
  `.agent-sidebar-cell-text` — pinned top-level navigation identity
- `workbench.parts.auxiliarybar` — current home of the agent chat panel
- Button rendering: `<button>` vs `<div>` with `cursor: pointer`
