// UX-04/05/06 canonical surface views.  Presentation only: every value shown
// comes from a canonical JSON projection over the existing authorities, every
// mutation posts to the existing canonical writer route, and a surface whose
// backend contract is not established stays visibly gated — never fabricated.

import { useCallback, useEffect, useState } from "react";
import {
  fetchCostLines,
  fetchDiagnostics,
  fetchRevenueContracts,
  fetchRuns,
  fetchSheetFields,
  fetchTrust,
  runModel,
  saveCostLinesBatch,
  saveWorkbookField,
} from "./api";
import type { SheetFieldPayload } from "./types";

type FetchState<T> = { state: "loading" } | { state: "error"; message: string } | { state: "ready"; data: T };

type CanonicalFailure = { ok: false; code: string; message?: string };

function useCanonical<T>(fetcher: () => Promise<T | CanonicalFailure>, deps: unknown[]): FetchState<T> & { retry: () => void } {
  const [state, setState] = useState<FetchState<T>>({ state: "loading" });
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    let live = true;
    setState({ state: "loading" });
    fetcher().then((result: T | CanonicalFailure) => {
      if (!live) return;
      if (!result || (result as { ok?: unknown }).ok !== true) {
        const failure = result as CanonicalFailure;
        setState({ state: "error", message: failure.message || failure.code || "The server refused this read." });
      } else {
        setState({ state: "ready", data: result as T });
      }
    });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);
  const retry = useCallback(() => setNonce((n) => n + 1), []);
  return Object.assign(state, { retry }) as FetchState<T> & { retry: () => void };
}

function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="fm-banner" role="alert">
      <span className="fm-demo-label">UNAVAILABLE</span>
      <span className="fm-banner-copy">{message}</span>
      {onRetry && <button type="button" className="fm-btn" onClick={onRetry}>Retry</button>}
    </div>
  );
}

function LoadingNote() {
  return <p className="fm-info-note" role="status">Loading canonical data…</p>;
}

// ───────────────────────────── UX-04: financing fields ─────────────────────────────

function fieldIsEditable(field: SheetFieldPayload): boolean {
  return field.binding_label === "bound";
}

