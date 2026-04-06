# GitHub PR workflows (comprehensive reference)

This document is the **stacked-PR and deep PR-operations** layer of
[`github-manager`](../SKILL.md). It incorporates the full workflow from an
internal `github-pr-manager` skill (company-oriented) and is maintained here
as a **personal superset**: same procedures, plus repo-local `gh` identity
switching and paths suited to this workspace.

**Read first** in the parent skill: Quick Start (identity), then return here
for Section 1 and scenarios A–E.

---

# GitHub PR Manager (reference body)

Five workflow scenarios, all built on the same foundation: getting the right
diff. Every scenario begins with Section 1.

| Scenario | When to use |
|----------|-------------|
| **A** | Write/update a PR summary, or review a PR |
| **B** | Split a large PR into stacked PRs |
| **C** | Address peer review feedback on any PR in a stack |
| **D** | Merge PRs (AIO-merge or stacked-merge strategy) |
| **E** | Post-merge cleanup |

### Quick start (most common use case)

**To write or refresh a single PR summary**: Prerequisites → Section 1 →
Scenario A. Ignore B–E unless you are splitting or merging stacked PRs.

**To split, review, and merge a large PR**: Prerequisites → Section 1 →
Scenario B (split) → Scenario C (address feedback) → Scenario D (merge) →
Scenario E (cleanup).

---

## Prerequisites & Setup

> **READ THIS FIRST if you are new to this workflow.** These tools must be
> installed and configured before using any scenario. Existing users can skip
> to Section 1.

### Required tools

| Tool | Purpose | Install | Verify |
|------|---------|---------|--------|
| **GitHub CLI (`gh`)** | PR operations, API calls, auth | See setup below | `gh auth status` |
| **Aviator CLI (`av`)** | Stacked PR management (Scenarios B–E only) | `brew install aviator-co/tap/av` | `av --version` |
| **Git** | Version control | Pre-installed on macOS/Linux | `git --version` |

### GitHub CLI setup (detailed)

The `gh` CLI is the backbone of this workflow. It handles authentication,
API calls, PR creation, and more.

#### Standard setup (human in a regular terminal)

```bash
# 1. Install
brew install gh                          # macOS
# or: sudo apt install gh               # Debian/Ubuntu
# or: winget install GitHub.cli         # Windows

# 2. Authenticate
gh auth login
#   → Choose: GitHub.com (for orgs hosted on github.com, e.g. github.com/pinternal)
#     OR your GitHub Enterprise Server hostname (e.g. github.mycompany.com)
#   → Choose: HTTPS (recommended) or SSH
#   → Authenticate via browser (recommended) or paste a token

# 3. For org repos that use SSO: authorize your token for the org
#    After gh auth login, go to: GitHub → Settings → Developer settings →
#    Personal access tokens → click "Configure SSO" next to your token
#    → Authorize for your org. Or use:
gh auth refresh -h github.com -s read:org

# 4. Verify
gh auth status
# Should show: ✓ Logged in to github.com as <username>

# 5. Set default repo (avoids specifying -R on every command)
gh repo set-default <owner>/<repo>

# 6. Find your repo's owner/name (useful for filling in <OWNER>/<REPO>)
gh repo view --json nameWithOwner -q .nameWithOwner

# 7. Find your repo's default branch (never assume master or main)
gh repo view --json defaultBranchRef -q .defaultBranchRef.name
```

#### Cursor IDE setup

Cursor's integrated terminal has its own shell environment and may not
inherit SSH agent sessions or credentials from your system terminal. You
must set up `gh` auth **inside Cursor's terminal** for `gh` API calls and
git push to work from agent sessions.

```bash
# 1. Open Cursor's integrated terminal (Ctrl+` or Cmd+`)

# 2. Run gh auth login — this is interactive, the agent cannot do it for you
gh auth login
#   → GitHub.com
#   → SSH (required if your repo uses SSH certificate auth)
#   → Upload your SSH public key (e.g. ~/.ssh/id_ed25519.pub)
#   → Login with a web browser
#   → Copy the one-time code shown, press Enter, complete in browser

# 3. After browser auth completes, verify in Cursor's terminal:
gh auth status
gh auth setup-git    # configures git to use gh as credential helper

# 4. Test that git push works:
git push --dry-run 2>&1 | head -5
```

> **Why this is needed**: Cursor spawns agent shell sessions from its own
> terminal environment. If `gh auth login` was only done in a system
> terminal (e.g., iTerm, Terminal.app), Cursor's shells may not see those
> credentials. Running `gh auth login` once inside Cursor's terminal
> persists the auth for all future agent sessions in that workspace.

#### SSH certificate auth (org-managed repos)

Some organizations require **SSH certificate authentication** instead of
standard personal SSH keys. The git remote URL may use an org-scoped SSH
user, and neither plain SSH keys nor HTTPS tokens may work for `git push`.

You must sign and install SSH certificates using **your employer's or org's
documented tooling** (names and commands vary) **before** pushing.
Certificates often expire after a short TTL, so you re-sign on a schedule
your IT team defines.

```bash
# Example shape only — replace with your org's actual commands:
# <org-cert-tool> login
# <org-cert-tool> sign   # or equivalent for GitHub access
# <org-cert-tool> install

# Verify: agent should show certificates + private keys
ssh-add -l

# Test push
git push --dry-run 2>&1 | head -5
```

> **Important**: `gh auth login` alone is **not sufficient** for SSH
> certificate repos. You need both: `gh auth login` (for `gh` API calls)
> AND a valid SSH certificate (for `git push`/`git fetch`). If `gh api`
> works but `git push` fails with `Permission denied (publickey)`, your
> SSH certificate has likely expired — re-run your cert signing script.

**Common issues:**

| Problem | Fix |
|---------|-----|
| `gh auth login` shows wrong hostname | Run `gh auth login --hostname github.com` (or your GHE hostname) |
| Authenticated but can't access org repos | Authorize SSO: GitHub Settings → Developer settings → Tokens → Configure SSO |
| `Permission denied (publickey)` on git push | Run `gh auth login` in Cursor terminal with SSH protocol; or `gh auth setup-git` |
| TLS/cert error in Cursor/agent sandboxes | Agent: use `--required_permissions ["all"]`; Human: check `SSL_CERT_FILE` or proxy settings |
| `gh pr edit` fails with "Projects Classic" error | Use REST API instead: `gh api repos/.../pulls/<PR> -X PATCH -F "body=@file.md"` |
| Rate limit exceeded | Check: `gh api rate_limit --jq '.resources.core.remaining'` |
| `gh` commands return 404 or wrong repo | Set default: `gh repo set-default <owner>/<repo>` or use `-R <owner>/<repo>` |
| SSH cert expired (org-managed certs) | Re-sign using your org's SSH cert workflow (see internal docs). |
| `gh api` works but `git push` fails | Two separate auth mechanisms: `gh` uses token, `git push` uses SSH cert — renew the cert |

