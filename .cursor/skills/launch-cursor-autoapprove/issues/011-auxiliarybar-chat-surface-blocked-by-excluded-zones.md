---
id: 011
title: Auxiliary bar chat surface blocked by excluded zones
status: partial
severity: critical
root_cause: Chat UI moved into workbench.parts.auxiliarybar (an excluded zone); composer DOM no longer places conversations as a sibling of div.full-input-box; SkipEsc concatenation broke stripKeyboardHints dismissal matching.
lesson_extracted: false
---

## Symptoms

- Starting around Cursor 3.0.8, the chat/agent panel lives under
  `workbench.parts.auxiliarybar`, which the injector excludes to avoid false
  positives on explorer/panel controls (see issue 002).
- **Impact**: Total auto-click failure on real prompts in the dedicated window:
  zero candidates, zero clicks, zero blocked events.
- Synthetic CDP probes still passed because they inject `role="dialog"` elements,
  bypassing both the excluded-zone filter and the broken sibling scan.

## Root Cause

Three bugs compounded:

1. **`isInExcludedZone()`** returned true for every chat approval button because
   they sit inside `workbench.parts.auxiliarybar`.

2. **`findApprovalButtons()` sibling scan** used `inputBox.previousElementSibling`.
   After the DOM change, `div.full-input-box` has no such sibling: messages live
   under `div.conversations`, a **cousin** under `div.composer-bar.editor`, not a
   sibling of the input wrapper.

   New shape (simplified):

   ```
   div.composer-bar.editor
     ├── div.conversations (messages + approval buttons)
     └── div
         └── div.composer-input-blur-wrapper
               └── div.full-input-box
   ```

3. **`stripKeyboardHints()`** only stripped trailing `Esc` when preceded by
   whitespace. Cursor renders the Skip control as concatenated `SkipEsc`, which
   normalized to `skipesc` and failed to match `skip` in `DISMISS_PATTERNS`, so
   the nearby-dismissal check failed for paired controls like `Run`.

## Fix

1. **`isInExcludedZone(el)`**: If the matched excluded zone contains
   `div.full-input-box`, treat it as hosting the chat surface and **do not**
   exclude:

   ```javascript
   function isInExcludedZone(el) {
     for (const sel of EXCLUDED_ZONES) {
       const zone = el.closest(sel);
       if (zone) {
         if (zone.querySelector("div.full-input-box")) return false;
         return true;
       }
     }
     return false;
   }
   ```

2. **`findApprovalButtons()`**: Walk up from the input box (up to a few ancestor
   levels) and scan **siblings at each level**, not only direct siblings of the
   input box.

3. **`_isComposerSurface()`**: Walk **up** from the shallow `inputBox` and use
   `node.contains(el)` at each level so deeply nested buttons are not missed by
   a depth limit.

4. **`stripKeyboardHints()`**: Replace whitespace-dependent trailing-`Esc`
   handling with a regex that strips trailing `Esc` / `Escape` with or without
   preceding space, when at least two characters precede the hint.

## Affected versions

- Cursor 3.0.8 (Chrome/142.0.7444.265).
- Likely any build where the agent chat panel renders inside
  `workbench.parts.auxiliarybar`.

## Current status

- **Partially fixed**: Shell command **Run** prompts auto-click correctly again.
- **Still open**: Subagent **View+Allow** prompts — separate investigation
  needed.

## Related

- [002](002-dom-injector-clicks-explorer-and-editor-elements.md): DOM injector
  clicks explorer/editor elements (original motivation for `EXCLUDED_ZONES`).
- [010](010-plain-text-esc-shortcut-suffix-blocked-shell-command-cards.md):
  Plain-text Esc shortcut suffix on shell command cards.

## Debugging method (key lesson)

The decisive signal came from a **live CDP diagnostic poller**: a small Python
script connecting to the dedicated window over CDP WebSocket every 300–500ms,
evaluating `acceptDebugSnapshot()` plus ad hoc DOM queries.

- By tick 35+, snapshots showed `approvalTextFound: true` but
  `candidateCount: 0`, `dialogCount: 0`, `siblingCount: 0` — proving the prompt
  was on screen while discovery returned nothing.
- A deep ancestry walk from `div.full-input-box` showed the path through
  `workbench.parts.auxiliarybar`.
- Targeted checks (`zone.querySelector("div.full-input-box")`,
  `node.contains(el)` from `inputBox`) validated the fix before deployment.

**Lesson**: When synthetic harnesses pass but production UI fails, instrument
the **real** workbench DOM on a timer; snapshot fields that split “text visible”
from “candidates found” isolate zone vs. traversal bugs quickly.
