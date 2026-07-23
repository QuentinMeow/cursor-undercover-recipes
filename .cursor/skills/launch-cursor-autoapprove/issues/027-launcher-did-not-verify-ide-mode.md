---
id: 027
title: Launcher did not verify full IDE mode before injection
status: resolved
severity: high
root_cause: CDP target selection treated any workbench.html page as suitable, although Cursor can also open a standalone Agents window without the full IDE.
lesson_extracted: true
---

## Symptoms

- A dedicated Cursor process could open in Agents mode rather than the requested
  IDE workspace.
- Target binding and injection had no mode-level proof beyond a workbench URL or
  title.

## Direct evidence

Cursor 3.12.30 CLI help distinguishes:

- the normal path-based full IDE launch
- `--chat`, which opens a standalone chat window without the full IDE
- `--classic`, which disables glass mode and forces classic windows (dev-only)
- `--glass`, which enables the multi-workbench architecture

The old `_is_workbench()` check matched both because both use Cursor's
workbench renderer.

## Resolution

- Centralize launch arguments in `_cursor_ide_launch_args()`, require a local
  workspace or SSH folder URI, pass `--classic --new-window`, and never include
  `--chat` or `--glass`.
- Before launch, require Cursor CLI help to advertise the version-coupled
  `--classic` flag; fail closed if it disappears.
- Probe each CDP target for `workbench.desktop.main.css/js`. Treat
  `workbench.glass.main.css/js` as Agents mode; generic workbench parts remain
  secondary diagnostics only.
- Bind, rebind, inject, enable, and cycle only against a verified IDE surface.
- Report `Mode: IDE (verified)` in status.
- If a new process exposes only an Agents/incomplete surface, close it and
  remove the session instead of enabling the gate.

## Lesson

A workbench URL and generic workbench parts prove renderer type, not product
mode. Launch automation must force classic mode and verify the mode-specific
loaded bundle before mutation.
