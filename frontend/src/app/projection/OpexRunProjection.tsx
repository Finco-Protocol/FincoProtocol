import { useEffect, useState } from "react";
import { FriendlyError } from "../productLanguage";
import { showKeur } from "../costAmounts";
import { useCostUnit } from "../CostUnit";
import { useReportPrecision } from "../ReportPrecision";

/** G10 Option A (Draft) — Inputs > OPEX > Last Run: the committed immutable Run's own all-in operating expenses per
 *  financial period, read from the Run's persisted P&L evidence. The browser only lays the server's numbers out:
 *  a missing Run renders NOT_RUN and a missing statement renders NOT_AVAILABLE — never a zero and never a
 *  working-copy estimate. Freshness (CURRENT/STALE) is the server's runtime-authority verdict, shown as-is. */
interface RunIdentity {
  history_id: string; ran_at: string; engine_version: string | null; workbook_version: string | null;
  scenario_id: string | null; scenario_name: string | null; runtime_snapshot_id: string;
}
interface RunProjection {
  ok: true; unit: string; status: "OK" | "NOT_RUN" | "OPEX_STATEMENT_UNAVAILABLE";
  run: RunIdentity | null; freshness: { state: string };
  years: Array<number | null>;
  periods: Array<{ period: number | null; date: string | null; operating_expenses_keur: number | null }>;
  basis: string;
}
type Failure = { code: string; message?: string };

async function load(project: string): Promise<RunProjection | Failure> {
  try {
    const response = await fetch(`/v2/model-react/opex-run-projection?${new URLSearchParams({ project })}`, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" } });
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
  const [data, setData] = useState<RunProjection | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  useEffect(() => {
    let live = true;
    void load(project).then((r) => { if (!live) return; if ("status" in r) { setData(r); setFailure(null); } else setFailure(r); });
    return () => { live = false; };
  }, [project, reloadKey]);
  if (failure) return <FriendlyError code={failure.code} message={failure.message} />;
  if (!data) return <p className="rx-boot-loading" role="status" data-opex-run="loading">Loading the Last-Run OPEX…</p>;
  const stale = data.freshness.state === "STALE";
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
