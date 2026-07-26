---
id: 035
title: Task Allow pills ignored bare native clicks
status: resolved
severity: critical
root_cause: Cursor 3.13.10 task-subagent Allow pills did not reliably respond to renderer-synthetic activation and at least one required trusted input. The injector counted dispatches as attempts, but the raw controls remained pending.
lesson_extracted: true
---

## Symptoms

- Reloading the injector rearmed and attempted three exact `Allow` controls.
- Click counters increased, but all three raw controls remained visible.
- Confirmation correctly stayed at zero after the raw-control fix.

## Direct evidence

Live validation first dispatched the existing bare `HTMLElement.click()` path
four times; `acceptDebugSnapshot()` still returned all three candidates.
Mouse-only synthetic sequences were inconsistent across the remaining task
pills. An exact pointer-plus-mouse activation probe (`pointerdown`, `mousedown`,
`pointerup`, `mouseup`, `click`) removed the targeted raw control within one
second, but another task still required a trusted CDP
`Input.dispatchMouseEvent` pressed/released pair. That final control disappeared
within one second after trusted dispatch.

Final hash `9bb203ec3be6` validation injected an exact registered task pill whose
click handler deliberately ignored every untrusted event. The renderer made
one bounded untrusted attempt, the worker made one trusted attempt, and the
raw Allow count reached zero with `clicked: trusted`.

## Resolution

- Use the proven pointer-plus-mouse activation sequence only for exact
  `button.task-subagent-header-pill-button--allow` controls.
- Keep native `HTMLElement.click()` as the default for all other approved
  controls.
- Keep pointer/mouse events out of the generic fallback and do not add keyboard
  events.
- After one delayed unresolved exact task-pill attempt, let a detached
  per-session helper dispatch one trusted CDP mouse click. The injector must
  authorize the exact task/fingerprint and uncovered center point; the helper
  must re-verify IDE mode and the pinned target before dispatch.

## Lesson

Minimal click simulation remains the safe default, but a product widget may
require its normal pointer and mouse activation lifecycle. Escalate only for a
narrowly identified, already-authorized control and validate success from raw
DOM disappearance rather than attempt counters. If `isTrusted` is required,
keep the CDP bridge out of generic discovery and preserve one bounded fallback
attempt per exact prompt.
