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

- `Gate: ON`
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
- `-w <slug>` filters to a specific workspace
- `--json` outputs NDJSON for machine consumption

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

## Optional Test 5: Panel/Alternate Surface Prompt Coverage

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

Prefer real snapshot mode (no synthetic prompt injection):

```bash
/usr/bin/python3 "$(git rev-parse --show-toplevel)/.cursor/skills/launch-cursor-autoapprove/scripts/stress_test.py" \
  --mode snapshot --duration 60 --interval 2.5 --port 9222
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
  --mode synthetic --suite meaningful --port 9222
```

Optional deep synthetic matrix:

```bash
/usr/bin/python3 "$(git rev-parse --show-toplevel)/.cursor/skills/launch-cursor-autoapprove/scripts/stress_test.py" \
  --mode synthetic --suite full --port 9222
```

## Test 10: Real-Prompt Replay

Replay sanitized real-prompt fixtures (the end-to-end regression gate):

```bash
/usr/bin/python3 "$(git rev-parse --show-toplevel)/.cursor/skills/launch-cursor-autoapprove/scripts/stress_test.py" \
  --mode replay --port 9222
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
- `history.jsonl` contains `click` records with `fingerprint` and `prompt` fields
- If a prompt was missed: `UNKNOWN:` line shows the unmatched prompt text
- Artifact files in `~/.cursor/launch-autoapprove/prompt-artifacts/` for any
  blocked or unknown events

Expected result (meaningful suite):

- around a dozen high-signal cases (instead of 50)
- `Results: <n>/<n> passed, 0 failed`
- artifacts under `logs/<run-id>-harness-synthetic/`

Engineering note:

- The evidence package is the source of truth, not just terminal PASS lines.
- The harness now syncs wait time to `acceptStatus().interval` + margin, so cases
  are sampled after at least one injector poll. Forcing a shorter wait can create
  false negatives.
- The click counter is expected to increase by the number of positive cases,
  while false-positive guard cases should not contribute clicks.
- If a case fails, inspect `cases/<N>.json` first (look at `visibleButtons`,
  `candidates`, and `eligible`), then compare with the paired screenshots.

Categories tested:
- 10 dismiss+approval combinations (cancel, skip, close, etc.)
- 10 companion+approval combinations (view, stop, details, etc.)
- 6 single-action modal probes (approve* solo, approve+view, approve+cancel)
- 4 non-approve solo buttons (should NOT click)
- 10 false-positive guards (excluded zones, invisible, disabled, etc.)
- 11 edge cases (keyboard hints, plain-text `Esc` hints, case, whitespace, role=button, etc.)
- 6 real-prompt replay fixtures (dedupe-checked)

## Cleanup

Pause auto-clicking when you are done:

```bash
/usr/bin/python3 "$LAUNCHER" off
```

Or close the dedicated window completely:

```bash
/usr/bin/python3 "$LAUNCHER" stop
```
