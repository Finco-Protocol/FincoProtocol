/*
 * FINCO Protocol — Spreadsheet Interaction Layer
 * C1-PR8 / UI-2B-CorrA: FillManager — directional fill for editable cells.
 *
 * Ctrl+D: Fill Down  — for each column in the selection, copy the source
 *   (topmost) cell value downward through the selected rows in that column.
 * Ctrl+R: Fill Right — for each row in the selection, copy the source
 *   (leftmost) cell value rightward through the selected columns in that row.
 *
 * Single-cell active (no multi-selection): fills one neighbor in direction.
 *
 * Persistence: CAS-safe serial queue (same as ClipboardManager) — each cell
 * awaits the HTMX response before the next is submitted, preventing
 * stale-content_hash rejections from concurrent form submissions.
 *
 * Cell/editor contract: _resolveEditor() supports wrapper-span cells and
 * legacy naked-INPUT cells.
 */
(function () {
  'use strict';

  function _registry() { return window.FcGridRegistry || null; }
  function _selMgr() { return window.FcSelectionManager || null; }
  function _activeMgr() { return window.FcActiveCellManager || null; }

  function _isNativeControl(el) {
    if (!el) return false;
    var t = el.tagName;
    return t === 'INPUT' || t === 'SELECT' || t === 'TEXTAREA' ||
           t === 'BUTTON' || t === 'A' || el.isContentEditable;
  }

  function _resolveEditor(cellEl) {
    if (!cellEl) return null;
    var tag = cellEl.tagName;
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return cellEl;
    return cellEl.querySelector('input:not([type="hidden"]),select,textarea') || null;
  }

  function _getInputValue(cellEl) {
    var inp = _resolveEditor(cellEl);
    return inp ? inp.value : null;
  }

  /* ── CAS-safe serial persistence queue ─────────────────────────── */

  function _persistOne(gridId, addr, value, onDone, onError) {
    var reg = _registry();
    var cr = reg && reg.getAddr(gridId, addr);
    if (!cr || !cr.el || cr.el.dataset.fcEditable === 'false') {
      onDone(); return;
    }
    var inp = _resolveEditor(cr.el);
    if (!inp) { onDone(); return; }
    var form = inp.closest && inp.closest('form');
    if (!form) { onDone(); return; }

    inp._fcUndoOldValue = inp.value;
    inp.value = value;
    inp.dispatchEvent(new Event('input', { bubbles: true }));

    var handler = function (evt) {
      if (evt.detail.elt !== form) return;
      document.removeEventListener('htmx:afterRequest', handler);
      if (evt.detail.successful) {
        setTimeout(onDone, 80);
      } else {
        var status = evt.detail.xhr && evt.detail.xhr.status;
        onError(addr, status);
      }
    };
    document.addEventListener('htmx:afterRequest', handler);
    try { form.requestSubmit(); } catch (e) { form.submit(); }
  }

  function _runQueue(items, gridId) {
    if (!items.length) return;
    var item = items[0];
    var rest = items.slice(1);
    _persistOne(gridId, item.addr, item.value,
      function () { _runQueue(rest, gridId); },
      function (failAddr, status) {
        console.warn('[FcFill] Fill stopped at', failAddr, '— server status', status);
      }
    );
  }

  /* ── fill logic ─────────────────────────────────────────────────── */

  function _fill(direction) {
    var amgr = _activeMgr();
    var active = amgr && amgr.getActiveCell();
    if (!active || !active.cell) return;

    var reg = _registry();
    if (!reg) return;
    var gridId = active.gridId;
    var sel = _selMgr() && _selMgr().getSelection();

    var queue = [];

    if (sel && sel.gridId === gridId && sel.addresses && sel.addresses.length > 1) {
      // Multi-cell selection: directional fill within the rectangle
      var grid = reg.getGrid(gridId);
      if (!grid) return;

      // Determine the bounding box of the selection
      var selCells = sel.addresses.map(function (addr) {
        return reg.getAddr(gridId, addr);
      }).filter(Boolean);
      if (!selCells.length) return;

      var minRow = selCells[0].row, maxRow = selCells[0].row;
      var minCol = selCells[0].col, maxCol = selCells[0].col;
      selCells.forEach(function (cr) {
        if (cr.row < minRow) minRow = cr.row;
        if (cr.row > maxRow) maxRow = cr.row;
        if (cr.col < minCol) minCol = cr.col;
        if (cr.col > maxCol) maxCol = cr.col;
      });

      if (direction === 'down') {
        // For each column in the selection, copy the top-row value downward
        for (var c = minCol; c <= maxCol; c++) {
          var sourceCr = grid.rows[minRow] && grid.rows[minRow][c];
          if (!sourceCr) continue;
          var sourceVal = _getInputValue(sourceCr.el);
          if (sourceVal === null) continue;
          for (var r = minRow + 1; r <= maxRow; r++) {
            var targetCr = grid.rows[r] && grid.rows[r][c];
            if (!targetCr || !targetCr.addr) continue;
            if (targetCr.el && targetCr.el.dataset.fcEditable === 'false') continue;
            queue.push({ addr: targetCr.addr, value: sourceVal });
          }
        }
      } else {
        // direction === 'right'
        // For each row in the selection, copy the leftmost value rightward
        for (var r2 = minRow; r2 <= maxRow; r2++) {
          var sourceCr2 = grid.rows[r2] && grid.rows[r2][minCol];
          if (!sourceCr2) continue;
          var sourceVal2 = _getInputValue(sourceCr2.el);
          if (sourceVal2 === null) continue;
          for (var c2 = minCol + 1; c2 <= maxCol; c2++) {
            var targetCr2 = grid.rows[r2] && grid.rows[r2][c2];
            if (!targetCr2 || !targetCr2.addr) continue;
            if (targetCr2.el && targetCr2.el.dataset.fcEditable === 'false') continue;
            queue.push({ addr: targetCr2.addr, value: sourceVal2 });
          }
        }
      }
    } else {
      // No multi-selection — fill one neighbor
      var neighbor = reg.neighbors && reg.neighbors(
        active.cell,
        direction === 'down' ? 'down' : 'right'
      );
      if (!neighbor || !neighbor.addr) return;
      if (neighbor.el && neighbor.el.dataset.fcEditable === 'false') return;
      var val = _getInputValue(active.cell.el);
      if (val !== null) queue.push({ addr: neighbor.addr, value: val });
    }

    _runQueue(queue, gridId);
  }

  function _onKeyDown(evt) {
    if (!evt.ctrlKey && !evt.metaKey) return;
    var ae = document.activeElement;
    if (_isNativeControl(ae)) return;

    if (evt.key === 'd' || evt.key === 'D') {
      evt.preventDefault();
      _fill('down');
    } else if (evt.key === 'r' || evt.key === 'R') {
      evt.preventDefault();
      _fill('right');
    }
  }

  var _initialized = false;

  function init() {
    if (_initialized) return false;
    _initialized = true;
    document.addEventListener('keydown', _onKeyDown);
    return true;
  }

  window.FcFillManager = { init: init };
  init();
})();
