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
  `Path("example-lib").resolve()` becomes `$CWD/example-lib`, which may not exist.
  The launcher must validate that the resolved path is an existing directory.
  Do not guess with hardcoded search parents (e.g. `~/code`) — that is
  environment-specific and breaks for other users. Instead, use an explicit
  alias config file (`config.json`) and auto-register directory names on
  successful launch so short names work on subsequent invocations.

- **Alias resolution must preserve workspace kind**: `config.json` can contain
  both local paths and `vscode-remote://ssh-remote+...` folder URIs. A command
  that advertises alias support must not re-validate every alias as a local
  directory. Resolve SSH URI aliases as SSH workspaces and dispatch them through
  the same path as `launch-ssh`, including remote path preflight.

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
  use `Approve` wording rather than `Accept`/`Allow`/`Run`, and compound labels
  like `Allow scripts` do not match the shorter `allow` pattern. Keep the label
  list updated with exact synonym variants (`approve`, `approve request`,
  `allow scripts`, etc.) and verify with real prompt surfaces whenever users
  report `Waiting for Approval` plus unchanged click counters.

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

## Background Window Behavior

- **Do not equate OS focus with renderer suspension**: On Cursor 3.12.17, a
  dedicated window with `document.hasFocus() === false` and
  `document.visibilityState === "visible"` continued to auto-click real `Run`
  prompts. Separate visible dedicated windows can therefore operate in
  parallel. Verify with click-count deltas instead of assuming only the key
  window works.

- **Minimized or hidden is still a separate risk**: Chromium may throttle a
  renderer whose visibility state becomes `hidden`. The successful non-focused
  case does not prove minimized-window reliability. For unattended workflows,
  inspect `status` and direct click evidence after changing window visibility.

## Sidebar Agent Mounting

- **Sidebar rows are navigation, not parallel chat DOMs**: On Cursor 3.12.17,
  direct CDP inspection found exactly one `div.full-input-box` and one
  `div.conversations`. Selecting a pinned row replaced that mounted chat while
  the counts remained one. Inactive pinned agents therefore have no approval
  buttons available for a DOM injector to click.

- **Pinned row cycling is sequential, never simultaneous**: Clicking each
  sidebar row exposes one chat at a time. Automatic navigation must therefore
  target only active unselected pinned rows while the Agent Window is
  unfocused. A focused-window `cycle --once` is an explicit bounded test, not
  background behavior.

- **Top-level navigation needs exact restoration identity**: Use the exact
  `Pinned` section, a normalized title unique across the rendered Agent
  sidebar, `data-selected`, and matching selected editor resource. Never trust
  a retained sidebar node after navigation; re-resolve the unique title and
  Pinned-section membership immediately before every visit, then fail closed
  on title/resource drift. Restore scroll against the remounted conversation
  rather than a disconnected pre-navigation container.

- **Refresh nested recovery after switching top-level agents**: Selecting a
  pinned row replaces the mounted conversation, invalidating tray elements and
  virtual-row references. Restore the original agent and rediscover nested
  rows/tray entries before continuing the cycle.

- **A newer user selection outranks automation restoration**: Capture an
  interaction generation before top-level navigation. If it changes, abort the
  entire cycle, preserve the user's current sidebar/tab/scroll selection, and
  skip all remaining pinned, tray, and virtual-row navigation. Apply the same
  guard while mounting, confirming, and restoring every path. A focus-only
  transition may restore automation-owned state, but must still end that cycle.

- **Give navigation paths independent budgets**: A slow pinned visit must not
  consume the time reserved for tray or virtual-row recovery. Bound pinned
  work separately and rotate its cursor across cycles.

## Running-Subagent Tray Recovery

- **Read-only subagent editors may have no composer input**: On Cursor 3.12.17,
  selecting an `N subagents running` tray entry mounted a child editor with
  `div.conversations` but no `div.full-input-box`. Input-anchored discovery
  cannot recognize that surface. Use exact tray-row and selected-tab identity
  to establish a narrow trusted scope.

- **A navigation fallback must restore actual widget state**: Calling
  `HTMLElement.click()` did not restore Cursor's selected editor tab. The tab
  widget required a synthetic `mousedown`/`mouseup` sequence before `click`.
  Verify restoration by reading `aria-selected` after the cycle, not by assuming
  a dispatched click changed selection.

