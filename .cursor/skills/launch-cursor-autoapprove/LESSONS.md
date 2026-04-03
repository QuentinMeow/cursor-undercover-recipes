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

- **Use context-first acceptance, not label-only acceptance**: Exact label matching
  is still brittle if context is weak. Require trusted prompt surfaces (modal roots
  or composer/chat context anchored to the real input box) before evaluating
  dismissal/companion/modal guard rules.
