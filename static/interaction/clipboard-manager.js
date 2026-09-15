/*
 * FINCO Protocol — Spreadsheet Interaction Layer
 * C1-PR7 / UI-2B-CorrA: ClipboardManager — TSV copy/paste for selected ranges.
 *
 * Copy: Ctrl+C writes rectangular TSV to the system clipboard.
 * Paste: Ctrl+V parses TSV and persists cells via a CAS-safe serial queue:
 *   each cell mutation awaits the HTMX response (and DOM swap) before the
 *   next cell is re-resolved and submitted, preventing stale-content_hash
 *   rejections that would occur with concurrent form submissions.
 *
 * Cell/editor contract: _resolveEditor() supports both wrapper-span cells
 * (data-fc-cell on a span containing an INPUT) and legacy naked-INPUT cells.
 *
 * Programmatic edits record undo entries: each target input's
 * _fcUndoOldValue is set before modification; FcUndoManager picks it up
 * on successful save.
 */
(function () {
  'use strict';

  function _selMgr() { return window.FcSelectionManager || null; }
  function _registry() { return window.FcGridRegistry || null; }

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

  function _cellValue(cellEl) {
    var inp = _resolveEditor(cellEl);
    if (inp) return inp.value;
    var val = cellEl.querySelector && cellEl.querySelector('.v2-field-value,.v2-field-empty');
    return val ? val.textContent.trim() : (cellEl.textContent || '').trim();
  }

  /* ── copy ─────────────────────────────────────────────────────── */

  function _copy() {
    var sel = _selMgr() && _selMgr().getSelection();
    if (!sel || !sel.addresses || !sel.addresses.length) return false;

    var reg = _registry();
    var values = sel.addresses.map(function (addr) {
      var cr = reg && reg.getAddr(sel.gridId, addr);
      return cr ? _cellValue(cr.el) : '';
    });

    var rows = [];
    var currentRow = [];
    var prevRow = null;
    sel.addresses.forEach(function (addr, i) {
      var cr = reg && reg.getAddr(sel.gridId, addr);
      var rowIdx = cr ? cr.row : i;
      if (prevRow !== null && rowIdx !== prevRow) {
        rows.push(currentRow.join('\t'));
        currentRow = [];
      }
      currentRow.push(values[i]);
      prevRow = rowIdx;
    });
    if (currentRow.length) rows.push(currentRow.join('\t'));
    var tsv = rows.join('\n');

    navigator.clipboard && navigator.clipboard.writeText(tsv).catch(function () {});
    return true;
  }

  /* ── CAS-safe serial persistence queue ───────────────────────── */

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

    // Record current value for undo (picked up by FcUndoManager on save)
    inp._fcUndoOldValue = inp.value;
    inp.value = value;
    inp.dispatchEvent(new Event('input', { bubbles: true }));

    var handler = function (evt) {
      if (evt.detail.elt !== form) return;
      document.removeEventListener('htmx:afterRequest', handler);
      if (evt.detail.successful) {
        // Wait for HTMX swap to settle before next step
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
        console.warn('[FcClipboard] Paste stopped at', failAddr, '— server status', status);
      }
    );
  }

  /* ── paste ────────────────────────────────────────────────────── */

  function _paste(text) {
    var sel = _selMgr() && _selMgr().getSelection();
    if (!sel) return;

    var lines = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
    // Strip trailing empty line from trailing newline
    if (lines.length > 1 && lines[lines.length - 1] === '') lines.pop();

    var reg = _registry();
    var grid = reg && reg.getGrid(sel.gridId);
    if (!grid) return;

    var startCr = reg.getAddr(sel.gridId, sel.activeAddr || sel.anchorAddr);
    if (!startCr) return;

    var startRow = startCr.row;
    var startCol = startCr.col;
    var queue = [];

    lines.forEach(function (line, rowOffset) {
      var tokens = line.split('\t');
      tokens.forEach(function (token, colOffset) {
        var targetCr = reg.getCell(sel.gridId, startRow + rowOffset, startCol + colOffset);
        if (!targetCr || !targetCr.addr) return;
        if (targetCr.el && targetCr.el.dataset.fcEditable === 'false') return;
        queue.push({ addr: targetCr.addr, value: token });
      });
    });

    _runQueue(queue, sel.gridId);
  }

  /* ── keyboard handler ─────────────────────────────────────────── */

  function _onKeyDown(evt) {
    if (!evt.ctrlKey && !evt.metaKey) return;
    var ae = document.activeElement;
    if (_isNativeControl(ae)) return;

    if (evt.key === 'c' || evt.key === 'C') {
      if (_copy()) evt.preventDefault();
    } else if (evt.key === 'v' || evt.key === 'V') {
      evt.preventDefault();
      navigator.clipboard && navigator.clipboard.readText().then(_paste).catch(function () {});
    }
  }

  var _initialized = false;

  function init() {
    if (_initialized) return false;
    _initialized = true;
    document.addEventListener('keydown', _onKeyDown);
    return true;
  }

  window.FcClipboardManager = { init: init };
  init();
})();
