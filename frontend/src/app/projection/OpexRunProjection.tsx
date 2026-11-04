import { useEffect, useRef, useState } from "react";
import { FriendlyError } from "../productLanguage";
import { showKeur } from "../costAmounts";
import { useCostUnit } from "../CostUnit";
import { useReportPrecision } from "../ReportPrecision";
import { RequestGate, type RequestIdentity } from "./opexRunRequest";

/** G10 Option A (Draft, gated) — Inputs > OPEX > Last Run: the committed immutable Run's own all-in operating
 *  expenses per financial period, read from the Run's persisted P&L evidence. The browser only lays the
 *  server's numbers out: a missing Run renders NOT_RUN and a missing statement renders NOT_AVAILABLE — never
 *  a zero and never a working-copy estimate. Freshness (CURRENT/STALE) is the server's runtime-authority
 *  verdict for the displayed history row.
 *
 *  Request lifecycle: every (project, reloadKey) change begins a NEW gated request (previous one aborted) and
 *  synchronously resets the panel to loading; a settled response is applied only when its identity is still
 *  the gate's current one, and the panel renders ONLY data whose identity matches the current props — a slow
 *  or out-of-order response can never show another project's Run evidence, not even transiently. */
interface RunIdentity {
  history_id: string; ran_at: string; engine_version: string | null; workbook_version: string | null;
  scenario_id: string | null; scenario_name: string | null; runtime_snapshot_id: string;
}
interface RunProjection {
  ok: true; unit: string; status: "OK" | "NOT_RUN" | "OPEX_STATEMENT_UNAVAILABLE" | "PANEL_DISABLED";
  run: RunIdentity | null; freshness: { state: string };
  years: Array<number | null>;
  periods: Array<{ period: number | null; date: string | null; operating_expenses_keur: number | null }>;
  basis: string;
}
type Failure = { code: string; message?: string };
type Stage =
  | { identity: RequestIdentity; phase: "loading" }
  | { identity: RequestIdentity; phase: "ready"; data: RunProjection }
  | { identity: RequestIdentity; phase: "failed"; failure: Failure };

async function load(project: string, signal: AbortSignal): Promise<RunProjection | Failure> {
  try {
    const response = await fetch(`/v2/model-react/opex-run-projection?${new URLSearchParams({ project })}`, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" }, signal });
    const body = await response.json().catch(() => null) as (RunProjection | (Failure & { ok: false })) | null;
    if (response.ok && body && body.ok === true) return body;
    return { code: (body as Failure | null)?.code ?? `HTTP_${response.status}`, message: (body as Failure | null)?.message };
  } catch {
    return { code: "SERVER_UNREACHABLE" };
  }
}

export function OpexRunProjection({ project, reloadKey }: { project: string; reloadKey: number }) {
  const [unit] = useCostUnit();
  const { precision } = useReportPrecision();
  const cell = (v: number | null | undefined) => (v === null || v === undefined || Number.isNaN(v) ? "—" : showKeur(v, unit, precision));
  const gateRef = useRef<RequestGate | null>(null);
  if (gateRef.current === null) gateRef.current = new RequestGate();
  const gate = gateRef.current;
  const [stage, setStage] = useState<Stage | null>(null);
  useEffect(() => {
    const { identity, signal } = gate.begin(project, reloadKey);
    setStage({ identity, phase: "loading" });            // synchronous reset: prior project's data is not renderable now
    void load(project, signal).then((result) => {
      if (!gate.isCurrent(identity)) return;             // stale/out-of-order response: never applied
      setStage("status" in result
        ? { identity, phase: "ready", data: result }
        : { identity, phase: "failed", failure: result });
    });
    return () => gate.cancel();
  }, [project, reloadKey, gate]);
  if (stage === null || stage.identity.project !== project || stage.identity.reloadKey !== reloadKey) {
    // Defence in depth: never render anything fetched for a different identity.
    return <p className="rx-boot-loading" role="status" data-opex-run="loading">Loading the Last-Run OPEX…</p>;
  }
  if (stage.phase === "failed") return <FriendlyError code={stage.failure.code} message={stage.failure.message} />;
  if (stage.phase === "loading") return <p className="rx-boot-loading" role="status" data-opex-run="loading">Loading the Last-Run OPEX…</p>;
  const data = stage.data;
  const stale = data.freshness.state === "STALE";
  if (data.status === "PANEL_DISABLED") {
    return <p className="rx-note" data-opex-run="disabled">The Last-Run OPEX panel is not enabled for this environment.</p>;
  }
  return (
    <section className="rx-card rcm-analysis" data-opex-run="ready" aria-label="Last-Run OPEX">
      <h3>Last Run — all-in OPEX by period</h3>
      {data.status === "NOT_RUN" ? (
        <p className="rx-note" data-opex-run="not_run">Not available: this project has no committed Run yet. Last-Run OPEX is shown only from a committed immutable Run — no estimate is made from the working copy.</p>
      ) : data.status === "OPEX_STATEMENT_UNAVAILABLE" ? (
        <p className="rx-note" data-opex-run="unavailable">Not available: the committed Run's evidence does not carry operating-expense periods. Nothing is invented in its place.</p>
      ) : (
        <>
          <dl className="rcm-facts" data-opex-run-identity="true">
            <div><dt>Run</dt><dd>{data.run?.history_id}</dd></div>
            <div><dt>Ran at</dt><dd>{data.run?.ran_at}</dd></div>
            <div><dt>Scenario</dt><dd>{data.run?.scenario_name ?? data.run?.scenario_id ?? "—"}</dd></div>
            <div><dt>Freshness</dt><dd data-opex-run-freshness={data.freshness.state}>{data.freshness.state}{stale ? " — inputs changed after this Run; save and Run again to refresh" : ""}</dd></div>
          </dl>
          <p className="rx-note">{data.basis}</p>
          <div className="rcm-scroll" tabIndex={0} role="region" aria-label="Last-Run OPEX by period">
            <table className="fm-table rcux-opex-proj" data-opex-run-table="true">
              <thead><tr><th scope="col">Period</th><th scope="col">Period end</th><th scope="col" className="fm-num">All-in OPEX ({unit})</th></tr></thead>
              <tbody>
                {data.periods.map((p, i) => (
                  <tr key={i} data-opex-run-period={p.period ?? i}>
                    <td>{p.period ?? "—"}</td>
                    <td>{p.date ?? "—"}</td>
                    <td className="fm-num" data-opex-run-cell={p.period ?? i}>{cell(p.operating_expenses_keur)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
