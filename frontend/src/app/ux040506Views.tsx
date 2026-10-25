// UX-04/05/06 canonical surface views (CAPEX/OPEX batch editor, Run history, Diagnostics, Trust).
// The Financing/Revenue editors and the Run action moved to ./workflow in WF-React-2.  Presentation only: every value shown
// comes from a canonical JSON projection over the existing authorities, every
// mutation posts to the existing canonical writer route, and a surface whose
// backend contract is not established stays visibly gated — never fabricated.

import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchCostLines,
  fetchDiagnostics,
  fetchRuns,
  fetchTrust,
  saveCostLinesBatch,
} from "./api";
import type { PersistedIntegrity } from "./types";
import { CostLineManager } from "./workflow/CostLineManager";
import { useReportDirty } from "./workflow/workflowShared";

type FetchState<T> = { state: "loading" } | { state: "error"; message: string } | { state: "ready"; data: T };

type CanonicalFailure = { ok: false; code: string; message?: string };

function useCanonical<T>(fetcher: () => Promise<T | CanonicalFailure>, deps: unknown[]): FetchState<T> & { retry: () => void } {
  const [state, setState] = useState<FetchState<T>>({ state: "loading" });
  const [nonce, setNonce] = useState(0);
  const lastDeps = useRef<string>("");
  useEffect(() => {
    let live = true;
    // Stale-while-revalidate: a retry (after a committed change) keeps the current
    // data on screen so editors and their status messages are not unmounted; a
    // change of project/sheet/scope still starts from the loading state.
    const key = JSON.stringify(deps);
    const sameScope = lastDeps.current === key;
    lastDeps.current = key;
    setState((prev) => (sameScope && prev.state === "ready" ? prev : { state: "loading" }));
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

// ───────────────────────────── UX-04: CAPEX / OPEX line batches ─────────────────────────────

export function CostLinesView({ project, reloadKey = 0, onMutated }: { project: string; reloadKey?: number; onMutated?: () => void }) {
  const [sheet, setSheet] = useState<"capex" | "opex">("capex");
  const fetcher = useCallback(() => fetchCostLines(project, sheet), [project, sheet]);
  const state = useCanonical(fetcher, [project, sheet]);
  const retryCosts = state.retry;
  useEffect(() => { if (reloadKey > 0) retryCosts(); }, [reloadKey, retryCosts]);
  const [staged, setStaged] = useState<Record<string, { label?: string; amount_keur?: string; inflation_pct?: string; notes?: string }>>({});
  const [status, setStatus] = useState<{ tone: "ok" | "error" | "conflict"; text: string } | null>(null);
  const [inFlight, setInFlight] = useState(false);

  useEffect(() => { setStaged({}); setStatus(null); }, [sheet, project]);
  useReportDirty(`cost-lines-${sheet}`, Object.keys(staged).length);

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
      onMutated?.();
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
      <CostLineManager project={project} data={data} onChanged={() => { state.retry(); onMutated?.(); }} />
    </section>
  );
}

// ───────────────────────────── UX-05: Run + history ─────────────────────────────

export function RunsView({ project }: { project: string }) {
  const fetcher = useCallback(() => fetchRuns(project), [project]);
  const state = useCanonical(fetcher, [project]);
  const historyRows = state.state === "ready" ? state.data.runs : [];

  if (state.state === "loading") return <LoadingNote />;
  if (state.state === "error") return <ErrorNote message={state.message} onRetry={state.retry} />;
  return (
    <section className="fm-card fm-section" aria-label="Run history">
      <div className="fm-card-title"><h2>Run history</h2><span>immutable committed evidence</span></div>
      <p id="run-contract-note" className="fm-info-note">Runs are started from the status bar through the existing <code>POST /v2/workbook/run</code> (composite CAS). Saving never starts a Run; a stale Working Copy refuses the Run instead of silently re-running old inputs.</p>
      <div className="fm-table-wrap">
        <table className="fm-table">
          <thead><tr><th>Ran at</th><th>Scenario</th><th>Origin</th><th>Engine</th><th>Identity</th></tr></thead>
          <tbody>
            {historyRows.map((run, index) => (
              <tr key={run.history_id ?? index}>
                <td className="fm-mono">{run.ran_at ?? "—"}</td>
                <td>{run.active_scenario_name ?? run.active_scenario_id ?? "—"}</td>
                <td>{run.runtime_origin ?? "—"}</td>
                <td>{run.engine_version ?? "—"}</td>
                <td className="fm-mono">{run.composite_hash ?? "—"}<br /><span>Snapshot: {run.runtime_snapshot_id || "—"}</span></td>
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

function readable(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Unavailable";
  if (Array.isArray(value)) return value.map(readable).join("; ");
  if (typeof value === "object") return Object.entries(value as Record<string, unknown>)
    .map(([key, item]) => `${key.replace(/_/g, " ")}: ${readable(item)}`).join("; ");
  return String(value);
}

function IntegrityEvidence({ integrity }: { integrity: PersistedIntegrity | null }) {
  return <section className="fm-card fm-section" aria-label="Current Run integrity">
    <div className="fm-card-title"><h3>Current Run integrity</h3><span>{integrity?.overall ?? "UNAVAILABLE"}</span></div>
    <p className="fm-info-note">Internal consistency of the committed Run only. This is separate from input freshness, reference regression, certificate signing and FINCO Verify.</p>
    <p className="fm-info-note">Snapshot: <span className="fm-mono">{readable(integrity?.run_identity?.snapshot_id)}</span></p>
    <p className="fm-info-note">Checks: {readable(integrity?.counts)}</p>
    {integrity?.checks?.length ? <div className="fm-table-wrap"><table className="fm-table">
      <thead><tr><th>Check</th><th>Status</th><th>Detail</th></tr></thead>
      <tbody>{integrity.checks.map((check, index) => <tr key={String(check.check_id ?? index)}>
        <td>{readable(check.title ?? check.check_id)}</td><td>{readable(check.status)}</td>
        <td>{readable(check.reason_code ?? check.detail)}</td>
      </tr>)}</tbody>
    </table></div> : <p className="fm-info-note">No committed integrity checks are available.</p>}
  </section>;
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
      <IntegrityEvidence integrity={data.integrity} />
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
      <p className="fm-info-note">Diagnostics state: {readable(diagnostics.state)} · {checks.length} reported checks</p>
      <p className="fm-info-note">Evidence identity: {readable(diagnostics.identity)}</p>
    </section>
  );
}

export function TrustView({ project }: { project: string }) {
  const fetcher = useCallback(() => fetchTrust(project), [project]);
  const state = useCanonical(fetcher, [project]);
  if (state.state === "loading") return <LoadingNote />;
  if (state.state === "error") return <ErrorNote message={state.message} onRetry={state.retry} />;
  const data = state.data;
  return (
    <section aria-label="Trust and integrity evidence">
      <p className="fm-info-note">Run freshness: {data.run_state}. Snapshot: <span className="fm-mono">{readable(data.identity?.snapshot_id)}</span></p>
      <IntegrityEvidence integrity={data.integrity} />
      <section className="fm-card fm-section" aria-label="Reference regression evidence">
        <div className="fm-card-title"><h3>Reference regression evidence</h3><span>{data.validation.state}</span></div>
        <p className="fm-info-note">{data.validation.scope}</p>
        <p className="fm-info-note">Not executed by opening this page. A reference PASS is not validation of this project.</p>
        {data.validation.load_url ? <a className="fm-btn" href={data.validation.load_url} target="_blank" rel="noopener noreferrer">Explicitly run reference regression (separate evidence)</a>
          : <p className="fm-info-note">{data.validation.reason}</p>}
      </section>
      <section className="fm-card fm-section" aria-label="Run certificate">
        <div className="fm-card-title"><h3>Run certificate</h3><span>{data.certificate.state}</span></div>
        <p className="fm-info-note">{data.certificate.scope}</p>
        {data.certificate.load_url ? <a className="fm-btn" href={data.certificate.load_url} target="_blank" rel="noopener noreferrer">Explicitly request certificate (canonical route)</a>
          : <p className="fm-info-note">{data.certificate.reason}</p>}
      </section>
      <p className="fm-info-note">No project validation was triggered by this read. Unavailable evidence stays unavailable; none of these sections imply FINCO Verify.</p>
    </section>
  );
}
