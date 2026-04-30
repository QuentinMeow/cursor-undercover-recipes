# Issue 004: CDP Targets Wrong Workbench in Multi-Window Scenarios

## Symptom

When two or more workbench pages exist within a single dedicated Cursor
process (e.g., an extra manual window opened inside the same process),
`_cdp_evaluate` would non-deterministically pick "the first workbench
target that succeeds." This caused:

- `caa status` reporting Gate ON while the visible window showed paused
- `caa on`/`off` toggling the wrong page
- Window title being set on an unrelated window (e.g., a manually opened
  `other-repo` workspace getting the `autoapprove ✅ demo-repo` title)
- Click count stuck at 0 because the injector was running on a different
  renderer than the one the user interacted with

## Root Cause

`_cdp_evaluate()` was port-scoped: it enumerated `/json` targets on every
call and picked the first workbench page. When multiple workbench pages
existed on the same port, any command could land on the wrong page.

## Fix

**Stable CDP target binding** — at launch time, the launcher selects one
workbench target, stores its `id` in `state.json` as `cdp_target_id`,
and all subsequent CDP calls (`on`, `off`, `status`, `stop`) address
only that specific target. If the bound target disappears, operations
fail closed with a clear warning instead of silently retargeting another
page.

## Verification

1. Launch two dedicated sessions (`caa launch` for two repos)
2. Manually open a third window inside one of the dedicated processes
3. Run `caa status` — should show a WARNING about multiple workbench
   targets on that port and report the bound target ID
4. Run `caa on -w <slug>` — should only affect the bound target
5. Confirm the manually opened window title is NOT overwritten

## Lessons Extracted

See `../LESSONS.md` — "CDP Target Binding" section.
