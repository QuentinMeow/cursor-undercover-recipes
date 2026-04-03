# Lessons

## Cursor Version Coupling

- **DOM selectors and excluded zones are coupled to specific Cursor versions**: The
  injector relies on workbench part IDs (`workbench.parts.auxiliarybar`, etc.) and
  CSS class names (`div.full-input-box`, `div.conversations`, `div.composer-bar`).
  Cursor can relocate UI panels across workbench parts between versions. What was
  in the editor area in one version may move to the auxiliary bar in the next.
  Always re-validate the DOM structure when upgrading Cursor.

- **Excluded zones must be conditional, not absolute**: Blanket exclusion of
  `workbench.parts.auxiliarybar` worked when the chat panel was elsewhere. When
  Cursor moved the agent chat into the auxiliary bar, the exclusion silently
  killed all auto-clicking. The fix: check whether the excluded zone also hosts
  a chat surface (`zone.querySelector("div.full-input-box")`). This makes the
  exclusion contextual rather than positional.

- **Synthetic probes mask real failures**: The `diagnose` command's synthetic probe
  injects `role="dialog"` elements that bypass both excluded zones and sibling-scan
  issues. A passing synthetic probe does NOT prove real prompts will be clicked.
  Always validate with real prompts and real click-count deltas.

- **Document the known working Cursor version alongside every injector change**:
  When the injector passes validation, record the Cursor version, Chrome version,
  and the injector script hash. Future failures can then be bisected against version
  changes.

## Live CDP Diagnostic Method

- **When the injector silently fails, deploy a CDP polling diagnostic**: Connect
  to the dedicated window via CDP WebSocket (using the launcher's raw-socket
  handshake to bypass origin restrictions). Evaluate `acceptDebugSnapshot()` plus
  custom DOM queries every 300-500ms. Trigger real prompts and capture what the
  injector sees in real-time. This is the fastest path from "clicks are 0" to
  "here is the exact broken step."

- **Walk from the known-shallow element, not the deeply-nested one**: When checking
  whether a button shares a container with the chat input, walk UP from the input
  box (known-shallow, ~4 levels to the composer root) and use `node.contains(el)`.
  Walking up from the button is fragile because Cursor's component tree can be 25+
  levels deep and any fixed depth limit will eventually be too short.

- **Query the excluded zone directly**: Instead of walking from the button to check
  if it's in a chat surface, use `el.closest(excludedZoneSelector)` to get the zone
  element, then `zone.querySelector("div.full-input-box")` to check if it hosts a
  chat. This is O(1) in DOM traversal and eliminates depth-limit bugs entirely.

- **Capture per-button ancestry in diagnostic snapshots**: When a button is found but
  not clicked, log its full ancestry path (tag, id, class at each level). This
  immediately reveals which workbench part the button lives in and how far it is
  from the expected containers.

## Keyboard Hint Normalization

- **Adjacent spans produce concatenated textContent without whitespace**: Cursor
  renders button labels like "Skip" and "Esc" in separate `<span>` elements.
  `textContent` concatenates them as "SkipEsc" with no space. The keyboard hint
  stripper must handle both "Skip Esc" (whitespace-separated) and "SkipEsc"
  (concatenated). A regex like `/(.{2,}?)\s*(?:esc|escape)$/i` handles both
  without hollowing out standalone "Esc".

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

## Session State Hygiene

- **Dead and invalid sessions must be garbage-collected automatically**: If
  sessions are persisted on disk (e.g. `state.json`), every state load should
  prune entries whose PIDs are dead OR whose workspace paths no longer exist.
  A session with a non-existent workspace is always broken regardless of PID
  status — the Cursor window opened on a bogus path, and keeping the entry
  causes slug collisions, which cascade into new profile dirs and forced
  re-logins.  Relying on explicit `stop` commands for cleanup causes stale
  entries to accumulate and confuse every subsequent command.

- **Bare-name workspace arguments resolve relative to CWD, not intent**:
  `Path("gocmp").resolve()` becomes `$CWD/gocmp`, which may not exist.
  The launcher must validate that the resolved path is an existing directory.
  Do not guess with hardcoded search parents (e.g. `~/code`) — that is
  environment-specific and breaks for other users. Instead, use an explicit
  alias config file (`config.json`) and auto-register directory names on
  successful launch so short names work on subsequent invocations.

- **Auth tokens must be bootstrapped into dedicated profiles**: Electron
  `--user-data-dir` profiles are fully isolated — including login state.
  Copy `cursorAuth/*` rows from the default profile's `state.vscdb` at
  launch time so the user is not forced to re-login for every new workspace.

## Runtime Sync

- **Long-lived injected scripts need an explicit version handshake**: When a
  launcher can update the on-disk JavaScript while the target window stays
  open, compare an on-disk script hash with the in-window injector state and
  reload only when they differ. Otherwise `status` can look healthy while the
  running window still uses stale logic.

## Process Discipline

