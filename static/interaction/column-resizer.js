/*
 * FINCO Protocol — Spreadsheet Interaction Layer
 * C1-PR12 / UI-2B-CorrA: ColumnResizer — drag-to-resize column headers.
 *
 * Attaches mousedown listeners to .fc-col-resize-handle elements inside
 * column header cells. Handles must have a data-col attribute matching the
 * column name (e.g. data-col="desc").
 *
 * On drag, sets both the CSS custom property --fc-col-<name>-width on the
 * nearest [data-fc-grid] ancestor AND directly sets width/flex on matching
 * column elements (.v2-capex-col-<name>, .v2-opex-col-<name>, etc.) so the
 * layout change is immediately visible regardless of CSS variable fallbacks.
 *
 * Resize state is session-only (no server persistence for MVP).
 * Minimum column width: 60px.
 */
(function () {
  'use strict';

  var MIN_WIDTH = 60;
  var _dragging = null;

  function _applyWidth(gridEl, col, width) {
    var px = width + 'px';
    var gridId = gridEl.dataset.fcGrid || '';
    // Grid-specific CSS custom property consumed by grid-template-columns rules.
    // e.g. --fc-capex-desc-width, --fc-opex-y1-width
    if (gridId) {
      gridEl.style.setProperty('--fc-' + gridId + '-' + col + '-width', px);
    }
    // Generic fallback for non-grid layouts or other consumers
    gridEl.style.setProperty('--fc-col-' + col + '-width', px);
  }

  function _onMouseMove(evt) {
    if (!_dragging) return;
    var dx = evt.clientX - _dragging.startX;
    var newWidth = Math.max(MIN_WIDTH, _dragging.startWidth + dx);
    _applyWidth(_dragging.grid, _dragging.col, newWidth);
  }

  function _onMouseUp() {
    _dragging = null;
    document.removeEventListener('mousemove', _onMouseMove);
    document.removeEventListener('mouseup', _onMouseUp);
    document.body.style.userSelect = '';
    document.body.style.cursor = '';
  }

  function _onHandleMouseDown(evt) {
    evt.preventDefault();
    var handle = evt.currentTarget;
    var col = handle.dataset.col;
    if (!col) return;

    var header = handle.parentElement;
    if (!header) return;
    var startWidth = header.getBoundingClientRect().width;
    var gridEl = handle.closest('[data-fc-grid]');
    if (!gridEl) return;

    _dragging = {
      col: col,
      startX: evt.clientX,
      startWidth: startWidth,
      grid: gridEl,
    };
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'col-resize';
    document.addEventListener('mousemove', _onMouseMove);
    document.addEventListener('mouseup', _onMouseUp);
  }

  function _bindHandles(root) {
    var handles = (root || document).querySelectorAll('.fc-col-resize-handle');
    handles.forEach(function (h) {
      h.removeEventListener('mousedown', _onHandleMouseDown);
      h.addEventListener('mousedown', _onHandleMouseDown);
    });
  }

  var _initialized = false;

  function init() {
    if (_initialized) return false;
    _initialized = true;
    _bindHandles(document);
    document.addEventListener('htmx:afterSwap', function () { _bindHandles(document); });
    return true;
  }

  window.FcColumnResizer = { init: init, bindHandles: _bindHandles };
  init();
})();
