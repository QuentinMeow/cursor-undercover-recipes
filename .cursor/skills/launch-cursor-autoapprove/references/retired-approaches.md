# Retired Approaches

## Summary

This skill replaced two earlier auto-approval experiments:

- `cursor-autoapprove`
- `personal-cursor-quickapprove`

Both taught useful lessons, but neither was a good long-term user-facing skill.
This document keeps the reasoning visible after the old folders are removed.

## Retired Skill 1: `cursor-autoapprove`

`cursor-autoapprove` tried to solve too many layers at once:

- a `beforeShellExecution` hook
- session management
- PID / workspace ownership
- a DOM injector
- a macOS Accessibility watcher
- validation tooling
- spillover protocols

### What Worked

- good failure analysis
- strong lessons about isolation scope
- useful validation discipline
- the eventual move toward DOM-based clicking

### Why It Was Retired

The skill became too broad and too hard to trust as the main user workflow.
Key failures and constraints:

1. The shell hook does **not** suppress Cursor's approval dialogs. It runs after
   the dialog is resolved, so it cannot be the main auto-approval mechanism.
2. Agent commands can arrive at the hook with `cwd=''`, which makes workspace
   scoping tricky and undermines any design that depends on hook-side allow
   signals.
3. The macOS Accessibility tree did not expose Cursor's approval buttons
   reliably enough to make AX clicking the primary path.
4. The skill's promise drifted toward per-pane or per-agent isolation, but the
   observable identity was really workspace + top-level PID/window.
5. The installed runtime could drift from the repo source, which made debugging
   confusing unless users reinstalled constantly.

The repo kept the most durable lessons and moved the supported workflow to a
much smaller launcher-only skill.

## Retired Skill 2: `personal-cursor-quickapprove`

`personal-cursor-quickapprove` was a temporary fallback that sent Return-style
keystrokes into a targeted Cursor process on a timer.

### Why It Was Useful Temporarily

- simple to prototype
- useful for narrowing down whether focus/shortcut behavior mattered
- independent of AX tree visibility

### Why It Was Retired

It was a workaround, not a safe productized skill:

1. It sent keystrokes at the process level, not to a specific DOM element.
2. It depended on keyboard focus being on the right dialog at the right time.
3. It could hit the wrong surface inside that process if focus moved.
4. It provided almost no positive evidence that the right thing was clicked.
5. It encouraged a "spam the shortcut and hope" model instead of a precise
   scoped click.

That made it too risky to present as a durable shared skill.

## Lessons Carried Forward Into `launch-cursor-autoapprove`

### 1. Match the automation surface to the rendering layer

Cursor renders approval controls in the Chromium DOM, so the supported skill now
operates there through CDP instead of trying to force AX or keystrokes to work.

### 2. Keep the scope narrow and observable

The supported isolation unit is:

- one dedicated Cursor process
- one dedicated profile
- one injected renderer-local script

That is something the code can actually observe and control.

### 3. Validate mechanism, not just outcome

Command completion is not enough. The supported workflow exposes click counts
and recent click logs through `caa status`.

### 4. Keep the pattern list complete

The DOM injector must explicitly match all known approval labels. Missing
`Allow` broke subagent approvals until the pattern list was corrected.

### 5. Handle installed/runtime drift explicitly

`caa on` now reloads stale in-window injector code when the installed script hash
does not match the running window's hash.

## What To Use Now

Use only:

- `launch-cursor-autoapprove`

If you need stronger confidence, keep the dedicated-window model and use the
manual validation flow from [`manual-testing.md`](manual-testing.md).

## Migration Cleanup (If You Used Retired Skills)

If you previously installed the retired `cursor-autoapprove` stack globally,
remove stale runtime artifacts so they cannot conflict with this skill:

- `~/.cursor/skills/global-cursor-autoapprove/`
- `~/.cursor/auto-approval/`
- any `beforeShellExecution` hook entries in `~/.cursor/hooks.json` that call:
  - `~/.cursor/auto-approval/cursor_auto_approval.py hook-shell`

The supported global skill name for this approach is:

- `/global-launch-cursor-autoapprove`

**Note (2026-04)**: The repo-local `.cursor/hooks.json` had a stale
`beforeShellExecution` hook calling the retired `cursor_auto_approval.py`.
This was removed as part of the observer-policy rework. The launcher now
automatically detects and warns about any remaining stale hooks at launch
and status time.
