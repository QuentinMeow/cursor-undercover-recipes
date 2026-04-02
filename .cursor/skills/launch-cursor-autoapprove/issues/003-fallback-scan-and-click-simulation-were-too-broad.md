---
id: 003
title: Fallback scan and click simulation were too broad for reliable approval-only behavior
status: resolved
severity: high
root_cause: The injector still fell back to broad whole-window scanning and used aggressive click simulation, which could either click unrelated controls or behave inconsistently across Cursor surfaces.
resolved_at: 2026-04-02
lesson_extracted: true
---

## Symptoms

After fixing substring matching (issue 002), behavior was safer but still had
two structural risks:

1. Candidate discovery could still scan broadly when chat-adjacent anchors were
   absent.
2. Click execution used multiple synthetic events plus Enter keydown, which was
   stronger than needed and harder to reason about.

## Root Cause

The original injector was optimized for “click something that works” rather
than “click only likely approval controls.” This left residual risk in two
areas:

- **Selection scope**: broad fallback scanning without structural guardrails.
- **Click semantics**: dispatching pointer/mouse events and synthetic Enter in a
  way that could trigger side effects beyond a normal click.

## Fix

1. **Structured candidate roots**:
   - chat-adjacent siblings above `div.full-input-box`
   - modal/prompt roots (`dialog`, `popover`, `dropdown`)
   - composer-root fallback

2. **Approval safety gate**:
   - approval candidates now require a nearby dismissal control
     (`skip`, `cancel`, `dismiss`, `deny`, `not now`, `close`) within ancestor
     depth <= 6.

3. **Conservative click strategy**:
   - focus + native `el.click()` when available
   - fallback to one mouse click event
   - removed synthetic Enter keydown.

4. **Richer click telemetry**:
   - click entries now include `kind` (`approval`, `connection`, `resume`) to
     aid debugging and manual verification.

## Lesson

For UI auto-approval in an IDE, exact text matching alone is not enough.
Robustness requires all of:

1. constrained discovery roots
2. structural safety gates (nearby dismissal/proximity checks)
3. minimal click simulation semantics
4. explicit telemetry for post-hoc validation
