---
id: 029
title: Selected tray child still restored before its approval tail rendered
status: resolved
severity: critical
root_cause: The earlier candidate wait accepted one mounted conversation plus one second and 250 ms of DOM quiet as readiness; a long virtualized transcript could remain stable in a partial mount while its tail and approval control were still absent.
lesson_extracted: true
---

## Symptoms

- Cycling visibly selected a running subagent and returned to the parent.
- No approval was attempted.
- Manually leaving the same child selected later exposed the pending button.
- History showed `tray_no_candidate` after approximately one second with zero
  mounted approval controls.

## Direct evidence

The live event ledger contained long runs of `tray_no_candidate` records with
`waitedMs` near 1,000–1,050 and `approvalControls: 0`. This proves the existing
issue-023 fix waited as implemented, but its readiness predicate and duration
were still insufficient: editor selection and a quiet partial virtual list did
not prove the transcript tail had materialized.

During validation, the new runtime selected `Company principles canary`,
mounted one conversation and one tail container, reached bottom distance zero
with three tail pulses, and remained there for 1,806 ms until a newer user
interaction correctly aborted the automatic visit.

## Resolution

- After exact child selection, repeatedly locate the single virtualized
  conversation scroll container and anchor it to the current bottom whenever
  its height grows or it drifts from the tail.
- Keep tray children selected for at least 2.5 seconds and up to five seconds.
- Permit an early empty result only after 500 ms of DOM quiet, one mounted
  conversation, one exact tail container, and a bottom-stable position.
- Preserve the shorter one-to-1.5-second window for pinned top-level visits.
- Add conversation-mounted, tail-container-count, tail-distance, tail-pulse,
  and next-probe telemetry to no-candidate events.
- Back off fully materialized empty children from 15 to 60 seconds so running
  children without approvals are not repeatedly remounted.
- Prompt identity changes clear empty/exhausted state and allow a fresh
  bounded attempt.

## Lesson

Virtualized transcript readiness must be established at the tail, not inferred
from tab selection or temporary DOM quiet. Empty recovery results also require
backoff; otherwise a readiness miss becomes a continuous navigation loop.
