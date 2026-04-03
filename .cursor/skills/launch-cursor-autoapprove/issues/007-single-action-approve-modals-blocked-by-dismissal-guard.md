---
id: 007
title: Single-action approve modals were blocked by dismissal guard
status: resolved
severity: high
root_cause: Approval candidates required a nearby dismissal control, but some Cursor permission prompts render as single-action modal approve buttons without a sibling dismiss button.
resolved_at: 2026-04-03
lesson_extracted: true
---

## Symptoms

- Gate remained `ON` and injector hash looked healthy.
- Prompt stayed at `Waiting for Approval...` until manual click.
- `status` click count stayed unchanged during the blocked prompt.

## Root Cause

The safety guard required `hasNearbyDismissal(...)` for approval clicks.
That works for two-button prompts (`Approve` + `Cancel`) but rejects single-action
modal prompts such as `Approve terminal command`.

## Fix

Added a narrow exception:

- allow `approve*` approval IDs when all are true:
  - element is inside modal prompt roots (`dialog`/`alertdialog`/`aria-modal`)
  - root is visible and not in excluded workbench zones
  - no explicit dismissal control is present
  - root has a very small action surface (<= 2 short visible clickable controls)

This preserves exact text matching and excluded-zone protection while unblocking
real single-action permission prompts.

## Evidence

Harness repro on bound target:

- Single-action modal (`Approve terminal command`) before fix: no click.
- Same scenario after fix: auto-click fired and `status` `Recent` recorded
  `approve_terminal_command`.

## Lesson

Dismissal proximity is a strong safety default, but modal permission prompts can
legitimately be single-action. For those, use a constrained context exception
instead of globally weakening click safety.
