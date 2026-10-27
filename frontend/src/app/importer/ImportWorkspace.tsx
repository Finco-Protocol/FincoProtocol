import { useEffect, useMemo, useRef, useState } from "react";
import "../../styles/rcm-analysis.css";
import { FriendlyError } from "../productLanguage";
import { StatusNote, useReportDirty, useReportPending, useSingleFlight, useUnresolvedLock, type StatusMessage } from "../workflow/workflowShared";
import { applyApproved, confirmSelection, fetchImportContext, uploadForReview } from "./api";
import type { ApprovedRow, ImportConfirm, ImportContext, ImportPreview, ImportResult, ImportRow, RowChoice, RowStatus } from "./types";

const STATUS_TEXT: Record<RowStatus, string> = {
  ready: "Ready", needs_review: "Check where it goes", unchanged: "No change", invalid: "Invalid value",
  unsupported: "Cannot be imported here", unsupported_for_apply: "Cannot be imported here",
};
const REASON_TEXT: Array<[RegExp, string]> = [
  [/UNSUPPORTED_LABEL/, "We could not match this item to an assumption of the model."],
  [/MAPPING_AMBIGUOUS/, "More than one assumption could match. Choose the right one."],
  [/DUPLICATE_TARGET/, "Another row in the file points to the same assumption. Keep only one."],
  [/FORMULA_NOT_AUTHORITATIVE/, "The cell holds a formula without a stored value."],
  [/UNSUPPORTED_FOR_APPLY/, "This item is edited in its own place (for example contracts or financing)."],
];
const reasonText = (reason: string | null) => (reason ? (REASON_TEXT.find(([re]) => re.test(reason))?.[1] ?? "This row needs your review.") : "");

type Filter = "all" | "ready" | "attention" | "unchanged" | "blocked";
const FILTERS: Array<[Filter, string]> = [["all", "All"], ["ready", "Ready"], ["attention", "Needs attention"], ["unchanged", "No change"], ["blocked", "Cannot be imported"]];
const bucket = (r: ImportRow): Filter => (r.status === "ready" ? "ready" : r.status === "unchanged" ? "unchanged" : r.status === "needs_review" ? "attention" : "blocked");

type Step = "upload" | "review" | "confirm" | "result";
const STEP_LABEL: Record<Step, string> = { upload: "1 · Choose a file", review: "2 · Review", confirm: "3 · Confirm", result: "4 · Saved" };

const cell = (v: string | number | null | undefined) => (v === null || v === undefined || v === "" ? "—" : String(v));

/** Inputs > Import from Excel / CSV.  Four deliberate steps over the existing import transaction:
 *  choose a file (read in memory, nothing stored) → review the proposed mapping (nothing written) → confirm the exact values (nothing written)
 *  → save to the project (one transaction; results become out of date; the model is NOT run).  Mapping, unit conversion and validation are
 *  the server's; the browser only carries the user's choices. */
