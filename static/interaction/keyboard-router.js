/*
 * FINCO Protocol — Spreadsheet Interaction Layer
 * C1-PR5: KeyboardRouter (keyboard navigation foundation only — no
 * selection, clipboard, undo, fill, formula mode, or recalculation)
 *
 * Reference: docs/C1_INTERACTION_LAYER_DESIGN.md,
 *            docs/C1_PR1_IMPLEMENTATION_NOTE.md,
 *            docs/C1_PR2_IMPLEMENTATION_NOTE.md,
 *            docs/C1_PR3_IMPLEMENTATION_NOTE.md,
 *            docs/C1_PR4_IMPLEMENTATION_NOTE.md,
 *            docs/C1_PR5_IMPLEMENTATION_NOTE.md,
 *            docs/C1_PR6_IMPLEMENTATION_NOTE.md.
 *
 * C1-PR6 addendum: after moving the active cell, this module also
 * tells FcSelectionManager (if loaded) to either extend the
 * selection range (Shift+Arrow) or collapse it to the new active
 * cell (every other move) — see the bottom of _onKeyDown(). This is
 * the only change made in PR6; all movement/guard logic above is
 * unchanged from PR5.
 *
 * Responsibility in this PR is limited to:
 *   - moving the active cell with ArrowUp/Down/Left/Right, Enter,
 *     Shift+Enter, Tab, Shift+Tab, Home, End, and Ctrl+Arrow
 *   - doing so ONLY when DOM focus is currently on a registered grid
 *     cell ([data-fc-cell]) that matches FcActiveCellManager's
 *     current active cell — any other focus target (a real <input>,
 *     <select>, <textarea>, <button>, <a>, a modal, or simply no
 *     active cell at all) is left completely untouched
 *   - reusing FcGridRegistry.neighbors() / FcActiveCellManager /
 *     FcFocusManager exactly as they already exist — this module
 *     holds no parallel state of its own; on every keydown it reads
 *     the live active cell and grid index, so it automatically keeps
 *     working (or safely no-ops) across htmx swaps handled by
 *     FcSwapLifecycle, with no extra wiring
 *
 * This module does NOT:
 *   - implement selection, ranges, Shift+Arrow extension, or
 *     multi-cell selection
 *   - implement clipboard, copy/paste, undo/redo, or fill-down/drag
 *     fill
 *   - implement a context menu, formula editing, or recalculation
 *   - change mouse click/dblclick behaviour, or editable-input typing
 *     behaviour — those are never touched because this module ignores
 *     all keydowns unless the focused element is itself a registered
 *     grid cell
 */
