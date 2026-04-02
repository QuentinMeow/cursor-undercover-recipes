# Lessons

## Runtime Sync

- **Long-lived injected scripts need an explicit version handshake**: When a
  launcher can update the on-disk JavaScript while the target window stays
  open, compare an on-disk script hash with the in-window injector state and
  reload only when they differ. Otherwise `status` can look healthy while the
  running window still uses stale logic.

## DOM Auto-Click Safety

- **Never use substring matching for approval labels in an IDE**: File names,
  editor content, and terminal output routinely contain words like "run",
  "allow", and "apply". Use exact match (after stripping keyboard hints) and
  zone exclusion (skip sidebar/editor) plus a nearby-dismissal guard to prevent
  false clicks.
  This is the DOM equivalent of earlier AX-watcher false-positive incidents.

- **Matching must be paired with structural context and conservative clicks**:
  exact label matching still needs prompt-root scoping and nearby-dismissal
  checks, and click simulation should stay minimal (`el.click()` first, no
  blind Enter key spam). This combination is what turns "best effort" DOM
  automation into something predictable enough for day-to-day use.
