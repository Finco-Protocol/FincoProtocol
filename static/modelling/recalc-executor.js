/*
 * FINCO Protocol — Live Modelling Layer
 * C2-PR5: Incremental Recalculation Execution Stub (infrastructure
 * only — a deterministic, no-op execution boundary that receives a
 * flushed recalc snapshot (already annotated with affectedGroups by
 * C2-PR4's FcDependencyGraph) and produces a stable result object; no
 * financial recalculation, no formula evaluation, no backend Run
 * call, no DOM/KPI change, no dirty-state change)
 *
 * Reference: docs/C2_PR1_IMPLEMENTATION_NOTE.md,
 *            docs/C2_PR2_DIRTY_STATE_UNIFICATION_NOTE.md,
 *            docs/C2_PR3_RECALC_SCHEDULER_FOUNDATION_NOTE.md,
 *            docs/C2_PR4_DEPENDENCY_GRAPH_FOUNDATION_NOTE.md,
 *            docs/C2_PR5_INCREMENTAL_RECALC_EXECUTION_STUB_NOTE.md.
 *
 * This module answers exactly one question: "given a recalc snapshot
 * (dirty grids/addrs + projectDirty + affectedGroups), what would the
 * execution layer do?" For THIS PR, the answer is always "nothing" —
 * it never calculates an output, never calls a backend endpoint, and
 * never mutates any dirty-state/recalc-scheduler/dependency-graph
 * state owned by FcLiveModel/FcDependencyGraph. It exists purely as
 * the seam a future PR will replace with a real incremental
 * recalculation call.
 *
 * Ownership: window.FcRecalcExecutor is a new, standalone module —
 * like FcDependencyGraph (C2-PR4), deliberately not folded into
 * FcLiveModel. It owns exactly one piece of state: the most recent
 * execute() result (`_lastExecution`), exposed via
 * getLastExecution()/clearLastExecution(). It never reads or writes
 * FcLiveModel's dirty state directly, never reads the DOM, and never
 * computes a dependency mapping itself — it only reads the
 * `affectedGroups` field FcDependencyGraph already attached to the
 * snapshot before this module is ever invoked.
 *
 * Input contract: a snapshot shaped like
 *   { grids: [{gridId, addrs: [...]}], projectDirty, affectedGroups: [...] }
 * (i.e. exactly what FcLiveModel.flushScheduledRecalc() produces after
 * C2-PR4's dependency-resolution step). execute()/canExecute() never
 * throw on a missing/malformed snapshot — malformed input degrades to
 * the safest possible result rather than raising.
 *
 * Output contract: a deterministic, plain-data result object:
 *   {
 *     status: "stubbed" | "stubbed-unknown" | "stubbed-empty" | "stubbed-invalid",
 *     executed: false,
 *     affectedGroups: [...sorted, deduplicated],
 *     dirtyCells: [...sorted, deduplicated fully-qualified addrs,
 *                  i.e. the same "gridId!key" strings already present
 *                  verbatim in snapshot.grids[].addrs...],
 *     reason: <string, from options.reason, default "manual-flush">
 *   }
 * `executed` is always `false` in this PR — there is no execution
 * mode in which this stub actually performs work. `status` is
 * "stubbed-unknown" when affectedGroups contains "unknown" (still
 * safe, still a no-op, but distinguishable for future diagnostics);
 * "stubbed-empty" when the snapshot is well-formed but carries no
 * dirty grids/addrs at all; "stubbed-invalid" when the snapshot
 * itself failed the defensive shape-check (canExecute would have
 * returned false); "stubbed" otherwise. No timestamp, session id, or
 * other non-reproducible field appears anywhere in the result.
 *
 * This module does NOT:
 *   - evaluate any formula or call app/waterfall_core.py, domain/*,
 *     or any other financial code
 *   - make any network/AJAX/htmx call of any kind
 *   - call Save, Run, or any backend endpoint
 *   - mutate FcLiveModel dirty state, the recalc scheduler, or
 *     FcDependencyGraph's (stateless) registry
 *   - touch the DOM or any rendered KPI/output value
 */