(function () {
  'use strict';

  var NAV_KEYS = {
    ArrowRight: 1, ArrowLeft: 1, ArrowDown: 1, ArrowUp: 1,
    Enter: 1, Tab: 1, Home: 1, End: 1
  };

  // C1-PR6: keys for which Shift means "extend the selection range"
  // rather than "move and collapse" — everything else (Enter/Tab's
  // own Shift-for-direction meaning, Home/End) always collapses.
  var ARROW_KEYS = {
    ArrowRight: 1, ArrowLeft: 1, ArrowDown: 1, ArrowUp: 1
  };

  function _isGridCellFocused() {
    var el = document.activeElement;
    return !!(el && el.closest && el.closest('[data-fc-cell]'));
  }

  function _currentActive() {
    var active = window.FcActiveCellManager && window.FcActiveCellManager.getActiveCell
      ? window.FcActiveCellManager.getActiveCell()
      : null;
    if (!active || !active.cell) return null;
    // Conservative: only act if the registry's notion of "active"
    // still matches what actually has DOM focus right now.
    var el = document.activeElement;
    if (el !== active.cell.el && !(active.cell.el.contains && active.cell.el.contains(el))) return null;
    return active;
  }

  function _edge(cell, direction) {
    var current = cell;
    var next = window.FcGridRegistry.neighbors(current, direction);
    while (next) {
      current = next;
      next = window.FcGridRegistry.neighbors(current, direction);
    }
    return current;
  }

  function _rowCell(grid, rowIndex, colIndex) {
    var row = grid.rows[rowIndex];
    if (!row || !row.length) return null;
    if (colIndex < 0 || colIndex >= row.length) return null;
    return row[colIndex];
  }

  function _resolveTarget(evt, grid, cell) {
    switch (evt.key) {
      case 'ArrowRight':
        return evt.ctrlKey ? _edge(cell, 'right') : window.FcGridRegistry.neighbors(cell, 'right');
      case 'ArrowLeft':
        return evt.ctrlKey ? _edge(cell, 'left') : window.FcGridRegistry.neighbors(cell, 'left');
      case 'ArrowDown':
        return evt.ctrlKey ? _edge(cell, 'down') : window.FcGridRegistry.neighbors(cell, 'down');
      case 'ArrowUp':
        return evt.ctrlKey ? _edge(cell, 'up') : window.FcGridRegistry.neighbors(cell, 'up');
      case 'Enter':
        return evt.shiftKey
          ? window.FcGridRegistry.neighbors(cell, 'up')
          : window.FcGridRegistry.neighbors(cell, 'down');
      case 'Tab':
        return evt.shiftKey
          ? window.FcGridRegistry.neighbors(cell, 'left')
          : window.FcGridRegistry.neighbors(cell, 'right');
      case 'Home':
        return _rowCell(grid, cell.row, 0);
      case 'End':
        return _rowCell(grid, cell.row, (grid.rows[cell.row] || []).length - 1);
      default:
        return null;
    }
  }

  function _onKeyDown(evt) {
    if (!NAV_KEYS.hasOwnProperty(evt.key)) return;
    if (!_isGridCellFocused()) return;

    var current = _currentActive();
    if (!current) return;

    // UI-2A safety: if a native interactive control inside the cell
    // owns focus (e.g. a V2 <input> or <select> in a field row), do
    // NOT intercept — let the control handle its own keyboard
    // semantics (cursor movement, Home/End in text, option selection).
    // Only intercept when the [data-fc-cell] element itself is focused.
    var ae = document.activeElement;
    if (ae && ae !== current.cell.el) {
      var tag = ae.tagName;
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' ||
          tag === 'BUTTON' || tag === 'A' || ae.isContentEditable) {
        return;
      }
    }

    var grid = window.FcGridRegistry.getGrid(current.gridId);
    if (!grid) return;

    // We own this key while focus is on a registered grid cell — stop
    // it here (e.g. Tab escaping the grid, or the page scrolling on
    // arrow keys) whether or not a target cell is found.
    evt.preventDefault();

    var target = _resolveTarget(evt, grid, current.cell);
    if (!target || target === current.cell) return;

    window.FcActiveCellManager.setActiveCell(current.gridId, target);

    // C1-PR6: Shift+Arrow extends the selection range (anchor stays
    // fixed); every other move collapses the selection to the new
    // active cell, mirroring how the active cell itself always
    // collapses to exactly one cell. FcSelectionManager is optional —
    // this module still works (active cell + focus only) if it isn't
    // loaded.
    if (ARROW_KEYS.hasOwnProperty(evt.key) && evt.shiftKey &&
        window.FcSelectionManager && window.FcSelectionManager.extendTo) {
      window.FcSelectionManager.extendTo(current.gridId, target);
    } else if (window.FcSelectionManager && window.FcSelectionManager.collapseToActive) {
      window.FcSelectionManager.collapseToActive();
    }

    if (window.FcFocusManager && window.FcFocusManager.syncFocus) {
      window.FcFocusManager.syncFocus();
    }
  }

  var _initialized = false;

  function init() {
    if (_initialized) return false;
    _initialized = true;

    document.addEventListener('keydown', _onKeyDown);

    return true;
  }

  window.FcKeyboardRouter = {
    init: init
  };

  init();
})();
