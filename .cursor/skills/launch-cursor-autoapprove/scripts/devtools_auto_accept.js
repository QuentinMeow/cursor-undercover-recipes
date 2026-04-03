// Cursor Auto-Accept DOM Injector
// Injected by launcher.py via CDP Runtime.evaluate.
// Canonical DOM injector for the launch-cursor-autoapprove skill.
// Manual DevTools paste is emergency fallback only.
// Originally adapted from ivalsaraj/true-yolo-cursor-auto-accept-full-agentic-mode,
// then narrowed to Cursor approval surfaces with structured logging.
//
// API:  startAccept()  stopAccept()  acceptStatus()
(function () {
  "use strict";

  if (globalThis.__cursorAutoAccept) {
    console.log("[autoAccept] already loaded — use startAccept() / stopAccept()");
    return;
  }

  const LOG_PREFIX = "[autoAccept]";
  const SCRIPT_HASH = globalThis.__cursorAutoAcceptScriptHash || "unknown";
  const REPO_SLUG = globalThis.__cursorAutoAcceptRepoSlug || "workspace";
  const STRATEGY_VERSION = "2026-04-context-first";
  const TITLE_SYNC_INTERVAL = 3000;

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
  ];
  const PROMPT_ROOT_SELECTORS = [
    '[role="dialog"]',
    '[role="alertdialog"]',
    '[aria-modal="true"]',
  ];
  const DISMISS_PATTERNS = new Set(["skip", "cancel", "dismiss", "deny", "not now", "close", "reject", "don't allow", "decline"]);
  const COMPANION_PATTERNS = new Set(["view", "stop", "details", "show details"]);

  const RESUME_DATA_LINK = "command:composer.resumeCurrentChat";

  const state = {
    scriptHash: SCRIPT_HASH,
    repoSlug: REPO_SLUG,
    interval: 2000,
    running: false,
    timer: null,
    titleTimer: null,
    totalClicks: 0,
    clicks: [],
    enableResume: true,
    enableConnectionRetry: true,
  };

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
      if (el.closest(sel)) return true;
    }
    return false;
  }

  function stripKeyboardHints(text) {
    return text
      .replace(/\s*\([⌃⌥⇧⌘⎋⏎↩\s\w]{1,6}\)\s*$/, "")
      .replace(/[\s\u21A9\u23CE\u21E7\u2318\u2325\u238B\u232B\u2326\u21E5]+$/, "")
      .trim();
  }

  function normalizeLabel(text) {
    return stripKeyboardHints(text.toLowerCase().trim());
  }

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
    const surface = el.closest(
      '[class*="composer"], [class*="chat"], [class*="conversation"], [id*="composer"]'
    );
    if (!surface) return false;
    return !!surface.querySelector("div.full-input-box");
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
      let sib = inputBox.previousElementSibling;
      let depth = 0;
      while (sib && depth < 5) {
        collectApprovalMatches(sib, buttons, seen);
        sib = sib.previousElementSibling;
        depth++;
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
      const composerRoot = inputBox.closest(
        '[class*="composer"], [class*="chat"], [class*="conversation"], [id*="composer"]'
      );
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
    const candidates = findApprovalButtons().map((btn) => ({
      kind: btn.kind || "approval",
      id: btn.id || "",
      text: btn.text || "",
      reason: _eligibilityReason(btn),
      surface: _debugSurface(btn.el),
      inExcludedZone: isInExcludedZone(btn.el),
      hasDismissNearby: hasNearbyDismissal(btn.el),
      hasCompanionNearby: hasNearbyCompanion(btn.el),
      isModalSingleActionApprove: isModalSingleActionApprove(btn),
    }));
    return {
      strategyVersion: STRATEGY_VERSION,
      scriptHash: state.scriptHash,
      running: state.running,
      totalClicks: state.totalClicks,
      visibleButtons: _debugButtons(),
      candidates,
      eligible: candidates.filter((c) => c.reason !== null),
      ts: new Date().toISOString(),
    };
  }

  function checkAndClick() {
    const buttons = findApprovalButtons();
    if (buttons.length === 0) return;
    const priority = { approval: 0, connection: 1, resume: 2 };
    const eligible = buttons
      .map((btn) => ({ ...btn, reason: _eligibilityReason(btn) }))
      .filter((btn) => btn.reason !== null)
      .sort((a, b) => (priority[a.kind || "approval"] ?? 9) - (priority[b.kind || "approval"] ?? 9));
    if (eligible.length === 0) return;

    const btn = eligible[0];
    clickEl(btn.el);
    state.totalClicks++;
    const entry = { ts: new Date().toISOString(), kind: btn.kind || "approval", id: btn.id, text: btn.text, reason: btn.reason };
    state.clicks.push(entry);
    if (state.clicks.length > 100) {
      state.clicks = state.clicks.slice(-100);
    }
    console.log(`${LOG_PREFIX} clicked ${btn.id}: "${btn.text}" [${btn.reason}] (total: ${state.totalClicks})`);
  }

  function start(interval) {
    if (state.running) {
      console.log(`${LOG_PREFIX} already running`);
      return;
    }
    if (typeof interval === "number" && interval > 0) state.interval = interval;
    state.running = true;
    state.timer = setInterval(checkAndClick, state.interval);
    _syncTitle();
    console.log(`${LOG_PREFIX} started (interval ${state.interval}ms)`);
  }

  function stop() {
    if (!state.running) {
      console.log(`${LOG_PREFIX} not running`);
      return;
    }
    clearInterval(state.timer);
    state.timer = null;
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
      recentClicks: state.clicks.slice(-10),
    };
    console.log(`${LOG_PREFIX} status`, JSON.stringify(s, null, 2));
    return s;
  }

  state.titleTimer = setInterval(_syncTitle, TITLE_SYNC_INTERVAL);
  _syncTitle();

  globalThis.__cursorAutoAccept = { start, stop, status, state };
  globalThis.startAccept = start;
  globalThis.stopAccept = stop;
  globalThis.acceptStatus = status;
  globalThis.acceptDebugSnapshot = debugSnapshot;

  console.log(`${LOG_PREFIX} loaded (${SCRIPT_HASH}) — startAccept() / stopAccept() / acceptStatus()`);
})();
