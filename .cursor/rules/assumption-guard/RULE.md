---
description: Verify assumptions with evidence before acting on them — never state unverified facts
alwaysApply: true
---

# Assumption Guard

## Problem This Solves

AI agents confidently state things they haven't verified, then build debugging
strategies on those unverified claims. When the assumption is wrong, all
downstream work is wasted.

## The Rule

**Before stating any fact about the runtime environment, verify it with a
concrete check.** If you cannot verify it, explicitly mark it as an assumption.

## What Must Be Verified

### Environment State
- Which process/window/terminal is the user working in? → Check process lists,
  window titles, session state files.
- What version of the software is running? → Check version commands, not memory.
- Is the target system actually receiving your commands? → Check connection
  status, not assumptions about routing.

### Temporal Claims
- When did something start or happen? → Check timestamps in logs, not your
  estimate of elapsed time.
- Is a process still running? → Check PID/process status, not the last known
  state.

### Causal Claims
- "X is causing Y" → Show evidence that X is present AND that removing/changing
  X changes Y. Correlation is not causation in debugging.

## How To Mark Assumptions

When you cannot verify something, say so explicitly:

- **Bad**: "The user is in the normal Cursor window, not the dedicated one."
- **Good**: "I haven't verified which Cursor window is active. Let me check the
  window title and session state."

- **Bad**: "The session started at 7:50 PM."
- **Good**: "The session metadata shows a launch timestamp — let me read it."

## Verification Patterns

| Claim Type | Verification Method |
|-----------|-------------------|
| Active window/process | `ps`, window title, session state file |
| Software version | `--version` flag, binary metadata, update URL |
| Config state | Read the config file, don't assume from memory |
| Connection status | Health check command, not "it was connected earlier" |
| DOM/UI state | Live query via CDP/DevTools, not cached snapshot |
| Time/duration | Timestamps from logs, not wall-clock estimation |

## Hard Rules

- **Never state "the user is in X" without checking.** Window focus, terminal
  multiplexing, and dedicated processes make this unreliable by intuition.
- **Never state "X started at time T" without reading a timestamp.** Human
  time estimation across sessions is unreliable; log timestamps are not.
- **Never build a fix based on an unverified causal claim.** If you haven't
  proven the cause, you're guessing — and guesses compound.
- **When the user corrects an assumption, re-examine all conclusions built
  on that assumption.** They are all suspect.

## Example: The Wrong-Window Misdiagnosis

The agent claimed the user was in the normal Cursor window based on a DOM query
that checked for an "active chat" indicator. The user corrected: "I launched you
via `caa launch cursor` command." The agent had built an entire debugging theory
on the wrong-window assumption, wasting ~20 minutes.

The fix: always check session state (`caa status`) which shows the bound target
ID, workspace, and window title — concrete evidence, not inference.
