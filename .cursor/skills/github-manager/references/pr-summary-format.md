# PR Summary Output Format

The PR summary is a **collaborative draft**. The agent fills in what it can
confidently derive from the diff, and marks everything else as a visible TODO
for the author. The summary covers **Why** (motivation), **How** (approach),
and **What** (effects/impact). "As titled" is never acceptable.

The layout uses progressive disclosure: only TL;DR and Goal are visible by
default; everything else is collapsed.

## TODO marker format

When the agent is not 100% confident about a section, insert this block:

```markdown
> **🔍 TODO(author):** [Clear prompt explaining what info is needed]
>
> _Guidance: [Specific instructions or examples to help the author fill it in]_
```

For reviewer-directed questions:

```markdown
> **🔍 TODO(reviewer):** [Question for the reviewer to consider during review]
```

These are intentionally loud (blockquote + emoji + bold) so they stand out when
scanning the PR body. The author should resolve all `TODO(author)` items before
requesting review. `TODO(reviewer)` items are discussion prompts for the review.

## Visible sections (always expanded)

> Do NOT include a title/heading in the PR body. GitHub already shows the PR
> title above the body. Start directly with the TL;DR.
>
> **Exception for stacked/AIO PRs**: When using the stacked PR workflow
> (stacked/AIO workflows in
> [pr-workflows-comprehensive.md](pr-workflows-comprehensive.md) scenarios B–E),
> the PR body starts with a stack context blockquote (merge strategy +
> navigation links) BEFORE the TL;DR. See that doc A.3a (AIO PRs) and A.3b
> (stacked PRs) for the exact format.

### 1) TL;DR

2-5 bullets summarizing the biggest behavioral changes. Most reviewers will
only read this.

If you can determine the behavioral changes from the diff, write them
confidently. If any are ambiguous, add a TODO:

```markdown
- Add exponential backoff to token refresh
- 🔍 *TODO(author): Is the max-retries default (3) appropriate for production?*
```

### 2) Goal / Motivation

Cover **Why** (what pain it fixes), **How** (approach taken), and **What**
(effects/impact). 1-3 short paragraphs.

If motivation is clear from the diff (e.g., a bug fix with an obvious trigger),
write it. If not, insert a TODO:

```markdown
## Goal

> **🔍 TODO(author):** The diff adds retry logic to the token refresher, but
> the motivation isn't clear from the code alone. Please add 1-2 sentences:
> What user-facing problem triggered this? Was there an incident?
>
> _Guidance: Think "why now?" -- link to a Jira ticket, Slack thread, or
> incident if applicable._
```

## Collapsed sections (use `<details>` blocks)

Everything below the Goal MUST be in `<details><summary>` blocks.

Use `<h2>` inside `<summary>` for visual consistency with the visible `## TL;DR`
and `## Goal` headers:

```html
<details>
<summary><h2>Section Title (context)</h2></summary>
...content...
</details>
```

### 3) Changes table (collapsed)

**Small-to-medium PRs** -- file-level table:

```markdown
<details>
<summary><h2>Changes (N files)</h2></summary>

| File | Change | Description |
|------|--------|-------------|
| `pkg/auth/token.go` | Modified | Add token refresh with exponential backoff |
| `pkg/auth/token_test.go` | Added | Unit tests for refresh logic |

</details>
```

**Large PRs (15+ files)** -- group by area:

```markdown
<details>
<summary><h2>Changes (32 files across 6 areas)</h2></summary>

| Area | Files | Change summary |
|------|-------|----------------|
| `pkg/auth/` | 4 modified, 2 added | Token refresh with backoff + tests |
| `cmd/server/` | 1 modified | Wire in new token refresher |

</details>
```

**Trivial changes** -- nested collapsed section inside the changes table,
file paths only, no description:

```markdown
<details>
<summary>Trivial changes (5 files)</summary>

- `pkg/util/constants.go`
- `Makefile`
- `internal/naming/rename.go`
- `cmd/server/main.go` (comment-only)
- `docs/changelog.md`

</details>
```

What counts as trivial:
- Comment additions/updates (no logic change)
- Import reordering or formatting
- Variable/function renames with no behavioral change
- Adding simple constants or small self-explanatory utilities
- Makefile/build config tweaks (unless they change build behavior)
- Typo fixes

If in doubt, put it in the main table with a description.

### 4) Detailed changes (collapsed)

```markdown
<details>
<summary><h2>Detailed changes</h2></summary>

### Theme 1 (e.g., "Auth workflow")
- Description of behavioral delta...

### Theme 2 (e.g., "Testing")
- Description of behavioral delta...

### Risks / rollout notes
- Workflow behavior changes, compatibility concerns, surprising deletions.

</details>
```

Organize by theme. Describe behavioral deltas, not code mechanics. Include
risks/rollout notes as the last subsection.

### 5) Test plan (collapsed)

Every PR should have a test plan. This is how the author proves due diligence.