### Aviator CLI setup

[Aviator](https://docs.aviator.co/aviator-cli) is a tool that manages
stacked PR branches, handles rebasing across the stack, and automates
PR creation with correct base branches.

```bash
# 1. Install
brew install aviator-co/tap/av          # macOS (Homebrew)
# Non-brew: see https://docs.aviator.co/aviator-cli for other install methods

# 2. Initialize in your repo (once per clone)
cd <your-repo>
av init
# This creates metadata in .git/av/ — safe and non-destructive

# 3. Verify
av --version
av stack tree    # should show current branch

# Recovery: if av state is corrupted, re-run `av init` or re-clone
```

### Repository setup checklist

- [ ] `gh auth status` shows authenticated (with SSO authorized if needed)
- [ ] `av init` completed in the repo root
- [ ] PR-body scratch dir exists and is gitignored (see **Local Backup** in this doc — personal default under `.cursor/skills/github-manager/logs/`, or `.agent-files/pr` in some org repos)
- [ ] You know your repo's default branch: `gh repo view --json defaultBranchRef -q .defaultBranchRef.name`
- [ ] You know your repo's merge strategy: check repo Settings → General → Pull Requests (squash-merge, merge queue, etc.)

---

## Terminology

| Term | Meaning |
|------|---------|
| **All-In-One (AIO) PR** | A single branch/PR containing **all** changes. The primary integration-test and CI target. Depending on the merge strategy, this is either the merge target (AIO-merge) or a reference-only PR (stacked-merge). |
| **Stacked PRs** | The decomposed series of small PRs created from the AIO. Each targets the previous stacked PR's branch (or `master` for the first). Used for focused code review. |
| **AIO-merge strategy** | Review on stacked PRs, merge via the AIO PR. **Default and recommended.** Best when all changes ship together. |
| **Stacked-merge strategy** | Review and merge each stacked PR individually, bottom-up. Best when features release independently. |

### Why two merge strategies?

Many repositories enforce **blocking reviews on the latest commit**. This
creates a problem for stacked PRs:

- When you merge the bottom stacked PR, it changes the base of the next PR,
  which invalidates the existing review approval (because the HEAD commit
  changed via rebase).
- This means you need re-approval on every stacked PR after each merge in the
  stack -- a painful serial process.

**AIO-merge** solves this: reviewers leave feedback on the small stacked PRs
(easy to understand), but the single AIO PR is what actually gets approved and
merged. One approval, one merge, all changes land together.

**Stacked-merge** is appropriate when you genuinely want to land features
incrementally (e.g., PR1 ships to production and is validated before PR2
lands).

### Choosing a strategy

| Signal | Strategy |
|--------|----------|
| All changes ship together as one release | **AIO-merge** (default) |
| Repo has blocking review on latest commit | **AIO-merge** (avoids re-approval churn) |
| Features can be released independently | **Stacked-merge** |
| Each PR needs separate rollout/monitoring | **Stacked-merge** |
| Team prefers single merge commit in history | **AIO-merge** |

When in doubt, use **AIO-merge**.

---

## ⛔ SECTION 1: How to Get PR Content — READ THIS FIRST ⛔

> **THIS IS THE SINGLE MOST IMPORTANT PART OF THIS SKILL.**
>
> Getting the wrong diff is the **#1 source of wrong PR summaries, bad line
> counts, incorrect split decisions, and embarrassing factual errors.** Every
> past mistake traces back to: diffing against the wrong base branch, using
> stale local branches, reading partial diffs, or computing line counts from
> filenames instead of the actual diff.
>
> **You MUST follow these steps exactly, every time, with zero shortcuts.**
> If you skip this section, everything downstream will be wrong.

### Step 0 — Get the actual base branch (ALWAYS DO THIS FIRST)

```bash
gh pr view <PR> --json baseRefName,headRefName,changedFiles,additions,deletions,title,number
```

> **CRITICAL**: NEVER assume the base is `master` or `main`. PRs frequently
> target other branches (e.g., a stacked PR targets the previous stacked PR's
> branch). Diffing against the wrong base produces a completely wrong change
> set. If `gh` fails with a TLS/cert error in a sandbox, re-run with
> `--required_permissions ["all"]`.

Store `baseRefName` and `headRefName`. Use them in **every** command below.

### Step 1 — Get the exact file list (source of truth)

```bash
gh api repos/<owner>/<repo>/pulls/<PR>/files --paginate --jq '.[].filename'
```

Or: `gh pr diff <PR> --name-only`

Count files: pipe to `| wc -l`.

**GATE**: If the file count does NOT match `changedFiles` from Step 0, **STOP**
and re-fetch. Do not proceed with a mismatched file list.

### Step 2 — Get the actual diff content

Preferred (exact GitHub diff):

```bash
gh pr diff <PR>
```

Local equivalent (remote-tracking refs, never stale local branches):

```bash
git fetch origin <baseRefName> <headRefName>
git diff origin/<baseRefName>...origin/<headRefName>
```

**Correct**: `origin/<baseRefName>...origin/<headRefName>` (3-dot merge-base
diff, matches GitHub)

> **⛔ NEVER do any of these:**
> - `origin/master..HEAD` or `git diff origin/master` — unless you confirmed
>   `master` IS the base in Step 0
> - `<baseRefName>...HEAD` with a local branch name — local branches may be
>   stale
> - `git log origin/master..HEAD` for commit history — use the correct base
> - Read files on disk and assume they represent the PR diff — the working tree
>   may have uncommitted changes or be on a different branch
> - Compute line counts from filenames, commit messages, or partial diffs

**Verify**: `git diff origin/<baseRefName>...origin/<headRefName> --stat |
tail -1` must match the `additions`/`deletions` from Step 0.

### Step 3 — Get per-file line counts (MANDATORY for any summary with numbers)

> **⛔ NEVER fabricate or estimate line counts.** Every number in a PR summary
> must come from this API call. If numbers don't add up, re-run this step.

```bash
gh api repos/<owner>/<repo>/pulls/<PR>/files --paginate \
  -q '.[] | "\(.filename)\t+\(.additions)\t-\(.deletions)"'
```

Cross-check: the per-file additions/deletions MUST sum to the PR-level totals
from Step 0. If they don't, paginate or re-fetch.

Classify each file:

| Category | Pattern | Counts toward review threshold? |
|----------|---------|--------------------------------|
| LOGIC | `.go`, `.py`, `.ts` (not test) | Yes |
| TEST | `*_test.go`, `test_*.py`, `/tests/`, `/testdata/` | No (but tracked) |
| CONFIG | `.yaml`, `.toml`, `go.mod`, `go.sum`, `Makefile` | No (but tracked) |
| DOC | `.md`, `.html`, `docs/` | No |
| AUTOGEN | `.pb.go`, `swagger`, `docs.go` | No |

### Step 4 — Get commit history scoped to the PR

```bash
git log --format='%h %ad %s' --date=short origin/<baseRefName>..origin/<headRefName>
```

### Step 5 — Read and analyze the full diff (MANDATORY before any action)

> You MUST read and understand the full diff before writing any summary or
> making any splitting decision. Never act based on filenames, commit messages,
> or partial diffs alone.

For large PRs, read in priority order:

```bash
gh api repos/<owner>/<repo>/pulls/<PR>/files --paginate \
  -q 'sort_by(.additions) | reverse | .[:20] | .[] | "\(.additions)\t\(.deletions)\t\(.filename)"'
```

Then skim remaining file patches for surprises (deletes, moves, contract
changes).

Build a "behavioral change checklist" from the diff:
- New/changed CLI flags (`pflag.*Var(`, `--<flag>`)
- New/changed env vars (`os.Getenv("...")`)
- New/changed config keys (`yaml:"..."`, `*.yaml` additions)
- Contracts/invariants ("must", "required", "fail fast", "reject")

### Step 6 — Get PR comments and review feedback

GitHub stores comments in three separate locations. You must check all three
to get the complete picture.

```bash
# Issue comments (conversation thread — bot comments, general discussion)
gh api repos/<OWNER>/<REPO>/issues/<PR>/comments \
  --jq '.[] | "\(.user.login) (\(.created_at)):\n\(.body)\n---"'

# Review comments (line-level annotations on specific code)
gh api repos/<OWNER>/<REPO>/pulls/<PR>/comments \
  --jq '.[] | "\(.user.login) on \(.path):\(.line):\n\(.body)\n---"'

# PR reviews (approve/request-changes with body text)
gh api repos/<OWNER>/<REPO>/pulls/<PR>/reviews \
  --jq '.[] | "\(.user.login) (\(.state)):\n\(.body)\n---"'
```

| API endpoint | What it returns | Typical content |
|-------------|-----------------|-----------------|
| `issues/<PR>/comments` | Conversation-thread comments | Automated review bots, general discussion |
| `pulls/<PR>/comments` | Line-level review annotations | Inline code feedback from reviewers |
| `pulls/<PR>/reviews` | Review actions with body | Approve/request-changes with summary text |

> **For Scenario C**: Always check ALL three endpoints to ensure you don't miss
> feedback. Automated review bots typically post to the issues comments
> endpoint, while human reviewers use the review/line-comment endpoints.

### Quick-reference command block

```bash
# === Copy this block and fill in <PR>, <OWNER>, <REPO> ===
# Step 0: base branch (MUST DO FIRST)
gh pr view <PR> --json baseRefName,headRefName,changedFiles,additions,deletions,title,number

# Step 1: file list
gh api repos/<OWNER>/<REPO>/pulls/<PR>/files --paginate --jq '.[].filename'

# Step 2: diff
gh pr diff <PR>

# Step 3: per-file line counts (MANDATORY for numbers)
gh api repos/<OWNER>/<REPO>/pulls/<PR>/files --paginate \
  -q '.[] | "\(.filename)\t+\(.additions)\t-\(.deletions)"'

# Step 4: commits
git log --format='%h %ad %s' --date=short origin/<baseRefName>..origin/<headRefName>

# Step 6: comments (all three types)
gh api repos/<OWNER>/<REPO>/issues/<PR>/comments --jq '.[].body'
gh api repos/<OWNER>/<REPO>/pulls/<PR>/comments --jq '.[].body'
gh api repos/<OWNER>/<REPO>/pulls/<PR>/reviews --jq '.[] | select(.body != "") | .body'
```

---

## 2. GitHub API Limits & Responsible Usage

> **WHY THIS MATTERS**: GitHub rate-limits REST API calls to 5,000/hour for
> authenticated users and GraphQL to 5,000 points/hour. Brute-force approaches
> (e.g., fetching every file individually, polling in tight loops) will hit
> limits and break workflows for the entire team.

### REST API

| Limit | Value |
|-------|-------|
| Authenticated requests | 5,000 / hour |
| Unauthenticated | 60 / hour |
| Secondary rate limit | ~100 requests/minute for content-creating endpoints |

**Best practices**:
- Use `--paginate` with `gh api` to batch file lists (100 per page).
- Prefer `gh pr diff <PR>` (single request) over fetching individual file
  patches.
- Cache results: if you already fetched a PR's diff, don't re-fetch unless
  the branch was updated.
- For stacks of N PRs, budget ~5 API calls per PR (metadata + files + diff).
  A 5-PR stack costs ~25 calls, well within limits.

### GraphQL API

| Limit | Value |
|-------|-------|
| Points per hour | 5,000 |
| Typical query cost | 1-10 points |
| Max query complexity | 500,000 nodes |

**Best practices**:
- Avoid GraphQL for diff content — use REST (`gh pr diff`) instead.
- Use GraphQL only when you need cross-entity queries (e.g., "list all PRs
  with their review status in one call").
- Check remaining budget: `gh api rate_limit --jq '.resources.graphql'`.

### Practical guidance for agents

- **Never loop over files individually** to fetch their content. Use
  `gh pr diff` to get the entire diff in one call.
- **Never poll PR status in a tight loop.** Use webhooks or one-shot checks.
- **Batch operations**: When updating multiple PRs (e.g., writing summaries
  for each stacked PR), add a 1-second delay between API writes to avoid
  secondary rate limits.
- **Check remaining quota** before starting a large operation:
  ```bash
  gh api rate_limit --jq '.resources.core.remaining'
  ```

---

## 3. Local Backup & File Naming

> Every PR summary or analysis MUST be backed up locally before uploading to
> GitHub. This protects against accidental overwrites and provides an audit
> trail.

### Local file path

**Personal / this repo (preferred):** use a gitignored path under the skill:

```
.cursor/skills/github-manager/logs/<YYYYMMDD-HHMM-TZ>-pr-<ID>-<branch-slug>.md
```

**Enterprise / some org clones:** teams sometimes standardize on:

```
.agent-files/pr/<YYYY-MM-DD>-PR-<ID>-<branch-name>.md
```

(with `.agent-files/` in `.gitignore`). Use whichever your repo already
documents; **never** commit draft PR bodies.

- Slashes in the branch name become dashes in the filename.
- If no PR yet, use `PR-temp` as the ID.
- One file per branch. Rename (update date) on subsequent updates.

### Lifecycle

1. **First draft (no PR)**: create with `PR-temp-<branch>.md`
2. **PR created**: rename to `PR-<ID>-<branch>.md`
3. **Updates**: rename old file to today's date, overwrite content

### Before overwriting an existing PR body

Always save the old body first:

```bash
# Adjust the path to match your chosen backup dir (see above).
gh pr view <PR> --json body --jq '.body' > .cursor/skills/github-manager/logs/old-<date>-PR-<ID>-<branch>.md
```

Then write the new summary, then upload:

```bash
gh api repos/<owner>/<repo>/pulls/<PR> -X PATCH \
  -F "body=@/path/to/your/local-summary.md"
```

> **⛔ ALWAYS use file-based upload (`-F "body=@file.md"`) for PR bodies.**
> NEVER use shell heredoc (`cat <<'EOF'`) to pass PR bodies to `gh pr create`
> or `gh api`. Heredoc delimiters (e.g., `EOF`, `PREOF`) frequently leak into
> the PR body as visible text, producing broken formatting on GitHub. Write
> the body to a local file first, then use `@file` syntax.

Use the REST API (not `gh pr edit`) to avoid the Projects Classic deprecation
error.

---

## Scenario A: Update PR Summary or Review a PR

This is the most common workflow. Use when asked to write, update, or review
a PR description. Works for **any** PR type: standalone, AIO, or stacked.

### A.1 — Retrieve PR content

Follow **Section 1 exactly** (Steps 0–6). No shortcuts. No local diffs
against assumed base branches. No guessing.

### A.2 — Analyze the diff

- Identify the top 3-7 meaningful behavioral changes.
- Group by intent/theme, not by folder.
- Inspect content diffs, not filenames.
- Build the behavioral change checklist from Step 5.

### A.3 — Write the summary

Follow the output format in [pr-summary-format.md](pr-summary-format.md).

**For standalone PRs and stacked PRs**: Write a standard summary focused on
that PR's diff.

**For AIO PRs**: Write a full summary of all combined changes PLUS the
stacked PR navigation table (see A.3a below).

**For stacked PRs that are part of a stack**: Write a full summary of that
PR's changes PLUS a stack context header (see A.3b below).

Key rules:
- **Net diff only**: Describe the final state, not the commit journey.
- **Diff-only scope**: NEVER mention files not changed in this PR.
- **Diff-anchored claims**: Every claim traces to a diff hunk.
- **No filler**: No "various improvements" or "minor refactoring."
- **Honest uncertainty**: Use TODO markers (see format reference) when unsure.

#### A.3a — AIO PR summary format

The AIO PR body must contain:

1. **Full summary** of all combined changes (TL;DR, Goal, Changes, Details,
   Test plan — the complete treatment, not a stub).
2. **Merge strategy indicator** at the top.
3. **Stacked PR navigation table** linking to each stacked PR.
4. **Section order requirement**: `TL;DR` first, then an expanded-by-default
   "Stacked PRs for review" block (`<details open>`), then `Goal`.

```markdown
> **Merge strategy**: AIO-merge — review on stacked PRs, merge this PR.

## TL;DR
(full summary of all combined behavioral changes)

<details open>
<summary><h2>Stacked PRs for review</h2></summary>

| # | PR | Title | Files | +/- | Description |
|---|-----|-------|-------|-----|-------------|
| 1 | #XXXX | [Title](url) | N | +A/-D | One-line summary |
| 2 | #YYYY | [Title](url) | N | +A/-D | One-line summary |

**Review order**: Start with #XXXX, then #YYYY.
**Merge**: Approve and merge this AIO PR after all stacked PRs are reviewed.

</details>

## Goal
(full motivation section)

(remaining collapsed sections: Changes, Detailed changes, Test plan, etc.)
```

#### A.3b — Stacked PR summary format

Each stacked PR body must contain:

1. **Stack context header** at the top (adapts to merge strategy).
2. **Full summary** of this PR's own changes (not a stub — a complete
   description that a reviewer can understand without reading other PRs).

**For AIO-merge** (review here, merge via AIO):

```markdown
> **Stack context**: PR N of M in the [<area> stack](link-to-aio-pr).
> AIO PR: #XXXX | Previous: #<prev-pr> | Next: #<next-pr>
>
> **Merge strategy**: AIO-merge — review here, merge via AIO PR #XXXX.

## TL;DR
(full summary of THIS PR's behavioral changes)

## Goal
(full motivation for THIS PR's changes)

(remaining sections: Changes, Detailed changes, Test plan, etc.)
```

**For stacked-merge** (review and merge each PR independently):

```markdown
> **Stack context**: PR N of M in the [<area> stack](link-to-aio-pr).
> AIO PR: #XXXX (reference only) | Previous: #<prev-pr> | Next: #<next-pr>
>
> **Merge strategy**: Stacked-merge — approve and merge this PR after #<prev-pr>.

## TL;DR
(full summary of THIS PR's behavioral changes)

## Goal
(full motivation for THIS PR's changes)

(remaining sections: Changes, Detailed changes, Test plan, etc.)
```

### A.4 — Fact-check all numbers

> **⛔ MANDATORY**: Every line count, file count, and percentage in the summary
> MUST match the GitHub API data from Step 0 and Step 3. Cross-check before
> writing.

Common mistakes to avoid:
- Adding logic + test lines and calling it "total" when GitHub reports
  additions/deletions separately.
- Mixing up additions vs. total changes (additions + deletions).
- Rounding numbers without marking them as approximate (~).

### A.5 — Evaluate the PR title

Format: `[area] descriptive summary of the change`

For AIO PRs: `[area] AIO: descriptive summary`

Update only if vague, missing area tag, or inaccurate:

```bash
gh api repos/<owner>/<repo>/pulls/<PR> -X PATCH \
  -f title='[area] summary' --jq '.title'
```

### A.6 — Write to both locations

1. **Local backup**: under `.cursor/skills/github-manager/logs/` (or your org's `.agent-files/pr/` convention)
2. **GitHub PR body**: Upload via REST API (see Section 3)

> If the PR already has a description, read it first and preserve sections
> the author wants to keep. Merge, don't blindly overwrite.

### A.7 — For code reviews (additional steps)

If reviewing (not just summarizing):

1. Read the PR description and commit messages for intent context.
2. Perform systematic review using
   [code-review-checklist.md](code-review-checklist.md).
3. Write findings using Conventional Comments labels.
4. Provide a summary with overall assessment.
5. Offer to post comments to the PR.

---

## Scenario B: Split a Large PR into Stacked PRs

Use when the user asks to split, stack, or decompose a PR for easier review.

> **KEY CONCEPT**: Splitting means **decomposing** a large body of work into a
> series of smaller, dependent PRs that are each easy to review. It does NOT
> mean adding a single small PR on top of a large one.
>
> The workflow always produces two artifacts:
> 1. **All-In-One (AIO) PR** — contains all changes. Depending on the merge
>    strategy, this is either the merge target or a reference.
> 2. **Stacked PRs** — the reviewable pieces. Each must compile/test
>    independently when applied on top of its parent in the stack.

### B.1 — Consolidate into an AIO branch (if needed)

Skip if there is already a single branch with all changes.

```bash
# Determine the default branch (never hardcode master/main)
DEFAULT_BRANCH=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name)

git fetch origin $DEFAULT_BRANCH
git checkout origin/$DEFAULT_BRANCH
git checkout -b <username>/<short-desc>-aio
git merge --no-ff origin/<branch1>
git merge --no-ff origin/<branch2>       # repeat for each branch
git push -u origin HEAD
gh pr create --base $DEFAULT_BRANCH \
  --title "[area] AIO: <desc>" \
  --body "Integration-test PR. See stacked PRs for review."
```

### B.2 — Determine the merge strategy

Ask the user (or infer from context):

| Question | If yes → |
|----------|----------|
| Do all changes need to ship together? | AIO-merge |
| Does the repo require blocking review on latest commit? | AIO-merge |
| Should features land independently? | Stacked-merge |

Default: **AIO-merge**.

Record the chosen strategy — it affects PR descriptions (A.3a/A.3b) and
merge workflow (Scenario D).

### B.3 — Review and update the AIO PR summary

Before splitting, ensure the AIO PR has an accurate narrative summary.

1. Run **Scenario A** (Section 1 → A.6) against the AIO PR.
2. Write the TL;DR, Goal, Changes, and Test plan sections (the full
   narrative). The stacked PR navigation table (A.3a) will be added in
   B.8 after the stacked PRs are created.

### B.4 — Classify and count lines

Use the analysis script from
[analysis-commands.md](analysis-commands.md) or the per-file API
data from Step 3 of Section 1.

**Threshold**: If logic + test + config lines ≤ 300, no split needed.

### B.5 — Design the split

Work through in order:

1. **Identify independent concerns** from the diff. Each becomes a candidate
   stacked PR. Dependencies determine ordering (foundations first).
2. **Tests and config**: If >100 lines, split into the next stacked PR after
   their logic PR. If small, keep with logic.
3. **Refactoring**: If file extraction would make the split cleaner, make it
   the first PR (pure structural, no behavioral change).
4. **Confidence check**: If unsure about a split requiring code changes,
   **pause and discuss** — present options and tradeoffs to the user (or
   team) before executing any branch operations.

Present the split plan and get user confirmation:

```
| # | Branch name           | Category     | Est. lines | Depends on |
|---|-----------------------|--------------|------------|------------|
| 1 | stack/refactor-utils  | Refactoring  | ~80        | None       |
| 2 | stack/core-logic      | Logic        | ~200       | #1         |
| 3 | stack/tests-and-config| Tests+Config | ~150       | #2         |
```

See [splitting-strategy.md](splitting-strategy.md) for detailed
decision framework.

### B.6 — Execute with Aviator CLI

```bash
DEFAULT_BRANCH=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name)
git checkout origin/$DEFAULT_BRANCH
av branch "stack/<username>-pr1-<short-desc>"
git checkout origin/<aio-branch> -- path/to/files...
git add -A && git commit -m "<PR1 message>"
av pr

av branch "stack/<username>-pr2-<short-desc>"
git checkout origin/<aio-branch> -- path/to/more-files...
git add -A && git commit -m "<PR2 message>"
av pr
```

**Key**: Always cherry-pick from `origin/<aio-branch>`, never from local
branches.

### B.7 — Set up bidirectional references

> **⛔ MANDATORY.** Every stacked PR and the AIO PR must reference each other
> so anyone can navigate the full picture. This is critical for both merge
> strategies.

Update each PR body using the formats from A.3a (AIO) and A.3b (stacked).

### B.8 — Write summaries for all PRs

1. **Stacked PR summaries**: Run **Scenario A** against each stacked PR
   (in parallel if sub-agents are available, sequentially otherwise). Each
   summary must be derived from that PR's own diff (not copied from the AIO).
   Use A.3b format with the correct merge strategy variant.

2. **Update AIO PR summary**: Now that stacked PRs exist with PR numbers,
   add the stacked PR navigation table (A.3a format) to the AIO PR body.
   Include accurate per-PR file counts and line counts from the API.

Add a 1-second delay between GitHub API write operations to avoid secondary
rate limits (see Section 2).

### B.9 — Verify the stack

```bash
av stack tree
```

---

## Scenario C: Address Peer Review Feedback

Use when a reviewer has left comments on any PR in the stack and the user
wants to address them.

### C.1 — Identify the PR's position in the stack

Determine whether the PR is:
- **A stacked PR** (part of a decomposed stack)
- **The AIO PR** (merge target in AIO-merge strategy)
- **A standalone PR** (no stack)

If it's part of a stack, read the AIO PR and ALL stacked PRs first to
understand the full picture. Use the bidirectional references from B.7.

### C.2 — Fetch all comments

Use **Step 6** from Section 1 to retrieve ALL comments across all three
endpoints (issue comments, review comments, reviews). Check every PR in the
stack, not just the one with the notification.

```bash
# For each PR in the stack:
gh api repos/<OWNER>/<REPO>/issues/<PR>/comments \
  --jq '.[] | "\(.user.login) (\(.created_at)):\n\(.body)\n---"'
gh api repos/<OWNER>/<REPO>/pulls/<PR>/comments \
  --jq '.[] | "\(.user.login) on \(.path):\(.line):\n\(.body)\n---"'
gh api repos/<OWNER>/<REPO>/pulls/<PR>/reviews \
  --jq '.[] | "\(.user.login) (\(.state)):\n\(.body)\n---"'
```

### C.3 — Evaluate the feedback

For each comment:
1. Read the comment and understand what the reviewer is asking.
2. Check the referenced code in the diff (not on disk — the working tree may
   not match the PR branch). Use `gh pr diff <PR>` to get the authoritative
   diff.
3. Validate: does the feedback make sense? Is there a real issue?
4. Classify as: **must-fix** (blocking), **should-fix** (non-blocking
   improvement), **won't-fix** (misunderstanding or deliberate design choice).
5. For won't-fix items, prepare a reasoned response explaining why.
6. For must-fix/should-fix items, proceed to C.4.

### C.4 — Make the code fix

**For stacked-merge strategy**: Fix the code in the affected stacked PR's
branch:

```bash
git checkout <stacked-pr-branch>
# make the fix
git add -A && git commit -m "address review: <brief description>"
```

**For AIO-merge strategy**: Fix the code in the AIO branch directly (since
that's what gets merged). Then update ALL affected stacked PR branches so
their review diffs stay accurate:

```bash
# 1. Fix on the AIO branch
git checkout <aio-branch>
# make the fix
git add -A && git commit -m "address review: <brief description>"
git push origin <aio-branch>

# 2. Identify which stacked PRs are affected
#    Check which stacked PRs touch the same files as the fix:
git diff HEAD~1 --name-only    # files changed by the fix

# 3. Update each affected stacked PR branch (bottom-up order)
#    For each affected branch, sync the fixed files from AIO:
git checkout <stacked-pr-branch>
git fetch origin <aio-branch>
git checkout origin/<aio-branch> -- <affected-files>
git add -A && git commit -m "sync fix from AIO: <brief description>"

# 4. After updating all affected branches, sync the stack:
av sync --all --push yes
```

> **Note on AIO approval invalidation**: Pushing to the AIO branch changes
> HEAD, which may invalidate existing approvals if the repo enforces "blocking
> review on latest commit." Plan for re-approval after fixes.

### C.5 — Sync the stack

After fixing, propagate changes through the stack:

```bash
av sync --all --push yes
```

This rebases all descendant branches and pushes them.

### C.6 — Run unit tests

Run the project's test suite to verify nothing is broken:

```bash
go test ./...                             # or project-specific test command
```

For AIO-merge, run tests on the AIO branch (the merge target).
For stacked-merge, run tests on each affected branch.

### C.7 — Update with latest trunk

If the stack is behind the default branch:

```bash
av sync --rebase-to-trunk
av sync --all --push yes
```

If merge conflicts arise, resolve in the affected branch, then re-sync.

### C.8 — Update all PR summaries

After code changes, PR summaries may be stale. Launch sub-agents to run
**Scenario A** against each affected stacked PR to refresh summaries. Also
update the AIO PR's stacked-PR table if line counts changed.

### C.9 — Respond to the reviewer

Post a reply on the PR comment thread explaining what was changed and where.
If the fix cascaded to other PRs in the stack, note which ones were affected.
For won't-fix items, explain the reasoning clearly.

---

## Scenario D: Merge PRs

Use when all reviews are complete and the PR(s) are ready to merge. The
workflow differs based on the merge strategy.

### D.0 — Detect merge queue and repo settings

```bash
# Determine the default branch (never hardcode master/main)
DEFAULT_BRANCH=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name)

# Check if the repo uses a merge queue or branch protection
gh api repos/<OWNER>/<REPO>/branches/$DEFAULT_BRANCH/protection \
  --jq '.required_status_checks' 2>/dev/null

# Check allowed merge methods
gh repo view --json squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed
```

Some repos protect their default branch with a **merge queue**. This changes
the safe merge command.

- If the target branch requires a merge queue, use `gh pr merge <PR>
  --match-head-commit <head-sha>` with **no** `--merge`, `--rebase`, or
  `--squash` flag. Let GitHub queue the PR using the repo's configured policy.
- If no merge queue, pass the flag matching the repo's allowed method
  (e.g., `--squash` if only squash-merge is allowed).
- Wait for the actual `mergedAt` event before considering a PR merged. "Added
  to merge queue" is not the same as merged.

### D.1 — AIO-merge strategy (default)

This is the recommended approach. Reviews happen on stacked PRs; the AIO PR
is what gets approved and merged.

#### Pre-merge checklist

- [ ] All stacked PRs have been reviewed (feedback addressed via Scenario C)
- [ ] AIO PR has passing CI
- [ ] AIO PR is up to date with the default branch
- [ ] AIO PR summary is current and includes stacked PR table
- [ ] Line counts in summaries match current state

#### Merge the AIO PR

```bash
# Get the current HEAD SHA
gh pr view <AIO-PR> --json headRefOid --jq '.headRefOid'

# If merge queue is enabled (D.0): omit method flags, let the queue decide
gh pr merge <AIO-PR> --match-head-commit <head-sha>

# If NO merge queue: pass the method flag matching repo settings
# Check allowed methods: gh repo view --json squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed
gh pr merge <AIO-PR> --squash --match-head-commit <head-sha>    # if squash allowed
# or: gh pr merge <AIO-PR> --merge --match-head-commit <head-sha>
```

If the repo uses squash-merge, this produces a single clean commit on the
default branch containing all the changes.

#### Close the stacked PRs

After the AIO PR merges, the stacked PRs' changes are already in master.
Close them (do NOT merge — that would create duplicate commits):

```bash
# Close each stacked PR with a comment
for pr in <PR1> <PR2> <PR3>; do
  gh pr close $pr --comment "Changes merged via AIO PR #<AIO-PR>. Closing stacked review PR."
  sleep 1
done
```

#### Clean up branches

```bash
# Delete remote stacked branches
for branch in stack/<username>-pr1-<desc> stack/<username>-pr2-<desc>; do
  gh api repos/<owner>/<repo>/git/refs/heads/$branch -X DELETE 2>/dev/null
  sleep 1
done

# Delete local branches
git branch -D stack/<username>-pr1-<desc> stack/<username>-pr2-<desc>

# The AIO branch is deleted automatically by GitHub on merge
# Clean up local tracking ref
git branch -D <aio-branch> 2>/dev/null
git remote prune origin 2>/dev/null
```

### D.2 — Stacked-merge strategy

Use when features should land independently.

#### Pre-merge checklist

- [ ] All stacked PRs have passing CI
- [ ] All stacked PRs are approved by reviewers
- [ ] All review feedback has been addressed (Scenario C)
- [ ] The AIO branch is up to date with the default branch
- [ ] Line counts in AIO PR body match current state

#### Merge in dependency order (bottom-up)

```bash
# Merge the bottom PR first
gh pr view <bottom-PR> --json headRefOid --jq '.headRefOid'
gh pr merge <bottom-PR> --match-head-commit <head-sha>

# IMPORTANT:
# - Do NOT add --delete-branch for intermediate PRs until the child
#   PR has been retargeted away from that branch
# - Do NOT force --squash/--merge/--rebase when the base branch uses a merge queue
```

After the bottom PR merges:

```bash
av sync --all --push yes    # rebase remaining stack onto new master
```

Repeat for each PR in order.

**Re-approval issue**: After rebasing, the HEAD commit changes and blocking
reviews may be invalidated. The reviewer must re-approve each subsequent PR.
This is the key downside of stacked-merge — consider AIO-merge to avoid this.

#### Handle retargeting issues

If the next PR was **not** retargeted automatically, retarget or repair it
before continuing. If a branch was deleted too early and GitHub auto-closed a
child PR, recover immediately:

```bash
# Restore the deleted branch from the PR's recorded head SHA
gh pr view <closed-parent-PR> --json headRefName,headRefOid
gh api repos/<owner>/<repo>/git/refs -X POST \
  -f ref=refs/heads/<restored-branch> \
  -f sha=<head-sha>

# Reopen the affected PRs
gh pr reopen <parent-PR>
gh pr reopen <child-PR>
```

#### Verify each merge

After each PR merges, verify:
1. CI passes on the next PR (which was retargeted)
2. The diff shown on the next PR still looks correct (no extra commits leaked
   in from the merge)

#### Close the AIO PR

After **all** stacked PRs have merged, the AIO PR's changes are already in
master. Do NOT merge the AIO PR:

```bash
gh pr close <AIO-PR> --comment "All stacked PRs merged. Closing AIO reference PR."
```

#### Clean up branches

```bash
git branch -D <aio-branch>                          # delete local
gh api repos/<owner>/<repo>/git/refs/heads/<aio-branch> -X DELETE 2>/dev/null
```

Aviator should have already deleted the stacked PR branches on merge.

---

## Scenario E: Post-Merge Cleanup

Use after any merge (AIO-merge or stacked-merge) to ensure a clean state.

### E.1 — Delete local branches

```bash
# List all branches related to the stack (REVIEW before deleting)
git branch | grep -E '<pattern>'

# Verify these are the correct branches before deleting
# Delete them
git branch -D <branch1> <branch2> ...
```

> **Safety**: Always list and review branch names before deleting. Derive
> branch names from `gh pr view <PR> --json headRefName` rather than typing
> manually.

### E.2 — Clean up worktrees

If Aviator or manual operations created worktrees:

```bash
git worktree list
git worktree remove <path> --force    # for each stale worktree
```

### E.3 — Prune stale remote tracking refs

```bash
# Preferred (requires SSH/HTTPS access to remote)
git remote prune origin

# Fallback (if SSH is broken, manually remove stale refs)
git update-ref -d refs/remotes/origin/<stale-branch>
```

### E.4 — Drop stale stashes

If you stashed changes before switching branches:

```bash
git stash list
git stash drop stash@{N}    # for each stale stash
```

### E.5 — Verify clean state

```bash
git branch | grep -E 'stack/|<feature-pattern>'    # should return nothing
git worktree list                                    # should show only main worktree
git status                                           # should be clean
```

---

## Critical Rules

### Diff retrieval (the foundation)

- **NEVER** assume the base branch. Always detect via `gh pr view`.
- **NEVER** diff against `origin/master` without confirming master is the base.
- **NEVER** use local branch names in diffs (they may be stale).
- **NEVER** use `git diff` against the working tree as a substitute for
  `gh pr diff`. The working tree may not match the PR.
- **ALWAYS** verify file count and line counts match GitHub's numbers.
- **ALWAYS** use `gh api .../pulls/<PR>/files` for per-file line counts.

### Summaries and numbers

- **NEVER** write a summary based on filenames or commit messages alone.
- **NEVER** fabricate or estimate line counts. Every number comes from the API.
- **NEVER** mention files or modules not changed in the PR.
- **ALWAYS** read the full diff before writing anything.
- **ALWAYS** cross-check: per-file additions must sum to PR total additions.

### Stacked PRs and merge strategies

- **ALWAYS** maintain bidirectional references between AIO and stacked PRs.
- **ALWAYS** include full summaries on BOTH AIO and stacked PRs (not stubs).
- **ALWAYS** present the split plan and get user confirmation before creating branches.
- **NEVER** create a "stacked PR" by adding a small PR on top of a large one.
  Splitting means decomposing into multiple small PRs.
- **ALWAYS** record and follow the chosen merge strategy (AIO-merge or stacked-merge).
- **For AIO-merge**: Merge the AIO PR, then close (not merge) stacked PRs.
- **For stacked-merge**: Merge bottom-up, then close (not merge) the AIO PR.

### API usage

- **NEVER** loop over files individually to fetch content. Use `gh pr diff`.
- **NEVER** use shell heredoc (`cat <<'EOF'`) to pass PR bodies to any `gh`
  command. Heredoc delimiters leak into the PR text. Always write to a file
  first and use `-F "body=@file.md"`.
- **ALWAYS** add 1-second delays between sequential API write operations.
- **ALWAYS** check rate limit before large batch operations.

---

## Troubleshooting & Recovery

### CI failure triage

| Situation | Action |
|-----------|--------|
| AIO CI green, stacked PR CI red | Check if the stacked PR job is path-filtered or flaky. If AIO-merge, stacked CI is informational — merge AIO if tests pass there. If stacked-merge, fix the stacked PR before merging. |
| AIO CI red, stacked PRs green | The integration has a problem the parts don't. Investigate on the AIO branch; fix there and sync to stacked PRs (Scenario C). |
| Flaky test | Re-run: `gh run rerun <run-id> --failed`. If persistent, investigate. |

### Merge conflict during `av sync`

```bash
# av sync stops mid-rebase with conflicts
# 1. Check which branch has the conflict
git status

# 2. Resolve conflicts in the affected files
# edit files...
git add <resolved-files>
git rebase --continue

# 3. If stuck, abort and retry
git rebase --abort
# Then manually fix the source branch and re-sync

# 4. After resolving, continue syncing
av sync --all --push yes

# 5. Verify clean state
av stack tree
```

If conflicts persist across multiple retries, consider rebuilding stacked
branches from the AIO as a fresh split.

### Accidental merge of a stacked PR under AIO-merge

If someone merges a stacked PR when the strategy was AIO-merge:

1. **Check what landed**: `gh pr view <merged-PR> --json mergedAt,headRefOid`
2. **If commits reached trunk**: Close remaining stacked PRs with a comment
   explaining the situation. Update the AIO PR to exclude already-merged
   changes, or close it if all changes landed.
3. **If partial landing**: The AIO branch may now conflict with trunk.
   Rebase the AIO: `git fetch origin && git rebase origin/<default-branch>`.
   Resolve conflicts and force-push (with user confirmation).
4. **Prevent recurrence**: Mark stacked PRs as Draft on GitHub, or add
   "DO NOT MERGE — review only" to their titles.

### Modifying an existing stack

**Adding a new PR to the stack:**

```bash
# Insert between existing PRs (e.g., new PR between #2 and #3)
git checkout <pr2-branch>
av branch "stack/<username>-pr2.5-<desc>"
git checkout origin/<aio-branch> -- <new-files>
git add -A && git commit -m "<message>"
av pr
av sync --all --push yes
# Update all bidirectional references (A.3a table + A.3b headers)
```

**Removing a PR from the stack:**

Close the PR with a comment. Cherry-pick its commits into an adjacent PR
or back into the AIO. Run `av sync --all --push yes` and update all
bidirectional references.

**Re-ordering the stack:**

Re-ordering is high-risk. Preferred approach: rebuild branches from the AIO
with the new order (fresh `av branch` + cherry-pick sequence). Close old PRs
and create new ones. Always get user confirmation before re-ordering.

### `av` state corrupted or not initialized

```bash
# Re-initialize (safe, non-destructive)
av init

# If still broken: check .git/av/ metadata
# Last resort: abandon av for this stack, manage branches manually
# Reconstruct stack info from GitHub PR bases:
for pr in <PR1> <PR2> <PR3>; do
  gh pr view $pr --json number,baseRefName,headRefName \
    --jq '"\(.number): \(.headRefName) → \(.baseRefName)"'
done
```

### Resuming a stack workflow mid-session

When picking up a stack started in a previous session:

1. Read the AIO PR body for merge strategy and stacked PR table
2. Run `av stack tree` to see current branch state
3. List open PRs: `gh pr list --author <username> --state open --json number,title,headRefName`
4. Check for unaddressed review comments (Section 1, Step 6)
5. Verify all branches are in sync: `av sync --all --push yes`

### CODEOWNERS considerations

If the repo has a `CODEOWNERS` file:

- Before splitting, check which paths require specific reviewers:
  `cat CODEOWNERS` or `gh api repos/<OWNER>/<REPO>/contents/CODEOWNERS`
- Ensure each stacked PR's changed files trigger the correct owner
  assignments, OR note that only the AIO PR needs owner approval
  (depending on repo policy)
- Check review assignments: `gh pr view <PR> --json reviewRequests`

---

## Merge Strategy Quick Reference

```
┌─────────────────────────────────────────────────────────┐
│                   AIO-MERGE (default)                   │
│                                                         │
│  1. Split AIO → stacked PRs (Scenario B)                │
│  2. Reviewers review each stacked PR                    │
│  3. Author addresses feedback (Scenario C)              │
│  4. Approve + merge the AIO PR                          │
│  5. Close all stacked PRs                               │
│  6. Clean up (Scenario E)                               │
│                                                         │
│  ✅ One approval, one merge, no re-approval churn       │
│  ✅ Clean single commit on master (if squash-merge)     │
│  ❌ All-or-nothing: can't land features incrementally   │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                    STACKED-MERGE                        │
│                                                         │
│  1. Split AIO → stacked PRs (Scenario B)                │
│  2. Reviewers review + approve bottom PR first          │
│  3. Merge bottom PR, rebase stack (av sync)             │
│  4. Re-approve next PR (HEAD changed), merge, repeat    │
│  5. Close the AIO PR after all stacked PRs merge        │
│  6. Clean up (Scenario E)                               │
│                                                         │
│  ✅ Features land independently                         │
│  ✅ Can validate each feature in production              │
│  ❌ Re-approval needed after each rebase                │
│  ❌ Slower: serial approval + merge cycle               │
└─────────────────────────────────────────────────────────┘
```

---

## Relationship to Other Docs

This reference is the **deep workflow guide** for stacked PR management and
pairs with the repo's [`github-manager`](../SKILL.md) entrypoint (identity +
routing).

| Doc | Purpose | Precedence |
|-----|---------|------------|
| [`github-manager` / `SKILL.md`](../SKILL.md) | `gh` identity switching, quick start, links into this file | Entry point |
| This file (`pr-workflows-comprehensive.md`) | Section 1, scenarios A–E, merge strategies | Primary for stacked/AIO work |
| [pr-summary-format.md](pr-summary-format.md) | Section templates and formatting | Supplementary to A.3 |

If another repo defines a separate Cursor rule for standalone PR summaries,
use it for simple one-off descriptions; for stacked or AIO PRs, follow A.3a/A.3b
in this reference.

---

## Additional Resources

### Internal references

- [pr-summary-format.md](pr-summary-format.md) — PR summary output
  format, section templates, expandable command style, TODO markers
- [code-review-checklist.md](code-review-checklist.md) — Systematic
  review checklist and Conventional Comments reference
- [splitting-strategy.md](splitting-strategy.md) — Decision
  framework for how to split
- [analysis-commands.md](analysis-commands.md) — Reusable commands
  for PR analysis
- [reviewer-best-practices.md](reviewer-best-practices.md) —
  Research-backed reviewer tips

### External references

- [GitHub CLI docs](https://cli.github.com/manual/) — `gh` command reference
- [Aviator CLI docs](https://docs.aviator.co/aviator-cli) — `av` stacked PR management
- [GitHub: About merge queues](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)
- [GitHub: Dismissing stale reviews](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches#dismiss-stale-pull-request-approvals-when-new-commits-are-pushed)
