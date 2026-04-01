// Cursor Auto-Accept DOM Injector
// Paste into DevTools console of a dedicated agent Cursor window.
// Canonical DOM injector for the launch-cursor-autoapprove skill.
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
  const TITLE_SYNC_INTERVAL = 3000;

  const APPROVAL_PATTERNS = [
    { pattern: "accept all", id: "accept_all" },
    { pattern: "accept", id: "accept" },
    { pattern: "always allow", id: "always_allow" },
    { pattern: "allow", id: "allow" },
    { pattern: "run command", id: "run_command" },
    { pattern: "run", id: "run" },
    { pattern: "apply", id: "apply" },
    { pattern: "execute", id: "execute" },
  ];

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

  function matchesApproval(el) {
    if (!el || !el.textContent) return null;
    const text = el.textContent.toLowerCase().trim();
    for (const { pattern, id } of APPROVAL_PATTERNS) {
      if (text.includes(pattern) && isVisible(el) && isClickable(el)) {
        return { id, text: el.textContent.trim() };
      }
    }
    return null;
  }

  function findButtonsInElement(root) {
    const selectors = [
      "button",
      'div[class*="button"]',
      'div[style*="cursor: pointer"]',
      'div[style*="cursor:pointer"]',
      '[class*="primary-button"]',
      '[class*="secondary-button"]',
      '[class*="text-button"]',
    ];
    const results = [];
    for (const sel of selectors) {
      for (const el of root.querySelectorAll(sel)) {
        const m = matchesApproval(el);
        if (m) results.push({ el, ...m });
      }
    }
    const m = matchesApproval(root);
    if (m) results.push({ el: root, ...m });
    return results;
  }

  function findApprovalButtons() {
    const buttons = [];

    const inputBox = document.querySelector("div.full-input-box");
    if (inputBox) {
      let sib = inputBox.previousElementSibling;
      let depth = 0;
      while (sib && depth < 5) {
        buttons.push(...findButtonsInElement(sib));
        sib = sib.previousElementSibling;
        depth++;
      }
    }

    if (buttons.length === 0) {
      const all = document.querySelectorAll("button, div[class*='button']");
      for (const el of all) {
        const m = matchesApproval(el);
        if (m) buttons.push({ el, ...m });
      }
    }

    if (state.enableResume) {
      const resumeLinks = document.querySelectorAll(
        `a[data-link="${RESUME_DATA_LINK}"], [class*="markdown-link"][data-link="${RESUME_DATA_LINK}"]`
      );
      for (const el of resumeLinks) {
        if (isVisible(el)) {
          buttons.push({ el, id: "resume_conversation", text: el.textContent.trim() });
        }
      }
    }

    if (state.enableConnectionRetry) {
      const containers = document.querySelectorAll(
        '[class*="dropdown"], [class*="popover"], [class*="dialog"]'
      );
      for (const container of containers) {
        const text = container.textContent.toLowerCase();
        if (
          text.includes("connection failed") ||
          text.includes("internet") ||
          text.includes("vpn")
        ) {
          for (const btn of container.querySelectorAll("button")) {
            const t = btn.textContent.toLowerCase().trim();
            if (t === "resume" || t === "try again") {
              if (isVisible(btn) && isClickable(btn)) {
                buttons.push({
                  el: btn,
                  id: t === "resume" ? "connection_resume" : "connection_try_again",
                  text: btn.textContent.trim(),
                });
              }
            }
          }
        }
      }
    }

    return buttons;
  }

  function clickEl(el) {
    const r = el.getBoundingClientRect();
    const x = r.left + r.width / 2;
    const y = r.top + r.height / 2;
    const opts = { bubbles: true, cancelable: true, view: window, clientX: x, clientY: y };

    try {
      el.dispatchEvent(new PointerEvent("pointerdown", { ...opts, pointerType: "mouse" }));
    } catch (_) {}
    el.dispatchEvent(new MouseEvent("mousedown", opts));
    el.click();
    el.dispatchEvent(new MouseEvent("click", opts));
    el.dispatchEvent(new MouseEvent("mouseup", opts));
    try {
      el.dispatchEvent(new PointerEvent("pointerup", { ...opts, pointerType: "mouse" }));
    } catch (_) {}

    if (el.focus) el.focus();
    el.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", code: "Enter", keyCode: 13, bubbles: true })
    );
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

  function checkAndClick() {
    const buttons = findApprovalButtons();
    if (buttons.length === 0) return;

    const btn = buttons[0];
    clickEl(btn.el);
    state.totalClicks++;
    const entry = { ts: new Date().toISOString(), id: btn.id, text: btn.text };
    state.clicks.push(entry);
    if (state.clicks.length > 100) {
      state.clicks = state.clicks.slice(-100);
    }
    console.log(`${LOG_PREFIX} clicked ${btn.id}: "${btn.text}" (total: ${state.totalClicks})`);
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

  console.log(`${LOG_PREFIX} loaded (${SCRIPT_HASH}) — startAccept() / stopAccept() / acceptStatus()`);
})();
