# Issue 005: Ghost Sessions, Auth Re-login, and Workspace Resolution

## Symptoms

1. **Ghost sessions from bare names**: Running `caa launch gocmp` from `~`
   created a session keyed to `/Users/qmiao/gocmp` (non-existent), while the
   real project at `/Users/qmiao/code/gocmp` already had a session. This
   doubled the session count (6 entries instead of 3).

2. **Wrong workspace opened**: Cursor received the non-existent path and
   opened a blank/wrong window (e.g., treating the path as a file name
   instead of a project directory).

3. **Stale sessions accumulate**: Sessions whose Cursor processes had exited
   remained in `state.json` indefinitely. Only explicit `caa stop` removed
   them.

4. **Re-login required for every new workspace**: Each dedicated profile's
   `state.vscdb` lacked auth tokens, forcing the user to log into Cursor
   again for every new workspace launch.

## Root Causes

- `cmd_launch` resolved workspace via `Path(arg).resolve()` without checking
  that the result exists as a directory.
- No automatic garbage collection of dead-PID sessions.
- `_sync_user_settings` only copied `settings.json` and `keybindings.json`,
  not the `cursorAuth/*` keys from `state.vscdb`.

## Fixes

1. **Workspace resolution**: Added `_resolve_workspace_for_launch()` which
   validates the path exists, then falls back to slug matching against
   existing sessions and searching well-known parent directories
   (`~/code`, `~/src`, `~/projects`, `~/dev`, `~/repos`).

2. **Session GC**: Added `_gc_stale_sessions()` called from every
   `_load_state()`. Prunes entries whose PIDs are dead OR whose workspace
   path does not exist as a directory. For non-existent workspace paths
   where the PID is still alive, the orphaned Cursor process is terminated
   first.

3. **Auth sync**: Added `_sync_auth_tokens()` called from
   `_sync_user_settings()`. Copies `cursorAuth/*` rows from the default
   Cursor profile's `state.vscdb` into the dedicated profile.

## Verification

1. `caa launch gocmp` from any directory should resolve to `~/code/gocmp`
   (or whichever well-known parent contains it).
2. `caa launch nonexistent` should error with a helpful message listing
   known slugs.
3. `caa status` should only show running sessions (dead entries auto-pruned).
4. First launch of a new workspace should not require re-login.

## Lessons Extracted

See `../LESSONS.md` — "Session State Hygiene" section.
