// UX-07 — scenario management, assumption compare and the revenue contract
// editor.  Every mutation posts to the EXISTING canonical scenario/contract
// form routes; creating or selecting a scenario never starts a Run; KPI
// deltas are not computed in the browser (persisted evidence projections
// carry them).

import { useCallback, useEffect, useState } from "react";
import { fetchScenarioCompare, fetchScenarios, saveRevenueContracts } from "./api";

type FetchState<T> = { state: "loading" } | { state: "error"; message: string } | { state: "ready"; data: T };

function useCanonicalView<T>(fetcher: () => Promise<T | { ok: false; code: string; message?: string }>, deps: unknown[]): FetchState<T> & { retry: () => void } {
  const [state, setState] = useState<FetchState<T>>({ state: "loading" });
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    let live = true;
    setState({ state: "loading" });
    fetcher().then((result: T | { ok: false; code: string; message?: string }) => {
      if (!live) return;
      if (!result || (result as { ok?: unknown }).ok !== true) {
        const failure = result as { code: string; message?: string };
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

function Note({ message, tone }: { message: string; tone: "ok" | "error" | "conflict" }) {
  return <div className="fm-info-note" role="status" data-tone={tone}>{message}</div>;
}

async function postScenarioForm(
  url: string,
  fields: Record<string, string>,
): Promise<{ outcome: "ok" | "refused" | "unknown"; message: string }> {
  const body = new URLSearchParams(fields);
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      redirect: "follow",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    });
  } catch {
    return { outcome: "unknown", message: "The scenario outcome is UNKNOWN: the connection failed before a definitive response. Reload to reconcile — do not re-submit blindly." };
  }
  // Direct canonical JSON answers (validation / auth / conflict) are refusals
  // with the backend's own message — never UNKNOWN, never success.
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    try {
      const payload = (await response.json()) as { error?: string };
      if (payload && payload.error) return { outcome: "refused", message: payload.error };
    } catch { /* fall through to destination classification */ }
    return { outcome: "refused", message: `The scenario action was refused (HTTP ${response.status}).` };
  }
  let finalUrl: URL;
  try {
    finalUrl = new URL(response.url);
  } catch {
    return { outcome: "unknown", message: "The scenario outcome is UNKNOWN: the response destination could not be read. Reload to reconcile." };
  }
  if (finalUrl.pathname === "/login") {
    return { outcome: "refused", message: "Your session has expired — sign in again. Nothing was changed." };
  }
  const v2Err = finalUrl.searchParams.get("v2_err");
  if (v2Err !== null) return { outcome: "refused", message: v2Err };
  if (finalUrl.pathname !== "/v2/workbook") {
    return { outcome: "unknown", message: `The scenario outcome is UNKNOWN: unexpected destination (${finalUrl.pathname}). Reload to reconcile.` };
  }
  return { outcome: "ok", message: "Scenario updated through the canonical authority. No Run was started." };
}

