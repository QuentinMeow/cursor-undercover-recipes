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
