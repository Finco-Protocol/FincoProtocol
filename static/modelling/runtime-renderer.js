/*
 * FINCO Protocol — Live Modelling Layer
 * C2-PR8: First End-to-End Incremental Runtime Slice (client-side
 * RESPONSE RENDERER only — receives the JSON response from a real
 * POST /model/preview network call made elsewhere (see
 * static/modelling/live-model.js's flushScheduledRecalc()), validates
 * it defensively, and patches exactly ONE existing, NON-FINANCIAL
 * Overview status DOM element. This module never makes a network
 * call itself, never evaluates a financial formula, never calls Save
 * or Run, never touches persistence or export, and never throws.)
 *
 * Reference: docs/C2_PR1_IMPLEMENTATION_NOTE.md through
 *            docs/C2_PR7_BACKEND_PREVIEW_ENDPOINT_CONTRACT_STUB_NOTE.md,
 *            docs/C2_PR8_FIRST_RUNTIME_SLICE.md.
 *
 * Ownership: window.FcRuntimeRenderer is a new, standalone module —
 * like FcDependencyGraph (C2-PR4), FcRecalcExecutor (C2-PR5), and
 * FcRecalcPreview (C2-PR6/PR7), deliberately not folded into
 * FcLiveModel. It owns no dirty-state, scheduler, dependency-graph, or
 * execution state of any kind — it is a pure, stateless DOM-patching
 * consumer of a server response object it is handed by its caller.
 *
 * Input contract: render(responseBody) where responseBody is expected
 * to be shaped like the POST /model/preview JSON response (see
 * main_web.py's model_preview() route / docs/C2_PR7_*.md /
 * docs/C2_PR8_FIRST_RUNTIME_SLICE.md), in particular:
 *   {
 *     ok: true,
 *     ...,
 *     overview: { runtime_status: "<string>", updated: <boolean> }
 *   }
 * `render()` NEVER throws, for any input, including `null`/
 * `undefined`/a non-object/a malformed `overview` field/a response
 * with `ok: false`/a response from a network error path (the caller
 * is expected to pass `null` or an error-shaped object on fetch
 * failure — see live-model.js). On anything that doesn't validate, it
 * is a safe no-op: it does not touch the DOM at all, and the existing
 * status text is left exactly as it was.
 *
 * Output: returns a small diagnostic result object
 *   { rendered: <boolean>, reason: <string> }
 * for callers/tests that want to confirm what happened, but this
 * return value is informational only — nothing in this module's own
 * logic depends on a caller reading it.
 *
 * DOM contract: patches exactly one existing element,
 * #overview-runtime-status-value (inside the always-rendered
 * #overview-runtime-status status region in
 * app/templates/partials/workspace_shell.html's Overview tab). This
 * element holds a plain runtime STATUS string (e.g. "Preview
 * executed"), never an IRR/DSCR/revenue/tax/other real KPI number —
 * deliberately chosen so this slice can never be mistaken for a real
 * recalculation having occurred. If the element is not present in the
 * DOM (e.g. an isolated test fixture, or a future page that doesn't
 * render the Overview tab), this is a safe no-op.
 *
 * C2-PR10: additionally, when the response body carries a "capex"
 * field ({ capex_total_preview: <number>, currency: "EUR" }), this
 * module ALSO patches a second, separate, always-rendered element,
 * #capex-total-preview-value (inside #capex-total-preview, next to —
 * never replacing or relabelling — the C2-PR8 runtime status
 * indicator). This is the first and only real numeric value this
 * whole runtime path is allowed to render anywhere: a plain CAPEX
 * line-item SUM of the live, unsaved CAPEX grid, computed entirely
 * client-side (static/modelling/recalc-preview.js) and merely echoed
 * back by the server — never a real financial-engine output, and
 * never confused with the saved/Run-derived Total CAPEX figure shown
 * elsewhere on the CAPEX sheet. Missing/malformed "capex" is a safe
 * no-op for this part only — it never clears or invalidates a
 * previously-rendered overview status, and a missing/malformed
 * "overview" field never blocks rendering a present, valid "capex"
 * field (the two are rendered independently). See
 * docs/C2_PR10_CAPEX_TOTAL_PREVIEW.md.
 *
 * C2-PR14: a third independent additive patch, mirroring the C2-PR10/
 * PR13 capex/revenue patches exactly — when the response body carries
 * an "opex" field ({ preview: <number>, currency: "EUR" }), this module
 * ALSO patches #opex-total-preview-value. See docs/C2_PR14_OPEX_PREVIEW.md.
 *
 * C2-PR15: a fourth independent additive patch — when the response
 * body carries an "ebitda" field ({ preview: <number|null>, currency:
 * "EUR" }), this module ALSO patches #ebitda-preview-value. EBITDA is
 * never computed here — it arrives already-computed (see
 * static/modelling/recalc-preview.js's _computeEbitdaFromPreviews and
 * docs/C2_PR15_EBITDA_PREVIEW.md for the client-side-computation
 * choice). A null/absent ebitda.preview is a safe no-op for this patch
 * only, exactly like a missing "capex"/"revenue"/"opex" field.
 *
 * C2-PR16: a fifth independent additive patch — when the response body
 * carries an "operating_cash_flow" field ({ preview: <number|null>,
 * currency: "EUR" }), this module ALSO patches
 * #operating-cf-preview-value. *** THIS VALUE IS NOT AUTHORITATIVE
 * OPERATING CASH FLOW *** — it is EBITDA Preview passed through
 * verbatim, with no debt/tax/depreciation/financing adjustment, solely
 * to prove the preview pipeline can chain a preview of a preview of
 * previews. See docs/C2_PR16_OPERATING_CF_PREVIEW.md.
 *
 * C2-PR11 (Runtime Preview UX Polish): the previous binary Idle/
 * "Preview executed" status text is replaced with an explicit 5-state
 * machine — Idle, "Preview updating…", "Preview ready", "Preview
 * unavailable", "Preview failed" — driven by THREE new, additive,
 * non-throwing entry points this module exposes for the request
 * lifecycle's caller (static/modelling/live-model.js) to call at the
 * appropriate moment:
 *
 *   - setUpdating()    — call right before a preview fetch is issued.
 *   - setUnavailable() — call when there is nothing to preview yet
 *                        (e.g. a flush produced no previewPayload, no
 *                        dirty cells, or fetch/FcRecalcPreview isn't
 *                        available) instead of issuing a fetch at all.
 *   - setFailed(seq)   — call from the fetch's .catch()/non-2xx branch.
 *
 * `render(body)` itself becomes the "success" transition (-> "Preview
 * ready"), and is UNCHANGED in its own validation/patch logic — it
 * still patches `#overview-runtime-status-value`'s text to whatever
 * `body.overview.runtime_status` says (still just a status string,
 * still never a financial value) and `#capex-total-preview-value`'s
 * text/badge class to the formatted CAPEX sum, independently, exactly
 * as before. C2-PR11 only adds the explicit state machine bookkeeping
 * (the `data-c2pr11-runtime-state` attribute, the `aria-busy`
 * attribute on the two parent `.runtime-status-indicator` elements,
 * and the `#…-sr` visually-hidden announcement spans) around the
 * existing patches — it does not change what triggers a render or what
 * value gets rendered on success.
 *
 * CRITICAL invariant carried over from C2-PR9's staleness guard,
 * restated here because it is this PR's most safety-critical
 * correctness rule: a `setFailed()` call (or any other non-success
 * state transition) must NEVER blank, reset, or otherwise touch the
 * last successfully-rendered VALUE text of either
 * `#overview-runtime-status-value` or `#capex-total-preview-value` —
 * it only ever changes the STATE label/attributes layered on top of
 * whatever value is already displayed. Only a genuinely newer
 * successful `render()` call is ever allowed to replace a displayed
 * value. `setFailed()`/`setUnavailable()`/`setUpdating()` are pure
 * state-label transitions; they never write to either `__value`
 * element's `textContent` at all — they only touch
 * `data-c2pr11-runtime-state`/`aria-busy`/the `#…-sr` announcement
 * text. The caller (`live-model.js`) is responsible for the existing
 * C2-PR9 sequence-token check that already gates whether a given
 * response is even allowed to reach `render()`/`setFailed()` at all
 * for a given request; this module does not re-implement or weaken
 * that guard — it is a pure consumer of "the caller has already
 * decided this is the response for the newest request."
 *
 * See docs/C2_PR11_PREVIEW_UX_POLISH.md for the full state machine
 * (all 5 states, every valid transition, and exactly what triggers
 * each).
 *
 * This module does NOT:
 *   - make any network/AJAX/htmx call of any kind
 *   - evaluate any formula or call app/waterfall_core.py, domain/*,
 *     or any other financial code
 *   - call Save, Run, or any backend endpoint other than reading the
 *     response object it is handed
 *   - mutate FcLiveModel dirty state, the recalc scheduler,
 *     FcDependencyGraph's registry, or FcRecalcExecutor/FcRecalcPreview
 *     state
 *   - touch any other DOM element, KPI value, or persistence/export
 *     surface
 */