(function () {
  'use strict';

  var _lastExecution = null;

  function _isNonEmptyString(v) {
    return typeof v === 'string' && v.length > 0;
  }

  /**
   * Defensive shape-check predicate. Returns true only for a snapshot
   * that at minimum has a `grids` array (each entry, if present,
   * shaped like {gridId, addrs: [...]}) — `projectDirty` and
   * `affectedGroups` are optional/tolerated-missing since this should
   * remain usable even against a C2-PR3-only snapshot (no
   * FcDependencyGraph loaded). Never throws.
   *
   * Note on addr shape: addrs in `grid.addrs` (as produced by
   * FcLiveModel.getDirtyCells/getPendingRecalcSnapshot) are already
   * fully-qualified "gridId!key" strings (the raw `data-fc-addr`
   * attribute value) — gridId is *not* a separate prefix that needs
   * to be re-applied. dirtyCells below preserves each addr exactly as
   * given, deduplicated and sorted.
   */
  function canExecute(snapshot) {
    if (!snapshot || typeof snapshot !== 'object') return false;
    if (!Array.isArray(snapshot.grids)) return false;
    for (var i = 0; i < snapshot.grids.length; i++) {
      var grid = snapshot.grids[i];
      if (!grid || typeof grid !== 'object') return false;
      if (!_isNonEmptyString(grid.gridId)) return false;
      if (!Array.isArray(grid.addrs)) return false;
      for (var j = 0; j < grid.addrs.length; j++) {
        if (typeof grid.addrs[j] !== 'string') return false;
      }
    }
    return true;
  }

  function _uniqueSorted(arr) {
    var seen = {};
    var out = [];
    (arr || []).forEach(function (v) {
      if (typeof v === 'string' && !seen[v]) {
        seen[v] = true;
        out.push(v);
      }
    });
    out.sort();
    return out;
  }

  function _deriveDirtyCells(snapshot) {
    var cells = [];
    if (snapshot && Array.isArray(snapshot.grids)) {
      snapshot.grids.forEach(function (grid) {
        if (!grid || !_isNonEmptyString(grid.gridId) || !Array.isArray(grid.addrs)) return;
        grid.addrs.forEach(function (addr) {
          if (typeof addr === 'string' && addr.length) {
            cells.push(addr);
          }
        });
      });
    }
    return _uniqueSorted(cells);
  }

  /**
   * Executes (in name only — this PR performs no real work) against a
   * recalc snapshot. Never throws. Always returns a deterministic,
   * plain-data result object; never performs a calculation, a network
   * call, a DOM change, or a dirty-state mutation. Records the result
   * as the "last execution" (see getLastExecution/clearLastExecution).
   */
  function execute(snapshot, options) {
    var opts = options || {};
    var reason = _isNonEmptyString(opts.reason) ? opts.reason : 'manual-flush';

    if (!canExecute(snapshot)) {
      var invalidResult = {
        status: 'stubbed-invalid',
        executed: false,
        affectedGroups: [],
        dirtyCells: [],
        reason: reason
      };
      _lastExecution = invalidResult;
      return invalidResult;
    }

    var affectedGroups = _uniqueSorted(
      (snapshot && Array.isArray(snapshot.affectedGroups)) ? snapshot.affectedGroups : []
    );
    var dirtyCells = _deriveDirtyCells(snapshot);

    var status = 'stubbed';
    if (affectedGroups.indexOf('unknown') !== -1) {
      status = 'stubbed-unknown';
    } else if (dirtyCells.length === 0 && affectedGroups.length === 0) {
      status = 'stubbed-empty';
    }

    var result = {
      status: status,
      executed: false,
      affectedGroups: affectedGroups,
      dirtyCells: dirtyCells,
      reason: reason
    };

    // C2-PR6: additive only. If window.FcRecalcPreview is present
    // (static/modelling/recalc-preview.js, loaded before this file),
    // hand it this stub's own result (plus the original snapshot) so
    // it can build a deterministic preview-request payload describing
    // what a FUTURE backend preview/recalc endpoint would need. This
    // module never builds that payload itself, never sends it
    // anywhere, and never performs any network call as a result of
    // this call. If FcRecalcPreview isn't loaded, this is a no-op and
    // the result shape is byte-for-byte identical to this PR's
    // predecessor (C2-PR5) — no previewPrepared/previewPayload fields
    // are added.
    if (window.FcRecalcPreview && typeof window.FcRecalcPreview.buildPreviewPayload === 'function') {
      result.previewPrepared = true;
      result.previewPayload = window.FcRecalcPreview.buildPreviewPayload(snapshot, result, { reason: reason });
    }

    _lastExecution = result;
    return result;
  }

  function getLastExecution() {
    return _lastExecution;
  }

  function clearLastExecution() {
    _lastExecution = null;
  }

  window.FcRecalcExecutor = {
    execute: execute,
    canExecute: canExecute,
    getLastExecution: getLastExecution,
    clearLastExecution: clearLastExecution
  };
})();
