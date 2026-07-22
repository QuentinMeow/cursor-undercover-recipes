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
- When cycling is enabled and exact registered task identity exists, the
  candidate is `cycleOwned`: the confirmation-aware cycle path is its sole click
  owner, and normal eligible, blocked, and unknown paths exclude it.
- Debug snapshots expose `cycleOwned` and omit owned candidates from `eligible`.
- When cycling is OFF or no registered identity exists, ordinary visible-card
  scanning remains available.
- Focused source-level unit coverage protects the sticky-failure and
  single-owner guards.

## Verification

The Python unit suite covers default-on cycling, sticky failed state, and normal
plus debug eligible-path ownership filters. Final global reinstall and live
verification are deferred to the post-review check.

## Lesson

A retry limit is ineffective if reconciliation can reopen terminal state or a
second confirmation-blind scanner can click the same action outside that retry
budget. Retry-governed actions need one click owner.
