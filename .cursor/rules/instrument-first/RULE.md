---
description: Deploy instrumentation before forming hypotheses — evidence first, theory second
alwaysApply: true
---

# Instrument-First Debugging

## Problem This Solves

AI agents form hypotheses about failures and then look for confirming evidence.
This is backwards. The correct order is: collect evidence, then form hypotheses
that explain the evidence. When the agent guesses first, it spends time proving
itself right instead of finding the actual bug.

## The Principle

**When behavior diverges from expectation, your first action must be to
instrument — not to hypothesize.**

"Instrument" means: deploy a tool that captures the system's internal state
during the failure, in a structured format, without human involvement.

## The Protocol

### Step 1: Detect Divergence
Something didn't work as expected. The metric didn't change, the output is
wrong, the click didn't happen, the test failed.

### Step 2: Instrument (IMMEDIATELY)
Before asking "why did it fail?", deploy capture tooling:

- **For DOM/UI issues**: A polling diagnostic that captures element state,
  ancestry, computed styles, and application-level debug snapshots every
  200-500ms.
- **For API/network issues**: Request/response logging with full
  headers and bodies.
- **For process issues**: PID tracking, exit code capture, stdout/stderr
  interleaving with timestamps.
- **For state issues**: Periodic dumps of relevant state objects to
  structured JSON files.

Save captures to a timestamped directory (e.g., `/tmp/diagnostic-<timestamp>/`).

### Step 3: Reproduce
Re-trigger the failure while instrumentation is running. Do not change anything
yet — pure observation.

### Step 4: Read the Evidence
Read the captured data. Look for the specific step where expected and actual
behavior diverge. This is your root cause signal.

### Step 5: Hypothesize (NOW you can think)
With evidence in hand, form a hypothesis that explains what you observed.

### Step 6: Fix and Verify
Apply the fix. Re-run with instrumentation still active. Verify that the
specific divergence point is resolved.

## Why "Guess First" Fails

| Guess-First Pattern | Why It Fails |
|---------------------|-------------|
| "Maybe it's the wrong window" | You don't know until you check the window |
| "Maybe the selector changed" | You don't know until you query the DOM |
| "Maybe the config is stale" | You don't know until you read the config |
| "Maybe the element type is different" | You don't know until you scan all elements |

In every case, the fix for "you don't know" is instrumentation, not guessing.

## What Good Instrumentation Looks Like

- **Structured output** (JSON, not unstructured logs) so it's machine-parseable.
- **Periodic capture** (not one-shot) so transient states are caught.
- **Per-element detail** (tag, text, computed properties, ancestry) so you can
  see exactly what the system sees.
- **Saved to disk** so evidence survives the debugging session.
- **Self-documenting** (timestamps, context) so another agent can read the
  captures without knowing what to look for.

## Hard Rules

- **Never propose a fix without first capturing evidence of the failure.**
  "I think the problem is X" is not evidence. "The diagnostic shows X at
  tick 35" is evidence.
- **Never trust a system's self-report over direct observation.** If `status`
  says "loaded" but clicks are 0, the status is lying or incomplete. Observe
  the actual behavior.
- **Instrument broadly, then narrow.** Start by capturing everything in the
  relevant domain (all buttons, all elements, all state). Narrow after you
  see the data.

## Example: The Subagent Allow Button

The auto-clicker's diagnostic (which only queried `button, [role="button"]`)
showed zero candidates for subagent prompts. A broader scan (all elements with
approval-like text, regardless of tag) immediately revealed the Allow button
was a `<div>` with `cursor: pointer`, not a `<button>`. The fix was one line.

The broad scan took 30 seconds to write and run. It would have been done on
attempt 1 if this rule had been followed.
