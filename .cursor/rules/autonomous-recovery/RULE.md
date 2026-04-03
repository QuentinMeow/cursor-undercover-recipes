---
description: Self-correction loop for stuck agents — step back and replan without waiting for human coaching
alwaysApply: true
---

# Autonomous Recovery Loop

## Problem This Solves

When an AI agent gets stuck, it often continues on the same path until a human
says "step back and think about this differently." This rule makes that step-back
automatic.

## The Recovery Loop

After every action that produces a result, run this mental checklist:

### 1. Did the result match expectations?

If YES → proceed to next step.
If NO → enter the recovery loop:

### 2. What did I assume?

List every assumption that led to this action. Common categories:
- Environment: which process, window, version, config
- Structure: which element, container, selector, API shape
- Causality: what's causing the observed behavior
- Timing: when things started, how long they've been running

### 3. Which assumptions are verified vs unverified?

For each assumption, ask: "What concrete evidence do I have for this?"
- If evidence exists → mark as verified.
- If no evidence → mark as **unverified** and prioritize checking it.

### 4. What tools can I deploy to get evidence?

For each unverified assumption, identify the simplest tool or command that
would confirm or deny it. Prefer tools that produce structured, saved output.

### 5. Am I repeating a failed approach?

If your proposed next action is substantially similar to something that already
failed:
- **STOP.** You are in a loop.
- Write down what the failed approach assumed.
- Identify a **fundamentally different** approach (different tool, different
  entry point, broader scope, different abstraction level).

## Trigger Conditions

Enter the recovery loop **automatically** when any of these occur:

- A fix didn't change the observed metric (click count, test result, etc.)
- The same error or symptom appears after a fix attempt
- You realize you're about to re-run a command you already ran
- A diagnostic shows the same state as before your intervention
- You've been working on the same sub-problem for more than 3 action cycles
  without progress

## The "Stuck" Heuristic

You are stuck if TWO OR MORE of these are true:
1. The last two actions produced no new information.
2. You are considering re-running something that already ran.
3. Your confidence in the root cause is below 60%.
4. The user has corrected an assumption in the last 3 messages.

When stuck, your **first** action must be deploying new instrumentation — not
proposing another fix.

## What "Fundamentally Different" Means

| Same Approach (don't repeat) | Different Approach (try this) |
|------------------------------|------------------------------|
| Re-run the same selector query | Scan ALL elements regardless of type |
| Check the same log file again | Deploy a live polling diagnostic |
| Assume the config is correct | Read and print the actual config |
| Re-run the fix with minor tweaks | Instrument the failure point first |
| Trust the status command | Directly observe the running system |

## Hard Rules

- **Never wait for the user to say "step back."** That's your job.
- **Never say "let me try that again" without explaining what's different.**
  If nothing is different, you're in a loop.
- **After any user correction, immediately re-examine all prior conclusions**
  that depended on the corrected assumption. They are all potentially wrong.
- **When in doubt, instrument.** The cost of unnecessary instrumentation is
  minutes. The cost of continuing on a wrong path is hours.
