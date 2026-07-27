---
id: 036
title: Focused mode still navigated into subagent child editors
status: resolved
severity: critical
root_cause: The original automatic-cycle guard protected only pinned rows, so tray and registered-row recovery navigated away from visible questions. The first correction overgeneralized document focus into a global navigation stop and regressed focused-window subagent progress when no question existed.
lesson_extracted: true
---

## Symptoms

- The dedicated IDE title showed 🔵 `focused`.
- A parent conversation had a visible question card awaiting user input.
- Automatic recovery repeatedly selected a nested subagent child editor,
  replacing the parent view and defeating the focused-mode contract.

## Direct evidence

On Cursor 3.13.10 with injector `9bb203ec3be6`, live status for the affected
workspace reported:

```text
Banner: FOCUSED (window_focused), 1 active agents
Tray:   1 advertised, 0 mounted, 16 visits
Pinned: 1/1 active, 0 visits
```

The renderer therefore knew the window was focused while the tray path kept
navigating. Source inspection found:

- `_cycleBlockReason(false)` returned no block for a quiet focused composer or
  question card after the two-second recent-interaction guard elapsed.
- `runSubagentCycle()` removed pinned entries when focused but retained
  registered rows and tray headers/entries.
- `abortIfWindowFocused` was computed as
  `!explicit && !document.hasFocus()`, so an automatic cycle that passed through
  while already focused also disabled its in-flight focus-transition guard.

## Resolution

- Detect only Cursor's visible pending `.glass-questionnaire-tray`, requiring
  its `Next`/`Continue` and `Skip` controls.
- A focused window returns `human_question_pending` only while that tray is
  mounted. Window, terminal, or editor focus alone no longer blocks recovery
  after the short interaction guard.
- All automatic registered-row, tray-child, and pinned-agent paths use the same
  question-specific initial and in-flight guard.
- The direct scanner remains active for the currently mounted conversation.
- If a question appears after recovery selected a child or pinned agent, the
  cycle preserves that question-bearing selection instead of restoring the
  original parent.
- Explicit `cycle --once` remains available as the bounded override.

## Verification

- Injector syntax check passed.
- The 42-test launcher/injector suite passed.
- Global installation and both running-session reloads succeeded with injector
  `f7bb2e652670`; both targets remained `Mode: IDE (verified)` with the gate and
  cycle enabled.
- With focus forced true and no questionnaire, live status reported
  `MULTI-WINDOW`, `humanQuestionPending: false`, and an automatic cycle returned
  `ok: true` rather than a focus block.
- A temporary structurally accurate questionnaire probe reported
  `FOCUSED (human_question_pending)` and an automatic cycle returned
  `{"ok": false, "reason": "human_question_pending"}`.
- The same mounted questionnaire with focus false reported `MULTI-WINDOW`,
  proving the gate requires both the pending question and focused document.

## Lesson

Focus is context, not the stop condition. All automatic UI navigation must use
one shared pending-human-question gate, and a question discovered by navigation
must retain the current question-bearing selection for the user.
