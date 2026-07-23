---
id: 019
title: Unconfirmed subagent approvals bypassed bounded retries
status: resolved
severity: critical
root_cause: Mutation discovery reactivated failed tasks, and the confirmation-blind fallback scanner remained a second click owner for registered subagent cards, so both paths could bypass the cycle scheduler's retry limit.
lesson_extracted: true
---

## Symptoms

- An approval click did not produce a confirmable card or row-state change.
- The bounded retry path marked the task `failed` with `unconfirmed_click`.
- The next mutation discovery pass immediately restored `approval_pending`, so
  automatic cycling retried the same unresolved card indefinitely.
- After failed status became sticky, the cycle scheduler stopped retrying but
  the ordinary fallback scanner still clicked the same registered `Allow` at
  each eight-second fingerprint cooldown.

## Evidence

During default-on live verification, old approval cards did not confirm and
their task records reached 61 attempts despite the intended initial attempt plus
one retry limit. A follow-up live check showed that sticky failure stopped cycle
attempts while ordinary scanner clicks continued every eight seconds.

## Resolution

- When a visible approval remains, `_deriveTaskStatus` now preserves an existing
  `failed` status instead of returning `approval_pending`.
- The task stays failed while the unresolved approval remains visible. Normal
  status derivation can resume after the approval clears so changed row state
  can be observed.
- The original resolution made the confirmation-aware cycle the sole owner for
  every registered card. Issue 026 refined this after it proved too restrictive:
  the mounted direct path now gets one attempt per task-scoped fingerprint,
  shares cooldown with row recovery, and is excluded only while an exact
  bounded lease is active. It cannot resume clicking forever after retries are
  exhausted.
- Debug snapshots expose both `cycleOwned` and `directRetryExhausted` and omit
  either state from `eligible`.
- Focused source-level unit coverage protects the sticky-failure and
  single-owner guards.

## Verification

The Python unit suite covers default-on cycling, sticky failed state, and normal
plus debug eligible-path ownership filters. Final global reinstall and live
verification are deferred to the post-review check.

## Lesson

A retry limit is ineffective if reconciliation can reopen terminal state or a
second confirmation-blind scanner can click the same action without its own
cap. Redundant paths need shared dedupe, bounded attempts, and leased ownership.
