---
id: 028
title: Exhausted tray children were remounted until the heap safety trip
status: resolved
severity: critical
root_cause: The two-attempt click cap marked prompt fingerprints failed, but tray discovery still navigated to those children before consulting the terminal retry record; each repeated failure also selected the scheduler's two-second retry delay.
lesson_extracted: true
---

## Symptoms

- A dedicated window stopped with visible pending approvals.
- Status showed the gate OFF after a `js_heap_limit` safety trip.
- Tray visit counts grew rapidly even though click attempts and confirmations
  no longer changed.
- Each cycle expanded the collapsed running tray, opened the same children,
  immediately returned retry-exhausted, restored the parent, and repeated.

## Direct evidence

Live investigation of `jobs-finder-combined` on Cursor 3.12.30 found:

- the safety circuit tripped at 807,793,856 bytes against the former
  805,306,368-byte threshold
- four tray prompt fingerprints had exactly two attempts and `failed: true`
- the last 40 seconds before the trip contained about 52 child remounts
- every final cycle reported four tray visits and four tray failures with no
  possible click
- status showed 763 cumulative tray visits
- the visible parent `Run` remained eligible and uncooldowned; it was pending
  only because the safety trip had latched the gate OFF

Cursor itself can retain substantial transcript memory, so the remount loop is
a demonstrated churn amplifier rather than proof of the only allocator.

## Resolution

- Persist title, selected resource identity, exhaustion time, and next probe
  time with navigated approval retry records.
- Filter deferred pinned/tray entries before navigation.
- After two unconfirmed clicks, defer the exact prompt for one minute and use
  exponential probes capped at 15 minutes.
- Report exhausted probes as `deferred`, not as fresh cycle failures.
- When all remaining navigation is deferred, schedule the cycle at the earliest
  probe deadline instead of the normal or two-second interval.
- A changed prompt fingerprint clears superseded retry state; a confirmed
  prompt clears all retry state for that exact target.
- Raise the requested JavaScript-heap circuit threshold from 768 MiB to 4 GiB.
  The independent three-consecutive-scans-over-250-ms circuit remains.

## Lesson

Bounded clicking is not bounded recovery when navigation still remounts the
same terminal target. Retry state must suppress work before the expensive UI
transition and must not feed a fast-retry scheduler after exhaustion.