```markdown
<details>
<summary><h2>Test plan</h2></summary>

**Unit tests**: `go test ./pkg/auth/...` -- 12 passed (see Verification below)

**Manual verification**: Deployed to staging, confirmed token refresh succeeds
after 401 response. Logs show backoff intervals of 1s, 2s, 4s.

**Edge cases considered**:
- Token expires mid-request -> retry with fresh token ✅
- Auth server unreachable -> fail after max retries ✅

</details>
```

If the agent can run side-effect-free tests, include results. If the agent
cannot determine how the change was tested, insert a TODO:

```markdown
<details>
<summary><h2>Test plan</h2></summary>

> **🔍 TODO(author):** Please describe how you verified this change works.
>
> _Guidance: Include specific commands you ran, test environments used, and
> edge cases you considered. For bug fixes, show evidence the bug is fixed.
> "It compiles" is not a test plan._

</details>
```

For refactors with no behavioral change, explicitly state so:

```markdown
**Test plan**: Pure structural refactoring -- no behavioral change. Verified
by running `go test ./...` and confirming all existing tests pass.
```

### 6) Verification & test results (collapsed)

```markdown
<details>
<summary><h2>Verification & test results</h2></summary>
(test output and commands here, using expandable command style)
</details>
```

Two parts: automated results (run by the agent) and manual commands (for the
reviewer).

## Expandable command style

All commands and output in PR summaries MUST use this format.

### Commands that WERE run (side-effect-free)

```markdown
<details>
<summary><code>pytest tests/test_token.py</code> ✅ 12 passed</summary>

```
$ pytest tests/test_token.py -v
tests/test_token.py::test_refresh_success PASSED
tests/test_token.py::test_refresh_backoff PASSED
========================= 12 passed in 0.45s ===========================
```

</details>
```

Summary line rules:
- Core command in `<code>` tags
- Abbreviate long arguments (`pytest tests/...`)
- Result indicator: ✅ pass, ❌ failure, ⚠️ warnings
- Brief count ("12 passed", "3 errors")

### Commands that were NOT run (side effects)

```markdown
<details>
<summary><code>kubectl apply -f deploy/manifest.yaml</code> (DID NOT RUN)</summary>

**What this does**: Applies the updated manifest to the cluster.
**Why not run**: Real changes against a live cluster.
**To verify manually**:
```bash
kubectl apply -f deploy/manifest.yaml --dry-run=client
kubectl apply -f deploy/manifest.yaml
```

</details>
```

### What to run vs. not run

| Safe to run | Do NOT run (DID NOT RUN) |
|-------------|--------------------------|
| Unit tests (`pytest`, `go test`) | `kubectl apply/delete/patch` on real clusters |
| Linters, formatters, type-checkers | Database migrations |
| `--dry-run` or `--check` flags | API calls that create/modify/delete resources |
| `go build`, `go vet`, `mypy` | Deployment or release commands |
| Reading cluster state (no write) | Anything that costs money |

## Best practices

1. **Reviewer empathy**: Write for zero-context readers. "Why" before "what".
2. **Diff-anchored claims**: Every claim traces to a diff hunk.
3. **No filler**: No "various improvements" or "minor refactoring".
4. **Highlight breaking changes**: CLI flags, env vars, config keys, API contracts
   -- call out in both TL;DR and Risks.
5. **Honest changes table**: Must match the actual diff.
6. **Test evidence builds trust**: Show output, don't just assert correctness.
7. **Net diff only**: Describe final state, not commit journey.
8. **Never mention unchanged areas**: If not in the diff, not in the summary.
9. **Consistent formatting**: Expandable command style throughout.
10. **Progressive disclosure**: Only TL;DR and Goal visible. Details collapsed.
11. **Link related context**: Parent issues, epics, prior PRs in Motivation.
12. **Keep it current**: Update after follow-up commits.
13. **TODO over guessing**: If you're not sure, add a TODO. A visible gap the
    author fills in is better than a confident-sounding wrong statement.
14. **Test plan is mandatory**: Every PR needs a test plan, even if it's just
    "ran existing tests, all pass." For refactors, state "no behavioral change."
15. **Searchable titles**: Titles should include scope and action so someone
    grepping commit history can find this PR.

## When to add TODOs vs. write confidently

| Agent confidence | Action |
|------------------|--------|
| **High** -- diff clearly shows the behavior | Write the section confidently |
| **Medium** -- can infer but not certain | Write best guess, mark with 🔍 and ask author to confirm |
| **Low** -- cannot determine from diff | Insert a TODO(author) with specific prompt |
| **Reviewer concern** -- spotted a potential issue | Insert a TODO(reviewer) question |

Examples of medium-confidence writing:

```markdown
## Goal

This PR appears to add retry logic to handle transient auth failures.
🔍 *TODO(author): Please confirm this motivation and add context (incident? user report?).*
```

The guiding principle: a reviewer reading the summary should immediately know
which parts are agent-verified from the diff and which parts need human input.
