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
(function () {
  "use strict";

  if (globalThis.__cursorAutoAccept) {
    console.log("[autoAccept] already loaded — use startAccept() / stopAccept()");
    return;
  }

  const LOG_PREFIX = "[autoAccept]";
  const SCRIPT_HASH = globalThis.__cursorAutoAcceptScriptHash || "unknown";
  const REPO_SLUG = globalThis.__cursorAutoAcceptRepoSlug || "workspace";
  const STRATEGY_VERSION = "2026-04-observer-policy";
  const TITLE_SYNC_INTERVAL = 3000;
  const OBSERVER_DEBOUNCE_MS = 300;
  const FINGERPRINT_COOLDOWN_MS = 8000;
  const EVENT_QUEUE_MAX = 200;

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
  const PROMPT_ROOT_SELECTORS = [
    '[role="dialog"]',
    '[role="alertdialog"]',
    '[aria-modal="true"]',
  ];
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
    interval: 2000,
    running: false,
    timer: null,
    titleTimer: null,
    observer: null,
    observerDebounceTimer: null,
    totalClicks: 0,
    clicks: [],
    eventQueue: [],
    fingerprintCooldowns: new Map(),
    enableResume: true,
    enableConnectionRetry: true,
    enableStateProbe: false,
  };

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
    return buttons.join("|") || "empty";
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

  function matchesApproval(el) {
    if (!el || !el.textContent) return null;
    const raw = el.textContent.trim();
    if (raw.length > 60) return null;
    if (isInExcludedZone(el)) return null;
    const stripped = normalizeLabel(raw);
    for (const { pattern, id } of APPROVAL_PATTERNS) {
      if (stripped === pattern && isVisible(el) && isClickable(el)) {
        return { id, text: raw };
      }
    }
    return null;
  }

  function _matchesLabelSet(el, labelSet) {
    if (!el || !el.textContent) return false;
    const raw = el.textContent.trim();
    if (!raw || raw.length > 40) return false;
    if (!isVisible(el) || !isClickable(el) || isInExcludedZone(el)) return false;
    return labelSet.has(normalizeLabel(raw));
  }

  function matchesDismissal(el) {
    return _matchesLabelSet(el, DISMISS_PATTERNS);
  }

  function matchesCompanion(el) {
    return _matchesLabelSet(el, COMPANION_PATTERNS);
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

  function hasNearbyDismissal(el) {
    return _hasNearbyMatch(el, matchesDismissal);
  }

  function hasNearbyCompanion(el) {
    return _hasNearbyMatch(el, matchesCompanion);
  }

  function _isPromptRoot(el) {
    return !!el.closest(PROMPT_ROOT_SELECTORS.join(", "));
  }

  function _isComposerSurface(el) {
    const inputBox = document.querySelector("div.full-input-box");
    if (!inputBox) return false;
    let node = inputBox;
    for (let d = 0; d < 8 && node && node !== document.body; d++) {
      if (node.contains(el)) return true;
      node = node.parentElement;
    }
    return false;
  }

  function _hasTrustedPromptContext(btn) {
    if (!btn || !btn.el) return false;
    if (btn.kind === "resume" || btn.kind === "connection") return true;
    return _isPromptRoot(btn.el) || _isComposerSurface(btn.el);
  }

  function isModalSingleActionApprove(btn) {
    if (!btn || btn.kind !== "approval" || !btn.el) return false;
    if (!["approve", "approve_request", "approve_terminal_command"].includes(btn.id)) return false;

    const root = btn.el.closest(PROMPT_ROOT_SELECTORS.join(", "));
    if (!root || isInExcludedZone(root) || !isVisible(root)) return false;

    const controls = [];
    const seen = new Set();
    for (const sel of BUTTON_SELECTORS) {
      for (const el of root.querySelectorAll(sel)) {
        if (seen.has(el)) continue;
        seen.add(el);
        if (!isVisible(el) || !isClickable(el) || isInExcludedZone(el)) continue;
        const text = (el.textContent || "").trim();
        if (!text || text.length > 60) continue;
        controls.push(el);
      }
    }

    if (controls.some((el) => matchesDismissal(el))) return false;
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

  function findApprovalButtons() {
    const buttons = [];
    const seen = new Set();

    const inputBox = document.querySelector("div.full-input-box");
    if (inputBox) {
      let ancestor = inputBox;
      for (let aDepth = 0; ancestor && aDepth < 4 && buttons.length === 0; aDepth++) {
        let sib = ancestor.previousElementSibling;
        let sibIdx = 0;
        while (sib && sibIdx < 5) {
          collectApprovalMatches(sib, buttons, seen);
          sib = sib.previousElementSibling;
          sibIdx++;
        }
        ancestor = ancestor.parentElement;
      }
    }

    if (buttons.length === 0) {
      const promptRoots = document.querySelectorAll(PROMPT_ROOT_SELECTORS.join(", "));
      for (const root of promptRoots) {
        if (isInExcludedZone(root)) continue;
        collectApprovalMatches(root, buttons, seen);
      }
    }

    if (buttons.length === 0 && inputBox) {
      let composerRoot = null;
      let node = inputBox;
      for (let i = 0; i < 8 && node && node !== document.body; i++) {
        const cn = (node.className || "").toString();
        if (/composer|chat|conversation/i.test(cn) || (node.id && /composer/i.test(node.id))) {
          composerRoot = node;
        }
        node = node.parentElement;
      }
      if (composerRoot) {
        collectApprovalMatches(composerRoot, buttons, seen);
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
    if (!_hasTrustedPromptContext(btn)) return null;
    if (btn.kind === "resume") return "resume";
    if (hasNearbyDismissal(btn.el)) return "dismiss";
    if (hasNearbyCompanion(btn.el)) return "companion";
    if (isModalSingleActionApprove(btn)) return "modal";
    return null;
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

  function checkAndClick() {
    _probeStructuredState();

    const buttons = findApprovalButtons();
    if (buttons.length === 0) return;

    const priority = { approval: 0, connection: 1, resume: 2 };

    const evaluated = buttons.map((btn) => ({
      ...btn,
      reason: _eligibilityReason(btn),
      fingerprint: _promptFingerprint(btn.el),
    }));

    const eligible = evaluated
      .filter((btn) => btn.reason !== null)
      .sort((a, b) => (priority[a.kind || "approval"] ?? 9) - (priority[b.kind || "approval"] ?? 9));

    const blocked = evaluated.filter((btn) => btn.reason === null && _hasTrustedPromptContext(btn));
    const unknown = evaluated.filter((btn) => btn.reason === null && !_hasTrustedPromptContext(btn));

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

    if (eligible.length === 0) return;

    const btn = eligible[0];

    if (_isCoolingDown(btn.fingerprint)) {
      console.log(`${LOG_PREFIX} skipping ${btn.id} (cooldown for fingerprint ${btn.fingerprint.slice(0, 20)})`);
      return;
    }

    const command = _extractCommandText(btn.el);
    const promptCapture = _capturePromptSubtree(btn.el);

    clickEl(btn.el);
    _markClicked(btn.fingerprint);
    state.totalClicks++;
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

  // -----------------------------------------------------------------------
  // MutationObserver: detect prompt surfaces immediately
  // -----------------------------------------------------------------------

  function _setupObserver() {
    if (state.observer) return;

    state.observer = new MutationObserver(() => {
      if (!state.running) return;
      if (state.observerDebounceTimer) clearTimeout(state.observerDebounceTimer);
      state.observerDebounceTimer = setTimeout(() => {
        state.observerDebounceTimer = null;
        checkAndClick();
      }, OBSERVER_DEBOUNCE_MS);
    });

    state.observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["role", "aria-modal", "class", "style", "disabled"],
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
    const emoji = state.running ? "\u2705" : "\u23F8";
    const title = `autoapprove ${emoji} ${REPO_SLUG}`;
    document.title = title;
    const titleButton = document.querySelector(
      '[id="workbench.parts.titlebar"] .window-title-text'
    );
    if (titleButton) {
      titleButton.textContent = title;
      titleButton.title = title;
      titleButton.setAttribute("aria-label", title);
    }
    const titleContainer = document.querySelector(
      '[id="workbench.parts.titlebar"] .window-title'
    );
    if (titleContainer) titleContainer.title = title;
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
      observerActive: !!state.observer,
      eventQueueLength: state.eventQueue.length,
      cooldownEntries: state.fingerprintCooldowns.size,
      visibleButtons: _debugButtons(),
      candidates,
      eligible: candidates.filter((c) => c.reason !== null),
      ts: new Date().toISOString(),
    };
  }

  // -----------------------------------------------------------------------
  // Start / stop / status
  // -----------------------------------------------------------------------

  function start(interval) {
    if (state.running) {
      console.log(`${LOG_PREFIX} already running`);
      return;
    }
    if (typeof interval === "number" && interval > 0) state.interval = interval;
    state.running = true;
    _setupObserver();
    state.timer = setInterval(checkAndClick, state.interval);
    _syncTitle();
    console.log(`${LOG_PREFIX} started (interval ${state.interval}ms, observer active)`);
    setTimeout(checkAndClick, 50);
  }

  function stop() {
    if (!state.running) {
      console.log(`${LOG_PREFIX} not running`);
      return;
    }
    clearInterval(state.timer);
    state.timer = null;
    _teardownObserver();
    state.running = false;
    _syncTitle();
    console.log(`${LOG_PREFIX} stopped (total clicks: ${state.totalClicks})`);
  }

  function status() {
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
      recentClicks: state.clicks.slice(-10),
    };
    console.log(`${LOG_PREFIX} status`, JSON.stringify(s, null, 2));
    return s;
  }

  // -----------------------------------------------------------------------
  // Bootstrap
  // -----------------------------------------------------------------------

  state.titleTimer = setInterval(_syncTitle, TITLE_SYNC_INTERVAL);
  _syncTitle();

  globalThis.__cursorAutoAccept = { start, stop, status, state };
  globalThis.startAccept = start;
  globalThis.stopAccept = stop;
  globalThis.acceptStatus = status;
  globalThis.acceptDebugSnapshot = debugSnapshot;

  console.log(
    `${LOG_PREFIX} loaded (${SCRIPT_HASH}) — startAccept() / stopAccept() / acceptStatus()`
  );
})();
