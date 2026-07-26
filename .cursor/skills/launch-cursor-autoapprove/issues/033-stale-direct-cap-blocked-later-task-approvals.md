---
id: 033
title: Stale direct-attempt caps blocked later approvals for the same task
status: resolved
severity: critical
root_cause: A registered task's direct-attempt cap was keyed by row identity and button labels and never cleared, even though one long-running subagent can issue several sequential approvals with that same fingerprint. Registered-row confirmation also accepted outer status advancement while the raw Allow control remained present.
lesson_extracted: true
---

## Symptoms

- Three visible `Allow | Stop` parent cards remained pending with the gate and
  cycle both ON.
- The failure was identical in focused and multi-window modes.
- Status showed prior click attempts and one confirmation, but the controls
  remained visible.

## Direct evidence

Live `acceptDebugSnapshot()` output on Cursor 3.13.10 found all three controls
as visible, clickable, uncovered composer candidates with `reason: companion`.
Every candidate had `directRetryExhausted: true` and was excluded solely by the
permanent direct-attempt map. One still-visible fingerprint also appeared in
the recent click log as a confirmed registered-row cycle.

The confirmation path treated a derived `failed` or `completed` task status as
advancement even when `_sameApprovalStillPresent()` returned true. This
produced false confirmation and retained stale retry state around the real
pending control.

## Resolution

- Clear direct-attempt records for one task only after its exact mounted row is
  observed without a visible approval. Virtualized or otherwise unmounted rows
  do not rearm the direct path.
- Clear the direct cap after confirmed raw-control disappearance so a later
  prompt from the same task can use the fast path.
- Require two consecutive checks with no matching raw approval before a
  registered-row click is confirmed.
- Remove outer task status as an independent confirmation signal.

## Lesson

A task-scoped row-and-label fingerprint deduplicates one prompt but does not
identify every approval over the task's lifetime. Rearm only from positive
evidence that the exact mounted prompt cleared, and never report success while
the raw approval control remains.
