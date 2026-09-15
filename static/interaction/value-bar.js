/*
 * FINCO Protocol — Spreadsheet Interaction Layer
 * C1-PR11: ValueBar — formula/address bar for active cell.
 *
 * Displays:
 *   - cell address in #fc-value-bar-addr
 *   - current value / input text in #fc-value-bar-value (read-only preview)
 *
 * Updates on every active-cell change (click, keyboard navigation, HTMX swap).
 * Does NOT create client-side financial formula authority — read-only display only.
 * Does NOT intercept input in the bar (the bar is a display element, not an editor).
 */
(function () {
  'use strict';

  function _activeMgr() { return window.FcActiveCellManager || null; }

  var _barAddr = null;
  var _barValue = null;

  function _getEl(id) {
    if (!_barAddr) {
      _barAddr = document.getElementById('fc-value-bar-addr');
      _barValue = document.getElementById('fc-value-bar-value');
    }
    return id === 'addr' ? _barAddr : _barValue;
  }

  function _cellDisplayValue(cellEl) {
    if (!cellEl) return '';
    var inp = cellEl.querySelector && cellEl.querySelector('input:not([type="hidden"]),select,textarea');
    if (inp) return inp.value;
    var vspan = cellEl.querySelector && cellEl.querySelector('.v2-field-value');
    if (vspan) {
      var emptyEl = vspan.querySelector('.v2-field-empty');
      if (emptyEl) return '';
      return vspan.textContent.trim();
    }
    return cellEl.textContent.trim();
  }

  function _sync() {
    var addrEl = document.getElementById('fc-value-bar-addr');
    var valEl = document.getElementById('fc-value-bar-value');
    if (!addrEl || !valEl) return;

    var amgr = _activeMgr();
    var active = amgr && amgr.getActiveCell();
    if (!active || !active.cell) {
      addrEl.textContent = '';
      valEl.textContent = '';
      return;
    }
    var addr = active.cell.addr || '';
    addrEl.textContent = addr;
    valEl.textContent = _cellDisplayValue(active.cell.el);
  }

  var _initialized = false;

  function init() {
    if (_initialized) return false;
    _initialized = true;
    document.addEventListener('click', _sync);
    document.addEventListener('fc:gridsScanned', _sync);
    document.addEventListener('fc:engineReady', _sync);
    document.addEventListener('fc:activeCellChanged', _sync);
    document.addEventListener('input', _sync);
    return true;
  }

  window.FcValueBar = { init: init, sync: _sync };
  init();
})();
