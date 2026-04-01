---
id: 001
title: Running dedicated window keeps stale injector after reinstall
status: resolved
severity: medium
root_cause: The launcher reused any already-injected DOM script without checking whether the on-disk injector had changed.
resolved_at: 2026-04-01
lesson_extracted: true
---

## Symptoms

After reinstalling `launch-cursor-autoapprove` while a dedicated Cursor window
was already running, `on` resumed the existing in-window injector instead of
refreshing it. New fixes on disk were not picked up until the user manually
cleared and re-injected the script.

## Root Cause

`launcher.py on` only checked whether `acceptStatus()` existed. If the window
already had any injector loaded, the launcher treated that as good enough.
There was no version handshake between:

- the on-disk `devtools_auto_accept.js`
- the already-running script inside the Cursor renderer

## Fix

- Added a short content hash for the injected script.
- Stored that hash in the in-window injector state.
- Updated `on` to compare the running hash with the current on-disk hash.
- Reloaded the injector when the hashes differ.
- Exposed the hash through `status` so users can verify which injector version a
  running window is using.

## Lesson

Long-lived injected scripts need an explicit version handshake. A launcher
should not assume "script exists" means "script is current."
