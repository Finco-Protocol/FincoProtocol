// WS-2 / M-007, M-010 — CAPEX / OPEX line items as a compact, keyboard-first grid.
//
// Replaces the former table that repeated `State` / `Notes` columns on every row.  Behaviour:
//   * Enter / ArrowDown / ArrowUp / Tab / Shift+Tab / Escape and TSV paste (see grid.ts);
//   * staged edits live in the shared pending-change store (ChangesProvider), so the Changes
//     drawer, undo/redo and navigation between sections see the same drafts;
//   * "Save" here is this sheet's existing all-or-none line writer
//     (POST /v2/workbook/grid/cost-lines/save).  It is NOT Save All: a cross-section
//     transaction needs the gated endpoint (see saveAll.ts).  The model is never run.
// Row notes stay available behind a disclosure; derived/committed status text is gone.

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import "../../styles/ws2-editing.css";
import { fetchCostLines, saveCostLinesBatch } from "../api";
import { buildCostLineEdits, classifyBatchAttempt, sameDecimalText, type CostLineEditWire } from "../costLinePayload";
import { friendlyMessage } from "../productLanguage";
import type { CostLinePayload, CostLinesPayload } from "../types";
import { CostLineManager } from "../workflow/CostLineManager";
import { useLeaveGuard, useReportDirty, useReportPending, useSingleFlight } from "../workflow/workflowShared";
import { EnsureChangesProvider, useChanges } from "./ChangesProvider";
import { sumDecimals } from "./decimal";
import { numberValidator, type CellValidator, type GridModel, type PasteAssignment } from "./grid";
import type { EditSection, StageInput } from "./pendingEdits";
import { useGridKeys } from "./useGridKeys";

type Sheet = "capex" | "opex";
type Status = { tone: "ok" | "error" | "conflict"; text: string } | null;

const COLUMNS_CAPEX = ["label", "amount"] as const;
const COLUMNS_OPEX = ["label", "amount", "inflation"] as const;

const textOf = (value: number | string | null | undefined) => (value === null || value === undefined ? "" : String(value));
const labelValidator: CellValidator = (text) => (text.trim() ? { ok: true, value: text } : { ok: false, message: "Description is required." });
const amountValidator = numberValidator({ allowNegative: false });
const inflationValidator = numberValidator({ allowNegative: true });

export function CostLinesGridView(props: { project: string; reloadKey?: number; onMutated?: () => void; requestedSheet?: Sheet; requestNonce?: number }) {
  return <EnsureChangesProvider identity={null}><CostLinesGrid {...props} /></EnsureChangesProvider>;
}

