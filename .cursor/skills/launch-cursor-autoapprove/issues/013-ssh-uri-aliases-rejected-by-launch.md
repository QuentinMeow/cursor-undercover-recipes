# Issue 013: SSH URI Aliases Rejected by `launch`

## Symptoms

Running `caa alias list` showed an alias pointing to an SSH folder URI:

```text
devapp-pinkube  vscode-remote://ssh-remote+devapp/home/qmiao/code/pinkube  (ssh)
```

But `caa launch devapp-pinkube` failed with:

```text
Workspace 'devapp-pinkube' is not a valid directory or alias.
```

The error listed the same alias as known, which made the launcher appear
self-contradictory.

## Root Cause

`_resolve_workspace_for_launch()` documented aliases as returning a local path
or SSH folder URI, but the implementation only accepted alias targets whose
values passed `Path(alias_target).is_dir()`. SSH folder URI aliases were found
in `config.json`, then rejected because they are not local filesystem paths.

## Fix

`_resolve_workspace_for_launch()` now preserves SSH folder URIs from direct
arguments or aliases. `cmd_launch()` detects those SSH workspaces, parses the
host and remote path, and dispatches through the existing `cmd_launch_ssh()`
flow so remote aliases get the same launch behavior and preflight checks as
explicit `caa launch-ssh <host> <path>`.

## Verification

1. A remote alias like `devapp-pinkube` resolves to its
   `vscode-remote://ssh-remote+...` target instead of being rejected as a
   missing local directory.
2. `caa launch <remote-alias>` follows the same SSH launch path as
   `caa launch-ssh <host> <absolute-remote-path>`.
3. `caa launch nonexistent` still errors and lists known aliases.

## Lessons Extracted

See `../LESSONS.md` — "Session State Hygiene" section.
