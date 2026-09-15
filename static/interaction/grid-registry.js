/*
 * FINCO Protocol — Spreadsheet Interaction Layer
 * C1-PR1: GridRegistry (foundation only — no behaviour)
 *
 * Reference: docs/C1_INTERACTION_LAYER_DESIGN.md, sections 2-4.
 *
 * This module ONLY discovers and indexes grid markup. It does not
 * move focus, does not handle keys, does not select, copy, paste,
 * undo, or recalculate anything. It is read-only with respect to
 * the DOM: it never adds/removes classes, attributes, or listeners
 * on the cells it indexes.
 *
 * Markup contract (per design doc §2):
 *   data-fc-grid="<gridId>"        grid root (e.g. a <table>)
 *   data-fc-row                    optional explicit row marker;
 *                                   falls back to the nearest <tr>
 *                                   ancestor when absent
 *   data-fc-cell                   marks a navigable cell (<td>/<th>)
 *   data-fc-addr="<address>"       unique cell address string
 *   data-fc-editable="true|false"  defaults to "false" when absent
 *   data-fc-kind="amount|label|select|date"
 *   data-fc-scroll-container       (C1-PR3, optional) marks the
 *                                   nearest scrollable ancestor of a
 *                                   grid, used only for scroll-position
 *                                   capture/restore in FcSwapLifecycle.
 *                                   Purely opt-in — grids without it
 *                                   simply have no scroll preservation.
 *
 * Rows that contain no data-fc-editable="true" cell (category band
 * rows, subtotal rows, total rows) are still indexed for row/col
 * navigation — every cell in them simply resolves as non-editable
 * unless explicitly marked otherwise.
 */
