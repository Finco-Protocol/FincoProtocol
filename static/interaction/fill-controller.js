/*
 * FINCO Protocol — Spreadsheet Interaction Layer
 * C1-PR9: FillController (fill-down / fill-right foundation only —
 * no drag-fill handle, autofill series, formula editing, relative
 * references, formatting/validation copy, or recalculation)
 *
 * Reference: docs/C1_INTERACTION_LAYER_DESIGN.md,
 *            docs/C1_PR1_IMPLEMENTATION_NOTE.md through
 *            docs/C1_PR8_IMPLEMENTATION_NOTE.md,
 *            docs/C1_PR9_IMPLEMENTATION_NOTE.md.
 *
 * Responsibility in this PR is limited to:
 *   - Fill Down (Ctrl+D / Cmd+D): takes the current selection's top
 *     row as the source, fills it downward into every editable cell
 *     within the selection
 *   - Fill Right (Ctrl+R / Cmd+R): takes the current selection's
 *     leftmost column as the source, fills it rightward into every
 *     editable cell within the selection
 *   - skipping non-editable cells safely, never writing to them
 *   - clipping safely against the selection/grid bounds (never throws)
 *   - recording the whole fill as one undo transaction via
 *     FcUndoManager.recordTransaction(), reusing
 *     FcClipboardController.applyCellValue() for every write — no
 *     duplicated cell-write logic
 *   - leaving the selection, active cell, and focus exactly as they
 *     were before the fill
 *
 * This module does NOT:
 *   - implement a drag-fill handle or autofill series
 *   - parse or translate formulas, or implement relative references
 *   - copy formatting or validation rules — values only
 *   - implement cut, delete-row behaviour, or recalculation
 *   - persist anything or integrate with Save/Run
 *   - hold a parallel notion of "what is selected" or "what is
 *     active" — every fill reads FcSelectionManager.getSelection()
 *     and FcGridRegistry's live grid index fresh; this module owns no
 *     state of its own
 */
