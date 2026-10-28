// WS-2 / M-007, M-010 — keyboard-first grid behaviour, as pure functions.
//
// Spreadsheet conventions for the CAPEX/OPEX amount grids:
//   Enter / ArrowDown   next editable row, same column      Shift+Enter / ArrowUp   previous
//   Tab / Shift+Tab     next / previous editable cell        (never trapped: past the last cell the browser moves on)
//   Escape              cancel the staged edit of the focused cell
//   Paste (TSV)         multi-row / multi-column, validated as ONE all-or-nothing block
//
// Nothing here saves or calculates: it maps keys and pasted text to cell positions and to
// staged text.  Values keep their canonical meaning and display unit; the server stays the
// validation authority at Save.

import { formatDecimal, parseDecimal, type DecimalSeparator } from "./decimal";

export interface GridModel {
  /** Column ids in visual order. */
  columns: readonly string[];
  /** Visible rows in visual order.  Hidden/filtered rows are simply absent. */
  rows: ReadonlyArray<{ id: string; editable: Readonly<Record<string, boolean>> }>;
}

export interface CellPos { row: number; col: number }

const isEditable = (grid: GridModel, row: number, col: number) =>
  grid.rows[row]?.editable[grid.columns[col]] === true;

/** Subset of KeyboardEvent the navigation needs (so it can be tested without a DOM). */
export interface KeyLike {
  key: string; shiftKey: boolean; altKey: boolean; ctrlKey: boolean; metaKey: boolean;
  isComposing?: boolean; keyCode?: number;
  /** `tagName` / `type` of the focused element. */
  target?: { tagName?: string; type?: string; isContentEditable?: boolean } | null;
}

/**
 * True when the grid must NOT intercept the key: IME composition, modified shortcuts, and
 * controls whose own keys carry meaning (select, textarea, date/range/checkbox inputs, contenteditable).
 */
export function shouldIgnoreKey(event: KeyLike): boolean {
  if (event.isComposing || event.keyCode === 229) return true;
  if (event.altKey || event.ctrlKey || event.metaKey) return true;
  const target = event.target;
  if (!target) return false;
  const tag = (target.tagName ?? "").toLowerCase();
  if (tag === "select" || tag === "textarea" || target.isContentEditable) return true;
  if (tag === "input") {
    const type = (target.type ?? "text").toLowerCase();
    if (!["text", "number", "search", "tel", ""].includes(type)) return true;
  }
  return false;
}

export type NavResult =
  | { kind: "move"; to: CellPos }
  /** Past the last/first editable cell (or no target): do nothing special; Tab falls through to the browser. */
  | { kind: "stay" }
  | { kind: "cancel" }
  | { kind: "none" };

function nextInColumn(grid: GridModel, pos: CellPos, step: 1 | -1): CellPos | null {
  for (let row = pos.row + step; row >= 0 && row < grid.rows.length; row += step) {
    if (isEditable(grid, row, pos.col)) return { row, col: pos.col };
  }
  return null;
}

function nextInReadingOrder(grid: GridModel, pos: CellPos, step: 1 | -1): CellPos | null {
  const columns = grid.columns.length;
  for (let index = pos.row * columns + pos.col + step; index >= 0 && index < grid.rows.length * columns; index += step) {
    const row = Math.floor(index / columns), col = index % columns;
    if (isEditable(grid, row, col)) return { row, col };
  }
  return null;
}

/** Maps a key press on the cell at `pos` to a grid action.  `none` means "not ours": leave the key alone. */
export function navigate(grid: GridModel, pos: CellPos, event: KeyLike): NavResult {
  if (shouldIgnoreKey(event)) return { kind: "none" };
  switch (event.key) {
    case "Enter": {
      const to = nextInColumn(grid, pos, event.shiftKey ? -1 : 1);
      return to ? { kind: "move", to } : { kind: "stay" };
    }
    case "ArrowDown": case "ArrowUp": {
      if (event.shiftKey) return { kind: "none" };       // Shift+Arrow extends a text selection
      const to = nextInColumn(grid, pos, event.key === "ArrowDown" ? 1 : -1);
      return to ? { kind: "move", to } : { kind: "stay" };
    }
    case "Tab": {
      const to = nextInReadingOrder(grid, pos, event.shiftKey ? -1 : 1);
      return to ? { kind: "move", to } : { kind: "none" };   // leave the grid: never a keyboard trap
    }
    case "Escape":
      return { kind: "cancel" };
    default:
      return { kind: "none" };
  }
}

// ───────────────────────────── TSV paste ─────────────────────────────

