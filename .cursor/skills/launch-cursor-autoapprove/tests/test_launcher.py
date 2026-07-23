from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


LAUNCHER_PATH = Path(__file__).parents[1] / "scripts" / "launcher.py"
INJECTOR_PATH = Path(__file__).parents[1] / "scripts" / "devtools_auto_accept.js"
SPEC = importlib.util.spec_from_file_location("launch_autoapprove_launcher", LAUNCHER_PATH)
assert SPEC and SPEC.loader
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class InjectorSourceTests(unittest.TestCase):
    def test_subagent_cycling_is_enabled_in_initial_renderer_state(self) -> None:
        source = INJECTOR_PATH.read_text()
        state_start = source.index("const state = {")
        state_end = source.index("\n  };", state_start)
        initial_state = source[state_start:state_end]

        self.assertIn("cycleEnabled: true,", initial_state)
        self.assertNotIn("cycleEnabled: false,", initial_state)

    def test_failed_task_stays_failed_while_approval_remains_visible(self) -> None:
        source = INJECTOR_PATH.read_text()
        function_start = source.index("function _deriveTaskStatus(")
        function_end = source.index("\n  function ", function_start)
        derive_status = source[function_start:function_end]

        self.assertIn(
            'return existingStatus === "failed" ? "failed" : "approval_pending";',
            derive_status,
        )
        self.assertNotIn(
            'if (_visibleRowApproval(row)) return "approval_pending";',
            derive_status,
        )

    def test_registered_row_recovery_targets_only_current_composer(self) -> None:
        source = INJECTOR_PATH.read_text()
        active_start = source.index("function _activeSubagentRecords(")
        active_end = source.index("\n  function ", active_start)
        active_records = source[active_start:active_end]

        self.assertIn("const virtualizer = _getVirtualizerSnapshot();", active_records)
        self.assertIn("virtualizer.snapshot.composerId", active_records)
        self.assertIn(
            "record.parentComposerId === currentComposerId",
            active_records,
        )

    def test_direct_and_cycle_paths_share_bounded_candidate_ownership(self) -> None:
        source = INJECTOR_PATH.read_text()

        ownership_start = source.index("function _isCycleOwnedSubagentCandidate(")
        ownership_end = source.index("\n  function ", ownership_start)
        ownership = source[ownership_start:ownership_end]
        self.assertIn("if (!btn?.el) return false;", ownership)
        self.assertIn("if (state.cycleActive && navigationScope)", ownership)
        self.assertNotIn("navigationScope.group.contains(btn.el)", ownership)
        self.assertIn("if (!state.cycleEnabled) return false;", ownership)
        self.assertIn("const task = _taskForRow(row);", ownership)
        self.assertIn("state.registeredApprovalOwnerTaskKey !== null", ownership)
        self.assertIn(
            "task.taskKey === state.registeredApprovalOwnerTaskKey",
            ownership,
        )

        scanner_start = source.index("function _checkAndClickImpl(")
        scanner_end = source.index("\n  function ", scanner_start)
        scanner = source[scanner_start:scanner_end]
        self.assertIn(
            "cycleOwned: _isCycleOwnedSubagentCandidate(btn),",
            scanner,
        )
        self.assertIn("!btn.cycleOwned &&", scanner)
        self.assertIn("!btn.directRetryExhausted", scanner)
        self.assertIn(
            "state.directRegisteredApprovalAttempts.set(btn.fingerprint",
            scanner,
        )
        self.assertIn(
            "state.directRegisteredApprovalAttempts.size > 200",
            scanner,
        )

        debug_start = source.index("function debugSnapshot(")
        debug_end = source.index("\n  function ", debug_start)
        debug_snapshot = source[debug_start:debug_end]
        self.assertIn(
            "cycleOwned: _isCycleOwnedSubagentCandidate(btn),",
            debug_snapshot,
        )
        self.assertIn("!c.cycleOwned &&", debug_snapshot)
        self.assertIn("!c.directRetryExhausted", debug_snapshot)
        self.assertIn("directRetryExhausted:", debug_snapshot)
        navigation_start = source.index("async function _attemptNavigatedApproval(")
        navigation_end = source.index("\n  async function ", navigation_start)
        navigation_attempt = source[navigation_start:navigation_end]
        row_attempt_start = source.index("async function _attemptSubagentApproval(")
        row_attempt_end = source.index("\n  function ", row_attempt_start)
        row_attempt = source[row_attempt_start:row_attempt_end]
        scoped_start = source.index("function _scopedCycleCandidate(")
        scoped_end = source.index("\n  function ", scoped_start)
        scoped_candidate = source[scoped_start:scoped_end]
        cycle_start = source.index("async function runSubagentCycle(")
        cycle_end = source.index("\n  function ", cycle_start)
        cycle = source[cycle_start:cycle_end]
        self.assertIn("state.navigationApprovalScope = {", navigation_attempt)
        self.assertNotIn("state.navigationApprovalScope = null", navigation_attempt)
        self.assertIn("state.navigationApprovalScope = null;", cycle)
        self.assertIn("function _beginNavigationApprovalScope(", source)
        self.assertIn(
            "state.registeredApprovalOwnerTaskKey = record.taskKey;",
            row_attempt,
        )
        self.assertIn(
            "state.registeredApprovalOwnerTaskKey = null;",
            row_attempt,
        )
        self.assertIn("} finally {", row_attempt)
        self.assertIn(
            "candidate.fingerprint = _promptFingerprint(candidate.el);",
            scoped_candidate,
        )

    def test_scanner_skips_cooling_candidates_before_selecting_one(self) -> None:
        source = INJECTOR_PATH.read_text()
        scanner_start = source.index("function _checkAndClickImpl(")
        scanner_end = source.index("\n  function ", scanner_start)
        scanner = source[scanner_start:scanner_end]

        self.assertIn(
            "const btn = eligible.find((candidate) => "
            "!_isCoolingDown(candidate.fingerprint));",
            scanner,
        )
        self.assertIn("if (!btn) return;", scanner)
        self.assertNotIn("const btn = eligible[0];", scanner)
        self.assertNotIn("if (_isCoolingDown(btn.fingerprint))", scanner)

    def test_direct_scanner_checks_all_mounted_composer_surfaces(self) -> None:
        source = INJECTOR_PATH.read_text()
        find_start = source.index("function findApprovalButtons(")
        find_end = source.index("\n  function ", find_start)
        find_buttons = source[find_start:find_end]
        surface_start = source.index("function _isComposerSurface(")
        surface_end = source.index("\n  function ", surface_start)
        composer_surface = source[surface_start:surface_end]

        self.assertIn(
            'const inputBoxes = Array.from(document.querySelectorAll("div.full-input-box"));',
            find_buttons,
        )
        self.assertIn("for (const inputBox of inputBoxes)", find_buttons)
        self.assertIn(
            'const inputBoxes = document.querySelectorAll("div.full-input-box");',
            composer_surface,
        )
        self.assertNotIn(
            'document.querySelector("div.full-input-box")',
            composer_surface,
        )

    def test_cycle_visits_running_subagent_tray_and_restores_editor_tabs(self) -> None:
        source = INJECTOR_PATH.read_text()
        header_start = source.index("function _runningSubagentTrayHeaders(")
        header_end = source.index("\n  function ", header_start)
        tray_headers = source[header_start:header_end]
        tray_start = source.index("function _runningSubagentTrayEntries(")
        tray_end = source.index("\n  function ", tray_start)
        tray_discovery = source[tray_start:tray_end]
        bounds_start = source.index("function _boundedRunningSubagentTrayEntries(")
        bounds_end = source.index("\n  function ", bounds_start)
        tray_bounds = source[bounds_start:bounds_end]
        advance_start = source.index("function _advanceRunningSubagentTrayCursor(")
        advance_end = source.index("\n  function ", advance_start)
        tray_advance = source[advance_start:advance_end]
        wait_start = source.index("async function _waitForSelectedSubagentGroup(")
        wait_end = source.index("\n  function ", wait_start)
        wait_for_group = source[wait_start:wait_end]
        candidate_wait_start = source.index("function _waitForTrayCandidates(")
        candidate_wait_end = source.index("\n  function ", candidate_wait_start)
        wait_for_candidate = source[candidate_wait_start:candidate_wait_end]
        tail_start = source.index("function _materializeNavigatedTranscriptTail(")
        tail_end = source.index("\n  function ", tail_start)
        materialize_tail = source[tail_start:tail_end]
        attempt_start = source.index("async function _attemptNavigatedApprovalImpl(")
        attempt_end = source.index("\n  function ", attempt_start)
        attempt = source[attempt_start:attempt_end]
        eligibility_start = source.index("function _trayEligibilityReason(")
        eligibility_end = source.index("\n  function ", eligibility_start)
        tray_eligibility = source[eligibility_start:eligibility_end]
        cycle_start = source.index("async function runSubagentCycle(")
        cycle_end = source.index("\n  function ", cycle_start)
        cycle = source[cycle_start:cycle_end]

        self.assertIn("SUBAGENT_TRAY_HEADER_PATTERN.test(headerText)", tray_headers)
        self.assertIn("SUBAGENT_TRAY_ITEM_SELECTOR", tray_discovery)
        self.assertIn("!isVisible(item)", tray_discovery)
        self.assertIn("_boundedRunningSubagentTrayEntries(entries)", tray_discovery)
        self.assertIn("CYCLE_MAX_TRAY_ITEMS", tray_bounds)
        self.assertNotIn("state.trayCursor =", tray_bounds)
        self.assertIn("Math.min(processedCount, entryCount)", tray_advance)
        self.assertIn('group.querySelector("div.conversations")', wait_for_group)
        self.assertNotIn('group.querySelector("div.full-input-box")', wait_for_group)
        self.assertIn("new MutationObserver(", wait_for_candidate)
        self.assertIn("CYCLE_TRAY_MIN_CANDIDATE_WAIT_MS", wait_for_candidate)
        self.assertIn("CYCLE_TRAY_QUIET_MS", wait_for_candidate)
        self.assertIn("CYCLE_TRAY_CANDIDATE_TIMEOUT_MS", wait_for_candidate)
        self.assertIn(
            "_materializeNavigatedTranscriptTail(target, readiness)",
            wait_for_candidate,
        )
        self.assertIn("SCROLL_CONTAINER_SELECTOR", materialize_tail)
        self.assertIn("_setProgrammaticScroll(container, bottom)", materialize_tail)
        self.assertIn(
            '"transcript_tail_stable_without_candidate"',
            wait_for_candidate,
        )
        self.assertIn("tailPulses: readiness.tailPulses", wait_for_candidate)
        self.assertIn(
            "const waitResult = await _waitForTrayCandidates(target);",
            attempt,
        )
        self.assertIn("type: `${source}_no_candidate`", attempt)
        self.assertIn("group?.contains(candidate.el)", tray_eligibility)
        self.assertIn(
            "hasNearbyDismissal(candidate.el, { allowExcluded: true })",
            tray_eligibility,
        )
        self.assertIn(
            "const match = matchesApproval(el, { allowExcluded: true });",
            source,
        )
        self.assertIn(
            "let trayEntries = _runningSubagentTrayEntries({ bounded: false });",
            cycle,
        )
        self.assertEqual(
            cycle.count("_runningSubagentTrayEntries({ bounded: false })"),
            2,
        )
        self.assertIn("await _visitSubagentTrayEntry(", cycle)
        self.assertLess(
            cycle.index("for (const entry of trayEntries)"),
            cycle.index("if (!context && records.length > 0)"),
        )
        self.assertIn("await _restoreEditorSelectionContext(", cycle)
        self.assertIn("_activateEditorTab(tab);", source)

    def test_tray_approval_retries_are_bounded(self) -> None:
        source = INJECTOR_PATH.read_text()
        attempt_start = source.index("async function _attemptNavigatedApprovalImpl(")
        attempt_end = source.index("\n  function ", attempt_start)
        attempt = source[attempt_start:attempt_end]
        exhaust_start = source.index("function _markNavigatedAttemptExhausted(")
        exhaust_end = source.index("\n  function ", exhaust_start)
        exhaust = source[exhaust_start:exhaust_end]
        filter_start = source.index("function _filterNavigationBackoff(")
        filter_end = source.index("\n  function ", filter_start)
        backoff_filter = source[filter_start:filter_end]
        cycle_start = source.index("async function runSubagentCycle(")
        cycle_end = source.index("\n  function ", cycle_start)
        cycle = source[cycle_start:cycle_end]

        self.assertIn(
            "previous.attempts >= CYCLE_TRAY_MAX_ATTEMPTS",
            attempt,
        )
        self.assertIn("previous.failed = true;", exhaust)
        self.assertIn("reason: `${source}_retry_exhausted`", attempt)
        self.assertIn("_navigatedApprovalAttempts(source)", attempt)
        self.assertIn("CYCLE_EXHAUSTED_PROBE_BASE_MS", exhaust)
        self.assertIn("CYCLE_EXHAUSTED_PROBE_MAX_MS", exhaust)
        self.assertIn("nextProbeAt", backoff_filter)
        self.assertIn(
            "_filterNavigationBackoff(eligibleTrayEntries, \"tray\")",
            cycle,
        )
        self.assertIn(
            "_filterNavigationBackoff(pinnedEntries, \"pinned\")",
            cycle,
        )
        self.assertIn('result.outcome === "deferred"', cycle)
        self.assertIn("onlyDeferredNavigation", cycle)
        self.assertNotIn(
            "summary.trayDeferred > 0 ||",
            cycle[cycle.index("const needsSoonerRetry ="):],
        )

    def test_empty_child_mounts_are_backed_off_after_tail_readiness_wait(self) -> None:
        source = INJECTOR_PATH.read_text()
        record_start = source.index("function _recordNavigatedEmptyBackoff(")
        record_end = source.index("\n  function ", record_start)
        record = source[record_start:record_end]
        attempt_start = source.index("async function _attemptNavigatedApprovalImpl(")
        attempt_end = source.index("\n  function ", attempt_start)
        attempt = source[attempt_start:attempt_end]

        self.assertIn("CYCLE_EMPTY_PROBE_BASE_MS", record)
        self.assertIn("CYCLE_EMPTY_PROBE_MAX_MS", record)
        self.assertIn("noCandidate: true", record)
        self.assertIn("_clearNavigatedAttemptsForTarget(", record)
        self.assertIn(
            "_recordNavigatedEmptyBackoff(attemptsMap, target)",
            attempt,
        )
        self.assertIn('outcome: paused ? "paused" : missed ? "miss" : "deferred"', attempt)
        self.assertIn("conversationMounted: waitResult.conversationMounted", attempt)
        self.assertIn("tailContainerCount: waitResult.tailContainerCount", attempt)
        self.assertIn("tailPulses: waitResult.tailPulses", attempt)

    def test_renderer_heap_safety_limit_is_four_gib(self) -> None:
        source = INJECTOR_PATH.read_text()
        launcher_source = LAUNCHER_PATH.read_text()

        self.assertIn(
            "const MAX_JS_HEAP_BYTES = 4 * 1024 * 1024 * 1024;",
            source,
        )
        self.assertNotIn(
            "const MAX_JS_HEAP_BYTES = 768 * 1024 * 1024;",
            source,
        )
        self.assertIn("maxJSHeapBytes: MAX_JS_HEAP_BYTES", source)
        self.assertIn('"maxJSHeapBytes"', launcher_source)
        self.assertIn("MiB limit", launcher_source)

    def test_collapsed_tray_is_expanded_and_entries_are_reresolved(self) -> None:
        source = INJECTOR_PATH.read_text()
        headers_start = source.index("function _runningSubagentTrayHeaders(")
        headers_end = source.index("\n  function ", headers_start)
        headers = source[headers_start:headers_end]
        ensure_start = source.index("async function _ensureRunningSubagentTrayExpanded(")
        ensure_end = source.index("\n  async function ", ensure_start)
        ensure = source[ensure_start:ensure_end]
        ready_start = source.index("function _subagentTrayEntriesReady(")
        ready_end = source.index("\n  function ", ready_start)
        ready = source[ready_start:ready_end]
        signature_start = source.index("function _subagentTrayExpansionSignature(")
        signature_end = source.index("\n  function ", signature_start)
        signature = source[signature_start:signature_end]
        resolve_start = source.index("async function _resolveRunningSubagentTrayEntry(")
        resolve_end = source.index("\n  async function ", resolve_start)
        resolve = source[resolve_start:resolve_end]
        restore_start = source.index(
            "async function _restoreSubagentTrayExpansionContext("
        )
        restore_end = source.index("\n  function ", restore_start)
        restore = source[restore_start:restore_end]
        visit_start = source.index("async function _visitSubagentTrayEntry(")
        visit_end = source.index("\n  async function ", visit_start)
        visit = source[visit_start:visit_end]
        cycle_start = source.index("async function runSubagentCycle(")
        cycle_end = source.index("\n  function ", cycle_start)
        cycle = source[cycle_start:cycle_end]

        self.assertIn("SUBAGENT_TRAY_HEADER_PATTERN.test(headerText)", headers)
        self.assertIn("_subagentTrayHeaderExpanded(header, block)", headers)
        self.assertIn("_activateNavigationElement(headers[0].header);", ensure)
        self.assertIn("CYCLE_TRAY_EXPAND_TIMEOUT_MS", ensure)
        self.assertIn("_runningSubagentTrayEntries({ bounded: false })", ensure)
        self.assertIn('reason: "tray_header_ambiguous"', ensure)
        self.assertIn("_subagentTrayExpansionBackoff(headers[0])", ensure)
        self.assertIn("_recordSubagentTrayExpansionFailure(", ensure)
        self.assertIn("CYCLE_TRAY_EXPAND_MAX_FAILURES", source)
        self.assertIn('"tray_expand_retry_exhausted"', ensure)
        self.assertIn("parentIdentity", signature)
        self.assertIn("state.trayParentIds.get(parentTab)", signature)
        self.assertNotIn("header.expanded", signature)
        self.assertIn("_subagentTrayEntriesReady(headers[0], entries)", ensure)
        self.assertIn("header.mounted >= header.advertised", ready)
        self.assertIn('"tray_items_partially_mounted"', ensure)
        self.assertLess(
            ensure.index("let headers = _runningSubagentTrayHeaders();"),
            ensure.index("let entries = _runningSubagentTrayEntries({ bounded: false });"),
        )
        self.assertIn(
            "const prepared = await _ensureRunningSubagentTrayExpanded(options);",
            resolve,
        )
        self.assertIn("normalizeLabel(candidate.title) === wanted", resolve)
        self.assertIn(
            "const resolved = await _resolveRunningSubagentTrayEntry(entry, options);",
            visit,
        )
        self.assertNotIn("if (!entry.item.isConnected)", visit)
        self.assertIn("currentEntry.item", visit)
        self.assertIn("let trayHeaders = _runningSubagentTrayHeaders();", cycle)
        self.assertIn(
            "trayExpansionContext = _captureSubagentTrayExpansionContext();",
            cycle,
        )
        self.assertIn("if (!trayExpansionContext.ok) {", cycle)
        self.assertIn(
            "_boundedRunningSubagentTrayEntries(\n"
            "                  filteredTrayEntries.entries",
            cycle,
        )
        self.assertIn("_uniquelyTitledRunningSubagentTrayEntries(", cycle)
        self.assertIn("CYCLE_TRAY_MAX_DURATION_MS", cycle)
        self.assertIn("const rowStartedPerformance = performance.now();", cycle)
        self.assertIn("trayEntriesProcessed++;", cycle)
        self.assertIn("_advanceRunningSubagentTrayCursor(", cycle)
        self.assertIn(
            "await _restoreSubagentTrayExpansionContext(",
            cycle,
        )
        self.assertIn('reason: "tray_restore_parent_changed"', source)
        self.assertIn("_editorTabResourceKey(parentTab)", source)
        self.assertIn("type: \"tray_restore\"", restore)
        self.assertIn("changed: false", restore)
        self.assertEqual(source.count('"tray_expansion_not_restored"'), 1)
        self.assertIn('source: "tray_between_visits"', cycle)
        self.assertLess(
            cycle.index("const betweenVisitRestore = await _restoreEditorSelectionContext("),
            cycle.index("const afterTrayTakeover = _navigationTakeoverReason("),
        )

    def test_cycle_visits_and_restores_pinned_top_level_agents(self) -> None:
        source = INJECTOR_PATH.read_text()
        discovery_start = source.index("function _pinnedAgentEntries(")
        discovery_end = source.index("\n  function ", discovery_start)
        discovery = source[discovery_start:discovery_end]
        visit_start = source.index("async function _visitPinnedAgentEntry(")
        visit_end = source.index("\n  function ", visit_start)
        visit = source[visit_start:visit_end]
        restore_start = source.index(
            "async function _restoreAgentSidebarSelectionContext("
        )
        restore_end = source.index("\n  function ", restore_start)
        restore = source[restore_start:restore_end]
        cycle_start = source.index("async function runSubagentCycle(")
        cycle_end = source.index("\n  function ", cycle_start)
        cycle = source[cycle_start:cycle_end]
        wait_start = source.index("function _waitForTrayCandidates(")
        wait_end = source.index("\n  function ", wait_start)
        candidate_wait = source[wait_start:wait_end]
        raw_check_start = source.index(
            "function _rawNavigatedApprovalStillPresent("
        )
        raw_check_end = source.index("\n  function ", raw_check_start)
        raw_check = source[raw_check_start:raw_check_end]

        self.assertIn("PINNED_AGENT_SECTION_PATTERN.test(sectionTitle)", discovery)
        self.assertIn('item.getAttribute("data-selected") === "true"', discovery)
        self.assertIn("!!item.querySelector(PINNED_AGENT_ACTIVE_SELECTOR)", discovery)
        self.assertIn(
            "entry.ambiguous = titleCounts.get(normalizeLabel(entry.title)) !== 1",
            discovery,
        )
        self.assertIn("const titleCounts = new Map();", discovery)
        self.assertIn("for (const entry of raw)", discovery)
        self.assertIn("raw.filter((entry) => !entry.ambiguous)", discovery)
        self.assertIn(
            'const item = _uniqueAgentSidebarRow(title, "Pinned");',
            source,
        )
        self.assertIn("_resolvePinnedAgentEntry(entry.title", visit)
        self.assertGreaterEqual(visit.count("_resolvePinnedAgentEntry("), 2)
        self.assertIn("_activateAgentSidebarRow(resolved.item);", visit)
        self.assertLess(
            visit.index("_beginNavigationApprovalScope("),
            visit.index("_activateAgentSidebarRow(resolved.item);"),
        )
        self.assertIn("_navigationTakeoverReason(options)", visit)
        self.assertIn("CYCLE_PINNED_MOUNT_TIMEOUT_MS", visit)
        self.assertIn("_navigationTakeoverReason(target)", candidate_wait)
        self.assertIn("target.selectionElement.getAttribute", source)
        self.assertIn("await _attemptNavigatedApproval(", visit)
        self.assertIn(
            "_uniqueAgentSidebarRow(context.title, context.sectionTitle)",
            restore,
        )
        self.assertIn("_activateAgentSidebarRow(row);", restore)
        self.assertIn("selected.targetKey !== context.resourceKey", restore)
        self.assertIn("shouldPreserveUserSelection()", restore)
        self.assertIn("normalizeLabel(text) !== normalizeLabel(candidate.text)", raw_check)
        self.assertNotIn("isVisible(", raw_check)
        self.assertNotIn("isClickable(", raw_check)
        self.assertIn("activeOnly: !explicit", cycle)
        self.assertIn("if (!explicit && document.hasFocus()) pinnedEntries = [];", cycle)
        self.assertIn("await _visitPinnedAgentEntry(entry, {", cycle)
        self.assertIn('if (result.outcome === "paused") {', cycle)
        self.assertIn("preserveUserSelection = true;", cycle)
        self.assertIn("if (!abortAfterPinned) {", cycle)
        self.assertIn("CYCLE_PINNED_MAX_DURATION_MS", cycle)
        self.assertIn("const trayStartedPerformance = performance.now();", cycle)
        self.assertIn("const rowStartedPerformance = performance.now();", cycle)
        self.assertIn("{ preserveOnInteraction: true }", cycle)
        self.assertIn("_visitSubagentTrayEntry(", cycle)
        self.assertIn("navigationOptions", cycle)
        pinned_loop = cycle.index("for (const entry of pinnedEntries)")
        self.assertLess(
            pinned_loop,
            cycle.index("_getVirtualizerSnapshot(true);", pinned_loop),
        )

    def test_navigated_confirmation_requires_raw_control_absence(self) -> None:
        source = INJECTOR_PATH.read_text()
        attempt_start = source.index("async function _attemptNavigatedApprovalImpl(")
        attempt_end = source.index("\n  function ", attempt_start)
        attempt = source[attempt_start:attempt_end]
        raw_start = source.index("function _rawNavigatedApprovalStillPresent(")
        raw_end = source.index("\n  function ", raw_start)
        raw_check = source[raw_start:raw_end]

        self.assertIn("normalizeLabel(text) !== normalizeLabel(candidate.text)", raw_check)
        self.assertNotIn("_trayCandidates(", raw_check)
        self.assertIn("let consecutiveAbsentChecks = 0;", attempt)
        self.assertIn("_rawNavigatedApprovalStillPresent(", attempt)
        self.assertIn("if (consecutiveAbsentChecks >= 2)", attempt)

    def test_row_materialization_rolls_back_on_user_takeover(self) -> None:
        source = INJECTOR_PATH.read_text()
        materialize_start = source.index("async function _materializeSubagentRow(")
        materialize_end = source.index("\n  function ", materialize_start)
        materialize = source[materialize_start:materialize_end]
        attempt_start = source.index("async function _attemptSubagentApproval(")
        attempt_end = source.index("\n  function ", attempt_start)
        attempt = source[attempt_start:attempt_end]

        self.assertIn("_navigationTakeoverReason(options)", materialize)
        self.assertIn("result.scrollDelta =", materialize)
        self.assertIn("_rollbackMaterializationScroll(context, result);", materialize)
        self.assertIn("_rollbackMaterializationScroll(context, materialized);", attempt)

    def test_automatic_cycle_pauses_while_terminal_or_editor_is_focused(self) -> None:
        source = INJECTOR_PATH.read_text()
        focus_start = source.index("function _activeEditingSurfaceBlockReason(")
        focus_end = source.index("\n  function ", focus_start)
        focus_guard = source[focus_start:focus_end]
        block_start = source.index("function _cycleBlockReason(")
        block_end = source.index("\n  function ", block_start)
        cycle_block = source[block_start:block_end]
        interaction_start = source.index("function _setupInteractionGuard(")
        interaction_end = source.index("\n  function ", interaction_start)
        interaction_guard = source[interaction_start:interaction_end]

        self.assertIn("textarea.xterm-helper-textarea", focus_guard)
        self.assertIn('return "terminal_focused";', focus_guard)
        self.assertIn('return editable && !composerEditable ? "editor_focused"', focus_guard)
        self.assertIn(
            "const focusReason = _activeEditingSurfaceBlockReason();",
            cycle_block,
        )
        self.assertIn("if (focusReason) return focusReason;", cycle_block)
        self.assertIn(
            '["pointerdown", "keydown", "wheel"]',
            interaction_guard,
        )
        self.assertNotIn('"scroll"', interaction_guard)

    def test_cycle_focus_restoration_preserves_newer_user_focus(self) -> None:
        source = INJECTOR_PATH.read_text()
        restore_start = source.index("function _settleFocusAfterAutomation(")
        restore_end = source.index("\n  function ", restore_start)
        restore_focus = source[restore_start:restore_end]
        scroll_start = source.index("function _restoreScrollContext(")
        scroll_end = source.index("\n  function ", scroll_start)
        restore_scroll = source[scroll_start:scroll_end]
        tabs_start = source.index("function _restoreEditorSelectionContext(")
        tabs_end = source.index("\n  function ", tabs_start)
        restore_tabs = source[tabs_start:tabs_end]
        cycle_start = source.index("async function runSubagentCycle(")
        cycle_end = source.index("\n  function ", cycle_start)
        cycle = source[cycle_start:cycle_end]

        self.assertIn("_focusTargetForContext(context)", restore_focus)
        self.assertIn("state.lastUserFocusGeneration", source)
        self.assertIn("FOCUS_SETTLE_DELAY_MS", restore_focus)
        self.assertNotIn(".focus(", restore_scroll)
        self.assertNotIn(".focus(", restore_tabs)
        self.assertIn("_navigationTakeoverReason(options)", restore_tabs)
        self.assertIn("_selectedEditorTab(group) === tab", restore_tabs)
        self.assertIn("await _restoreEditorSelectionContext(", cycle)
        self.assertIn("outerEditorContext || editorContext || context", cycle)
        self.assertIn('"subagent_cycle"', cycle)
        self.assertIn(
            '_settleFocusAfterAutomation(focusContext, "direct_scan");',
            source,
        )


