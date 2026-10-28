import { useEffect, useState } from "react";
import "../../styles/rcm-analysis.css";
import { FriendlyError } from "../productLanguage";

/** Inputs > Studios > OPEX projection (Y1 … Yn): the saved project's operating cost by group and year, exactly as the server projects it
 *  (line amounts, each line's escalation, applied contingency).  The browser only lays the numbers out; a year the server has no value for is shown as
 *  "—", never as 0. */
interface Projection {
  ok: true; unit: string; years: number[];
  rows: Array<{ code: string; name: string; derived: boolean; has_data: boolean; escalation: string; values: Array<number | null> }>;
  contingency: { rate_pct: number; by_year: Array<number | null> };
  totals: { excluding_contingency: Array<number | null>; including_contingency: Array<number | null> };
  kpis: { year1_total_keur: number | null; final_year_total_keur: number | null; per_mw_year1_keur: number | null; per_mwh_year1_eur: number | null };
  escalation: { value: string | null; label: string | null }; basis: string;
}
type Failure = { code: string; message?: string };

const cell = (v: number | null | undefined) => (v === null || v === undefined || Number.isNaN(v) ? "—" : v.toLocaleString("en-US", { maximumFractionDigits: 0 }));

async function load(project: string): Promise<Projection | Failure> {
  try {
    const response = await fetch(`/v2/model-react/opex-projection?${new URLSearchParams({ project })}`, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" } });
    const body = await response.json().catch(() => null) as (Projection | (Failure & { ok: false })) | null;
    if (response.ok && body && body.ok === true) return body;
    return { code: (body as Failure | null)?.code ?? `HTTP_${response.status}`, message: (body as Failure | null)?.message };
  } catch {
    return { code: "SERVER_UNREACHABLE" };
  }
}

export function OpexProjection({ project, reloadKey }: { project: string; reloadKey: number }) {
  const [data, setData] = useState<Projection | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  useEffect(() => {
    let live = true;
    void load(project).then((r) => { if (!live) return; if ("years" in r) { setData(r); setFailure(null); } else setFailure(r); });
    return () => { live = false; };
  }, [project, reloadKey]);
  if (failure) return <FriendlyError code={failure.code} message={failure.message} />;
  if (!data) return <p className="rx-boot-loading" role="status" data-opex-projection="loading">Loading the OPEX projection…</p>;
  const last = data.years[data.years.length - 1];
  return (
    <section className="rx-card rcm-analysis" data-opex-projection="ready" aria-label="OPEX projection">
      <h3>OPEX projection (Y1–Y{last})</h3>
      <p className="rx-note">Operating cost of the saved project by group and year, in {data.unit}. {data.basis}</p>
      <dl className="rcm-facts">
        <div><dt>Year 1 OPEX incl. contingency</dt><dd data-opex-y1="true">{cell(data.kpis.year1_total_keur)} {data.unit}</dd></div>
        <div><dt>Year {last} OPEX</dt><dd>{cell(data.kpis.final_year_total_keur)} {data.unit}</dd></div>
        <div><dt>OPEX per MW (Y1)</dt><dd>{data.kpis.per_mw_year1_keur === null ? "—" : data.kpis.per_mw_year1_keur.toFixed(2)} kEUR/MW</dd></div>
        <div><dt>Escalation</dt><dd>{data.escalation.value ?? "—"}{data.escalation.label ? ` · ${data.escalation.label}` : ""}</dd></div>
      </dl>
      <div className="rcm-scroll" tabIndex={0} role="region" aria-label="OPEX by group and year">
        <table className="fm-table rcux-opex-proj" data-opex-projection-table="true">
          <thead><tr><th scope="col">Code</th><th scope="col">Group</th>{data.years.map((y) => <th key={y} scope="col" className="fm-num">Y{y}</th>)}</tr></thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.code} data-opex-row={r.code} data-opex-has-data={r.has_data ? "true" : "false"}>
                <td>{r.code}</td><th scope="row">{r.name}{r.derived ? " (derived)" : ""}</th>
                {r.values.map((v, i) => <td key={i} className="fm-num" data-opex-cell={`${r.code}:${data.years[i]}`}>{cell(v)}</td>)}
              </tr>
            ))}
            <tr data-opex-row="contingency"><td></td><th scope="row">Applied contingency ({data.contingency.rate_pct.toFixed(1)}%)</th>{data.contingency.by_year.map((v, i) => <td key={i} className="fm-num">{cell(v)}</td>)}</tr>
            <tr data-opex-row="total"><td></td><th scope="row">Total OPEX</th>{data.totals.including_contingency.map((v, i) => <td key={i} className="fm-num" data-opex-total={data.years[i]}><strong>{cell(v)}</strong></td>)}</tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}
