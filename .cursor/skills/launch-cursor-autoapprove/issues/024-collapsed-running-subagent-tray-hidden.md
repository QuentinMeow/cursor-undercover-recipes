---
id: 024
title: Collapsed running-subagent tray hid blocked children
status: resolved
severity: critical
root_cause: Tray recovery discovered only mounted child rows, but Cursor unmounted those rows whenever the exact `N subagents running` header was collapsed.
lesson_extracted: true
---

## Symptoms

- The parent showed a collapsed `2 subagents running` header.
- A child remained on a real shell `Run` approval while the gate and cycle were
  both ON.
- Status reported one waiting task but `Tray: 0 running`.
- Automatic cycles repeatedly reported `trayTaskCount: 0`.
- Manually expanding the tray made the existing child-editor recovery approve
  the command immediately.

## Direct evidence

Live capture on Cursor 3.12.17 found:

- the exact `.composer-toolbar-section-header-label` remained mounted with
  `2 subagents running`
- the collapsed chevron used `transform: rotate(0deg)`
- the section contained zero
  `.composer-toolbar-background-job-item-clickable` rows while collapsed
- clicking the exact header rotated the chevron to 90 degrees and mounted two
  child rows
- the next existing tray visit selected `Draft Grafana and NBCUniversal`,
  clicked its real `Run` control, and recorded
  `tray_approval_confirmed`
- after the fix, status distinguishes `2 advertised`, `0 mounted`, and
  `1/1 collapsed`, and automatic recovery approved three consecutive real
  child commands from the initially collapsed tray

The matching policy and selected-child scope were already correct. Discovery
failed one level earlier because it treated mounted rows as proof that the tray
existed.

## Resolution

- Discover exact visible running-subagent headers independently of mounted
  child rows.
- Record advertised, raw-mounted, eligible, collapsed, and unknown state in
  status telemetry.
- Expand a collapsed exact header with an 800 ms bound and fail closed when
  header identity or expansion state is ambiguous. Require the advertised rows
  to mount, back off repeated expansion misses, and exhaust after five failures
  for an unchanged parent/count identity.
- Re-resolve each child by unique normalized title immediately before visiting
  it because selecting one child remounts and collapses the parent tray.
- Advance round-robin state only by unique-title rows actually processed and
  give tray and registered-row recovery separate budgets.
- Restore the original parent editor between child visits, then restore the
  tray's original expansion state only when its captured parent resource still
  matches and newer user interaction has not taken over.
- Emit `tray_expand`, `tray_expand_miss`, and `tray_restore` evidence.

## Lesson

Collapsible navigation headers and their child rows have separate lifecycles.
Treat the exact header as the durable index, materialize its rows within a
bounded scope, and re-resolve row identity after every navigation remount.
