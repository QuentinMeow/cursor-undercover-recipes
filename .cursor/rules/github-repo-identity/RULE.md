---
description: Switch gh to the repo's personal identity before GitHub CLI work
alwaysApply: true
---

# GitHub Identity

This repository pushes over a personal SSH remote, but `gh` may still be
pointed at a different `github.com` account.

Before any `gh` command in this repo:

1. Run:
   `python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" enter --target-user QuentinMeow`
2. If the helper reports that `QuentinMeow` is not logged into `gh`, stop and
   ask the user to complete a one-time `gh auth login` inside Cursor. Do not
   continue with the wrong account.
3. After the GitHub work is done, run the matching `leave` command to restore
   the previously active `gh` account:
   `python3 "$(git rev-parse --show-toplevel)/.cursor/skills/github-manager/scripts/gh_identity.py" leave`

Use `status` when debugging identity state. This workflow is only for `gh` API
identity; do not change `git config` as part of it.