export function FinancingView({ project }: { project: string }) {
  const fetcher = useCallback(() => fetchSheetFields(project, "debt"), [project]);
  const state = useCanonical(fetcher, [project]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<{ tone: "ok" | "error" | "conflict"; text: string } | null>(null);
  const [inFlight, setInFlight] = useState(false);

  useEffect(() => { setDrafts({}); setStatus(null); }, [project]);

  const saveField = async (field: SheetFieldPayload) => {
    if (state.state !== "ready") return;
    const data = state.data;
    const value = drafts[field.field_id];
    if (value === undefined || value === (field.value ?? "")) return;
    setInFlight(true);
    setStatus(null);
    const result = await saveWorkbookField({
      updateUrl: data.save.url,
      project,
      fieldId: field.field_id,
      value,
      workbookVersion: data.save.workbook_version,
      contentHash: data.save.content_hash,
      csrfToken: data.save.csrf_token,
      financingCsrfToken: data.save.financing_csrf_token,
      // Correction A: a clean canonical redirect alone is not proof of a commit.
      // Reconcile through a fresh authorized projection and compare the
      // persisted value with what was submitted (numeric-tolerant).
      verifyCommitted: async () => {
        const fresh = await fetchSheetFields(project, "debt");
        if (fresh.ok !== true) return false;
        const persisted = fresh.fields.find((f) => f.field_id === field.field_id);
        if (!persisted) return false;
        const persistedText = String(persisted.value ?? "").trim();
        const submittedText = value.trim();
        if (persistedText === submittedText) return true;
        const a = Number(persistedText), b = Number(submittedText);
        return Number.isFinite(a) && Number.isFinite(b) && a === b;
      },
    });
    if ("kind" in result) {
      setStatus({ tone: "conflict", text: result.message });
    } else if (result.ok) {
      setStatus({ tone: "ok", text: `${field.label} saved atomically${result.verified ? " and verified in the fresh projection" : ""}. The model was not run.` });
      setDrafts((d) => { const n = { ...d }; delete n[field.field_id]; return n; });
      state.retry();
    } else {
      setStatus({ tone: "error", text: result.message });
    }
    setInFlight(false);
  };

  if (state.state === "loading") return <LoadingNote />;
  if (state.state === "error") return <ErrorNote message={state.message} onRetry={state.retry} />;
  const data = state.data;
  const editableCount = data.fields.filter(fieldIsEditable).length;
  return (
    <section className="fm-card fm-section" aria-label="Debt and Equity facilities">
      <div className="fm-card-title"><h2>Debt &amp; Equity facilities</h2><span>canonical /v2/workbook/update writer</span></div>
      {data.project.protected_reference && <div className="fm-banner" role="note"><span className="fm-demo-label">PROTECTED REFERENCE</span><span className="fm-banner-copy">Read-only. Working-copy the reference to edit facility terms.</span></div>}
      {status && <div className={`fm-info-note`} role="status" data-tone={status.tone}>{status.text}</div>}
      <div className="fm-field-grid">
        {data.fields.map((field) => {
          const canEdit = fieldIsEditable(field) && !data.project.protected_reference;
          const current = drafts[field.field_id] ?? field.value ?? "";
          return (
            <label key={field.field_id} className="fm-field" data-binding={field.binding_label}>
              <span className="fm-field-label">{field.label}</span>
              {canEdit ? (
                <input
                  className="fm-input"
                  value={current}
                  disabled={inFlight}
                  aria-describedby={field.help_text ? `help-${field.field_id}` : undefined}
                  onChange={(e) => setDrafts((d) => ({ ...d, [field.field_id]: e.target.value }))}
                  onBlur={() => saveField(field)}
                  onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); saveField(field); } }}
                />
              ) : (
                <span className="fm-field-value">{field.display_value ?? field.value ?? "—"} <small>({field.binding_label})</small></span>
              )}
              {field.help_text && <small id={`help-${field.field_id}`}>{field.help_text}</small>}
            </label>
          );
        })}
      </div>
      <p className="fm-info-note">Bound fields save one-by-one through the canonical writer (composite CAS; 409 on staleness). Display-only and template-locked values are computed or frozen — they are never editable here. {editableCount} bound fields in this sheet.</p>
    </section>
  );
}

// ───────────────────────────── UX-04: CAPEX / OPEX line batches ─────────────────────────────

