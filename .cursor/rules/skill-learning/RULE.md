---
description: Skill learning framework — automated issue tracking, testing, and lesson extraction for all skills
globs: ".cursor/skills/**"
alwaysApply: false
---

## Purpose

Every skill should accumulate operational knowledge over time. When an agent
encounters a bug, misdiagnosis, or unexpected behaviour while using a skill, it
must record what happened, why, and what general principle prevents recurrence.
This creates a feedback loop that makes each skill more reliable without human
intervention.

## Required Directories

Every skill under `.cursor/skills/<skill-name>/` must include:

| Path | Purpose |
|------|---------|
| `tests/` | Validation scripts, fixtures, and expected-output files |
| `issues/` | Structured issue records (one file per issue) |
| `LESSONS.md` | Accumulated generic lessons extracted from resolved issues |

Create these directories when first working on any skill that lacks them.

## Issue Recording

When an agent encounters a failure, unexpected behaviour, or misdiagnosis while
using a skill:

1. Create a new file at `issues/<NNN>-<slug>.md` (zero-padded 3-digit sequence).
2. Use this template:

```markdown
---
id: <NNN>
title: <concise title>
status: open | resolved
severity: critical | high | medium | low
root_cause: <one-sentence root cause>
resolved_at: <ISO date or empty>
lesson_extracted: true | false
---

## Symptoms

What happened and how the failure manifested.

## Root Cause

Why it happened — the underlying mechanism, not just the surface trigger.

## Fix

What was changed to resolve it.

## Lesson

The generic principle extracted (copied verbatim into LESSONS.md when resolved).
```

3. Mark `status: resolved` and `lesson_extracted: true` once the fix is verified
   and the lesson has been added to `LESSONS.md`.

## Test Expectations

- `tests/` must contain at least one runnable validation script per skill.
- After making changes to a skill, run its tests. Record failures as issues.
- Tests should produce machine-readable output (JSON, exit codes) so agents
  can programmatically verify pass/fail rather than interpreting prose.

## Lesson Extraction

After resolving an issue, extract a **generic lesson** — a transferable
principle, not a point fix — and append it to `LESSONS.md`.

### Quality Filter

Before writing a lesson, apply these gates:

| Gate | Good example | Bad example |
|------|-------------|-------------|
| **Generic** — applies beyond the specific bug | "Safety gates that inspect UI element text must distinguish interactive elements from document content; checking the element's own AXPress action is more reliable than checking ancestors." | "Set max_levels to 7 not 3." |
| **Actionable** — an agent can follow it in future work | "Validation scripts must classify outcomes by log evidence, not by observing whether a command completed." | "Be careful with timestamps." |
| **Non-obvious** — the agent wouldn't already know this | "Electron apps expose all editor text as AXStaticText with pressable ancestors, making ancestor-based clickability checks unreliable for filtering document content." | "Test your code after making changes." |

Reject lessons that fail any gate. Noise (obvious, specific, or non-actionable
observations) degrades the signal-to-noise ratio and makes the file useless.

### LESSONS.md Format

```markdown
# Lessons

## <Category>

- **<Principle>**: <Explanation of why this matters and when to apply it.>
```

Group lessons by category (e.g., "Accessibility scanning", "Validation",
"Safety gates"). Each lesson is one bullet: bold principle, then explanation.

## Continuous Improvement Loop

```
encounter problem → record issue → fix → verify with tests → extract lesson → update LESSONS.md
```

Agents must follow this loop automatically whenever they hit a problem during
skill usage. Do not wait for human instruction to record issues or extract
lessons.

## Anti-Patterns

- **Overfitting**: Writing a lesson that only applies to the exact bug you just
  fixed. Ask: "Would this help someone who hits a *different* bug in the same
  category?"
- **Workarounds over fixes**: A lesson that says "add X to a hardcoded list"
  is a workaround. A lesson that says "the matching logic should normalize
  inputs using Y" is a generic fix.
- **Noisy logging**: Recording every minor observation as an issue. Only record
  problems that caused incorrect behaviour, wasted time, or required human
  intervention.

## Read Order

1. Check `LESSONS.md` before modifying a skill — it contains hard-won
   operational knowledge.
2. Check `issues/` for open issues before starting new work on a skill.
3. Run `tests/` after making changes to verify nothing regressed.
