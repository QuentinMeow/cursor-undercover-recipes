# Splitting Strategy

Detailed decision framework for breaking a PR into stacked PRs.
[pr-workflows-comprehensive.md](pr-workflows-comprehensive.md) gives the
high-level flow; this document covers the nuances.

## Core Principle: Logic First, Lines Second

The primary axis for splitting is **logical concern**, not line count. Two
unrelated 100-line changes are better as two PRs than one 200-line PR, even
though 200 is under the threshold. Conversely, a single tightly-coupled 400-line
change may be best left as one PR if splitting would force the reviewer to
context-switch between interleaved halves.

Line counts are a **trigger for thinking**, not a splitting rule.

## What should NEVER be mixed in a single PR

These mixing anti-patterns make reviews harder. Each is a splitting signal:

- **Unrelated style/formatting changes mixed with logic changes.** Reviewers
  have to squint to find the real logic. Submit whitespace and style changes
  as a separate PR.
- **Large generated code mixed with logic changes.** If regenerating
  Thrift/protobuf schemas produces hundreds of lines, consider separating
  it so reviewers can focus on logic. Small generated changes can stay with
  the logic that triggered them.
- **Refactoring mixed with behavioral changes.** Pre-factor first in a separate
  PR, then introduce the logic change on top. This makes both PRs easy to
  review in isolation.
- **Multiple unrelated features in one PR.** Each commit should be its own
  atomic unit of work. If two features can be understood independently, they
  should be separate PRs.
- **Large code drops.** Thousands of lines introducing full new features while
  rewriting supporting infrastructure. These are hard to review and harder to
  bisect later.

## Decision Tree

Work through in order. Stop as soon as the PR is reviewer-friendly.

### Step 1: Identify independent concerns

Read the diff and ask: "Are there two or more changes that a reviewer could
understand in isolation?" Common patterns:

- A new feature + a bugfix that happened to land in the same branch.
- A refactoring + the behavioral change that uses the refactoring.
- Changes to two unrelated subsystems (e.g., API handler + CLI tooling).
- A migration + the code that depends on the migration.

If yes, each concern becomes a candidate stacked PR. Order them by dependency
(foundations first, consumers later).

If the concerns are tightly coupled (circular imports, interleaved in the same
functions), they probably belong in one PR.

### Step 2: Evaluate the size of each candidate

For each candidate, compute:

```
logic_lines = additions + deletions in LOGIC files (excluding comments/blanks)
test_lines  = additions + deletions in TEST files
config_lines = additions + deletions in CONFIG files
total_nontrivial = logic_lines + test_lines + config_lines
```

**Under 300 total nontrivial lines** -- the candidate is fine as-is.

**300-500 total nontrivial lines** -- consider whether tests/config can move to
a follow-up PR. If logic alone is under 300, splitting tests out makes the logic
PR very reviewable.

**Over 500 total nontrivial lines** -- strongly consider splitting further.
Check Step 3.

### Step 3: Split tests and config into follow-up PRs

Tests and config do not count as "real" changes for review purposes, but they
add visual noise in the GitHub diff view. Split them when:

- **Test lines exceed ~100.** A logic PR with 200 lines of logic and 300 lines
  of tests is better as two PRs: one with logic, one with tests. The reviewer
  can approve the logic first and skim the tests separately.
- **Config changes are mechanical and large.** Adding a new service to 15 YAML
  files is noise in a logic PR. Split it out.
- **The test changes are for existing code** (not new code in this PR). These
  are independently reviewable and should always be a separate PR.

Keep tests with logic when:
- There are fewer than ~50 lines of test changes.
- The tests are the primary evidence that the logic is correct (reviewer needs
  to see them together to approve).

### Step 4: Consider refactoring as a separate first PR

If splitting the logic into clean PRs would be easier after some file
reorganization (extracting a shared module, splitting a monolith file), make the
refactoring the **first** PR in the stack:

