import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useDemoSessionState } from "../_shared/demoSession";
import { preferredScrollBehavior } from "../_shared/motion";
import { isEditablePeriodCell, pastePeriodRectangle, periodCellError, periodHeaders, periodRows, type PeriodRow } from "./periodGrid";
import "./period-grid.css";

export type LineSheet = "capex" | "opex";
export type LineValues = Record<LineSheet, string[][]>;
export const initialLineValues: LineValues = {
  capex: [["1.2", "2.4", "3.1"], ["0.1", "0.3", "0.4"], ["0.2", "0.2", "0.3"]],
  opex: [["0.35", "0.36", "0.36"], ["0.04", "0.04", "0.05"], ["0.02", "0.03", "0.03"]],
};
export const lineErrors = (values: string[][]) =>
  values.some(row => row.some(value => !value.trim() || !Number.isFinite(Number(value)) || Number(value) < 0));

type Cell = { row: number; col: number };
export type CostLinePlannerProps = {
  sheet: LineSheet;
  values: string[][];
  committed: string[][];
  operationPeriod: string;
  onOperationPeriodChange: (value: "3M" | "6M") => void;
  onChange: (next: string[][]) => void;
  onSave: () => void;
  onEditing?: (editing: boolean) => void;
  onPendingError?: (pending: boolean) => void;
  readOnly?: boolean;
};

const colLabel = (col: number) => {
  let value = col + 2;
  let label = "";
  while (value > 0) {
    const remainder = (value - 1) % 26;
    label = String.fromCharCode(65 + remainder) + label;
    value = Math.floor((value - 1) / 26);
  }
  return label;
};