function CostLinesGrid({ project, reloadKey = 0, onMutated, requestedSheet, requestNonce = 0 }: {
  project: string; reloadKey?: number; onMutated?: () => void; requestedSheet?: Sheet; requestNonce?: number;
}) {
  const [sheet, setSheet] = useState<Sheet>("capex");
  const [data, setData] = useState<CostLinesPayload | null>(null);
  const [loadError, setLoadError] = useState("");
  const [status, setStatus] = useState<Status>(null);
  const [inFlight, setInFlight] = useState(false);
  const [unknownBatch, setUnknownBatch] = useState<CostLineEditWire[] | null>(null);
  const changes = useChanges();
  const confirmIfDirty = useLeaveGuard();
  const singleFlight = useSingleFlight();
  const live = useRef(0);

  const load = useCallback(async () => {
    const mine = ++live.current;
    const result = await fetchCostLines(project, sheet);
    if (mine !== live.current) return;
    if (!result || (result as { ok?: unknown }).ok !== true) {
      setLoadError(friendlyMessage((result as { code?: string })?.code, (result as { message?: string })?.message, "This could not be loaded right now. Nothing was changed."));
      return;
    }
    setLoadError(""); setData(result as CostLinesPayload);
  }, [project, sheet]);

  useEffect(() => { setData(null); setStatus(null); setUnknownBatch(null); void load(); }, [load]);
  useEffect(() => { if (reloadKey > 0) void load(); }, [reloadKey, load]);

  const lastRequest = useRef(requestNonce);
  useEffect(() => {
    if (!requestedSheet || requestNonce === lastRequest.current) return;
    lastRequest.current = requestNonce;
    if (requestedSheet !== sheet) confirmIfDirty(() => setSheet(requestedSheet), { ignore: (key) => !key.startsWith("cost-") });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestedSheet, requestNonce]);

  const section: EditSection = sheet;
  const mine = changes.edits.filter((e) => e.section === section);
  // One dirty count per staged LINE so the shell's leave guard reads the same number the old editor reported.
  const stagedLines = new Set(mine.map((e) => e.key.split("#")[0])).size;
  useReportDirty(`cost-lines-${sheet}`, stagedLines);
  useReportPending(`cost-lines-${sheet}`, inFlight);

  const columns = sheet === "opex" ? COLUMNS_OPEX : COLUMNS_CAPEX;
  const lines = data?.lines ?? [];
  const readOnlyProject = data?.project.protected_reference ?? true;
  const locked = inFlight || unknownBatch !== null;
  const editableLine = (line: CostLinePayload) => line.active && !readOnlyProject && !locked;

  const model = useMemo<GridModel>(() => ({
    columns,
    rows: lines.map((line) => ({ id: line.sub_line_id, editable: Object.fromEntries(columns.map((c) => [c, editableLine(line)])) })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [lines, columns, readOnlyProject, locked]);

  const validators: Record<string, CellValidator> = { label: labelValidator, amount: amountValidator, inflation: inflationValidator };

  const baselineOf = (line: CostLinePayload, col: string) =>
    col === "label" ? line.label : col === "amount" ? textOf(line.amount_keur) : textOf(line.inflation_pct);

  const valueOf = (line: CostLinePayload, col: string) =>
    changes.get(section, `${line.sub_line_id}#${col}`)?.value ?? baselineOf(line, col);

  const stageInput = (line: CostLinePayload, col: string, typed: string): StageInput => {
    const verdict = validators[col](typed);
    const baseline = baselineOf(line, col);
    const equal = col === "label" ? typed === baseline : sameDecimalText(typed.trim(), baseline);
    return {
      section, key: `${line.sub_line_id}#${col}`,
      label: `${line.label} — ${col === "label" ? "description" : col === "amount" ? "amount" : "inflation"}`,
      unit: col === "amount" ? "kEUR" : col === "inflation" ? "%" : "",
      baseline, value: equal ? baseline : typed, rowVersion: line.row_version,
      canonical: verdict.ok && !equal ? verdict.value : undefined,
      error: verdict.ok || equal ? undefined : verdict.message,
      meta: { label: line.label, amount_keur: textOf(line.amount_keur), notes: line.notes ?? "" },
    };
  };

  const container = useRef<HTMLDivElement>(null);
  const [pasteNote, setPasteNote] = useState("");
  const keys = useGridKeys(container, {
    model, validators,
    restore: (rowId, colId, value) => {
      const line = lines.find((l) => l.sub_line_id === rowId);
      if (line) changes.stage(stageInput(line, colId, value));
    },
    applyPaste: (assignments: PasteAssignment[]) => {
      changes.stageMany(assignments.flatMap((a) => {
        const line = lines.find((l) => l.sub_line_id === a.rowId);
        return line ? [stageInput(line, a.colId, a.value)] : [];
      }));
      setPasteNote(`Pasted ${assignments.length} cell${assignments.length === 1 ? "" : "s"}. Nothing is saved yet.`);
    },
    rejectPaste: (plan) => setPasteNote(`Paste rejected, nothing was changed: ${plan.errors[0].message}${plan.errors.length > 1 ? ` (+${plan.errors.length - 1} more)` : ""}`),
    undo: changes.undo, redo: changes.redo,
  });

  const stagedPatch = () => {
    const patch: Record<string, { label?: string; amount_keur?: string; inflation_pct?: string; notes?: string }> = {};
    for (const edit of mine) {
      const [id, col] = edit.key.split("#");
      const entry = patch[id] ?? (patch[id] = {});
      const submit = edit.canonical ?? edit.value;
      if (col === "label") entry.label = edit.value;
      else if (col === "amount") entry.amount_keur = submit;
      else if (col === "inflation") entry.inflation_pct = submit;
      else if (col === "notes") entry.notes = edit.value;
    }
    return patch;
  };

  const save = () => singleFlight(async () => {
    if (!data || inFlight || mine.length === 0) return;
    if (changes.invalidCount > 0) { setStatus({ tone: "error", text: "Fix the highlighted values first. Nothing was saved." }); return; }
    const built = buildCostLineEdits(sheet, stagedPatch(), data.lines);
    if (!built.ok) { setStatus({ tone: "error", text: built.message }); return; }
    setInFlight(true); setStatus(null);
    const result = await saveCostLinesBatch({ saveUrl: data.save.url, project, csrfToken: data.save.csrf_token, workbookVersion: data.save.workbook_version, contentHash: data.save.content_hash, sheet, edits: built.edits });
    if ("kind" in result) {
      if (result.kind === "unknown") setUnknownBatch(built.edits);
      setStatus({ tone: "conflict", text: result.message });
    } else if (result.ok) {
      setStatus({ tone: "ok", text: `${result.savedCount} line(s) saved atomically. The model was not run; results are outdated until the next Run.` });
      for (const edit of mine) changes.revert(edit.id);
      await load(); onMutated?.();
    } else setStatus({ tone: "error", text: result.message });
    setInFlight(false);
  });

  const reconcile = async () => {
    if (!unknownBatch) return;
    setInFlight(true);
    setStatus({ tone: "conflict", text: "Checking the saved lines on the server…" });
    const fresh = await fetchCostLines(project, sheet);
    if (!fresh || (fresh as { ok?: unknown }).ok !== true) {
      setInFlight(false);
      setStatus({ tone: "error", text: "The saved lines could not be read. Nothing was changed; check the connection and try again." });
      return;
    }
    const verdict = classifyBatchAttempt(unknownBatch, (fresh as CostLinesPayload).lines);
    setUnknownBatch(null);
    await load(); onMutated?.();
    if (verdict === "committed") {
      for (const edit of mine) changes.revert(edit.id);
      setStatus({ tone: "ok", text: "Reconciled: this batch had been committed on the server. It was not sent twice and the model was not run." });
    } else if (verdict === "not_committed") setStatus({ tone: "ok", text: "Reconciled: the batch did not reach the server, so nothing changed. Your edits are kept — press Save to retry." });
    else setStatus({ tone: "conflict", text: "Reconciled: some lines changed elsewhere. Your edits are kept; review them, then Save against the latest version." });
    setInFlight(false);
  };

  const switchSheet = (next: Sheet) => { if (next !== sheet) confirmIfDirty(() => setSheet(next), { ignore: (key) => !key.startsWith("cost-") }); };
  const headingId = useId();

  if (!data) return loadError
    ? <div className="fm-banner" role="alert"><span className="fm-demo-label">UNAVAILABLE</span><span className="fm-banner-copy">{loadError}</span><button type="button" className="fm-btn" onClick={() => void load()}>Retry</button></div>
    : <p className="fm-info-note" role="status">Loading…</p>;

  const total = sumDecimals(lines.filter((l) => l.active).map((l) => valueOf(l, "amount")));
  const title = sheet === "capex" ? "CAPEX" : "OPEX";

  return (
    <section className="fm-card fm-section" aria-labelledby={headingId} data-cost-grid={sheet}>
      <div className="fm-card-title">
        <h2 id={headingId}>{sheet === "capex" ? "CAPEX construction plan" : "OPEX operating profile"}</h2>
        <span className="fm-toolbar">
          <button type="button" className={`fm-btn ${sheet === "capex" ? "fm-btn-primary" : ""}`} aria-pressed={sheet === "capex"} onClick={() => switchSheet("capex")}>CAPEX</button>
          <button type="button" className={`fm-btn ${sheet === "opex" ? "fm-btn-primary" : ""}`} aria-pressed={sheet === "opex"} onClick={() => switchSheet("opex")}>OPEX</button>
        </span>
      </div>
      <p className="rx-save-scope" data-save-scope="cost-lines">
        <strong>Saves:</strong> every edited {title} line, together — all are saved or none. Saving does not run the model.
        {" "}Edits stay staged while you move between sections and are listed under <em>Changes</em>.
      </p>
      <p className="ws2-grid-keys rx-note">Enter or ↓ next row · ↑ previous · Tab next cell · Esc cancels the cell · paste a block from Excel · Ctrl+Z / Ctrl+Y undo / redo.</p>
      {readOnlyProject && <div className="fm-banner" role="note"><span className="fm-demo-label">READ-ONLY TEMPLATE</span><span className="fm-banner-copy">Read-only. Line items of a reference are immutable.</span></div>}
      {status && <div className="fm-info-note" role={status.tone === "ok" ? "status" : "alert"} data-tone={status.tone}>{status.text}</div>}
      {pasteNote && <div className="fm-info-note" role="status" data-paste-note="true">{pasteNote}</div>}
      <div ref={container} className="fm-table-wrap rx-lines-scroll" role="region" tabIndex={0} aria-label={`${title} line items, scrollable`} data-lines-scroll={sheet}>
        <table className="fm-table ws2-grid">
          <caption className="fm-sr-only">{title} line items. Amounts in kEUR.</caption>
          <thead><tr><th scope="col">Line</th><th scope="col">Amount (kEUR)</th>{sheet === "opex" && <th scope="col">Inflation (%)</th>}</tr></thead>
          <tbody>
            {lines.map((line, r) => {
              const rowEditable = editableLine(line);
              return (
                <tr key={line.sub_line_id} data-inactive={!line.active || undefined} data-line={line.sub_line_id}>
                  {columns.map((col, c) => {
                    const edit = changes.get(section, `${line.sub_line_id}#${col}`);
                    const value = valueOf(line, col);
                    const errorId = `${headingId}-${r}-${c}-err`;
                    const label = `${col === "label" ? "Description" : col === "amount" ? "Amount (kEUR)" : "Inflation (%)"} for ${line.label}`;
                    return (
                      <td key={col}>
                        <input className={`fm-input ws2-cell ${col === "label" ? "ws2-cell-text" : ""}`} type="text"
                               inputMode={col === "label" ? "text" : "decimal"} autoComplete="off" spellCheck={false}
                               aria-label={label} aria-invalid={edit?.error ? true : undefined} aria-describedby={edit?.error ? errorId : undefined}
                               data-r={r} data-c={c} data-changed={edit ? "true" : undefined}
                               value={value} disabled={!rowEditable}
                               onFocus={keys.onFocus} onKeyDown={keys.onKeyDown} onPaste={keys.onPaste}
                               onChange={(event) => { setStatus(null); setPasteNote(""); changes.stage(stageInput(line, col, event.target.value), { coalesce: true }); }} />
                        {edit?.error && <small id={errorId} className="ws2-cell-error" role="alert">{edit.error}</small>}
                        {col === "label" && (
                          <details className="ws2-row-notes">
                            <summary>{line.active ? "Notes" : "Notes · inactive line"}</summary>
                            <input className="fm-input" aria-label={`Notes for ${line.label}`} disabled={!rowEditable}
                                   value={changes.get(section, `${line.sub_line_id}#notes`)?.value ?? (line.notes ?? "")}
                                   onChange={(event) => changes.stage({
                                     section, key: `${line.sub_line_id}#notes`, label: `${line.label} — notes`, unit: "", baseline: line.notes ?? "",
                                     value: event.target.value, rowVersion: line.row_version, meta: { label: line.label, amount_keur: textOf(line.amount_keur) },
                                   }, { coalesce: true })} />
                          </details>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
            {!lines.length && <tr><td colSpan={columns.length}><span role="status">No line items were projected for this sheet.</span></td></tr>}
          </tbody>
          {lines.length > 0 && total !== null && (
            <tfoot><tr className="ws2-grid-total"><th scope="row">Sum of line amounts (kEUR, as shown — not a model result)</th><td data-lines-sum="true" style={{ textAlign: "right" }}>{total}</td>{sheet === "opex" && <td />}</tr></tfoot>
          )}
        </table>
      </div>
      <div className="fm-toolbar" style={{ marginTop: 10 }}>
        <button type="button" className="fm-btn fm-btn-primary" data-cost-save="true" disabled={locked || !stagedLines || readOnlyProject || changes.invalidCount > 0} onClick={() => void save()}>
          Save {stagedLines || ""} edited line{stagedLines === 1 ? "" : "s"} atomically
        </button>
        <button type="button" className="fm-btn" disabled={locked || !mine.length} onClick={() => changes.revertSection(section)}>Discard staged edits</button>
        <button type="button" className="fm-btn" disabled={!changes.canUndo} onClick={changes.undo}>Undo</button>
        <button type="button" className="fm-btn" disabled={!changes.canRedo} onClick={changes.redo}>Redo</button>
        {unknownBatch !== null && <button type="button" className="fm-btn" disabled={inFlight} data-cost-reconcile="true" onClick={() => void reconcile()}>Check saved state</button>}
      </div>
      <p className="fm-info-note">If someone else changed one of these lines in the meantime, nothing is saved and you are asked to reload before saving again. Saving never runs the model.</p>
      <CostLineManager key={sheet} project={project} data={data} onChanged={() => { void load(); onMutated?.(); }} />
    </section>
  );
}
