---
id: 030
title: Cross-composer registered rows were fast-retried forever
status: resolved
severity: high
root_cause: The renderer registry retains task records from multiple parent composers, but active-row selection did not scope records to the currently mounted virtualizer composer before materialization.
lesson_extracted: true
---

## Symptoms

- Live history emitted `composer_identity_changed` for every registered row.
- Each cycle counted those identity mismatches as misses.
- The miss summary selected the two-second retry delay.
- No approval could be found because none of the retained rows belonged to the
  currently mounted composer.

## Direct evidence

After loading injector `133fcc1444eb`, a live `jobs-finder-combined` session
retained four active task records across two parent composer IDs. The current
virtualizer exposed a different selected composer. Every two seconds the cycle
attempted all four records, emitted four `composer_identity_changed` misses, and
immediately scheduled another fast pass.

## Resolution

- Read the cached/just-refreshed virtualizer composer identity before choosing
  registered row records.
- Include an active record in row materialization only when its
  `parentComposerId` matches the currently mounted composer.
- Keep non-current records in the registry rather than marking them failed or
  stale; they can become eligible again if their exact parent composer is
  selected later.
- Tray and pinned navigation remain independent recovery paths for other
  mounted conversations.

## Lesson

A renderer-wide task registry is broader than a mounted virtualized transcript.
Scope expensive row materialization to the current composer before counting
misses; identity mismatch is routing information, not a transient retry.