export default function CostLinePlanner({ sheet, values, committed, operationPeriod, onOperationPeriodChange, onChange, onSave, onEditing, onPendingError, readOnly = false }: CostLinePlannerProps) {
  const [view, setView] = useState<"quarterly" | "semiannual">(operationPeriod === "6M" ? "semiannual" : "quarterly");
  const [horizon, setHorizon] = useState<"sample" | "60" | "80" | "120">(() => {
    const requested = new URLSearchParams(window.location.search).get("opexHorizon");
    if (requested === "extended") return "60";
    return requested === "60" || requested === "80" || requested === "120" ? requested : "sample";
  });
  const [profile, setProfile] = useState("Front-loaded");
  const [precision, setPrecision] = useState(2);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const horizonQuarterCount = horizon === "sample" ? 12 : Number(horizon);
  const longHorizon = sheet === "opex" && horizon !== "sample" ? horizonQuarterCount : false;
  const rows = useMemo(() => periodRows(sheet, view, longHorizon), [sheet, view, longHorizon]);
  const headers = useMemo(() => periodHeaders(sheet, view, longHorizon), [sheet, view, longHorizon]);
  const validationRows = useMemo(() => periodRows(sheet, "quarterly", sheet === "opex"), [sheet]);
  const lockedView = sheet === "opex" && view === "semiannual";
  const sourceValues = lockedView ? rows.map(row => [...row.values]) : values;
  const visibleRows = useMemo(() => rows.map((row, rowIndex) => ({ row, rowIndex })).filter(({ row, rowIndex }) => {
    if (row.kind === "group") return true;
    let parent: string | undefined;
    for (let index = rowIndex - 1; index >= 0; index--) {
      if (rows[index].kind === "group") { parent = rows[index].id; break; }
    }
    return !parent || !collapsedGroups.has(parent);
  }), [collapsedGroups, rows]);
  const visibleIndexes = useMemo(() => new Set(visibleRows.map(item => item.rowIndex)), [visibleRows]);
  const editableCells = useMemo(() => {
    const cells: Cell[] = [];
    rows.forEach((row, rowIndex) => headers.forEach((_, colIndex) => {
      if (visibleIndexes.has(rowIndex) && !lockedView && isEditablePeriodCell(sheet, view, rowIndex, colIndex, longHorizon)) cells.push({ row: rowIndex, col: colIndex });
    }));
    return cells;
  }, [headers, lockedView, longHorizon, rows, sheet, view, visibleIndexes]);
  const firstCell = editableCells[0] || { row: 0, col: 0 };
  const [selected, setSelected] = useState<Cell>(() => {
    const params = new URLSearchParams(window.location.search);
    const requested = { row: Number.parseInt(params.get("costRow") || "", 10), col: Number.parseInt(params.get("costCol") || "", 10) };
    return params.get("costSheet") === sheet && editableCells.some(cell => cell.row === requested.row && cell.col === requested.col) ? requested : firstCell;
  });
  const [range, setRange] = useState<{ from: Cell; to: Cell } | null>(null);
  const [editing, setEditing] = useState<Cell | null>(null);
  const [buffer, setBuffer] = useState("");
  const [pendingError, setPendingError] = useState("");
  const [saveNotice, setSaveNotice] = useState("");
  const [lineSaveAcknowledgements, setLineSaveAcknowledgements] = useDemoSessionState("period-line-save-acknowledgements", { capex: false, opex: false });
  const locallySaved = lineSaveAcknowledgements[sheet];
  const setLocallySaved = (value: boolean) => setLineSaveAcknowledgements(current => ({ ...current, [sheet]: value }));
  const scrollRef = useRef<HTMLDivElement>(null);
  const cellRefs = useRef(new Map<string, HTMLButtonElement>());
  const undoRef = useRef<string[][][]>([]);
  const editCallbackRef = useRef(onEditing);
  const pendingCallbackRef = useRef(onPendingError);
  editCallbackRef.current = onEditing;
  pendingCallbackRef.current = onPendingError;

  const dirty = JSON.stringify(values) !== JSON.stringify(committed);
  const errors = useMemo(() => {
    if (lockedView) return [] as { row: number; col: number; message: string }[];
    const found: { row: number; col: number; message: string }[] = [];
    validationRows.forEach((row, rowIndex) => {
      (values[rowIndex] || []).forEach((value, colIndex) => {
        const message = periodCellError(row, value);
        if (message) found.push({ row: rowIndex, col: colIndex, message });
      });
    });
    return found;
  }, [lockedView, validationRows, values]);
  const firstError = errors[0];
  const address = `${colLabel(selected.col)}${selected.row + 1}`;
  const displayValue = (rowIndex: number, colIndex: number) => {
    const raw = sourceValues[rowIndex]?.[colIndex] ?? rows[rowIndex]?.values[colIndex] ?? "";
    if (!raw || raw === "—" || raw === "Not linked") return raw;
    const row = rows[rowIndex];
    if (row?.kind === "amount" || row?.unit === "%") {
      const number = Number(raw);
      if (Number.isFinite(number)) return row.unit === "%" ? `${number.toFixed(precision)}%` : number.toFixed(precision);
    }
    return raw;
  };
  const selectCell = useCallback((cell: Cell) => {
    setSelected(cell);
    const params = new URLSearchParams(window.location.search);
    params.set("costSheet", sheet);
    params.set("costRow", String(cell.row));
    params.set("costCol", String(cell.col));
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}${window.location.hash}`);
  }, [sheet]);

  useEffect(() => {
    setView(operationPeriod === "6M" ? "semiannual" : "quarterly");
  }, [operationPeriod]);
  useEffect(() => {
    const isStillEditable = editableCells.some(cell => cell.row === selected.row && cell.col === selected.col);
    const fallback = editableCells[0] || { row: 0, col: 0 };
    if (!isStillEditable && (fallback.row !== selected.row || fallback.col !== selected.col)) selectCell(fallback);
  }, [editableCells, selected, selectCell]);
  useEffect(() => {
    if (!firstError) return;
    for (let index = firstError.row - 1; index >= 0; index--) {
      if (rows[index].kind === "group") {
        setCollapsedGroups(current => {
          if (!current.has(rows[index].id)) return current;
          const next = new Set(current);
          next.delete(rows[index].id);
          return next;
        });
        break;
      }
    }
  }, [firstError, rows]);
  useEffect(() => {
    if (!editing) cellRefs.current.get(`${selected.row}:${selected.col}`)?.focus();
  }, [editing, selected]);
  useEffect(() => () => {
    editCallbackRef.current?.(false);
    pendingCallbackRef.current?.(false);
  }, []);

  const reportPending = (message: string) => {
    setPendingError(message);
    pendingCallbackRef.current?.(Boolean(message));
  };
  const snapshot = () => {
    undoRef.current = [...undoRef.current.slice(-39), values.map(row => [...row])];
  };
  const stageCell = (row: number, col: number, value: string) => {
    snapshot();
    const next = values.map(line => [...line]);
    if (!next[row]) next[row] = [];
    next[row][col] = value;
    onChange(next);
    reportPending("");
    setSaveNotice("");
    setLocallySaved(false);
  };
  const finishEdit = (move?: "next" | "previous" | "down" | "up") => {
    if (!editing) return;
    const current = editing;
    stageCell(current.row, current.col, buffer);
    setEditing(null);
    editCallbackRef.current?.(false);
    if (move) moveSelection(current, move);
  };
  const cancelEdit = () => {
    setEditing(null);
    editCallbackRef.current?.(false);
  };
  const moveSelection = useCallback((from: Cell, direction: "next" | "previous" | "down" | "up", extend = false) => {
    if (!editableCells.length) return;
    const index = editableCells.findIndex(cell => cell.row === from.row && cell.col === from.col);
    let targetIndex = index;
    if (direction === "next") targetIndex = index + 1;
    if (direction === "previous") targetIndex = index - 1;
    if (direction === "down" || direction === "up") {
      const step = direction === "down" ? 1 : -1;
      let targetRow = from.row + step;
      while (targetRow >= 0 && targetRow < rows.length) {
        const match = editableCells.findIndex(cell => cell.row === targetRow && cell.col === from.col);
        if (match >= 0) { targetIndex = match; break; }
        targetRow += step;
      }
    }
    if (targetIndex < 0 || targetIndex >= editableCells.length || targetIndex === index) {
      if (direction === "next" || direction === "previous") {
        selectCell(from);
        requestAnimationFrame(() => document.getElementById("finco-line-save")?.focus());
      }
      return;
    }
    const target = editableCells[targetIndex];
    selectCell(target);
    if (extend) setRange(current => ({ from: current?.from || from, to: target }));
    else setRange(null);
  }, [editableCells, rows.length, selectCell]);

  const beginEdit = (row: number, col: number, initialText?: string) => {
    if (readOnly) {
      setSaveNotice("Reference is read-only. No cost-line edit was opened; create a local working copy to edit.");
      return;
    }
    if (!isEditablePeriodCell(sheet, view, row, col, longHorizon) || lockedView) return;
    selectCell({ row, col });
    setBuffer(initialText ?? sourceValues[row]?.[col] ?? "");
    setEditing({ row, col });
    editCallbackRef.current?.(true);
    reportPending("");
  };
  const handlePaste = (event: React.ClipboardEvent, row: number, col: number) => {
    event.preventDefault();
    if (readOnly) {
      reportPending("Paste blocked: Reference is read-only. No values changed.");
      return;
    }
    if (lockedView) {
      reportPending("Semiannual OPEX is a fixed reference view. Switch to quarterly to edit values.");
      return;
    }
    const parsed = pastePeriodRectangle(event.clipboardData.getData("text/plain"), row, col, rows, values, sheet, view, longHorizon);
    if (parsed.error || !parsed.values) {
      reportPending(parsed.error || "This pasted range was rejected. No cells were changed; correct the range and paste again.");
      return;
    }
    snapshot();
    onChange(parsed.values);
    reportPending("");
    setSaveNotice("");
    setLocallySaved(false);
    setEditing(null);
    editCallbackRef.current?.(false);
  };
  const undo = () => {
    if (readOnly) {
      setSaveNotice("Undo is unavailable in read-only Reference mode.");
      return;
    }
    if (editing) { cancelEdit(); return; }
    const prior = undoRef.current.pop();
    if (prior) {
      onChange(prior);
      reportPending("");
      setLocallySaved(false);
      setSaveNotice("Last staged edit restored.");
    }
  };
  const handleGridKey = (event: React.KeyboardEvent, cell: Cell) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
      event.preventDefault();
      undo();
      return;
    }
    if (event.key === "ArrowRight" || event.key === "ArrowDown" || event.key === "ArrowLeft" || event.key === "ArrowUp") {
      event.preventDefault();
      moveSelection(cell, event.key === "ArrowRight" ? "next" : event.key === "ArrowLeft" ? "previous" : event.key === "ArrowDown" ? "down" : "up", event.shiftKey);
    } else if (event.key === "Enter" || event.key === "F2") {
      event.preventDefault();
      beginEdit(cell.row, cell.col);
    } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      beginEdit(cell.row, cell.col, event.key);
    }
  };
  const onSaveClick = () => {
    if (readOnly) {
      setSaveNotice("Reference is read-only. No cost-line Save was performed.");
      return;
    }
    if (editing) {
      setSaveNotice("Finish the active cell edit with Enter or Tab, or cancel it with Esc, before saving.");
      return;
    }
    if (errors.length || pendingError) {
      setSaveNotice("Correct the marked cells and resolve the rejected paste before saving this line batch.");
      return;
    }
    onSave();
    setLocallySaved(true);
    setSaveNotice("Local demo save acknowledged for this line batch only. No model run was triggered; fixed Last Run values did not change.");
  };
  const isInRange = (row: number, col: number) => {
    if (!range) return false;
    return row >= Math.min(range.from.row, range.to.row) && row <= Math.max(range.from.row, range.to.row) &&
      col >= Math.min(range.from.col, range.to.col) && col <= Math.max(range.from.col, range.to.col);
  };
  const scrollPeriods = (direction: -1 | 1) => scrollRef.current?.scrollBy({ left: direction * 360, behavior: preferredScrollBehavior() });
  const profileCopy: Record<string, string> = {
    "Front-loaded": "Illustrative early draw pattern only. Selection changes this note, not period values or calculations.",
    "Back-loaded": "Illustrative later draw pattern only. Selection changes this note, not period values or calculations.",
    "S-curve": "Illustrative construction cadence only. No S-curve is applied to the values below.",
    Milestone: "Illustrative milestone cadence only. Milestone dates are editable where shown; no spend is generated.",
  };

  return <section className="fm-card fm-period-editor" aria-labelledby="fm-period-title">
    <div className="fm-card-title fm-period-title">
      <div><h2 id="fm-period-title">{sheet.toUpperCase()} period cost lines</h2><span className="fm-period-unit">{sheet === "opex" && longHorizon
        ? `${view === "quarterly" ? `${horizonQuarterCount}-quarter` : `${Math.ceil(horizonQuarterCount / 2)}-half-year`} · ${horizonQuarterCount > 60 ? "layout stress fixture" : "extended UX fixture"}`
        : "EUR millions · fixed synthetic data"}</span></div>
      <span className={`fm-period-state${dirty ? " is-dirty" : ""}`}>{readOnly ? "REFERENCE · READ ONLY" : lockedView ? "SEMIANNUAL · FIXED REFERENCE VIEW" : dirty ? "WORKING COPY · UNSAVED" : locallySaved ? "LOCAL DEMO SAVE · NOT RUN" : "WORKING COPY · NO STAGED EDITS"}</span>
    </div>
    <div className="fm-period-toolbar">
      <div className="fm-period-toolbar-left">
        {sheet === "capex" ? <>
          <label>Profile example <select aria-label="CAPEX profile design example" value={profile} onChange={event => setProfile(event.target.value)}>
            {["Front-loaded", "Back-loaded", "S-curve", "Milestone"].map(option => <option key={option}>{option}</option>)}
          </select></label>
          <span className="fm-period-copy">{profileCopy[profile]}</span>
        </> : <>
          <label>Operating view <select aria-label="OPEX period view" value={view} onChange={event => {
            const next = event.target.value as "quarterly" | "semiannual";
            setView(next);
            onOperationPeriodChange(next === "semiannual" ? "6M" : "3M");
            setRange(null);
            setEditing(null);
            editCallbackRef.current?.(false);
          }}>
            <option value="quarterly">Quarterly · editable working copy</option>
            <option value="semiannual">Semiannual · locked fixed view</option>
          </select></label>
          <label>Schedule horizon <select aria-label="OPEX schedule horizon" value={horizon} onChange={event => {
            const next = event.target.value as "sample" | "60" | "80" | "120";
            setHorizon(next);
            setRange(null);
            setEditing(null);
            editCallbackRef.current?.(false);
            const params = new URLSearchParams(window.location.search);
            if (next === "sample") params.delete("opexHorizon"); else params.set("opexHorizon", next);
            window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}${window.location.hash}`);
          }}>
            <option value="sample">Sample · 12Q / 6H</option>
            <option value="60">Long UX preview · 60Q / 30H</option>
            <option value="80">Layout stress only · 80Q / 40H</option>
            <option value="120">Layout stress only · 120Q / 60H</option>
          </select></label>
          <span className="fm-period-copy">No escalation or aggregation is generated. Beyond the authored 12Q example, editable 60Q cells are zero placeholders, not a forecast. 80Q/120Q are layout stress views only; cells after 60Q are unavailable and locked. Half-year values are fixed references, not aggregates.</span>
        </>}
      </div>
      <div className="fm-period-actions">
        <label className="fm-period-precision">Decimals <select aria-label={`${sheet.toUpperCase()} display precision`} value={precision} onChange={event => setPrecision(Number(event.target.value))}>{[0, 1, 2, 3].map(value => <option key={value} value={value}>{value}</option>)}</select></label>
        <button type="button" className="fm-period-scroll-control" aria-label="Scroll periods left" onClick={() => scrollPeriods(-1)}>← Earlier</button>
        <button type="button" className="fm-period-scroll-control" aria-label="Scroll periods right" onClick={() => scrollPeriods(1)}>Later →</button>
        <button id="finco-line-save" type="button" className="fm-btn fm-period-save" onClick={onSaveClick} disabled={Boolean(readOnly || editing || errors.length || pendingError || lockedView)} aria-describedby="fm-period-save-note">
          {readOnly ? "Save disabled · Reference" : lockedView ? "Fixed view" : `Save ${sheet.toUpperCase()} lines`}
        </button>
      </div>
    </div>
    <div className="fm-period-boundary" role="status">
      <span>{sheet === "opex" ? "Quarterly Working Copy" : "Monthly Working Copy"}: <strong>{dirty ? "unsaved edits" : "clean"}</strong> · Local Save: <strong>{locallySaved ? "acknowledged in this browser-tab session only" : "not saved"}</strong> · Run: <strong>not executed</strong></span>
      <span>{lockedView ? "Semiannual view: fixed synthetic Last Run reference · no quarterly aggregation" : "Last Run: fixed synthetic reference · separate Save never runs it"}</span>
    </div>
    <div className="fm-period-formula" aria-live="polite">
      <strong className="fm-period-address">{address}</strong>
      <span className="fm-period-formula-label">{rows[selected.row]?.label || "Selected period"}</span>
      <span className="fm-period-value">{sourceValues[selected.row]?.[selected.col] ?? ""}</span>
      <span className="fm-period-unit">{rows[selected.row]?.unit || "—"}</span>
      <span className="fm-period-source">{lockedView || rows[selected.row]?.kind === "fixed" ? "Fixed synthetic reference · no lineage" : "Working-copy input · local demo only"}</span>
      {lockedView && <span className="fm-period-lock">Fixed view</span>}
    </div>
    <div className="fm-period-scroll" ref={scrollRef} role="region" aria-label={`${sheet.toUpperCase()} period spreadsheet`} tabIndex={-1}>
      <table className="fm-period-table">
        <thead><tr><th scope="col" className="fm-period-metric-head">Line item <span>EUR m</span></th>{headers.map((header, col) =>
          <th key={`${header}-${col}`} scope="col" className="fm-period-heading"><span>{colLabel(col)}</span>{header}</th>
        )}</tr></thead>
        <tbody>{visibleRows.map(({ row, rowIndex }: { row: PeriodRow; rowIndex: number }) => {
          const rowValues = sourceValues[rowIndex] || [];
          const isGroup = row.kind === "group";
            return <tr key={row.id} className={`fm-period-row fm-period-row-${row.kind}${selected.row === rowIndex ? " is-active-row" : ""}`}>
            <th scope="row" className="fm-period-metric">
              <span className="fm-period-row-number">{rowIndex + 1}</span>
              {row.kind === "group" ? <button
                type="button"
                className="fm-period-group-toggle"
                aria-expanded={!collapsedGroups.has(row.id)}
                aria-label={`${collapsedGroups.has(row.id) ? "Expand" : "Collapse"} ${row.label}`}
                onClick={() => setCollapsedGroups(current => {
                  const next = new Set(current);
                  if (next.has(row.id)) next.delete(row.id); else next.add(row.id);
                  return next;
                })}
              >{collapsedGroups.has(row.id) ? "＋" : "−"} <span>{row.label}</span></button> : <span>{row.label}</span>}
              <small>{row.unit}</small>
            </th>
            {headers.map((_, colIndex) => {
              const value = rowValues[colIndex] ?? row.values[colIndex] ?? "";
              const editable = !lockedView && isEditablePeriodCell(sheet, view, rowIndex, colIndex, longHorizon);
              const error = editable ? periodCellError(row, value) : undefined;
              const isSelected = selected.row === rowIndex && selected.col === colIndex;
              const cellAddress = `${colLabel(colIndex)}${rowIndex + 1}`;
              const dirtyCell = editable && !lockedView && value !== committed[rowIndex]?.[colIndex];
              return <td key={`${row.id}-${colIndex}`} className={[
                "fm-period-cell",
                selected.col === colIndex ? "is-active-column" : "",
                !editable ? "is-locked" : "",
                dirtyCell ? "is-dirty" : "",
                error ? "has-error" : "",
                isSelected ? "is-selected" : "",
                isInRange(rowIndex, colIndex) ? "is-range" : "",
                isGroup ? "is-group-cell" : "",
              ].filter(Boolean).join(" ")} aria-selected={isSelected || isInRange(rowIndex, colIndex)} aria-invalid={error ? "true" : undefined}>
                {editing?.row === rowIndex && editing.col === colIndex ? <input
                  className="fm-period-input"
                  aria-label={`${sheet.toUpperCase()} ${row.label}, ${headers[colIndex]}, cell ${cellAddress}`}
                  aria-invalid={error ? "true" : undefined}
                  aria-describedby={error ? `fm-period-error-${rowIndex}-${colIndex}` : undefined}
                  value={buffer}
                  autoFocus
                  onChange={event => setBuffer(event.target.value)}
                  onKeyDown={event => {
                    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") { event.preventDefault(); undo(); return; }
                    if (event.key === "Escape") { event.preventDefault(); cancelEdit(); }
                    else if (event.key === "Enter") { event.preventDefault(); finishEdit(event.shiftKey ? "up" : "down"); }
                    else if (event.key === "Tab") { event.preventDefault(); finishEdit(event.shiftKey ? "previous" : "next"); }
                  }}
                  onPaste={event => handlePaste(event, rowIndex, colIndex)}
                  onBlur={() => { if (editing?.row === rowIndex && editing.col === colIndex) finishEdit(); }}
                /> : <button
                  ref={element => {
                    const key = `${rowIndex}:${colIndex}`;
                    if (element) cellRefs.current.set(key, element);
                    else cellRefs.current.delete(key);
                  }}
                  type="button"
                  className="fm-period-cell-button"
                  tabIndex={editable && isSelected ? 0 : -1}
                  disabled={!editable}
                  aria-label={`${sheet.toUpperCase()} ${row.label}, ${headers[colIndex]}, ${value || "blank"}${error ? `, error: ${error}` : ""}${!editable ? ", fixed" : ""}`}
                  title={error || `${row.label} · ${headers[colIndex]} · ${cellAddress}`}
                  onClick={event => {
                    selectCell({ row: rowIndex, col: colIndex });
                    if (event.shiftKey) setRange(current => ({ from: current?.from || selected, to: { row: rowIndex, col: colIndex } }));
                    else setRange(null);
                  }}
                  onDoubleClick={() => beginEdit(rowIndex, colIndex)}
                  onKeyDown={event => handleGridKey(event, { row: rowIndex, col: colIndex })}
                  onPaste={event => handlePaste(event, rowIndex, colIndex)}
                >{displayValue(rowIndex, colIndex) || <span className="fm-period-empty">—</span>}</button>}
                {error && <span className="fm-period-error" id={`fm-period-error-${rowIndex}-${colIndex}`} role="status">{error}</span>}
              </td>;
            })}
          </tr>;
        })}</tbody>
      </table>
    </div>
    <div className="fm-period-footer">
      <div className="fm-period-instructions">
        <strong>Cell {address}</strong> · Enter edits · arrows move between editable cells · Enter / Shift+Enter stages and moves vertically · Tab / Shift+Tab stages across cells · Esc cancels · paste a TSV rectangle · Ctrl/Cmd+Z undoes one staged change.
      </div>
      <div className="fm-period-disclaimer">Fixed summaries are reference values and may not reconcile. No totals, forecasts, or financial results are calculated here. Demo TSV staging is local only; it does not represent production multi-row cost-line persistence (canonical line saves are per-row serial CAS and require independent verification).</div>
    </div>
    {(firstError || pendingError || saveNotice) && <div className={`fm-period-message${firstError || pendingError ? " is-error" : ""}`} role={firstError || pendingError ? "alert" : "status"}>
      {pendingError && <p><strong>Paste not applied.</strong> {pendingError} No cell in the rectangle was changed.</p>}
      {firstError && <p><strong>Cell {colLabel(firstError.col)}{firstError.row + 1} needs correction.</strong> {firstError.message} Correct the marked value before saving.</p>}
      {saveNotice && <p id="fm-period-save-note">{saveNotice}</p>}
    </div>}
    {!firstError && !pendingError && !saveNotice && <span id="fm-period-save-note" className="fm-period-sr-only">Save is available when all editable values are valid and no cell is being edited.</span>}
    {sheet === "capex" && <div className="fm-period-profile-note" aria-live="polite">{profileCopy[profile]}</div>}
  </section>;
}
