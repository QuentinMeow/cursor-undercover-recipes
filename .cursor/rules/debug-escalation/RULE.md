---
description: Mandatory debug escalation ladder — prevents agents from repeating failed approaches
alwaysApply: true
---

# Debug Escalation Protocol

## Problem This Solves

AI agents often repeat a failed debugging approach, burning time and user trust.
This rule forces strategy escalation after repeated failures instead of retrying
harder on the same path.

## The Escalation Ladder

When a fix or diagnostic attempt **fails**, escalate through these levels in
order. Never stay on the same level for more than **two attempts**.

### Level 1: Quick Check (attempt 1–2)

- Run the existing diagnostic commands (e.g., `status`, `diagnose`).
- Check the most obvious cause (wrong target, wrong config, typo).
- If the quick check reveals the issue, fix and verify.

### Level 2: Instrument (attempt 3–4)

- **Deploy a live capture tool** that records the system's internal state during
  the failure. Do not form a new hypothesis — collect evidence first.
- Save structured snapshots (JSON, not just console logs) to a timestamped
  directory.
- Re-trigger the failure while the capture tool is running.
- Read the captured data before proposing any fix.

### Level 3: Broaden the Search (attempt 5–6)

- Challenge every assumption made at Level 1–2. Explicitly list them and verify
  each one with concrete evidence (process lists, window titles, version strings,
  DOM dumps — whatever is relevant).
- Check if the environment itself is different from what you assumed (wrong
  window, wrong process, wrong version, stale config).
- Search for elements by the broadest possible query (e.g., all elements with
  matching text, not just `<button>` tags).

### Level 4: Replan (attempt 7+)

- Stop executing. Write a structured diagnostic plan that includes:
  1. What has been tried and what each attempt revealed.
  2. What assumptions remain unverified.
  3. What fundamentally different approaches exist.
  4. What tools could be built to get direct evidence.
- Present the plan to the user (or execute it if operating autonomously).

## Counting Failures

A "failure" is any of:
- The fix didn't change the observed behavior.
- The diagnostic showed the same result as the previous attempt.
- The expected metric (click count, test pass, etc.) didn't improve.

## Hard Rules

- **Never repeat the exact same command/fix and expect different results.**
  If you ran it and it didn't work, something upstream is different from what
  you assumed. Find what.
- **Never trust a passing synthetic test as proof that real usage works.**
  Synthetic probes can bypass the exact code paths that fail in production.
  Always validate with real inputs after synthetic tests pass.
- **If you catch yourself saying "let me try that again"** — you are on the
  wrong level. Escalate.

## Example: The Auxiliarybar Incident

An auto-clicker had 0 real clicks. The agent's debugging went:
1. Level 1: `status` → loaded, `diagnose` → synthetic probe passed. **Wrong conclusion: "it works."**
2. Level 1 again: same commands. Same result. **Stuck — should have escalated.**
3. User coached: "replan with harness engineering mindset."
4. Level 2: Deployed a CDP polling diagnostic. Captured per-button state during real prompts.
5. Level 2 evidence: buttons were in `workbench.parts.auxiliarybar` (excluded zone). Synthetic probes bypassed this.
6. Fix: made excluded zones conditional. Verified with real click count delta.

The fix took 15 minutes once Level 2 was reached. The Level 1 loop wasted 45+ minutes.
