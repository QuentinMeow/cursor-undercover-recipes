# Review Checklist

Use this when reviewing PRs locally or before posting GitHub comments.

## Correctness

- Does the diff do what the PR claims?
- Are edge cases and failure paths handled safely?
- If auth or identity changed, is the target account verified rather than
  assumed?

## Design

- Is this the simplest design that satisfies the goal?
- Is the patch a durable direction or a local hack?
- Would a step-back review recommend a cleaner boundary or smaller surface?

## Testing

- Do tests cover the behavior that matters, not just the implementation shape?
- For bug fixes, is there a regression test or equivalent proof?
- Could the current tests pass while the user-visible behavior is still wrong?

## Security And Safety

- Are secrets, tokens, or account identifiers kept out of the diff?
- Does any automation fail closed on ambiguous state?
- Are destructive or irreversible operations guarded or user-approved?

## Operations

- Is there a rollback or recovery story if the change misbehaves?
- Are logs, status output, or diagnostics strong enough to debug failures?

## Review Labels

Use concise labels when summarizing findings:

- `issue:` for correctness or safety problems
- `suggestion:` for improvements
- `question:` when intent is unclear
- `todo:` for missing verification before merge
- `praise:` for something notably strong
