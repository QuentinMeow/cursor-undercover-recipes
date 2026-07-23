---
id: 026
title: Registered mounted Allow cards lost direct-scanner backup
status: resolved
severity: critical
root_cause: Enabling cycle recovery permanently marked every registered task-row approval as cycle-owned, so the ordinary mounted-composer scanner could never click its visible Allow button.
lesson_extracted: true
---

## Symptoms

- A parent transcript visibly showed a subagent `Allow | Stop` card.
- The parent-level Allow button sometimes remained pending.
- Progress depended on navigating into the individual subagent editor and
  clicking its approval there.

## Direct evidence

The direct scanner evaluated every candidate with
`_isCycleOwnedSubagentCandidate()`. For any registered task row, that function
returned true whenever cycling was enabled, even while no cycle attempt owned
the row. The eligible direct-scanner list then excluded the candidate.

After the fix, a live Cursor 3.12.30 harness subagent ran one harmless Python
command. The mounted parent card advanced without child navigation, and status
recorded a direct `allow` click with `reason: companion` plus the exact
task-scoped `allow|stop` fingerprint. Final-hash validation also reported
`DirectCaps: 1 registered prompt(s)`, proving the direct retry cap was recorded.

## Resolution

- Replace permanent task-row ownership with a short lease for the exact task
  currently being attempted by registered-row recovery.
- Bound the mounted direct path to one attempt per task-scoped prompt
  fingerprint, so it remains a backup without bypassing failed cycle retry
  state forever.
- Keep exclusive ownership for tray and pinned navigation from mount through
  verified restoration.
- Use the same task-scoped prompt fingerprint in direct and registered-row
  paths, so either path cools the other for eight seconds.
- Release the registered-row lease in `finally`, including failures and user
  takeover.

The visible parent button is again the fast path. Registered-row and child
navigation recovery remain independent backups without concurrent duplicate
clicks.

## Lesson

Redundant recovery mechanisms should share dedupe state, cap each path, and
lease ownership only during an active attempt. Permanent ownership silently
disables the supposed fast path; an uncapped backup bypasses retry safety.
