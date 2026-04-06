# Reviewer Best Practices

Research-backed guidance for making PRs reviewer-friendly, with specific advice
for stacked PR workflows.

## The Research

### SmartBear "Best Kept Secrets of Peer Code Review"

A study of 2,500+ code reviews at Cisco found:

- **Review effectiveness drops sharply above 200-400 lines.** Defect density
  found by reviewers declines as PR size increases. The sweet spot is under 400
  lines of change.
- **Review sessions longer than 60 minutes lose effectiveness.** Reviewers
  become fatigued and miss defects. Keep each PR reviewable in a single focused
  session.
- **Reviewers find fewer defects per line in large reviews.** A 200-line PR
  gets more thorough scrutiny per line than a 1,000-line PR.

### Google "Modern Code Review" (2018, Sadowski et al.)

Analysis of code review practices at Google scale:

- **Small CLs are reviewed faster.** Median time-to-first-review decreases
  with CL size. Small CLs also have higher approval rates.
- **Reviewers value context and motivation.** The most helpful CL descriptions
  explain *why* the change exists, not just *what* changed.
- **Incremental changes build reviewer trust.** A series of small, well-explained
  changes is easier to approve than one large change, even if the total lines
  are identical.

### Microsoft "Expectations, Outcomes, and Challenges of Modern Code Review" (2013)

Findings from a survey of 900+ developers:

- **Understanding is the #1 review goal.** Reviewers spend most of their effort
  understanding the change, not finding bugs. Reducing comprehension overhead
  (through smaller PRs, good descriptions, and logical ordering) directly
  improves review quality.
- **Reviewer preparation matters.** Reviewers who understand the broader context
  (what the feature is, how the PR fits into a larger effort) give better
  feedback. Stacked PRs with clear descriptions provide this context naturally.

## Practical Guidelines for Stacked PRs

### 1. Each PR should have a single purpose

A reviewer should be able to summarize the PR in one sentence. If it takes a
paragraph, the PR does too much.

Good:
- "Extract the shared request validation into a utility module."
- "Add the /books endpoint handler and route registration."
- "Add unit tests for the /books endpoint."

Bad:
- "Add books feature, refactor validation, update config, and fix a typo."

### 2. Order the stack bottom-up

Foundations first, consumers later. This lets reviewers build a mental model
incrementally:

1. Shared types, interfaces, utilities
2. Core business logic
3. Integration points (handlers, routes, CLI)
4. Tests
5. Config and deployment

Reviewers who approve PR1 have the context needed for PR2.

### 3. Make each PR self-contained where possible

Ideally, each stacked PR should compile and pass tests on its own. This:
- Lets CI validate each layer independently.
- Allows reviewers to approve and merge in order without waiting for the full
  stack.
- Reduces the blast radius if one PR needs rework.

When strict self-containment is impossible (e.g., PR2 adds a function that is
only called in PR3), document this clearly in the PR description.

### 4. Write PR descriptions for stacked context

Each stacked PR description should include:

- **Where it fits in the stack** (e.g., "PR 2 of 3").
- **What the previous PR established** (one sentence of context).
- **What this PR adds on top** (the TL;DR).
- **Links to the other PRs in the stack.**

Example intro (matches A.3b in pr-workflows-comprehensive.md):

> **Stack context**: PR 2 of 3 in the [books-feature stack](#link-to-aio-pr).
> AIO PR: #122 | Previous: #123 | Next: #125
>
> **Merge strategy**: AIO-merge — review here, merge via AIO PR #122.

### 5. Keep the diff focused

GitHub shows the diff between the stacked PR's branch and its base branch (the
previous PR). This means the reviewer sees only the incremental change -- which
is the whole point. To keep this clean:

- Do not include changes from the parent PR in the child PR's commits.
- If you need to fix something in a parent PR, fix it there and run `av sync`
  to propagate.
- Avoid "merge commits" from trunk that add noise to the diff.

### 6. Respond to review feedback promptly

In a stack, feedback on PR1 may require changes that cascade to PR2 and PR3.

**For stacked-merge**: Fix in the affected PR's branch, then `av sync --all`
to propagate to descendants.

**For AIO-merge**: Fix on the AIO branch (the merge target), then sync the
fix to affected stacked PR branches so review diffs stay accurate. See
pr-workflows-comprehensive.md Scenario C.4 for the detailed algorithm.

In both cases, notify the reviewer that the change has been made.

The faster this feedback loop runs, the faster the stack merges.

### 7. Do not force reviewers to review the whole stack at once

Stacked PRs are meant to be reviewed independently. Do not send a message like
"please review all 5 PRs." Instead:

- Ask for review on the first PR.
- Once it is approved, ask for review on the second, and so on.
- If a reviewer wants to look ahead, the links are in the description.

This respects the reviewer's time and keeps the feedback focused.

### 8. Handle the AIO PR according to the merge strategy

The AIO (All-In-One) PR's role depends on the chosen merge strategy:

**AIO-merge (default)**: The AIO PR is the **merge target**. Reviewers
review the stacked PRs for focused feedback, then the AIO PR gets approved
and merged. After the AIO merges, close all stacked PRs (do NOT merge them).

**Stacked-merge**: The AIO PR is **reference-only**. Each stacked PR gets
approved and merged individually, bottom-up. After all stacked PRs merge,
close the AIO PR (do NOT merge it).

In both cases:
- The AIO PR body should include a full summary plus a stacked PR table.
- Mark the AIO as Draft if using stacked-merge (so reviewers know not to
  approve it directly).

## Anti-Patterns

| Anti-pattern | Why it hurts | Fix |
|--------------|-------------|-----|
| 1,000+ line PR with "it's all related" | Reviewer fatigue, missed defects | Split by concern; use stacked PRs |
| Stacked PRs that don't compile independently | CI failures on each PR confuse reviewers | Adjust boundaries so each compiles |
| Reviewer asked to review all stacked PRs at once | Defeats the purpose of splitting | Request review sequentially |
| Stacked PR descriptions that assume reviewer saw previous PRs | Reviewers may start from any PR | Each description is self-contained |
| Rebasing the stack manually instead of using `av sync` | Merge conflicts, lost commits | Always use `av sync` |
| Splitting small generated code into its own PR | Noise; nobody reviews generated code | Keep small generated changes with the logic that triggered them; separate only if hundreds of lines |
