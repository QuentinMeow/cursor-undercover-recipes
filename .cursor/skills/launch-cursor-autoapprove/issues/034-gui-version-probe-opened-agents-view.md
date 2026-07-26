---
id: 034
title: GUI version probe opened an unverified Agents view
status: resolved
severity: high
root_cause: An agent invoked Cursor's macOS GUI executable with --version, assuming it would print and exit. The process stayed running and opened Cursor's default Agents surface outside the launcher's --classic and CDP verification path.
lesson_extracted: true
---

## Symptoms

- A new Agents view opened while diagnosing a live auto-approve session.
- The window was not launched through `caa launch` and therefore was not a
  verified dedicated IDE session.

## Direct evidence

`/Applications/Cursor.app/Contents/MacOS/Cursor --version` did not exit after
30 seconds on Cursor 3.13.10. Its process logs showed normal application
startup. Reading `CFBundleShortVersionString` from the app bundle returned the
version without starting another Cursor process.

## Resolution

- Require every Cursor workspace launch in `SKILL.md` to use `caa launch` or
  `caa launch-ssh`.
- Explicitly forbid direct GUI-executable invocation, including version probes.
- Use macOS app bundle metadata for version diagnostics.
- Continue requiring `Mode: IDE (verified)` before a launch is reported as
  successful.

## Lesson

Command-line-looking flags do not make an Electron GUI executable a safe
metadata probe. Keep diagnostics side-effect free and route every real launch
through the same mode-forcing and verification boundary.