/** Parses spreadsheet clipboard text (TSV, CRLF/LF, RFC-4180-style quoting for cells with tabs/newlines). */
export function parseTsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [], cell = "", quoted = false, started = false;
  const pushCell = () => { row.push(cell); cell = ""; started = false; };
  const pushRow = () => { pushCell(); rows.push(row); row = []; };
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') { cell += '"'; i += 1; } else quoted = false;
      } else cell += ch;
    } else if (ch === '"' && !started && cell === "") { quoted = true; started = true; }
    else if (ch === "\t") pushCell();
    else if (ch === "\r") { if (text[i + 1] === "\n") i += 1; pushRow(); }
    else if (ch === "\n") pushRow();
    else { cell += ch; started = true; }
  }
  if (cell !== "" || row.length > 0 || started) pushRow();
  // Excel appends one trailing newline: that is not an extra empty row.
  while (rows.length > 1 && rows[rows.length - 1].every((c) => c === "")) rows.pop();
  return rows;
}

export type CellVerdict = { ok: true; value: string } | { ok: false; message: string };
export type CellValidator = (text: string) => CellVerdict;

export interface NumberRule { allowNegative?: boolean; min?: number; max?: number; separator?: DecimalSeparator; maxDecimals?: number }

/** Validator for amount-like cells.  Accepts `1,234.5`, `(1,234.5)`, `€ 1 234,5` (auto separator), `-3`; emits canonical plain text. */
export function numberValidator(rule: NumberRule = {}): CellValidator {
  const { allowNegative = false, min, max, separator = ".", maxDecimals } = rule;
  return (raw) => {
    let text = raw.trim().replace(/^[€$£]\s*|\s*(€|EUR|kEUR|k€)$/i, "");
    let negative = false;
    const paren = /^\((.*)\)$/.exec(text);
    if (paren) { negative = true; text = paren[1]; }
    const parsed = parseDecimal(text, separator);
    if (!parsed.ok) {
      return { ok: false, message: parsed.reason === "empty" ? "Enter a number." : parsed.reason === "ambiguous" ? "The decimal separator is ambiguous." : "Not a number." };
    }
    negative = negative !== parsed.negative;
    const canonical = formatDecimal({ negative, integer: parsed.integer, fraction: parsed.fraction });
    if (negative && canonical !== "0" && !allowNegative) return { ok: false, message: "Must not be negative." };
    if (maxDecimals !== undefined && (parsed.fraction.replace(/0+$/, "").length) > maxDecimals) return { ok: false, message: `At most ${maxDecimals} decimals.` };
    const asNumber = Number(canonical);
    if (!Number.isFinite(asNumber)) return { ok: false, message: "Number is out of range." };
    if (min !== undefined && asNumber < min) return { ok: false, message: `Must be at least ${min}.` };
    if (max !== undefined && asNumber > max) return { ok: false, message: `Must be at most ${max}.` };
    return { ok: true, value: canonical };
  };
}

export interface PasteAssignment { rowId: string; colId: string; value: string; rowIndex: number; colIndex: number }
export interface PasteError { rowIndex: number; colIndex: number; rowId?: string; colId?: string; message: string }
export type PastePlan = { ok: true; assignments: PasteAssignment[] } | { ok: false; errors: PasteError[] };

/**
 * Plans a paste of `matrix` anchored at `anchor`.  ALL-OR-NOTHING: if any target cell is outside the grid,
 * not editable or fails its validator the plan is rejected as a whole and nothing may be staged.
 * A single pasted value goes to the anchor cell only (the browser's normal single-cell paste).
 */
export function planPaste(grid: GridModel, anchor: CellPos, matrix: string[][], validators: Readonly<Record<string, CellValidator>>): PastePlan {
  const errors: PasteError[] = [];
  const assignments: PasteAssignment[] = [];
  matrix.forEach((cells, dr) => cells.forEach((text, dc) => {
    const rowIndex = anchor.row + dr, colIndex = anchor.col + dc;
    const row = grid.rows[rowIndex], colId = grid.columns[colIndex];
    if (!row || colId === undefined) {
      errors.push({ rowIndex, colIndex, message: "The pasted block extends past the end of the table." });
      return;
    }
    if (!row.editable[colId]) {
      errors.push({ rowIndex, colIndex, rowId: row.id, colId, message: "A pasted cell lands on a read-only or derived cell." });
      return;
    }
    const verdict = (validators[colId] ?? numberValidator())(text);
    if (!verdict.ok) errors.push({ rowIndex, colIndex, rowId: row.id, colId, message: verdict.message });
    else assignments.push({ rowId: row.id, colId, value: verdict.value, rowIndex, colIndex });
  }));
  return errors.length ? { ok: false, errors } : { ok: true, assignments };
}
