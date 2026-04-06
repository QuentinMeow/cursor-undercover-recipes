# Code Review Checklist

Systematic checklist for reviewing PRs. Work through each section against the
diff. Not every item applies to every PR -- skip sections that are irrelevant.

## 1. Functionality / Correctness

- Does the code do what the PR description says it does?
- Are edge cases handled (nil/null, empty collections, boundary values, zero)?
- Are error paths handled gracefully? Does the code fail safely?
- Is error propagation correct (not swallowing errors silently)?
- In concurrent code: thread-safety, race conditions, deadlock potential?
- Are resource lifetimes correct (open/close, acquire/release)?

## 2. Code Quality / Readability

- Are variable, function, and type names clear and descriptive?
- Is the code self-documenting? Would a reader understand it without comments?
- Is there unnecessary complexity, nesting, or indirection?
- Any magic numbers or hardcoded values that should be constants?
- Does it follow single-responsibility (one function = one job)?
- Any code duplication that should be extracted?
- Does it follow the language's conventions and the project's style guide?

## 3. Testing

- Are there tests for new functionality?
- Do tests cover edge cases and error scenarios?
- For bug fixes: is there a regression test that fails without the fix?
- Are tests clear and readable? (Test code quality = production code quality.)
- Are tests named after the behavior they verify?
- Any flaky test risk (timing, ordering, external dependencies)?
- Is test coverage adequate for the risk level of the change?

## 4. Performance

- Any obvious performance issues (N+1 queries, unnecessary allocations)?
- Inefficient loops or data structures?
- Unnecessary API calls, network requests, or database queries?
- For hot paths: is memoization or caching appropriate?
- Are there new goroutines/threads without bounded concurrency?

## 5. Security

- Input validation and sanitization present?
- Any injection risks (SQL, XSS, command injection)?
- Sensitive data handled correctly (no hardcoded secrets, no logging PII)?
- Authentication and authorization checks in place?
- Secrets kept server-side, not exposed in frontend code?

## 6. Design / Architecture

- Is the approach the simplest that works? (KISS / YAGNI)
- Are abstractions appropriate and not premature?
- Does the change fit the existing architecture, or does it introduce a new
  pattern that will confuse future readers?
- If this is a public API change: is it backward-compatible?
- If this is a config/flag change: are defaults safe?

## 7. Documentation / Observability

- Are non-obvious decisions documented in comments?
- Is the PR description accurate and complete?
- Are new metrics, logs, or alerts added where appropriate?
- For user-facing changes: is user documentation updated?

## 8. Rollout / Operational Safety

- Is there a rollback plan if this change causes issues?
- Are feature flags or gradual rollout mechanisms in place for risky changes?
- Does the change require coordinated deployment across services?
- Are there monitoring dashboards or alerts to detect regressions?

---

## Conventional Comments Reference

### Labels

| Label | When to use | Blocking? |
|-------|-------------|-----------|
| **praise:** | Highlight something genuinely well done. Include at least one per review. | No |
| **issue:** | A specific problem that needs fixing. Pair with a suggestion when possible. | Usually yes |
| **suggestion:** | An improvement idea. Explain what and why. | Varies |
| **question:** | You're not sure if something is a problem. Ask the author. | No |
| **nitpick:** | Trivial style/preference item. | No |
| **todo:** | Small, necessary task before merge (e.g., "add a test for this edge case"). | Yes |
| **thought:** | An idea sparked by the review. Non-blocking, but valuable. | No |
| **chore:** | Process task (e.g., "link the Jira ticket"). | Yes |
| **note:** | Something the reader should be aware of. | No |

### Decorations

Append in parentheses after the label to add context:

- `(blocking)` -- must be resolved before merge.
- `(non-blocking)` -- nice to have, can be a follow-up.
- `(security)` -- security-related concern.
- `(performance)` -- performance-related concern.

### Format

```
#<N> **<label> (<decoration>):** `<file>:<line>` -- <description>

<optional suggestion, code example, or question>
```

### Examples

```markdown
#1 **praise:** `pkg/auth/refresher.go:45` -- Clean use of exponential backoff
with jitter. The retry logic is easy to follow and well-tested.

#2 **issue (blocking):** `pkg/auth/refresher.go:82` -- `refreshToken` does not
check whether the token response body is nil before unmarshaling. This will
panic on HTTP 204 responses.

**suggestion:** Add a nil/empty body check:
    if resp.Body == nil || resp.ContentLength == 0 {
        return nil, errEmptyTokenResponse
    }

#3 **question:** `cmd/server/main.go:23` -- Is the 30-second timeout for token
refresh intentional? In high-latency environments this might be too short.

#4 **nitpick (non-blocking):** `pkg/auth/refresher.go:15` -- The import block
mixes standard library and third-party imports. Consider grouping them.

#5 **todo:** `pkg/auth/refresher_test.go` -- Missing test for the case where
the auth server returns HTTP 429 (rate limited). Please add before merge.
```

---

## Review Summary Template

After listing all findings, provide a summary:

```markdown
## Review Summary

**Overall**: [Approve / Approve with comments / Request changes]

**Critical issues** (must fix):
- #2 -- nil body panic in refreshToken

**Suggestions** (recommended):
- #3 -- review timeout value for high-latency environments

**Positive aspects**:
- #1 -- clean retry logic with jitter

**Remaining questions**:
- #3 -- timeout appropriateness
```

For local reviews (no PR), replace the overall line with:
"**Quality assessment**: [Good / Needs work before pushing / Significant concerns]"
