---
id: 025
title: Pinned conversation duplicated in history blocked all pinned cycling
status: resolved
severity: critical
root_cause: Pinned identity required a title to be globally unique across the entire Agent sidebar, but Cursor 3.12.30 renders the same conversation in both Pinned and its date-based history section.
lesson_extracted: true
---

## Symptoms

- Two pinned conversations both showed Cursor's active spinner.
- Status reported `Pinned: 2/2 active, 1 ambiguous, 0 visits`.
- Automatic and explicit cycles never visited either pinned conversation.

## Direct evidence

Live CDP capture on Cursor 3.12.30 found:

- `Behavioral interview preparation` once in the exact `Pinned` section
- the same title once in `Today`
- two distinct pinned rows, both with `.spinning-loader`
- selected chat tabs with resource UUIDs for both pinned conversations

The history duplicate was expected product rendering, not two ambiguous pinned
targets. The global title count rejected one target, then original-selection
capture rejected the entire pinned pass.

After the fix and injector reload, explicit cycling visited both pinned rows in
one pass. Subsequent status reported `2/2 active, 0 ambiguous`, a real
`pinned:dismiss` Run confirmation, and
`PinnedLast: original_agent_restored`.

## Resolution

- Resolve pinned targets by exact title within the exact `Pinned` section.
- Treat a title as ambiguous only when it is duplicated inside `Pinned`.
- Capture the original row's section title and restore within that exact
  section, then retain the existing selected-tab resource check.

This preserves fail-closed behavior for real same-section duplicates while
allowing Cursor's normal Pinned-plus-history projection.

## Lesson

Navigation projections can render one conversation in multiple sections.
Scope title uniqueness to the section being navigated and use the selected
resource identity for confirmation.
