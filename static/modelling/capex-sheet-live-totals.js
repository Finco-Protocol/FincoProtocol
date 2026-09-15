/*
 * FINCO Protocol — CAPEX Sheet Live Totals + Excel-style Direct Typing
 * Product Gap PR1: CAPEX Real Excel Editing + Live Totals
 *
 * Reference: docs/PRODUCT_GAP_PR1_CAPEX_EXCEL_EDITING.md
 *
 * This module is CAPEX-sheet-specific and deliberately kept separate
 * from the generic C1 interaction layer (grid-registry / active-cell /
 * focus-manager / keyboard-router / cell-io) and from the C2 preview
 * pipeline (recalc-preview.js / live-model.js / runtime-renderer.js).
 * It does NOT modify any of those modules and does NOT add any new
 * `/model/preview` payload fields. It is pure, additive, in-sheet DOM
 * rendering plus one keyboard UX affordance (type-to-replace), both
 * scoped to the "capex" grid only.
 *
 * Two responsibilities:
 *
 *   1. Excel-style direct typing on the CAPEX grid only:
 *      - When the active cell (per FcActiveCellManager) is an
 *        editable CAPEX amount cell and is NOT already in "input edit
 *        mode" (i.e. DOM focus is on the [data-fc-cell] itself, not
 *        on a descendant <input> that the user clicked into), typing
 *        a digit / "." / "-" immediately opens the cell's <input>,
 *        REPLACES its existing value with the typed character (exact
 *        Excel behaviour: first keystroke replaces, never appends),
 *        and moves DOM focus into the input so subsequent keystrokes
 *        are handled natively by the <input> itself (this module does
 *        not double-handle keys once truly inside edit mode).
 *      - Backspace/Delete clears the cell's value and enters edit
 *        mode (does not silently no-op).
 *      - Enter / Shift+Enter / Tab / Shift+Tab while IN edit mode:
 *        commit the edited value (already live via cell-io's
 *        input/change dispatch from the in-progress edit) and move
 *        the active cell down/up/right/left exactly like the existing
 *        C1 FcKeyboardRouter does for un-edited navigation. Escape
 *        restores the pre-edit value and exits edit mode without
 *        committing.
 *      - Normal arrow-key navigation when NOT in edit mode is left
 *        completely alone (FcKeyboardRouter already owns that); this
 *        module only adds the "first keystroke starts editing"
 *        behaviour for the digit/./- /Backspace/Delete keys that
 *        FcKeyboardRouter does not handle at all today.
 *
 *   2. Live CAPEX subtotal/total rendering:
 *      - Listens for `input` events (live, per keystroke — not just on
 *        commit) on any editable CAPEX amount cell's <input>, and
 *        immediately recomputes + re-renders, purely in the DOM:
 *          - the owning category subtotal (e.g. "C.01 Subtotal")
 *          - Hard CAPEX Total (C.01–C.16)
 *          - Total CAPEX (C.01–C.18)
 *      - This is sheet-level DOM rendering only. It does not call
 *        `/model/preview`, does not touch recalc-preview.js's preview
 *        payload, and does not mark anything dirty for the C2 preview
 *        pipeline beyond what cell-io's existing input/change dispatch
 *        already does for FcLiveModel (unchanged, pre-existing
 *        behaviour).
 *
 * Total CAPEX rule (exact):
 *   Total CAPEX (live, in-sheet) = Hard CAPEX Total (sum of all
 *   currently-rendered C.01–C.16 editable amount cells' live values)
 *   + the CURRENT VALUE ALREADY DISPLAYED IN THE DOM for C.17
 *   (Financing Costs) and C.18 (Reserve Accounts), read from their
 *   existing read-only `data-fc-raw` cells (the backend-computed
 *   financing/reserve total cells already rendered server-side by
 *   sheet_capex.html). C.17/C.18 are NEVER recomputed, fabricated, or
 *   guessed client-side — they are read verbatim from the DOM exactly
 *   as the backend rendered them. If a C.17/C.18 row is not present in
 *   the DOM at all (defensive fallback only; the production template
 *   always renders both), that row's contribution is treated as 0 for
 *   the live total, and the live total is then equal to Hard CAPEX
 *   Total alone — i.e. it always sums exactly the values currently
 *   available/visible, never inventing a number for an absent row.
 *
 * Save/Run separation:
 *   This module never submits, fetches, or POSTs anything. It only
 *   reads/writes `textContent`/`value` on already-rendered DOM nodes.
 *   Save continues to depend solely on the existing `name=`-attributed
 *   <input> elements rendered by _line_item_grid.html (unchanged by
 *   this file). Run remains a separate, explicit, server-side action.
 *   No DB write of any kind occurs from typing or from this module.
 */
