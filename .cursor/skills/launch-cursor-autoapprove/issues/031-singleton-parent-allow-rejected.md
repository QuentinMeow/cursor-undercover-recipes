---
id: 031
title: Singleton parent Allow controls were rejected without Stop
status: resolved
severity: critical
root_cause: Parent-row approvals required a nearby dismissal or companion control; Cursor's newer running-subagent layout can render an exact registered task row with one visible Allow button and no Stop button.
lesson_extracted: true
---

## Symptoms

- The parent transcript visibly showed two blue `Allow` buttons.
- The gate and cycle both reported ON, but neither button was clicked.
- Registered-row recovery repeatedly reported `no_eligible_candidate`.

## Direct evidence

Live history captured both controls as:

- `pattern_id: allow`
- `surface: composer`
- visible, clickable, and outside excluded zones
- exact task-scoped fingerprints for `Credibility revision canary` and
  `Question mapping canary`
- one-button prompt captures containing only `Allow`

Both rows were registered with exact `data-find-row-key`, tool-use, composer,
and virtualizer identities and had `approval_pending` status. Policy still
returned no reason because the controls had no nearby dismissal or companion.
The existing synthetic `View | Allow` diagnostic passed, proving the gap was
specific to the singleton parent-row layout.

## Resolution

- Treat a singleton `Allow` as eligible only when it belongs to one exact
  registered subagent row.
- Require the task to have an active status and the row key to match the
  registry record exactly.
- Require one exact scroll container, viewport intersection, no unrelated
  visible modal, and an uncovered hit target.
- Preserve `dismiss` and `companion` as the preferred reasons when those
  controls exist; use `registered_task` only for the singleton fallback.
- Reuse the existing direct-attempt cap, row-cycle confirmation, task-scoped
  fingerprint, and ownership lease.

## Lesson

Companion controls are strong approval evidence, but Cursor can remove them
from a known task card. An exact registered row plus viewport and hit-testing
checks is a stronger narrow context than accepting singleton `Allow` buttons
on arbitrary composer surfaces.
