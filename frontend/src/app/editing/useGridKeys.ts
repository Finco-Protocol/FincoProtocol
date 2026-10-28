// WS-2 — wires the pure grid behaviour (grid.ts) to DOM events for one table.
//
// Cells are inputs carrying data-r / data-c.  The hook owns focus movement, Escape-cancel, TSV paste
// and undo/redo shortcuts; it never decides what a value means (the caller's validators and the
// server do) and it stays out of the way of IME, selects, textareas and modified shortcuts.

import { useCallback, useRef, type ClipboardEvent, type KeyboardEvent, type RefObject } from "react";
import { navigate, parseTsv, planPaste, type CellValidator, type GridModel, type PasteAssignment, type PastePlan } from "./grid";

export interface GridKeyOptions {
  model: GridModel;
  validators: Readonly<Record<string, CellValidator>>;
  /** Value a cell had when it received focus: Escape restores it. */
  restore: (rowId: string, colId: string, value: string) => void;
  /** An accepted paste: applied as ONE staged step. */
  applyPaste: (assignments: PasteAssignment[]) => void;
  /** A rejected paste: nothing was staged. */
  rejectPaste: (plan: Extract<PastePlan, { ok: false }>) => void;
  undo: () => void;
  redo: () => void;
}

export function useGridKeys(container: RefObject<HTMLElement>, options: GridKeyOptions) {
  const focusValue = useRef<{ r: number; c: number; value: string } | null>(null);
  const opts = useRef(options);
  opts.current = options;

  const focusCell = useCallback((r: number, c: number) => {
    const el = container.current?.querySelector<HTMLInputElement>(`input[data-r="${r}"][data-c="${c}"]`);
    if (el) { el.focus(); el.select(); }
  }, [container]);

  const posOf = (el: EventTarget | null) => {
    const input = el as HTMLInputElement | null;
    if (!input || input.dataset?.r === undefined) return null;
    return { row: Number(input.dataset.r), col: Number(input.dataset.c) };
  };

  const onFocus = useCallback((event: React.FocusEvent<HTMLInputElement>) => {
    const pos = posOf(event.target);
    if (pos) focusValue.current = { r: pos.row, c: pos.col, value: event.target.value };
  }, []);

  const onKeyDown = useCallback((event: KeyboardEvent<HTMLInputElement>) => {
    const { model, restore, undo, redo } = opts.current;
    const pos = posOf(event.target);
    if (!pos) return;
    const native = event.nativeEvent;
    // App-level undo/redo: the store is the authority for staged values (native text undo would diverge from it).
    if ((event.ctrlKey || event.metaKey) && !event.altKey && !native.isComposing && event.key.toLowerCase() === "z") {
      event.preventDefault(); if (event.shiftKey) redo(); else undo(); return;
    }
    if ((event.ctrlKey || event.metaKey) && !event.altKey && !native.isComposing && event.key.toLowerCase() === "y") {
      event.preventDefault(); redo(); return;
    }
    const result = navigate(model, pos, {
      key: event.key, shiftKey: event.shiftKey, altKey: event.altKey, ctrlKey: event.ctrlKey, metaKey: event.metaKey,
      isComposing: native.isComposing, keyCode: native.keyCode,
      target: { tagName: (event.target as HTMLElement).tagName, type: (event.target as HTMLInputElement).type },
    });
    if (result.kind === "move") { event.preventDefault(); focusCell(result.to.row, result.to.col); }
    else if (result.kind === "stay") event.preventDefault();      // Enter on the last row: keep focus, never submit a form
    else if (result.kind === "cancel") {
      const saved = focusValue.current;
      if (saved && saved.r === pos.row && saved.c === pos.col) {
        event.preventDefault();
        restore(model.rows[pos.row].id, model.columns[pos.col], saved.value);
      }
    }
  }, [focusCell]);

  const onPaste = useCallback((event: ClipboardEvent<HTMLInputElement>) => {
    const pos = posOf(event.target);
    if (!pos) return;
    const text = event.clipboardData.getData("text/plain");
    const matrix = parseTsv(text);
    // A single value pastes like ordinary text into the focused input.
    if (matrix.length <= 1 && (matrix[0]?.length ?? 0) <= 1) return;
    event.preventDefault();
    const { model, validators, applyPaste, rejectPaste } = opts.current;
    const plan = planPaste(model, pos, matrix, validators);
    if (plan.ok) applyPaste(plan.assignments); else rejectPaste(plan);
  }, []);

  return { onKeyDown, onPaste, onFocus, focusCell };
}