(function () {
  'use strict';

  var GRID_ID = 'capex';

  // ── Helpers ────────────────────────────────────────────────────────

  function _grid() {
    if (!window.FcGridRegistry || typeof window.FcGridRegistry.getGrid !== 'function') return null;
    return window.FcGridRegistry.getGrid(GRID_ID);
  }

  function _isCapexAmountCell(cell) {
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

  // Category code from a data-fc-addr like "capex!C.01.01.amount"
  // -> "C.01". Returns null if it can't be parsed.
  function _categoryOf(addr) {
    if (!addr || addr.indexOf('capex!') !== 0) return null;
    var rest = addr.slice('capex!'.length); // "C.01.01.amount"
    var parts = rest.split('.');
    if (parts.length < 2) return null;
    return parts[0] + '.' + parts[1]; // "C" + "01" -> "C.01"
  }

  function _setCellRawAndText(rowSelectorAttr, rowSelectorValue, value, formatted) {
    var tr = document.querySelector(
      '#capex-single-sheet tr[' + rowSelectorAttr + '="' + rowSelectorValue + '"]'
    );
    if (!tr) return;
    var td = tr.querySelector('[data-fc-cell]');
    if (!td) return;
    td.setAttribute('data-fc-raw', value);
    td.textContent = formatted;
  }

  // ── Live subtotal recomputation (DOM-only) ─────────────────────────

  function recomputeLiveTotals() {
    var grid = _grid();
    if (!grid || !grid.rows) return;

    // category code -> running sum
    var catTotals = {};
    var hardTotal = 0;

    grid.rows.forEach(function (row) {
      (row || []).forEach(function (cell) {
        if (!_isCapexAmountCell(cell)) return;
        var addr = cell.el.getAttribute('data-fc-addr');
        var cat = _categoryOf(addr);
        if (!cat) return;
        var raw = window.FcCellIO && window.FcCellIO.readValue
          ? window.FcCellIO.readValue(cell)
          : (cell.el.getAttribute('data-fc-raw') || '');
        var num = _parseNum(raw);
        catTotals[cat] = (catTotals[cat] || 0) + num;
        hardTotal += num;
      });
    });

    Object.keys(catTotals).forEach(function (cat) {
      var value = catTotals[cat];
      _setCellRawAndText('data-capex-row', 'cat-subtotal-' + cat, value, _formatAmount(value));
    });

    _setCellRawAndText('data-capex-row', 'hard-capex-total', hardTotal, _formatAmount(hardTotal));

    // C.17/C.18: read verbatim from the DOM (backend-computed,
    // read-only, never recomputed/fabricated here). Missing rows
    // contribute 0 — see the exact Total CAPEX rule documented at the
    // top of this file and in docs/PRODUCT_GAP_PR1_CAPEX_EXCEL_EDITING.md.
    var financingTotal = 0;
    var financingRows = document.querySelectorAll(
      '#capex-single-sheet tr.lig-row--data-financing [data-fc-cell][data-fc-raw]'
    );
    financingRows.forEach(function (td) {
      financingTotal += _parseNum(td.getAttribute('data-fc-raw'));
    });

    var grandTotal = hardTotal + financingTotal;
    _setCellRawAndText('data-capex-row', 'grand-total', grandTotal, _formatAmount(grandTotal));
  }

  // ── Excel-style direct typing ──────────────────────────────────────

  var _editState = null; // { cellEl, input, previousValue, wasEmpty }

  function _isEditModeActive() {
    var el = document.activeElement;
    return !!(_editState && el === _editState.input);
  }

  function _activeCapexCell() {
    var active = window.FcActiveCellManager && window.FcActiveCellManager.getActiveCell
      ? window.FcActiveCellManager.getActiveCell()
      : null;
    if (!active || active.gridId !== GRID_ID || !active.cell) return null;
    if (!_isCapexAmountCell(active.cell)) return null;
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
    // Case A: not yet editing — a CAPEX amount cell is active and has
    // DOM focus directly (not its <input>). Handle "start typing"
    // keys only; everything else (arrows, etc.) is left to
    // FcKeyboardRouter untouched.
    if (!_isEditModeActive()) {
      var cell = _activeCapexCell();
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

  window.FcCapexSheetLiveTotals = {
    init: init,
    recomputeLiveTotals: recomputeLiveTotals
  };

  init();
})();
