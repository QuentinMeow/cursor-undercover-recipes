# PR Workflows

## Right Diff First

Every PR workflow starts by resolving the real base branch from GitHub. Never
assume `main` or `master`.

### Metadata

```bash
gh pr view <PR> --json baseRefName,headRefName,changedFiles,additions,deletions,title,number
```

### File list

```bash
gh api repos/<owner>/<repo>/pulls/<PR>/files --paginate --jq '.[].filename'
```

Cross-check the file count against `changedFiles` before moving on.

### Diff content

Preferred:

```bash
gh pr diff <PR>
```

Remote-tracking equivalent:

```bash
git fetch origin <baseRefName> <headRefName>
git diff origin/<baseRefName>...origin/<headRefName>
```

Use the three-dot merge-base diff. Avoid stale local branches and avoid the
working tree as a substitute for PR content.

### Per-file counts

```bash
gh api repos/<owner>/<repo>/pulls/<PR>/files --paginate \
  -q '.[] | "\(.filename)\t+\(.additions)\t-\(.deletions)"'
```

Only publish numbers that come from GitHub or the actual diff.

## Review Feedback

Read all three comment surfaces:

```bash
gh api repos/<owner>/<repo>/issues/<PR>/comments --jq '.[].body'
gh api repos/<owner>/<repo>/pulls/<PR>/comments --jq '.[].body'
gh api repos/<owner>/<repo>/pulls/<PR>/reviews --jq '.[] | select(.body != "") | .body'
```

Bots, inline comments, and review summaries often land in different endpoints.

## Safe PR Body Updates

Back up the existing body before overwriting it:

```bash
gh pr view <PR> --json body --jq '.body' > /tmp/pr-body-before.md
gh api repos/<owner>/<repo>/pulls/<PR> -X PATCH -F "body=@/tmp/pr-body-after.md"
```

Prefer file-based uploads over shell heredocs for multi-line PR bodies.

## Splitting And Cleanup

- Split by logical concern first, then use line counts as a sanity check.
- Keep review PRs self-contained when possible.
- If stacked or dependent PRs exist, update links and merge strategy notes in
  every affected PR body.
- After merge, clean up local branches, worktrees, and stale remote-tracking
  refs only after checking whether any branch still contains local-only commits.
