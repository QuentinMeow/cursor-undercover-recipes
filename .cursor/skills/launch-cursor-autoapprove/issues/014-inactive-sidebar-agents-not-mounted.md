---
id: 014
title: Inactive sidebar agents are not mounted chat surfaces
status: known-limitation
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

True simultaneous background approval is not available to the current
DOM-injection architecture. It can only inspect and click controls that Cursor
mounts for the selected chat.

A separate dedicated window is different: on Cursor 3.12.17, a visible window
with `document.hasFocus() === false` continued clicking real prompts. The
limitation here is specifically inactive conversations represented only by
sidebar rows in the same renderer.

A future opt-in feature could detect waiting-status sidebar rows, select each
one, scan/click, and restore the original row. That would be sequential rather
than simultaneous, visibly change the UI, and rely on unstable private DOM
selectors, so it is intentionally not enabled by default.

## Lessons extracted

See `../LESSONS.md` — "Sidebar Agent Mounting".
