---
id: 014
title: Inactive sidebar agents are not mounted chat surfaces
status: resolved
severity: medium
root_cause: Cursor mounts only the selected agent conversation in the workbench DOM; pinned and inactive agents are navigation rows without approval controls.
lesson_extracted: true
---

## Question

Can the DOM injector approve all pinned/sidebar agents at the same time instead
of only the selected conversation?

## Direct evidence

Tested on Cursor 3.12.17 through the dedicated session's bound CDP target:

1. With the current conversation selected, the renderer contained one
   `div.full-input-box`, one `div.conversations`, and no approval controls in
   inactive sidebar rows.
2. A pinned row (`Global skill for branch cleanup`) was selected through its
   `.agent-sidebar-cell`.
3. After the new chat loaded, the selected row changed but the renderer still
   contained exactly one input and one conversations container.
4. The original conversation was selected again and confirmed restored.

The pinned row did not have a hidden composer or prompt DOM before selection.
Selection replaced the mounted conversation.

## Conclusion

True simultaneous background approval is not available to the DOM-injection
architecture. It can inspect and click controls only after Cursor mounts the
selected chat, so multi-pinned support must be sequential.

A separate dedicated window is different: on Cursor 3.12.17, a visible window
with `document.hasFocus() === false` continued clicking real prompts. The
limitation here is specifically inactive conversations represented only by
sidebar rows in the same renderer.

## Resolution

The default cycle scheduler now adds a bounded top-level path:

- discover `.agent-sidebar-cell` rows under the exact `Pinned` section and
  require each title to be unique across the currently rendered Agent sidebar
- automatically visit only active unselected rows while the Agent Window is
  unfocused
- require exact sidebar selection plus one matching selected editor resource
  before scanning the mounted conversation
- re-resolve each unique title and Pinned-section row immediately before its
  visit so prior remounts cannot recycle a later target
- reuse scoped candidate policy, raw-control confirmation, and the two-attempt
  cap
- give pinned work a separate 3.5-second, two-row round-robin budget so nested
  recovery retains its full budget
- re-resolve the original unique title and resource before restoring its
  transcript scroll, editor tabs, and focus
- abort the whole cycle on a focus transition and preserve any newer user
  sidebar/tab/scroll selection instead of restoring stale automation state
- hold exclusive navigation ownership from before mount until restoration is
  observed, withholding even body-level portal candidates to prevent
  direct-scanner races on unattributed pending controls
- let explicit `cycle --once` visit completed pinned rows for a deterministic
  two-row restoration test

Duplicate titles and ambiguous original selection fail closed. Status and
history expose pinned visit/attempt/confirmation/failure and restoration
telemetry.

Live Cursor 3.12.17 verification with injector `538f6927c92e` used the current
conversation plus one completed pinned history row. An explicit cycle reported
two visits; a scoped synthetic `View` + `Allow` prompt in the history row was
clicked and confirmed exactly once; the original row and selected tab were
restored. A separate automatic-mode probe with `document.hasFocus() === false`
and a temporary active marker visited only the unselected row once and restored
the original. Subsequent automatic cycles made zero pinned visits after the
marker was removed. Race probes also preserved a newer user selection and kept
a temporarily disabled/hidden control unconfirmed without a second click.

Unpinned history rows remain outside automatic scope. The nested
`N subagents running` composer tray remains a separate recovery path.

## Lessons extracted

See `../LESSONS.md` — "Sidebar Agent Mounting".