export function CostLinesView({ project }: { project: string }) {
  const [sheet, setSheet] = useState<"capex" | "opex">("capex");
  const fetcher = useCallback(() => fetchCostLines(project, sheet), [project, sheet]);
  const state = useCanonical(fetcher, [project, sheet]);
  const [staged, setStaged] = useState<Record<string, { label?: string; amount_keur?: string; inflation_pct?: string; notes?: string }>>({});
  const [status, setStatus] = useState<{ tone: "ok" | "error" | "conflict"; text: string } | null>(null);
  const [inFlight, setInFlight] = useState(false);

  useEffect(() => { setStaged({}); setStatus(null); }, [sheet, project]);

  const saveBatch = async () => {
    if (state.state !== "ready") return;
    const data = state.data;
    const edits = Object.entries(staged).map(([subLineId, patch]) => {
      const line = data.lines.find((l) => l.sub_line_id === subLineId);
      return {
        kind: sheet,
        sub_line_id: subLineId,
        label: patch.label ?? line?.label ?? "",
        amount_keur: patch.amount_keur !== undefined ? Number(patch.amount_keur) : Number(line?.amount_keur ?? 0),
        row_version: line?.row_version ?? "",
        inflation_pct: sheet === "opex" ? (patch.inflation_pct !== undefined ? Number(patch.inflation_pct) : (line?.inflation_pct ?? null)) : undefined,
        notes: patch.notes ?? line?.notes ?? "",
      };
    });
    if (!edits.length) return;
    setInFlight(true);
    setStatus(null);
    const result = await saveCostLinesBatch({
      saveUrl: data.save.url,
      project,
      csrfToken: data.save.csrf_token,
      workbookVersion: data.save.workbook_version,
      contentHash: data.save.content_hash,
      sheet,
      edits,
    });
    if ("kind" in result) {
      setStatus({ tone: "conflict", text: result.message });
    } else if (result.ok) {
      setStatus({ tone: "ok", text: `${result.savedCount} line(s) saved atomically. The model was not run.` });
      setStaged({});
      state.retry();
    } else {
      setStatus({ tone: "error", text: result.message });
    }
    setInFlight(false);
  };

  if (state.state === "loading") return <LoadingNote />;
  if (state.state === "error") return <ErrorNote message={state.message} onRetry={state.retry} />;
  const data = state.data;
  const stagedCount = Object.keys(staged).length;
  return (
    <section className="fm-card fm-section" aria-label={`${sheet === "capex" ? "CAPEX" : "OPEX"} line items`}>
      <div className="fm-card-title">
        <h2>{sheet === "capex" ? "CAPEX construction plan" : "OPEX operating profile"}</h2>
        <span className="fm-toolbar">
          <button type="button" className={`fm-btn ${sheet === "capex" ? "fm-btn-primary" : ""}`} aria-pressed={sheet === "capex"} onClick={() => setSheet("capex")}>CAPEX</button>
          <button type="button" className={`fm-btn ${sheet === "opex" ? "fm-btn-primary" : ""}`} aria-pressed={sheet === "opex"} onClick={() => setSheet("opex")}>OPEX</button>
        </span>
      </div>
      {data.project.protected_reference && <div className="fm-banner" role="note"><span className="fm-demo-label">PROTECTED REFERENCE</span><span className="fm-banner-copy">Read-only. Line items of a reference are immutable.</span></div>}
      {status && <div className="fm-info-note" role="status" data-tone={status.tone}>{status.text}</div>}
      <div className="fm-table-wrap">
        <table className="fm-table">
          <thead><tr><th>Label</th><th>{sheet === "capex" ? "Amount (keur)" : "Amount (keur)"}</th>{sheet === "opex" && <th>Inflation %</th>}<th>Notes</th><th>State</th></tr></thead>
          <tbody>
            {data.lines.map((line) => {
              const stagedLine = staged[line.sub_line_id] || {};
              const value = (key: "label" | "amount_keur" | "inflation_pct" | "notes") => stagedLine[key] !== undefined ? stagedLine[key] : (line[key] as string | number | null);
              return (
                <tr key={line.sub_line_id} data-stale={!line.active || undefined}>
                  <td><input className="fm-input" aria-label={`Label for ${line.label}`} disabled={inFlight || !line.active || data.project.protected_reference} value={String(value("label") ?? "")} onChange={(e) => setStaged((s) => ({ ...s, [line.sub_line_id]: { ...s[line.sub_line_id], label: e.target.value } }))} /></td>
                  <td><input className="fm-input" inputMode="decimal" aria-label={`Amount for ${line.label}`} disabled={inFlight || !line.active || data.project.protected_reference} value={String(value("amount_keur") ?? "")} onChange={(e) => setStaged((s) => ({ ...s, [line.sub_line_id]: { ...s[line.sub_line_id], amount_keur: e.target.value } }))} /></td>
                  {sheet === "opex" && <td><input className="fm-input" inputMode="decimal" aria-label={`Inflation for ${line.label}`} disabled={inFlight || !line.active || data.project.protected_reference} value={String(value("inflation_pct") ?? "")} onChange={(e) => setStaged((s) => ({ ...s, [line.sub_line_id]: { ...s[line.sub_line_id], inflation_pct: e.target.value } }))} /></td>}
                  <td><input className="fm-input" aria-label={`Notes for ${line.label}`} disabled={inFlight || !line.active || data.project.protected_reference} value={String(value("notes") ?? "")} onChange={(e) => setStaged((s) => ({ ...s, [line.sub_line_id]: { ...s[line.sub_line_id], notes: e.target.value } }))} /></td>
                  <td>{line.active ? (staged[line.sub_line_id] ? "staged" : "committed") : "inactive"}</td>
                </tr>
              );
            })}
            {!data.lines.length && <tr><td colSpan={5}><span role="status">No line items were projected for this sheet.</span></td></tr>}
          </tbody>
        </table>
      </div>
      <div className="fm-toolbar" style={{ marginTop: 10 }}>
        <button type="button" className="fm-btn fm-btn-primary" disabled={inFlight || !stagedCount || data.project.protected_reference} onClick={saveBatch}>
          Save {stagedCount || ""} staged line{stagedCount === 1 ? "" : "s"} atomically
        </button>
        <button type="button" className="fm-btn" disabled={inFlight || !stagedCount} onClick={() => setStaged({})}>Discard staged edits</button>
      </div>
      <p className="fm-info-note">One atomic batch through the canonical writer: all lines persist or none; row versions are verified (409 on a concurrent change); the model is never run by a Save.</p>
    </section>
  );
}