export function ScenarioView({ project, onScenarioChanged }: { project: string; onScenarioChanged?: () => void }) {
  const fetcher = useCallback(() => fetchScenarios(project), [project]);
  const state = useCanonicalView(fetcher, [project]);
  const [newName, setNewName] = useState("");
  const [status, setStatus] = useState<{ tone: "ok" | "error" | "conflict"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [compareId, setCompareId] = useState("");

  const act = async (url: string, fields: Record<string, string>) => {
    setBusy(true);
    setStatus(null);
    const result = await postScenarioForm(url, fields);
    if (result.outcome === "ok") {
      // Reconcile through a fresh authorized scenarios projection before
      // claiming success: the canonical redirect alone is not commit evidence.
      const fresh = await fetchScenarios(project);
      if (fresh.ok === true) {
        setStatus({ tone: "ok", text: `${result.message} (verified against the fresh projection)` });
        state.retry();
        onScenarioChanged?.();
      } else {
        setStatus({ tone: "conflict", text: "The scenario action answered success, but the fresh projection could not confirm it. Reload to reconcile — do not re-submit blindly." });
      }
    } else {
      setStatus({ tone: result.outcome === "unknown" ? "conflict" : "error", text: result.message });
    }
    setBusy(false);
  };

  if (state.state === "loading") return <p className="fm-info-note" role="status">Loading scenarios…</p>;
  if (state.state === "error") {
    return (
      <section className="fm-card fm-section" aria-label="Scenarios">
        <div className="fm-card-title"><h2>Scenarios</h2></div>
        <div className="fm-banner" role="alert"><span className="fm-demo-label">UNAVAILABLE</span><span className="fm-banner-copy">{state.message}</span></div>
        <button type="button" className="fm-btn" onClick={state.retry}>Retry</button>
      </section>
    );
  }
  const data = state.data;
  return (
    <section className="fm-card fm-section" aria-label="Scenario management">
      <div className="fm-card-title"><h2>Scenarios</h2><span>canonical scenario authority · a selection never runs the model</span></div>
      {data.project.protected_reference && <div className="fm-banner" role="note"><span className="fm-demo-label">PROTECTED REFERENCE</span><span className="fm-banner-copy">References have a single immutable case; scenario management applies to Working Copies.</span></div>}
      <fieldset className="fm-readonly-fieldset" disabled={Boolean(data.project.protected_reference)} aria-label="Scenario actions (disabled on protected references)"><legend className="fm-sr-only">Scenario actions</legend>
      {status && <Note message={status.text} tone={status.tone} />}
      <div className="fm-table-wrap">
        <table className="fm-table">
          <thead><tr><th>Scenario</th><th>State</th><th>Overrides</th><th>Updated</th><th>Actions</th></tr></thead>
          <tbody>
            {data.scenarios.map((s) => (
              <tr key={s.scenario_id}>
                <td>{s.name} {s.active && <strong data-active-scenario="true">· active</strong>}</td>
                <td>{s.is_base_case ? "Base Case" : s.archived ? "archived" : "child scenario"}</td>
                <td>{s.override_count}</td>
                <td className="fm-mono">{s.updated_at ?? "—"}</td>
                <td>
                  <span className="fm-toolbar">
                    {!s.active && !s.archived && (
                      <button type="button" className="fm-btn" disabled={busy} aria-label={`Select scenario ${s.name}`}
                        onClick={() => act(data.mutations.select.url, { project, scenario_id: s.scenario_id })}>Select</button>
                    )}
                    {!s.is_base_case && !s.archived && (
                      <>
                        <button type="button" className="fm-btn" disabled={busy} aria-label={`Rename scenario ${s.name}`}
                          onClick={() => {
                            const next = window.prompt(`Rename scenario ${s.name} to:`, s.name);
                            if (next && next.trim() && next !== s.name) act(data.mutations.rename.url, { project, scenario_id: s.scenario_id, new_name: next.trim() });
                          }}>Rename</button>
                        <button type="button" className="fm-btn" disabled={busy} aria-label={`Archive scenario ${s.name}`}
                          onClick={() => act(data.mutations.archive.url, { project, scenario_id: s.scenario_id })}>Archive</button>
                      </>
                    )}
                    <button type="button" className="fm-btn" aria-label={`Compare with scenario ${s.name}`}
                      aria-pressed={compareId === s.scenario_id}
                      onClick={() => setCompareId(compareId === s.scenario_id ? "" : s.scenario_id)}>Compare</button>
                  </span>
                </td>
              </tr>
            ))}
            {!data.scenarios.length && <tr><td colSpan={5}><span role="status">No scenarios exist yet — only the Base Case is present.</span></td></tr>}
          </tbody>
        </table>
      </div>
      {!data.project.protected_reference && (
        <div className="fm-toolbar" style={{ marginTop: 10 }}>
          <input className="fm-input" aria-label="New scenario name" placeholder="New scenario name"
            value={newName} onChange={(e) => setNewName(e.target.value)} />
          <button type="button" className="fm-btn fm-btn-primary" disabled={busy || !newName.trim()}
            aria-label="Create scenario"
            onClick={() => act(data.mutations.create.url, { project, scenario_name: newName.trim() }).then(() => setNewName(""))}>
            Create scenario
          </button>
        </div>
      )}
      <p className="fm-info-note">{data.mutations.note}</p>
      </fieldset>
      {compareId && <ScenarioCompareView project={project} scenarioId={compareId} />}
    </section>
  );
}

export function ScenarioCompareView({ project, scenarioId }: { project: string; scenarioId: string }) {
  const fetcher = useCallback(() => fetchScenarioCompare(project, scenarioId), [project, scenarioId]);
  const state = useCanonicalView(fetcher, [project, scenarioId]);
  if (state.state === "loading") return <p className="fm-info-note" role="status">Building the assumption compare…</p>;
  if (state.state === "error") return <Note message={state.message} tone="error" />;
  const data = state.data;
  return (
    <div className="fm-card fm-section" style={{ marginTop: 12 }} aria-label="Scenario assumption compare">
      <div className="fm-card-title"><h3>Assumption compare</h3>
        <span>{data.base.label} vs {data.scenario?.label ?? "selected scenario"}</span>
      </div>
      <div className="fm-table-wrap">
        <table className="fm-table">
          <thead><tr><th>Field</th><th>{data.base.label}</th><th>{data.scenario?.label ?? "Scenario"}</th></tr></thead>
          <tbody>
            {data.differences.map((d) => (
              <tr key={d.field_id}>
                <td className="fm-mono">{d.field_id}</td>
                <td>{d.base_value === null || d.base_value === undefined ? "—" : String(d.base_value)}</td>
                <td>{d.scenario_value === null || d.scenario_value === undefined ? "—" : String(d.scenario_value)}</td>
              </tr>
            ))}
            {!data.differences.length && <tr><td colSpan={3}><span role="status">No assumption differences — the scenario matches the Working Copy on every stored field.</span></td></tr>}
          </tbody>
        </table>
      </div>
      <p className="fm-info-note">
        Persisted Run evidence: {data.base.last_run_snapshot_id ? `Base side Last Run ${data.base.last_run_snapshot_id.slice(0, 12)}` : "Base side has NO persisted Run"} ·{" "}
        {data.scenario?.last_run_snapshot_id ? `scenario Run ${data.scenario.last_run_snapshot_id.slice(0, 12)}` : "scenario side has NO persisted Run"}.
        {data.kpi_compare.reason}
      </p>
    </div>
  );
}

// ───────────────────── UX-07: revenue contract editor ─────────────────────

export function RevenueEditorView({ project, revenuePayload, onSaved }: {
  project: string;
  revenuePayload: { contracts: Record<string, unknown>; save: { url: string; csrf_token: string; content_hash: string; workbook_version: string } };
  onSaved?: () => void;
}) {
  // Correction B: the canonical contract payload lives in `contracts.raw` (the
  // string the writer validates).  The surrounding editor projection carries
  // presentation metadata that must NOT be submitted.  A project without an
  // existing contract configuration shows an explicit empty state — no
  // synthetic default contract is ever invented here.
  const contracts = revenuePayload.contracts as {
    active?: boolean; raw?: string; scope?: string; technology?: string; overridden?: boolean;
  };
  const hasContract = contracts.active === true && typeof contracts.raw === "string" && contracts.raw.trim() !== "";
  const initial = hasContract ? prettyOrRaw(contracts.raw as string) : "";
  const [draft, setDraft] = useState(initial);
  const [status, setStatus] = useState<{ tone: "ok" | "error" | "conflict"; text: string } | null>(null);
  const [inFlight, setInFlight] = useState(false);
  const dirty = hasContract && draft !== initial;

  function prettyOrRaw(raw: string): string {
    try {
      return JSON.stringify(JSON.parse(raw), null, 2);
    } catch {
      return raw; // the canonical writer decides; never pre-mutate
    }
  }

  const syntaxProblem = dirty ? (() => { try { JSON.parse(draft); return null; } catch (e) { return `Invalid JSON syntax: ${(e as Error).message}`; } })() : null;

  const save = async () => {
    if (syntaxProblem) {
      setStatus({ tone: "error", text: syntaxProblem });
      return;
    }
    setInFlight(true);
    setStatus(null);
    const result = await saveRevenueContracts({
      saveUrl: revenuePayload.save.url,
      project,
      csrfToken: revenuePayload.save.csrf_token,
      contentHash: revenuePayload.save.content_hash,
      contractsJson: draft,
    });
    setInFlight(false);
    if ("kind" in result) {
      setStatus({ tone: "conflict", text: result.message });
    } else if (result.ok) {
      setStatus({ tone: "ok", text: "Revenue contracts saved atomically through the canonical writer. No Run was started." });
      onSaved?.();
    } else {
      setStatus({ tone: "error", text: result.message });
    }
  };

  return (
    <section className="fm-card fm-section" aria-label="Revenue and PPA contract editor">
      <div className="fm-card-title"><h3>Revenue contract editor</h3><span>canonical payload · validated by the writer</span></div>
      {status && <Note message={status.text} tone={status.tone} />}
      {!hasContract ? (
        <div className="fm-banner" role="note">
          <span className="fm-demo-label">NO CONTRACT CONFIGURED</span>
          <span className="fm-banner-copy">This project has no revenue contract payload yet. The canonical guided PPA form in the legacy workbook creates one; this editor never invents a default contract, because that could change financial economics.</span>
        </div>
      ) : (
        <label className="fm-field">
          <span className="fm-field-label">Canonical contracts payload — scope: {String(contracts.scope ?? "unknown")} · technology: {String(contracts.technology ?? "unknown")}{contracts.overridden ? " · scenario-overridden" : ""} (validated server-side)</span>
          <textarea className="fm-input" rows={14} spellCheck={false} data-revenue-editor="true"
            style={{ width: "100%", fontFamily: "var(--font-mono, monospace)", fontSize: 11 }}
            value={draft} disabled={inFlight}
            onChange={(e) => setDraft(e.target.value)} />
        </label>
      )}
      {syntaxProblem && <div className="fm-banner" role="alert"><span className="fm-demo-label">JSON SYNTAX</span><span className="fm-banner-copy">{syntaxProblem}</span></div>}
      <div className="fm-toolbar" style={{ marginTop: 8 }}>
        <button type="button" className="fm-btn fm-btn-primary" disabled={inFlight || !dirty}
          aria-label="Save revenue contracts" onClick={save}>
          Save contracts atomically
        </button>
        <button type="button" className="fm-btn" disabled={inFlight || !dirty} onClick={() => setDraft(initial)}>Discard edits</button>
      </div>
      <p className="fm-info-note">
        The payload is validated by the canonical contract writer (typed stream rules, indexation start, rounding);
        a rejected save changes nothing. Composite CAS applies — a stale payload answers 409 and must be reloaded.
        The guided PPA form remains available in the legacy workbook.
      </p>
    </section>
  );
}
