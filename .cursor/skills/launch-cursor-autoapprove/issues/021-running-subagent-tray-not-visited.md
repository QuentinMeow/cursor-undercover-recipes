---
id: 021
title: Running-subagent tray was not used as approval recovery
status: resolved
severity: critical
root_cause: The injector only scanned mounted composer inputs and registered parent-transcript rows; a running subagent's read-only agent editor was mounted only after its composer-toolbar tray row was selected.
lesson_extracted: true
---

## Symptoms

- The parent showed an `N subagents running` tray.
- A child agent was blocked on a real shell approval.
- Parent-row recovery had already failed or no longer had a usable mounted row.
- The ordinary scanner could not reach the child because its read-only agent
  editor had no `div.full-input-box`.

## Direct evidence

Validated on Cursor 3.12.17:

- the running tray used `.composer-toolbar-background-job-item-clickable`
  entries under a header such as `1 subagent running`
- selecting `Qualify target-company boards` mounted a separate agent editor
  with one `div.conversations`, zero `div.full-input-box` elements, and a real
  `Skip | Run` shell approval
- exact selected-tab identity exposed a stable agent resource UUID
- a tray-scoped `Run` click resolved the card in 101 ms
- the event ledger recorded `tray_approval_attempted` followed by
  `tray_approval_confirmed`
- the previously selected editor tab was restored and remained stable across
  repeated automatic cycles

## Resolution

- Scan every mounted input-backed composer in the ordinary direct path.
- Add a second default-on path that recognizes the exact running-subagent tray,
  visits up to eight entries per bounded cycle, and resolves each selected
  child by exact tab title/resource identity.
- Permit approval matching inside the otherwise excluded editor area only
  within that exact selected child editor, while retaining exact labels,
  dismissal/companion guards, coverage checks, and unrelated-modal blocking.
- Confirm that the candidate disappeared, cap each tray prompt at two attempts,
  and record tray-specific attempt/confirmation events.
- Capture and restore selected editor tabs and focus. Tab restoration dispatches
  the `mousedown` sequence required by Cursor's tab widget before `click`.

## Lesson

Read-only subagent editors are valid approval surfaces even when they have no
composer input. Treat the running-subagent tray as a bounded navigation index,
then scope approval policy to the exact selected child and restore the user's
editor selection.