(function () {
  'use strict';

  // gridId -> { root, rows: [[cellRecord, ...], ...], cellsByAddr: {addr: cellRecord} }
  var _grids = {};

  function _isEditable(el) {
    return el.getAttribute('data-fc-editable') === 'true';
  }

  function _rowKeyFor(cellEl) {
    var explicit = cellEl.closest('[data-fc-row]');
    if (explicit) return explicit;
    var tr = cellEl.closest('tr');
    if (tr) return tr;
    // No row container found — the cell is its own row.
    return cellEl;
  }

  function _buildIndex(gridRoot) {
    var cellEls = gridRoot.querySelectorAll('[data-fc-cell]');
    var rowOrder = [];
    var rowMap = {}; // rowKeyEl -> row index

    var rows = [];
    var cellsByAddr = {};

    for (var i = 0; i < cellEls.length; i++) {
      var cellEl = cellEls[i];
      var rowKeyEl = _rowKeyFor(cellEl);

      var rowIndex = rowMap.hasOwnProperty(_keyId(rowKeyEl))
        ? rowMap[_keyId(rowKeyEl)]
        : -1;
      if (rowIndex === -1) {
        rowIndex = rows.length;
        rowMap[_keyId(rowKeyEl)] = rowIndex;
        rows.push([]);
        rowOrder.push(rowKeyEl);
      }

      var colIndex = rows[rowIndex].length;
      var addr = cellEl.getAttribute('data-fc-addr') || null;

      var record = {
        el: cellEl,
        addr: addr,
        row: rowIndex,
        col: colIndex,
        editable: _isEditable(cellEl),
        kind: cellEl.getAttribute('data-fc-kind') || null
      };

      rows[rowIndex].push(record);
      if (addr) cellsByAddr[addr] = record;
    }

    var container = gridRoot.closest('[data-fc-scroll-container]') || null;

    return { root: gridRoot, rows: rows, cellsByAddr: cellsByAddr, active: null, container: container };
  }

  // Cheap stable identity key for a DOM node, used only as a map key
  // during a single _buildIndex pass (not persisted).
  var _keySeq = 0;
  function _keyId(el) {
    if (!el.__fcRowKey) {
      _keySeq += 1;
      el.__fcRowKey = 'r' + _keySeq;
    }
    return el.__fcRowKey;
  }

  /**
   * Scan `root` (defaults to document) for [data-fc-grid] roots and
   * (re)build their index. Safe to call repeatedly — re-scanning a
   * grid id that already exists simply replaces its index, it does
   * not duplicate or accumulate state.
   */
  function scan(root) {
    var scope = root || document;
    var gridRoots = [];

    if (scope.nodeType === 1 && scope.matches && scope.matches('[data-fc-grid]')) {
      gridRoots.push(scope);
    }
    if (scope.querySelectorAll) {
      var found = scope.querySelectorAll('[data-fc-grid]');
      for (var i = 0; i < found.length; i++) gridRoots.push(found[i]);
    }

    var registered = [];
    for (var j = 0; j < gridRoots.length; j++) {
      var gridRoot = gridRoots[j];
      var gridId = gridRoot.getAttribute('data-fc-grid');
      if (!gridId) continue;

      var previousActiveAddr = (_grids[gridId] && _grids[gridId].active)
        ? _grids[gridId].active.addr
        : null;

      var rebuilt = _buildIndex(gridRoot);
      if (previousActiveAddr && rebuilt.cellsByAddr[previousActiveAddr]) {
        rebuilt.active = rebuilt.cellsByAddr[previousActiveAddr];
      }
      _grids[gridId] = rebuilt;
      registered.push(gridId);
    }
    return registered;
  }

  function scanAll() {
    return scan(document);
  }

  function getGrid(gridId) {
    return _grids[gridId] || null;
  }

  function getGridIds() {
    return Object.keys(_grids);
  }

  function getCell(gridId, row, col) {
    var grid = _grids[gridId];
    if (!grid || !grid.rows[row]) return null;
    return grid.rows[row][col] || null;
  }

  function getAddr(gridId, addr) {
    var grid = _grids[gridId];
    if (!grid) return null;
    return grid.cellsByAddr[addr] || null;
  }

  function neighbors(cell, direction) {
    if (!cell) return null;
    var grid = null;
    for (var gridId in _grids) {
      if (!_grids.hasOwnProperty(gridId)) continue;
      var candidate = _grids[gridId];
      if (candidate.rows[cell.row] && candidate.rows[cell.row][cell.col] === cell) {
        grid = candidate;
        break;
      }
    }
    if (!grid) return null;

    var targetRow = cell.row;
    var targetCol = cell.col;
    if (direction === 'up') targetRow -= 1;
    else if (direction === 'down') targetRow += 1;
    else if (direction === 'left') targetCol -= 1;
    else if (direction === 'right') targetCol += 1;
    else return null;

    if (targetRow < 0 || targetCol < 0) return null;
    if (!grid.rows[targetRow]) return null;
    return grid.rows[targetRow][targetCol] || null;
  }

  /**
   * Active-cell bookkeeping (C1-PR2). The registry only stores which
   * cell record is active per grid — it does not touch the DOM (no
   * classes, no focus) and does not infer neighbours. Visual state
   * and click handling live in FcActiveCellManager.
   */
  function setActiveCell(gridId, cell) {
    var grid = _grids[gridId];
    if (!grid) return null;
    grid.active = cell || null;
    return grid.active;
  }

  function clearActiveCell(gridId) {
    var grid = _grids[gridId];
    if (!grid) return;
    grid.active = null;
  }

  function getActiveCell(gridId) {
    var grid = _grids[gridId];
    return grid ? grid.active : null;
  }

  function _reset() {
    // Test-only helper: clears all registered grids.
    _grids = {};
  }

  window.FcGridRegistry = {
    scan: scan,
    scanAll: scanAll,
    getGrid: getGrid,
    getGridIds: getGridIds,
    getCell: getCell,
    getAddr: getAddr,
    neighbors: neighbors,
    setActiveCell: setActiveCell,
    clearActiveCell: clearActiveCell,
    getActiveCell: getActiveCell,
    _reset: _reset
  };
})();