- **Always update lessons and docs after fixing a bug**: Every bug fix
  must produce a corresponding update to `LESSONS.md`, `issues/`, and
  `references/implementation.md`.  The cost of forgetting is that the
  same mistake recurs because the context is lost.  Treat doc updates
  as part of the definition of done, not an afterthought.

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

- **Approval synonyms drift across Cursor surfaces**: Some permission prompts
  use `Approve` wording rather than `Accept`/`Allow`/`Run`. Keep the label list
  updated with exact synonym variants (`approve`, `approve request`, etc.) and
  verify with real prompt surfaces whenever users report `Waiting for Approval`
  plus unchanged click counters.

- **Keyboard hints can be plain text, not just glyphs**: Cursor shell approval
  cards may render dismiss buttons like `Skip Esc` instead of plain `Skip`.
  Normalize trailing plain-text shortcut hints before exact label matching, or
  otherwise valid `Run` prompts will be blocked because the nearby dismissal is
  invisible to the policy engine.

- **Dismissal-guard exceptions must stay narrow and contextual**: Requiring a
  nearby dismiss action is a strong default, but Cursor can show single-action
  modal permission prompts (`approve terminal command`) with no cancel sibling.
  Handle these with tightly scoped modal-context exceptions, not a global guard
  relaxation.

- **Non-dismissal companion controls are a distinct structural signal**: Tool-call
  approval prompts pair `Allow` with `View` (or `Stop`, `Details`). These are not
  dismissals and must not be added to `DISMISS_PATTERNS` — doing so corrupts the
  semantic model and causes cross-interaction bugs with `isModalSingleActionApprove`.
  Instead, model them as a separate `COMPANION_PATTERNS` set with identical safety
  hygiene (visibility, clickability, zone exclusion, ancestor-depth walk).

- **Eligibility telemetry pays for itself immediately**: Adding a `reason` field
  to click log entries (`dismiss`, `companion`, `modal`, `resume`) makes post-hoc
  debugging trivial. Without it, you can see *that* a click happened but not *why*
  the guard let it through — which is exactly what you need to diagnose false
  positives and missed clicks.

- **Synthetic DOM probes via createElement are more reliable than innerHTML**: When
  injecting test elements via CDP, `innerHTML` can silently fail to set ARIA
  attributes (`role`, `aria-modal`) in some Electron/Chromium contexts.
  `createElement` + `setAttribute` always works.

## Harness Engineering

- **Pass/fail lines are not enough; save per-case evidence artifacts**: Stress tests
  should persist paired screenshots plus machine-readable button inventories and
  eligibility traces for every case. When behavior regresses, visual + structured
  artifacts are the fastest way to understand "what button existed" and "why guard
  logic accepted/rejected it."

- **Prefer real snapshot harnesses for day-to-day confidence**: Synthetic probes are
  useful for deterministic regression checks, but routine validation should collect
  snapshots from real Cursor UI states so selector drift and context assumptions are
  tested against actual product surfaces.

- **Synthetic probe suites must reset dedupe state between cases**: The injector's
  fingerprint cooldown is correct at runtime, but it can create false negatives in
  back-to-back harness cases that reuse the same normalized button set. Clear
  cooldown state before each synthetic or replay case so the harness measures
  matcher behavior, not cross-case residue.

- **Use context-first acceptance, not label-only acceptance**: Exact label matching
  is still brittle if context is weak. Require trusted prompt surfaces (modal roots
  or composer/chat context anchored to the real input box) before evaluating
  dismissal/companion/modal guard rules.

- **Turn real misses into regression fixtures**: When a prompt is missed in
  production, sanitize its DOM capture and commit it as a test fixture. The replay
  harness prevents the same miss from recurring without human involvement.

## Observer-Driven Architecture

- **MutationObserver catches prompts faster than polling alone**: A fixed-interval
  poll has a worst-case latency equal to the interval. A MutationObserver fires
  within milliseconds of DOM changes. The poll remains as a safety net for edge
  cases the observer might miss (e.g., attribute-only changes on existing nodes).

- **Prompt fingerprinting prevents double-clicks**: When a prompt doesn't immediately
  disappear after being clicked (e.g., network delay), the next poll cycle would
  click it again. Computing a fingerprint from the sorted button labels within the
  prompt root and applying a cooldown period prevents this.

- **Split discovery from policy**: Candidate discovery (finding button-like elements)
  should be separate from the policy decision (should this be clicked?). This makes
  each layer independently testable and easier to debug.

## Event Sink and Observability

- **Click events must be persisted durably, not just in memory**: The in-memory
  click history in the injector is lost when the page reloads or the process
  crashes. The event queue + launcher drain pattern ensures events survive across
  sessions.

- **Unknown prompts are the most valuable diagnostic**: When the injector finds a
  button that matches an approval pattern but lacks trusted context, that's a
  signal that either the pattern list or the context detection needs updating.
  Capturing these as artifacts with the prompt subtree makes debugging trivial.

- **Stale hooks cause split-brain debugging**: Having two approval systems active
  simultaneously makes every failure ambiguous. Detect and warn about conflicting
  configurations at startup, not after hours of debugging.


