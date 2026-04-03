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
