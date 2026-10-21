import React, { useEffect, useRef, useState } from "react";
import { Assumptions, assumptionLabels, InputKey } from "../_shared/validation";
import { pasteScalars, scalarKeys } from "./gridPaste";
import "./workbook.css";

const units: Partial<Record<InputKey, string>> = { capacity: "MWp", start: "date", cod: "date", term: "years", ppaPrice: "€/MWh", ppaTenor: "years", contracted: "%", indexation: "%", scheduledStep: "%", capex: "€m", opex: "€m/yr", tax: "%", debt: "€m", interest: "% p.a.", tenor: "years", dscr: "x", mezzDebt: "€m", mezzCoupon: "%", mezzPik: "%", equity: "€m", ownership: "%" };
export type InputGridProps = { values: Assumptions; committed: Assumptions; errors: Partial<Record<InputKey, string>>; onChange: (values: Assumptions) => void; onSave: () => void; onRun: () => void; onEditing: (editing: boolean) => void; blocked: boolean; dirty: boolean; runBlocked?: boolean; readOnly?: boolean };
function readInitialCell() {
  const params = new URLSearchParams(window.location.search);
  const row = Number.parseInt(params.get("inputRow") || "0", 10);
  const col = Number.parseInt(params.get("inputCol") || "0", 10);
  return {
    row: Number.isFinite(row) ? Math.max(0, Math.min(scalarKeys.length + 1, row)) : 0,
    col: Number.isFinite(col) ? Math.max(0, Math.min(1, col)) : 0,
  };
}
export default function InputGrid({ values, committed, errors, onChange, onSave, onRun, onEditing, blocked, dirty, runBlocked, readOnly = false }: InputGridProps) {
  const [cell, setCell] = useState(readInitialCell);
  const [editing, setEditing] = useState(false);
  const [buffer, setBuffer] = useState("");
  const [notice, setNotice] = useState(() => readOnly
    ? "Read-only Reference. Select a cell to inspect its synthetic value; edit, paste, Save and Run are disabled."
    : "Select a working-draft cell. Enter to edit; Enter again stages the value.");
  const [undo, setUndo] = useState<Assumptions[]>([]);
  const editor = useRef<HTMLInputElement>(null);
  const selectOnEdit = useRef(true);
  const previousCheckpoint = useRef(committed);
  const rows = [...scalarKeys, "currency", "projectIRR"] as const;
  const key = rows[cell.row];
  const editable = !readOnly && cell.col === 0 && scalarKeys.includes(key as InputKey);
  const address = `${cell.col === 0 ? "B" : "C"}${cell.row + 1}`;
  const valueAt = (row: number, col: number) => {
    const k = rows[row];
    return k === "currency" ? "EUR" : k === "projectIRR" ? "7.82%" : (col === 0 ? values : committed)[k];
  };
  useEffect(() => { if (editing) { editor.current?.focus(); if (selectOnEdit.current) editor.current?.select(); else editor.current?.setSelectionRange(buffer.length, buffer.length); } }, [editing]);
  useEffect(() => () => onEditing(false), []);
  useEffect(() => {
    setUndo([]);
    if (previousCheckpoint.current !== committed) setNotice("Scalar batch acknowledged in this browser-tab session only. No staged grid changes, backend write, or Run.");
    previousCheckpoint.current = committed;
  }, [committed]);
  function select(row: number, col: number, focus = true) {
    const next = { row: Math.max(0, Math.min(rows.length - 1, row)), col: Math.max(0, Math.min(1, col)) };
    setCell(next);
    const params = new URLSearchParams(window.location.search);
    params.set("inputRow", String(next.row));
    params.set("inputCol", String(next.col));
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}${window.location.hash}`);
    if (focus) requestAnimationFrame(() => document.getElementById(`wb-cell-${next.row}-${next.col}`)?.focus());
  }
  function begin(text?: string) {
    if (readOnly) { setNotice("Reference is read-only. No edit was opened; create a local working copy to make changes."); return; }
    if (!editable) { setNotice("Locked / fixed synthetic cell. No formula evaluation or editing."); return; }
    selectOnEdit.current = text === undefined;
    setBuffer(text ?? valueAt(cell.row, cell.col)); setEditing(true); onEditing(true);
  }
  function stage(row: number, col: number) {
    if (readOnly) { setEditing(false); onEditing(false); setNotice("Reference is read-only. No staged value was changed."); return; }
    if (scalarKeys.includes(key as InputKey)) { setUndo(stack => [...stack.slice(-19), { ...values }]); onChange({ ...values, [key]: buffer }); }
    setEditing(false); onEditing(false); setNotice(`${address} staged locally. Save batch separately; nothing calculated.`);
    select(row, col);
  }
  function cancel() { setEditing(false); onEditing(false); setNotice("Cell edit cancelled; previous staged value retained."); select(cell.row, cell.col); }
  function undoBatch() {
    if (readOnly) { setNotice("Undo is unavailable in read-only Reference mode."); return; }
    const previous = undo.at(-1);
    if (!previous) return;
    onChange(previous); setUndo(stack => stack.slice(0, -1)); setNotice("Last grid edit / paste undone. No backend data changed.");
  }
  function tabMove(reverse: boolean) {
    const flat = Math.max(0, Math.min(rows.length * 2 - 1, cell.row * 2 + cell.col + (reverse ? -1 : 1)));
    return { row: Math.floor(flat / 2), col: flat % 2 };
  }
  function keys(event: React.KeyboardEvent) {
    if (editing) {
      if (event.key === "Escape") { event.preventDefault(); cancel(); }
      if (event.key === "Enter") { event.preventDefault(); stage(cell.row + (event.shiftKey ? -1 : 1), cell.col); }
      if (event.key === "Tab") { event.preventDefault(); const next = tabMove(event.shiftKey); stage(next.row, next.col); }
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") { event.preventDefault(); undoBatch(); return; }
    if (event.key === "Enter" || event.key === "F2") { event.preventDefault(); begin(); }
    else if (event.key === "Escape") { setNotice("No active cell edit to cancel."); }
    else if (event.key === "Tab") {
      const next = tabMove(event.shiftKey);
      // Let Tab leave the grid at its outer boundaries.
      if (next.row === cell.row && next.col === cell.col) return;
      event.preventDefault(); select(next.row, next.col);
    } else if (event.key.startsWith("Arrow")) {
      event.preventDefault();
      select(cell.row + (event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0), cell.col + (event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0));
    } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) { event.preventDefault(); begin(event.key); }
  }
  return <section aria-labelledby="grid-title" className="fm-wb-grid-panel">
    <div className="fm-card-title"><h2 id="grid-title">Hybrid Input Grid</h2><span>Authorized scalar demo · 21 fields + locked references</span></div>
    <div className="fm-wb-grid-toolbar"><span><b>{readOnly ? "REFERENCE · READ ONLY" : dirty ? "UNSAVED / STAGED" : "No staged scalar changes"}</b> · {readOnly ? "inspect only" : "browser-tab demo only"}</span>
      <div><button type="button" className="fm-btn" disabled={readOnly || !undo.length || editing} onClick={undoBatch}>Undo staged edit</button> <button type="button" className="fm-btn" disabled={readOnly} aria-disabled={blocked || editing} onClick={onSave}>Save scalar batch</button> <button type="button" className="fm-btn fm-btn-primary" disabled={readOnly} aria-disabled={runBlocked || blocked || dirty || editing} onClick={onRun}>Run demo separately</button></div>
    </div>
    <div className="fm-wb-formula" aria-label="Cell address and display-only value bar"><strong>{address}</strong><span>fx · display only</span><output>{editing ? buffer : valueAt(cell.row, cell.col)}</output><small>{units[key as InputKey] || (key === "currency" ? "ISO" : key === "projectIRR" ? "%" : "—")} · {readOnly ? "Reference · read-only" : editable ? "Working-copy input" : "Fixed synthetic reference"} · {key === "projectIRR" ? "label only" : editable ? "no expression" : "no formula evaluation"}</small></div>
    <div className="fm-wb-grid-help">Enter/F2 edit · Enter/Shift+Enter stage + down/up · Tab/Shift+Tab next/previous cell · Esc cancel · arrows select · Ctrl/Cmd+Z undo. Paste one value column from selected row, or TSV metric + value pairs. Locked cells reject edits.</div>
    <div className="fm-wb-grid-scroll" role="region" tabIndex={-1} aria-label="Input grid scroll area">
      <table role="grid" aria-label="Hybrid input grid" aria-readonly={readOnly || undefined} aria-rowcount={rows.length + 1} aria-colcount={4} className="fm-wb-input-table"
        onKeyDown={keys} onPaste={event => {
          if (editing) return;
          event.preventDefault();
           if (readOnly) { setNotice("Paste rejected: Reference is read-only. No values changed."); return; }
          if (!editable) { setNotice("Paste rejected: selected cell is locked. Nothing staged."); return; }
          const result = pasteScalars(event.clipboardData.getData("text/plain"), cell.row, values);
          if (result.error || !result.values) { setNotice(result.error || "Paste rejected."); return; }
          setUndo(stack => [...stack.slice(-19), { ...values }]); onChange(result.values); setNotice("Entire validated paste batch staged atomically in this browser tab. Save is separate; no backend write.");
        }}>
        <thead><tr><th scope="col">A · Metric</th><th scope="col">Unit</th><th scope="col">B · Working draft</th><th scope="col">C · Last demo save / locked</th></tr></thead>
        <tbody>{rows.map((k, row) => {
          const unlocked = scalarKeys.includes(k as InputKey);
          const error = unlocked ? errors[k as InputKey] : undefined;
          return <tr key={k} className={cell.row === row ? "fm-wb-active-row" : undefined}><th scope="row"><span className="fm-wb-rownum">{row + 1}</span>{unlocked ? assumptionLabels[k as InputKey] : k === "currency" ? "Reporting currency" : "Project IRR · fixed synthetic"}</th>
            <td className="fm-wb-unit">{unlocked ? units[k as InputKey] : k === "currency" ? "ISO" : "%"}</td>
            {[0, 1].map(col => {
              const active = cell.row === row && cell.col === col;
              return <td role="gridcell" aria-selected={active} key={col} className={`${col === cell.col ? "fm-wb-active-column " : ""}${col === 1 || !unlocked ? "fm-wb-locked" : ""}${col === 0 && unlocked && values[k as InputKey] !== committed[k as InputKey] ? " fm-wb-dirty" : ""}${error && col === 0 ? " fm-wb-cell-error" : ""}`}>
                {active && editing ? <input ref={editor} aria-label={`Edit ${unlocked ? assumptionLabels[k as InputKey] : k}`} value={buffer} onChange={e => setBuffer(e.target.value)} /> :
                  <button id={`wb-cell-${row}-${col}`} type="button" tabIndex={active ? 0 : -1} aria-label={`${col === 0 ? "B" : "C"}${row + 1} ${unlocked ? assumptionLabels[k as InputKey] : k} ${valueAt(row, col)}${col === 1 || !unlocked ? " locked" : " editable"}`} aria-invalid={Boolean(error && col === 0)} aria-describedby={error && col === 0 ? `wb-error-${k}` : undefined}
                      onFocus={() => select(row, col, false)} onClick={() => select(row, col, false)} onDoubleClick={() => {
                        select(row, col, false);
                        if (readOnly) { setNotice("Reference is read-only. No edit was opened."); return; }
                        if (col === 0 && unlocked) { selectOnEdit.current = true; setBuffer(values[k as InputKey]); setEditing(true); onEditing(true); }
                      }}>{valueAt(row, col)}</button>}
                {error && col === 0 && <span className="fm-invalid-note" id={`wb-error-${k}`}>{error}</span>}
              </td>;
            })}</tr>;
        })}</tbody>
      </table>
    </div>
    <p role="status" className="fm-wb-grid-notice">{notice}</p>
    <div className="fm-info-note">This is a scalar sheet, not a period-input matrix. Period-aligned examples live in CAPEX/OPEX planners and statement sheets. “Last demo save” is a browser-tab session checkpoint only; it is not backend persistence.</div>
  </section>;
}
