---
id: 012
title: Allow scripts permission prompts were not matched by injector patterns
status: resolved
severity: high
root_cause: The exact approval pattern list included `allow` but omitted the compound `allow scripts` label used by Cursor script permission prompts.
resolved_at: 2026-04-30
lesson_extracted: true
---

## Symptoms

- A Cursor permission card showed `Skip`, `Allow scripts`, and `Accept` actions.
- The gate was ON, but the card stayed blocked until manual approval.

## Root Cause

The injector intentionally uses exact normalized text matching for safety.
`Allow scripts` normalizes to `allow scripts`, which does not equal the existing
`allow` approval pattern.

## Fix

Added `allow scripts` to `APPROVAL_PATTERNS` with a dedicated
`allow_scripts` ID. Added both synthetic and replay coverage for the reported
card shape while preserving the existing dismissal/companion/modal eligibility
guards.

## Lesson

Compound approval labels need explicit pattern entries. Do not relax exact
matching to prefixes or substrings; update the allow-list and add a fixture for
the real prompt shape.
