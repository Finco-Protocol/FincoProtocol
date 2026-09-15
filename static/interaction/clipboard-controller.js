/*
 * FINCO Protocol — Spreadsheet Interaction Layer
 * C1-PR7: ClipboardController (Excel-compatible TSV copy/paste
 * foundation only — no undo/redo, fill, formula editing, or
 * recalculation)
 *
 * Reference: docs/C1_INTERACTION_LAYER_DESIGN.md,
 *            docs/C1_PR1_IMPLEMENTATION_NOTE.md,
 *            docs/C1_PR2_IMPLEMENTATION_NOTE.md,
 *            docs/C1_PR3_IMPLEMENTATION_NOTE.md,
 *            docs/C1_PR4_IMPLEMENTATION_NOTE.md,
 *            docs/C1_PR5_IMPLEMENTATION_NOTE.md,
 *            docs/C1_PR6_IMPLEMENTATION_NOTE.md,
 *            docs/C1_PR7_IMPLEMENTATION_NOTE.md,
 *            docs/C1_PR8_IMPLEMENTATION_NOTE.md.
 *
 * C1-PR8 addendum: pasteText() now records one "paste" transaction
 * with FcUndoManager (if loaded) covering every cell it actually
 * wrote, plus the active-cell/selection state before and after, so a
 * multi-cell paste undoes/redoes as a single user action. This is the
 * only behavioural change made in PR8; all copy/parse/clip logic
 * below is unchanged from PR7. FcUndoManager is optional — paste
 * still works unchanged (no undo history) if it isn't loaded.
 *
 * Responsibility in this PR is limited to:
 *   - copying the current selection (FcSelectionManager) as
 *     Excel-compatible TSV (tab-separated columns, newline-separated
 *     rows) on Ctrl+C / Cmd+C
 *   - pasting TSV (from Excel, Google Sheets, LibreOffice, plain text,
 *     or a prior FINCO Protocol copy) from the active cell's origin on
 *     Ctrl+V / Cmd+V, clipping safely against grid bounds
 *   - updating the active cell (top-left of the pasted region) and
 *     selection (the full pasted region) after a paste, reusing the
 *     existing FcActiveCellManager/FcSelectionManager APIs
 *   - using the modern async Clipboard API when available, with a
 *     same-session in-memory fallback that never blocks on browser
 *     permission prompts
 *
 * This module does NOT:
 *   - implement the undo/redo stack itself (FcUndoManager, PR8, owns
 *     that) — it only records a "paste" transaction when one is
 *     available, and never applies undo/redo on its own
 *   - implement fill-down/fill-right/drag-fill/autofill
 *   - implement cut (Ctrl+X), delete-row behaviour, or any clipboard
 *     operation spanning more than one grid/project
 *   - parse or translate formulas, or trigger recalculation
 *   - hold a parallel notion of "what is selected" — every copy/paste
 *     reads FcSelectionManager.getSelection() and FcGridRegistry's
 *     live grid index; the only state this module owns is the
 *     clipboard payload itself (the in-memory fallback cache), which
 *     is exactly what a clipboard is for, not a selection/grid model
 */
