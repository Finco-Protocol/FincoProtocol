/*
 * FINCO Protocol — Live Modelling Layer
 * C2-PR6: Incremental Recalculation Preview Boundary (infrastructure
 * only — a deterministic, client-only payload BUILDER describing what
 * a FUTURE backend preview/recalc endpoint would need to receive; this
 * module never calls that endpoint, never makes any network request,
 * never evaluates a formula, never mutates the DOM, and never mutates
 * any dirty-state/recalc-scheduler/dependency-graph/execution state
 * owned by FcLiveModel/FcDependencyGraph/FcRecalcExecutor)
 *
 * C2-PR10: adds exactly one additive, opt-in computation — a CAPEX
 * total PREVIEW (a plain sum of the live, possibly-unsaved CAPEX grid
 * cell values currently in the DOM). This is the first PR in the
 * entire C1/C2 chain allowed to perform any real numeric computation,
 * and it is deliberately scoped to nothing more than "sum the editable
 * CAPEX amount cells currently visible in the browser." It does NOT
 * call app/waterfall_core.py, domain/*, or any other financial engine
 * code, client- or server-side. See
 * docs/C2_PR10_CAPEX_TOTAL_PREVIEW.md for the full design rationale
 * (in particular: why this sum is computed CLIENT-SIDE from
 * FcGridRegistry/FcCellIO rather than sent to the server to be
 * summed there).
 *
 * C2-PR13: adds a second, independent additive computation following
 * the EXACT same pattern — a Revenue total PREVIEW (a plain sum of the
 * live, possibly-unsaved Revenue grid editable cell values currently
 * in the DOM). Revenue grid cells use `data-fc-kind="text"` (not
 * "amount" like CAPEX) per the existing markup in
 * app/templates/partials/sheet_revenue.html, so
 * `_computeRevenueTotalFromDom()` matches on `cell.editable === true`
 * and `cell.kind === 'text'` instead — the same "editable, plain
 * line-item" selection rule, just using Revenue's own kind convention.
 * It never calls any financial engine code either. See
 * docs/C2_PR13_REVENUE_PREVIEW.md.
 *
 * C2-PR14 adds a third, independent additive computation following the
 * EXACT same pattern — an OPEX total PREVIEW (a plain sum of the live,
 * possibly-unsaved OPEX grid editable "Budget" cell values currently in
 * the DOM). OPEX grid cells use `data-fc-kind="amount"` (the same
 * convention as CAPEX, not Revenue's "text") per the existing markup in
 * app/templates/partials/sheet_opex_detail.html, so
 * `_computeOpexTotalFromDom()` matches on `cell.editable === true` and
 * `cell.kind === 'amount'`. See docs/C2_PR14_OPEX_PREVIEW.md.
 *
 * C2-PR15 adds EBITDA Preview = Revenue Preview − OPEX Preview, computed
 * ENTIRELY CLIENT-SIDE, purely arithmetically, from the two preview
 * numbers already computed above in this same flush
 * (`revenueTotalPreview`/`opexTotalPreview`) — it never re-reads the
 * DOM, never reads Overview KPIs, and never calls any engine. If either
 * input is null, the EBITDA preview is null (never a fabricated partial
 * value). See docs/C2_PR15_EBITDA_PREVIEW.md for the client-vs-server
 * design choice rationale.
 *
 * C2-PR16 adds Operating Cash Flow Preview = EBITDA Preview (passthrough
 * only — no debt/tax/depreciation/financing adjustments). This is
 * DELIBERATELY, EXPLICITLY a non-authoritative simplification that
 * exists only to prove the preview pipeline can chain a preview of a
 * preview of previews. See docs/C2_PR16_OPERATING_CF_PREVIEW.md.
 *
 * Reference: docs/C2_PR1_IMPLEMENTATION_NOTE.md,
 *            docs/C2_PR2_DIRTY_STATE_UNIFICATION_NOTE.md,
 *            docs/C2_PR3_RECALC_SCHEDULER_FOUNDATION_NOTE.md,
 *            docs/C2_PR4_DEPENDENCY_GRAPH_FOUNDATION_NOTE.md,
 *            docs/C2_PR5_INCREMENTAL_RECALC_EXECUTION_STUB_NOTE.md,
 *            docs/C2_PR6_INCREMENTAL_RECALC_PREVIEW_BOUNDARY_NOTE.md,
 *            docs/C2_PR10_CAPEX_TOTAL_PREVIEW.md,
 *            docs/C2_PR13_REVENUE_PREVIEW.md,
 *            docs/C2_PR14_OPEX_PREVIEW.md,
 *            docs/C2_PR15_EBITDA_PREVIEW.md,
 *            docs/C2_PR16_OPERATING_CF_PREVIEW.md.
 *
 * This module answers exactly one question: "given a flushed recalc
 * snapshot and its (stubbed) execution result, what request payload
 * WOULD a future backend preview/recalc call need?" It only BUILDS
 * that payload as a plain-data object; it never sends it anywhere.
 *
 * Ownership: window.FcRecalcPreview is a new, standalone module —
 * like FcDependencyGraph (C2-PR4) and FcRecalcExecutor (C2-PR5),
 * deliberately not folded into FcLiveModel. It owns exactly one piece
 * of state: the most recently built payload (`_lastPreviewPayload`),
 * exposed via getLastPreviewPayload()/clearLastPreviewPayload(). It
 * never reads or writes FcLiveModel's dirty state directly, never
 * computes a dependency mapping, and never performs or duplicates any
 * execution logic — it only reads the `snapshot`/`execution` objects
 * it is handed.
 *
 * Input contract:
 *   buildPreviewPayload(snapshot, execution, options)
 *   - snapshot: shaped like
 *     { grids: [{gridId, addrs: [...]}], projectDirty, affectedGroups: [...] }
 *     (i.e. exactly what FcLiveModel.flushScheduledRecalc() produces,
 *     before or after FcRecalcExecutor.execute() is called).
 *   - execution: shaped like FcRecalcExecutor.execute()'s result
 *     ({status, executed, affectedGroups, dirtyCells, reason}), or any
 *     subset thereof, or omitted/null.
 *   - options: optional; reserved for future use (currently unused
 *     beyond defensive handling — no required fields).
 *   Never throws on malformed/missing snapshot or execution — both
 *   degrade to the safest possible payload rather than raising.
 *
 * Output contract: a deterministic, plain-data payload object:
 *   {
 *     valid: true | false,
 *     dirtyCells: [...sorted, deduplicated fully-qualified "gridId!key"
 *                  strings, derived the same way FcRecalcExecutor
 *                  derives its own dirtyCells field],
 *     affectedGroups: [...sorted, deduplicated group strings, preferring
 *                      execution.affectedGroups when present, falling
 *                      back to snapshot.affectedGroups],
 *     projectDirty: <boolean, from snapshot.projectDirty, default false>,
 *     reason: <string, from execution.reason if present, else
 *              options.reason if present, else "manual-flush">,
 *     executionStatus: <string from execution.status, or null if no
 *                       execution object was supplied/it was malformed>,
 *     project: <string project code from window.location's "project"
 *               query parameter, or null if unavailable — see metadata
 *               handling below; never fabricated>
 *   }
 * No timestamp, session id, or other non-reproducible field appears
 * anywhere in the payload. Two logically-equal (snapshot, execution)
 * pairs — however differently ordered their underlying grids/addrs/
 * groups arrays are — always produce deep-equal payloads.
 *
 * Metadata handling decision: the ONLY project/scenario identifier
 * available anywhere in the existing client without inventing new
 * server-rendered markup is the "project" query-string parameter
 * already present on every production workspace URL (confirmed via
 * tests/test_c2_pr5_recalc_executor_browser.py's fixture:
 * `page.goto(f"{live_server}/?project={project_code}", ...)`, and via
 * grepping app/templates/partials for the many `data-project-code`
 * attributes scattered across narrower partials — none of which are
 * guaranteed to be present/rendered on every workspace page, unlike
 * the URL itself). This module reads it defensively from
 * `window.location.search` via the global URLSearchParams
 * constructor (already used elsewhere in this codebase, e.g.
 * static/app.js's `new URLSearchParams(new FormData(form))` calls);
 * if it's missing, empty, or `window`/`window.location` is somehow
 * unavailable (e.g. a non-browser test harness), `project` is set to
 * `null` — never fabricated, never defaulted to a placeholder string.
 * No scenario identifier is included: no reliable, always-rendered
 * scenario id signal was found in the existing DOM/URL that isn't
 * scoped to a single narrow partial (e.g. scenario_tab.html's
 * data-active-scenario-id, which isn't present on every tab), so this
 * PR omits it entirely rather than reading a possibly-absent element
 * and guessing.
 *
 * This module does NOT:
 *   - evaluate any formula or call app/waterfall_core.py, domain/*,
 *     or any other financial code
 *   - make any network/AJAX/htmx call of any kind, to any endpoint,
 *     ever (this is the single most safety-critical invariant of this
 *     module — it only BUILDS a payload, it never transmits it)
 *   - call Save, Run, or any backend endpoint
 *   - mutate FcLiveModel dirty state, the recalc scheduler,
 *     FcDependencyGraph's (stateless) registry, or FcRecalcExecutor's
 *     last-execution state
 *   - touch the DOM or any rendered KPI/output value
 */
