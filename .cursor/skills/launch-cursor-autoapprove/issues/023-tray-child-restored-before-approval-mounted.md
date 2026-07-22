---
id: 023
title: Tray child was restored before its approval mounted
status: resolved
severity: critical
root_cause: The tray cycle scanned a selected child editor after a fixed 150 ms delay, then immediately restored the parent; a long child transcript could mount its pending approval later than that window.
lesson_extracted: true
---

## Symptoms

- The parent showed `1 subagent running` but no approval card.
- Manually selecting the tray child exposed a real pending shell `Run` approval.
- Runtime history recorded repeated `tray_visit` events for the exact child but
  zero `tray_approval_attempted` events.
- Each affected visit finished in roughly 230–310 ms, including the old fixed
  150 ms settle delay.

## Direct evidence

The installed injector successfully selected
`Implement matching metadata corrections` by exact tab identity and restored
the parent. The child editor contained a conversation but the approval control
was not eligible during the one immediate scan. Selecting the same child
manually and leaving it mounted exposed the pending approval shown in the user
screenshot.

## Resolution

- Replace the fixed settle delay with a bounded candidate-mount wait.
- Observe the exact selected child group for transcript mutations while polling
  only that group for tray-scoped eligible approvals.
- Require at least one second, finish after 250 ms of DOM quiet, and cap the wait at
  1.5 seconds.
- Abort if the selected child tab changes.
- Emit `tray_no_candidate` with the wait reason, duration, and approval-control
  count so a successful visit is no longer mistaken for successful scanning.

## Lesson

Mounting a child editor and mounting the end of its virtualized transcript are
separate asynchronous steps. Navigation recovery must wait for candidate
materialization, not merely for the editor tab and conversation container.
