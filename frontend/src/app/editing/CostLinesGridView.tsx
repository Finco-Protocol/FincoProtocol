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

import { Fragment, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import "../../styles/ws2-editing.css";
import { fetchCostLines, saveCostLinesBatch } from "../api";
import { buildCostLineEdits, classifyBatchAttempt, sameDecimalText, type CostLineEditWire } from "../costLinePayload";
import { friendlyMessage } from "../productLanguage";
import type { CostLinePayload, CostLinesPayload } from "../types";
import { CostLineManager, costGroupLabel } from "../workflow/CostLineManager";
import { useLeaveGuard, useReportDirty, useReportPending, useSingleFlight } from "../workflow/workflowShared";
import { EnsureChangesProvider, useChanges } from "./ChangesProvider";
import { sumDecimals } from "./decimal";
import { useDensity } from "../uiDensity";
import { numberValidator, type CellValidator, type GridModel, type PasteAssignment } from "./grid";
import type { EditSection, StageInput } from "./pendingEdits";
import { useGridKeys } from "./useGridKeys";

type Sheet = "capex" | "opex";
const MAPPING_NOTE: Record<string, string> = {
  UNRESOLVED: "This group is still to be confirmed. Active saved lines here are still used by the model exactly as before.",
  DERIVED: "Calculated by the model when it runs — not an editable cost line.",
};
type Status = { tone: "ok" | "error" | "conflict"; text: string } | null;

const COLUMNS_CAPEX = ["label", "amount"] as const;
const COLUMNS_OPEX = ["label", "amount", "inflation"] as const;

const textOf = (value: number | string | null | undefined) => (value === null || value === undefined ? "" : String(value));
const labelValidator: CellValidator = (text) => (text.trim() ? { ok: true, value: text } : { ok: false, message: "Description is required." });
const amountValidator = numberValidator({ allowNegative: false });
const inflationValidator = numberValidator({ allowNegative: true });

export function CostLinesGridView(props: { project: string; reloadKey?: number; onMutated?: () => void; requestedSheet?: Sheet; requestNonce?: number; query?: string; scenarioName?: string }) {
  return <EnsureChangesProvider identity={null}><CostLinesGrid {...props} /></EnsureChangesProvider>;
}

function useNarrow(query = "(max-width: 900px)") {
  const get = () => (typeof window !== "undefined" && typeof window.matchMedia === "function" ? window.matchMedia(query).matches : false);
  const [narrow, setNarrow] = useState(get);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return undefined;
    const mq = window.matchMedia(query);
    const on = () => setNarrow(mq.matches);
    mq.addEventListener("change", on);
    on();
    return () => mq.removeEventListener("change", on);
  }, [query]);
  return narrow;
}

type ColId = "code" | "line" | "basis" | "qty" | "unit" | "amount" | "perMw" | "cont" | "vat" | "wht" | "dep" | "infl" | "year" | "profile" | "status" | "menu";
type LineFilter = "all" | "nonzero" | "changed" | "inactive";
const FILTERS: ReadonlyArray<{ id: LineFilter; label: string }> = [
  { id: "all", label: "All" }, { id: "nonzero", label: "Non-zero" }, { id: "changed", label: "Changed" }, { id: "inactive", label: "Calculated / unsupported" },
];

