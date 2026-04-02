---
id: 002
title: DOM injector clicks file explorer and editor elements matching approval patterns
status: resolved
severity: critical
root_cause: matchesApproval used substring matching (text.includes(pattern)) with no zone exclusion, so file names, editor text, and other non-approval UI containing words like "allow", "run", or "apply" triggered false-positive clicks.
resolved_at: 2026-04-02
lesson_extracted: true
---

## Symptoms

While the user was renaming a file in the explorer sidebar, the auto-accept
injector clicked on explorer items whose names or nearby text contained
approval-pattern substrings. Example: a file named
`ubagent-allow-button-autoapproval.md` matched the "allow" pattern.

The user also observed that the clicking stopped after typing in the chat
window, likely because the `div.full-input-box` anchor became active and the
primary scan path (near chat input) took precedence over the fallback path.

## Root Cause

Two compounding problems in `devtools_auto_accept.js`:

1. **Substring matching**: `matchesApproval` used `text.includes(pattern)`
   which matched "allow" inside "allow-button-autoapproval", "run" inside
   "running", "apply" inside "Apply Changes", etc.

2. **Unrestricted fallback scan**: When no buttons were found near the chat
   input box, `findApprovalButtons` fell back to scanning ALL
   `button, div[class*='button']` elements in the entire document, including
   the file explorer, editor, terminal panel, and auxiliary sidebar.

## Fix

Four changes to `devtools_auto_accept.js`:

1. **Exact matching after hint stripping**: `matchesApproval` now strips
   trailing keyboard shortcut glyphs (↩, ⏎, etc.) and parenthesized hints
   like `(⌃⏎)`, then compares the result with `===` instead of `.includes()`.
   This means "Run ↩" matches "run" but "ubagent-allow-button-autoapproval.md"
   does not match "allow".

2. **Zone exclusion**: Added `EXCLUDED_ZONES` array covering the sidebar,
   auxiliary bar, editor, and terminal panel. `matchesApproval` rejects any
   element inside these zones via `el.closest(selector)`.

3. **Max text length filter**: Elements with `textContent.trim().length > 60`
   are rejected, filtering out long file names, prose, and code content.

4. **Added missing patterns**: "run this time only" and "continue" were added
   to `APPROVAL_PATTERNS` to compensate for the switch from substring to exact
   matching.

## Lesson

DOM-level auto-clickers that scan the entire document for approval-like text
are inherently fragile in IDE environments where the document contains code,
file names, and prose that overlap with approval vocabulary. Two defenses are
both needed:

1. **Exact text matching** (not substring) with normalization for shortcut
   hints and whitespace.
2. **Spatial scoping** to known approval surfaces (chat panel, dialog
   overlays) with explicit exclusion of non-interactive zones (explorer,
   editor, terminal).

This is the DOM equivalent of AX-watcher issue 002 (watcher clicking document
text) — the same class of false-positive, different implementation layer.