class ParserTests(unittest.TestCase):
    def test_default_poll_interval_is_half_second(self) -> None:
        parser, _ = launcher.build_parser()

        launch = parser.parse_args(["launch", "/workspace"])
        launch_ssh = parser.parse_args(["launch-ssh", "devbox"])

        self.assertEqual(launcher.DEFAULT_POLL_INTERVAL_SECONDS, 0.5)
        self.assertEqual(launch.interval, 0.5)
        self.assertEqual(launch_ssh.interval, 0.5)
        self.assertEqual(launcher._session_poll_interval({}), 0.5)
        self.assertEqual(
            launcher._session_poll_interval({"poll_interval_seconds": "invalid"}),
            0.5,
        )

    def test_cycle_modes_and_subagents_json(self) -> None:
        parser, _ = launcher.build_parser()
        cycle = parser.parse_args(["cycle", "--once", "-w", "repo"])
        self.assertEqual(cycle.cycle_mode, "once")
        self.assertEqual(cycle.workspace, "repo")

        subagents = parser.parse_args(["subagents", "--json", "repo"])
        self.assertTrue(subagents.json_output)
        self.assertEqual(subagents.workspace_pos, "repo")

    def test_cycle_requires_exactly_one_mode(self) -> None:
        parser, _ = launcher.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["cycle"])
        with self.assertRaises(SystemExit):
            parser.parse_args(["cycle", "--on", "--once"])