(function () {
  'use strict';

  // In-memory fallback clipboard payload (TSV text or null). Used when
  // the async Clipboard API is unavailable or rejected (e.g. no user
  // permission yet) — this is what makes copy-then-paste within
  // FINCO Protocol itself work reliably regardless of browser permissions.
  var _lastCopiedText = null;

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
    return window.FcCellIO.readValue(cell);
  }

  function _setCellValue(cell, value) {
    window.FcCellIO.writeValue(cell, value);
  }

  /**
   * Resolve the current selection's rectangle bounds in grid-space,
   * using only FcSelectionManager's public anchor/active addresses
   * and FcGridRegistry's live cell index — no internal selection
   * state is read or duplicated.
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

  function _buildTsv(bounds) {
    var grid = window.FcGridRegistry.getGrid(bounds.gridId);
    if (!grid) return '';

    var lines = [];
    for (var r = bounds.minRow; r <= bounds.maxRow; r++) {
      var cols = [];
      for (var c = bounds.minCol; c <= bounds.maxCol; c++) {
        var cell = grid.rows[r] && grid.rows[r][c] ? grid.rows[r][c] : null;
        cols.push(_cellValue(cell));
      }
      lines.push(cols.join('\t'));
    }
    return lines.join('\n');
  }

  /**
   * Parse Excel/Sheets/LibreOffice/plain-text TSV into a 2D array of
   * strings. Handles \r\n, \r, and \n line endings, and drops a single
   * trailing empty row caused by a trailing newline (the common case
   * when copying a range out of a real spreadsheet).
   */
  function _parseTsv(text) {
    var normalized = String(text).replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    var lines = normalized.split('\n');
    if (lines.length > 1 && lines[lines.length - 1] === '') {
      lines.pop();
    }
    return lines.map(function (line) { return line.split('\t'); });
  }

  function copySelection() {
    var bounds = _selectionBounds();
    if (!bounds) return null;

    var tsv = _buildTsv(bounds);
    _lastCopiedText = tsv;

    if (window.navigator && window.navigator.clipboard && window.navigator.clipboard.writeText) {
      try {
        window.navigator.clipboard.writeText(tsv).catch(function () {
          // Permission denied or unavailable — the in-memory fallback
          // above already covers same-session paste; nothing else to do.
        });
      } catch (e) {
        // Synchronous throw (e.g. insecure context) — same fallback applies.
      }
    }

    return tsv;
  }

  function getLastCopiedText() {
    return _lastCopiedText;
  }

  /**
   * Apply parsed TSV rows/cols at the given grid's active-cell origin,
   * clipping safely against grid bounds, then update the active cell
   * (top-left of the pasted region) and selection (the full pasted
   * region, clipped) to match.
   */
  function pasteText(text) {
    if (!text) return false;

    var active = window.FcActiveCellManager && window.FcActiveCellManager.getActiveCell
      ? window.FcActiveCellManager.getActiveCell()
      : null;
    if (!active || !active.cell) return false;

    var gridId = active.gridId;
    var origin = active.cell;
    var grid = window.FcGridRegistry.getGrid(gridId);
    if (!grid) return false;

    var rows = _parseTsv(text);
    if (!rows.length || !rows[0].length) return false;

    var selectionBefore = window.FcSelectionManager && window.FcSelectionManager.getSelection
      ? window.FcSelectionManager.getSelection()
      : null;

    var changes = [];
    var lastCell = origin;
    for (var r = 0; r < rows.length; r++) {
      var targetRow = grid.rows[origin.row + r];
      if (!targetRow) break; // clip safely: no more rows in the grid

      for (var c = 0; c < rows[r].length; c++) {
        var targetCell = targetRow[origin.col + c];
        if (!targetCell) break; // clip safely: no more columns in this row

        if (targetCell.editable && targetCell.addr) {
          changes.push({ addr: targetCell.addr, before: _cellValue(targetCell), after: rows[r][c] });
        }
        _setCellValue(targetCell, rows[r][c]);
        lastCell = targetCell;
      }
    }

    window.FcActiveCellManager.setActiveCell(gridId, origin);

    if (window.FcSelectionManager) {
      window.FcSelectionManager.selectSingle(gridId, lastCell);
      window.FcSelectionManager.extendTo(gridId, origin);
    }

    if (window.FcFocusManager && window.FcFocusManager.syncFocus) {
      window.FcFocusManager.syncFocus();
    }

    if (changes.length && window.FcUndoManager && window.FcUndoManager.recordTransaction) {
      window.FcUndoManager.recordTransaction({
        type: 'paste',
        gridId: gridId,
        changes: changes,
        activeBefore: { gridId: gridId, addr: origin.addr },
        activeAfter: { gridId: gridId, addr: origin.addr },
        selectionBefore: selectionBefore,
        selectionAfter: { gridId: gridId, anchorAddr: lastCell.addr, activeAddr: origin.addr }
      });
    }

    return true;
  }

  /**
   * Ctrl+V / Cmd+V entry point: prefer the live system clipboard via
   * the async Clipboard API; fall back to the in-memory
   * same-session payload when it is unavailable, rejected (e.g. no
   * permission yet), or empty. Never throws and never blocks normal
   * browser permission flows — the read is best-effort only.
   */
  function _pasteFromSystemClipboard() {
    if (window.navigator && window.navigator.clipboard && window.navigator.clipboard.readText) {
      try {
        window.navigator.clipboard.readText().then(
          function (text) {
            pasteText(text || _lastCopiedText);
          },
          function () {
            pasteText(_lastCopiedText);
          }
        );
        return;
      } catch (e) {
        // Synchronous throw (e.g. insecure context) — fall through to cache.
      }
    }
    pasteText(_lastCopiedText);
  }

  function _isCopyChord(evt) {
    return (evt.ctrlKey || evt.metaKey) && !evt.shiftKey && !evt.altKey &&
      (evt.key === 'c' || evt.key === 'C');
  }

  function _isPasteChord(evt) {
    return (evt.ctrlKey || evt.metaKey) && !evt.shiftKey && !evt.altKey &&
      (evt.key === 'v' || evt.key === 'V');
  }

  function _onKeyDown(evt) {
    if (!_isCopyChord(evt) && !_isPasteChord(evt)) return;
    if (!_isGridCellFocused()) return;
    if (!_currentActive()) return;

    if (_isCopyChord(evt)) {
      evt.preventDefault();
      copySelection();
    } else {
      evt.preventDefault();
      _pasteFromSystemClipboard();
    }
  }

  var _initialized = false;

  function init() {
    if (_initialized) return false;
    _initialized = true;

    document.addEventListener('keydown', _onKeyDown);

    return true;
  }

  window.FcClipboardController = {
    init: init,
    copySelection: copySelection,
    pasteText: pasteText,
    getLastCopiedText: getLastCopiedText,
    applyCellValue: _setCellValue
  };

  init();
})();