- **Excluded-zone exceptions must be identity-scoped**: Child agent editors
  live under the normally excluded editor workbench part. Permit matching there
  only after an exact running-tray title resolves to one selected agent tab and
  one conversations surface. Keep exact approval labels, nearby dismissal or
  companion evidence, unrelated-modal blocking, and click coverage checks.

- **Redundant approval paths still need bounded ownership**: Keep immediate
  mounted-composer scanning as the fast path and use tray navigation as
  recovery. Visit a bounded number of tray rows per pass, confirm that each
  prompt changed, cap retries, and retain the interaction guard so redundancy
  does not become unbounded UI churn.

- **Selected editor does not mean transcript tail mounted**: A long read-only
  child can expose its selected tab and `div.conversations` before the pending
  approval at the transcript tail mounts. A fixed post-navigation sleep can
  repeatedly restore the parent too early. Observe mutations in the exact child
  group, require a minimum candidate wait, finish after DOM quiet, and retain a
  hard timeout plus selected-tab identity check.

- **A tray visit without a candidate needs explicit telemetry**: Recording only
  `tray_visit` makes successful navigation indistinguishable from a premature
  scan. Record the no-candidate reason, wait duration, and count of raw approval
  controls without persisting prompt content.

- **Loss of eligibility is not approval confirmation**: A clicked control may
  become disabled, hidden, covered, or briefly detached while the prompt
  remains pending. Confirm against raw control presence over consecutive final
  checks, not against the filtered set of currently clickable candidates. If a
  framework reuses the same node, compare its current label and prompt identity
  instead of treating connectedness alone as pending.

- **Navigation ownership spans mount through verified restoration**:
  Mutation-driven ordinary scans can run before a selected editor finishes
  mounting and after synchronous restoration clicks are dispatched. Acquire
  scoped ownership before navigation, then retain it until sidebar/resource
  identity and selected tabs are observed restored so another click path cannot
  race or retry concurrently. Body-level portal controls have no editor-group
  ancestor, so fail closed by withholding every ordinary-scanner candidate
  while navigation ownership is active.

## Focus Preservation During Recovery

- **A start-only interaction guard is not enough**: Even a 150 ms approval
  cycle can overlap a user moving from chat to the terminal. Track a monotonic
  interaction generation through the entire asynchronous cycle, not only the
  time since the last input at cycle start.

- **A native `scroll` event is not necessarily user input**: Cursor transcript
  auto-follow and programmatic `scrollTop` changes can emit trusted scroll
  events after the write. Track wheel, pointer, and keyboard intent instead;
  otherwise normal output falsely aborts navigation as a user takeover.

- **Never restore stale focus from multiple owners**: Scroll restoration and
  tab restoration both calling `focus()` can overwrite a newer user choice.
  Keep scroll/tab state restoration focus-free and route focus through one
  owner that resolves the latest user target. Use that owner for direct
  approval clicks too, because product post-click behavior can change focus
  without any tab navigation.

- **Focused editing surfaces should block automatic navigation**: When the
  dedicated window is focused and its terminal or another non-composer editor
  is active, postpone row/tray cycling even if the user has paused typing for
  more than the normal interaction timeout. Direct non-navigating approval
  scans can continue.

- **Product focus can settle after the automation promise**: Cursor may focus
  its agent surface asynchronously after an approval resolves. Restore focus
  immediately and once more after a short delay, but re-resolve the latest user
  interaction before the delayed attempt so the correction cannot itself steal
  focus.

- **Rollback only automation's scroll contribution on takeover**: User input
  can arrive while virtual-row materialization is awaiting a mount. Record the
  actual programmatic scroll delta and subtract that delta from the current
  position on takeover. This removes automation's movement while preserving
  any relative wheel/keyboard movement the user added afterward.

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

- **Runtime interval changes must replace the existing timer**: A
  `startAccept(interval)` API that returns early when already running makes a
  CLI interval flag appear successful without changing behavior. Update
  `state.interval`, clear the current timer, and install a new timer before
  reporting the requested interval.

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

## Command Text Extraction

- **Button labels alone are not enough for post-hoc debugging**: Knowing that
  "Run" was clicked does not tell you what command was approved. Extracting the
  command text from the prompt surface before clicking and persisting it in a
  dedicated ledger makes approval auditing possible.

- **Extract before clicking, not after**: The DOM may change immediately after
  `el.click()` (the prompt may close). Always capture command text and prompt
  subtree before the click, not after.

- **Prefer `innerText` over `textContent` for human-readable output**:
  `textContent` flattens all descendant text without whitespace boundaries.
  `innerText` preserves visual formatting including newlines, making multiline
  commands readable in persisted logs.

