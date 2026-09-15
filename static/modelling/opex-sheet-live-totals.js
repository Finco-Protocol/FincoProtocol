/*
 * FINCO Protocol — OPEX Sheet Live Totals + Excel-style Direct Typing
 * Product Gap PR2/PR3/PR4: OPEX Real Excel Editing + Live Operating Totals
 *
 * Reference: docs/PRODUCT_GAP_PR2_OPEX_EXCEL_EDITING.md
 * Mirrors: static/modelling/capex-sheet-live-totals.js (Product Gap PR1)
 *
 * This module is OPEX-sheet-specific and deliberately kept separate
 * from the generic C1 interaction layer (grid-registry / active-cell /
 * focus-manager / keyboard-router / cell-io) and from the C2 preview
 * pipeline (recalc-preview.js / live-model.js / runtime-renderer.js).
 * It does NOT modify any of those modules and does NOT add any new
 * `/model/preview` payload fields. It is pure, additive, in-sheet DOM
 * rendering plus one keyboard UX affordance (type-to-replace), both
 * scoped to the "opex" grid only.
 *
 * Two responsibilities (identical UX contract to CAPEX PR1, adapted to
 * the OPEX grid's actual editable surface — see the note below on the
 * one structural difference from CAPEX):
 *
 *   1. Excel-style direct typing on the OPEX grid only:
 *      - When the active cell (per FcActiveCellManager) is an editable
 *        OPEX Budget cell and is NOT already in "input edit mode" (DOM
 *        focus is on the [data-fc-cell] itself, not on a descendant
 *        <input> the user clicked into), typing a digit / "." / "-"
 *        immediately opens the cell's <input>, REPLACES its existing
 *        value with the typed character (Excel: first keystroke
 *        replaces, never appends), and moves DOM focus into the input.
 *      - Backspace/Delete clears the cell's value and enters edit mode.
 *      - Enter / Shift+Enter / Tab / Shift+Tab while IN edit mode:
 *        commit the edited value and move the active cell down/up/
 *        right/left exactly like the existing C1 FcKeyboardRouter does
 *        for un-edited navigation. Escape restores the pre-edit value
 *        and exits edit mode without committing.
 *      - Normal arrow-key navigation when NOT in edit mode is left
 *        completely alone (FcKeyboardRouter already owns that).
 *
 *   2. Live OPEX subtotal/total rendering:
 *      - Listens for `input` events (live, per keystroke) on any
 *        editable OPEX Budget <input>, and immediately recomputes +
 *        re-renders, purely in the DOM:
 *          - the owning category subtotal (Y1 column only — see rule
 *            below for why)
 *          - Operating Subtotal (sum of non-contingency category
 *            subtotals, Y1)
 *          - Total OPEX (Y1)
 *      - This is sheet-level DOM rendering only. It does not call
 *        `/model/preview`, does not touch recalc-preview.js's preview
 *        payload, and does not mark anything dirty for the C2 preview
 *        pipeline beyond what cell-io's existing input/change dispatch
 *        already does for FcLiveModel (unchanged, pre-existing
 *        behaviour).
 *
 * Structural difference from CAPEX (why only the Y1 column is live):
 *   Unlike the CAPEX grid (one editable amount cell per row), the OPEX
 *   grid has ONE editable cell per child row (the Y1 "Budget" cell,
 *   `data-fc-addr="opex!<code>.budget"`) and a separate, always
 *   read-only set of Y1..Yn "year" cells per row that the backend
 *   derives from the budget via inflation/active-flags (see
 *   `_build_opex_detail_items` in app/ui/project_context.py). Only the
 *   Budget (Y1) column can honestly be recomputed client-side from the
 *   live, possibly-mid-edit Budget values — recomputing Y2..Yn would
 *   require reproducing the backend's inflation/active-flag formula in
 *   JS, which is exactly the kind of "fabricate a number" the spec
 *   forbids. So this module's live totals are Y1-column only: Category
 *   Subtotal (Y1), Operating Subtotal (Y1), and Total OPEX (Y1). The
 *   Y2..Yn year columns, and the "Total OPEX Y{n}" summary card, are
 *   left exactly as the backend rendered them (frozen), unchanged by
 *   this module.
 *
 * Total OPEX (Y1) rule (exact):
 *   Operating Subtotal (live) = sum of the live (possibly mid-edit,
 *   unsaved) values of every editable OPEX Budget cell across the
 *   whole "opex" grid (i.e. every non-contingency child line on a user
 *   project — contingency-category lines are never
 *   `data-fc-editable="true"`, so they are structurally excluded
 *   without special-casing, exactly like CAPEX's C.17/C.18 exclusion
 *   from Hard CAPEX Total).
 *
 *   Total OPEX (Y1, live) = Operating Subtotal (live, as computed
 *   above) + the value CURRENTLY DISPLAYED IN THE DOM for each
 *   contingency category's Y1 subtotal cell (read verbatim from its
 *   existing read-only `data-fc-raw` attribute, identified by
 *   `[data-opex-row^="cat-subtotal-"][data-opex-contingency="true"]`).
 *   Contingency category subtotals are NEVER recomputed, estimated, or
 *   fabricated client-side — they stay exactly as the backend rendered
 *   them (`contingency_pct × sum(non-contingency Y1 totals)`,
 *   computed server-side), mirroring CAPEX's C.17/C.18 rule precisely.
 *   If, defensively, no contingency category subtotal row is present
 *   in the DOM at all (does not happen in the production template when
 *   a contingency category exists — purely a defensive fallback), that
 *   row's contribution is treated as exactly `0`.
 *
 * Save/Run separation:
 *   This module never submits, fetches, or POSTs anything. It only
 *   reads/writes `textContent`/`value` on already-rendered DOM nodes.
 *   The OPEX Budget <input> elements carry no `name=` attribute (per
 *   C2-PR17), so Save's `hx-include="#main-form"` cannot and does not
 *   submit them — Save's behaviour, route, and persisted data are
 *   completely unchanged by this module. Run remains a separate,
 *   explicit, server-side action, untouched.
 */
