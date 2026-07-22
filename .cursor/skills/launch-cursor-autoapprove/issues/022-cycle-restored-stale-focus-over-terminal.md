---
id: 022
title: Subagent cycle restored stale chat focus over terminal typing
status: resolved
severity: critical
root_cause: Recovery captured focus once, then unconditionally focused that stale element after asynchronous row/tray work; a user who moved to the terminal during the cycle could be sent back to the agent surface.
lesson_extracted: true
---

## Symptoms

- The user was typing in Cursor's integrated terminal.
- Focus moved into the agent UI while a subagent recovery cycle ran.
- The main direct approval scanner did not navigate tabs, but registered-row
  recovery was materializing and approving parent transcript rows.

## Evidence

The event ledger at the report time showed no running-tray visits. It showed
registered-row cycles with one `Allow | Stop` approval, including a cycle from
`07:37:21.636Z` to `07:37:21.790Z`.

Code inspection found two unconditional stale-focus writes:

- `_restoreScrollContext()` focused the element captured at cycle start.
- `_restoreEditorSelectionContext()` independently did the same after tab
  restoration.

The start-only two-second interaction guard could not protect a user who moved
to the terminal after a cycle began. It also allowed a cycle after the terminal
had been focused but idle for more than two seconds.

## Resolution

- Automatic row/tray recovery now pauses whenever the focused Cursor window has
  the terminal or another non-composer editable surface focused.
- Real pointer/keyboard interactions increment an interaction generation and
  retain the latest user-selected editable target.
- Scroll and tab restoration no longer call `focus()` themselves.
- One focus-settle owner restores either the original target or the newer user
  target. It runs immediately and again after 300 ms to survive Cursor's
  asynchronous post-approval focus, while always resolving the latest user
  interaction before acting.
- Direct visible-prompt clicks use the same focus-settle owner, so Cursor's
  post-approval behavior cannot move an active terminal even when no recovery
  navigation was needed.
- `status` reports the active focus kind, any cycle focus block, and the last
  focus-settle outcome.

## Verification

In a live dedicated renderer, the terminal's real
`textarea.xterm-helper-textarea` was focused while `document.hasFocus()` was
forced true for a controlled automatic-cycle probe. The cycle returned
`terminal_focused`, the terminal remained active, and `status` reported:

```text
Cycle:     OFF
Focus:     terminal
```

The direct mounted approval scanner also handled a visible `Allow` while the
terminal remained the active element.

A deterministic live prompt then simulated Cursor focusing the composer 100 ms
after a direct approval click. Focus telemetry showed:

```text
before:              terminal
cursor_async_100ms:  composer
settled_400ms:       terminal
```

`lastFocusRestore` reported `direct_scan`, `delayed`, `restored`, and
`targetKind: terminal`.

## Lesson

Never restore a focus snapshot after asynchronous automation without checking
whether the user interacted meanwhile. Focused editing surfaces should block
automatic navigation, and delayed focus correction must follow the newest user
target rather than the cycle's stale starting target.
