---
description: Evidence-first harness engineering principles for AI agent reliability
alwaysApply: false
globs:
  - ".cursor/skills/**"
  - ".cursor/rules/**"
---

# Agent Harness Engineering

These principles apply whenever building, modifying, or operating tools that
AI agents use autonomously. The goal is trustworthy signals over optimistic
assumptions.

## Core Principles

1. **Validate mechanisms, not just outcomes.** A command that "succeeds"
   silently might be acting on the wrong target. Verify the actual mechanism
   (e.g., which CDP target received the evaluation) rather than assuming
   success from a non-error return code.

2. **Fail closed on ambiguity.** When there are multiple possible targets,
   pages, or sessions, do not silently pick one. Either require explicit
   disambiguation or fail with a clear diagnostic. False-positive success
   is worse than a visible failure.

3. **Observability before features.** Diagnostics, logging, and status
   reporting must be correct and trustworthy before adding new capabilities
   on top. A feature built on misleading health signals will compound errors.

4. **Durable evidence.** In-memory state (click counts, gate status) is lost
   on crash or reload. Maintain an append-only event log so post-hoc analysis
   is possible even when the process is gone.

5. **Explicit drift detection.** When on-disk artifacts (scripts, configs)
   can diverge from in-process state, implement hash comparison and surface
   mismatches visibly. "Stale but looks healthy" is a common failure mode.

6. **Multi-agent adversarial review.** One agent may be wrong; multiple
   independent agents reviewing the same approach increases confidence. Use
   research agents, skeptical reviewers, and implementation agents in
   parallel when the stakes are high.

7. **Prefer fixed workflows over open-ended loops.** Use the smallest control
   flow that can prove correctness: explicit steps, bounded retries, and clear
   exit conditions before adding more autonomy.

8. **Machine-checkable done criteria.** Define success in terms of tests, exit
   codes, status fields, diff checks, or other durable signals rather than the
   model's self-report.

## High-Stakes Review Cadence

When the work touches auth, GitHub automation, release flow, or safety-critical
agent tooling, add these independent checks before finalizing:

- **Goal auditor ("take one thousand steps back")**: verify the work still
  targets the user's real objective and not a narrower local optimization.
- **Step-back reviewer ("take a step back")**: challenge hacky patches,
  accidental complexity, and architectural drift.
- **Design skeptic**: look for a smaller trusted surface or simpler mechanism.
- **Test skeptic**: confirm the planned tests and manual checks exercise the
  claimed behavior instead of only the implementation shape.

Parallelize independent analysis, then serialize conflicting edits through one
integrator. If these reviewers disagree or the evidence is weak, stop and ask
the user instead of pushing ahead.

## Applying These Principles

When working on the `launch-cursor-autoapprove` skill or similar harnesses:

- Every CDP command must target a pinned identifier, not a dynamic first-match.
- `status` must surface target identity, target count, drift, and ambiguity
  warnings — not just a "Gate: ON" summary.
- Title and visual signals are convenience labels, not proof of correctness.
  The event log and status diagnostics are the source of truth.
- Before adding a new approval pattern or click target, instrument it in
  diagnostics first, then verify with manual testing, then enable the
  auto-click.

## Related

- `launch-cursor-autoapprove` skill: `.cursor/skills/launch-cursor-autoapprove/SKILL.md`
- Issue 004 (multi-workbench misbinding): `.cursor/skills/launch-cursor-autoapprove/issues/004-cdp-targets-wrong-workbench-in-multi-window.md`
- Lessons: `.cursor/skills/launch-cursor-autoapprove/LESSONS.md`