(function () {
  'use strict';

  var GRID_ID = 'opex';

  // ── Helpers ────────────────────────────────────────────────────────

  function _grid() {
    if (!window.FcGridRegistry || typeof window.FcGridRegistry.getGrid !== 'function') return null;
    return window.FcGridRegistry.getGrid(GRID_ID);
  }

  function _isOpexBudgetCell(cell) {
    return !!(cell && cell.kind === 'amount' && cell.editable);
  }

  function _inputOf(cellEl) {
    return cellEl && cellEl.querySelector ? cellEl.querySelector('input.fc-input-native') : null;
  }

  function _parseNum(raw) {
    var n = parseFloat(raw);
    return isNaN(n) ? 0 : n;
  }

  function _formatAmount(n) {
    return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  // Category code from a data-opex-cat attribute on the Budget cell
  // (set directly server-side — no address parsing needed, unlike
  // CAPEX's "capex!C.01.01.amount" -> "C.01" derivation).
  function _categoryOf(cellEl) {
    return cellEl.getAttribute('data-opex-cat') || null;
  }

  function _setCellRawAndText(opexRowValue, value, formatted) {
    var td = document.querySelector(
      '[data-fc-grid="opex"] [data-opex-row="' + opexRowValue + '"]'
    );
    if (!td) return;
    td.setAttribute('data-fc-raw', value);
    td.textContent = formatted;
  }

  // ── Live subtotal recomputation (DOM-only, Y1 column only) ─────────

  function recomputeLiveTotals() {
    var grid = _grid();
    if (!grid || !grid.rows) return;

    // category code -> running sum (Y1 Budget values only)
    var catTotals = {};
    var operatingSubtotal = 0;

    grid.rows.forEach(function (row) {
      (row || []).forEach(function (cell) {
        if (!_isOpexBudgetCell(cell)) return;
        var cat = _categoryOf(cell.el);
        if (!cat) return;
        var raw = window.FcCellIO && window.FcCellIO.readValue
          ? window.FcCellIO.readValue(cell)
          : (cell.el.getAttribute('data-fc-raw') || '');
        var num = _parseNum(raw);
        catTotals[cat] = (catTotals[cat] || 0) + num;
        operatingSubtotal += num;
      });
    });

    Object.keys(catTotals).forEach(function (cat) {
      var value = catTotals[cat];
      _setCellRawAndText('cat-subtotal-' + cat, value, _formatAmount(value));
    });

    _setCellRawAndText('operating-subtotal', operatingSubtotal, _formatAmount(operatingSubtotal));

    // Contingency category subtotal(s): read verbatim from the DOM
    // (backend-computed, read-only, never recomputed/fabricated here).
    // Missing rows contribute 0 — see the exact Total OPEX rule
    // documented at the top of this file and in
    // docs/PRODUCT_GAP_PR2_OPEX_EXCEL_EDITING.md.
    var contingencyTotal = 0;
    var contingencyRows = document.querySelectorAll(
      '[data-fc-grid="opex"] [data-opex-row^="cat-subtotal-"][data-opex-contingency="true"]'
    );
    contingencyRows.forEach(function (td) {
      contingencyTotal += _parseNum(td.getAttribute('data-fc-raw'));
    });

    var grandTotal = operatingSubtotal + contingencyTotal;
    _setCellRawAndText('grand-total', grandTotal, _formatAmount(grandTotal));
  }

  // ── Excel-style direct typing ──────────────────────────────────────

  var _editState = null; // { cellEl, input, previousValue }

  function _isEditModeActive() {
    var el = document.activeElement;
    return !!(_editState && el === _editState.input);
  }

  function _activeOpexCell() {
    var active = window.FcActiveCellManager && window.FcActiveCellManager.getActiveCell
      ? window.FcActiveCellManager.getActiveCell()
      : null;
    if (!active || active.gridId !== GRID_ID || !active.cell) return null;
    if (!_isOpexBudgetCell(active.cell)) return null;
    // Only act if DOM focus is genuinely on the cell itself (not
    // already inside its <input> — that case is "already editing"
    // and must be left to the native input).
    var el = document.activeElement;
    if (el !== active.cell.el) return null;
    return active.cell;
  }

  function _beginEdit(cell, initialValue) {
    var input = _inputOf(cell.el);
    if (!input) return null;
    var previousValue = input.value;
    input.value = initialValue;
    _editState = { cellEl: cell.el, input: input, previousValue: previousValue };
    input.focus();
    // Caret at end of the (newly typed) value.
    try {
      var len = input.value.length;
      input.setSelectionRange(len, len);
    } catch (e) {
      // setSelectionRange unsupported for this input type in this
      // browser — non-fatal, focus alone is enough for typing to work.
    }
    input.dispatchEvent(new Event('input', { bubbles: true }));
    recomputeLiveTotals();
    return _editState;
  }

  function _endEdit(commit) {
    if (!_editState) return;
    var input = _editState.input;
    if (!commit) {
      input.value = _editState.previousValue;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
      recomputeLiveTotals();
    } else {
      // Ensure a final 'change' fires so FcLiveModel's existing
      // focusin/change dirty-tracking sees the committed value (mirrors
      // native blur behaviour; cell-io/live-model are untouched).
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }
    var cellEl = _editState.cellEl;
    _editState = null;
    if (cellEl) cellEl.focus({ preventScroll: true });
  }

  function _moveActive(direction) {
    var current = window.FcActiveCellManager && window.FcActiveCellManager.getActiveCell
      ? window.FcActiveCellManager.getActiveCell()
      : null;
    if (!current || !current.cell || !window.FcGridRegistry) return;
    var target = window.FcGridRegistry.neighbors(current.cell, direction);
    if (!target) return;
    window.FcActiveCellManager.setActiveCell(current.gridId, target);
    if (window.FcFocusManager && window.FcFocusManager.syncFocus) {
      window.FcFocusManager.syncFocus();
    }
  }

  var TYPE_START_RE = /^[0-9.\-]$/;

  function _onKeyDown(evt) {
    // Case A: not yet editing — an OPEX Budget cell is active and has
    // DOM focus directly (not its <input>). Handle "start typing" keys
    // only; everything else (arrows, etc.) is left to
    // FcKeyboardRouter untouched.
    if (!_isEditModeActive()) {
      var cell = _activeOpexCell();
      if (!cell) return;

      if (TYPE_START_RE.test(evt.key)) {
        evt.preventDefault();
        _beginEdit(cell, evt.key);
        return;
      }
      if (evt.key === 'Backspace' || evt.key === 'Delete') {
        evt.preventDefault();
        _beginEdit(cell, '');
        return;
      }
      return;
    }

    // Case B: genuinely in edit mode (focus is on the <input> itself).
    // Only intercept the commit/cancel keys; every other keystroke is
    // handled natively by the <input> (never double-handled).
    switch (evt.key) {
      case 'Enter':
        evt.preventDefault();
        _endEdit(true);
        _moveActive(evt.shiftKey ? 'up' : 'down');
        break;
      case 'Tab':
        evt.preventDefault();
        _endEdit(true);
        _moveActive(evt.shiftKey ? 'left' : 'right');
        break;
      case 'Escape':
        evt.preventDefault();
        _endEdit(false);
        break;
      default:
        // Let the native <input> handle it (typing, arrow-within-
        // text, Home/End-within-text, etc.).
        break;
    }
  }

  function _onInput(evt) {
    var el = evt.target;
    if (!el || !el.matches || !el.matches('input.fc-input-native')) return;
    var cellEl = el.closest('[data-fc-cell]');
    if (!cellEl) return;
    var gridEl = cellEl.closest('[data-fc-grid="' + GRID_ID + '"]');
    if (!gridEl) return;
    recomputeLiveTotals();
  }

  function _onFocusOut(evt) {
    // If the user clicks/tabs away from an in-progress edit input by
    // means other than our own Enter/Tab/Escape handling above (e.g.
    // a mouse click elsewhere), treat it as a commit — mirrors native
    // <input> blur-commits-value semantics and keeps _editState from
    // going stale.
    if (_editState && evt.target === _editState.input) {
      _editState = null;
    }
  }

  var _initialized = false;

  function init() {
    if (_initialized) return false;
    _initialized = true;

    document.addEventListener('keydown', _onKeyDown);
    document.addEventListener('input', _onInput);
    document.addEventListener('focusout', _onFocusOut);
    document.addEventListener('fc:gridsScanned', recomputeLiveTotals);
    document.addEventListener('fc:engineReady', recomputeLiveTotals);

    return true;
  }

  window.FcOpexSheetLiveTotals = {
    init: init,
    recomputeLiveTotals: recomputeLiveTotals
  };

  init();
})();
