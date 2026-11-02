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

import { Fragment, useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import "../../styles/ws2-editing.css";
import { fetchCostLines, saveCostLinesBatch } from "../api";
import { buildCostLineEdits, classifyBatchAttempt, sameDecimalText, type CostLineEditWire } from "../costLinePayload";
import { friendlyMessage } from "../productLanguage";
import { divideDecimalText, perMwLabel, showKeur } from "../costAmounts";
import { OPEX_BASE_FIELD_BY_GROUP } from "../costGroupDisplay";
import { sectionOfField } from "./fieldSection";
import { useSaveAllBridge } from "../saveAllBridge";
import { CostUnitSelect, useCostUnit } from "../CostUnit";
import { useReportPrecision } from "../ReportPrecision";
import type { CostLinePayload, CostLinesPayload, GridRowPayload } from "../types";
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
/** What the CAPEX spending-profile document (the existing Studio's saved data) says for each item; absent item = no profile saved for it. */
type ProfileView = { rows: Record<string, { shape?: string; milestone?: string }>; broken: boolean };
const SHAPE_TEXT: Record<string, string> = { UNIFORM: "Even", FRONT_LOADED: "Front-loaded", BACK_LOADED: "Back-loaded", EXPLICIT: "Monthly % entered" };
function profileText(view: ProfileView, code: string): string {
  if (view.broken) return "Profile error";
  const row = view.rows[code];
  if (!row) return "Model default — end of construction period";
  if (row.shape === "MILESTONE") return row.milestone ? `One payment, month ${row.milestone}` : "One payment";
  return SHAPE_TEXT[row.shape ?? ""] ?? "Saved profile";
}
const openCapexStudio = () => {
  const tab = document.querySelector<HTMLElement>("[data-studio-tab='capex-profile']");
  if (tab && tab.getAttribute("aria-selected") !== "true") tab.click();
  (document.getElementById("wf-inputs-studios") ?? tab)?.scrollIntoView({ block: "start" });
  window.setTimeout(() => document.querySelector<HTMLElement>("[data-studio-tab='capex-profile']")?.focus({ preventScroll: true }), 0);
};

type Status = { tone: "ok" | "error" | "conflict"; text: string } | null;

const COLUMNS_CAPEX = ["label", "amount"] as const;
const COLUMNS_OPEX = ["label", "amount", "inflation"] as const;

const textOf = (value: number | string | null | undefined) => (value === null || value === undefined ? "" : String(value));
const labelValidator: CellValidator = (text) => (text.trim() ? { ok: true, value: text } : { ok: false, message: "Description is required." });
const amountValidator = numberValidator({ allowNegative: false });
const inflationValidator = numberValidator({ allowNegative: true });

export interface CostLinesGridProps {
  project: string; sheet: Sheet; reloadKey?: number; onMutated?: () => void; query?: string; scenarioName?: string;
  /** Switching CAPEX / OPEX is a route change owned by the workbench (it asks before leaving unsaved cost edits). */
  onSheet?: (next: Sheet) => void;
  /** OPEX only: the saved scalar base fields (same field ids and writer as the canonical cells) shown as the first row of their group. */
  baseRows?: ReadonlyArray<GridRowPayload>;
  /** Where the inline add-line form of the clicked group is drawn (a table cell this grid owns). */
}
export function CostLinesGridView(props: CostLinesGridProps) {
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

type ColId = "line" | "amount" | "perMw" | "infl" | "profile" | "status" | "menu";
type LineFilter = "all" | "nonzero" | "changed" | "inactive";
const FILTERS: ReadonlyArray<{ id: LineFilter; label: string }> = [
  { id: "all", label: "All" }, { id: "nonzero", label: "Non-zero" }, { id: "changed", label: "Changed" }, { id: "inactive", label: "Calculated / unsupported" },
];

function CostLinesGrid({ project, sheet, reloadKey = 0, onMutated, query = "", scenarioName = "Base Case", onSheet, baseRows = [] }: CostLinesGridProps) {
  const [data, setData] = useState<CostLinesPayload | null>(null);
  const [loadError, setLoadError] = useState("");
  const [status, setStatus] = useState<Status>(null);
  const [inFlight, setInFlight] = useState(false);
  const [density, toggleDensity] = useDensity();
  const narrow = useNarrow();
  const [loadedKey, setLoadedKey] = useState(-1);
  const [groupPreset, setGroupPreset] = useState<{ code: string; nonce: number } | null>(null);
  const [rowAction, setRowAction] = useState<{ lineId: string; active: boolean; nonce: number } | null>(null);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [addGroup, setAddGroup] = useState<string | null>(null);
  // An amount shows at the chosen report precision (default 0 decimals) while the cell is at rest; focusing it (or having typed in it) shows the
  // exact saved decimal text, which is what is staged and saved. Display precision never touches the stored value.
  const [focusedKey, setFocusedKey] = useState<string | null>(null);
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  const saveAll = useSaveAllBridge();
  const [unit] = useCostUnit();
  const { precision } = useReportPrecision();
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState<LineFilter>("all");
  const [localQuery, setLocalQuery] = useState("");
  const [profiles, setProfiles] = useState<ProfileView | null>(null);
  const [unknownBatch, setUnknownBatch] = useState<CostLineEditWire[] | null>(null);
  const changes = useChanges();
  const confirmIfDirty = useLeaveGuard();
  const singleFlight = useSingleFlight();
  const live = useRef(0);

  const wantedKey = useRef(reloadKey);
  wantedKey.current = reloadKey;
  const load = useCallback(async () => {
    const mine = ++live.current;
    const asked = wantedKey.current;
    const result = await fetchCostLines(project, sheet);
    if (mine !== live.current) return;
    if (!result || (result as { ok?: unknown }).ok !== true) {
      setLoadError(friendlyMessage((result as { code?: string })?.code, (result as { message?: string })?.message, "This could not be loaded right now. Nothing was changed."));
      return;
    }
    setLoadError(""); setData(result as CostLinesPayload); setLoadedKey(asked);
  }, [project, sheet]);

  useEffect(() => { setData(null); setLoadedKey(-1); setStatus(null); setUnknownBatch(null); void load(); }, [load]);
  useEffect(() => { if (reloadKey > 0) void load(); }, [reloadKey, load]);

  useEffect(() => {
    setProfiles(null);
    if (sheet !== "capex") return undefined;
    const controller = new AbortController();
    void (async () => {
      try {
        const r = await fetch(`/v2/model-react/capex/profiles?project=${encodeURIComponent(project)}`, { credentials: "same-origin", cache: "no-store", signal: controller.signal, headers: { Accept: "application/json" } });
        const body = await r.json() as { ok?: boolean; saved?: { rows?: Record<string, { shape?: string; milestone?: string }>; error?: string | null; binding?: { saved?: boolean; bound?: boolean } } };
        if (!controller.signal.aborted && r.ok && body.ok) {
          const binding = body.saved?.binding;
          setProfiles({ rows: body.saved?.rows ?? {}, broken: Boolean(body.saved?.error) || Boolean(binding?.saved && !binding.bound) });
        }
      } catch { /* the column then shows a dash: it is optional context */ }
    })();
    return () => controller.abort();
  }, [project, sheet, reloadKey]);

  const section: EditSection = sheet;
  const mine = changes.edits.filter((e) => e.section === section);
  // One dirty count per staged LINE so the shell's leave guard reads the same number the old editor reported.
  const stagedLines = new Set(mine.map((e) => e.key.split("#")[0])).size;
  useReportDirty(`cost-lines-${sheet}`, stagedLines);
  useReportPending(`cost-lines-${sheet}`, inFlight);
  // OPEX base amounts are canonical cells (same field ids and writer as the Assumptions grid) staged in the same store.
  const baseIds = new Set(sheet === "opex" ? baseRows.map((r) => r.field_id || r.code) : []);
  const baseStaged = changes.edits.filter((e) => baseIds.has(e.key) && e.section === sectionOfField(e.key));
  useReportDirty("opex-base", baseStaged.length);

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
      const hay = `${line.label} ${costGroupLabel(line.category, data?.line_management?.eligible_groups ?? [])}`.toLowerCase();
      if (!hay.includes(needle) && !isChanged(line)) return false;
    }
    if (filter === "nonzero") return Number(valueOf(line, "amount")) !== 0;
    if (filter === "changed") return isChanged(line);
    if (filter === "inactive") return !line.active || lineInfo.get(line.sub_line_id)?.mapping_status === "UNRESOLVED";
    return true;
  });
  const lines = filtered.filter((l) => !collapsed.has(l.category));
  const readOnlyProject = data?.project.protected_reference ?? true;
  // The grid is "refreshing" from the moment the workspace announces newer saved data until the read for it has landed: the composite
  // identity held in `data` belongs to the older state, so no line command may use it (a stale token would only be refused).
  const refreshing = loadedKey !== reloadKey;
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
      await load();                                                  // read the saved lines first: the cells then change straight from the typed text to the saved text
      for (const edit of mine) changes.revert(edit.id);
      onMutated?.();
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

  const switchSheet = (next: Sheet) => { if (next !== sheet) confirmIfDirty(() => onSheet?.(next), { ignore: (key) => !key.startsWith("cost-") }); };
  const headingId = useId();

  if (!data) return loadError
    ? <div className="fm-banner" role="alert"><span className="fm-demo-label">UNAVAILABLE</span><span className="fm-banner-copy">{loadError}</span><button type="button" className="fm-btn" onClick={() => void load()}>Retry</button></div>
    : <p className="fm-info-note" role="status">Loading…</p>;

  const capacity = projection?.capacity ?? null;
  const perYear = sheet === "opex";
  const cols: ColId[] = narrow
    ? (sheet === "capex" ? ["line", "amount"] : ["line", "amount", "infl"])
    : sheet === "capex"
      ? ["line", "amount", "perMw", "profile", "status", "menu"]
      : ["line", "amount", "perMw", "infl", "status", "menu"];
  const amountAt = cols.indexOf("amount");
  const total = sumDecimals(allLines.filter((l) => l.active).map((l) => valueOf(l, "amount")));
  const fmtKeur = (n: number | string | null) => showKeur(n, unit, precision);
  // Totals follow the chosen unit; the amount inputs are always kEUR. Whenever the unit is not kEUR the totals say which unit they are in.
  const unitTag = unit === "kEUR" ? null : <small className="ci-preview"> {unit}</small>;
  const title = sheet === "capex" ? "CAPEX" : "OPEX";
  // Every canonical group is shown (an empty group offers "+ Add line"); calculated groups are explained, never editable.
  const eligibleCodes = new Set((data.line_management?.eligible_groups ?? []).map((g) => g.code));
  const showEmpty = filter === "all" && !needle;
  const groupOrder = (() => {
    const fromLines = Array.from(new Set(filtered.map((l) => l.category)));
    if (!projection) return fromLines;
    const withLines = new Set(fromLines);
    const out = projection.groups.map((g) => g.code).filter((c) => withLines.has(c) || (showEmpty && (eligibleCodes.has(c) || groupInfo.get(c)?.mapping_status === "DERIVED")));
    for (const c of fromLines) if (!out.includes(c)) out.push(c);
    return out;
  })();
  const openAdd = (cat: string | undefined) => {
    if (!cat) return;
    setCollapsed((prev) => { if (!prev.has(cat)) return prev; const next = new Set(prev); next.delete(cat); return next; });
    setAddGroup(cat);
    setGroupPreset({ code: cat, nonce: Date.now() });
  };
  const baseRowFor = (cat: string) => {
    const id = sheet === "opex" ? OPEX_BASE_FIELD_BY_GROUP[cat] : undefined;
    return id ? baseRows.find((r) => (r.field_id || r.code) === id) : undefined;
  };
  const stageBase = (row: GridRowPayload, name: string, typed: string) => {
    const id = row.field_id || row.code;
    const verdict = amountValidator(typed);
    const baseline = row.value ?? "";
    const equal = sameDecimalText(typed.trim(), baseline);
    changes.stage({ section: sectionOfField(id), key: id, label: `${name} — base amount`, unit: row.unit, baseline, value: equal ? baseline : typed,
                    error: verdict.ok || equal ? undefined : verdict.message }, { coalesce: true });
  };
  const editedAmount = (line: CostLinePayload) => {
    const edit = changes.get(section, `${line.sub_line_id}#amount`);
    return edit ? (edit.canonical ?? (edit.error ? null : edit.value)) : undefined;
  };

  const inputTd = (line: CostLinePayload, col: "label" | "amount" | "inflation", r: number, c: number) => {
    const rowEditable = editableLine(line);
    const edit = changes.get(section, `${line.sub_line_id}#${col}`);
    const cellKey = `${line.sub_line_id}#${col}`;
    const raw = valueOf(line, col);
    const value = col === "amount" && !edit && focusedKey !== cellKey ? showKeur(raw, "kEUR", precision) : raw;
    const errorId = `${headingId}-${r}-${c}-err`;
    const label = `${col === "label" ? "Label" : col === "amount" ? "Amount" : "Inflation"} for ${line.label}`;   // the original editor's accessible names
    const field = (
      <input className={`fm-input ws2-cell ${col === "label" ? "ws2-cell-text" : ""}`} type="text"
        inputMode={col === "label" ? "text" : "decimal"} autoComplete="off" spellCheck={false}
        aria-label={label} aria-invalid={edit?.error ? true : undefined} aria-describedby={edit?.error ? errorId : undefined}
        data-r={r} data-c={c} data-changed={edit ? "true" : undefined}
        value={value} disabled={!rowEditable} data-exact={col === "amount" ? raw : undefined}
        onFocus={(event) => { setFocusedKey(cellKey); keys.onFocus(event); }} onBlur={() => setFocusedKey((k) => (k === cellKey ? null : k))}
        onKeyDown={keys.onKeyDown} onPaste={keys.onPaste}
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
          ? <div className="ws2-label-wrap">{field}{notesBlock}</div>
          : field}
        {edit?.error && <small id={errorId} className="ws2-cell-error" role="alert">{edit.error}</small>}
      </td>
    );
  };

  const staticTd = (id: ColId, line: CostLinePayload) => {
    const info = lineInfo.get(line.sub_line_id);
    switch (id) {
      case "perMw": {
        const preview = editedAmount(line);
        const saved = info?.per_mw_keur ?? null;
        const text = preview !== undefined ? (preview && capacity?.available ? divideDecimalText(preview, capacity.mw) : null) : saved;
        const live = line.active && capacity?.available && text !== null;
        return (
          <td key={id} className="ci-num ci-col-permw" data-per-mw={line.sub_line_id} data-per-mw-state={!live ? "unavailable" : preview !== undefined ? "preview" : "saved"}
              title={!live ? (capacity?.note ?? "Per-MW is shown for active lines when the installed capacity is known.") : preview !== undefined ? "Unsaved preview — not saved" : undefined}>
            {live ? <>{fmtKeur(text)}{preview !== undefined && <small className="ci-preview"> unsaved preview</small>}</> : "—"}
          </td>);
      }
      case "profile": return (
        <td key={id} className="ci-col-profile" data-cost-profile={line.sub_line_id}>
          {profiles === null ? "—" : (
            <button type="button" className="ci-link ci-profile" title="Shown from the saved spending profile. Edit it in the CAPEX spending profile studio." data-profile-link={line.sub_line_id}
                    onClick={openCapexStudio}>
              {profileText(profiles, info?.finco_display_code ?? "")} ▸
            </button>)}
        </td>);
      case "status": return (
        <td key={id} className="ci-col-status" data-cost-status={line.sub_line_id}>
          {!line.active ? <span className="ws2-chip">Inactive</span>
            : isChanged(line) ? <span className="ws2-chip ws2-chip-changed">Changed</span>
            : info?.mapping_status === "UNRESOLVED" ? <span className="ws2-chip" data-mapping-status="UNRESOLVED" title={MAPPING_NOTE.UNRESOLVED}>To be confirmed</span>
            : editableLine(line) ? <span className="ws2-chip ws2-chip-ok">Editable</span> : <span className="ws2-chip">Locked</span>}
        </td>);
      case "menu": return (
        <td key={id} className="ci-col-menu">
          <RowMenu line={line} open={menuFor === line.sub_line_id} disabled={readOnlyProject || refreshing || locked}
                   onToggle={() => setMenuFor(menuFor === line.sub_line_id ? null : line.sub_line_id)}
                   onAction={(active) => { setMenuFor(null); setRowAction({ lineId: line.sub_line_id, active, nonce: Date.now() }); }} />
        </td>);
      default: return <td key={id} />;
    }
  };

  const HEAD: Record<ColId, string> = { line: "Line", amount: "Amount (kEUR)", perMw: perMwLabel(unit, perYear), infl: "Inflation (%)", profile: "Payment profile", status: "Status", menu: "" };
  const baseTr = (cat: string, row: GridRowPayload) => {
    const id = row.field_id || row.code;
    const name = costGroupLabel(cat, data.line_management?.eligible_groups ?? []);
    const edit = changes.get(sectionOfField(id), id);
    const baseKey = `base:${id}`;
    const rawBase = edit?.value ?? (row.value ?? "");
    const value = !edit && focusedKey !== baseKey ? showKeur(rawBase, "kEUR", precision) : rawBase;
    const live = edit ? (edit.error ? null : edit.value) : (row.value ?? "");
    const perMwText = capacity?.available && live !== null ? divideDecimalText(live, capacity.mw) : null;
    const editable = Boolean(row.editable) && !readOnlyProject && !locked;
    const errorId = `${headingId}-base-${id}`;
    return (
      <tr key={`base-${id}`} data-base-row={id} data-line-kind="base">
        {cols.map((col) => col === "line" ? (
          <td key={col} className="ci-col-line"><div className="ws2-label-wrap"><span className="ws2-base-label">Group base amount</span>
            <small className="ci-preview" title="The saved yearly base amount of this group. It is saved with the other cells (Save changes) and adds to the lines below.">saved with Save changes</small></div></td>
        ) : col === "amount" ? (
          <td key={col} className="ci-col-amount">
            <input className="fm-input ws2-cell" type="text" inputMode="decimal" autoComplete="off" spellCheck={false} data-base-input={id}
              aria-label={`Base amount for ${name}`} aria-invalid={edit?.error ? true : undefined} aria-describedby={edit?.error ? errorId : undefined}
              data-changed={edit ? "true" : undefined} value={value} data-exact={rawBase} disabled={!editable}
              onFocus={() => setFocusedKey(baseKey)} onBlur={() => setFocusedKey((k) => (k === baseKey ? null : k))}
              onChange={(event) => { setStatus(null); stageBase(row, name, event.target.value); }} />
            {edit?.error && <small id={errorId} className="ws2-cell-error" role="alert">{edit.error}</small>}
          </td>
        ) : col === "perMw" ? (
          <td key={col} className="ci-num ci-col-permw" data-per-mw-state={perMwText === null ? "unavailable" : edit ? "preview" : "saved"}
              title={perMwText === null ? (capacity?.note ?? "Per-MW is shown when the installed capacity is known.") : edit ? "Unsaved preview — not saved" : undefined}>
            {perMwText === null ? "—" : <>{fmtKeur(perMwText)}{edit && <small className="ci-preview"> unsaved preview</small>}</>}
          </td>
        ) : col === "status" ? (
          <td key={col} className="ci-col-status">{edit ? <span className="ws2-chip ws2-chip-changed">Changed</span> : editable ? <span className="ws2-chip ws2-chip-ok">Editable</span> : <span className="ws2-chip">Locked</span>}</td>
        ) : col === "infl" ? (
          <td key={col} className="ci-num" title="The base amount follows the project's OPEX escalation.">—</td>
        ) : <td key={col} />)}
      </tr>
    );
  };
  let rowIndex = 0;

  return (
    <section className="fm-card fm-section" aria-label={`${title} line items`} data-cost-grid={sheet} data-density={density}>
      <div className="fm-card-title ci-detail-head">
        <h2 id={headingId}>{title} — all lines</h2>
        <span className="ci-detail-sub" data-cost-subtitle="true">{allLines.length} lines · scenario {scenarioName}</span>
        <span className="fm-toolbar">
                    <button type="button" className={`fm-btn ${sheet === "capex" ? "fm-btn-primary" : ""}`} aria-pressed={sheet === "capex"} onClick={() => switchSheet("capex")}>CAPEX</button>
          <button type="button" className={`fm-btn ${sheet === "opex" ? "fm-btn-primary" : ""}`} aria-pressed={sheet === "opex"} onClick={() => switchSheet("opex")}>OPEX</button>
          <button type="button" className="fm-btn" aria-pressed={density === "compact"} data-density-toggle="true" onClick={toggleDensity}>Compact rows</button>
        </span>
      </div>
      <p className="rx-save-scope" data-save-scope="cost-lines">
        <strong>Saves:</strong> every edited {title} line below, together — all are saved or none. Saving does not run the model.
        {" "}Edits stay staged while you move between sections and are listed under <em>Changes</em>.
      </p>
      <p className="ws2-grid-keys rx-note">Enter or ↓ next row · ↑ previous · Tab next cell · Esc cancels the cell · paste a block from Excel · Ctrl+Z / Ctrl+Y undo / redo.</p>
      {sheet === "capex" || sheet === "opex" ? (
        <p className="rx-note" data-permw-note={capacity ? (capacity.available ? "available" : "unavailable") : "none"}>
          {capacity?.available
            ? <>One saved amount per line, in kEUR. {perMwLabel(unit, perYear)} = amount ÷ {capacity.mw} MW {capacity.basis}{perYear ? ", per year" : ""} — read-only, never saved.</>
            : <>One saved amount per line, in kEUR. {capacity?.note ?? "Per-MW figures are not available for this project."}</>}
        </p>) : null}
      {refreshing && (
        <div className="fm-info-note" role="status" data-cost-refreshing="true">
          {loadError ? <>{loadError} <button type="button" className="fm-btn" onClick={() => void load()}>Retry</button></> : "Updating to the latest saved state… adding or retiring lines is available again in a moment."}
        </div>)}
      {readOnlyProject && <div className="fm-banner" role="note"><span className="fm-demo-label">READ-ONLY TEMPLATE</span><span className="fm-banner-copy">Read-only. Line items of a reference are immutable.</span></div>}
      {status && <div className="fm-info-note" role={status.tone === "ok" ? "status" : "alert"} data-tone={status.tone}>{status.text}</div>}
      {pasteNote && <div className="fm-info-note" role="status" data-paste-note="true">{pasteNote}</div>}
      <div className="ci-linebar" data-ci-linebar="true">
        <input type="search" className="fm-input ci-linesearch" data-cost-search="true" value={localQuery} placeholder="Search line or group…"
               aria-label={`Search ${title} lines`} onChange={(e) => setLocalQuery(e.target.value)} />
        <span className="ci-filters" role="group" aria-label="Show lines">
          {FILTERS.map((f) => (
            <button key={f.id} type="button" className="fm-btn ci-filter" aria-pressed={filter === f.id} data-cost-filter={f.id} onClick={() => setFilter(f.id)}>{f.label}</button>
          ))}
        </span>
        <CostUnitSelect />
        <button type="button" className="fm-btn ci-addline" data-cost-addline="true" disabled={readOnlyProject || refreshing}
                onClick={() => openAdd(addGroup ?? groupOrder.find((c) => eligibleCodes.has(c)))}>
          + Add line
        </button>
        <button type="button" className="fm-btn" data-cost-expand="true" onClick={() => setCollapsed(collapsed.size ? new Set() : new Set(groupOrder))}>{collapsed.size ? "Expand all" : "Collapse all"}</button>
        <span className="ci-shown" data-cost-shown="true" role="status">{filtered.length} of {allLines.length} lines shown</span>
      </div>
      <div ref={container} className="fm-table-wrap rx-lines-scroll" role="region" tabIndex={0} aria-label={`${title} line items, scrollable`} data-lines-scroll={sheet}>
        <table className="fm-table ws2-grid">
          <caption className="fm-sr-only">{title} line items. Amounts are entered in kEUR; totals and per-MW figures are shown in {unit}.</caption>
          <thead><tr>{cols.map((id) => (
            <th key={id} scope="col" className={`ci-h-${id}${id === "amount" || id === "perMw" ? " ci-num" : ""}`}
                title={id === "perMw" ? "Read-only: amount divided by the saved installed capacity" : undefined}>{id === "menu" ? <span className="fm-sr-only">Row actions</span> : HEAD[id]}</th>))}</tr></thead>
          <tbody>
            {groupOrder.map((cat) => {
              const g = groupInfo.get(cat);
              const isCollapsed = collapsed.has(cat);
              const members = filtered.filter((l) => l.category === cat);
              return (
                <Fragment key={cat}>
                  <tr className="ws2-group-row" data-group-row={cat}>
                    <th scope="colgroup" colSpan={Math.max(amountAt, 1)}>
                      <button type="button" className="ci-twisty" aria-expanded={!isCollapsed} aria-label={`${isCollapsed ? "Expand" : "Collapse"} ${costGroupLabel(cat, data.line_management?.eligible_groups ?? [])}`} data-cost-twisty={cat}
                              onClick={() => { const next = new Set(collapsed); if (isCollapsed) next.delete(cat); else next.add(cat); setCollapsed(next); }} />
                      <span className="ws2-group-name">{costGroupLabel(cat, data.line_management?.eligible_groups ?? [])}</span>
                      <span className="ws2-group-meta" data-group-meta={cat}>
                        <span className="ci-n">{members.length} line{members.length === 1 ? "" : "s"}</span>
                        {g && g.mapping_status !== "PROVEN" && <span className="ws2-chip" data-mapping-status={g.mapping_status} title={MAPPING_NOTE[g.mapping_status]}>{g.mapping_status === "DERIVED" ? "Calculated" : "To be confirmed"}</span>}
                      </span>
                    </th>
                    <td className="ci-num ci-gtotal" data-group-saved-total={g && g.saved_total_keur !== null ? cat : undefined}>{g && g.saved_total_keur !== null ? <>{fmtKeur(g.saved_total_keur)}{unitTag}</> : ""}</td>
                    {cols.length - amountAt - 1 > 0 && (
                      <td colSpan={cols.length - amountAt - 1} className="ci-gaction">
                        <button type="button" className="ci-link" disabled={readOnlyProject || refreshing || !data.line_management.eligible_groups.some((eg) => eg.code === cat)} data-cost-group-add={cat}
                                onClick={() => openAdd(cat)}>+ Add line</button>
                      </td>)}
                  </tr>
                  {!isCollapsed && (() => { const b = baseRowFor(cat); return b ? baseTr(cat, b) : null; })()}
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
                  {addGroup === cat && <tr data-add-row={cat}><td colSpan={cols.length}><div ref={setSlot} className="ci-addslot" /></td></tr>}
                  {!isCollapsed && !members.length && !baseRowFor(cat) && g?.mapping_status !== "DERIVED" && addGroup !== cat && (
                    <tr data-empty-group={cat}><td colSpan={cols.length} className="ci-empty-group">No lines in this group yet.</td></tr>)}
                </Fragment>
              );
            })}
            {!lines.length && !groupOrder.length && <tr><td colSpan={cols.length}><span role="status">{allLines.length ? "No lines match this search or filter." : "No line items were projected for this sheet."}</span></td></tr>}
          </tbody>
          {allLines.length > 0 && total !== null && (
            <tfoot>
              <tr className="ws2-grid-total"><th scope="row" colSpan={Math.max(amountAt, 1)}>{sheet === "opex" ? "Sum of added line amounts" : "Sum of line amounts"} ({unit}, as shown — not a model result)</th><td data-lines-sum="true" data-exact={total} className="ci-num">{fmtKeur(total)}{unitTag}</td>{cols.length - amountAt - 1 > 0 && <td colSpan={cols.length - amountAt - 1} />}</tr>
              {projection && <tr className="ws2-grid-total" data-saved-total-row="true"><th scope="row" colSpan={Math.max(amountAt, 1)}>Saved on the server ({unit}, sum of active saved {sheet === "opex" ? "added lines — excludes the group base amounts" : "lines"} — not a model result)</th><td data-saved-total="true" data-exact={String(projection.saved_total_keur)} className="ci-num">{fmtKeur(projection.saved_total_keur)}{unitTag}</td>{cols.length - amountAt - 1 > 0 && <td colSpan={cols.length - amountAt - 1} />}</tr>}
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
      {sheet === "opex" && baseIds.size > 0 && (
        <p className="rx-note" data-base-save-note="true">
          Group base amounts are saved with the other cells, together with cost lines, by <strong>Save changes</strong> (top bar or here).
          {" "}<em>Save staged lines</em> above saves the added lines only.
          {baseStaged.length > 0 && <>{" "}<button type="button" className="fm-btn fm-btn-primary" data-opex-save-all="true" disabled={saveAll.disabled || saveAll.run === null} title={saveAll.reason || undefined}
            onClick={() => saveAll.run?.()}>{saveAll.saving ? "Saving…" : `Save ${saveAll.total} change${saveAll.total === 1 ? "" : "s"}`}</button></>}
        </p>)}
      <CostLineManager key={sheet} project={project} data={data} refreshing={refreshing} presetGroup={groupPreset} rowAction={rowAction}
                       slot={addGroup ? slot : null} openGroup={addGroup} onClose={() => setAddGroup(null)}
                       onChanged={() => { setAddGroup(null); void load(); onMutated?.(); }} />
    </section>
  );
}

/** The only row actions with a real canonical command: retire (soft deactivation) and reactivate. Duplicate / reorder / delete are not offered.
 *  The list is positioned against the viewport so the table's scroll container never clips it. */
function RowMenu({ line, open, disabled, onToggle, onAction }: { line: CostLinePayload; open: boolean; disabled: boolean; onToggle: () => void; onAction: (active: boolean) => void }) {
  const id = useId();
  const button = useRef<HTMLButtonElement>(null);
  const first = useRef<HTMLButtonElement>(null);
  const [at, setAt] = useState<{ top?: number; bottom?: number; right: number } | null>(null);
  useEffect(() => { if (open && at) first.current?.focus({ preventScroll: true }); }, [open, at]);
  useLayoutEffect(() => {
    if (!open) { setAt(null); return undefined; }
    const place = () => { const rect = button.current?.getBoundingClientRect(); if (rect) setAt({ ...(rect.bottom + 48 > window.innerHeight ? { bottom: window.innerHeight - rect.top + 2 } : { top: rect.bottom + 2 }), right: Math.max(4, window.innerWidth - rect.right) }); };
    place();
    const away = (event: Event) => { if (!(event.target instanceof Node) || !(button.current?.parentElement?.contains(event.target))) onToggle(); };
    document.addEventListener("mousedown", away);
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => { document.removeEventListener("mousedown", away); window.removeEventListener("scroll", place, true); window.removeEventListener("resize", place); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  return (
    <span className="ci-menuwrap">
      <button ref={button} type="button" className="ci-menu" aria-haspopup="menu" aria-expanded={open} aria-controls={open ? id : undefined} disabled={disabled}
              aria-label={`Actions for ${line.label}`} data-row-menu={line.sub_line_id}
              onClick={onToggle} onKeyDown={(e) => { if (e.key === "Escape" && open) { e.stopPropagation(); onToggle(); } }}>…</button>
      {open && at && (
        <span id={id} role="menu" className="ci-menulist" aria-label={`Actions for ${line.label}`} style={{ top: at.top, bottom: at.bottom, right: at.right }}>
          <button ref={first} type="button" role="menuitem" className="ci-menuitem" data-row-action={line.active ? "retire" : "reactivate"}
                  onClick={() => onAction(!line.active)} onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); onToggle(); button.current?.focus(); } }}>
            {line.active ? "Deactivate line" : "Reactivate line"}
          </button>
        </span>)}
    </span>
  );
}
