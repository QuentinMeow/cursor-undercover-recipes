# Lessons

## CDP Target Binding

- **Port-scoped CDP control is not window-scoped**: A single CDP debugging
  port can expose multiple `type: "page"` targets when the Electron process
  has more than one workbench window. Dynamically picking "the first workbench
  target" on every command causes silent mis-targeting. The fix is to pin a
  specific target ID at launch time and store it in session state so all
  subsequent commands address only that page.

- **Fail closed on target loss**: If the pinned target disappears from the
  `/json` listing, the command must error out with a clear message instead
  of silently retargeting another page. False-positive success signals are
  worse than failures because they erode trust in the harness.

- **Warn on ambiguity**: When multiple workbench targets appear on a
  session's port, `status` must surface a visible WARNING. The extra targets
  likely mean a manual window was opened inside the dedicated process, which
  can confuse CDP commands.

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
