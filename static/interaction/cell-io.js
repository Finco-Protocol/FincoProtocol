/*
 * FINCO Protocol — Spreadsheet Interaction Layer
 * Shared cell read/write IO, extracted from FcClipboardController so
 * Clipboard/Undo/Fill share one cell value implementation instead of
 * each duplicating it.
 *
 * Reference: docs/C1_INTERACTION_LAYER_DESIGN.md,
 *            docs/CAPEX_C1_MIGRATION_NOTE.md.
 *
 * readValue(cell) precedence:
 *   1. data-fc-raw on the cell element, if present (the raw
 *      unformatted numeric value behind a formatted display, e.g. a
 *      CAPEX amount cell showing "12,345.67" but backed by a raw
 *      float)
 *   2. a descendant input/select/textarea's value
 *   3. the cell element's trimmed textContent
 *
 * writeValue(cell, value) writes to a descendant input/select/
 * textarea when present (else textContent), dispatches `input` and
 * `change` events exactly as the prior FcClipboardController write
 * path did, and updates data-fc-raw when the cell already carries one
 * (so a written raw value keeps round-tripping through copy/fill/
 * paste instead of silently reverting to a stale formatted string).
 *
 * This module does NOT recalculate, validate, or format values — it
 * only moves the value already chosen by the caller (Clipboard/Undo/
 * Fill) into/out of the DOM.
 */
(function () {
  'use strict';

  function readValue(cell) {
    if (!cell || !cell.el) return '';
    if (cell.el.hasAttribute && cell.el.hasAttribute('data-fc-raw')) {
      return cell.el.getAttribute('data-fc-raw');
    }
    var input = cell.el.querySelector('input, select, textarea');
    if (input) return input.value != null ? String(input.value) : '';
    return cell.el.textContent != null ? cell.el.textContent.trim() : '';
  }

  function writeValue(cell, value) {
    if (!cell || !cell.el || !cell.editable) return;
    var input = cell.el.querySelector('input, select, textarea');
    if (input) {
      input.value = value;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    } else {
      cell.el.textContent = value;
    }
    if (cell.el.hasAttribute && cell.el.hasAttribute('data-fc-raw')) {
      cell.el.setAttribute('data-fc-raw', value);
    }
  }

  window.FcCellIO = {
    readValue: readValue,
    writeValue: writeValue
  };
})();
