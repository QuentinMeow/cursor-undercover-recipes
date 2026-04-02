# Manual Testing Guide

## Goal

This guide is for users who want to verify that the dedicated auto-approve
window is actually clicking real Cursor approval prompts.

## Before You Start

1. Install the latest skill:

```bash
bash "$(git rev-parse --show-toplevel)/.cursor/skills/launch-cursor-autoapprove/scripts/install.sh" --target global --force
```

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

## Important Testing Note

Not every agent command will produce a visible approval prompt.

Some commands are silently auto-approved by Cursor's own allowlist, so command
completion alone does **not** prove the DOM injector clicked anything. Use
`/usr/bin/python3 "$LAUNCHER" status` before and after a prompt-producing action
to confirm the click count changed.

Also validate the opposite: non-prompt UI actions must **not** increase click
count (false-positive regression coverage).

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

## Optional Test 4: Panel/Alternate Surface Prompt Coverage

If your workflow surfaces prompts outside the main chat area (for example panel
or alternate composer surfaces), verify one such prompt while gate is ON.

Expected result:

- prompt is handled automatically, OR
- if not handled, document the exact surface and DOM context as a known
  limitation for selector tuning.

## Cleanup

Pause auto-clicking when you are done:

```bash
/usr/bin/python3 "$LAUNCHER" off
```

Or close the dedicated window completely:

```bash
/usr/bin/python3 "$LAUNCHER" stop
```