class SubagentSnapshotTests(unittest.TestCase):
    def test_snapshot_sanitizer_removes_prompt_and_command_content(self) -> None:
        raw = {
            "version": 1,
            "scriptHash": "abc",
            "workspace": "/wrong",
            "targetId": "target",
            "cycleEnabled": True,
            "counts": {"active": 1},
            "tray": {
                "running": 2,
                "mounted": 3,
                "advertised": 3,
                "headers": 1,
                "collapsed": 1,
                "unknown": 0,
                "visits": 3,
                "attempts": 1,
                "confirmed": 1,
                "failed": 0,
                "prompt": "secret",
            },
            "pinned": {
                "total": 2,
                "active": 1,
                "eligible": 2,
                "ambiguous": 0,
                "visits": 4,
                "attempts": 1,
                "confirmed": 1,
                "failed": 0,
                "lastRestore": {
                    "ok": True,
                    "reason": "original_agent_restored",
                    "ts": "2026-07-22T00:00:00Z",
                    "prompt": "secret",
                },
                "titles": ["secret title"],
            },
            "tasks": [{
                "taskKey": "task",
                "rowKey": "row",
                "status": "running",
                "title": "Safe title",
                "command": "secret-token",
                "prompt": {"text": "secret prompt"},
            }],
            "command": "top-level-secret",
        }

        clean = launcher._sanitize_subagent_snapshot(raw, "/workspace", "repo")

        self.assertEqual(clean["workspace"], "/workspace")
        self.assertEqual(clean["slug"], "repo")
        self.assertNotIn("command", clean)
        self.assertNotIn("command", clean["tasks"][0])
        self.assertNotIn("prompt", clean["tasks"][0])
        self.assertEqual(clean["tasks"][0]["title"], "Safe title")
        self.assertEqual(clean["tray"]["confirmed"], 1)
        self.assertEqual(clean["tray"]["mounted"], 3)
        self.assertEqual(clean["tray"]["advertised"], 3)
        self.assertEqual(clean["tray"]["headers"], 1)
        self.assertEqual(clean["tray"]["collapsed"], 1)
        self.assertEqual(clean["tray"]["unknown"], 0)
        self.assertNotIn("prompt", clean["tray"])
        self.assertEqual(clean["pinned"]["total"], 2)
        self.assertEqual(clean["pinned"]["active"], 1)
        self.assertEqual(clean["pinned"]["eligible"], 2)
        self.assertEqual(clean["pinned"]["ambiguous"], 0)
        self.assertEqual(
            clean["pinned"]["lastRestore"]["reason"],
            "original_agent_restored",
        )
        self.assertNotIn("prompt", clean["pinned"]["lastRestore"])
        self.assertNotIn("titles", clean["pinned"])

    def test_tray_status_formats_current_and_legacy_snapshots(self) -> None:
        current = launcher._format_tray_status({
            "advertised": 3,
            "mounted": 2,
            "running": 1,
            "headers": 1,
            "collapsed": 0,
            "unknown": 1,
            "visits": 4,
            "attempts": 2,
            "confirmed": 1,
            "failed": 0,
        })
        legacy = launcher._format_tray_status({"running": 2})

        self.assertIn("3 advertised, 2 mounted, 1 eligible", current)
        self.assertIn("0/1 collapsed, 1 unknown", current)
        self.assertIn("4 visits, 2 attempts, 1 confirmed, 0 failed", current)
        self.assertIn("2 advertised, 2 mounted, 2 eligible", legacy)
        self.assertIn("0/0 collapsed, 0 unknown", legacy)

    def test_sync_writes_atomic_multi_session_snapshot(self) -> None:
        exported = {
            "version": 1,
            "targetId": "target",
            "cycleEnabled": False,
            "counts": {"active": 1},
            "tasks": [{"taskKey": "task", "rowKey": "row", "status": "running"}],
        }
        cdp_result = {
            "result": {
                "result": {
                    "value": json.dumps(exported),
                },
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = Path(tmpdir)
            with (
                mock.patch.object(launcher, "RUNTIME_DIR", runtime),
                mock.patch.object(launcher, "SUBAGENTS_PATH", runtime / "subagents.json"),
                mock.patch.object(launcher, "_cdp_evaluate", return_value=cdp_result),
            ):
                snapshot = launcher._sync_subagent_registry(
                    9222, "target", "/workspace", "repo",
                )
                saved = json.loads((runtime / "subagents.json").read_text())

        self.assertIsNotNone(snapshot)
        self.assertEqual(saved["sessions"]["/workspace"]["tasks"][0]["taskKey"], "task")


class CdpJsonTests(unittest.TestCase):
    def test_json_expression_requests_promise_awaiting(self) -> None:
        cdp_result = {
            "result": {
                "result": {
                    "value": json.dumps({"ok": True}),
                },
            },
        }
        with mock.patch.object(launcher, "_cdp_evaluate", return_value=cdp_result) as evaluate:
            result = launcher._cdp_json_expression(
                9222,
                "(async () => ({ok:true}))()",
                "target",
                await_promise=True,
            )

        self.assertEqual(result, {"ok": True})
        self.assertTrue(evaluate.call_args.kwargs["await_promise"])


class IdeModeTests(unittest.TestCase):
    def test_launch_args_force_classic_ide_without_chat_or_glass(self) -> None:
        local = launcher._cursor_ide_launch_args(
            9222, Path("/profile"), workspace="/workspace",
        )
        remote = launcher._cursor_ide_launch_args(
            9223,
            Path("/profile-remote"),
            folder_uri="vscode-remote://ssh-remote+devbox/workspace",
        )

        self.assertIn("--new-window", local)
        self.assertIn("--classic", local)
        self.assertIn("/workspace", local)
        self.assertNotIn("--chat", local)
        self.assertNotIn("--glass", local)
        self.assertIn("--new-window", remote)
        self.assertIn("--classic", remote)
        self.assertIn("--folder-uri", remote)
        self.assertNotIn("--chat", remote)
        self.assertNotIn("--glass", remote)

    def test_classic_mode_support_fails_closed_when_flag_disappears(self) -> None:
        supported = subprocess.CompletedProcess(
            args=["cursor", "--help"],
            returncode=0,
            stdout="--classic  Disable glass mode and force classic windows",
        )
        missing = subprocess.CompletedProcess(
            args=["cursor", "--help"],
            returncode=0,
            stdout="--new-window  Force to open a new window",
        )
        with (
            mock.patch.object(launcher, "CURSOR_CLI", Path(__file__)),
            mock.patch.object(launcher.subprocess, "run", return_value=supported),
        ):
            ok, reason = launcher._cursor_classic_mode_support()
        self.assertTrue(ok)
        self.assertEqual(reason, "classic_mode_supported")

        with (
            mock.patch.object(launcher, "CURSOR_CLI", Path(__file__)),
            mock.patch.object(launcher.subprocess, "run", return_value=missing),
        ):
            ok, reason = launcher._cursor_classic_mode_support()
        self.assertFalse(ok)
        self.assertIn("--classic", reason)

    def test_surface_probe_uses_mode_specific_workbench_bundles(self) -> None:
        expression = launcher._CDP_SURFACE_MODE_EXPR
        self.assertIn("workbench\\.desktop\\.main", expression)
        self.assertIn("workbench\\.glass\\.main", expression)
        self.assertIn('"desktop_bundle"', expression)
        self.assertIn('"glass_bundle"', expression)

    def test_selects_only_a_verified_full_ide_target(self) -> None:
        targets = [
            {
                "id": "agents",
                "url": "vscode-file://workbench/workbench.html",
                "webSocketDebuggerUrl": "ws://agents",
            },
            {
                "id": "ide",
                "url": "vscode-file://workbench/workbench.html",
                "webSocketDebuggerUrl": "ws://ide",
            },
        ]

        with (
            mock.patch.object(
                launcher, "_cdp_list_page_targets", return_value=targets,
            ),
            mock.patch.object(
                launcher,
                "_cdp_target_surface",
                side_effect=lambda target, timeout=5.0: {
                    "mode": "ide" if target["id"] == "ide" else "agents_or_incomplete",
                },
            ),
        ):
            selected = launcher._cdp_select_workbench_target(9222)

        self.assertEqual(selected["id"], "ide")

    def test_rejects_agents_only_target(self) -> None:
        target = {
            "id": "agents",
            "url": "vscode-file://workbench/workbench.html",
            "webSocketDebuggerUrl": "ws://agents",
        }
        with (
            mock.patch.object(
                launcher, "_cdp_list_page_targets", return_value=[target],
            ),
            mock.patch.object(
                launcher,
                "_cdp_target_surface",
                return_value={"mode": "agents_or_incomplete"},
            ),
            self.assertRaisesRegex(RuntimeError, "No full IDE target found"),
        ):
            launcher._cdp_select_workbench_target(9222)


class TargetRebindTests(unittest.TestCase):
    def test_rebinds_only_unique_replacement_workbench(self) -> None:
        session = {
            "workspace": "/workspace",
            "cdp_port": 9222,
            "cdp_target_id": "old",
        }
        state = {"sessions": {"/workspace": dict(session)}}
        with (
            mock.patch.object(
                launcher,
                "_cdp_list_page_targets",
                return_value=[{"id": "new", "type": "page"}],
            ),
            mock.patch.object(launcher, "_is_workbench", return_value=True),
            mock.patch.object(
                launcher, "_cdp_target_surface", return_value={"mode": "ide"},
            ),
            mock.patch.object(launcher, "_load_state", return_value=state),
            mock.patch.object(launcher, "_save_state") as save_state,
        ):
            target, changed = launcher._rebind_session_target_if_unique(session)

        self.assertTrue(changed)
        self.assertEqual(target, "new")
        self.assertEqual(session["cdp_target_id"], "new")
        save_state.assert_called_once()

    def test_does_not_rebind_ambiguous_workbenches(self) -> None:
        session = {
            "workspace": "/workspace",
            "cdp_port": 9222,
            "cdp_target_id": "old",
        }
        with (
            mock.patch.object(
                launcher,
                "_cdp_list_page_targets",
                return_value=[{"id": "one"}, {"id": "two"}],
            ),
            mock.patch.object(launcher, "_is_workbench", return_value=True),
            mock.patch.object(
                launcher, "_cdp_target_surface", return_value={"mode": "ide"},
            ),
        ):
            target, changed = launcher._rebind_session_target_if_unique(session)

        self.assertFalse(changed)
        self.assertEqual(target, "old")


if __name__ == "__main__":
    unittest.main()
