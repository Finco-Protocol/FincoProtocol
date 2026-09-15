/*
 * FINCO Protocol — Spreadsheet Interaction Layer
 * C1-PR2: ActiveCellManager (active-cell foundation only — no behaviour)
 *
 * Reference: docs/C1_INTERACTION_LAYER_DESIGN.md,
 *            docs/C1_PR1_IMPLEMENTATION_NOTE.md,
 *            docs/C1_PR2_IMPLEMENTATION_NOTE.md.
 *
 * Responsibility in this PR is limited to:
 *   - tracking exactly one active cell across the whole page
 *   - toggling a single CSS class to reflect that state
 *   - restoring (or safely clearing) the active cell after an htmx
 *     swap, via the fc:gridsScanned / fc:engineReady events from
 *     engine.js
 *   - setting the active cell on a plain single click
 *
 * This module does NOT:
 *   - handle keyboard input of any kind
 *   - implement selection, ranges, or multi-selection
 *   - implement clipboard, undo/redo, or fill-down
 *   - move focus or scroll position itself (it relies on the
 *     browser's default click behaviour only)
 *   - change double-click behaviour — it never calls preventDefault()
 *     or stopPropagation(), so any existing/future dblclick handling
 *     is completely unaffected
 *
 * FcGridRegistry (PR1) remains the single source of truth for which
 * cell is active per grid; this module only ever has at most one
 * grid/cell pair active at a time and keeps the registry and the DOM
 * class in sync with that.
 */
(function () {
  'use strict';

  var ACTIVE_CLASS = 'fc-active-cell';

  var _activeGridId = null;
  var _activeCell = null;

  function _dispatchChanged(gridId, cell) {
    document.dispatchEvent(new CustomEvent('fc:activeCellChanged', {
      detail: { gridId: gridId, cell: cell }
    }));
  }

  function setActiveCell(gridId, cell) {
    if (!gridId || !cell) return null;

    if (_activeCell && (_activeGridId !== gridId || _activeCell !== cell)) {
      _clearVisual();
      window.FcGridRegistry.clearActiveCell(_activeGridId);
    }

    _activeGridId = gridId;
    _activeCell = cell;
    window.FcGridRegistry.setActiveCell(gridId, cell);
    _applyVisual(cell);
    _dispatchChanged(gridId, cell);

    return cell;
  }

  function clearActiveCell() {
    if (!_activeCell) return;
    _clearVisual();
    window.FcGridRegistry.clearActiveCell(_activeGridId);
    _activeGridId = null;
    _activeCell = null;
    _dispatchChanged(null, null);
  }

  function getActiveCell() {
    if (!_activeCell) return null;
    return { gridId: _activeGridId, cell: _activeCell };
  }

  function _applyVisual(cell) {
    if (cell && cell.el && cell.el.classList) {
      cell.el.classList.add(ACTIVE_CLASS);
    }
  }

  function _clearVisual() {
    if (_activeCell && _activeCell.el && _activeCell.el.classList) {
      _activeCell.el.classList.remove(ACTIVE_CLASS);
    }
  }

  /**
   * Re-resolve the active cell against the freshly (re)built registry
   * state after a scan. FcGridRegistry.scan() already re-attaches the
   * active record (by address) onto the rebuilt grid when the address
   * still exists; here we just re-apply (or drop) the visual class to
   * match, since rebuilding replaces DOM element references.
   *
   * C1-Final-Hardening: this is the module's *only* reaction to a
   * scan/swap, and it is a pure, idempotent re-derivation from
   * FcGridRegistry — the single source of truth for "what is active
   * in grid X right now". It never makes its own independent
   * set/clear decision based on a separately-held pre-swap snapshot
   * (that authoritative decision belongs solely to
   * FcSwapLifecycle.reconcileAfterSwap(), which calls this function
   * explicitly, in a fixed order, after it has already updated the
   * registry via setActiveCell()/clearActiveCell()). Calling this
   * function any number of times, in any order relative to
   * FcSwapLifecycle, always converges to the same end state: it only
   * ever reads current registry state and re-applies the matching
   * visual class — it cannot itself introduce a duplicate restore,
   * flicker, or stale-state regression, because it has no
   * independent state of its own to race with.
   */
  function reconcileAfterScan(gridIds) {
    var grids = gridIds || [];
    if (!_activeGridId || !_activeCell) return;
    if (grids.indexOf(_activeGridId) === -1) return;

    var resolved = window.FcGridRegistry.getActiveCell(_activeGridId);
    if (resolved) {
      if (_activeCell !== resolved) {
        _activeCell = resolved;
      }
      _applyVisual(resolved);
    } else {
      _activeGridId = null;
      _activeCell = null;
    }
  }

  function _onGridsScanned(evt) {
    var grids = (evt && evt.detail && evt.detail.grids) || [];
    reconcileAfterScan(grids);
  }

  function _onCellClick(evt) {
    var cellEl = evt.target && evt.target.closest
      ? evt.target.closest('[data-fc-cell]')
      : null;
    if (!cellEl) return;

    var gridRoot = cellEl.closest('[data-fc-grid]');
    if (!gridRoot) return;

    var gridId = gridRoot.getAttribute('data-fc-grid');
    var grid = window.FcGridRegistry.getGrid(gridId);
    if (!grid) return;

    var addr = cellEl.getAttribute('data-fc-addr');
    var cell = addr ? window.FcGridRegistry.getAddr(gridId, addr) : null;
    if (!cell) return;

    setActiveCell(gridId, cell);
  }

  var _initialized = false;

  function init() {
    if (_initialized) return false;
    _initialized = true;

    document.addEventListener('click', _onCellClick);
    document.addEventListener('fc:gridsScanned', _onGridsScanned);
    document.addEventListener('fc:engineReady', _onGridsScanned);

    return true;
  }

  window.FcActiveCellManager = {
    init: init,
    setActiveCell: setActiveCell,
    clearActiveCell: clearActiveCell,
    getActiveCell: getActiveCell,
    reconcileAfterScan: reconcileAfterScan
  };

  init();
})();