// ───────────────────────────── UX-04: revenue / PPA (read-only) ─────────────────────────────

export function RevenueView({ project }: { project: string }) {
  const fetcher = useCallback(() => fetchRevenueContracts(project), [project]);
  const state = useCanonical(fetcher, [project]);
  if (state.state === "loading") return <LoadingNote />;
  if (state.state === "error") return <ErrorNote message={state.message} onRetry={state.retry} />;
  const data = state.data;
  return (
    <section className="fm-card fm-section" aria-label="Revenue and PPA contracts">
      <div className="fm-card-title"><h2>Revenue &amp; PPA contracts</h2><span>canonical contract state</span></div>
      <pre className="fm-mono" style={{ overflowX: "auto", padding: 10, background: "var(--surface)", border: "1px solid var(--line)" }}>
        {JSON.stringify(data.contracts, null, 2)}
      </pre>
      <div className="fm-banner" role="note">
        <span className="fm-demo-label">GATED EDITING</span>
        <span className="fm-banner-copy">The guided contract editor keeps its canonical form on the legacy workbook; its React editing contract is not established yet, so this surface is read-only. The canonical writer (POST /v2/workbook/revenue/contracts, composite CAS + bound CSRF) is documented for the next increment.</span>
      </div>
    </section>
  );
}

// ───────────────────────────── UX-05: Run + history ─────────────────────────────

