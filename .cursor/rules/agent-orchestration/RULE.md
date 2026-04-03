---
description: Repo-wide agent orchestration and adversarial review triggers
alwaysApply: true
---

# Agent Orchestration

Use the simplest workflow that can prove correctness. Do not spawn extra agents
for tiny, obvious tasks.

## When To Escalate

Add independent agent perspectives when the task is multi-file, ambiguous,
risky, auth-related, automation-heavy, or likely to create false confidence.

## Default Roles

1. **Goal auditor ("take one thousand steps back")**: Restate the user's real
   goal, non-goals, and what would prove the current direction wrong.
2. **Step-back reviewer ("take a step back")**: Check whether the current plan
   or patch is a hack, a local optimum, or an architectural mismatch.
3. **Design skeptic**: Look for a simpler or more durable design before
   locking in complexity.
4. **Test skeptic**: Verify the planned tests actually measure the claimed
   behavior instead of only mirroring the implementation.
5. **Historian**: Check `MEMORY.md`, `LESSONS.md`, and issue history before
   repeating a known failure mode.

## Operating Rules

- Parallelize independent analysis, then merge conclusions through one
  integrator before editing.
- Use evidence, not prompt theater: code references, diffs, tests, logs, or
  reproducible commands must support important claims.
- If reviewers disagree, evidence is weak, or the change is irreversible, stop
  and ask the user instead of guessing.