(function () {
  'use strict';

  function _isGridCellFocused() {
    var el = document.activeElement;
    return !!(el && el.closest && el.closest('[data-fc-cell]'));
  }

  function _currentActive() {
    var active = window.FcActiveCellManager && window.FcActiveCellManager.getActiveCell
      ? window.FcActiveCellManager.getActiveCell()
      : null;
    if (!active || !active.cell) return null;
    var el = document.activeElement;
    if (el !== active.cell.el && !(active.cell.el.contains && active.cell.el.contains(el))) return null;
    return active;
  }

  function _cellValue(cell) {
    if (window.FcCellIO && window.FcCellIO.readValue) {
      return window.FcCellIO.readValue(cell);
    }
    return '';
  }

  function _applyCellValue(cell, value) {
    if (window.FcCellIO && window.FcCellIO.writeValue) {
      window.FcCellIO.writeValue(cell, value);
    }
  }

  /**
   * Resolve the current selection's rectangle bounds in grid-space,
   * mirroring FcClipboardController's _selectionBounds — no internal
   * selection state is read or duplicated.
   */
  function _selectionBounds() {
    var sel = window.FcSelectionManager && window.FcSelectionManager.getSelection
      ? window.FcSelectionManager.getSelection()
      : null;
    if (!sel) return null;

    var anchor = window.FcGridRegistry.getAddr(sel.gridId, sel.anchorAddr);
    var active = window.FcGridRegistry.getAddr(sel.gridId, sel.activeAddr);
    if (!anchor || !active) return null;

    return {
      gridId: sel.gridId,
      minRow: Math.min(anchor.row, active.row),
      maxRow: Math.max(anchor.row, active.row),
      minCol: Math.min(anchor.col, active.col),
      maxCol: Math.max(anchor.col, active.col)
    };
  }

  function _isMultiCell(bounds) {
    return bounds.minRow !== bounds.maxRow || bounds.minCol !== bounds.maxCol;
  }

  function _recordFill(type, gridId, changes, snapshot) {
    if (!changes.length) return;
    if (!(window.FcUndoManager && window.FcUndoManager.recordTransaction)) return;

    window.FcUndoManager.recordTransaction({
      type: type,
      gridId: gridId,
      changes: changes,
      activeBefore: snapshot.active,
      activeAfter: snapshot.active,
      selectionBefore: snapshot.selection,
      selectionAfter: snapshot.selection
    });
  }

  function _snapshotState(gridId) {
    var active = window.FcActiveCellManager && window.FcActiveCellManager.getActiveCell
      ? window.FcActiveCellManager.getActiveCell()
      : null;
    var activeSnapshot = active && active.cell && active.cell.addr
      ? { gridId: gridId, addr: active.cell.addr }
      : null;

    var sel = window.FcSelectionManager && window.FcSelectionManager.getSelection
      ? window.FcSelectionManager.getSelection()
      : null;
    var selectionSnapshot = sel
      ? { gridId: sel.gridId, anchorAddr: sel.anchorAddr, activeAddr: sel.activeAddr }
      : null;

    return { active: activeSnapshot, selection: selectionSnapshot };
  }

  /**
   * Fills `targetRow`/`targetCol` within the selection's bounds from
   * a source row/column, writing only editable cells, skipping
   * everything else safely. Returns the list of {addr, before, after}
   * changes actually written.
   */
  function _fillDown(grid, bounds) {
    var changes = [];
    for (var c = bounds.minCol; c <= bounds.maxCol; c++) {
      var sourceRow = grid.rows[bounds.minRow];
      var sourceCell = sourceRow ? sourceRow[c] : null;
      if (!sourceCell) continue;
      var value = _cellValue(sourceCell);

      for (var r = bounds.minRow + 1; r <= bounds.maxRow; r++) {
        var targetRow = grid.rows[r];
        var targetCell = targetRow ? targetRow[c] : null;
        if (!targetCell) continue; // clip safely: no such row/col
        if (!targetCell.editable || !targetCell.addr) continue; // skip non-editable

        var before = _cellValue(targetCell);
        if (before === value) continue;
        changes.push({ addr: targetCell.addr, before: before, after: value });
        _applyCellValue(targetCell, value);
      }
    }
    return changes;
  }

  function _fillRight(grid, bounds) {
    var changes = [];
    for (var r = bounds.minRow; r <= bounds.maxRow; r++) {
      var sourceRow = grid.rows[r];
      var sourceCell = sourceRow ? sourceRow[bounds.minCol] : null;
      if (!sourceCell) continue;
      var value = _cellValue(sourceCell);

      for (var c = bounds.minCol + 1; c <= bounds.maxCol; c++) {
        var targetRow = grid.rows[r];
        var targetCell = targetRow ? targetRow[c] : null;
        if (!targetCell) continue; // clip safely: no such row/col
        if (!targetCell.editable || !targetCell.addr) continue; // skip non-editable

        var before = _cellValue(targetCell);
        if (before === value) continue;
        changes.push({ addr: targetCell.addr, before: before, after: value });
        _applyCellValue(targetCell, value);
      }
    }
    return changes;
  }

  function _runFill(type, fillFn) {
    var bounds = _selectionBounds();
    if (!bounds) return false; // no/invalid selection
    if (!_isMultiCell(bounds)) return false; // single-cell selection: no-op

    var grid = window.FcGridRegistry.getGrid(bounds.gridId);
    if (!grid) return false;

    var snapshot = _snapshotState(bounds.gridId);
    var changes = fillFn(grid, bounds);
    if (!changes.length) return false; // nothing editable/changed: no-op

    _recordFill(type, bounds.gridId, changes, snapshot);

    if (window.FcFocusManager && window.FcFocusManager.syncFocus) {
      window.FcFocusManager.syncFocus();
    }

    return true;
  }

  function fillDown() {
    return _runFill('fill-down', _fillDown);
  }

  function fillRight() {
    return _runFill('fill-right', _fillRight);
  }

  function _isFillDownChord(evt) {
    return (evt.ctrlKey || evt.metaKey) && !evt.shiftKey && !evt.altKey &&
      (evt.key === 'd' || evt.key === 'D');
  }

  function _isFillRightChord(evt) {
    return (evt.ctrlKey || evt.metaKey) && !evt.shiftKey && !evt.altKey &&
      (evt.key === 'r' || evt.key === 'R');
  }

  function _onKeyDown(evt) {
    if (!_isFillDownChord(evt) && !_isFillRightChord(evt)) return;
    if (!_isGridCellFocused()) return;
    if (!_currentActive()) return;

    if (_isFillDownChord(evt)) {
      evt.preventDefault();
      fillDown();
    } else {
      evt.preventDefault();
      fillRight();
    }
  }

  var _initialized = false;

  function init() {
    if (_initialized) return false;
    _initialized = true;

    document.addEventListener('keydown', _onKeyDown);

    return true;
  }

  window.FcFillController = {
    init: init,
    fillDown: fillDown,
    fillRight: fillRight
  };

  init();
})();
