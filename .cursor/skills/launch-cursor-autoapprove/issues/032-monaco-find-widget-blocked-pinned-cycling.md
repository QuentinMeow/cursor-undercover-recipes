---
id: 032
title: Monaco Find widget permanently blocked pinned-agent cycling
status: resolved
severity: critical
root_cause: The recovery modal guard treated every visible role=dialog element as blocking, including Monaco's persistent non-modal editor Find widget.
lesson_extracted: true
---

## Symptoms

- Two pinned Agent Window conversations were active.
- The selected conversation and its nested subagents continued receiving direct
  approvals, but another pinned conversation remained at `Waiting approval`.
- The title remained in the recovery-blocked state instead of resuming
  cross-agent cycling.

## Direct evidence

Live status on the affected dedicated renderer reported:

- gate and cycle ON
- `Pinned: 2/2 active`
- zero pinned visits and zero pinned approval attempts
- banner blocked by `unrelated_modal`

A CDP DOM capture found exactly one visible prompt-root selector match:

```text
text: No results
role: dialog
class: editor-widget find-widget visible no-results
ancestor: .monaco-editor .overlayWidgets
aria-modal: absent
```

This was Monaco's editor Find widget, not a modal permission prompt. Because it
can remain mounted indefinitely, `_hasUnrelatedVisibleModal()` blocked every
automatic recovery cycle indefinitely while the direct scanner kept working.

## Resolution

- Classify a non-modal `.find-widget[role="dialog"]` inside `.monaco-editor`
  separately from blocking modal roots.
- Keep `aria-modal="true"`, alert dialogs, and other visible prompt roots
  blocking by default.
- Report blocking and ignored non-modal dialog-root counts in status.
- Rename the operational banner to describe scope: 🔵 `focused` for direct
  mounted-conversation scanning, 🟢 `multi-window` when an unfocused IDE may
  navigate pinned conversations, and 🔴 `off` for a disabled gate.

## Verification

- Source tests cover the narrow Monaco classification, status telemetry, and
  focused/multi-window banner contract.
- Live status after injector refresh reported `0 blocking, 1 ignored non-modal`
  while the persistent Find widget remained visible.
- The same automatic cycle then advanced from zero to two pinned visits,
  attempted the waiting conversation's real `Run` approval, confirmed it, and
  restored the original agent selection.

## Lesson

ARIA roles describe accessibility structure, not always interaction modality.
Safety guards must distinguish known embedded widgets from actual blocking
modals, and cross-agent recovery needs visit counters so direct-scanner success
cannot mask a broken navigation path.
