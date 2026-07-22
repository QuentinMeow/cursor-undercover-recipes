---
id: 018
title: New launches left virtualized subagent recovery disabled
status: resolved
severity: high
root_cause: The injector started the main approval gate but initialized nested-subagent cycling to false, so registered offscreen rows were not revisited automatically.
lesson_extracted: true
---

## Symptoms

- `caa launch` and `caa launch-ssh` advertised auto-approval ON.
- Visible approval cards were handled, but virtualized nested-subagent cards
  remained pending until the user manually scrolled their rows into view.
- Users had to discover and run a second `caa cycle --on` command for the
  advertised launch behavior to work across offscreen rows.

## Resolution

- Initialize registered nested-subagent cycling ON with the launch injector.
- Keep `caa cycle --off` as the explicit opt-out and `caa cycle --on` as the
  re-enable command.
- Preserve exact-row identity, bounded cycle duration/task counts, interaction
  guards, scroll/focus restoration, and renderer circuit breakers.
- Keep Agent Window and top-level sidebar-conversation cycling deferred and
  separate from selected-parent nested-subagent recovery.

## Verification

Focused Python unit coverage asserts that the injector's initial renderer state
contains `cycleEnabled: true`. Live reinstall and Cursor validation remain part
of the post-review release check.

## Lesson

When launch promises automation is ON, bounded recovery required for routine
virtualized states should share that default instead of requiring a hidden
second opt-in.
