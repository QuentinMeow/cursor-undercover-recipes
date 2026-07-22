---
id: 015
title: Subagent approval rows become unmounted while parent continues
status: implemented
severity: critical
root_cause: Cursor virtualizes the selected parent transcript, so running subagent rows and their approval controls can be unmounted as parent output advances.
lesson_extracted: true
---

## Symptoms

- The parent agent continues producing output while subagents run.
- Cursor auto-follows the parent output.
- Older subagent approval cards stop being discoverable by the DOM injector.
- Label-only fingerprints can also make concurrent `Allow|Stop` cards block one
  another during cooldown.
- Click history records dispatch attempts but does not prove that a card
  resolved.

## Evidence

Validated on Cursor 3.12.17:

- a 112-row conversation mounted only 10 virtualized rows
- the private virtualizer snapshot reported TanStack with six overscan rows
- a bounded scroll sweep remounted all 112 rows in about four seconds
- a temporary full-height pulse also mounted all rows, then restored the
  original virtualized state
- a managed-permissions probe did not suppress its terminal prompt in the live
  session; it ran only after the delayed DOM clicker was restored
- four concurrent real subagent tasks produced distinct `Allow|Stop` prompts;
  all four were approved and completed while parent output moved their rows
  away from the bottom viewport
- task-scoped fingerprints allowed two different prompts to be clicked 500ms
  apart without re-clicking one unresolved prompt

## Resolution

Record subagent/tool row identity while mounted, maintain a renderer-local task
registry, and revisit exact registered rows through bounded virtual-list
materialization. Clicks must be scoped to the registered row and counted only
after the card is confirmed resolved.

See
[`../references/subagent-approval-cycling.md`](../references/subagent-approval-cycling.md)
for the implemented registry, CLI, safety rules, and verification matrix.

Implemented surfaces:

- renderer-local registry mirrored to namespaced `localStorage`
- atomically persisted sanitized snapshots in `subagents.json`
- per-task fingerprints for identical `Allow|Stop` cards
- `caa cycle --on|--off|--once`
- `caa subagents [--json]`
- exact-row materialization through the private TanStack snapshot
- bounded click confirmation, one retry, scroll/focus restoration, and
  interaction guards
- terminal lifecycle detection from the row's `data-tool-status` marker
- scan-duration and JS-heap safety trips

A real completed subagent was remounted after its row had moved offscreen and
the registry transitioned from `running` to `completed`. Live approval-click
acceptance was also verified for four concurrent real `Allow|Stop` cards at the
0.5-second fallback cadence. The narrower case where a card first appears only
after its row is already unmounted remains dependent on Cursor timing and was
not deterministically reproduced.
