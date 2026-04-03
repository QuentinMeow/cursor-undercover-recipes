---
id: 006
title: Approve-labeled permission prompts were not matched by injector patterns
status: resolved
severity: medium
root_cause: The approval pattern list covered accept/allow/run variants but omitted approve-labeled variants used by some Cursor permission prompts.
resolved_at: 2026-04-03
lesson_extracted: true
---

## Symptoms

- User sees `Waiting for Approval...` in chat while gate is ON.
- `status` shows `Clicks: 0` and no new `Recent` entries.
- Prompt wording is `Approve ...` instead of `Allow`/`Run`/`Accept`.

## Root Cause

The injector uses exact normalized text matching (not substring matching) for
safety. This is correct, but the exact list did not include:

- `approve`
- `approve request`
- `approve terminal command`

Because those labels were missing, the injector correctly ignored the prompt.

## Fix

Added the three approve-labeled variants to `APPROVAL_PATTERNS` in
`scripts/devtools_auto_accept.js`, preserving exact-match semantics and the
existing dismissal-proximity guard.

## Lesson

When prompt text changes across Cursor surfaces, exact-match safety still
requires regular synonym maintenance. Missing a synonym causes false negatives;
substring matching would cause false positives. Keep exact matching, update the
list, and validate against live prompts.
