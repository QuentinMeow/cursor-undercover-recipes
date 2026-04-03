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

Cross-check the file count against `changedFiles` before moving on. If the
counts disagree, stop and re-fetch before publishing anything.

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

If you need a second check on totals, compare the remote-tracking diff stats
against GitHub's metadata:

```bash
git diff origin/<baseRefName>...origin/<headRefName> --stat
```

If the additions, deletions, or changed-file totals do not line up, stop and
re-fetch before writing a summary.

### Commit scope

```bash
git log --format='%h %ad %s' --date=short origin/<baseRefName>..origin/<headRefName>
```

Use the PR-scoped commit range for narrative context, not `origin/main..HEAD`
or another assumed default branch.

### Per-file counts

```bash
gh api repos/<owner>/<repo>/pulls/<PR>/files --paginate \
  -q '.[] | "\(.filename)\t+\(.additions)\t-\(.deletions)"'
```

Only publish numbers that come from GitHub or the actual diff.

## Staging And Artifact Hygiene

Before committing or opening a PR, inspect what will actually ship:

```bash
git status --short
git diff --cached --name-only
git diff --cached
```

Keep local-only artifacts out of the diff unless the user explicitly asks for
those exact paths:

- `.agents/worklog/*.md` (keep `.gitkeep` committed)
- `.cursor/MEMORY.md`
- `.cursor/skills/**/logs/**`
- scratch outputs such as PR-body backups or ad hoc analysis dumps

`.gitignore` does not untrack files that were force-added or committed earlier.
If one of these paths is already tracked, remove it from the index with
`git rm --cached <path>` instead of assuming ignore rules are enough.

Do not use `git add -f` on ignored agent artifacts unless the user explicitly
asks for that exact file to be versioned.

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
RUN_ID="$(date +%Y%m%d-%H%M-%Z)-pr-body"
SCRATCH_DIR=".cursor/skills/github-manager/logs/$RUN_ID"
mkdir -p "$SCRATCH_DIR"
gh pr view <PR> --json body --jq '.body' > "$SCRATCH_DIR/pr-body-before.md"
gh api repos/<owner>/<repo>/pulls/<PR> -X PATCH -F "body=@$SCRATCH_DIR/pr-body-after.md"
```

Use `/tmp` instead if you do not want repo-local scratch, but keep the backup
out of the diff either way.

Prefer file-based uploads over shell heredocs for multi-line PR bodies.

## Splitting And Cleanup

- Split by logical concern first, then use line counts as a sanity check.
- Keep review PRs self-contained when possible.
- If stacked or dependent PRs exist, update links and merge strategy notes in
  every affected PR body.
- After merge, clean up local branches, worktrees, and stale remote-tracking
  refs only after checking whether any branch still contains local-only commits.
