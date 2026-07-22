---
id: 020
title: Cooling mounted button starved later eligible candidates
status: resolved
severity: high
root_cause: The scanner selected eligible[0] before checking its fingerprint cooldown, so a cooling first button caused an early return that prevented every later mounted eligible button from being considered.
lesson_extracted: true
---

## Symptoms

- Multiple distinct eligible approval buttons were mounted at the same time.
- The first button remained in the DOM after being clicked and entered the
  intentional eight-second fingerprint cooldown.
- Although fallback scans ran every 0.5 seconds, later mounted buttons were not
  clicked on consecutive scans.

## Evidence

Observed click attempts were about eight seconds apart despite the configured
0.5-second fallback poll. `_checkAndClickImpl()` always selected `eligible[0]`,
then returned when that candidate was cooling down, so the first unresolved
prompt paced all other mounted candidates at its cooldown interval.

## Resolution

- Select the first eligible candidate whose fingerprint is not cooling down.
- Return only when every eligible candidate is cooling down.
- Preserve one click per scan and the eight-second cooldown for the same
  unresolved prompt.
- Add focused source-level coverage that requires cooldown-aware `.find(...)`
  selection and rejects the old `eligible[0]` plus early cooldown-return shape.

## Verification

The Python launcher test suite covers the scanner selection guard. After global
installation at injector hash `0474979860ef`, a live fallback-only probe kept
two distinct modal roots mounted after click. `Allow` and `Run` were each
clicked exactly once, 502 ms apart, with no unrelated clicks; the cooling first
root no longer starved the second.

## Lesson

Per-prompt cooldowns must filter candidate selection, not short-circuit the
whole scan. Global scan cadence should remain available to other distinct
eligible prompts.
