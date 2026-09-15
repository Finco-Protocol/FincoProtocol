/*
 * FINCO Protocol — Spreadsheet Interaction Layer
 * C1-PR9 / UI-2B-CorrA: UndoManager — undo/redo for user edits.
 *
 * Records a stack of {addr, gridId, oldValue, newValue} entries.
 * Ctrl+Z undoes the most recent edit; Ctrl+Y / Ctrl+Shift+Z redoes it.
 *
 * Entry is pushed when a V2 field save completes successfully
 * (htmx:afterRequest with success status on a field form).
 *
 * Cell/editor contract: uses _resolveEditor() which supports both the
 * standard V2 wrapper cell (data-fc-cell wraps native INPUT) and the
 * older pattern where an INPUT itself carries data-fc-cell.
 *
 * Stale-CAS handling: if the server returns 409 on an undo/redo,
 * the stack pointer is restored to its pre-operation position and the
 * input value is reverted — the undo is cleanly cancelled.
 *
 * Programmatic edits (paste, fill, type-to-edit): those modules set
 * inp._fcUndoOldValue before modifying inp.value; _onAfterRequest then
 * records the entry on successful save, same as user-typed edits.
 */
(function () {
  'use strict';

  var MAX_STACK = 100;
  var _stack = [];
  var _stackIdx = -1;

  function _registry() { return window.FcGridRegistry || null; }

  function _isNativeControl(el) {
    if (!el) return false;
    var t = el.tagName;
    return t === 'INPUT' || t === 'SELECT' || t === 'TEXTAREA' ||
           t === 'BUTTON' || t === 'A' || el.isContentEditable;
  }

  /* Returns the native editor for a cell element. Handles both:
     - wrapper span (data-fc-cell) containing INPUT/SELECT/TEXTAREA
     - INPUT/SELECT/TEXTAREA that IS the data-fc-cell (legacy) */
  function _resolveEditor(cellEl) {
    if (!cellEl) return null;
    var tag = cellEl.tagName;
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return cellEl;
    return cellEl.querySelector('input:not([type="hidden"]),select,textarea') || null;
  }

  /* ── record ─────────────────────────────────────────────────────── */

  function record(gridId, addr, oldValue, newValue) {
    if (oldValue === newValue) return;
    if (_stackIdx < _stack.length - 1) {
      _stack = _stack.slice(0, _stackIdx + 1);
    }
    _stack.push({ gridId: gridId, addr: addr, old: oldValue, new: newValue });
    if (_stack.length > MAX_STACK) _stack.shift();
    _stackIdx = _stack.length - 1;
  }

  /* ── apply ──────────────────────────────────────────────────────── */

  var _applyingUndo = false;

  function _apply(entry, targetValue, onSuccess, onFail) {
    var reg = _registry();
    if (!reg) { onFail && onFail(); return; }
    var cr = reg.getAddr(entry.gridId, entry.addr);
    if (!cr) { onFail && onFail(); return; }
    var inp = _resolveEditor(cr.el);
    if (!inp) { onFail && onFail(); return; }

    var prevVal = inp.value;
    inp.value = targetValue;
    inp.dispatchEvent(new Event('input', { bubbles: true }));
    var form = inp.closest && inp.closest('form');
    if (!form) { onFail && onFail(); return; }

    _applyingUndo = true;
    var handler = function (evt) {
      if (evt.detail.elt !== form) return;
      document.removeEventListener('htmx:afterRequest', handler);
      _applyingUndo = false;

      if (!evt.detail.successful) {
        var status = evt.detail.xhr && evt.detail.xhr.status;
        console.warn('[FcUndo] Server rejected undo (status ' + status + ') — restoring local value');
        // Attempt to restore the input's pre-undo value
        var cr2 = reg.getAddr(entry.gridId, entry.addr);
        var inp2 = cr2 ? _resolveEditor(cr2.el) : null;
        if (inp2) inp2.value = prevVal;
        onFail && onFail();
      } else {
        inp._fcUndoOldValue = undefined;
        onSuccess && onSuccess();
      }
    };
    document.addEventListener('htmx:afterRequest', handler);
    try { form.requestSubmit(); } catch (e) { form.submit(); }
  }

  /* ── undo / redo ────────────────────────────────────────────────── */

  function undo() {
    if (_stackIdx < 0) return;
    var entry = _stack[_stackIdx];
    _stackIdx--;
    _apply(entry, entry.old, null, function () { _stackIdx++; });
  }

  function redo() {
    if (_stackIdx >= _stack.length - 1) return;
    _stackIdx++;
    var entry = _stack[_stackIdx];
    _apply(entry, entry.new, null, function () { _stackIdx--; });
  }

  /* ── auto-record on field saves ─────────────────────────────────── */

  function _onBeforeInput(evt) {
    var inp = evt.target;
    if (!inp || !inp.closest) return;
    var cellEl = inp.closest('[data-fc-cell]');
    if (!cellEl) return;
    // Capture baseline only once per transaction (first keystroke).
    // If _fcUndoOldValue is already set the user is mid-edit — do NOT
    // overwrite it, or the committed baseline would be lost.
    if (inp._fcUndoOldValue === undefined) {
      inp._fcUndoOldValue = inp.value;
    }
  }

  function _onAfterRequest(evt) {
    if (_applyingUndo) return;
    var form = evt.detail && evt.detail.elt;
    if (!form || form.tagName !== 'FORM') return;
    if (!evt.detail.successful) return;

    // Find all editable inputs in the form; resolve their [data-fc-cell] wrapper
    var inputs = form.querySelectorAll('input:not([type="hidden"]),select,textarea');
    inputs.forEach(function (inp) {
      var cellEl = inp.closest('[data-fc-cell]');
      if (!cellEl) return;
      var addr = cellEl.dataset.fcAddr;
      var gridEl = cellEl.closest('[data-fc-grid]');
      var gridId = gridEl ? gridEl.dataset.fcGrid : null;
      if (!addr || !gridId) return;
      var oldVal = inp._fcUndoOldValue;
      var newVal = inp.value;
      if (oldVal !== undefined && oldVal !== newVal) {
        record(gridId, addr, oldVal, newVal);
      }
      inp._fcUndoOldValue = undefined;
    });
  }

  /* ── keyboard handler ────────────────────────────────────────────── */

  function _onKeyDown(evt) {
    if (!evt.ctrlKey && !evt.metaKey) return;
    var ae = document.activeElement;
    if (_isNativeControl(ae)) return;

    if (evt.key === 'z' || evt.key === 'Z') {
      evt.preventDefault();
      if (evt.shiftKey) { redo(); } else { undo(); }
    } else if (evt.key === 'y' || evt.key === 'Y') {
      evt.preventDefault();
      redo();
    }
  }

  var _initialized = false;

  function init() {
    if (_initialized) return false;
    _initialized = true;
    document.addEventListener('keydown', _onKeyDown);
    document.addEventListener('beforeinput', _onBeforeInput, true);
    document.addEventListener('htmx:afterRequest', _onAfterRequest);
    return true;
  }

  window.FcUndoManager = {
    init: init, record: record, undo: undo, redo: redo,
    // Test-only: expose stack state for browser assertions
    get _stackIdx() { return _stackIdx; },
    _reset: function () { _stack = []; _stackIdx = -1; }
  };
  init();
})();