- The refactoring PR should be a **pure structural change** with no behavioral
  delta. This lets reviewers approve it quickly with high confidence.
- The subsequent logic PRs then operate on the cleaner structure.

Signs that a refactoring PR is warranted:
- A single file has >500 lines of changes and contains multiple logical
  concerns.
- The same utility function is duplicated in the diff because two subsystems
  both need it.
- Splitting would require moving code between files -- better to do that as a
  clean refactoring step first.

**Caution**: If the refactoring is large or risky, switch to plan mode and
present options. Never autonomously make large structural changes.

### Step 5: Consider alternative splitting strategies

If concern-based splitting (Step 1) doesn't yield clean boundaries, try:

**Walking skeleton**: Build a minimal end-to-end path through the feature first
(e.g., a route that returns a hardcoded response), then fill in real
implementations in follow-up PRs. Each PR adds a thin slice of functionality.

**Architectural layer**: Split by layer -- database schema, backend API/logic,
and frontend UX in 3 separate PRs. Each layer is independently reviewable.

**Interface-first**: Introduce the interface or type definitions first (with
empty or stub implementations), then fill in implementations in follow-up PRs.
Useful for large interface changes.

### Step 6: Verify each PR compiles/tests independently

After designing the split, mentally verify (or actually check) that each stacked
PR, when applied on top of its parent, produces a compilable/testable state.
If not, the boundaries need adjustment.

Common issues:
- PR2 uses a function introduced in PR1 but PR1 forgot to export it.
- PR3 has tests that import a fixture added in PR2 but the fixture file was
  assigned to PR1.
- A config change in PR3 references a new binary built in PR2.

## Edge Cases

### The PR is already small but has unrelated changes

Even if the total is under 300 lines, if there are two unrelated concerns,
splitting is still valuable. Reviewers prefer focused PRs.

### The logic is a single atomic change over 500 lines

This happens with large interface changes, protocol buffer updates, or
sweeping refactors. Options:

1. **Accept it.** Some changes are genuinely inseparable. Document why in the PR
   description and ask the reviewer to allocate time.
2. **Introduce the interface first** (empty implementations), then fill in
   implementations in follow-up PRs.
3. **Split by file** if different files implement independent parts of the same
   interface.

### Comment-heavy changes

If a PR adds 500 lines but 300 of them are comments or documentation strings,
the actual review burden is low. Do not split just to hit a line count target.

### Generated code

Auto-generated files (protobuf, swagger, mocks) should never drive a split.
Exclude them from line counts entirely. If the generated code is large, mention
it in the PR description so reviewers know to skip those files.

### Deletions-heavy PRs

A PR that deletes 800 lines and adds 50 is easy to review (the reviewer just
confirms the deletions are safe). Do not split deletion-heavy PRs unless the
deletions span unrelated areas.

## Example Splits

### Example 1: New API endpoint (450 logic + 200 test + 50 config)

```
Stack:
  PR1 (stack/refactor-shared-types)  -- 80 lines, extract shared request types
  PR2 (stack/add-books-endpoint)     -- 370 lines, new handler + route
  PR3 (stack/books-tests-config)     -- 250 lines, tests + config
```

Rationale: The shared types are used by the new endpoint but also by other code.
Extracting them first is a clean refactoring. Tests + config are bulky and
better reviewed separately.

### Example 2: Bugfix + unrelated cleanup (150 + 120 lines)

```
Stack:
  PR1 (stack/fix-timeout-handling)   -- 150 lines, the actual bugfix
  PR2 (stack/cleanup-deprecated-api) -- 120 lines, unrelated cleanup
```

Rationale: Even though the total (270) is under 300, these are independent
concerns. A reviewer should be able to approve the bugfix without thinking
about the cleanup.

### Example 3: Large refactoring (900 logic lines, tightly coupled)

```
Single PR -- no split.
```

Rationale: The changes are all part of a single architectural refactoring.
Splitting would create intermediate states that don't compile. Documented as
a large PR with a detailed description and reviewer guidance.
