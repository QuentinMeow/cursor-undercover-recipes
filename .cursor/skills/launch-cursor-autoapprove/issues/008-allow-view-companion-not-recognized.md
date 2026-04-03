---
id: 008
title: Allow+View tool-call prompts blocked by eligibility guard
status: resolved
severity: high
root_cause: The eligibility filter required a nearby dismissal control, but tool-call approval prompts pair Allow with View (a non-dismissal companion). No eligibility path covered this pattern.
resolved_at: 2026-04-03
lesson_extracted: true
---

## Symptoms

- Gate remained `ON` and injector hash looked healthy.
- Prompt stayed at `Waiting for Approval...` until manual click.
- `caa status` click count stayed unchanged during the blocked prompt.
- The prompt showed `Allow` next to `View` — neither a dismiss control nor an
  `approve*` label eligible for the modal single-action path.

## Root Cause

The eligibility filter in `checkAndClick` had three paths:

1. `btn.kind === "resume"` — only for resume links
2. `hasNearbyDismissal(btn.el)` — requires cancel/skip/close/dismiss/deny/not now
3. `isModalSingleActionApprove(btn)` — only for `approve*` IDs in dialog roots

"View" is not a dismiss action, and "allow" is not an `approve*` ID. All three
paths rejected the Allow button, so it was never clicked.

## Fix

Added a **companion pattern** concept:

- `COMPANION_PATTERNS` set: `view`, `stop`, `details`, `show details`
- `matchesCompanion(el)` with the same hygiene as `matchesDismissal` (visibility,
  clickability, excluded-zone checks)
- `hasNearbyCompanion(el)` using a shared `_hasNearbyMatch` helper
- Updated eligibility filter to include `hasNearbyCompanion(btn.el)` as a fourth path
- Added eligibility `reason` field to click telemetry for diagnostics

Also expanded `DISMISS_PATTERNS` with `reject`, `don't allow`, `decline` based
on multi-agent false-positive review.

Refactored `matchesDismissal`/`hasNearbyDismissal` to use shared helpers
(`_matchesLabelSet`, `_hasNearbyMatch`) to reduce duplication.

## Evidence

- Multi-agent review (3 independent agents) confirmed companion pattern as the
  correct abstraction over expanding dismiss patterns or relaxing modal guards
- `diagnose` command: synthetic View+Allow probe → PASS (clicks +2, reason=companion)
- 50-case stress test: 50/50 pass (20 dismiss, 10 companion, 10 modal, 10 false-positive
  guards, 10 edge cases including keyboard hints, case normalization, excluded zones)

## Lesson

Approval surfaces can have non-dismissal secondary controls (View, Stop, Details)
that indicate a real prompt just as strongly as Cancel does. Model these as
"companions" — a distinct structural signal from dismissals — rather than corrupting
the dismiss vocabulary or weakening modal constraints.
