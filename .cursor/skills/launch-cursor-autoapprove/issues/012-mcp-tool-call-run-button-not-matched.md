---
id: 012
title: MCP tool call Run button not matched by BUTTON_SELECTORS
status: resolved
severity: high
root_cause: >
  MCP tool call prompts render Run/Skip as <div class="anysphere-button
  composer-run-button"> and <div class="anysphere-text-button
  composer-skip-button">. The "anysphere-button" class does not contain
  "primary-button", "secondary-button", "text-button", or "action-label", so
  the Run button was invisible to every BUTTON_SELECTOR. Skip was found via
  [class*="text-button"] but never evaluated because no approval candidate was
  discovered.
resolved_at: 2026-04-06
lesson_extracted: true
---

## Symptoms

- Gate ON, injector hash healthy, observer active.
- MCP tool call prompt ("Run Get Channel History in slack") stayed at
  "Waiting for Approval..." until manual click.
- `caa status` click count unchanged during the blocked prompt.
- Shell command `Run⏎` prompts and subagent `Allow`/`View` prompts continued
  to work normally.

## Root Cause

MCP tool call prompts use Cursor's `anysphere-button` component class for the
primary action button, not the `primary-button` / `secondary-button` classes
used by older surfaces. The DOM structure (confirmed via live CDP inspection):

```
div (wrapper)
  └── div.composer-tool-call-status-row
       └── div.composer-tool-call-control-row
            ├── div > div.anysphere-text-button.composer-skip-button  ("Skip")
            └── div > div.anysphere-button.composer-run-button        ("Run⏎")
```

Both buttons:
- Are `<div>` elements (not `<button>`)
- Have no `role="button"` attribute
- Have `data-click-ready="true"` attribute
- Live inside `composer-tool-call-container composer-mcp-tool-call-block`
  within `workbench.parts.auxiliarybar`

The Run button's `anysphere-button` class matched none of the existing
`BUTTON_SELECTORS`:

| Selector | Matches Run? | Why |
|----------|-------------|-----|
| `button` | No | `<div>`, not `<button>` |
| `[role="button"]` | No | No role attribute |
| `[class*="primary-button"]` | No | Class is `anysphere-button` |
| `[class*="secondary-button"]` | No | |
| `[class*="text-button"]` | No | |
| `[class*="action-label"]` | No | |

The Skip button's `anysphere-text-button` class DID match
`[class*="text-button"]`, but since the Run button was never discovered as an
approval candidate, the Skip button's role as a nearby dismissal was never
evaluated.

## Fix

Added `'[class*="anysphere-button"]'` to `BUTTON_SELECTORS`. This matches
both `anysphere-button` (Run) and `anysphere-text-button` (Skip) — Cursor's
own button component classes.

The existing policy pipeline handles the rest without changes:
- `_isComposerSurface` finds the button (auxiliarybar hosts `div.full-input-box`)
- `hasNearbyDismissal` finds "Skip" nearby
- `_eligibilityReason` returns `"dismiss"` — click proceeds

## Affected versions

- Cursor 3.0.9 (confirmed).
- Likely any Cursor version that renders MCP tool call prompts with the
  `anysphere-button` component class.

## Evidence

- Live CDP DOM inspection of gocmp session with MCP prompt visible.
- `diagnose` DOM snapshot showed Skip with `excluded: true` (from its own
  broader enumeration) and Run button completely absent from button inventory.
- Shell command `Run⏎` (59 clicks) and subagent `Allow` (companion reason)
  continued working — confirming the issue was selector-specific, not a
  zone/policy regression.

## Related

- [011](011-auxiliarybar-chat-surface-blocked-by-excluded-zones.md): Auxiliary
  bar chat surface blocked by excluded zones (same workbench part, different
  failure mode).
- [008](008-allow-view-companion-not-recognized.md): Allow+View companion
  pattern (similar "button found but policy blocks" pattern, though here the
  button was never found at all).
