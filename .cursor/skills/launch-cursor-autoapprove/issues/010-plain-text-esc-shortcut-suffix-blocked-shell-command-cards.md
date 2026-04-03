---
id: 010
title: Plain-text Esc shortcut suffix blocked shell command approval cards
status: resolved
severity: high
root_cause: Dismissal matching handled plain labels and glyph-based shortcut hints, but not dismiss buttons rendered with a trailing plain-text Esc hint such as `Skip Esc`.
resolved_at: 2026-04-03
lesson_extracted: true
---

## Symptoms

- Real shell command approval cards stayed at `Waiting for Approval...` until a
  manual click.
- `caa status` showed the `Run ↩` action as a candidate, but click count stayed
  unchanged.
- The card rendered `Skip Esc` next to `Run ↩`.

## Root Cause

The injector uses exact normalized text matching for safety. `Run ↩` already
normalized to `run`, but `Skip Esc` normalized to `skip esc` because the
keyboard-hint stripper only handled parenthesized hints and trailing glyphs.

That broke the nearby-dismissal guard:

- `Run ↩` matched the `run` approval pattern
- `Skip Esc` failed to match the `skip` dismissal pattern
- the approval candidate stayed blocked because `hasNearbyDismissal(...)` returned false

## Fix

Added a narrow plain-text shortcut normalization step for trailing `Esc` /
`Escape` tokens in `stripKeyboardHints(...)`.

This preserves exact-match safety while making these real shell command cards
eligible again.

## Evidence

- Live synthetic repro with `Skip Esc` + `Run ↩` before fix: candidate detected,
  `reason: null`, click delta `0`
- Same repro after fix: `Run` becomes dismissal-eligible and click count increases
- Added both:
  - a synthetic harness regression case
  - a replay fixture based on the real card shape

## Lesson

Real Cursor button labels can mix semantic text with plain-text keyboard hints.
Exact matching remains the right safety model, but the normalization layer must
strip those hint suffixes consistently or the policy engine will miss otherwise
valid prompts.
