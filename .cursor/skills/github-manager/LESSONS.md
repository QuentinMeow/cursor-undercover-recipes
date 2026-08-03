# Lessons

## Identity Handling

- **SSH git auth and `gh` API auth are independent**: A push can use the right
  SSH key while `gh` still targets the wrong GitHub account, so identity-aware
  workflows must verify both channels before creating or editing PRs.
- **Restore the previous active `gh` login instead of assuming a fixed
  fallback**: Capturing the pre-existing account avoids clobbering other repos
  or sessions on machines that switch between personal and work identities.

## Staging Hygiene

- **Ignored files can still leak into a PR once tracked**: `.gitignore` does
  not remove files that were force-added or previously committed, so PR
  workflows must inspect staged paths and use `git rm --cached` to unwind
  accidental tracking instead of assuming ignore rules are enough.

## Worktree Safety

- **Local branch refs are shared, but indexes and files are per worktree**:
  moving `refs/heads/main` from a cleanup running elsewhere can make the main
  checkout appear to contain staged reverse changes. Refresh remote-tracking
  refs for comparison, snapshot the base OID, and update a local branch only
  through an explicit operation inside the worktree that has it checked out.
- **Inventory all worktrees before deleting a branch**: protecting only the
  invoking checkout is insufficient. Treat an unavailable or malformed
  worktree inventory as a reason to perform no cleanup.
