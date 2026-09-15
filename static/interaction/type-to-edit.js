/*
 * FINCO Protocol — Spreadsheet Interaction Layer
 * C1-PR10: TypeToEdit — enter edit mode by typing from a selected editable cell.
 *
 * When an editable spreadsheet cell (data-fc-editable="true") is the active
 * cell and the cell wrapper itself owns DOM focus (not a native control inside
 * it), a printable character keystroke:
 *   - clears the existing input value
 *   - moves DOM focus into the input element
 *   - inserts the typed character as the starting value
 *
 * Escape while the input has focus:
 *   - restores the original value (data-original-value, per V2 contract)
 *   - returns focus to the cell wrapper
 *
 * Enter while the input has focus:
 *   - delegates to existing v2FieldKeydown behavior (submits form)
 *
 * Does NOT intercept input when a native control already owns focus
 * (guard: document.activeElement is INPUT/SELECT/TEXTAREA/etc.).
 */
(function () {
  'use strict';

  function _activeMgr() { return window.FcActiveCellManager || null; }

  function _isNativeControl(el) {
    if (!el) return false;
    var t = el.tagName;
    return t === 'INPUT' || t === 'SELECT' || t === 'TEXTAREA' ||
           t === 'BUTTON' || t === 'A' || el.isContentEditable;
  }

  function _isPrintable(key) {
    return key.length === 1 && !key.match(/[\x00-\x1F\x7F]/);
  }

  function _resolveEditor(cellEl) {
    if (!cellEl) return null;
    var tag = cellEl.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA') return cellEl;
    return cellEl.querySelector('input:not([type="hidden"]),textarea') || null;
  }

  function _onKeyDown(evt) {
    // Skip modifier-combos (Ctrl+X etc handled by other managers)
    if (evt.ctrlKey || evt.metaKey || evt.altKey) return;

    var ae = document.activeElement;
    // Guard: don't intercept when native control owns focus
    if (_isNativeControl(ae)) return;

    if (!_isPrintable(evt.key)) return;

    var amgr = _activeMgr();
    var active = amgr && amgr.getActiveCell();
    if (!active || !active.cell) return;

    var cellEl = active.cell.el;
    if (!cellEl) return;
    if (cellEl.dataset.fcEditable !== 'true') return;

    var inp = _resolveEditor(cellEl);
    if (!inp) return;

    // Save original value for Escape and for FcUndoManager recording
    if (inp.dataset.originalValue === undefined || inp.dataset.originalValue === '') {
      inp.dataset.originalValue = inp.value;
    }
    inp._fcUndoOldValue = inp.dataset.originalValue;

    // Replace value with the typed character and move focus
    inp.value = evt.key;
    inp.dispatchEvent(new Event('input', { bubbles: true }));
    inp.focus();
    // Move caret to end
    try { inp.setSelectionRange(inp.value.length, inp.value.length); } catch (e) {}
    evt.preventDefault();
  }

  var _initialized = false;

  function init() {
    if (_initialized) return false;
    _initialized = true;
    document.addEventListener('keydown', _onKeyDown);
    return true;
  }

  window.FcTypeToEdit = { init: init };
  init();
})();