(function () {
  'use strict';

  var _lastPreviewPayload = null;

  function _isNonEmptyString(v) {
    return typeof v === 'string' && v.length > 0;
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

  /**
   * Derives the deduplicated, sorted, fully-qualified dirty-cell
   * address list from a snapshot, mirroring FcRecalcExecutor's own
   * `_deriveDirtyCells` exactly (addrs are already "gridId!key"
   * strings — not re-prefixed). Never throws.
   */
  function _deriveDirtyCellsFromSnapshot(snapshot) {
    var cells = [];
    if (snapshot && Array.isArray(snapshot.grids)) {
      snapshot.grids.forEach(function (grid) {
        if (!grid || typeof grid !== 'object') return;
        if (!Array.isArray(grid.addrs)) return;
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
   * C2-PR10: computes a deterministic, client-only CAPEX total PREVIEW
   * — a plain sum of every editable CAPEX amount cell's CURRENT (live,
   * possibly-unsaved) DOM value. This is the only numeric computation
   * anywhere in this PR; it is not a financial-engine call of any kind
   * — it is a transparent line-item sum, equivalent to what the user
   * could compute themselves with a calculator from what's currently
   * on screen.
   *
   * Reads live cell values via the existing C1 read APIs
   * (window.FcGridRegistry / window.FcCellIO) rather than re-querying
   * the DOM directly, so this module never duplicates C1's cell-value
   * read logic. Only cells that are:
   *   - registered under the "capex" grid id (FcGridRegistry.getGrid),
   *   - marked editable (cell.editable === true), and
   *   - of kind "amount" (cell.kind === 'amount')
   * are included — read-only cells (subtotals/totals/financing rows)
   * are deliberately excluded, since they are DERIVED values, not
   * independent line items, and including them would double-count.
   *
   * Never throws. Returns null (not 0, not a fabricated number) when
   * FcGridRegistry/FcCellIO are unavailable, or when the "capex" grid
   * is not currently registered/rendered (e.g. a different tab is
   * active, or an isolated test fixture without the CAPEX sheet) —
   * "no total available" must never be silently rendered as a real
   * zero total.
   */
  function _computeCapexTotalFromDom() {
    try {
      if (!window.FcGridRegistry || typeof window.FcGridRegistry.getGrid !== 'function') return null;
      if (!window.FcCellIO || typeof window.FcCellIO.readValue !== 'function') return null;

      var grid = window.FcGridRegistry.getGrid('capex');
      if (!grid || !grid.rows) return null;

      var total = 0;
      var counted = 0;
      grid.rows.forEach(function (row) {
        (row || []).forEach(function (cell) {
          if (!cell || !cell.editable || cell.kind !== 'amount') return;
          var raw = window.FcCellIO.readValue(cell);
          var num = parseFloat(raw);
          if (isNaN(num)) return;
          total += num;
          counted += 1;
        });
      });

      if (counted === 0) return null;
      // Round to 2dp to avoid noisy floating-point sums (e.g.
      // 1234.5599999999999) leaking into the rendered preview — this
      // is presentation rounding only, not a recalculation.
      return Math.round(total * 100) / 100;
    } catch (e) {
      return null;
    }
  }

  /**
   * C2-PR13: computes a deterministic, client-only Revenue total
   * PREVIEW — a plain sum of every editable Revenue line-item cell's
   * CURRENT (live, possibly-unsaved) DOM value. Exactly mirrors
   * `_computeCapexTotalFromDom()` above (see its docstring for the
   * full rationale, which applies identically here), with the one
   * necessary difference: Revenue editable cells are marked
   * `data-fc-kind="text"` (not "amount") in
   * app/templates/partials/sheet_revenue.html, so this function
   * matches on `cell.editable === true && cell.kind === 'text'`
   * instead. Read-only subtotal/total rows in the Revenue grid (Tariff
   * Y1, Y1 PPA Revenue, Y1 CO2 Revenue, Est. Total Y1 Revenue) are all
   * `editable === false` and are therefore deliberately excluded —
   * they are DERIVED values, not independent line items, and including
   * them would double-count exactly as for CAPEX.
   *
   * Never throws. Returns null (not 0, not a fabricated number) when
   * FcGridRegistry/FcCellIO are unavailable, or when the "revenue"
   * grid is not currently registered/rendered (e.g. a different tab is
   * active, or a protected/baseline project with no editable revenue
   * cells at all) — "no total available" must never be silently
   * rendered as a real zero total.
   */
  function _computeRevenueTotalFromDom() {
    try {
      if (!window.FcGridRegistry || typeof window.FcGridRegistry.getGrid !== 'function') return null;
      if (!window.FcCellIO || typeof window.FcCellIO.readValue !== 'function') return null;

      var grid = window.FcGridRegistry.getGrid('revenue');
      if (!grid || !grid.rows) return null;

      var total = 0;
      var counted = 0;
      grid.rows.forEach(function (row) {
        (row || []).forEach(function (cell) {
          if (!cell || !cell.editable || cell.kind !== 'text') return;
          var raw = window.FcCellIO.readValue(cell);
          var num = parseFloat(raw);
          if (isNaN(num)) return;
          total += num;
          counted += 1;
        });
      });

      if (counted === 0) return null;
      // Round to 2dp to avoid noisy floating-point sums leaking into
      // the rendered preview — this is presentation rounding only,
      // not a recalculation.
      return Math.round(total * 100) / 100;
    } catch (e) {
      return null;
    }
  }

  /**
   * C2-PR14: computes a deterministic, client-only OPEX total PREVIEW
   * — a plain sum of every editable OPEX "Budget" cell's CURRENT (live,
   * possibly-unsaved) DOM value. Exactly mirrors
   * `_computeCapexTotalFromDom()` (see its docstring for the full
   * rationale, which applies identically here): the OPEX grid uses
   * `data-fc-kind="amount"` (the same convention as CAPEX, NOT
   * Revenue's "text") per the existing markup in
   * app/templates/partials/sheet_opex_detail.html, so this function
   * matches on `cell.editable === true && cell.kind === 'amount'`.
   * Read-only category-subtotal rows (`data-fc-kind="subtotal"`) and
   * non-contingency-budget metadata cells (inflation/WHT %, which are
   * also `kind="amount"` but never `editable`) are excluded by the
   * `editable === true` check alone — only genuinely editable Budget
   * line items are summed.
   *
   * Never throws. Returns null (not 0, not a fabricated number) when
   * FcGridRegistry/FcCellIO are unavailable, or when the "opex" grid is
   * not currently registered/rendered, or no editable cell parses as a
   * number — "no total available" must never be silently rendered as a
   * real zero total.
   *
   * NOTE (as of C2-PR14): OPEX line items are not yet wired up as
   * editable in app/templates/partials/sheet_opex_detail.html — "Line
   * editing deferred" there is a pre-existing, intentional C1 boundary
   * unrelated to this PR. Making OPEX cells editable is out of scope
   * for a preview-pipeline PR. Until a dedicated C1 PR adds OPEX
   * editability, this function will always return null in practice
   * (counted === 0), which is the correct, documented behaviour per
   * the "never fabricate" rule — not a bug in this function.
   */
  function _computeOpexTotalFromDom() {
    try {
      if (!window.FcGridRegistry || typeof window.FcGridRegistry.getGrid !== 'function') return null;
      if (!window.FcCellIO || typeof window.FcCellIO.readValue !== 'function') return null;

      var grid = window.FcGridRegistry.getGrid('opex');
      if (!grid || !grid.rows) return null;

      var total = 0;
      var counted = 0;
      grid.rows.forEach(function (row) {
        (row || []).forEach(function (cell) {
          if (!cell || !cell.editable || cell.kind !== 'amount') return;
          var raw = window.FcCellIO.readValue(cell);
          var num = parseFloat(raw);
          if (isNaN(num)) return;
          total += num;
          counted += 1;
        });
      });

      if (counted === 0) return null;
      // Round to 2dp to avoid noisy floating-point sums leaking into
      // the rendered preview — this is presentation rounding only,
      // not a recalculation.
      return Math.round(total * 100) / 100;
    } catch (e) {
      return null;
    }
  }

  /**
   * C2-PR15: EBITDA Preview = Revenue Preview − OPEX Preview. Pure
   * arithmetic on the two preview numbers already computed above in
   * THIS SAME flush — never re-reads the DOM, never reads Overview
   * KPIs, never calls any engine. If either input is null/unavailable,
   * returns null (never a fabricated partial value) — this is the
   * single most important invariant of this function. Never throws.
   */
  function _computeEbitdaFromPreviews(revenuePreview, opexPreview) {
    if (typeof revenuePreview !== 'number' || !isFinite(revenuePreview)) return null;
    if (typeof opexPreview !== 'number' || !isFinite(opexPreview)) return null;
    return Math.round((revenuePreview - opexPreview) * 100) / 100;
  }

  /**
   * C2-PR16: Operating Cash Flow Preview = EBITDA Preview, verbatim.
   *
   * *** THIS IS NOT AUTHORITATIVE OPERATING CASH FLOW. ***
   * No debt service, no tax, no depreciation/amortization, no working
   * capital, no financing adjustment of any kind is applied here. This
   * is a deliberately, explicitly oversimplified placeholder whose sole
   * purpose is to prove the preview pipeline can chain a preview-of-a-
   * preview-of-previews (CAPEX/Revenue/OPEX -> EBITDA -> OCF). See
   * docs/C2_PR16_OPERATING_CF_PREVIEW.md for the full rationale. Never
   * throws; null propagates straight through (if EBITDA preview is
   * null, OCF preview is null).
   */
  function _computeOcfFromEbitda(ebitdaPreview) {
    if (typeof ebitdaPreview !== 'number' || !isFinite(ebitdaPreview)) return null;
    return ebitdaPreview;
  }

  /**
   * Reads the "project" query-string parameter from the current page
   * URL, defensively. Returns null (never a fabricated placeholder)
   * if window/window.location/URLSearchParams is unavailable, or if
   * the parameter is absent/empty.
   */
  function _readProjectFromLocation() {
    try {
      if (typeof window === 'undefined' || !window.location) return null;
      if (typeof URLSearchParams === 'undefined') return null;
      var params = new URLSearchParams(window.location.search || '');
      var value = params.get('project');
      return _isNonEmptyString(value) ? value : null;
    } catch (e) {
      return null;
    }
  }

  /**
   * Defensive, non-throwing shape-check predicate for a payload built
   * by this module (or any plain object claiming to be one). Returns
   * true only if every required field is present with the right
   * primitive/array type; tolerates `project` being null or a string.
   */
  function validatePreviewPayload(payload) {
    if (!payload || typeof payload !== 'object') return false;
    if (typeof payload.valid !== 'boolean') return false;
    if (!Array.isArray(payload.dirtyCells)) return false;
    for (var i = 0; i < payload.dirtyCells.length; i++) {
      if (typeof payload.dirtyCells[i] !== 'string') return false;
    }
    if (!Array.isArray(payload.affectedGroups)) return false;
    for (var j = 0; j < payload.affectedGroups.length; j++) {
      if (typeof payload.affectedGroups[j] !== 'string') return false;
    }
    if (typeof payload.projectDirty !== 'boolean') return false;
    if (typeof payload.reason !== 'string') return false;
    if (payload.executionStatus !== null && typeof payload.executionStatus !== 'string') return false;
    if (payload.project !== null && typeof payload.project !== 'string') return false;
    // C2-PR10: capexTotalPreview is additive/optional — older payloads
    // (or hand-constructed ones) without the field still validate, but
    // if present it must be null or a finite number.
    if (payload.hasOwnProperty('capexTotalPreview')) {
      var ctp = payload.capexTotalPreview;
      if (ctp !== null && (typeof ctp !== 'number' || !isFinite(ctp))) return false;
    }
    // C2-PR13: revenueTotalPreview is additive/optional, mirroring
    // capexTotalPreview exactly — null or a finite number only.
    if (payload.hasOwnProperty('revenueTotalPreview')) {
      var rtp = payload.revenueTotalPreview;
      if (rtp !== null && (typeof rtp !== 'number' || !isFinite(rtp))) return false;
    }
    // C2-PR14: opexTotalPreview is additive/optional, mirroring
    // capexTotalPreview/revenueTotalPreview exactly — null or a finite
    // number only.
    if (payload.hasOwnProperty('opexTotalPreview')) {
      var otp = payload.opexTotalPreview;
      if (otp !== null && (typeof otp !== 'number' || !isFinite(otp))) return false;
    }
    // C2-PR15: ebitdaPreview is additive/optional — null or a finite
    // number only. Computed purely client-side from revenue/opex
    // previews already in this payload (see buildPreviewPayload).
    if (payload.hasOwnProperty('ebitdaPreview')) {
      var ebp = payload.ebitdaPreview;
      if (ebp !== null && (typeof ebp !== 'number' || !isFinite(ebp))) return false;
    }
    // C2-PR16: operatingCashFlowPreview is additive/optional — null or
    // a finite number only. Equals ebitdaPreview verbatim (see
    // _computeOcfFromEbitda); NOT authoritative OCF.
    if (payload.hasOwnProperty('operatingCashFlowPreview')) {
      var ocfp = payload.operatingCashFlowPreview;
      if (ocfp !== null && (typeof ocfp !== 'number' || !isFinite(ocfp))) return false;
    }
    return true;
  }

  /**
   * Builds a deterministic preview-request payload from a recalc
   * snapshot and (optional) execution result. Never throws — a
   * malformed snapshot/execution degrades to a safe, explicitly
   * `valid: false` payload with empty dirtyCells/affectedGroups,
   * rather than raising. Records the result as the "last preview
   * payload" (see getLastPreviewPayload/clearLastPreviewPayload).
   *
   * This function performs NO calculation, NO network call, and NO
   * mutation of any dirty-state/scheduler/dependency-graph/execution
   * state — it only reads the snapshot/execution objects it is
   * handed and the current page URL.
   */
  function buildPreviewPayload(snapshot, execution, options) {
    var opts = (options && typeof options === 'object') ? options : {};

    var snapshotIsObject = !!(snapshot && typeof snapshot === 'object');
    var gridsIsArray = snapshotIsObject && Array.isArray(snapshot.grids);
    var valid = snapshotIsObject && gridsIsArray;

    var dirtyCells = valid ? _deriveDirtyCellsFromSnapshot(snapshot) : [];

    var executionIsObject = !!(execution && typeof execution === 'object');

    var affectedGroupsSource = null;
    if (executionIsObject && Array.isArray(execution.affectedGroups)) {
      affectedGroupsSource = execution.affectedGroups;
    } else if (snapshotIsObject && Array.isArray(snapshot.affectedGroups)) {
      affectedGroupsSource = snapshot.affectedGroups;
    }
    var affectedGroups = _uniqueSorted(affectedGroupsSource || []);

    var projectDirty = (snapshotIsObject && typeof snapshot.projectDirty === 'boolean')
      ? snapshot.projectDirty
      : false;

    var reason = 'manual-flush';
    if (executionIsObject && _isNonEmptyString(execution.reason)) {
      reason = execution.reason;
    } else if (_isNonEmptyString(opts.reason)) {
      reason = opts.reason;
    }

    var executionStatus = (executionIsObject && _isNonEmptyString(execution.status))
      ? execution.status
      : null;

    // C2-PR10: additive only. capexTotalPreview is null unless the
    // dirty set actually includes at least one "capex!..." address —
    // this keeps the field meaningfully scoped to "this flush touched
    // the CAPEX grid" rather than always recomputing it on every
    // unrelated flush (e.g. an OPEX edit). It is always recomputed
    // from the LIVE DOM (current, possibly-unsaved values), never from
    // dirtyCells/snapshot data itself.
    var touchesCapex = dirtyCells.some(function (addr) {
      return typeof addr === 'string' && addr.indexOf('capex!') === 0;
    });
    var capexTotalPreview = touchesCapex ? _computeCapexTotalFromDom() : null;

    // C2-PR13: additive only, mirrors capexTotalPreview's "only
    // recompute when this flush's dirty set actually touched the
    // relevant grid" scoping exactly, using "revenue!..." addresses
    // instead of "capex!...".
    var touchesRevenue = dirtyCells.some(function (addr) {
      return typeof addr === 'string' && addr.indexOf('revenue!') === 0;
    });
    var revenueTotalPreview = touchesRevenue ? _computeRevenueTotalFromDom() : null;

    // C2-PR14: additive only, mirrors capexTotalPreview/
    // revenueTotalPreview's "only recompute when this flush's dirty set
    // actually touched the relevant grid" scoping exactly, using
    // "opex!..." addresses.
    var touchesOpex = dirtyCells.some(function (addr) {
      return typeof addr === 'string' && addr.indexOf('opex!') === 0;
    });
    var opexTotalPreview = touchesOpex ? _computeOpexTotalFromDom() : null;

    // C2-PR15: EBITDA Preview = Revenue Preview − OPEX Preview, computed
    // PURELY from the two preview numbers already computed above in
    // THIS SAME flush (never re-read from DOM, never from Overview
    // KPIs, never from any engine). Since revenueTotalPreview/
    // opexTotalPreview are each independently null unless THIS flush's
    // dirty set touched their own grid (see touchesRevenue/touchesOpex
    // above), EBITDA is therefore null unless both the Revenue and OPEX
    // grids were edited together before the debounce settled (e.g. one
    // edit in each grid within the same debounce window) — this is
    // intentional, not a bug: EBITDA must never be computed from a
    // stale preview value carried over from an earlier, unrelated
    // flush, only from two values genuinely fresh in this exact flush.
    var ebitdaPreview = _computeEbitdaFromPreviews(revenueTotalPreview, opexTotalPreview);

    // C2-PR16: Operating Cash Flow Preview = EBITDA Preview, verbatim.
    // NOT authoritative OCF — see _computeOcfFromEbitda's docstring and
    // docs/C2_PR16_OPERATING_CF_PREVIEW.md.
    var operatingCashFlowPreview = _computeOcfFromEbitda(ebitdaPreview);

    var payload = {
      valid: valid,
      dirtyCells: dirtyCells,
      affectedGroups: affectedGroups,
      projectDirty: projectDirty,
      reason: reason,
      executionStatus: executionStatus,
      project: _readProjectFromLocation(),
      capexTotalPreview: capexTotalPreview,
      revenueTotalPreview: revenueTotalPreview,
      opexTotalPreview: opexTotalPreview,
      ebitdaPreview: ebitdaPreview,
      operatingCashFlowPreview: operatingCashFlowPreview
    };

    _lastPreviewPayload = payload;
    return payload;
  }

  function getLastPreviewPayload() {
    return _lastPreviewPayload;
  }

  function clearLastPreviewPayload() {
    _lastPreviewPayload = null;
  }

  // C2-PR7: backend preview endpoint contract stub now exists at
  // POST /model/preview (see main_web.py / docs/
  // C2_PR7_BACKEND_PREVIEW_ENDPOINT_CONTRACT_STUB_NOTE.md). This is
  // metadata ONLY — no code in this file, or anywhere else in this
  // PR, ever reads this constant to actually perform a fetch.
  var PREVIEW_ENDPOINT = '/model/preview';

  /**
   * C2-PR7: builds a plain-data, request-SHAPED object describing
   * what a FUTURE caller would need to send to the backend preview
   * endpoint contract stub (POST /model/preview) in order to submit
   * `payload`. This function does NOT send anything — no fetch, no
   * XMLHttpRequest, no htmx.ajax/htmx.trigger call exists anywhere in
   * this module. It is inert, unused-by-default infrastructure: no
   * existing code path (FcRecalcExecutor.execute(),
   * FcLiveModel.flushScheduledRecalc(), or any other module) calls
   * this helper automatically. A future PR may choose to wire this up
   * to an actual network call; this PR deliberately does not.
   *
   * Never throws. `payload` is not validated here (callers may pass
   * the result of buildPreviewPayload() directly, or anything else);
   * if `payload` is missing, `body` is simply `null`.
   */
  function buildPreviewRequest(payload) {
    return {
      url: PREVIEW_ENDPOINT,
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: (payload && typeof payload === 'object') ? payload : null
    };
  }

  window.FcRecalcPreview = {
    buildPreviewPayload: buildPreviewPayload,
    validatePreviewPayload: validatePreviewPayload,
    getLastPreviewPayload: getLastPreviewPayload,
    clearLastPreviewPayload: clearLastPreviewPayload,
    buildPreviewRequest: buildPreviewRequest,
    previewEndpoint: PREVIEW_ENDPOINT,
    // C2-PR10: exposed for direct testing of the CAPEX total preview
    // sum independent of a full snapshot/execution flow.
    computeCapexTotalFromDom: _computeCapexTotalFromDom,
    // C2-PR13: exposed for direct testing of the Revenue total preview
    // sum independent of a full snapshot/execution flow.
    computeRevenueTotalFromDom: _computeRevenueTotalFromDom,
    // C2-PR14: exposed for direct testing of the OPEX total preview
    // sum independent of a full snapshot/execution flow.
    computeOpexTotalFromDom: _computeOpexTotalFromDom,
    // C2-PR15: exposed for direct testing of the EBITDA arithmetic
    // independent of a full snapshot/execution flow.
    computeEbitdaFromPreviews: _computeEbitdaFromPreviews,
    // C2-PR16: exposed for direct testing of the OCF passthrough
    // independent of a full snapshot/execution flow.
    computeOcfFromEbitda: _computeOcfFromEbitda
  };
})();