- **Separate the command ledger from the general event log**: The general
  `history.jsonl` mixes session/gate/click/blocked/unknown events and rotates
  at 5 MB. A dedicated `commands.jsonl` with a larger rotation window (10 MB)
  ensures approved commands are not diluted or rotated away by high-frequency
  gate toggles.

- **Approved commands may contain secrets**: Tokens, passwords, and sensitive
  paths can appear in terminal commands. The command ledger is a local
  diagnostic record; treat it with the same caution as shell history.

## Renderer Performance and Fail-Safe Bounds

- **Faster polling and duplicate-click prevention are separate controls**: A
  500ms fallback lets different task cards be approved on consecutive scans.
  The per-fingerprint eight-second cooldown still prevents one unresolved card
  from being clicked every 500ms. Do not slow global polling to solve a
  per-prompt deduplication problem.

- **A cooling candidate must not abort the whole scan**: Apply per-prompt
  cooldown while selecting the scan's one click. If the first eligible
  candidate is cooling down, continue to the next distinct candidate; return
  only when all eligible candidates are cooling down.

- **Concurrent approval tests need delayed work plus parent transcript growth**:
  Launch several read-only tasks that do useful inspection before a 60-second
  sleep, then keep the parent producing relevant output. This exercises
  simultaneous permission cards, virtual-row unmounting, lifecycle updates,
  and renderer load in one bounded test.

- **Task status can be temporarily non-monotonic**: Cursor may mark the outer
  tool row `completed` before a nested subagent permission card appears. A
  visible eligible approval must outrank the outer `data-tool-status`; later
  mutation discovery can move the registry from `completed` to
  `approval_pending` and back to `completed`.

- **Task-scoped fingerprints enable safe throughput**: Four concurrent
  `Allow|Stop` prompts had identical labels but distinct task/row identities.
  The injector safely clicked all four, including two clicks 500ms apart,
  without weakening the cooldown for any individual prompt.

- **Scope reductions must pass the preserved real-prompt corpus**: Limiting the
  delete-file fallback to virtual rows fixed renderer load but initially broke
  the real editor-surface `Reject|Accept` fixture. Preserve exceptional coverage
  with an exact `.composer-tool-former-message` selector, deduplicate overlaps,
  and cap inspected roots instead of restoring a `document.body` scan.

- **Never run nested broad selectors from `document.body` after every
  mutation**: The old delete-file fallback gathered overlapping
  composer/message/tool containers, then scanned all descendant controls in
  each. Long streaming transcripts turned that into repeated superlinear DOM
  work. Scope fallbacks to mounted virtual rows or an exact prompt root.

- **Mutation observers need semantic filtering and a minimum scan gap**:
  Character-data and class mutations are continuous while an agent streams.
  Only task-row and approval-control mutations should trigger immediate work;
  the fallback poll handles uncertain changes. Rate-limit observer scans even
  after filtering.

- **Private debug APIs must not be toggled per mutation**: Enabling and disabling
  Cursor's virtualizer snapshot can itself cause renderer work. Cache one
  validated snapshot for a short interval and force at most one refresh at the
  start of a bounded cycle.

- **Automation running in the renderer needs a circuit breaker**: Track scan
  duration and JavaScript heap. Repeated pathological scans or a heap threshold
  should turn the gate off and record a durable safety event rather than
  contributing to an unresponsive window.

- **Renderer reloads invalidate pinned target IDs without necessarily changing
  the main PID or CDP port**: Rebind only when exactly one workbench target
  exists. Ambiguous target sets must still fail closed.

## Automation Defaults

- **A launch-time ON promise must include bounded recovery for routine hidden
  states**: If virtualization can hide approvals from the normal scan, leaving
  exact-row recovery OFF creates a partially working default that appears
  reliable only after manual scrolling. Enable safety-scoped recovery with the
  main automation and preserve an explicit opt-out.

## Retry State Reconciliation

- **Discovery must not reopen an exhausted retry state**: If the same unresolved
  approval remains after the bounded retry fails, preserve the terminal failure
  until the approval clears and changed row state can be observed. Otherwise
  each mutation silently resets the retry budget and creates an unbounded loop.

- **Retry-governed actions need one click owner**: A confirmation-aware cycle
  cannot enforce retry limits if a generic scanner can click the same registered
  control on its own cooldown. Route owned candidates exclusively through the
  bounded path, while retaining generic fallback when ownership is absent or
  disabled.