function CostLinesGrid({ project, reloadKey = 0, onMutated, requestedSheet, requestNonce = 0, query = "", scenarioName = "Base Case" }: {
  project: string; reloadKey?: number; onMutated?: () => void; requestedSheet?: Sheet; requestNonce?: number; query?: string; scenarioName?: string;
}) {
  const [sheet, setSheet] = useState<Sheet>("capex");
  const [data, setData] = useState<CostLinesPayload | null>(null);
  const [loadError, setLoadError] = useState("");
  const [status, setStatus] = useState<Status>(null);
  const [inFlight, setInFlight] = useState(false);
  const [density, toggleDensity] = useDensity();
  const narrow = useNarrow();
  const [extended, setExtended] = useState(false);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState<LineFilter>("all");
  const [localQuery, setLocalQuery] = useState("");
  const [profiles, setProfiles] = useState<{ custom: Set<string> } | null>(null);
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

  useEffect(() => {
    setProfiles(null);
    if (sheet !== "capex") return undefined;
    const controller = new AbortController();
    void (async () => {
      try {
        const r = await fetch(`/v2/model-react/capex/profiles?project=${encodeURIComponent(project)}`, { credentials: "same-origin", cache: "no-store", signal: controller.signal, headers: { Accept: "application/json" } });
        const body = await r.json() as { ok?: boolean; saved?: { rows?: Record<string, unknown> } };
        if (!controller.signal.aborted && r.ok && body.ok) setProfiles({ custom: new Set(Object.keys(body.saved?.rows ?? {})) });
      } catch { /* the column then shows a dash: it is optional context */ }
    })();
    return () => controller.abort();
  }, [project, sheet, reloadKey]);

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
  const baselineOf = (line: CostLinePayload, col: string) =>
    col === "label" ? line.label : col === "amount" ? textOf(line.amount_keur) : textOf(line.inflation_pct);

  const valueOf = (line: CostLinePayload, col: string) =>
    changes.get(section, `${line.sub_line_id}#${col}`)?.value ?? baselineOf(line, col);

  const allLines = data?.lines ?? [];
  const projection = data?.projection ?? null;
  const groupInfo = new Map((projection?.groups ?? []).map((g) => [g.code, g]));
  const lineInfo = new Map((projection?.lines ?? []).map((l) => [l.sub_line_id, l]));
  const needle = (localQuery || query).trim().toLowerCase();
  const isChanged = (line: CostLinePayload) => mine.some((e) => e.key.split("#")[0] === line.sub_line_id);
  const filtered = allLines.filter((line) => {
    if (needle) {
      const hay = `${lineInfo.get(line.sub_line_id)?.finco_display_code ?? ""} ${line.label} ${line.category}`.toLowerCase();
      if (!hay.includes(needle) && !isChanged(line)) return false;
    }
    if (filter === "nonzero") return Number(valueOf(line, "amount")) !== 0;
    if (filter === "changed") return isChanged(line);
    if (filter === "inactive") return !line.active || lineInfo.get(line.sub_line_id)?.mapping_status === "UNRESOLVED";
    return true;
  });
  const lines = filtered.filter((l) => !collapsed.has(l.category));
  const readOnlyProject = data?.project.protected_reference ?? true;
  const locked = inFlight || unknownBatch !== null;
  const editableLine = (line: CostLinePayload) => line.active && !readOnlyProject && !locked;

  const model = useMemo<GridModel>(() => ({
    columns,
    rows: lines.map((line) => ({ id: line.sub_line_id, editable: Object.fromEntries(columns.map((c) => [c, editableLine(line)])) })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [lines, columns, readOnlyProject, locked]);

  const validators: Record<string, CellValidator> = { label: labelValidator, amount: amountValidator, inflation: inflationValidator };

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

  const cols: ColId[] = narrow
    ? (sheet === "capex" ? ["line", "amount"] : ["line", "amount", "infl"])
    : sheet === "capex"
      ? ["code", "line", "basis", "qty", "unit", "amount", "perMw", ...(extended ? (["cont", "vat", "wht", "dep"] as ColId[]) : []), "profile", "status", "menu"]
      : ["code", "line", "amount", "basis", "infl", "year", "status", ...(extended ? (["wht"] as ColId[]) : []), "menu"];
  const amountAt = cols.indexOf("amount");
  const total = sumDecimals(allLines.filter((l) => l.active).map((l) => valueOf(l, "amount")));
  const fmtKeur = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: 2 });
  const title = sheet === "capex" ? "CAPEX" : "OPEX";
  const groupOrder = Array.from(new Set(filtered.map((l) => l.category)));
  const NOT_CONNECTED = "Not connected to the model yet";

  const inputTd = (line: CostLinePayload, col: "label" | "amount" | "inflation", r: number, c: number) => {
    const rowEditable = editableLine(line);
    const edit = changes.get(section, `${line.sub_line_id}#${col}`);
    const value = valueOf(line, col);
    const errorId = `${headingId}-${r}-${c}-err`;
    const label = `${col === "label" ? "Label" : col === "amount" ? "Amount" : "Inflation"} for ${line.label}`;   // the original editor's accessible names
    const code = col === "label" ? lineInfo.get(line.sub_line_id)?.finco_display_code : undefined;
    const field = (
      <input className={`fm-input ws2-cell ${col === "label" ? "ws2-cell-text" : ""}`} type="text"
        inputMode={col === "label" ? "text" : "decimal"} autoComplete="off" spellCheck={false}
        aria-label={label} aria-invalid={edit?.error ? true : undefined} aria-describedby={edit?.error ? errorId : undefined}
        data-r={r} data-c={c} data-changed={edit ? "true" : undefined}
        value={value} disabled={!rowEditable}
        onFocus={keys.onFocus} onKeyDown={keys.onKeyDown} onPaste={keys.onPaste}
        onChange={(event) => { setStatus(null); setPasteNote(""); changes.stage(stageInput(line, col, event.target.value), { coalesce: true }); }} />
    );
    const notesBlock = col === "label" ? (
      <details className="ws2-row-notes">
        <summary>{line.active ? "Notes" : "Notes · inactive line"}</summary>
        <input className="fm-input" aria-label={`Notes for ${line.label}`} disabled={!rowEditable}
               value={changes.get(section, `${line.sub_line_id}#notes`)?.value ?? (line.notes ?? "")}
               onChange={(event) => changes.stage({
                 section, key: `${line.sub_line_id}#notes`, label: `${line.label} — notes`, unit: "", baseline: line.notes ?? "",
                 value: event.target.value, rowVersion: line.row_version, meta: { label: line.label, amount_keur: textOf(line.amount_keur) },
               }, { coalesce: true })} />
      </details>
    ) : null;
    return (
      <td key={col} className={col === "label" ? "ci-col-line" : col === "amount" ? "ci-col-amount" : undefined}>
        {col === "label"
          ? <div className="ws2-label-wrap">{code && <span className="ws2-code" data-finco-code="true" aria-hidden="true">{code}</span>}{field}{notesBlock}</div>
          : field}
        {edit?.error && <small id={errorId} className="ws2-cell-error" role="alert">{edit.error}</small>}
      </td>
    );
  };

  const staticTd = (id: ColId, line: CostLinePayload) => {
    const info = lineInfo.get(line.sub_line_id);
    switch (id) {
      case "code": return <td key={id} className="ci-col-code"><span className="ws2-code" data-finco-code-col="true">{info?.finco_display_code}</span></td>;
      case "basis": return <td key={id} className="ci-col-basis ci-off" title={`Every line is a fixed amount in kEUR today. ${NOT_CONNECTED}.`}>
        <select disabled aria-label={`Basis for ${line.label} (not connected yet)`} className="ci-offselect"><option>fixed</option><option>per MW</option></select></td>;
      case "qty": case "unit": return <td key={id} className="ci-off ci-num" title={NOT_CONNECTED}>
        <input disabled className="ci-offinput" placeholder="—" aria-label={`${id === "qty" ? "Quantity" : "Unit price"} for ${line.label} (not connected yet)`} /></td>;
      case "perMw": return <td key={id} className="ci-off ci-num" title={NOT_CONNECTED}>—</td>;
      case "cont": case "vat": case "wht": case "dep": return <td key={id} className="ci-off ci-num" title={NOT_CONNECTED}>—</td>;
      case "year": return <td key={id} className="ci-off" title="The same amount applies every year, inflated as shown. A different amount per year is not connected yet.">
        <span className="ci-yearbar" role="img" aria-label="Same amount every year" /></td>;
      case "profile": return (
        <td key={id} className="ci-col-profile" data-cost-profile={line.sub_line_id}>
          {profiles === null ? "—" : (
            <button type="button" className="ci-link ci-profile" title="Open the spending profile (Studios)"
                    onClick={() => document.getElementById("wf-inputs-studios")?.scrollIntoView({ block: "start" })}>
              {profiles.custom.has(info?.finco_display_code ?? "") ? "Custom profile" : "Even over construction"} ▸
            </button>)}
        </td>);
      case "status": return (
        <td key={id} className="ci-col-status" data-cost-status={line.sub_line_id}>
          {!line.active ? <span className="ws2-chip">Inactive</span>
            : isChanged(line) ? <span className="ws2-chip ws2-chip-changed">Changed</span>
            : info?.mapping_status === "UNRESOLVED" ? <span className="ws2-chip" data-mapping-status="UNRESOLVED" title={MAPPING_NOTE.UNRESOLVED}>To be confirmed</span>
            : editableLine(line) ? <span className="ws2-chip ws2-chip-ok">Editable</span> : <span className="ws2-chip">Locked</span>}
        </td>);
      case "menu": return <td key={id} className="ci-col-menu"><button type="button" className="ci-menu" disabled aria-label={`Actions for ${line.label} (not connected yet)`} title={NOT_CONNECTED}>…</button></td>;
      default: return <td key={id} />;
    }
  };

  const HEAD: Record<ColId, string> = { code: "Code", line: "Line", basis: "Basis", qty: "Qty", unit: "Unit price", amount: "Amount (kEUR)", perMw: "K€/MW", cont: "Cont.", vat: "VAT", wht: "WHT", dep: "Dep.", infl: "Inflation (%)", year: "Year profile", profile: "Payment profile", status: "Status", menu: "" };
  const OFF: ReadonlySet<ColId> = new Set<ColId>(["basis", "qty", "unit", "perMw", "cont", "vat", "wht", "dep", "year", "menu"]);
  let rowIndex = 0;

  return (
    <section className="fm-card fm-section" aria-label={`${title} line items`} data-cost-grid={sheet} data-density={density}>
      <div className="fm-card-title ci-detail-head">
        <h2 id={headingId}>{title} — all lines</h2>
        <span className="ci-detail-sub" data-cost-subtitle="true">{allLines.length} lines · scenario {scenarioName}</span>
        <span className="fm-toolbar">
          <button type="button" className="fm-btn" data-cost-back="true" onClick={() => document.querySelector("[data-ci-summaries]")?.scrollIntoView({ block: "start" })}>← Back to {title} summary</button>
          <button type="button" className={`fm-btn ${sheet === "capex" ? "fm-btn-primary" : ""}`} aria-pressed={sheet === "capex"} onClick={() => switchSheet("capex")}>CAPEX</button>
          <button type="button" className={`fm-btn ${sheet === "opex" ? "fm-btn-primary" : ""}`} aria-pressed={sheet === "opex"} onClick={() => switchSheet("opex")}>OPEX</button>
          <button type="button" className="fm-btn" aria-pressed={density === "compact"} data-density-toggle="true" onClick={toggleDensity}>Compact rows</button>
        </span>
      </div>
      <p className="rx-save-scope" data-save-scope="cost-lines">
        <strong>Saves:</strong> every edited {title} line below, together — all are saved or none. Saving does not run the model.
        {" "}Edits stay staged while you move between sections and are listed under <em>Changes</em>.
      </p>
      <p className="ws2-grid-keys rx-note">Enter or ↓ next row · ↑ previous · Tab next cell · Esc cancels the cell · paste a block from Excel · Ctrl+Z / Ctrl+Y undo / redo. Greyed-out columns are not connected to the model yet.</p>
      {readOnlyProject && <div className="fm-banner" role="note"><span className="fm-demo-label">READ-ONLY TEMPLATE</span><span className="fm-banner-copy">Read-only. Line items of a reference are immutable.</span></div>}
      {status && <div className="fm-info-note" role={status.tone === "ok" ? "status" : "alert"} data-tone={status.tone}>{status.text}</div>}
      {pasteNote && <div className="fm-info-note" role="status" data-paste-note="true">{pasteNote}</div>}
      <div className="ci-linebar" data-ci-linebar="true">
        <input type="search" className="fm-input ci-linesearch" data-cost-search="true" value={localQuery} placeholder="Search code, line or group…"
               aria-label={`Search ${title} lines`} onChange={(e) => setLocalQuery(e.target.value)} />
        <span className="ci-filters" role="group" aria-label="Show lines">
          {FILTERS.map((f) => (
            <button key={f.id} type="button" className="fm-btn ci-filter" aria-pressed={filter === f.id} data-cost-filter={f.id} onClick={() => setFilter(f.id)}>{f.label}</button>
          ))}
        </span>
        <span className="ci-filters" role="group" aria-label="Columns">
          <button type="button" className="fm-btn ci-filter" aria-pressed={!extended} data-cost-columns="basic" onClick={() => setExtended(false)}>Basic</button>
          <button type="button" className="fm-btn ci-filter" aria-pressed={extended} data-cost-columns="extended" onClick={() => setExtended(true)}>{sheet === "capex" ? "+ Cont./VAT/WHT/Dep." : "+ WHT"}</button>
        </span>
        <button type="button" className="fm-btn ci-addline" data-cost-addline="true" disabled={readOnlyProject}
                onClick={() => { const m = document.querySelector<HTMLElement>(`[data-cost-line-manager="${sheet}"]`); m?.scrollIntoView({ block: "center" }); m?.querySelector<HTMLElement>("select, input")?.focus({ preventScroll: true }); }}>
          + Add line
        </button>
        <button type="button" className="fm-btn" data-cost-expand="true" onClick={() => setCollapsed(collapsed.size ? new Set() : new Set(groupOrder))}>{collapsed.size ? "Expand all" : "Collapse all"}</button>
        <span className="ci-shown" data-cost-shown="true" role="status">{filtered.length} of {allLines.length} lines shown</span>
      </div>
      <div ref={container} className="fm-table-wrap rx-lines-scroll" role="region" tabIndex={0} aria-label={`${title} line items, scrollable`} data-lines-scroll={sheet}>
        <table className="fm-table ws2-grid">
          <caption className="fm-sr-only">{title} line items. Amounts in kEUR.</caption>
          <thead><tr>{cols.map((id) => (
            <th key={id} scope="col" className={`ci-h-${id}${OFF.has(id) ? " ci-off" : ""}${id === "amount" || id === "perMw" || id === "qty" || id === "unit" ? " ci-num" : ""}`}
                title={OFF.has(id) && HEAD[id] ? NOT_CONNECTED : undefined}>{HEAD[id]}</th>))}</tr></thead>
          <tbody>
            {groupOrder.map((cat) => {
              const g = groupInfo.get(cat);
              const isCollapsed = collapsed.has(cat);
              const members = filtered.filter((l) => l.category === cat);
              return (
                <Fragment key={cat}>
                  <tr className="ws2-group-row" data-group-row={cat}>
                    <th scope="colgroup" colSpan={Math.max(amountAt, 1)}>
                      <button type="button" className="ci-twisty" aria-expanded={!isCollapsed} aria-label={`${isCollapsed ? "Expand" : "Collapse"} ${cat}`} data-cost-twisty={cat}
                              onClick={() => { const next = new Set(collapsed); if (isCollapsed) next.delete(cat); else next.add(cat); setCollapsed(next); }} />
                      <span className="ws2-group-name">{costGroupLabel(cat, data.line_management?.eligible_groups ?? [])}</span>
                      <span className="ws2-group-meta" data-group-meta={cat}>
                        <span className="ci-n">{members.length} line{members.length === 1 ? "" : "s"}</span>
                        {g && g.mapping_status !== "PROVEN" && <span className="ws2-chip" data-mapping-status={g.mapping_status} title={MAPPING_NOTE[g.mapping_status]}>{g.mapping_status === "DERIVED" ? "Calculated" : "To be confirmed"}</span>}
                      </span>
                    </th>
                    <td className="ci-num ci-gtotal" data-group-saved-total={g && g.saved_total_keur !== null ? cat : undefined}>{g && g.saved_total_keur !== null ? fmtKeur(g.saved_total_keur) : ""}</td>
                    {cols.length - amountAt - 1 > 0 && (
                      <td colSpan={cols.length - amountAt - 1} className="ci-gaction">
                        <button type="button" className="ci-link" disabled={readOnlyProject} data-cost-group-add={cat}
                                onClick={() => { const m = document.querySelector<HTMLElement>(`[data-cost-line-manager="${sheet}"]`); m?.scrollIntoView({ block: "center" }); m?.querySelector<HTMLElement>("select, input")?.focus({ preventScroll: true }); }}>+ line</button>
                      </td>)}
                  </tr>
                  {!isCollapsed && members.map((line) => {
                    const r = rowIndex++;
                    return (
                      <tr key={line.sub_line_id} data-inactive={!line.active || undefined} data-stale={!line.active || undefined} data-line={line.sub_line_id}>
                        {cols.map((id) => id === "line" ? inputTd(line, "label", r, 0)
                          : id === "amount" ? inputTd(line, "amount", r, 1)
                          : id === "infl" ? inputTd(line, "inflation", r, 2)
                          : staticTd(id, line))}
                      </tr>
                    );
                  })}
                </Fragment>
              );
            })}
            {!lines.length && !groupOrder.length && <tr><td colSpan={cols.length}><span role="status">{allLines.length ? "No lines match this search or filter." : "No line items were projected for this sheet."}</span></td></tr>}
          </tbody>
          {allLines.length > 0 && total !== null && (
            <tfoot>
              <tr className="ws2-grid-total"><th scope="row" colSpan={Math.max(amountAt, 1)}>Sum of line amounts (kEUR, as shown — not a model result)</th><td data-lines-sum="true" className="ci-num">{total}</td>{cols.length - amountAt - 1 > 0 && <td colSpan={cols.length - amountAt - 1} />}</tr>
              {projection && <tr className="ws2-grid-total" data-saved-total-row="true"><th scope="row" colSpan={Math.max(amountAt, 1)}>Saved on the server (kEUR, sum of active saved lines — not a model result)</th><td data-saved-total="true" className="ci-num">{fmtKeur(projection.saved_total_keur)}</td>{cols.length - amountAt - 1 > 0 && <td colSpan={cols.length - amountAt - 1} />}</tr>}
            </tfoot>
          )}
        </table>
      </div>
      <div className="fm-toolbar" style={{ marginTop: 10 }}>
        <button type="button" className="fm-btn fm-btn-primary" data-cost-save="true" disabled={locked || !stagedLines || readOnlyProject || changes.invalidCount > 0} onClick={() => void save()}>
          Save {stagedLines || ""} staged line{stagedLines === 1 ? "" : "s"} atomically
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