(function () {
  'use strict';

  var STATUS_VALUE_ELEMENT_ID = 'overview-runtime-status-value';
  // C2-PR10: separate target element id for the CAPEX total preview.
  var CAPEX_PREVIEW_VALUE_ELEMENT_ID = 'capex-total-preview-value';
  // C2-PR13: separate target element id for the Revenue total preview,
  // mirroring CAPEX_PREVIEW_VALUE_ELEMENT_ID exactly.
  var REVENUE_PREVIEW_VALUE_ELEMENT_ID = 'revenue-total-preview-value';
  // C2-PR14: separate target element id for the OPEX total preview,
  // mirroring CAPEX_PREVIEW_VALUE_ELEMENT_ID/REVENUE_PREVIEW_VALUE_ELEMENT_ID.
  var OPEX_PREVIEW_VALUE_ELEMENT_ID = 'opex-total-preview-value';
  // C2-PR15: separate target element id for the EBITDA preview.
  var EBITDA_PREVIEW_VALUE_ELEMENT_ID = 'ebitda-preview-value';
  // C2-PR16: separate target element id for the Operating Cash Flow
  // preview. NOT authoritative OCF — see module header comment.
  var OCF_PREVIEW_VALUE_ELEMENT_ID = 'operating-cf-preview-value';
  // C2-PR24: separate target element id for the Debt preview — the
  // FIRST backend-computed (not frontend-computed) preview value this
  // module renders. This module still only formats/patches the DOM;
  // the computation itself happens server-side
  // (app/services/model_preview.py's compute_debt_preview()).
  var DEBT_PREVIEW_VALUE_ELEMENT_ID = 'debt-preview-value';

  // C2-PR11: the two parent status-region elements (used for aria-busy)
  // and the two visually-hidden screen-reader announcement spans.
  // C2-PR13/14/15/16 each add one more region/sr pair.
  var OVERVIEW_REGION_ELEMENT_ID = 'overview-runtime-status';
  var OVERVIEW_SR_ELEMENT_ID = 'overview-runtime-status-sr';
  var CAPEX_REGION_ELEMENT_ID = 'capex-total-preview';
  var CAPEX_SR_ELEMENT_ID = 'capex-total-preview-sr';
  var REVENUE_REGION_ELEMENT_ID = 'revenue-total-preview';
  var REVENUE_SR_ELEMENT_ID = 'revenue-total-preview-sr';
  var OPEX_REGION_ELEMENT_ID = 'opex-total-preview';
  var OPEX_SR_ELEMENT_ID = 'opex-total-preview-sr';
  var EBITDA_REGION_ELEMENT_ID = 'ebitda-preview';
  var EBITDA_SR_ELEMENT_ID = 'ebitda-preview-sr';
  var OCF_REGION_ELEMENT_ID = 'operating-cf-preview';
  var OCF_SR_ELEMENT_ID = 'operating-cf-preview-sr';
  var DEBT_REGION_ELEMENT_ID = 'debt-preview';
  var DEBT_SR_ELEMENT_ID = 'debt-preview-sr';
  // C2-PR25: the two saved-inputs breakdown sub-elements (one span
  // each, both inside the existing #debt-preview container). The
  // renderer ONLY formats/patches these; it never reads or computes
  // any saved inputs itself. If either element is missing from the
  // DOM (older templates), this entire branch is a safe no-op.
  var DEBT_BASIS_CAPEX_ELEMENT_ID = 'debt-preview-saved-capex';
  var DEBT_BASIS_GEARING_ELEMENT_ID = 'debt-preview-saved-gearing';
  var DEBT_BASIS_REGION_ELEMENT_ID = 'debt-preview-basis';
  // C2-PR30: tax-preview slice — second backend-owned preview row
  // after debt. The renderer is forbidden from computing any tax
  // number; it ONLY patches the DOM with whatever the backend
  // decided to send (today: always preview-unavailable / null /
  // em-dash placeholder).
  var TAX_PREVIEW_VALUE_ELEMENT_ID = 'tax-preview-value';
  var TAX_REGION_ELEMENT_ID = 'tax-preview';
  var TAX_SR_ELEMENT_ID = 'tax-preview-sr';
  // C2-PR31: IRR preview slice — backend-owned. The renderer is
  // forbidden from computing any IRR number; it ONLY patches the
  // DOM with whatever the backend decided to send (today: always
  // preview-unavailable / null / em-dash placeholder).
  var IRR_PREVIEW_VALUE_ELEMENT_ID = 'irr-preview-value';
  var IRR_REGION_ELEMENT_ID = 'irr-preview';
  var IRR_SR_ELEMENT_ID = 'irr-preview-sr';
  // C2-PR32: DSCR preview slice — backend-owned. Mirrors IRR's
  // contract exactly.
  var DSCR_PREVIEW_VALUE_ELEMENT_ID = 'dscr-preview-value';
  var DSCR_REGION_ELEMENT_ID = 'dscr-preview';
  var DSCR_SR_ELEMENT_ID = 'dscr-preview-sr';

  // C2-PR11: the explicit 5-state machine. See
  // docs/C2_PR11_PREVIEW_UX_POLISH.md for the full description of every
  // valid transition between these states.
  var STATE = {
    IDLE: 'idle',
    UPDATING: 'updating',
    READY: 'ready',
    UNAVAILABLE: 'unavailable',
    FAILED: 'failed'
  };

  var STATE_LABEL = {
    idle: 'Idle',
    updating: 'Preview updating…',
    ready: 'Preview ready',
    unavailable: 'Preview unavailable',
    failed: 'Preview failed'
  };

  function _isNonEmptyString(v) {
    return typeof v === 'string' && v.length > 0;
  }

  function _getEl(id) {
    return (typeof document !== 'undefined' && document.getElementById)
      ? document.getElementById(id)
      : null;
  }

  /**
   * C2-PR11: shared bookkeeping helper for BOTH status regions —
   * always sets `data-c2pr11-runtime-state` on the value element,
   * `aria-busy` on the parent region element, and the visually-hidden
   * `#…-sr` announcement span's text. Never throws; a missing element
   * for any of the three ids involved is a safe partial no-op.
   *
   * Does NOT touch `textContent` itself — callers decide that
   * separately (see `_setOverviewState`/`_setCapexState` below), since
   * the two regions have different value-preservation rules: the
   * Overview status element's "value" IS the state label itself (its
   * one and only content is a plain runtime status string — C2-PR8's
   * own design choice, unchanged here), so it is always safe and
   * correct to update its displayed text on every transition. The
   * CAPEX preview element's value is a real computed number that must
   * NEVER be touched by a non-success transition — only `render()`'s
   * own value-patching code ever writes that element's text.
   */
  function _setBookkeeping(valueElementId, regionElementId, srElementId, state, srPrefix) {
    var label = STATE_LABEL[state] || STATE_LABEL[STATE.IDLE];
    var valueEl = _getEl(valueElementId);
    if (valueEl) {
      valueEl.setAttribute('data-c2pr11-runtime-state', state);
    }
    var regionEl = _getEl(regionElementId);
    if (regionEl) {
      regionEl.setAttribute('aria-busy', state === STATE.UPDATING ? 'true' : 'false');
    }
    var srEl = _getEl(srElementId);
    if (srEl) {
      srEl.textContent = srPrefix + label;
    }
    return { state: state, label: label, valueEl: valueEl };
  }

  /**
   * C2-PR11: transitions the Overview runtime-status region to `state`.
   * Unlike the CAPEX region, this element's displayed text IS the
   * state label (it has never shown anything but a plain status string
   * since C2-PR8), so every transition safely updates
   * `#overview-runtime-status-value`'s `textContent` to the new
   * label — there is no separate "value" to preserve here distinct
   * from the status itself.
   */
  function _setOverviewState(state) {
    var result = _setBookkeeping(
      STATUS_VALUE_ELEMENT_ID, OVERVIEW_REGION_ELEMENT_ID, OVERVIEW_SR_ELEMENT_ID,
      state, 'Runtime preview status: '
    );
    if (result.valueEl) {
      result.valueEl.textContent = result.label;
    }
  }

  /**
   * C2-PR11: transitions the CAPEX preview region's state-machine
   * bookkeeping ONLY — CRITICALLY, this never writes to
   * `#capex-total-preview-value`'s `textContent`. That element's text
   * is a real computed number; only `render()`'s own existing
   * value-patching code (the success edge) is ever allowed to change
   * it. A failed/unavailable/updating transition leaves whatever
   * number (or the initial "—" placeholder) was already displayed
   * completely untouched — only `data-c2pr11-runtime-state`,
   * `aria-busy`, and the `#capex-total-preview-sr` announcement change.
   */
  function _setCapexState(state) {
    _setBookkeeping(
      CAPEX_PREVIEW_VALUE_ELEMENT_ID, CAPEX_REGION_ELEMENT_ID, CAPEX_SR_ELEMENT_ID,
      state, 'CAPEX preview status: '
    );
  }

  /**
   * C2-PR13: transitions the Revenue preview region's state-machine
   * bookkeeping ONLY — mirrors `_setCapexState` exactly. Never writes
   * to `#revenue-total-preview-value`'s `textContent`; only `render()`'s
   * own value-patching code (the success edge) is ever allowed to
   * change it.
   */
  function _setRevenueState(state) {
    _setBookkeeping(
      REVENUE_PREVIEW_VALUE_ELEMENT_ID, REVENUE_REGION_ELEMENT_ID, REVENUE_SR_ELEMENT_ID,
      state, 'Revenue preview status: '
    );
  }

  /**
   * C2-PR14: transitions the OPEX preview region's state-machine
   * bookkeeping ONLY — mirrors `_setCapexState`/`_setRevenueState`
   * exactly. Never writes to `#opex-total-preview-value`'s
   * `textContent`.
   */
  function _setOpexState(state) {
    _setBookkeeping(
      OPEX_PREVIEW_VALUE_ELEMENT_ID, OPEX_REGION_ELEMENT_ID, OPEX_SR_ELEMENT_ID,
      state, 'OPEX preview status: '
    );
  }

  /**
   * C2-PR15: transitions the EBITDA preview region's state-machine
   * bookkeeping ONLY — mirrors the other `_set*State` helpers exactly.
   * Never writes to `#ebitda-preview-value`'s `textContent`.
   */
  function _setEbitdaState(state) {
    _setBookkeeping(
      EBITDA_PREVIEW_VALUE_ELEMENT_ID, EBITDA_REGION_ELEMENT_ID, EBITDA_SR_ELEMENT_ID,
      state, 'EBITDA preview status: '
    );
  }

  /**
   * C2-PR16: transitions the Operating Cash Flow preview region's
   * state-machine bookkeeping ONLY — mirrors the other `_set*State`
   * helpers exactly. Never writes to `#operating-cf-preview-value`'s
   * `textContent`.
   */
  function _setOcfState(state) {
    _setBookkeeping(
      OCF_PREVIEW_VALUE_ELEMENT_ID, OCF_REGION_ELEMENT_ID, OCF_SR_ELEMENT_ID,
      state, 'Operating cash flow preview status: '
    );
  }

  /**
   * C2-PR24: transitions the Debt preview region's state-machine
   * bookkeeping ONLY — mirrors the other `_set*State` helpers exactly.
   * Never writes to `#debt-preview-value`'s `textContent`. The debt
   * preview VALUE itself is backend-computed
   * (app/services/model_preview.py's compute_debt_preview()); this
   * module still only ever renders it, never computes it.
   */
  function _setDebtState(state) {
    _setBookkeeping(
      DEBT_PREVIEW_VALUE_ELEMENT_ID, DEBT_REGION_ELEMENT_ID, DEBT_SR_ELEMENT_ID,
      state, 'Debt preview status: '
    );
  }

  /**
   * C2-PR30: transitions the Tax preview region's state-machine
   * bookkeeping ONLY — mirrors `_setDebtState` exactly. Never writes
   * to `#tax-preview-value`'s `textContent`. The tax preview VALUE
   * itself (when it ever exists) is backend-computed by
   * app/services/previews/tax_preview.py; this module only ever
   * renders it, never computes it. Today the backend always reports
   * preview-unavailable so the renderer's tax branch is mostly a
   * safe no-op except for bookkeeping state transitions.
   */
  function _setTaxState(state) {
    _setBookkeeping(
      TAX_PREVIEW_VALUE_ELEMENT_ID, TAX_REGION_ELEMENT_ID, TAX_SR_ELEMENT_ID,
      state, 'Tax preview status: '
    );
  }

  /**
   * C2-PR31: transitions the IRR preview region's state-machine
   * bookkeeping ONLY — mirrors `_setTaxState` exactly. Never writes
   * to `#irr-preview-value`'s `textContent`. The IRR preview VALUE
   * itself (when it ever exists) is backend-computed by
   * app/services/previews/irr_preview.py; this module only ever
   * renders it, never computes it. Today the backend always reports
   * preview-unavailable so the renderer's IRR branch is mostly a
   * safe no-op except for bookkeeping state transitions.
   */
  function _setIrrState(state) {
    _setBookkeeping(
      IRR_PREVIEW_VALUE_ELEMENT_ID, IRR_REGION_ELEMENT_ID, IRR_SR_ELEMENT_ID,
      state, 'IRR preview status: '
    );
  }

  /**
   * C2-PR32: transitions the DSCR preview region's state-machine
   * bookkeeping ONLY — mirrors `_setTaxState` exactly. Never writes
   * to `#dscr-preview-value`'s `textContent`. The DSCR preview VALUE
   * itself (when it ever exists) is backend-computed by
   * app/services/previews/dscr_preview.py; this module only ever
   * renders it, never computes it. Today the backend always reports
   * preview-unavailable so the renderer's DSCR branch is mostly a
   * safe no-op except for bookkeeping state transitions.
   */
  function _setDscrState(state) {
    _setBookkeeping(
      DSCR_PREVIEW_VALUE_ELEMENT_ID, DSCR_REGION_ELEMENT_ID, DSCR_SR_ELEMENT_ID,
      state, 'DSCR preview status: '
    );
  }

  /**
   * C2-PR11: call right before a preview fetch is issued (i.e. at the
   * very start of a flush that is about to call fetch(POST
   * /model/preview)). Transitions BOTH the overview and CAPEX status
   * regions to "Preview updating…" / aria-busy="true". Never throws.
   * Never touches `#capex-total-preview-value`'s displayed text.
   */
  function setUpdating() {
    _setOverviewState(STATE.UPDATING);
    _setCapexState(STATE.UPDATING);
    _setRevenueState(STATE.UPDATING);
    _setOpexState(STATE.UPDATING);
    _setEbitdaState(STATE.UPDATING);
    _setOcfState(STATE.UPDATING);
    _setDebtState(STATE.UPDATING);
    // C2-PR30: tax preview bookkeeping mirrors the other six slices.
    _setTaxState(STATE.UPDATING);
    // C2-PR31: IRR preview bookkeeping mirrors the other seven slices.
    _setIrrState(STATE.UPDATING);
    // C2-PR32: DSCR preview bookkeeping mirrors the other eight slices.
    _setDscrState(STATE.UPDATING);
  }

  /**
   * C2-PR11: call when the pipeline determines there is nothing to
   * preview yet for this flush (no previewPayload was built, no dirty
   * cells, FcRecalcPreview/fetch unavailable, etc.) — i.e. instead of
   * ever issuing a fetch at all. Transitions to "Preview unavailable".
   * Never throws. Never touches `#capex-total-preview-value`'s
   * displayed text.
   */
  function setUnavailable() {
    _setOverviewState(STATE.UNAVAILABLE);
    _setCapexState(STATE.UNAVAILABLE);
    _setRevenueState(STATE.UNAVAILABLE);
    _setOpexState(STATE.UNAVAILABLE);
    _setEbitdaState(STATE.UNAVAILABLE);
    _setOcfState(STATE.UNAVAILABLE);
    _setDebtState(STATE.UNAVAILABLE);
  }

  /**
   * C2-PR11: call from the fetch's failure path (network error, non-2xx
   * status, or a JSON parse failure) for the response belonging to the
   * NEWEST issued request (the caller's existing C2-PR9 sequence-token
   * check is what decides this — this function does not re-check
   * staleness itself, it trusts its caller). Transitions to "Preview
   * failed".
   *
   * CRITICAL: this NEVER blanks, resets, or otherwise alters the
   * previously-rendered CAPEX preview VALUE text — only its state
   * label/aria-busy/sr-announcement change. The Overview status
   * element's text DOES change to "Preview failed" (that element's
   * text has always been a pure status string with no separate "value"
   * to preserve — see `_setOverviewState`). A user who has a valid
   * CAPEX preview number on screen and then experiences one failed
   * request continues to see that exact number, with only the Overview
   * status text and the CAPEX region's state attributes changing.
   * Never throws.
   */
  function setFailed() {
    _setOverviewState(STATE.FAILED);
    _setCapexState(STATE.FAILED);
    _setRevenueState(STATE.FAILED);
    _setOpexState(STATE.FAILED);
    _setEbitdaState(STATE.FAILED);
    _setOcfState(STATE.FAILED);
    _setDebtState(STATE.FAILED);
  }

  /**
   * C2-PR10: defensive, non-throwing shape-check for a POST
   * /model/preview response body's "capex" field. Returns true only
   * when "capex" is an object with a finite-number
   * "capex_total_preview" field — the only field this module actually
   * renders. "currency" is tolerated as present-or-absent/any type; it
   * is informational metadata only.
   */
  function _hasRenderableCapexPreview(body) {
    if (!body || typeof body !== 'object') return false;
    var capex = body.capex;
    if (!capex || typeof capex !== 'object') return false;
    var total = capex.capex_total_preview;
    return typeof total === 'number' && isFinite(total);
  }

  /**
   * C2-PR13: defensive, non-throwing shape-check for a POST
   * /model/preview response body's "revenue" field — mirrors
   * `_hasRenderableCapexPreview` exactly, reading `revenue.preview`
   * (the field name specified in the task contract) instead of
   * `capex.capex_total_preview`.
   */
  function _hasRenderableRevenuePreview(body) {
    if (!body || typeof body !== 'object') return false;
    var revenue = body.revenue;
    if (!revenue || typeof revenue !== 'object') return false;
    var total = revenue.preview;
    return typeof total === 'number' && isFinite(total);
  }

  /**
   * C2-PR14: defensive, non-throwing shape-check for a POST
   * /model/preview response body's "opex" field — mirrors
   * `_hasRenderableRevenuePreview` exactly, reading `opex.preview`.
   */
  function _hasRenderableOpexPreview(body) {
    if (!body || typeof body !== 'object') return false;
    var opex = body.opex;
    if (!opex || typeof opex !== 'object') return false;
    var total = opex.preview;
    return typeof total === 'number' && isFinite(total);
  }

  /**
   * C2-PR15: defensive, non-throwing shape-check for a POST
   * /model/preview response body's "ebitda" field — reads
   * `ebitda.preview`. A null/absent preview (e.g. revenue or opex
   * preview was unavailable this flush) is correctly NOT renderable —
   * the element keeps showing its last valid value (or the initial "—"
   * placeholder), exactly like every other preview field in this chain.
   */
  function _hasRenderableEbitdaPreview(body) {
    if (!body || typeof body !== 'object') return false;
    var ebitda = body.ebitda;
    if (!ebitda || typeof ebitda !== 'object') return false;
    var total = ebitda.preview;
    return typeof total === 'number' && isFinite(total);
  }

  /**
   * C2-PR16: defensive, non-throwing shape-check for a POST
   * /model/preview response body's "operating_cash_flow" field — reads
   * `operating_cash_flow.preview`. NOT authoritative OCF — see module
   * header comment.
   */
  function _hasRenderableOcfPreview(body) {
    if (!body || typeof body !== 'object') return false;
    var ocf = body.operating_cash_flow;
    if (!ocf || typeof ocf !== 'object') return false;
    var total = ocf.preview;
    return typeof total === 'number' && isFinite(total);
  }

  /**
   * C2-PR24: defensive, non-throwing shape-check for a POST
   * /model/preview response body's "debt" field — reads
   * `debt.senior_debt_preview`. Only renderable when `debt.status` is
   * the success status `"preview-ready"` AND `senior_debt_preview` is
   * a finite number; the `"preview-unavailable"`/`null` case is
   * correctly NOT renderable, leaving the placeholder "—" in place,
   * exactly like every other preview field in this chain.
   */
  function _hasRenderableDebtPreview(body) {
    if (!body || typeof body !== 'object') return false;
    var debt = body.debt;
    if (!debt || typeof debt !== 'object') return false;
    if (debt.status !== 'preview-ready') return false;
    var total = debt.senior_debt_preview;
    return typeof total === 'number' && isFinite(total);
  }

  /**
   * C2-PR10: formats a total preview number for display. Plain,
   * fixed 2-decimal formatting with thousands separators — no currency
   * conversion, no rounding beyond presentation, no calculation beyond
   * what was already summed/rounded by the caller. C2-PR13 reuses this
   * exact same formatter for the Revenue total preview (renamed from
   * `_formatCapexTotal` to `_formatTotalPreview` since it is no longer
   * CAPEX-specific; no formatting behaviour changed).
   */
  function _formatTotalPreview(total, currency) {
    var formatted;
    try {
      formatted = total.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    } catch (e) {
      formatted = total.toFixed(2);
    }
    return _isNonEmptyString(currency) ? (formatted + ' ' + currency) : formatted;
  }

  /**
   * Defensive, non-throwing shape-check for a POST /model/preview
   * response body's "overview" field specifically. Returns true only
   * when `overview` is an object with a non-empty string
   * `runtime_status` field (the only field this module actually
   * renders). `updated` is tolerated as present-or-absent/any type —
   * it is informational metadata only, not required for rendering.
   */
  function _hasRenderableOverview(body) {
    if (!body || typeof body !== 'object') return false;
    var overview = body.overview;
    if (!overview || typeof overview !== 'object') return false;
    return _isNonEmptyString(overview.runtime_status);
  }

  /**
   * Renders a parsed POST /model/preview response body by patching
   * the single #overview-runtime-status-value DOM element with the
   * response's overview.runtime_status string. Never throws.
   *
   * Safe-no-op cases (all return { rendered: false, reason: ... }):
   *   - `body` is null/undefined/not an object (e.g. a network error
   *     was passed through by the caller instead of a parsed response)
   *   - `body.overview` is missing or malformed
   *   - `body.overview.runtime_status` is missing or not a non-empty
   *     string
   *   - the target DOM element does not exist on the current page
   *
   * Deterministic: the same valid input always produces the same DOM
   * text content, synchronously, with no animation/timing/randomness
   * involved.
   */
  function render(body) {
    if (!body || typeof body !== 'object') {
      return { rendered: false, reason: 'no-response-body' };
    }

    var overviewRendered = false;
    var overviewReason = 'missing-or-malformed-overview';

    if (_hasRenderableOverview(body)) {
      var statusEl = (typeof document !== 'undefined' && document.getElementById)
        ? document.getElementById(STATUS_VALUE_ELEMENT_ID)
        : null;
      if (statusEl) {
        statusEl.textContent = body.overview.runtime_status;
        statusEl.setAttribute('data-c2pr8-runtime-status', 'patched');
        // C2-PR11: a successful render is the ONLY transition into
        // "Preview ready" — the success edge of the state machine.
        // Uses the shared `_setBookkeeping` helper directly (NOT
        // `_setOverviewState`, which would overwrite the real
        // `runtime_status` text just written above with the generic
        // "Preview ready" label) so only the state-machine bookkeeping
        // (data-c2pr11-runtime-state/aria-busy/sr text) changes here,
        // never the just-written value text.
        _setBookkeeping(STATUS_VALUE_ELEMENT_ID, OVERVIEW_REGION_ELEMENT_ID, OVERVIEW_SR_ELEMENT_ID, STATE.READY, 'Runtime preview status: ');
        overviewRendered = true;
        overviewReason = 'ok';
      } else {
        overviewReason = 'target-element-not-found';
      }
    }

    // C2-PR10: independent second patch — a missing/malformed "capex"
    // field never blocks the overview status patch above, and vice
    // versa. Each is rendered (or safely skipped) on its own merits.
    var capexRendered = false;
    var capexReason = 'missing-or-malformed-capex';

    if (_hasRenderableCapexPreview(body)) {
      var capexEl = (typeof document !== 'undefined' && document.getElementById)
        ? document.getElementById(CAPEX_PREVIEW_VALUE_ELEMENT_ID)
        : null;
      if (capexEl) {
        capexEl.textContent = _formatTotalPreview(body.capex.capex_total_preview, body.capex.currency);
        capexEl.setAttribute('data-c2pr10-capex-preview', 'patched');
        // C2-PR11: success edge -> "Preview ready" bookkeeping for the
        // CAPEX region, in lockstep with the value patch immediately
        // above. Uses `_setBookkeeping` directly (not `_setCapexState`,
        // though they're equivalent here) for symmetry with the
        // Overview branch above.
        _setBookkeeping(CAPEX_PREVIEW_VALUE_ELEMENT_ID, CAPEX_REGION_ELEMENT_ID, CAPEX_SR_ELEMENT_ID, STATE.READY, 'CAPEX preview status: ');
        capexRendered = true;
        capexReason = 'ok';
      } else {
        capexReason = 'target-element-not-found';
      }
    }

    // C2-PR13: independent third patch — mirrors the CAPEX block above
    // exactly. A missing/malformed "revenue" field never blocks the
    // overview/capex patches, and vice versa; each of the three is
    // rendered (or safely skipped) on its own merits.
    var revenueRendered = false;
    var revenueReason = 'missing-or-malformed-revenue';

    if (_hasRenderableRevenuePreview(body)) {
      var revenueEl = (typeof document !== 'undefined' && document.getElementById)
        ? document.getElementById(REVENUE_PREVIEW_VALUE_ELEMENT_ID)
        : null;
      if (revenueEl) {
        revenueEl.textContent = _formatTotalPreview(body.revenue.preview, body.revenue.currency);
        revenueEl.setAttribute('data-c2pr13-revenue-preview', 'patched');
        // C2-PR11-style success edge -> "Preview ready" bookkeeping for
        // the Revenue region, in lockstep with the value patch
        // immediately above.
        _setBookkeeping(REVENUE_PREVIEW_VALUE_ELEMENT_ID, REVENUE_REGION_ELEMENT_ID, REVENUE_SR_ELEMENT_ID, STATE.READY, 'Revenue preview status: ');
        revenueRendered = true;
        revenueReason = 'ok';
      } else {
        revenueReason = 'target-element-not-found';
      }
    }

    // C2-PR14: independent fourth patch — mirrors the CAPEX/Revenue
    // blocks above exactly.
    var opexRendered = false;
    var opexReason = 'missing-or-malformed-opex';

    if (_hasRenderableOpexPreview(body)) {
      var opexEl = (typeof document !== 'undefined' && document.getElementById)
        ? document.getElementById(OPEX_PREVIEW_VALUE_ELEMENT_ID)
        : null;
      if (opexEl) {
        opexEl.textContent = _formatTotalPreview(body.opex.preview, body.opex.currency);
        opexEl.setAttribute('data-c2pr14-opex-preview', 'patched');
        _setBookkeeping(OPEX_PREVIEW_VALUE_ELEMENT_ID, OPEX_REGION_ELEMENT_ID, OPEX_SR_ELEMENT_ID, STATE.READY, 'OPEX preview status: ');
        opexRendered = true;
        opexReason = 'ok';
      } else {
        opexReason = 'target-element-not-found';
      }
    }

    // C2-PR15: independent fifth patch. EBITDA arrives already-
    // computed (client-side arithmetic on revenue/opex previews); this
    // module only formats and patches the DOM, exactly like every other
    // preview field.
    var ebitdaRendered = false;
    var ebitdaReason = 'missing-or-malformed-ebitda';

    if (_hasRenderableEbitdaPreview(body)) {
      var ebitdaEl = (typeof document !== 'undefined' && document.getElementById)
        ? document.getElementById(EBITDA_PREVIEW_VALUE_ELEMENT_ID)
        : null;
      if (ebitdaEl) {
        ebitdaEl.textContent = _formatTotalPreview(body.ebitda.preview, body.ebitda.currency);
        ebitdaEl.setAttribute('data-c2pr15-ebitda-preview', 'patched');
        _setBookkeeping(EBITDA_PREVIEW_VALUE_ELEMENT_ID, EBITDA_REGION_ELEMENT_ID, EBITDA_SR_ELEMENT_ID, STATE.READY, 'EBITDA preview status: ');
        ebitdaRendered = true;
        ebitdaReason = 'ok';
      } else {
        ebitdaReason = 'target-element-not-found';
      }
    }

    // C2-PR16: independent sixth patch. *** NOT AUTHORITATIVE OCF ***
    // — this value is EBITDA Preview passed straight through; see the
    // module header comment and docs/C2_PR16_OPERATING_CF_PREVIEW.md.
    var ocfRendered = false;
    var ocfReason = 'missing-or-malformed-operating-cash-flow';

    if (_hasRenderableOcfPreview(body)) {
      var ocfEl = (typeof document !== 'undefined' && document.getElementById)
        ? document.getElementById(OCF_PREVIEW_VALUE_ELEMENT_ID)
        : null;
      if (ocfEl) {
        ocfEl.textContent = _formatTotalPreview(body.operating_cash_flow.preview, body.operating_cash_flow.currency);
        ocfEl.setAttribute('data-c2pr16-ocf-preview', 'patched');
        _setBookkeeping(OCF_PREVIEW_VALUE_ELEMENT_ID, OCF_REGION_ELEMENT_ID, OCF_SR_ELEMENT_ID, STATE.READY, 'Operating cash flow preview status: ');
        ocfRendered = true;
        ocfReason = 'ok';
      } else {
        ocfReason = 'target-element-not-found';
      }
    }

    // C2-PR24: independent seventh patch — the FIRST backend-computed
    // preview field. This module performs zero arithmetic here either:
    // it only formats and patches the DOM with the already-computed
    // `senior_debt_preview` number the server sent. A
    // "preview-unavailable"/null debt field is a safe no-op, exactly
    // like every other preview field above.
    var debtRendered = false;
    var debtReason = 'missing-or-malformed-debt';

    // C2-PR26: basis sub-line element ids (added in this PR).
    var debtBasisEl = (typeof document !== 'undefined' && document.getElementById)
      ? document.getElementById(DEBT_BASIS_REGION_ELEMENT_ID) : null;
    var debtBasisCapexEl = (typeof document !== 'undefined' && document.getElementById)
      ? document.getElementById(DEBT_BASIS_CAPEX_ELEMENT_ID) : null;
    var debtBasisGearingEl = (typeof document !== 'undefined' && document.getElementById)
      ? document.getElementById(DEBT_BASIS_GEARING_ELEMENT_ID) : null;

    if (_hasRenderableDebtPreview(body)) {
      var debtEl = (typeof document !== 'undefined' && document.getElementById)
        ? document.getElementById(DEBT_PREVIEW_VALUE_ELEMENT_ID)
        : null;
      if (debtEl) {
        debtEl.textContent = _formatTotalPreview(body.debt.senior_debt_preview, body.debt.currency);
        debtEl.setAttribute('data-c2pr24-debt-preview', 'patched');
        // C2-PR25: patch the saved-inputs breakdown sub-line. The
        // values are EXACTLY what the server already decided in
        // app/services/model_preview.py's compute_debt_preview();
        // the renderer only formats them — it never reads or
        // computes anything. Both fields are guaranteed to be
        // finite numbers when status === 'preview-ready' (the same
        // condition that gated _hasRenderableDebtPreview() above).
        if (debtBasisCapexEl && body.debt.saved_total_capex !== undefined && body.debt.saved_total_capex !== null) {
          debtBasisCapexEl.textContent = _formatTotalPreview(body.debt.saved_total_capex, body.debt.currency);
        }
        if (debtBasisGearingEl && body.debt.saved_gearing_pct !== undefined && body.debt.saved_gearing_pct !== null) {
          // Gearing is a 0-100 percentage; show as plain % (no currency).
          debtBasisGearingEl.textContent = body.debt.saved_gearing_pct.toFixed(2) + ' %';
        }
        if (debtBasisEl) {
          debtBasisEl.setAttribute('data-c2pr25-debt-basis', 'patched');
        }
        _setBookkeeping(DEBT_PREVIEW_VALUE_ELEMENT_ID, DEBT_REGION_ELEMENT_ID, DEBT_SR_ELEMENT_ID, STATE.READY, 'Debt preview status: ');
        debtRendered = true;
        debtReason = 'ok';
      } else {
        debtReason = 'target-element-not-found';
      }
    } else if (body && body.debt && body.debt.status === 'preview-unavailable') {
      // C2-PR25: when the server explicitly reports "preview-
      // unavailable", make sure the basis sub-line reverts to the
      // em-dash placeholder (in case a prior successful render left
      // stale numbers on screen). Renderer-only behaviour; the
      // server never sends stale data.
      if (debtBasisCapexEl) { debtBasisCapexEl.textContent = '\u2014'; }
      if (debtBasisGearingEl) { debtBasisGearingEl.textContent = '\u2014'; }
      if (debtBasisEl) {
        debtBasisEl.setAttribute('data-c2pr25-debt-basis', 'idle');
      }
    }

    // C2-PR30: independent eighth patch — Tax preview. The backend
    // today always reports `status === "preview-unavailable"` and
    // `tax_preview === null`, so the DOM is patched with the em-dash
    // placeholder and a backend-state bookkeeping entry — both are
    // safe even if the backend later starts returning a real
    // `preview-ready` value, because `_hasRenderableTaxPreview()`
    // gates on the same conditions debt uses.
    var taxRendered = false;
    var taxReason = 'missing-or-malformed-tax';

    function _hasRenderableTaxPreview(body) {
      if (!body || typeof body !== 'object') return false;
      var tax = body.tax;
      if (!tax || typeof tax !== 'object') return false;
      if (tax.status !== 'preview-ready') return false;
      var v = tax.tax_preview;
      if (v === null || v === undefined) return false;
      if (typeof v !== 'number' || !isFinite(v)) return false;
      return true;
    }

    if (_hasRenderableTaxPreview(body)) {
      // Future path: the backend will compute a real tax preview
      // here. Until then, this branch is dead code, but kept
      // identical to the debt pattern so the architecture is
      // forward-compatible without further refactor.
      var taxEl = (typeof document !== 'undefined' && document.getElementById)
        ? document.getElementById(TAX_PREVIEW_VALUE_ELEMENT_ID)
        : null;
      if (taxEl) {
        taxEl.textContent = _formatTotalPreview(body.tax.tax_preview, body.tax.currency);
        taxEl.setAttribute('data-c2pr30-tax-preview', 'patched');
        _setBookkeeping(TAX_PREVIEW_VALUE_ELEMENT_ID, TAX_REGION_ELEMENT_ID, TAX_SR_ELEMENT_ID, STATE.READY, 'Tax preview status: ');
        taxRendered = true;
        taxReason = 'ok';
      } else {
        taxReason = 'target-element-not-found';
      }
    } else if (body && body.tax && body.tax.status === 'preview-unavailable') {
      // C2-PR30: always-unavailable path. Make sure the placeholder
      // is the em-dash even if a stale render left something behind.
      var taxElIdle = (typeof document !== 'undefined' && document.getElementById)
        ? document.getElementById(TAX_PREVIEW_VALUE_ELEMENT_ID)
        : null;
      if (taxElIdle) {
        taxElIdle.textContent = '\u2014';
        taxElIdle.setAttribute('data-c2pr30-tax-preview', 'idle');
        _setBookkeeping(TAX_PREVIEW_VALUE_ELEMENT_ID, TAX_REGION_ELEMENT_ID, TAX_SR_ELEMENT_ID, STATE.READY, 'Tax preview status: ');
        taxRendered = true;
        taxReason = 'preview-unavailable-shown-as-placeholder';
      } else {
        taxReason = 'target-element-not-found';
      }
    }

    // C2-PR31: independent ninth patch — IRR preview. Mirrors the
    // tax-preview branch exactly. The backend today always reports
    // `status === "preview-unavailable"` and `irr_preview === null`,
    // so the DOM is patched with the em-dash placeholder and a
    // backend-state bookkeeping entry.
    var irrRendered = false;
    var irrReason = 'missing-or-malformed-irr';

    function _hasRenderableIrrPreview(body) {
      if (!body || typeof body !== 'object') return false;
      var irr = body.irr;
      if (!irr || typeof irr !== 'object') return false;
      if (irr.status !== 'preview-ready') return false;
      var v = irr.irr_preview;
      if (v === null || v === undefined) return false;
      if (typeof v !== 'number' || !isFinite(v)) return false;
      return true;
    }

    if (_hasRenderableIrrPreview(body)) {
      // Future path: the backend will compute a real IRR here. Until
      // then this branch is dead code, kept identical to the
      // debt/tax pattern so the architecture is forward-compatible
      // without further refactor.
      var irrEl = (typeof document !== 'undefined' && document.getElementById)
        ? document.getElementById(IRR_PREVIEW_VALUE_ELEMENT_ID)
        : null;
      if (irrEl) {
        irrEl.textContent = _formatTotalPreview(body.irr.irr_preview, body.irr.currency);
        irrEl.setAttribute('data-c2pr31-irr-preview', 'patched');
        _setBookkeeping(IRR_PREVIEW_VALUE_ELEMENT_ID, IRR_REGION_ELEMENT_ID, IRR_SR_ELEMENT_ID, STATE.READY, 'IRR preview status: ');
        irrRendered = true;
        irrReason = 'ok';
      } else {
        irrReason = 'target-element-not-found';
      }
    } else if (body && body.irr && body.irr.status === 'preview-unavailable') {
      // Always-unavailable path. Patch with em-dash placeholder.
      var irrElIdle = (typeof document !== 'undefined' && document.getElementById)
        ? document.getElementById(IRR_PREVIEW_VALUE_ELEMENT_ID)
        : null;
      if (irrElIdle) {
        irrElIdle.textContent = '\u2014';
        irrElIdle.setAttribute('data-c2pr31-irr-preview', 'idle');
        _setBookkeeping(IRR_PREVIEW_VALUE_ELEMENT_ID, IRR_REGION_ELEMENT_ID, IRR_SR_ELEMENT_ID, STATE.READY, 'IRR preview status: ');
        irrRendered = true;
        irrReason = 'preview-unavailable-shown-as-placeholder';
      } else {
        irrReason = 'target-element-not-found';
      }
    }

    // C2-PR32: independent tenth patch — DSCR preview. Mirrors the
    // tax/IRR-preview branches exactly.
    var dscrRendered = false;
    var dscrReason = 'missing-or-malformed-dscr';

    function _hasRenderableDscrPreview(body) {
      if (!body || typeof body !== 'object') return false;
      var dscr = body.dscr;
      if (!dscr || typeof dscr !== 'object') return false;
      if (dscr.status !== 'preview-ready') return false;
      var v = dscr.dscr_preview;
      if (v === null || v === undefined) return false;
      if (typeof v !== 'number' || !isFinite(v)) return false;
      return true;
    }

    if (_hasRenderableDscrPreview(body)) {
      var dscrEl = (typeof document !== 'undefined' && document.getElementById)
        ? document.getElementById(DSCR_PREVIEW_VALUE_ELEMENT_ID)
        : null;
      if (dscrEl) {
        dscrEl.textContent = _formatTotalPreview(body.dscr.dscr_preview, body.dscr.currency);
        dscrEl.setAttribute('data-c2pr32-dscr-preview', 'patched');
        _setBookkeeping(DSCR_PREVIEW_VALUE_ELEMENT_ID, DSCR_REGION_ELEMENT_ID, DSCR_SR_ELEMENT_ID, STATE.READY, 'DSCR preview status: ');
        dscrRendered = true;
        dscrReason = 'ok';
      } else {
        dscrReason = 'target-element-not-found';
      }
    } else if (body && body.dscr && body.dscr.status === 'preview-unavailable') {
      var dscrElIdle = (typeof document !== 'undefined' && document.getElementById)
        ? document.getElementById(DSCR_PREVIEW_VALUE_ELEMENT_ID)
        : null;
      if (dscrElIdle) {
        dscrElIdle.textContent = '\u2014';
        dscrElIdle.setAttribute('data-c2pr32-dscr-preview', 'idle');
        _setBookkeeping(DSCR_PREVIEW_VALUE_ELEMENT_ID, DSCR_REGION_ELEMENT_ID, DSCR_SR_ELEMENT_ID, STATE.READY, 'DSCR preview status: ');
        dscrRendered = true;
        dscrReason = 'preview-unavailable-shown-as-placeholder';
      } else {
        dscrReason = 'target-element-not-found';
      }
    }

    if (!overviewRendered && !capexRendered && !revenueRendered && !opexRendered && !ebitdaRendered && !ocfRendered && !debtRendered && !taxRendered && !irrRendered && !dscrRendered) {
      return {
        rendered: false,
        reason: overviewReason,
        capexReason: capexReason,
        revenueReason: revenueReason,
        opexReason: opexReason,
        ebitdaReason: ebitdaReason,
        ocfReason: ocfReason,
        debtReason: debtReason,
        taxReason: taxReason,
        irrReason: irrReason,
        dscrReason: dscrReason
      };
    }

    return {
      rendered: overviewRendered || capexRendered || revenueRendered || opexRendered || ebitdaRendered || ocfRendered || debtRendered || taxRendered || irrRendered || dscrRendered,
      reason: overviewRendered ? 'ok' : overviewReason,
      capexRendered: capexRendered,
      capexReason: capexReason,
      revenueRendered: revenueRendered,
      revenueReason: revenueReason,
      opexRendered: opexRendered,
      opexReason: opexReason,
      ebitdaRendered: ebitdaRendered,
      ebitdaReason: ebitdaReason,
      ocfRendered: ocfRendered,
      ocfReason: ocfReason,
      debtRendered: debtRendered,
      debtReason: debtReason,
      taxRendered: taxRendered,
      taxReason: taxReason,
      irrRendered: irrRendered,
      irrReason: irrReason,
      dscrRendered: dscrRendered,
      dscrReason: dscrReason
    };
  }

  window.FcRuntimeRenderer = {
    render: render,
    // C2-PR11: explicit state-machine transitions for the request
    // lifecycle's caller (live-model.js) to drive.
    setUpdating: setUpdating,
    setUnavailable: setUnavailable,
    setFailed: setFailed,
    states: STATE,
    stateLabels: STATE_LABEL,
    statusValueElementId: STATUS_VALUE_ELEMENT_ID,
    capexPreviewValueElementId: CAPEX_PREVIEW_VALUE_ELEMENT_ID,
    revenuePreviewValueElementId: REVENUE_PREVIEW_VALUE_ELEMENT_ID,
    opexPreviewValueElementId: OPEX_PREVIEW_VALUE_ELEMENT_ID,
    ebitdaPreviewValueElementId: EBITDA_PREVIEW_VALUE_ELEMENT_ID,
    ocfPreviewValueElementId: OCF_PREVIEW_VALUE_ELEMENT_ID,
    debtPreviewValueElementId: DEBT_PREVIEW_VALUE_ELEMENT_ID
  };
})();
