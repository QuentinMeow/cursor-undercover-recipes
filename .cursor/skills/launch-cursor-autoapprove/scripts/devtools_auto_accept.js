// Cursor Auto-Accept DOM Injector
// Injected by launcher.py via CDP Runtime.evaluate.
// Canonical DOM injector for the launch-cursor-autoapprove skill.
// Manual DevTools paste is emergency fallback only.
//
// Architecture: observer-driven surface detection + policy engine + event sink.
// The MutationObserver detects DOM changes immediately; a fallback poll catches
// anything the observer misses. The policy engine decides click/block/unknown.
// All decisions are queued in state.eventQueue for the launcher to drain and
// persist durably.
//
// API:  startAccept()  stopAccept()  acceptStatus()  acceptDebugSnapshot()
//       setShareSafeTitle(bool)  setSubagentCycle(bool)
//       runSubagentCycle()  exportSubagentRegistry()
(function () {
  "use strict";

  if (globalThis.__cursorAutoAccept) {
    console.log("[autoAccept] already loaded — use startAccept() / stopAccept()");
    return;
  }

  // Capture Cursor's native title once at inject time so we can restore it in
  // screen-share mode (before any branded title runs).
  const NATURAL_DOC_TITLE_AT_INJECT = document.title;
  const _naturalTitlebarEl = document.querySelector(
    '[id="workbench.parts.titlebar"] .window-title-text'
  );
  const NATURAL_TITLEBAR_TEXT_AT_INJECT = _naturalTitlebarEl
    ? String(_naturalTitlebarEl.textContent || "")
    : "";

  const LOG_PREFIX = "[autoAccept]";
  const SCRIPT_HASH = globalThis.__cursorAutoAcceptScriptHash || "unknown";
  const REPO_SLUG = globalThis.__cursorAutoAcceptRepoSlug || "workspace";
  const STRATEGY_VERSION = "2026-07-subagent-cycle-v3-focus-safe";
  const TITLE_SYNC_INTERVAL = 3000;
  /** Faster ping while discreet so Cursor cannot show a fresh native title for long. */
  const TITLE_SYNC_INTERVAL_SHARE_SAFE = 500;
  const OBSERVER_DEBOUNCE_MS = 300;
  const OBSERVER_MIN_SCAN_GAP_MS = 500;
  const DEFAULT_POLL_INTERVAL_MS = 500;
  const MIN_POLL_INTERVAL_MS = 250;
  const MAX_POLL_INTERVAL_MS = 60000;
  const FINGERPRINT_COOLDOWN_MS = 8000;
  const EVENT_QUEUE_MAX = 200;
  const SUBAGENT_STORAGE_VERSION = 1;
  const SUBAGENT_REGISTRY_MAX = 500;
  const SUBAGENT_ROW_SELECTOR = ".virtualized-composer-messages-row";
  const SUBAGENT_SURFACE_SELECTOR = '.subagent-task-card, [class*="task-subagent"]';
  const SUBAGENT_TRAY_ITEM_SELECTOR = ".composer-toolbar-background-job-item-clickable";
  const SUBAGENT_TRAY_TITLE_SELECTOR = ".composer-toolbar-background-job-item-text";
  const SUBAGENT_TRAY_HEADER_PATTERN = /^\d+\s+subagents?\s+running$/i;
  const SCROLL_CONTAINER_SELECTOR = ".virtualized-composer-messages-scroll-container";
  const CYCLE_INTERACTION_GUARD_MS = 2000;
  const CYCLE_MOUNT_TIMEOUT_MS = 250;
  const CYCLE_CONFIRM_DELAYS_MS = [150, 350, 700, 1200];
  const CYCLE_AUTOMATIC_INTERVAL_MS = 5000;
  const CYCLE_MAX_TASKS = 20;
  const CYCLE_MAX_TRAY_ITEMS = 8;
  const CYCLE_MAX_DURATION_MS = 10000;
  const CYCLE_TRAY_MOUNT_TIMEOUT_MS = 800;
  const CYCLE_TRAY_MIN_CANDIDATE_WAIT_MS = 1000;
  const CYCLE_TRAY_QUIET_MS = 250;
  const CYCLE_TRAY_CANDIDATE_TIMEOUT_MS = 1500;
  const CYCLE_TRAY_CONFIRM_DELAYS_MS = [100, 300, 600];
  const CYCLE_TRAY_MAX_ATTEMPTS = 2;
  const FOCUS_SETTLE_DELAY_MS = 300;
  const VIRTUALIZER_SNAPSHOT_CACHE_MS = 5000;
  const MAX_SAFE_SCAN_DURATION_MS = 250;
  const MAX_CONSECUTIVE_SLOW_SCANS = 3;
  const MAX_JS_HEAP_BYTES = 768 * 1024 * 1024;
  const ACTIVE_SUBAGENT_STATUSES = new Set([
    "discovered",
    "running",
    "approval_pending",
    "approval_attempted",
    "approved",
  ]);

  // -----------------------------------------------------------------------
  // Pattern tables (discovery layer)
  // -----------------------------------------------------------------------

  const APPROVAL_PATTERNS = [
    { pattern: "accept all", id: "accept_all" },
    { pattern: "accept", id: "accept" },
    { pattern: "approve", id: "approve" },
    { pattern: "approve request", id: "approve_request" },
    { pattern: "approve terminal command", id: "approve_terminal_command" },
    { pattern: "always allow", id: "always_allow" },
    { pattern: "allow", id: "allow" },
    { pattern: "allow scripts", id: "allow_scripts" },
    { pattern: "run this time only", id: "run_this_time" },
    { pattern: "run command", id: "run_command" },
    { pattern: "run", id: "run" },
    { pattern: "apply", id: "apply" },
    { pattern: "execute", id: "execute" },
    { pattern: "continue", id: "continue" },
    { pattern: "switch", id: "switch_mode" },
    { pattern: "switch mode", id: "switch_mode_explicit" },
    { pattern: "change mode", id: "change_mode" },
    { pattern: "confirm", id: "confirm" },
  ];

  const EXCLUDED_ZONES = [
    '[id="workbench.parts.sidebar"]',
    '[id="workbench.parts.editor"]',
    '[id="workbench.parts.panel"]',
    '[id="workbench.parts.statusbar"]',
    '[id="workbench.parts.activitybar"]',
    '[id="workbench.parts.auxiliarybar"]',
  ];
  const BUTTON_SELECTORS = [
    "button",
    '[role="button"]',
    'a[role="button"]',
    '[class*="primary-button"]',
    '[class*="secondary-button"]',
    '[class*="text-button"]',
    '[class*="action-label"]',
    '.view-allow-btn-container-inner > div',
  ];
  const LOOSE_TEXT_CONTROL_SELECTORS = [
    ...BUTTON_SELECTORS,
    "div",
    "span",
  ];
  const PROMPT_ROOT_SELECTORS = [
    '[role="dialog"]',
    '[role="alertdialog"]',
    '[aria-modal="true"]',
  ];
  const DELETE_FILE_PROMPT_PATTERN = /\bdelete(?:\s+file)?\b/i;
  const DELETE_FILE_SURFACE_SELECTOR = ".composer-tool-former-message";
  const MAX_DELETE_FILE_FALLBACK_ROOTS = 100;
  const DISMISS_PATTERNS = new Set([
    "skip", "cancel", "dismiss", "deny", "not now", "close", "reject",
    "don't allow", "decline",
  ]);
  const COMPANION_PATTERNS = new Set(["view", "stop", "details", "show details"]);

  const RESUME_DATA_LINK = "command:composer.resumeCurrentChat";

  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------

  const state = {
    scriptHash: SCRIPT_HASH,
    repoSlug: REPO_SLUG,
    workspace: globalThis.__cursorAutoAcceptWorkspace || REPO_SLUG,
    targetId: globalThis.__cursorAutoAcceptTargetId || "unbound-target",
    interval: DEFAULT_POLL_INTERVAL_MS,
    running: false,
    timer: null,
    titleTimer: null,
    observer: null,
    observerDebounceTimer: null,
    totalClicks: 0,
    clicks: [],
    eventQueue: [],
    fingerprintCooldowns: new Map(),
    totalClickAttempts: 0,
    totalConfirmedApprovals: 0,
    totalScans: 0,
    lastScanDurationMs: 0,
    maxScanDurationMs: 0,
    lastScanAt: 0,
    consecutiveSlowScans: 0,
    safetyTrip: null,
    virtualizerCache: null,
    virtualizerCacheAt: 0,
    subagents: new Map(),
    // Recovery for registered subagent rows is part of the default launch
    // behavior. Users can still disable it explicitly with `caa cycle --off`.
    cycleEnabled: true,
    cycleActive: false,
    cycleTimer: null,
    cycleGeneration: 0,
    cycleCursor: 0,
    trayCursor: 0,
    trayApprovalAttempts: new Map(),
    totalTrayVisits: 0,
    totalTrayApprovalAttempts: 0,
    totalTrayConfirmedApprovals: 0,
    lastCycle: null,
    lastUserInteractionAt: 0,
    lastUserInteractionType: null,
    interactionGeneration: 0,
    lastUserFocusElement: null,
    lastUserFocusGeneration: 0,
    focusRestoreGeneration: 0,
    lastFocusRestore: null,
    interactionGuardInstalled: false,
    programmaticScrollDepth: 0,
    enableResume: true,
    enableConnectionRetry: true,
    enableStateProbe: false,
    /** When true, stop overriding the window title with autoapprove branding. */
    shareSafeTitle: false,
  };

  // -----------------------------------------------------------------------
  // Subagent registry, virtualizer adapter, and cycle scheduler
  // -----------------------------------------------------------------------

  function _subagentStorageKey() {
    return [
      "cursor-autoaccept-subagents",
      SUBAGENT_STORAGE_VERSION,
      state.workspace,
      state.targetId,
    ].join(":");
  }

  function _sanitizeSubagentRecord(record) {
    return {
      taskKey: String(record.taskKey || "").slice(0, 1000),
      workspace: String(record.workspace || state.workspace).slice(0, 1000),
      targetId: String(record.targetId || state.targetId).slice(0, 200),
      parentComposerId: String(record.parentComposerId || "").slice(0, 200),
      parentConversationId: record.parentConversationId
        ? String(record.parentConversationId).slice(0, 200)
        : null,
      toolUseId: record.toolUseId ? String(record.toolUseId).slice(0, 300) : null,
      rowKey: String(record.rowKey || "").slice(0, 1000),
      bubbleIds: Array.isArray(record.bubbleIds)
        ? record.bubbleIds.slice(0, 20).map((v) => String(v).slice(0, 200))
        : [],
      rowIndexHint: Number.isFinite(record.rowIndexHint) ? record.rowIndexHint : null,
      rowStartHint: Number.isFinite(record.rowStartHint) ? record.rowStartHint : null,
      title: String(record.title || "Subagent task").slice(0, 120),
      status: String(record.status || "discovered").slice(0, 40),
      firstSeenAt: record.firstSeenAt || null,
      lastSeenAt: record.lastSeenAt || null,
      lastProgressAt: record.lastProgressAt || null,
      lastAttemptAt: record.lastAttemptAt || null,
      confirmedAt: record.confirmedAt || null,
      attempts: Number.isFinite(record.attempts) ? record.attempts : 0,
      failure: record.failure ? String(record.failure).slice(0, 120) : null,
    };
  }

  function _persistSubagentRegistry() {
    try {
      const tasks = Array.from(state.subagents.values())
        .slice(-SUBAGENT_REGISTRY_MAX)
        .map(_sanitizeSubagentRecord);
      localStorage.setItem(
        _subagentStorageKey(),
        JSON.stringify({
          version: SUBAGENT_STORAGE_VERSION,
          workspace: state.workspace,
          targetId: state.targetId,
          cycleEnabled: state.cycleEnabled,
          tasks,
          savedAt: new Date().toISOString(),
        })
      );
    } catch (e) {
      console.log(`${LOG_PREFIX} could not persist subagent registry:`, e.message);
    }
  }

  function _loadSubagentRegistry() {
    try {
      const raw = localStorage.getItem(_subagentStorageKey());
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (
        parsed?.version !== SUBAGENT_STORAGE_VERSION ||
        parsed.workspace !== state.workspace ||
        parsed.targetId !== state.targetId ||
        !Array.isArray(parsed.tasks)
      ) {
        return;
      }
      state.cycleEnabled = parsed.cycleEnabled === true;
      for (const input of parsed.tasks.slice(-SUBAGENT_REGISTRY_MAX)) {
        if (!input || !input.taskKey || !input.rowKey || !input.parentComposerId) continue;
        const record = _sanitizeSubagentRecord(input);
        if (ACTIVE_SUBAGENT_STATUSES.has(record.status)) {
          record.status = "stale";
          record.failure = "injector_reload";
        }
        state.subagents.set(record.taskKey, record);
      }
    } catch (e) {
      console.log(`${LOG_PREFIX} could not restore subagent registry:`, e.message);
    }
  }

  function _getVirtualizerSnapshot(force = false) {
    if (
      !force &&
      state.virtualizerCache &&
      Date.now() - state.virtualizerCacheAt < VIRTUALIZER_SNAPSHOT_CACHE_MS
    ) {
      return state.virtualizerCache;
    }
    const api = globalThis.__cursorComposerVirtualizationDebug;
    if (
      !api ||
      typeof api.getSnapshot !== "function" ||
      typeof api.getEngineKind !== "function"
    ) {
      return { ok: false, reason: "virtualizer_api_missing" };
    }

    let wasEnabled = null;
    try {
      if (
        typeof api.isSnapshotEnabled === "function" &&
        typeof api.setSnapshotEnabled === "function"
      ) {
        wasEnabled = api.isSnapshotEnabled();
        if (!wasEnabled) api.setSnapshotEnabled(true);
      }
      const snapshot = api.getSnapshot();
      if (wasEnabled === false) api.setSnapshotEnabled(false);
      if (
        !snapshot ||
        typeof snapshot.composerId !== "string" ||
        !Array.isArray(snapshot.rows) ||
        !Number.isFinite(snapshot.totalSize)
      ) {
        const failed = { ok: false, reason: "virtualizer_shape_changed" };
        state.virtualizerCache = failed;
        state.virtualizerCacheAt = Date.now();
        return failed;
      }
      const rowsValid = snapshot.rows.every(
        (row) =>
          row &&
          Number.isFinite(row.index) &&
          typeof row.key === "string" &&
          Number.isFinite(row.start)
      );
      if (!rowsValid) {
        const failed = { ok: false, reason: "virtualizer_rows_invalid" };
        state.virtualizerCache = failed;
        state.virtualizerCacheAt = Date.now();
        return failed;
      }
      const result = {
        ok: true,
        engine: String(api.getEngineKind() || "unknown"),
        snapshot,
      };
      state.virtualizerCache = result;
      state.virtualizerCacheAt = Date.now();
      return result;
    } catch (e) {
      if (wasEnabled === false) {
        try {
          api.setSnapshotEnabled(false);
        } catch (_) {}
      }
      const failed = { ok: false, reason: `virtualizer_error:${e.message}` };
      state.virtualizerCache = failed;
      state.virtualizerCacheAt = Date.now();
      return failed;
    }
  }

  function _findSnapshotRow(snapshot, rowKey) {
    const matches = snapshot.rows.filter((row) => row.key === rowKey);
    return matches.length === 1 ? matches[0] : null;
  }

  function _findExactRow(rowKey) {
    const rows = document.querySelectorAll(`${SUBAGENT_ROW_SELECTOR}[data-find-row-key]`);
    for (const row of rows) {
      if (
        row.getAttribute("data-find-row-key") === rowKey &&
        row.querySelector(SUBAGENT_SURFACE_SELECTOR)
      ) {
        return row;
      }
    }
    return null;
  }

  function _toolUseIdFromRowKey(rowKey) {
    const match = String(rowKey || "").match(/:tool:([^\s]+)/);
    return match ? match[1] : null;
  }

  function _bubbleIdsFromRow(row) {
    const raw = row.getAttribute("data-find-bubble-ids") || "";
    return raw
      .split(/[\s,]+/)
      .map((value) => value.trim())
      .filter(Boolean)
      .slice(0, 20);
  }

  function _shortTaskTitle(surface) {
    const preferred = surface.querySelector(
      '.task-tool-call-header .truncate, [class*="title"], [class*="name"], [class*="summary"], header'
    );
    const source = preferred || surface;
    const lines = String(source.innerText || source.textContent || "")
      .split(/\n+/)
      .map((line) => line.trim().replace(/\s+/g, " "))
      .filter(Boolean)
      .filter((line) => !APPROVAL_PATTERNS.some(({ pattern }) => normalizeLabel(line) === pattern))
      .filter((line) => !DISMISS_PATTERNS.has(normalizeLabel(line)))
      .filter((line) => !COMPANION_PATTERNS.has(normalizeLabel(line)));
    return (lines[0] || "Subagent task").slice(0, 120);
  }

  function _visibleRowApproval(row) {
    const seen = new Set();
    for (const selector of BUTTON_SELECTORS) {
      for (const el of row.querySelectorAll(selector)) {
        if (seen.has(el)) continue;
        seen.add(el);
        if (matchesApproval(el)) return true;
      }
    }
    return false;
  }

  function _rowHasLabel(row, labels) {
    const seen = new Set();
    for (const selector of BUTTON_SELECTORS) {
      for (const el of row.querySelectorAll(selector)) {
        if (seen.has(el)) continue;
        seen.add(el);
        if (!isVisible(el) || !isClickable(el)) continue;
        const text = normalizeLabel(String(el.textContent || ""));
        if (labels.has(text)) return true;
      }
    }
    return false;
  }

  function _deriveTaskStatus(row, existingStatus = "discovered") {
    if (_visibleRowApproval(row)) {
      // An unconfirmed click is terminal until the card actually changes.
      // Otherwise mutation discovery immediately reactivates the same failed
      // task and the default-on scheduler retries it forever.
      return existingStatus === "failed" ? "failed" : "approval_pending";
    }
    if (_rowHasLabel(row, new Set(["stop"]))) return "running";
    const toolStatus = String(
      row.querySelector("[data-tool-status]")?.getAttribute("data-tool-status") || ""
    ).toLowerCase();
    if (/\b(completed|finished|done|succeeded|success)\b/.test(toolStatus)) {
      return "completed";
    }
    if (/\b(failed|errored|cancelled|canceled)\b/.test(toolStatus)) return "failed";
    const surface = row.querySelector(SUBAGENT_SURFACE_SELECTOR);
    const explicit = String(
      surface?.getAttribute("data-status") ||
      surface?.getAttribute("aria-label") ||
      ""
    ).toLowerCase();
    const shortText = String(surface?.innerText || surface?.textContent || "")
      .slice(0, 1000)
      .toLowerCase();
    const statusText = `${explicit} ${shortText}`;
    if (/\b(failed|errored|cancelled|canceled)\b/.test(statusText)) return "failed";
    if (/\b(completed|finished|done)\b/.test(statusText)) return "completed";
    if (/\b(waiting for approval|approval required|needs approval)\b/.test(statusText)) {
      return "approval_pending";
    }
    if (existingStatus === "approval_attempted") return existingStatus;
    return "running";
  }

  function _rowCandidatesFromRoot(root) {
    const candidates = [];
    const seen = new Set();
    collectApprovalMatches(root, candidates, seen);
    return candidates.filter((candidate) => root.contains(candidate.el));
  }

  function _taskForRow(row) {
    if (!row) return null;
    const rowKey = row.getAttribute("data-find-row-key");
    if (!rowKey) return null;
    const matches = Array.from(state.subagents.values()).filter(
      (record) => record.rowKey === rowKey && record.parentComposerId
    );
    return matches.length === 1 ? matches[0] : null;
  }

  function _discoverSubagentRows(root = document) {
    const rows = new Set();
    const roots = Array.isArray(root) ? root : [root];
    for (const candidateRoot of roots) {
      if (candidateRoot?.nodeType === Node.ELEMENT_NODE) {
        if (candidateRoot.matches?.(SUBAGENT_ROW_SELECTOR)) rows.add(candidateRoot);
        const parentRow = candidateRoot.closest?.(SUBAGENT_ROW_SELECTOR);
        if (parentRow) rows.add(parentRow);
      }
      const scope = candidateRoot?.querySelectorAll ? candidateRoot : document;
      for (const row of scope.querySelectorAll?.(SUBAGENT_ROW_SELECTOR) || []) {
        rows.add(row);
      }
    }
    const taskRows = Array.from(rows).filter((row) =>
      row.querySelector(SUBAGENT_SURFACE_SELECTOR)
    );
    if (taskRows.length === 0) return 0;

    const virtualizer = _getVirtualizerSnapshot();
    if (!virtualizer.ok) return 0;
    const snapshot = virtualizer.snapshot;

    let changed = false;
    let discovered = 0;
    const now = new Date().toISOString();
    for (const row of taskRows) {
      const surface = row.querySelector(SUBAGENT_SURFACE_SELECTOR);
      if (!surface) continue;
      const rowKey = row.getAttribute("data-find-row-key");
      if (!rowKey) continue;
      const snapshotRow = _findSnapshotRow(snapshot, rowKey);
      if (!snapshotRow) continue;
      const toolUseId = _toolUseIdFromRowKey(rowKey);
      const identity = toolUseId || rowKey;
      const taskKey = [
        state.workspace,
        state.targetId,
        snapshot.composerId,
        identity,
      ].join("|");
      const existing = state.subagents.get(taskKey);
      const nextStatus = _deriveTaskStatus(row, existing?.status);
      const title = _shortTaskTitle(surface);
      if (!existing) {
        const record = {
          taskKey,
          workspace: state.workspace,
          targetId: state.targetId,
          parentComposerId: snapshot.composerId,
          parentConversationId: null,
          toolUseId,
          rowKey,
          bubbleIds: _bubbleIdsFromRow(row),
          rowIndexHint: snapshotRow.index,
          rowStartHint: snapshotRow.start,
          title,
          status: nextStatus,
          firstSeenAt: now,
          lastSeenAt: now,
          lastProgressAt: now,
          lastAttemptAt: null,
          confirmedAt: null,
          attempts: 0,
          failure: null,
        };
        state.subagents.set(taskKey, record);
        _queueEvent({
          type: "subagent_discovered",
          taskKey,
          toolUseId,
          rowKey,
          rowIndexHint: snapshotRow.index,
          rowStartHint: snapshotRow.start,
          title,
          status: nextStatus,
        });
        discovered++;
        changed = true;
      } else {
        const previousStatus = existing.status;
        const progressChanged = previousStatus !== nextStatus || existing.title !== title;
        const lastSeenAge = Date.now() - Date.parse(existing.lastSeenAt || 0);
        const identityChanged =
          existing.rowKey !== rowKey ||
          existing.rowIndexHint !== snapshotRow.index ||
          existing.rowStartHint !== snapshotRow.start;
        existing.rowKey = rowKey;
        existing.bubbleIds = _bubbleIdsFromRow(row);
        existing.rowIndexHint = snapshotRow.index;
        existing.rowStartHint = snapshotRow.start;
        existing.title = title;
        existing.status = nextStatus;
        existing.lastSeenAt = now;
        if (progressChanged) existing.lastProgressAt = now;
        if (nextStatus !== "failed") existing.failure = null;
        if (previousStatus !== nextStatus) {
          _queueEvent({
            type: "subagent_status",
            taskKey,
            rowKey,
            from: previousStatus,
            status: nextStatus,
          });
        }
        if (progressChanged || identityChanged || lastSeenAge >= 5000) {
          changed = true;
        }
      }
    }

    if (changed) {
      _persistSubagentRegistry();
      if (state.running && state.cycleEnabled) {
        _scheduleSubagentCycle(discovered > 0 ? 100 : 1000);
      }
    }
    return discovered;
  }

  function _recordUserInteraction(event) {
    if (state.programmaticScrollDepth > 0 || event?.isTrusted === false) return;
    state.lastUserInteractionAt = Date.now();
    state.lastUserInteractionType = event?.type || "unknown";
    state.interactionGeneration++;
    const focusTarget = _focusTargetFromInteraction(event);
    if (focusTarget) {
      state.lastUserFocusElement = focusTarget;
      state.lastUserFocusGeneration = state.interactionGeneration;
    }
  }

  function _focusTargetFromInteraction(event) {
    const target = event?.target instanceof Element ? event.target : null;
    if (!target || !["pointerdown", "keydown"].includes(event.type)) return null;
    if (
      target.matches(
        'input, textarea, select, [contenteditable="true"], [role="textbox"]'
      )
    ) {
      return target;
    }
    const terminal = target.closest(".terminal-instance, .xterm");
    if (terminal) {
      return terminal.querySelector("textarea.xterm-helper-textarea");
    }
    const editor = target.closest(".monaco-editor");
    if (editor) {
      return editor.querySelector("textarea.inputarea");
    }
    return null;
  }

  function _setupInteractionGuard() {
    if (state.interactionGuardInstalled) return;
    for (const type of ["pointerdown", "keydown", "wheel", "scroll"]) {
      document.addEventListener(type, _recordUserInteraction, true);
    }
    state.interactionGuardInstalled = true;
  }

  function _composerHasUnsentText() {
    const inputBoxes = document.querySelectorAll("div.full-input-box");
    for (const inputBox of inputBoxes) {
      if (_inputBoxHasUnsentText(inputBox)) return true;
    }
    return false;
  }

  function _inputBoxHasUnsentText(inputBox) {
    const editable =
      inputBox.querySelector('[contenteditable="true"]') ||
      (inputBox.matches?.('[contenteditable="true"]') ? inputBox : null);
    if (!editable) return false;
    return String(editable.innerText || editable.textContent || "").trim().length > 0;
  }

  function _hasUnrelatedVisibleModal(row = null) {
    for (const modal of document.querySelectorAll(PROMPT_ROOT_SELECTORS.join(", "))) {
      if (!isVisible(modal)) continue;
      if (row && (row.contains(modal) || modal.contains(row))) continue;
      return true;
    }
    return false;
  }

  function _activeEditingSurfaceBlockReason() {
    const active = document.activeElement;
    if (!active || active === document.body || !(active instanceof Element)) {
      return null;
    }
    if (
      active.matches("textarea.xterm-helper-textarea") ||
      active.closest(".terminal-instance, .xterm")
    ) {
      return "terminal_focused";
    }
    const editable = active.matches(
      'input, textarea, select, [contenteditable="true"], [role="textbox"]'
    );
    const composerEditable = active.closest(
      "div.full-input-box, .composer-input-blur-wrapper"
    );
    return editable && !composerEditable ? "editor_focused" : null;
  }

  function _cycleBlockReason(explicit) {
    if (!state.running) return "gate_off";
    if (_composerHasUnsentText()) return "unsent_composer_text";
    if (_hasUnrelatedVisibleModal()) return "unrelated_modal";
    if (!explicit && document.hasFocus()) {
      const focusReason = _activeEditingSurfaceBlockReason();
      if (focusReason) return focusReason;
      if (Date.now() - state.lastUserInteractionAt < CYCLE_INTERACTION_GUARD_MS) {
        return `recent_${state.lastUserInteractionType || "interaction"}`;
      }
    }
    return null;
  }

  function _scrollContainer(records = []) {
    const taskContainers = new Set();
    for (const record of records) {
      const container = _findExactRow(record.rowKey)?.closest(SCROLL_CONTAINER_SELECTOR);
      if (container) taskContainers.add(container);
    }
    if (taskContainers.size === 1) return Array.from(taskContainers)[0];
    const containers = Array.from(document.querySelectorAll(SCROLL_CONTAINER_SELECTOR));
    if (containers.length !== 1) return null;
    return containers[0];
  }

  function _captureScrollContext(container) {
    const scrollHeight = container.scrollHeight;
    const viewportHeight = container.clientHeight;
    const scrollTop = container.scrollTop;
    const distanceFromBottom = Math.max(0, scrollHeight - viewportHeight - scrollTop);
    return {
      container,
      scrollTop,
      scrollHeight,
      viewportHeight,
      distanceFromBottom,
      wasNearBottom: distanceFromBottom <= 80,
      focusedElement: document.activeElement,
      interactionGeneration: state.interactionGeneration,
      autoFollowChanged: false,
    };
  }

  function _setProgrammaticScroll(container, top) {
    state.programmaticScrollDepth++;
    try {
      container.scrollTop = Math.max(0, top);
      container.dispatchEvent(new Event("scroll", { bubbles: true }));
    } finally {
      requestAnimationFrame(() => {
        state.programmaticScrollDepth = Math.max(0, state.programmaticScrollDepth - 1);
      });
    }
  }

  function _waitForExactRow(rowKey, timeoutMs = CYCLE_MOUNT_TIMEOUT_MS) {
    return new Promise((resolve) => {
      let finished = false;
      let timer = null;
      let observer = null;
      const finish = (row) => {
        if (finished) return;
        finished = true;
        if (timer) clearTimeout(timer);
        if (observer) observer.disconnect();
        resolve(row || null);
      };
      const check = () => {
        const row = _findExactRow(rowKey);
        if (row) finish(row);
      };
      observer = new MutationObserver(check);
      observer.observe(document.body, { childList: true, subtree: true });
      requestAnimationFrame(() => requestAnimationFrame(check));
      timer = setTimeout(() => finish(_findExactRow(rowKey)), timeoutMs);
      check();
    });
  }

  async function _materializeSubagentRow(record, context) {
    let row = _findExactRow(record.rowKey);
    const virtualizer = _getVirtualizerSnapshot();
    if (!virtualizer.ok) {
      return { row: null, reason: virtualizer.reason };
    }
    const snapshot = virtualizer.snapshot;
    if (snapshot.composerId !== record.parentComposerId) {
      return { row: null, reason: "composer_identity_changed" };
    }
    const snapshotRow = _findSnapshotRow(snapshot, record.rowKey);
    if (!snapshotRow) {
      return { row: null, reason: "row_identity_missing" };
    }
    record.rowIndexHint = snapshotRow.index;
    record.rowStartHint = snapshotRow.start;

    const viewportHeight = context.container.clientHeight || snapshot.viewportHeight;
    if (!Number.isFinite(viewportHeight) || viewportHeight <= 0) {
      return { row: null, reason: "hidden_or_zero_height_viewport" };
    }
    const targetTop = Math.max(0, snapshotRow.start - viewportHeight * 0.3);
    if (!row || !_rowInsideViewport(row, context.container)) {
      _setProgrammaticScroll(context.container, targetTop);
      row = await _waitForExactRow(record.rowKey);
    }
    if (!row || row.getAttribute("data-find-row-key") !== record.rowKey) {
      return { row: null, reason: "row_did_not_mount" };
    }
    _queueEvent({
      type: "row_materialized",
      taskKey: record.taskKey,
      rowKey: record.rowKey,
      rowIndexHint: record.rowIndexHint,
      rowStartHint: record.rowStartHint,
    });
    return { row, reason: null };
  }

  function _rowInsideViewport(row, container) {
    const rowRect = row.getBoundingClientRect();
    const viewportRect = container.getBoundingClientRect();
    return (
      rowRect.height > 0 &&
      viewportRect.height > 0 &&
      rowRect.bottom > viewportRect.top &&
      rowRect.top < viewportRect.bottom
    );
  }

  function _notCoveredByUnrelatedElement(el) {
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    const x = Math.min(window.innerWidth - 1, Math.max(0, rect.left + rect.width / 2));
    const y = Math.min(window.innerHeight - 1, Math.max(0, rect.top + rect.height / 2));
    const hit = document.elementFromPoint(x, y);
    return !hit || hit === el || el.contains(hit) || hit.contains(el);
  }

  function _scopedCycleCandidate(record, row, bypassCooldown = false) {
    const container = row.closest(SCROLL_CONTAINER_SELECTOR);
    if (
      !container ||
      !ACTIVE_SUBAGENT_STATUSES.has(record.status) ||
      row.getAttribute("data-find-row-key") !== record.rowKey ||
      _taskForRow(row)?.taskKey !== record.taskKey ||
      _hasUnrelatedVisibleModal(row)
    ) {
      return null;
    }
    const candidates = _rowCandidatesFromRoot(row)
      .map((candidate) => ({
        ...candidate,
        reason: _eligibilityReason(candidate),
      }))
      .filter((candidate) => candidate.reason !== null)
      .filter((candidate) => _rowInsideViewport(candidate.el, container))
      .filter((candidate) => _notCoveredByUnrelatedElement(candidate.el));
    if (candidates.length === 0) return null;
    const candidate = candidates[0];
    candidate.fingerprint = [
      record.taskKey,
      record.rowKey,
      candidate.id,
      normalizeLabel(candidate.text),
    ].join("|");
    if (!bypassCooldown && _isCoolingDown(candidate.fingerprint)) return null;
    return candidate;
  }

  function _sameApprovalStillPresent(record, row, candidate) {
    if (!row || row.getAttribute("data-find-row-key") !== record.rowKey) return false;
    return _rowCandidatesFromRoot(row).some(
      (next) =>
        next.id === candidate.id &&
        normalizeLabel(next.text) === normalizeLabel(candidate.text)
    );
  }

  async function _confirmCycleApproval(record, candidate, context) {
    for (const delay of CYCLE_CONFIRM_DELAYS_MS) {
      await new Promise((resolve) => setTimeout(resolve, delay));
      if (!state.running) return { confirmed: false, reason: "gate_off" };
      let row = _findExactRow(record.rowKey);
      if (!row) {
        const remounted = await _materializeSubagentRow(record, context);
        row = remounted.row;
      }
      if (!row) continue;
      const nextStatus = _deriveTaskStatus(row, record.status);
      const candidateGone = !_sameApprovalStillPresent(record, row, candidate);
      const statusAdvanced = !["approval_pending", "approval_attempted"].includes(nextStatus);
      if (candidateGone || statusAdvanced) {
        return { confirmed: true, status: nextStatus, reason: candidateGone ? "candidate_gone" : "status_advanced" };
      }
    }
    return { confirmed: false, reason: "unconfirmed_click" };
  }

  function _pushRecentConfirmedClick(candidate, command, source = "cycle") {
    const entry = {
      ts: new Date().toISOString(),
      kind: candidate.kind || "approval",
      id: candidate.id,
      text: candidate.text,
      reason: `${source}:${candidate.reason}`,
      fingerprint: candidate.fingerprint,
      confirmed: true,
      commandPreview: command ? command.preview : null,
      commandLines: command ? command.lineCount : null,
    };
    state.clicks.push(entry);
    if (state.clicks.length > 100) state.clicks = state.clicks.slice(-100);
  }

  async function _attemptSubagentApproval(record, context, retry = false) {
    const materialized = await _materializeSubagentRow(record, context);
    if (!materialized.row) {
      _queueEvent({
        type: "cycle_miss",
        taskKey: record.taskKey,
        rowKey: record.rowKey,
        reason: materialized.reason,
      });
      return { outcome: "miss", reason: materialized.reason };
    }
    const row = _findExactRow(record.rowKey);
    const candidate = row ? _scopedCycleCandidate(record, row, retry) : null;
    if (!candidate) {
      if (row) {
        record.status = _deriveTaskStatus(row, record.status);
        record.lastSeenAt = new Date().toISOString();
      }
      _queueEvent({
        type: "cycle_miss",
        taskKey: record.taskKey,
        rowKey: record.rowKey,
        reason: "no_eligible_candidate",
      });
      return { outcome: "no_candidate", reason: "no_eligible_candidate" };
    }

    const command = _extractCommandText(candidate.el);
    const prompt = _capturePromptSubtree(candidate.el);
    const now = new Date().toISOString();
    record.status = "approval_attempted";
    record.lastAttemptAt = now;
    record.attempts += 1;
    record.failure = null;
    state.totalClicks++;
    state.totalClickAttempts++;
    clickEl(candidate.el);
    _markClicked(candidate.fingerprint);
    _queueEvent({
      type: "approval_attempted",
      taskKey: record.taskKey,
      toolUseId: record.toolUseId,
      rowKey: record.rowKey,
      pattern_id: candidate.id,
      text: candidate.text,
      reason: candidate.reason,
      fingerprint: candidate.fingerprint,
      retry,
      prompt,
      command,
    });
    _persistSubagentRegistry();

    const confirmation = await _confirmCycleApproval(record, candidate, context);
    if (confirmation.confirmed) {
      record.status = ["completed", "failed"].includes(confirmation.status)
        ? confirmation.status
        : "approved";
      record.confirmedAt = new Date().toISOString();
      record.lastProgressAt = record.confirmedAt;
      record.failure = null;
      state.totalConfirmedApprovals++;
      _pushRecentConfirmedClick(candidate, command);
      _queueEvent({
        type: "approval_confirmed",
        taskKey: record.taskKey,
        toolUseId: record.toolUseId,
        rowKey: record.rowKey,
        pattern_id: candidate.id,
        text: candidate.text,
        reason: confirmation.reason,
        eligibility_reason: candidate.reason,
        fingerprint: candidate.fingerprint,
        prompt,
        command,
      });
      _persistSubagentRegistry();
      return { outcome: "confirmed", reason: confirmation.reason };
    }

    _queueEvent({
      type: "approval_unconfirmed",
      taskKey: record.taskKey,
      rowKey: record.rowKey,
      pattern_id: candidate.id,
      fingerprint: candidate.fingerprint,
      retry,
      reason: confirmation.reason,
    });
    return { outcome: "unconfirmed", reason: confirmation.reason };
  }

  function _restoreScrollContext(context) {
    const container = context.container;
    const beforeRestore = container.scrollTop;
    const target = context.wasNearBottom
      ? Math.max(0, container.scrollHeight - container.clientHeight)
      : Math.min(context.scrollTop, Math.max(0, container.scrollHeight - container.clientHeight));
    context.autoFollowChanged = Math.abs(beforeRestore - target) > 2;
    _setProgrammaticScroll(container, target);
  }

  function _activeSubagentRecords() {
    const records = Array.from(state.subagents.values()).filter((record) =>
      ACTIVE_SUBAGENT_STATUSES.has(record.status)
    );
    records.sort((a, b) => {
      const pendingA = a.status === "approval_pending" ? 0 : 1;
      const pendingB = b.status === "approval_pending" ? 0 : 1;
      if (pendingA !== pendingB) return pendingA - pendingB;
      return String(a.lastAttemptAt || "").localeCompare(String(b.lastAttemptAt || ""));
    });
    if (records.length <= CYCLE_MAX_TASKS) return records;
    const start = state.cycleCursor % records.length;
    const rotated = records.slice(start).concat(records.slice(0, start));
    state.cycleCursor = (start + CYCLE_MAX_TASKS) % records.length;
    return rotated.slice(0, CYCLE_MAX_TASKS);
  }

  function _runningSubagentTrayEntries(options = {}) {
    const entries = [];
    const seen = new Set();
    const labels = document.querySelectorAll(".composer-toolbar-section-header-label");
    for (const label of labels) {
      const headerText = String(label.innerText || label.textContent || "")
        .trim()
        .replace(/\s+/g, " ");
      if (!SUBAGENT_TRAY_HEADER_PATTERN.test(headerText)) continue;
      const header = label.closest(".composer-toolbar-section-header");
      const block = header?.parentElement?.parentElement;
      if (!header || !block || !isVisible(header)) continue;
      for (const item of block.querySelectorAll(SUBAGENT_TRAY_ITEM_SELECTOR)) {
        if (seen.has(item) || !item.isConnected || !isClickable(item)) continue;
        const titleNode = item.querySelector(SUBAGENT_TRAY_TITLE_SELECTOR);
        const title = String(titleNode?.innerText || titleNode?.textContent || "")
          .trim()
          .replace(/\s+/g, " ")
          .slice(0, 120);
        if (!title) continue;
        seen.add(item);
        entries.push({ item, title, headerText });
      }
    }
    if (options.bounded === false || entries.length <= CYCLE_MAX_TRAY_ITEMS) {
      return entries;
    }
    const start = state.trayCursor % entries.length;
    const rotated = entries.slice(start).concat(entries.slice(0, start));
    state.trayCursor = (start + CYCLE_MAX_TRAY_ITEMS) % entries.length;
    return rotated.slice(0, CYCLE_MAX_TRAY_ITEMS);
  }

  function _selectedEditorTab(group) {
    if (!group) return null;
    return (
      group.querySelector('[role="tab"][aria-selected="true"]') ||
      group.querySelector('[role="tab"].active.selected')
    );
  }

  function _captureEditorSelectionContext() {
    const selections = [];
    for (const group of document.querySelectorAll(".editor-group-container")) {
      const tab = _selectedEditorTab(group);
      if (tab) selections.push({ group, tab });
    }
    const focusedElement = document.activeElement;
    return {
      selections,
      focusedElement,
      interactionGeneration: state.interactionGeneration,
      focusedGroup: focusedElement?.closest?.(".editor-group-container") || null,
    };
  }

  function _activateEditorTab(tab) {
    const rect = tab.getBoundingClientRect();
    const options = {
      bubbles: true,
      cancelable: true,
      view: window,
      button: 0,
      buttons: 1,
      clientX: rect.left + rect.width / 2,
      clientY: rect.top + rect.height / 2,
    };
    tab.dispatchEvent(new MouseEvent("mousedown", options));
    tab.dispatchEvent(new MouseEvent("mouseup", { ...options, buttons: 0 }));
    if (typeof tab.click === "function") tab.click();
  }

  function _restoreEditorSelectionContext(context) {
    if (!context) return;
    const ordered = context.selections
      .filter(({ group, tab }) => group.isConnected && tab.isConnected)
      .sort((a, b) =>
        a.group === context.focusedGroup ? 1 : b.group === context.focusedGroup ? -1 : 0
      );
    for (const { group, tab } of ordered) {
      if (_selectedEditorTab(group) !== tab) _activateEditorTab(tab);
    }
  }

  function _focusKind(element) {
    if (!element || !(element instanceof Element)) return "none";
    if (
      element.matches("textarea.xterm-helper-textarea") ||
      element.closest(".terminal-instance, .xterm")
    ) {
      return "terminal";
    }
    if (element.closest("div.full-input-box, .composer-input-blur-wrapper")) {
      return "composer";
    }
    if (
      element.matches(
        'input, textarea, select, [contenteditable="true"], [role="textbox"]'
      )
    ) {
      return "editor";
    }
    return "other";
  }

  function _focusTargetForContext(context) {
    if (!context) return null;
    if (state.interactionGeneration === context.interactionGeneration) {
      return context.focusedElement;
    }
    if (state.lastUserFocusGeneration > context.interactionGeneration) {
      return state.lastUserFocusElement;
    }
    return null;
  }

  function _settleFocusAfterAutomation(context, source) {
    if (!context) return;
    const restoreGeneration = ++state.focusRestoreGeneration;
    const attempt = (phase) => {
      if (restoreGeneration !== state.focusRestoreGeneration) return;
      const target = _focusTargetForContext(context);
      if (
        !target ||
        target === document.body ||
        !target.isConnected ||
        typeof target.focus !== "function"
      ) {
        state.lastFocusRestore = {
          ts: new Date().toISOString(),
          source,
          phase,
          outcome:
            state.interactionGeneration === context.interactionGeneration
              ? "target_unavailable"
              : "preserved_new_user_interaction",
          targetKind: _focusKind(target),
        };
        return;
      }
      const neededRestore = document.activeElement !== target;
      if (neededRestore) {
        try {
          target.focus({ preventScroll: true });
        } catch (_) {}
      }
      const restored = document.activeElement === target;
      state.lastFocusRestore = {
        ts: new Date().toISOString(),
        source,
        phase,
        outcome: restored
          ? neededRestore
            ? "restored"
            : "already_preserved"
          : "restore_failed",
        targetKind: _focusKind(target),
        interactionChanged:
          state.interactionGeneration !== context.interactionGeneration,
      };
      if (phase === "delayed" && neededRestore && restored) {
        _queueEvent({
          type: "focus_restored",
          source,
          targetKind: _focusKind(target),
          interactionChanged:
            state.interactionGeneration !== context.interactionGeneration,
        });
      }
    };
    attempt("immediate");
    setTimeout(() => attempt("delayed"), FOCUS_SETTLE_DELAY_MS);
  }

  async function _waitForSelectedSubagentGroup(title) {
    const wanted = normalizeLabel(title);
    const deadline = performance.now() + CYCLE_TRAY_MOUNT_TIMEOUT_MS;
    while (performance.now() <= deadline) {
      const matches = [];
      for (const group of document.querySelectorAll(".editor-group-container")) {
        const tab = _selectedEditorTab(group);
        const tabText = String(tab?.innerText || tab?.textContent || "")
          .trim()
          .replace(/\s+/g, " ");
        if (
          tab &&
          normalizeLabel(tabText) === wanted &&
          group.querySelector("div.conversations")
        ) {
          matches.push({ group, tab });
        }
      }
      if (matches.length === 1) {
        const { group, tab } = matches[0];
        return {
          group,
          tab,
          targetKey:
            tab.getAttribute("data-resource-name") ||
            tab.getAttribute("data-resource-id") ||
            title,
        };
      }
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    return null;
  }

  function _trayEligibilityReason(candidate, group) {
    if (!candidate?.el || !group?.contains(candidate.el)) return null;
    if (_hasUnrelatedVisibleModal(group)) return null;
    if (isDeleteFileChangeApprove(candidate)) return "delete_file_change";
    if (candidate.kind === "resume") return "resume";
    if (hasNearbyDismissal(candidate.el, { allowExcluded: true })) return "dismiss";
    if (hasNearbyCompanion(candidate.el, { allowExcluded: true })) return "companion";
    if (isModalSingleActionApprove(candidate, { allowExcluded: true })) return "modal";
    return null;
  }

  function _trayApprovalMatches(group) {
    const candidates = [];
    const seen = new Set();
    for (const selector of BUTTON_SELECTORS) {
      for (const el of group.querySelectorAll(selector)) {
        if (seen.has(el)) continue;
        seen.add(el);
        const match = matchesApproval(el, { allowExcluded: true });
        if (match) candidates.push({ el, kind: "approval", ...match });
      }
    }
    return candidates;
  }

  function _trayCandidates(group, targetKey) {
    const candidates = _trayApprovalMatches(group)
      .map((candidate) => ({
        ...candidate,
        reason: _trayEligibilityReason(candidate, group),
      }))
      .filter((candidate) => candidate.reason !== null)
      .filter((candidate) => _notCoveredByUnrelatedElement(candidate.el));
    for (const candidate of candidates) {
      candidate.fingerprint = [
        "tray",
        state.workspace,
        targetKey,
        _promptFingerprint(candidate.el),
      ].join("|");
    }
    return candidates;
  }

  function _waitForTrayCandidates(target) {
    return new Promise((resolve) => {
      const startedAt = performance.now();
      let lastMutationAt = startedAt;
      let finished = false;
      let observer = null;
      let timer = null;

      const finish = (candidates, reason) => {
        if (finished) return;
        finished = true;
        if (timer) clearTimeout(timer);
        if (observer) observer.disconnect();
        resolve({
          candidates,
          reason,
          waitedMs: Math.round(performance.now() - startedAt),
        });
      };

      const check = () => {
        if (finished) return;
        if (timer) {
          clearTimeout(timer);
          timer = null;
        }
        if (
          !target.group?.isConnected ||
          !target.tab?.isConnected ||
          _selectedEditorTab(target.group) !== target.tab
        ) {
          finish([], "selected_subagent_changed");
          return;
        }

        const candidates = _trayCandidates(target.group, target.targetKey);
        if (candidates.length > 0) {
          finish(candidates, null);
          return;
        }

        const now = performance.now();
        const elapsed = now - startedAt;
        if (elapsed >= CYCLE_TRAY_CANDIDATE_TIMEOUT_MS) {
          finish([], "candidate_mount_timeout");
          return;
        }
        if (
          elapsed >= CYCLE_TRAY_MIN_CANDIDATE_WAIT_MS &&
          now - lastMutationAt >= CYCLE_TRAY_QUIET_MS
        ) {
          finish([], "no_eligible_candidate");
          return;
        }
        timer = setTimeout(check, 50);
      };

      observer = new MutationObserver(() => {
        lastMutationAt = performance.now();
        check();
      });
      observer.observe(target.group, {
        childList: true,
        subtree: true,
        characterData: true,
        attributes: true,
        attributeFilter: ["class", "disabled", "aria-disabled"],
      });
      check();
    });
  }

  function _sameTrayApprovalStillPresent(group, candidate) {
    if (!group?.isConnected) return false;
    return _trayCandidates(group, candidate.targetKey).some(
      (next) =>
        next.id === candidate.id &&
        normalizeLabel(next.text) === normalizeLabel(candidate.text)
    );
  }

  async function _attemptTrayApproval(target) {
    const waitResult = await _waitForTrayCandidates(target);
    if (waitResult.candidates.length === 0) {
      const approvalControls = target.group?.isConnected
        ? _trayApprovalMatches(target.group).length
        : 0;
      _queueEvent({
        type: "tray_no_candidate",
        targetKey: target.targetKey,
        title: target.title,
        reason: waitResult.reason,
        waitedMs: waitResult.waitedMs,
        approvalControls,
      });
      return {
        outcome:
          waitResult.reason === "selected_subagent_changed"
            ? "miss"
            : "no_candidate",
        reason: waitResult.reason,
      };
    }
    const candidate = waitResult.candidates[0];
    candidate.targetKey = target.targetKey;
    const previous = state.trayApprovalAttempts.get(candidate.fingerprint) || {
      attempts: 0,
      failed: false,
      targetKey: target.targetKey,
    };
    if (previous.failed || previous.attempts >= CYCLE_TRAY_MAX_ATTEMPTS) {
      previous.failed = true;
      state.trayApprovalAttempts.set(candidate.fingerprint, previous);
      return { outcome: "failed", reason: "tray_retry_exhausted" };
    }
    if (_isCoolingDown(candidate.fingerprint)) {
      return { outcome: "cooldown" };
    }

    const command = _extractCommandText(candidate.el);
    const prompt = _capturePromptSubtree(candidate.el);
    previous.attempts += 1;
    previous.lastAttemptAt = new Date().toISOString();
    state.trayApprovalAttempts.set(candidate.fingerprint, previous);
    if (state.trayApprovalAttempts.size > 100) {
      state.trayApprovalAttempts.delete(state.trayApprovalAttempts.keys().next().value);
    }
    state.totalClicks++;
    state.totalClickAttempts++;
    state.totalTrayApprovalAttempts++;
    clickEl(candidate.el);
    _markClicked(candidate.fingerprint);
    _queueEvent({
      type: "tray_approval_attempted",
      targetKey: target.targetKey,
      title: target.title,
      pattern_id: candidate.id,
      text: candidate.text,
      reason: candidate.reason,
      fingerprint: candidate.fingerprint,
      attempt: previous.attempts,
      prompt,
      command,
    });

    for (const delay of CYCLE_TRAY_CONFIRM_DELAYS_MS) {
      await new Promise((resolve) => setTimeout(resolve, delay));
      if (!state.running) return { outcome: "unconfirmed", reason: "gate_off" };
      if (!_sameTrayApprovalStillPresent(target.group, candidate)) {
        state.trayApprovalAttempts.delete(candidate.fingerprint);
        state.totalConfirmedApprovals++;
        state.totalTrayConfirmedApprovals++;
        _pushRecentConfirmedClick(candidate, command, "tray");
        _queueEvent({
          type: "tray_approval_confirmed",
          targetKey: target.targetKey,
          title: target.title,
          pattern_id: candidate.id,
          text: candidate.text,
          reason: "candidate_gone",
          eligibility_reason: candidate.reason,
          fingerprint: candidate.fingerprint,
          prompt,
          command,
        });
        return { outcome: "confirmed", reason: "candidate_gone" };
      }
    }

    previous.failed = previous.attempts >= CYCLE_TRAY_MAX_ATTEMPTS;
    state.trayApprovalAttempts.set(candidate.fingerprint, previous);
    _queueEvent({
      type: "tray_approval_unconfirmed",
      targetKey: target.targetKey,
      title: target.title,
      pattern_id: candidate.id,
      fingerprint: candidate.fingerprint,
      attempt: previous.attempts,
      failed: previous.failed,
      reason: "unconfirmed_click",
    });
    return {
      outcome: previous.failed ? "failed" : "unconfirmed",
      reason: "unconfirmed_click",
    };
  }

  async function _visitSubagentTrayEntry(entry) {
    if (!entry.item.isConnected) {
      return { outcome: "miss", reason: "tray_item_disconnected" };
    }
    _queueEvent({
      type: "tray_visit",
      title: entry.title,
      header: entry.headerText,
    });
    state.totalTrayVisits++;
    clickEl(entry.item);
    const selected = await _waitForSelectedSubagentGroup(entry.title);
    if (!selected) {
      _queueEvent({
        type: "tray_visit_miss",
        title: entry.title,
        reason: "selected_subagent_not_mounted",
      });
      return { outcome: "miss", reason: "selected_subagent_not_mounted" };
    }
    return _attemptTrayApproval({ ...selected, title: entry.title });
  }

  function _scheduleSubagentCycle(delayMs = CYCLE_AUTOMATIC_INTERVAL_MS) {
    if (!state.running || !state.cycleEnabled || state.cycleActive) return;
    if (state.cycleTimer) clearTimeout(state.cycleTimer);
    state.cycleTimer = setTimeout(() => {
      state.cycleTimer = null;
      runSubagentCycle({ explicit: false }).catch((e) => {
        console.log(`${LOG_PREFIX} subagent cycle error:`, e.message);
      });
    }, Math.max(50, delayMs));
  }

  async function runSubagentCycle(options = {}) {
    const explicit = options.explicit === true;
    if (state.cycleActive) {
      return { ok: false, reason: "cycle_already_active", lastCycle: state.lastCycle };
    }
    if (!explicit && !state.cycleEnabled) {
      return { ok: false, reason: "cycle_disabled" };
    }
    const blocked = _cycleBlockReason(explicit);
    if (blocked) {
      if (!explicit && state.cycleEnabled) _scheduleSubagentCycle(1000);
      return { ok: false, reason: blocked };
    }

    _getVirtualizerSnapshot(true);
    _discoverSubagentRows(document);
    const records = _activeSubagentRecords();
    const trayEntries = _runningSubagentTrayEntries();
    if (records.length === 0 && trayEntries.length === 0) {
      const result = {
        ok: true,
        rows: 0,
        confirmed: 0,
        failed: 0,
        misses: 0,
        trayVisits: 0,
        trayConfirmed: 0,
        trayFailed: 0,
        trayMisses: 0,
      };
      state.lastCycle = { ...result, ts: new Date().toISOString() };
      if (state.running && state.cycleEnabled) {
        _scheduleSubagentCycle(CYCLE_AUTOMATIC_INTERVAL_MS);
      }
      return result;
    }

    const container = records.length > 0 ? _scrollContainer(records) : null;
    const context = container ? _captureScrollContext(container) : null;
    const editorContext =
      trayEntries.length > 0 ? _captureEditorSelectionContext() : null;
    const generation = ++state.cycleGeneration;
    state.cycleActive = true;
    const startedAt = new Date().toISOString();
    const startedPerformance = performance.now();
    const summary = {
      ok: true,
      rows: 0,
      confirmed: 0,
      failed: 0,
      misses: 0,
      trayVisits: 0,
      trayConfirmed: 0,
      trayFailed: 0,
      trayMisses: 0,
    };
    _queueEvent({
      type: "cycle_started",
      explicit,
      taskCount: records.length,
      trayTaskCount: trayEntries.length,
      composerId: records[0]?.parentComposerId || null,
    });

    try {
      // Give the backup navigation path a chance before row confirmation can
      // consume the shared cycle budget. The normal mounted-composer scanner
      // remains active independently at the fallback poll cadence.
      for (const entry of trayEntries) {
        if (
          performance.now() - startedPerformance > CYCLE_MAX_DURATION_MS ||
          !state.running ||
          generation !== state.cycleGeneration
        ) {
          break;
        }
        summary.trayVisits++;
        const result = await _visitSubagentTrayEntry(entry);
        if (result.outcome === "confirmed") summary.trayConfirmed++;
        if (result.outcome === "failed") summary.trayFailed++;
        if (result.outcome === "miss") summary.trayMisses++;
      }

      if (!context && records.length > 0) {
        summary.misses += records.length;
        _queueEvent({
          type: "cycle_miss",
          reason: "ambiguous_scroll_container",
          taskCount: records.length,
        });
      } else if (context) {
        for (const record of records) {
          if (performance.now() - startedPerformance > CYCLE_MAX_DURATION_MS) {
            summary.misses++;
            break;
          }
          if (!state.running || generation !== state.cycleGeneration) break;
          summary.rows++;
          let result = await _attemptSubagentApproval(record, context, false);
          if (result.outcome === "unconfirmed" && state.running) {
            await new Promise((resolve) => setTimeout(resolve, 250));
            result = await _attemptSubagentApproval(record, context, true);
            if (result.outcome === "unconfirmed") {
              record.status = "failed";
              record.failure = "unconfirmed_click";
              summary.failed++;
            }
          }
          if (result.outcome === "confirmed") summary.confirmed++;
          if (result.outcome === "miss") summary.misses++;
        }
      }
    } finally {
      if (context?.container?.isConnected) _restoreScrollContext(context);
      _restoreEditorSelectionContext(editorContext);
      _settleFocusAfterAutomation(editorContext || context, "subagent_cycle");
      state.cycleActive = false;
      state.lastCycle = {
        ...summary,
        ts: new Date().toISOString(),
        startedAt,
        autoFollowChanged: context?.autoFollowChanged || false,
        restoredScrollTop: context?.container?.isConnected
          ? context.container.scrollTop
          : null,
      };
      _persistSubagentRegistry();
      _queueEvent({
        type: "cycle_finished",
        ...state.lastCycle,
      });
      if (state.running && state.cycleEnabled) {
        const needsSoonerRetry =
          summary.failed > 0 ||
          summary.misses > 0 ||
          summary.trayFailed > 0 ||
          summary.trayMisses > 0;
        _scheduleSubagentCycle(
          needsSoonerRetry ? 2000 : CYCLE_AUTOMATIC_INTERVAL_MS
        );
      }
    }
    return state.lastCycle;
  }

  function setSubagentCycle(enabled) {
    state.cycleEnabled = Boolean(enabled);
    if (!state.cycleEnabled && state.cycleTimer) {
      clearTimeout(state.cycleTimer);
      state.cycleTimer = null;
    }
    if (!state.cycleEnabled) state.cycleGeneration++;
    _persistSubagentRegistry();
    if (state.cycleEnabled && state.running) _scheduleSubagentCycle(50);
    return exportSubagentRegistry();
  }

  function exportSubagentRegistry() {
    const tasks = Array.from(state.subagents.values()).map(_sanitizeSubagentRecord);
    const trayEntries = _runningSubagentTrayEntries({ bounded: false });
    const trayAttempts = Array.from(state.trayApprovalAttempts.values());
    const counts = {
      active: tasks.filter((task) => ACTIVE_SUBAGENT_STATUSES.has(task.status)).length,
      waiting: tasks.filter((task) => task.status === "approval_pending").length,
      completed: tasks.filter((task) => task.status === "completed").length,
      failed: tasks.filter((task) => task.status === "failed").length,
      stale: tasks.filter((task) => task.status === "stale").length,
    };
    const virtualizer = _getVirtualizerSnapshot();
    return {
      version: SUBAGENT_STORAGE_VERSION,
      scriptHash: state.scriptHash,
      workspace: state.workspace,
      targetId: state.targetId,
      cycleEnabled: state.cycleEnabled,
      cycleActive: state.cycleActive,
      counts,
      tray: {
        running: trayEntries.length,
        visits: state.totalTrayVisits,
        attempts: state.totalTrayApprovalAttempts,
        confirmed: state.totalTrayConfirmedApprovals,
        failed: trayAttempts.filter((entry) => entry.failed).length,
      },
      lastCycle: state.lastCycle,
      virtualizer: virtualizer.ok
        ? {
            engine: virtualizer.engine,
            composerId: virtualizer.snapshot.composerId,
            rowCount: virtualizer.snapshot.rowCount,
            totalSize: virtualizer.snapshot.totalSize,
            viewportHeight: virtualizer.snapshot.viewportHeight,
            isAtBottom: virtualizer.snapshot.isAtBottom,
          }
        : { error: virtualizer.reason },
      tasks,
      exportedAt: new Date().toISOString(),
    };
  }

  // -----------------------------------------------------------------------
  // DOM helpers (shared by discovery and policy)
  // -----------------------------------------------------------------------

  function isVisible(el) {
    const s = window.getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return (
      s.display !== "none" &&
      s.visibility !== "hidden" &&
      parseFloat(s.opacity) > 0.1 &&
      r.width > 0 &&
      r.height > 0
    );
  }

  function isClickable(el) {
    const s = window.getComputedStyle(el);
    return s.pointerEvents !== "none" && !el.disabled;
  }

  function isInExcludedZone(el) {
    for (const sel of EXCLUDED_ZONES) {
      const zone = el.closest(sel);
      if (zone) {
        if (zone.querySelector("div.full-input-box")) return false;
        return true;
      }
    }
    return false;
  }

  function stripKeyboardHints(text) {
    let stripped = text
      .replace(/\s*\([⌃⌥⇧⌘⎋⏎↩\s\w]{1,6}\)\s*$/, "")
      .replace(/[\s\u21A9\u23CE\u21E7\u2318\u2325\u238B\u232B\u2326\u21E5]+$/, "")
      .trim();
    // Strip trailing "Esc"/"Escape" keyboard hint suffix.
    // Cursor renders this as adjacent spans so textContent may be "SkipEsc"
    // (no whitespace) or "Skip Esc" (with whitespace). Require at least 2
    // preceding chars so standalone "Esc" is not hollowed out.
    stripped = stripped.replace(/(.{2,}?)\s*(?:esc|escape)$/i, "$1").trim();
    return stripped;
  }

  function normalizeLabel(text) {
    return stripKeyboardHints(text.toLowerCase().trim());
  }

  // -----------------------------------------------------------------------
  // Prompt fingerprinting (dedupe layer)
  // -----------------------------------------------------------------------

  function _promptFingerprint(el) {
    const root = el.closest(PROMPT_ROOT_SELECTORS.join(", ")) || el.parentElement;
    if (!root) return "orphan";
    const buttons = [];
    for (const sel of BUTTON_SELECTORS) {
      for (const btn of root.querySelectorAll(sel)) {
        const t = (btn.textContent || "").trim();
        if (t && t.length <= 60) buttons.push(normalizeLabel(t));
      }
    }
    buttons.sort();
    const row = el.closest(SUBAGENT_ROW_SELECTOR);
    const task = _taskForRow(row);
    const promptPart = buttons.join("|") || "empty";
    return task ? `${task.taskKey}|${task.rowKey}|${promptPart}` : promptPart;
  }

  function _isCoolingDown(fingerprint) {
    const last = state.fingerprintCooldowns.get(fingerprint);
    if (!last) return false;
    return Date.now() - last < FINGERPRINT_COOLDOWN_MS;
  }

  function _markClicked(fingerprint) {
    state.fingerprintCooldowns.set(fingerprint, Date.now());
    if (state.fingerprintCooldowns.size > 100) {
      const oldest = state.fingerprintCooldowns.keys().next().value;
      state.fingerprintCooldowns.delete(oldest);
    }
  }

  // -----------------------------------------------------------------------
  // Event queue (sink for launcher to drain)
  // -----------------------------------------------------------------------

  function _queueEvent(ev) {
    ev.ts = new Date().toISOString();
    ev.scriptHash = SCRIPT_HASH;
    state.eventQueue.push(ev);
    if (state.eventQueue.length > EVENT_QUEUE_MAX) {
      state.eventQueue = state.eventQueue.slice(-EVENT_QUEUE_MAX);
    }
  }

  // -----------------------------------------------------------------------
  // State-first probe (feature-flagged)
  //
  // When enabled, checks for internal Cursor approval state before DOM
  // scanning. These internal signals are more stable than DOM labels but
  // may break across Cursor versions — hence the feature flag.
  // -----------------------------------------------------------------------

  function _probeStructuredState() {
    if (!state.enableStateProbe) return null;
    try {
      const indicators = [];
      const allElements = document.querySelectorAll("[class*='approval'], [class*='permission'], [data-testid*='approval']");
      for (const el of allElements) {
        if (!isVisible(el) || isInExcludedZone(el)) continue;
        indicators.push({
          tag: el.tagName.toLowerCase(),
          classes: el.className?.toString().slice(0, 100) || "",
          text: (el.textContent || "").trim().slice(0, 100),
        });
      }

      const composerStates = document.querySelectorAll("[class*='wakelock'], [class*='user-approval']");
      for (const el of composerStates) {
        if (!isVisible(el)) continue;
        indicators.push({
          tag: el.tagName.toLowerCase(),
          classes: el.className?.toString().slice(0, 100) || "",
          text: (el.textContent || "").trim().slice(0, 100),
          signal: "internal-state",
        });
      }

      if (indicators.length > 0) {
        _queueEvent({
          type: "state_probe",
          indicators,
          found: indicators.length,
        });
      }
      return indicators.length > 0 ? indicators : null;
    } catch (e) {
      console.log(`${LOG_PREFIX} state probe error:`, e.message);
      return null;
    }
  }

  // -----------------------------------------------------------------------
  // Discovery layer: find approval candidates
  // -----------------------------------------------------------------------

  function isLikelyLooseTextControl(el) {
    const tag = el.tagName.toLowerCase();
    if (tag !== "div" && tag !== "span") return true;
    const role = (el.getAttribute("role") || "").toLowerCase();
    const classes = (el.className || "").toString();
    const cursor = window.getComputedStyle(el).cursor;
    return (
      role === "button" ||
      /button|action|accept|reject/i.test(classes) ||
      cursor === "pointer"
    );
  }

  function matchesApproval(el, options = {}) {
    if (!el || !el.textContent) return null;
    const raw = el.textContent.trim();
    if (raw.length > 60) return null;
    if (isInExcludedZone(el) && !options.allowExcluded) return null;
    if (options.allowLooseText && !isLikelyLooseTextControl(el)) return null;
    const stripped = normalizeLabel(raw);
    for (const { pattern, id } of APPROVAL_PATTERNS) {
      if (stripped === pattern && isVisible(el) && isClickable(el)) {
        return { id, text: raw };
      }
    }
    return null;
  }

  function _matchesLabelSet(el, labelSet, options = {}) {
    if (!el || !el.textContent) return false;
    const raw = el.textContent.trim();
    if (!raw || raw.length > 40) return false;
    if (
      !isVisible(el) ||
      !isClickable(el) ||
      (isInExcludedZone(el) && !options.allowExcluded)
    ) {
      return false;
    }
    return labelSet.has(normalizeLabel(raw));
  }

  function matchesDismissal(el, options = {}) {
    return _matchesLabelSet(el, DISMISS_PATTERNS, options);
  }

  function matchesCompanion(el, options = {}) {
    return _matchesLabelSet(el, COMPANION_PATTERNS, options);
  }

  function _hasNearbyMatch(el, matchFn) {
    const PART_BOUNDARY = /^workbench\.parts\./;
    let node = el;
    for (let depth = 0; node && depth < 3; depth++) {
      if (node.id && PART_BOUNDARY.test(node.id)) break;
      for (const sel of BUTTON_SELECTORS) {
        for (const candidate of node.querySelectorAll(sel)) {
          if (candidate === el) continue;
          if (matchFn(candidate)) return true;
        }
      }
      node = node.parentElement;
    }
    return false;
  }

  function hasNearbyDismissal(el, options = {}) {
    return _hasNearbyMatch(el, (candidate) => matchesDismissal(candidate, options));
  }

  function hasNearbyCompanion(el, options = {}) {
    return _hasNearbyMatch(el, (candidate) => matchesCompanion(candidate, options));
  }

  function _isPromptRoot(el) {
    return !!el.closest(PROMPT_ROOT_SELECTORS.join(", "));
  }

  function _isComposerSurface(el) {
    const inputBoxes = document.querySelectorAll("div.full-input-box");
    for (const inputBox of inputBoxes) {
      let node = inputBox;
      for (let d = 0; d < 8 && node && node !== document.body; d++) {
        if (node.contains(el)) return true;
        node = node.parentElement;
      }
    }
    return false;
  }

  function _hasTrustedPromptContext(btn) {
    if (!btn || !btn.el) return false;
    if (btn.kind === "resume" || btn.kind === "connection") return true;
    return _isPromptRoot(btn.el) || _isComposerSurface(btn.el);
  }

  function isModalSingleActionApprove(btn, options = {}) {
    if (!btn || btn.kind !== "approval" || !btn.el) return false;
    if (!["approve", "approve_request", "approve_terminal_command"].includes(btn.id)) return false;

    const root = btn.el.closest(PROMPT_ROOT_SELECTORS.join(", "));
    if (
      !root ||
      (isInExcludedZone(root) && !options.allowExcluded) ||
      !isVisible(root)
    ) {
      return false;
    }

    const controls = [];
    const seen = new Set();
    for (const sel of BUTTON_SELECTORS) {
      for (const el of root.querySelectorAll(sel)) {
        if (seen.has(el)) continue;
        seen.add(el);
        if (
          !isVisible(el) ||
          !isClickable(el) ||
          (isInExcludedZone(el) && !options.allowExcluded)
        ) {
          continue;
        }
        const text = (el.textContent || "").trim();
        if (!text || text.length > 60) continue;
        controls.push(el);
      }
    }

    if (controls.some((el) => matchesDismissal(el, options))) return false;
    return controls.length > 0 && controls.length <= 2;
  }

  function collectApprovalMatches(root, out, seen) {
    for (const sel of BUTTON_SELECTORS) {
      for (const el of root.querySelectorAll(sel)) {
        if (seen.has(el)) continue;
        seen.add(el);
        const m = matchesApproval(el);
        if (m) out.push({ el, kind: "approval", ...m });
      }
    }
    if (!seen.has(root)) {
      seen.add(root);
      const m = matchesApproval(root);
      if (m) out.push({ el: root, kind: "approval", ...m });
    }
  }

  function _findDeleteFilePromptRoot(el) {
    let node = el;
    for (let depth = 0; node && node !== document.body && depth < 8; depth++) {
      const text = (node.textContent || "").trim();
      if (text.length <= 2000 && DELETE_FILE_PROMPT_PATTERN.test(text)) {
        return node;
      }
      node = node.parentElement;
    }
    return null;
  }

  function _hasLooseLabel(root, labelSet) {
    const seen = new Set();
    for (const sel of LOOSE_TEXT_CONTROL_SELECTORS) {
      for (const el of root.querySelectorAll(sel)) {
        if (seen.has(el)) continue;
        seen.add(el);
        if (!el.textContent || !isVisible(el) || !isClickable(el)) continue;
        const raw = el.textContent.trim();
        if (!raw || raw.length > 60) continue;
        if (labelSet.has(normalizeLabel(raw)) && isLikelyLooseTextControl(el)) {
          return true;
        }
      }
    }
    return false;
  }

  function isDeleteFileChangeApprove(btn) {
    if (!btn || btn.kind !== "approval" || btn.id !== "accept" || !btn.el) return false;
    const root = _findDeleteFilePromptRoot(btn.el);
    if (!root || !isVisible(root)) return false;
    return _hasLooseLabel(root, DISMISS_PATTERNS);
  }

  function collectDeleteFileChangeMatches(root, out, seen) {
    const text = (root.textContent || "").trim();
    if (
      !text ||
      text.length > 2000 ||
      !DELETE_FILE_PROMPT_PATTERN.test(text) ||
      !isVisible(root)
    ) {
      return;
    }
    for (const sel of LOOSE_TEXT_CONTROL_SELECTORS) {
      for (const el of root.querySelectorAll(sel)) {
        if (seen.has(el)) continue;
        seen.add(el);
        const m = matchesApproval(el, {
          allowExcluded: true,
          allowLooseText: true,
        });
        if (m) out.push({ el, kind: "approval", ...m });
      }
    }
  }

  function findApprovalButtons() {
    const buttons = [];
    const seen = new Set();

    const inputBoxes = Array.from(document.querySelectorAll("div.full-input-box"));
    for (const inputBox of inputBoxes) {
      const surfaceStart = buttons.length;
      let ancestor = inputBox;
      for (
        let aDepth = 0;
        ancestor && aDepth < 4 && buttons.length === surfaceStart;
        aDepth++
      ) {
        let sib = ancestor.previousElementSibling;
        let sibIdx = 0;
        while (sib && sibIdx < 5) {
          collectApprovalMatches(sib, buttons, seen);
          sib = sib.previousElementSibling;
          sibIdx++;
        }
        ancestor = ancestor.parentElement;
      }

      if (buttons.length === surfaceStart) {
        let composerRoot = null;
        let node = inputBox;
        for (let i = 0; i < 8 && node && node !== document.body; i++) {
          const cn = (node.className || "").toString();
          if (
            /composer|chat|conversation/i.test(cn) ||
            (node.id && /composer/i.test(node.id))
          ) {
            composerRoot = node;
          }
          node = node.parentElement;
        }
        if (composerRoot) {
          collectApprovalMatches(composerRoot, buttons, seen);
        }
      }
    }

    if (buttons.length === 0) {
      const promptRoots = document.querySelectorAll(PROMPT_ROOT_SELECTORS.join(", "));
      for (const root of promptRoots) {
        if (isInExcludedZone(root)) continue;
        collectApprovalMatches(root, buttons, seen);
      }
    }

    if (buttons.length === 0) {
      const deleteRoots = new Set(document.querySelectorAll(SUBAGENT_ROW_SELECTOR));
      for (const surface of document.querySelectorAll(DELETE_FILE_SURFACE_SELECTOR)) {
        if (deleteRoots.size >= MAX_DELETE_FILE_FALLBACK_ROOTS) break;
        deleteRoots.add(surface.closest(SUBAGENT_ROW_SELECTOR) || surface);
      }
      let inspected = 0;
      for (const root of deleteRoots) {
        if (inspected++ >= MAX_DELETE_FILE_FALLBACK_ROOTS) break;
        collectDeleteFileChangeMatches(root, buttons, seen);
        if (buttons.length > 0) break;
      }
    }

    if (state.enableResume) {
      const resumeLinks = document.querySelectorAll(
        `a[data-link="${RESUME_DATA_LINK}"], [class*="markdown-link"][data-link="${RESUME_DATA_LINK}"]`
      );
      for (const el of resumeLinks) {
        if (isVisible(el) && isClickable(el) && !isInExcludedZone(el)) {
          buttons.push({
            el,
            kind: "resume",
            id: "resume_conversation",
            text: el.textContent.trim(),
          });
        }
      }
    }

    if (state.enableConnectionRetry) {
      const containers = document.querySelectorAll(
        '[role="dialog"], [role="alertdialog"], [aria-modal="true"]'
      );
      for (const container of containers) {
        if (isInExcludedZone(container)) continue;
        const text = container.textContent;
        if (text.length > 500) continue;
        const lower = text.toLowerCase();
        if (!lower.includes("connection failed") && !lower.includes("connection error")) continue;
        for (const btn of container.querySelectorAll("button")) {
          const t = btn.textContent.toLowerCase().trim();
          if (t === "resume" || t === "try again" || t === "retry") {
            if (isVisible(btn) && isClickable(btn)) {
              buttons.push({
                el: btn,
                kind: "connection",
                id: t === "resume" ? "connection_resume" : "connection_try_again",
                text: btn.textContent.trim(),
              });
            }
          }
        }
      }
    }

    return buttons;
  }

  // -----------------------------------------------------------------------
  // Policy layer: decide click/block/unknown
  // -----------------------------------------------------------------------

  function _eligibilityReason(btn) {
    if (isDeleteFileChangeApprove(btn)) return "delete_file_change";
    if (!_hasTrustedPromptContext(btn)) return null;
    if (btn.kind === "resume") return "resume";
    if (hasNearbyDismissal(btn.el)) return "dismiss";
    if (hasNearbyCompanion(btn.el)) return "companion";
    if (isModalSingleActionApprove(btn)) return "modal";
    return null;
  }

  function _isCycleOwnedSubagentCandidate(btn) {
    if (!state.cycleEnabled || !btn?.el) return false;
    const row = btn.el.closest(SUBAGENT_ROW_SELECTOR);
    return !!_taskForRow(row);
  }

  function _debugSurface(el) {
    if (!el) return "none";
    if (_isPromptRoot(el)) return "modal";
    if (_isComposerSurface(el)) return "composer";
    return "other";
  }

  // -----------------------------------------------------------------------
  // Prompt-scoped artifact capture (focused, not whole-window)
  // -----------------------------------------------------------------------

  function _capturePromptSubtree(el) {
    const root = el.closest(PROMPT_ROOT_SELECTORS.join(", ")) || el.parentElement;
    if (!root) return null;
    const buttons = [];
    const seenEls = new Set();
    for (const sel of BUTTON_SELECTORS) {
      for (const btn of root.querySelectorAll(sel)) {
        if (seenEls.has(btn)) continue;
        seenEls.add(btn);
        const text = (btn.textContent || "").trim();
        if (!text || text.length > 80) continue;
        buttons.push({
          text,
          normalized: normalizeLabel(text),
          tag: btn.tagName.toLowerCase(),
          visible: isVisible(btn),
          clickable: isClickable(btn),
          excluded: isInExcludedZone(btn),
        });
      }
    }
    return {
      role: root.getAttribute("role"),
      ariaModal: root.getAttribute("aria-modal"),
      textPreview: (root.textContent || "").trim().slice(0, 200),
      buttonCount: buttons.length,
      buttons,
    };
  }

  // -----------------------------------------------------------------------
  // Command text extraction (preserves multiline formatting)
  // -----------------------------------------------------------------------

  const COMMAND_TEXT_CAP = 5000;

  function _extractCommandText(el) {
    let root = el.closest(PROMPT_ROOT_SELECTORS.join(", "));
    if (!root) {
      let node = el.parentElement;
      for (let d = 0; d < 5 && node && node !== document.body; d++) {
        if (node.querySelector("pre, code")) {
          root = node;
          break;
        }
        node = node.parentElement;
      }
    }
    if (!root) root = el.parentElement;
    if (!root) return null;

    for (const sel of ["pre code", "pre", "code"]) {
      for (const node of root.querySelectorAll(sel)) {
        const text = (node.innerText || node.textContent || "").trim();
        if (text.length >= 2 && text.length <= COMMAND_TEXT_CAP) {
          const lines = text.split("\n");
          return {
            text: text,
            lineCount: lines.length,
            preview: lines[0].slice(0, 120),
            source: "code_block",
          };
        }
      }
    }

    const fullText = (root.innerText || root.textContent || "").trim();
    if (!fullText || fullText.length < 2) return null;

    const buttonTexts = new Set();
    for (const sel of BUTTON_SELECTORS) {
      for (const btn of root.querySelectorAll(sel)) {
        const t = (btn.textContent || "").trim();
        if (t) buttonTexts.add(t);
      }
    }
    const filtered = fullText
      .split("\n")
      .filter((line) => line.trim() && !buttonTexts.has(line.trim()))
      .join("\n")
      .trim();
    if (!filtered || filtered.length < 2) return null;
    const capped = filtered.slice(0, COMMAND_TEXT_CAP);
    const lines = capped.split("\n");
    return {
      text: capped,
      lineCount: lines.length,
      preview: lines[0].slice(0, 120),
      source: "prompt_text",
    };
  }

  // -----------------------------------------------------------------------
  // Click execution
  // -----------------------------------------------------------------------

  function clickEl(el) {
    try {
      if (typeof el.click === "function") {
        el.click();
        return;
      }
    } catch (_) {}

    const r = el.getBoundingClientRect();
    const x = r.left + r.width / 2;
    const y = r.top + r.height / 2;
    const opts = { bubbles: true, cancelable: true, view: window, clientX: x, clientY: y };
    el.dispatchEvent(new MouseEvent("click", opts));
  }

  // -----------------------------------------------------------------------
  // Core check-and-click (called by observer and poll)
  // -----------------------------------------------------------------------

  function _checkAndClickImpl() {
    _discoverSubagentRows(document);
    _probeStructuredState();

    const buttons = findApprovalButtons();
    if (buttons.length === 0) return;

    const priority = { approval: 0, connection: 1, resume: 2 };

    const evaluated = buttons.map((btn) => ({
      ...btn,
      reason: _eligibilityReason(btn),
      fingerprint: _promptFingerprint(btn.el),
      cycleOwned: _isCycleOwnedSubagentCandidate(btn),
    }));

    const eligible = evaluated
      .filter((btn) => btn.reason !== null && !btn.cycleOwned)
      .sort((a, b) => (priority[a.kind || "approval"] ?? 9) - (priority[b.kind || "approval"] ?? 9));

    const blocked = evaluated.filter(
      (btn) => !btn.cycleOwned && btn.reason === null && _hasTrustedPromptContext(btn)
    );
    const unknown = evaluated.filter(
      (btn) => !btn.cycleOwned && btn.reason === null && !_hasTrustedPromptContext(btn)
    );

    for (const btn of blocked) {
      _queueEvent({
        type: "blocked_candidate",
        kind: btn.kind,
        pattern_id: btn.id,
        text: btn.text,
        surface: _debugSurface(btn.el),
        fingerprint: btn.fingerprint,
        prompt: _capturePromptSubtree(btn.el),
        command: _extractCommandText(btn.el),
      });
    }

    for (const btn of unknown) {
      _queueEvent({
        type: "unknown_prompt",
        kind: btn.kind,
        pattern_id: btn.id,
        text: btn.text,
        surface: _debugSurface(btn.el),
        fingerprint: btn.fingerprint,
        prompt: _capturePromptSubtree(btn.el),
        command: _extractCommandText(btn.el),
      });
    }

    const btn = eligible.find((candidate) => !_isCoolingDown(candidate.fingerprint));
    if (!btn) return;

    const command = _extractCommandText(btn.el);
    const promptCapture = _capturePromptSubtree(btn.el);
    const focusContext = {
      focusedElement: document.activeElement,
      interactionGeneration: state.interactionGeneration,
    };

    clickEl(btn.el);
    _settleFocusAfterAutomation(focusContext, "direct_scan");
    _markClicked(btn.fingerprint);
    state.totalClicks++;
    state.totalClickAttempts++;
    const entry = {
      ts: new Date().toISOString(),
      kind: btn.kind || "approval",
      id: btn.id,
      text: btn.text,
      reason: btn.reason,
      fingerprint: btn.fingerprint,
      commandPreview: command ? command.preview : null,
      commandLines: command ? command.lineCount : null,
    };
    state.clicks.push(entry);
    if (state.clicks.length > 100) {
      state.clicks = state.clicks.slice(-100);
    }

    _queueEvent({
      type: "click",
      kind: btn.kind || "approval",
      pattern_id: btn.id,
      text: btn.text,
      reason: btn.reason,
      fingerprint: btn.fingerprint,
      prompt: promptCapture,
      command: command,
    });

    console.log(
      `${LOG_PREFIX} clicked ${btn.id}: "${btn.text}" [${btn.reason}] (total: ${state.totalClicks})`
    );
  }

  function _tripSafetyCircuit(reason, details = {}) {
    if (state.safetyTrip) return;
    state.safetyTrip = {
      reason,
      ts: new Date().toISOString(),
      ...details,
    };
    _queueEvent({
      type: "safety_trip",
      reason,
      ...details,
    });
    setTimeout(() => {
      if (state.running) stop();
    }, 0);
  }

  function checkAndClick() {
    const started = performance.now();
    try {
      return _checkAndClickImpl();
    } finally {
      const duration = performance.now() - started;
      state.totalScans++;
      state.lastScanAt = Date.now();
      state.lastScanDurationMs = Math.round(duration * 10) / 10;
      state.maxScanDurationMs = Math.max(state.maxScanDurationMs, state.lastScanDurationMs);
      state.consecutiveSlowScans =
        duration > MAX_SAFE_SCAN_DURATION_MS ? state.consecutiveSlowScans + 1 : 0;
      if (state.consecutiveSlowScans >= MAX_CONSECUTIVE_SLOW_SCANS) {
        _tripSafetyCircuit("repeated_slow_scans", {
          durationMs: state.lastScanDurationMs,
          consecutive: state.consecutiveSlowScans,
        });
      }
      const usedHeap = performance.memory?.usedJSHeapSize;
      if (Number.isFinite(usedHeap) && usedHeap > MAX_JS_HEAP_BYTES) {
        _tripSafetyCircuit("js_heap_limit", {
          usedJSHeapBytes: usedHeap,
          limitBytes: MAX_JS_HEAP_BYTES,
        });
      }
    }
  }

  // -----------------------------------------------------------------------
  // MutationObserver: detect prompt surfaces immediately
  // -----------------------------------------------------------------------

  function _mutationElementMayContainApproval(element) {
    if (!element?.matches) return false;
    const relevant = [
      ...BUTTON_SELECTORS,
      ...PROMPT_ROOT_SELECTORS,
      SUBAGENT_TRAY_ITEM_SELECTOR,
      ".composer-toolbar-section-header-label",
      `[data-link="${RESUME_DATA_LINK}"]`,
    ].join(", ");
    return element.matches(relevant) || !!element.querySelector?.(relevant);
  }

  function _setupObserver() {
    if (state.observer) return;

    state.observer = new MutationObserver((records) => {
      if (!state.running) return;
      const discoveryRoots = new Set();
      let shouldScanApprovals = false;
      let shouldScheduleTrayCycle = false;
      for (const record of records) {
        if (record.type === "childList") {
          for (const node of record.addedNodes) {
            const element =
              node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
            if (!element) continue;
            if (
              element.closest?.(SUBAGENT_ROW_SELECTOR) ||
              element.querySelector?.(SUBAGENT_SURFACE_SELECTOR)
            ) {
              discoveryRoots.add(element);
            }
            if (
              element.closest?.(SUBAGENT_TRAY_ITEM_SELECTOR) ||
              element.querySelector?.(SUBAGENT_TRAY_ITEM_SELECTOR) ||
              element.matches?.(".composer-toolbar-section-header-label")
            ) {
              shouldScheduleTrayCycle = true;
            }
            if (_mutationElementMayContainApproval(element)) shouldScanApprovals = true;
          }
        } else if (record.target?.nodeType === Node.ELEMENT_NODE) {
          const target = record.target;
          if (target.closest?.(SUBAGENT_SURFACE_SELECTOR)) discoveryRoots.add(target);
          if (_mutationElementMayContainApproval(target)) shouldScanApprovals = true;
        } else if (record.type === "characterData" && record.target.parentElement) {
          const parent = record.target.parentElement;
          if (parent.closest?.(SUBAGENT_SURFACE_SELECTOR)) {
            discoveryRoots.add(parent);
            shouldScanApprovals = true;
          }
        }
      }
      if (discoveryRoots.size > 0) {
        _discoverSubagentRows(Array.from(discoveryRoots));
      }
      if (shouldScheduleTrayCycle && state.cycleEnabled) {
        _scheduleSubagentCycle(100);
      }
      if (!shouldScanApprovals) return;
      if (state.observerDebounceTimer) clearTimeout(state.observerDebounceTimer);
      const sinceLastScan = Date.now() - state.lastScanAt;
      const delay = Math.max(
        OBSERVER_DEBOUNCE_MS,
        OBSERVER_MIN_SCAN_GAP_MS - sinceLastScan
      );
      state.observerDebounceTimer = setTimeout(() => {
        state.observerDebounceTimer = null;
        checkAndClick();
      }, delay);
    });

    state.observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      characterData: true,
      attributeFilter: ["role", "aria-modal", "class", "disabled"],
    });
  }

  function _teardownObserver() {
    if (state.observer) {
      state.observer.disconnect();
      state.observer = null;
    }
    if (state.observerDebounceTimer) {
      clearTimeout(state.observerDebounceTimer);
      state.observerDebounceTimer = null;
    }
  }

  // -----------------------------------------------------------------------
  // Title sync
  // -----------------------------------------------------------------------

  function _syncTitle() {
    if (state.shareSafeTitle) {
      const docTitle = NATURAL_DOC_TITLE_AT_INJECT;
      const barText =
        NATURAL_TITLEBAR_TEXT_AT_INJECT || NATURAL_DOC_TITLE_AT_INJECT || docTitle;
      if (document.title !== docTitle) document.title = docTitle;
      const titleButton = document.querySelector(
        '[id="workbench.parts.titlebar"] .window-title-text'
      );
      if (titleButton) {
        if (titleButton.textContent !== barText) titleButton.textContent = barText;
        if (titleButton.title !== barText) titleButton.title = barText;
        if (titleButton.getAttribute("aria-label") !== barText) {
          titleButton.setAttribute("aria-label", barText);
        }
      }
      const titleContainer = document.querySelector(
        '[id="workbench.parts.titlebar"] .window-title'
      );
      if (titleContainer && titleContainer.title !== barText) {
        titleContainer.title = barText;
      }
      return;
    }

    const emoji = state.running ? "\u2705" : "\u23F8";
    const title = `autoapprove ${emoji} ${REPO_SLUG}`;
    if (document.title !== title) document.title = title;
    const titleButton = document.querySelector(
      '[id="workbench.parts.titlebar"] .window-title-text'
    );
    if (titleButton) {
      if (titleButton.textContent !== title) titleButton.textContent = title;
      if (titleButton.title !== title) titleButton.title = title;
      if (titleButton.getAttribute("aria-label") !== title) {
        titleButton.setAttribute("aria-label", title);
      }
    }
    const titleContainer = document.querySelector(
      '[id="workbench.parts.titlebar"] .window-title'
    );
    if (titleContainer && titleContainer.title !== title) {
      titleContainer.title = title;
    }
  }

  function _ensureTitleTimer() {
    if (state.titleTimer) clearInterval(state.titleTimer);
    const ms = state.shareSafeTitle ? TITLE_SYNC_INTERVAL_SHARE_SAFE : TITLE_SYNC_INTERVAL;
    state.titleTimer = setInterval(_syncTitle, ms);
  }

  function setShareSafeTitle(enabled) {
    state.shareSafeTitle = Boolean(enabled);
    _syncTitle();
    _ensureTitleTimer();
  }

  // -----------------------------------------------------------------------
  // Debug snapshot (prompt-scoped, not whole-window button dump)
  // -----------------------------------------------------------------------

  function _debugButtons(limit = 300) {
    const rows = [];
    const seen = new Set();
    for (const sel of BUTTON_SELECTORS) {
      for (const el of document.querySelectorAll(sel)) {
        if (seen.has(el)) continue;
        seen.add(el);
        const text = (el.textContent || "").trim().replace(/\s+/g, " ");
        if (!text || text.length > 80) continue;
        if (!isVisible(el)) continue;
        const m = matchesApproval(el);
        rows.push({
          text,
          normalized: normalizeLabel(text),
          tag: el.tagName.toLowerCase(),
          role: el.getAttribute("role") || "",
          inExcludedZone: isInExcludedZone(el),
          surface: _debugSurface(el),
          approvalId: m ? m.id : null,
          hasDismissNearby: hasNearbyDismissal(el),
          hasCompanionNearby: hasNearbyCompanion(el),
        });
        if (rows.length >= limit) return rows;
      }
    }
    return rows;
  }

  function debugSnapshot() {
    const candidates = findApprovalButtons().map((btn) => {
      const fp = _promptFingerprint(btn.el);
      return {
        kind: btn.kind || "approval",
        id: btn.id || "",
        text: btn.text || "",
        reason: _eligibilityReason(btn),
        cycleOwned: _isCycleOwnedSubagentCandidate(btn),
        surface: _debugSurface(btn.el),
        fingerprint: fp,
        coolingDown: _isCoolingDown(fp),
        inExcludedZone: isInExcludedZone(btn.el),
        hasDismissNearby: hasNearbyDismissal(btn.el),
        hasCompanionNearby: hasNearbyCompanion(btn.el),
        isModalSingleActionApprove: isModalSingleActionApprove(btn),
        prompt: _capturePromptSubtree(btn.el),
        command: _extractCommandText(btn.el),
      };
    });
    return {
      strategyVersion: STRATEGY_VERSION,
      scriptHash: state.scriptHash,
      running: state.running,
      totalClicks: state.totalClicks,
      totalScans: state.totalScans,
      lastScanDurationMs: state.lastScanDurationMs,
      maxScanDurationMs: state.maxScanDurationMs,
      shareSafeTitle: state.shareSafeTitle,
      observerActive: !!state.observer,
      mountedComposerCount: document.querySelectorAll("div.full-input-box").length,
      mountedConversationCount: document.querySelectorAll("div.conversations").length,
      eventQueueLength: state.eventQueue.length,
      cooldownEntries: state.fingerprintCooldowns.size,
      totalClickAttempts: state.totalClickAttempts,
      totalConfirmedApprovals: state.totalConfirmedApprovals,
      activeFocusKind: _focusKind(document.activeElement),
      cycleFocusBlockReason: document.hasFocus()
        ? _activeEditingSurfaceBlockReason()
        : null,
      lastFocusRestore: state.lastFocusRestore,
      subagents: exportSubagentRegistry(),
      visibleButtons: _debugButtons(),
      candidates,
      eligible: candidates.filter((c) => c.reason !== null && !c.cycleOwned),
      ts: new Date().toISOString(),
    };
  }

  // -----------------------------------------------------------------------
  // Start / stop / status
  // -----------------------------------------------------------------------

  function _normalizedPollInterval(interval) {
    if (typeof interval !== "number" || !Number.isFinite(interval)) {
      return state.interval;
    }
    return Math.min(
      MAX_POLL_INTERVAL_MS,
      Math.max(MIN_POLL_INTERVAL_MS, Math.round(interval))
    );
  }

  function start(interval) {
    const nextInterval = _normalizedPollInterval(interval);
    if (state.running) {
      if (nextInterval !== state.interval) {
        state.interval = nextInterval;
        clearInterval(state.timer);
        state.timer = setInterval(checkAndClick, state.interval);
        console.log(`${LOG_PREFIX} poll interval updated to ${state.interval}ms`);
        setTimeout(checkAndClick, 50);
      } else {
        console.log(`${LOG_PREFIX} already running (interval ${state.interval}ms)`);
      }
      return;
    }
    state.interval = nextInterval;
    state.running = true;
    state.safetyTrip = null;
    state.consecutiveSlowScans = 0;
    _setupInteractionGuard();
    _setupObserver();
    _discoverSubagentRows(document);
    state.timer = setInterval(checkAndClick, state.interval);
    _syncTitle();
    console.log(`${LOG_PREFIX} started (interval ${state.interval}ms, observer active)`);
    setTimeout(checkAndClick, 50);
    if (state.cycleEnabled) _scheduleSubagentCycle(100);
  }

  function stop() {
    if (!state.running) {
      console.log(`${LOG_PREFIX} not running`);
      return;
    }
    clearInterval(state.timer);
    state.timer = null;
    if (state.cycleTimer) {
      clearTimeout(state.cycleTimer);
      state.cycleTimer = null;
    }
    state.cycleGeneration++;
    _teardownObserver();
    state.running = false;
    _syncTitle();
    console.log(`${LOG_PREFIX} stopped (total clicks: ${state.totalClicks})`);
  }

  function status() {
    const registry = exportSubagentRegistry();
    const s = {
      strategyVersion: STRATEGY_VERSION,
      scriptHash: state.scriptHash,
      repoSlug: state.repoSlug,
      running: state.running,
      interval: state.interval,
      totalClicks: state.totalClicks,
      observerActive: !!state.observer,
      eventQueueLength: state.eventQueue.length,
      cooldownEntries: state.fingerprintCooldowns.size,
      totalClickAttempts: state.totalClickAttempts,
      totalConfirmedApprovals: state.totalConfirmedApprovals,
      totalScans: state.totalScans,
      lastScanDurationMs: state.lastScanDurationMs,
      maxScanDurationMs: state.maxScanDurationMs,
      safetyTrip: state.safetyTrip,
      usedJSHeapBytes: performance.memory?.usedJSHeapSize || null,
      recentClicks: state.clicks.slice(-10),
      shareSafeTitle: state.shareSafeTitle,
      cycleEnabled: state.cycleEnabled,
      cycleActive: state.cycleActive,
      subagentCounts: registry.counts,
      subagentTray: registry.tray,
      activeFocusKind: _focusKind(document.activeElement),
      cycleFocusBlockReason: document.hasFocus()
        ? _activeEditingSurfaceBlockReason()
        : null,
      lastFocusRestore: state.lastFocusRestore,
      lastCycle: state.lastCycle,
    };
    console.log(`${LOG_PREFIX} status`, JSON.stringify(s, null, 2));
    return s;
  }

  // -----------------------------------------------------------------------
  // Bootstrap
  // -----------------------------------------------------------------------

  _loadSubagentRegistry();
  _setupInteractionGuard();
  _ensureTitleTimer();
  _syncTitle();

  globalThis.__cursorAutoAccept = {
    start,
    stop,
    status,
    state,
    setShareSafeTitle,
    setSubagentCycle,
    runSubagentCycle,
    exportSubagentRegistry,
    discoverSubagentRows: _discoverSubagentRows,
  };
  globalThis.startAccept = start;
  globalThis.stopAccept = stop;
  globalThis.acceptStatus = status;
  globalThis.acceptDebugSnapshot = debugSnapshot;
  globalThis.setShareSafeTitle = setShareSafeTitle;
  globalThis.setSubagentCycle = setSubagentCycle;
  globalThis.runSubagentCycle = (options = {}) => runSubagentCycle(options);
  globalThis.exportSubagentRegistry = exportSubagentRegistry;

  console.log(
    `${LOG_PREFIX} loaded (${SCRIPT_HASH}) — startAccept() / stopAccept() / acceptStatus()`
  );
})();