export function RunsView({ project, contentHash, workbookVersion, onRan }: {
  project: string; contentHash?: string; workbookVersion?: string; onRan?: () => void;
}) {
  const fetcher = useCallback(() => fetchRuns(project), [project]);
  const state = useCanonical(fetcher, [project]);
  const [status, setStatus] = useState<{ tone: "ok" | "error" | "conflict"; text: string } | null>(null);
  const [inFlight, setInFlight] = useState(false);
  const data = state.state === "ready" ? state.data : null;
  const runsContract = data?.run_contract;
  const historyRows = data?.runs ?? [];

  const startRun = async () => {
    if (!runsContract || !contentHash || !workbookVersion) return;
    setInFlight(true);
    setStatus(null);
    const result = await runModel({ runUrl: runsContract.url, csrfToken: runsContract.csrf_token, project, contentHash, workbookVersion });
    setInFlight(false);
    if ("kind" in result) {
      setStatus({ tone: "conflict", text: result.message });
    } else if (result.ok) {
      setStatus({ tone: "ok", text: "Run committed from the canonical engine. Results come from the persisted evidence only." });
      state.retry();
      onRan?.();
    } else {
      setStatus({ tone: "error", text: result.message });
    }
  };

  if (state.state === "loading") return <LoadingNote />;
  if (state.state === "error") return <ErrorNote message={state.message} onRetry={state.retry} />;
  return (
    <section className="fm-card fm-section" aria-label="Run history">
      <div className="fm-card-title"><h2>Run history</h2><span>immutable committed evidence</span></div>
      {status && <div className="fm-info-note" role="status" data-tone={status.tone}>{status.text}</div>}
      <div className="fm-toolbar" style={{ marginBottom: 10 }}>
        <button type="button" className="fm-btn fm-btn-primary" disabled={inFlight || !contentHash || !workbookVersion}
          aria-describedby="run-contract-note" onClick={startRun}>
          {inFlight ? "Run in progress…" : "Run the model (canonical route)"}
        </button>
      </div>
      <p id="run-contract-note" className="fm-info-note">Runs through the existing <code>POST /v2/workbook/run</code> (composite CAS). Saving never starts a Run; a stale Working Copy refuses the Run instead of silently re-running old inputs.</p>
      <div className="fm-table-wrap">
        <table className="fm-table">
          <thead><tr><th>Ran at</th><th>Scenario</th><th>Origin</th><th>Engine</th><th>Identity</th></tr></thead>
          <tbody>
            {historyRows.map((run, index) => (
              <tr key={run.history_id ?? index}>
                <td className="fm-mono">{run.ran_at ?? "—"}</td>
                <td>{run.scenario_name ?? run.scenario_id ?? "—"}</td>
                <td>{run.origin ?? "—"}</td>
                <td>{run.engine_version ?? "—"}</td>
                <td className="fm-mono">{run.composite_identity ? String((run.composite_identity as Record<string, unknown>).composite_hash ?? "—") : "—"}</td>
              </tr>
            ))}
            {!historyRows.length && <tr><td colSpan={5}><span role="status">NOT RUN — no committed Run exists for this project yet.</span></td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ───────────────────────────── UX-06: diagnostics + trust ─────────────────────────────

function KeyValueBlocks(source: Record<string, unknown>, skip: Set<string>): Array<[string, unknown]> {
  return Object.entries(source).filter(([k]) => !skip.has(k));
}

export function DiagnosticsView({ project }: { project: string }) {
  const fetcher = useCallback(() => fetchDiagnostics(project), [project]);
  const state = useCanonical(fetcher, [project]);
  if (state.state === "loading") return <LoadingNote />;
  if (state.state === "error") return <ErrorNote message={state.message} onRetry={state.retry} />;
  const data = state.data;
  const insight = data.insight as Record<string, unknown>;
  const diagnostics = data.diagnostics as Record<string, unknown>;
  const checks = (diagnostics.checks as Array<Record<string, unknown>>) || [];
  const notClaims = String(insight.not_claims ?? "");
  return (
    <section className="fm-card fm-section" aria-label="Model checks and diagnostics">
      <div className="fm-card-title"><h2>Model checks &amp; diagnostics</h2><span>evaluated from the committed Last Run</span></div>
      <p className="fm-info-note" role="note">{notClaims}</p>
      <p className="fm-info-note"><strong>Run state: {String(insight.run_state ?? data.run_state)}</strong> · {String(insight.context_note ?? "")}</p>
      <div className="fm-table-wrap">
        <table className="fm-table">
          <thead><tr><th>Check</th><th>Status</th><th>Detail</th></tr></thead>
          <tbody>
            {checks.map((check, index) => (
              <tr key={String(check.check_id ?? index)}>
                <td>{String(check.label ?? check.check_id ?? index)}</td>
                <td>{String(check.status ?? "—")}</td>
                <td>{String(check.note ?? check.message ?? "—")}</td>
              </tr>
            ))}
            {!checks.length && <tr><td colSpan={3}><span role="status">{String(diagnostics.message ?? "No diagnostics were evaluated for this Run state.")}</span></td></tr>}
          </tbody>
        </table>
      </div>
      {KeyValueBlocks(diagnostics, new Set(["checks", "client_schema"])).map(([key, value]) => (
        <p key={key} className="fm-info-note"><strong>{key}:</strong> {typeof value === "object" ? JSON.stringify(value) : String(value)}</p>
      ))}
    </section>
  );
}

export function TrustView({ project }: { project: string }) {
  const fetcher = useCallback(() => fetchTrust(project), [project]);
  const state = useCanonical(fetcher, [project]);
  if (state.state === "loading") return <LoadingNote />;
  if (state.state === "error") return <ErrorNote message={state.message} onRetry={state.retry} />;
  const data = state.data;
  const section = (title: string, source: Record<string, unknown>) => (
    <div className="fm-card fm-section" style={{ marginBottom: 12 }}>
      <div className="fm-card-title"><h3>{title}</h3><span>{String(source.state ?? "—")}</span></div>
      {KeyValueBlocks(source, new Set(["state"])).map(([key, value]) => (
        <p key={key} className="fm-info-note"><strong>{key}:</strong> {typeof value === "object" ? JSON.stringify(value) : String(value)}</p>
      ))}
    </div>
  );
  return (
    <section aria-label="Trust and integrity evidence">
      {section("Run certificate", data.certificate)}
      {section("Validation evidence", data.validation)}
      <p className="fm-info-note">Trust sections come from the canonical evidence builders; an unavailable section is shown as UNAVAILABLE and is never presented as a pass.</p>
    </section>
  );
}