export function ImportWorkspace({ project, protectedReference, onSaved }: { project: string; protectedReference: boolean; onSaved: () => void }) {
  const [ctx, setCtx] = useState<ImportContext | null>(null);
  const [ctxError, setCtxError] = useState<{ code: string; message?: string } | null>(null);
  const [step, setStep] = useState<Step>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [encoding, setEncoding] = useState("utf-8-sig");
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [choices, setChoices] = useState<Record<number, RowChoice>>({});
  const [filter, setFilter] = useState<Filter>("all");
  const [confirmed, setConfirmed] = useState<ImportConfirm | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [busy, setBusy] = useState<"" | "upload" | "confirm" | "apply">("");
  const [error, setError] = useState<{ code: string; message?: string } | null>(null);
  const [status, setStatus] = useState<StatusMessage | null>(null);
  const [unresolved, setUnresolved] = useUnresolvedLock("import-apply");
  const singleFlight = useSingleFlight();
  const fileInput = useRef<HTMLInputElement | null>(null);

  const loadContext = () => {
    void fetchImportContext(project).then((r) => { if (r.ok) { setCtx(r); setCtxError(null); } else setCtxError(r); });
  };
  useEffect(loadContext, [project]);   // eslint-disable-line react-hooks/exhaustive-deps

  const selected = Object.values(choices).filter((c) => c.keep).length;
  useReportDirty("import-review", step === "review" || step === "confirm" ? Math.max(selected, 1) : 0);
  useReportPending("import-apply", busy === "apply");

  const fieldLabel = useMemo(() => new Map((ctx?.fields ?? []).map((f) => [f.id, f.label])), [ctx]);
  const reset = () => {
    setStep("upload"); setFile(null); setPreview(null); setChoices({}); setConfirmed(null); setResult(null); setError(null); setFilter("all");
    if (fileInput.current) fileInput.current.value = "";
    loadContext();
  };

  if (protectedReference) {
    return <p className="rx-empty" role="status" data-import-state="read-only">Templates are read-only. Start a project from this template to import data into it.</p>;
  }
  if (ctxError) return <FriendlyError code={ctxError.code} message={ctxError.message} />;
  if (!ctx) return <p className="rx-boot-loading" role="status" data-import-state="loading">Loading import…</p>;

  const upload = () => singleFlight(async () => {
    if (!file) { setError({ code: "IMPORT_FILE_REQUIRED", message: "Choose a CSV or XLSX file first." }); return; }
    setBusy("upload"); setError(null); setStatus(null);
    const r = await uploadForReview(project, ctx.csrf_token, file, encoding);
    setBusy("");
    if (!r.ok) { setError(r); loadContext(); return; }
    const initial: Record<number, RowChoice> = {};
    for (const row of r.rows) {
      initial[row.id] = { keep: row.status === "ready" && row.bulk_selectable, field: row.field_id ?? "", unit: row.source_unit ?? "", manual: "" };
    }
    setPreview(r); setChoices(initial); setFilter("all"); setStep("review");
  });

  const confirm = () => singleFlight(async () => {
    if (!preview) return;
    setBusy("confirm"); setError(null);
    const r = await confirmSelection(project, ctx.csrf_token, preview.preview_ticket, choices);
    setBusy("");
    if (!r.ok) { setError(r); return; }
    setConfirmed(r); setStep("confirm");
  });

  const apply = () => singleFlight(async () => {
    if (!confirmed) return;
    setBusy("apply"); setError(null); setStatus(null);
    const r = await applyApproved(project, ctx.csrf_token, confirmed.approved_ticket);
    setBusy("");
    if (r.ok) {
      setResult(r); setStep("result"); setStatus(null); onSaved();
      return;
    }
    if (r.code === "SERVER_UNREACHABLE" || /^HTTP_5/.test(r.code)) {
      // Ambiguous: the save may have happened.  Never retried; the Inputs page shows the truth.
      setUnresolved(true);
      setStatus({ tone: "conflict", text: "We could not confirm whether the values were saved. Open Inputs to check them before importing again — the same approval cannot be saved twice." });
      return;
    }
    setError(r);
  });

  const rows = preview?.rows ?? [];
  const visible = rows.filter((r) => filter === "all" || bucket(r) === filter);
  const counts: Record<Filter, number> = { all: rows.length, ready: 0, attention: 0, unchanged: 0, blocked: 0 };
  for (const r of rows) counts[bucket(r)] += 1;
  const patch = (id: number, next: Partial<RowChoice>) => setChoices((c) => ({ ...c, [id]: { ...c[id], ...next } }));
  const limit = ctx.limits.max_approved;
  const selectReady = () => setChoices((c) => {
    const out = { ...c };
    let n = 0;
    for (const r of rows) {
      const want = r.status === "ready" && r.bulk_selectable && n < limit;
      out[r.id] = { ...out[r.id], keep: want };
      if (want) n += 1;
    }
    return out;
  });
  const clearAll = () => setChoices((c) => Object.fromEntries(Object.entries(c).map(([k, v]) => [k, { ...v, keep: false }])));
  const incomplete = rows.some((r) => choices[r.id]?.keep && !choices[r.id]?.field);

  return (
    <section className="rx-card rcm-analysis" data-import-workspace="true" data-import-step={step} aria-label="Import from Excel or CSV">
      <h2>Import from Excel or CSV</h2>
      <p className="rx-note">Bring assumptions from a spreadsheet into this project. Your file is read in memory and is never stored. Nothing is saved until the last step, and the model is not run.</p>
      <ol className="rcux-steps" data-import-steps="true">
        {(Object.keys(STEP_LABEL) as Step[]).map((s) => <li key={s} aria-current={s === step ? "step" : undefined} data-step={s}>{STEP_LABEL[s]}</li>)}
      </ol>
      <StatusNote status={status} />
      {error && <FriendlyError code={error.code} message={error.message} />}

      {step === "upload" && (
        <div data-import-panel="upload">
          <div className="rx-controls">
            <label>File (CSV or XLSX, up to {Math.round(ctx.limits.max_upload_bytes / (1024 * 1024))} MB)
              <input ref={fileInput} type="file" accept=".csv,.xlsx" data-import-file="true" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setError(null); }} />
            </label>
            {/\.csv$/i.test(file?.name ?? "") && (
              <label>Text encoding
                <select value={encoding} data-import-encoding="true" onChange={(e) => setEncoding(e.target.value)}>
                  {ctx.limits.encodings.map((enc) => <option key={enc} value={enc}>{enc}</option>)}
                </select>
              </label>
            )}
            <button type="button" className="rx-button" data-import-upload="true" disabled={!file || busy !== "" || unresolved} aria-busy={busy === "upload"} onClick={() => void upload()}>
              {busy === "upload" ? "Reading file…" : "Read file and review"}
            </button>
          </div>
          <p className="rx-note">A CSV needs one item per row: the name in the first column and its value in the second (a unit in a third column is used when present). For an Excel workbook, label/value pairs on any sheet are read.</p>
        </div>
      )}

      {step === "review" && preview && (
        <div data-import-panel="review">
          <p className="rx-note" role="status" data-import-summary="true">
            {preview.detected} item{preview.detected === 1 ? "" : "s"} found in {file?.name ?? "the file"}: {counts.ready} ready, {counts.attention} need{counts.attention === 1 ? "s" : ""} a decision,
            {" "}{counts.unchanged} already match this project, {counts.blocked} cannot be imported here. Select up to {limit} rows to import.
          </p>
          <div className="rcm-tabs" role="tablist" aria-label="Filter rows">
            {FILTERS.map(([id, label]) => (
              <button key={id} type="button" role="tab" aria-selected={filter === id} className={`rcm-tab${filter === id ? " active" : ""}`} data-import-filter={id}
                onClick={() => setFilter(id)}>{label} ({counts[id]})</button>
            ))}
          </div>
          <div className="rx-controls">
            <button type="button" className="rx-button rx-button-secondary" data-import-select-ready="true" onClick={selectReady}>Select all ready rows</button>
            <button type="button" className="rx-button rx-button-secondary" data-import-clear="true" onClick={clearAll}>Clear selection</button>
            <span className="rx-note" data-import-selected="true" role="status">{selected} selected</span>
          </div>
          <div className="fi-table-scroll" tabIndex={0} role="region" aria-label="Rows found in the file">
            <table className="fm-table" data-import-table="true">
              <thead><tr><th scope="col">Import</th><th scope="col">In your file</th><th scope="col">Value</th><th scope="col">Unit in file</th><th scope="col">Goes to</th><th scope="col">Now in project</th><th scope="col">Status</th></tr></thead>
              <tbody>
                {visible.map((r) => {
                  const c = choices[r.id] ?? { keep: false, field: "", unit: "", manual: "" };
                  const blocked = bucket(r) === "blocked" && !r.manual_scalar_mapping_allowed;
                  const targetLabel = (r.field_id && fieldLabel.get(r.field_id)) || "";
                  return (
                    <tr key={r.id} data-import-row={r.id} data-import-status={r.status} data-import-field={c.field || undefined}>
                      <td><input type="checkbox" checked={c.keep} disabled={blocked || (!c.keep && selected >= limit)} aria-label={`Import ${r.label}`}
                        data-import-keep={r.id} onChange={(e) => patch(r.id, { keep: e.target.checked })} /></td>
                      <th scope="row">{r.label}<br /><small className="rx-note">{r.sheet} · {r.source_cell}</small></th>
                      <td>{r.original_value}</td>
                      <td><input type="text" value={c.unit} maxLength={20} aria-label={`Unit of ${r.label}`} data-import-unit={r.id} disabled={blocked} onChange={(e) => patch(r.id, { unit: e.target.value })} /></td>
                      <td>
                        <select value={c.field} disabled={blocked} aria-label={`Where ${r.label} goes`} data-import-target={r.id} onChange={(e) => patch(r.id, { field: e.target.value })}>
                          <option value="">{r.field_id ? "Choose…" : "Not matched — choose…"}</option>
                          {ctx.fields.map((f) => <option key={f.id} value={f.id}>{f.label}{f.unit ? ` (${f.unit})` : ""}</option>)}
                        </select>
                        {targetLabel && c.field === r.field_id && <small className="rx-note"> Suggested match</small>}
                      </td>
                      <td>{cell(r.current_value)}</td>
                      <td data-import-row-status={r.status}>
                        <strong>{STATUS_TEXT[r.status]}</strong>
                        {(r.reason || r.explanation.length > 0) && <small className="rx-note"><br />{reasonText(r.reason) || r.explanation[0]}</small>}
                      </td>
                    </tr>
                  );
                })}
                {visible.length === 0 && <tr><td colSpan={7}><span role="status">No rows in this view.</span></td></tr>}
              </tbody>
            </table>
          </div>
          {incomplete && <p className="rx-note" role="status" data-import-incomplete="true">Choose where each selected row goes.</p>}
          <div className="rx-controls">
            <button type="button" className="rx-button" data-import-confirm="true" disabled={selected === 0 || incomplete || busy !== ""} aria-busy={busy === "confirm"} onClick={() => void confirm()}>
              {busy === "confirm" ? "Checking…" : `Review ${selected} value${selected === 1 ? "" : "s"}`}
            </button>
            <button type="button" className="rx-button rx-button-secondary" data-import-restart="true" onClick={reset}>Start over</button>
          </div>
        </div>
      )}

      {step === "confirm" && confirmed && (
        <div data-import-panel="confirm">
          <p className="rx-note" role="status" data-import-confirm-summary="true">
            {confirmed.approved_count} value{confirmed.approved_count === 1 ? "" : "s"} will be saved to this project ({confirmed.changed_count} change{confirmed.changed_count === 1 ? "s" : ""} to the current value).
            {confirmed.unchecked_count > 0 ? ` ${confirmed.unchecked_count} other row${confirmed.unchecked_count === 1 ? " is" : "s are"} ignored.` : ""}
            {" "}Saving makes your results out of date (STALE) until you run the model again. Nothing is calculated now.
          </p>
          <div className="fi-table-scroll" tabIndex={0} role="region" aria-label="Values to be saved">
            <table className="fm-table" data-import-approved="true">
              <thead><tr><th scope="col">Assumption</th><th scope="col">Now</th><th scope="col">After import</th><th scope="col">From your file</th></tr></thead>
              <tbody>
                {confirmed.approved.map((a: ApprovedRow) => (
                  <tr key={a.source_id} data-import-approved-field={a.field_id} data-import-changed={a.changed ? "true" : "false"}>
                    <th scope="row">{fieldLabel.get(a.field_id) ?? a.label}</th>
                    <td>{cell(a.current_value)}{a.unit ? ` ${a.unit}` : ""}</td>
                    <td><strong>{a.value}</strong>{a.unit ? ` ${a.unit}` : ""}{!a.changed && <small className="rx-note"> (no change)</small>}</td>
                    <td>{a.label} · {a.original_value}{a.chosen_unit ? ` ${a.chosen_unit}` : ""}
                      {a.correction_note && <small className="rx-note"><br />You adjusted: {a.correction_note}</small>}
                      <details className="rx-tech-details"><summary>Details</summary><p className="fm-mono">{a.sheet}!{a.cell} → {a.field_id}<br />{a.normalization}</p></details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="rx-controls">
            <button type="button" className="rx-button" data-import-apply="true" disabled={busy !== "" || unresolved} aria-busy={busy === "apply"} onClick={() => void apply()}>
              {busy === "apply" ? "Saving…" : "Save to project"}
            </button>
            <button type="button" className="rx-button rx-button-secondary" data-import-back="true" disabled={busy !== ""} onClick={() => { setStep("review"); setConfirmed(null); setError(null); }}>Back to review</button>
          </div>
        </div>
      )}

      {step === "result" && result && (
        <div data-import-panel="result">
          <p className="rx-status rx-status-ok" role="status" data-import-result="true">
            {result.applied_count} assumption{result.applied_count === 1 ? "" : "s"} saved to this project{result.skipped_count > 0 ? `; ${result.skipped_count} row${result.skipped_count === 1 ? " was" : "s were"} not imported` : ""}.
            {" "}{result.semantics.note} Your results are now out of date (STALE).
          </p>
          <div className="fi-table-scroll" tabIndex={0} role="region" aria-label="Saved values">
            <table className="fm-table" data-import-saved="true">
              <thead><tr><th scope="col">Assumption</th><th scope="col">Before</th><th scope="col">Saved</th></tr></thead>
              <tbody>
                {result.saved.map((s) => (
                  <tr key={s.field_id} data-import-saved-field={s.field_id}>
                    <th scope="row">{fieldLabel.get(s.field_id) ?? s.label}</th><td>{cell(s.previous_value)}</td><td><strong>{cell(s.actual_value)}</strong></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details className="rx-tech-details" data-import-audit="true">
            <summary>Advanced details / Audit trail</summary>
            <p className="fm-mono">Approved {result.approved_at ?? "—"}{result.transaction_identity ? ` · project version ${result.transaction_identity.slice(0, 16)}…` : ""}</p>
          </details>
          <div className="rx-controls">
            <button type="button" className="rx-button" data-import-another="true" onClick={reset}>Import another file</button>
          </div>
        </div>
      )}
    </section>
  );
}
