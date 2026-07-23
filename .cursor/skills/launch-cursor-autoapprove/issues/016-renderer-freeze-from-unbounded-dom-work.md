---
id: 016
title: Dedicated renderer becomes unresponsive during long streaming transcripts
status: resolved
severity: critical
root_cause: Mutation-triggered approval checks included a whole-document nested delete-prompt scan; the first cycling implementation also refreshed the private virtualizer snapshot on every task-row mutation.
lesson_extracted: true
---

## Symptoms

- macOS reports that the dedicated Cursor window is not responding.
- The workbench renderer can exceed 700 MiB RSS while rendering a large active
  transcript.
- Reopening the window creates a new CDP target, leaving the launcher pinned to
  the dead target.
- The problem is easiest to reproduce while large diffs stream and subagent rows
  update.

## Evidence

- The old fallback called `collectDeleteFileChangeMatches(document.body, ...)`.
  Nested broad selectors then rescanned overlapping composer/message/tool
  subtrees after mutations.
- A restarted renderer with no injector still used about 722 MiB RSS and 218 MiB
  JavaScript heap for the large transcript, so not all renderer memory belongs
  to the injector.
- On the optimized renderer, bounded approval scans measured about 1–3 ms during
  idle task-free checks; CDP round trips remained below 57 ms.
- During a 90-second four-subagent stress run at the 500ms fallback cadence,
  the injector completed 339 scans with a 48.4ms maximum, used 247.7 MiB of
  JavaScript heap at the final sample, and did not trip the safety circuit.
- Renderer reloads changed the page target ID while the main Cursor PID and CDP
  port remained alive.

## Resolution

- Delete-file fallback scans currently mounted virtualized rows plus at most
  100 deduplicated `.composer-tool-former-message` roots; it never rescans
  `document.body`.
- Mutation handling ignores ordinary streamed text outside subagent/approval
  controls and rate-limits observer-triggered scans.
- Virtualizer snapshots are cached for five seconds and refreshed once at cycle
  start instead of toggled per task mutation.
- Registry persistence is throttled when task identity/status has not changed.
- The faster 500ms default remains bounded to one candidate per scan and keeps
  the existing per-fingerprint cooldown, so throughput does not mean repeatedly
  clicking one unresolved prompt.
- Cycles have task-count and elapsed-time bounds.
- Three consecutive scans above 250 ms or JavaScript heap above the configured
  limit trips the gate OFF and records `safety_trip`. The original limit was
  768 MiB; issue 028 raised the current limit to 4 GiB after adding
  exhausted-child navigation backoff.
- `on`, `off`, `cycle`, and `subagents` can safely rebind after a renderer reload
  only when exactly one workbench target exists.

## Remaining Product Risk

Cursor itself can consume substantial renderer memory for a large transcript
even with no injector loaded. The safety circuit limits injector contribution;
it cannot prevent a product-level renderer crash caused by transcript rendering.
