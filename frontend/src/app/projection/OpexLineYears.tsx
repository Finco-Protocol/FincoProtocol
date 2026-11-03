import { useEffect, useState } from "react";
import { FriendlyError } from "../productLanguage";
import { groupDisplayName } from "../costGroupDisplay";
import { showKeur } from "../costAmounts";
import { useCostUnit } from "../CostUnit";
import { useReportPrecision } from "../ReportPrecision";

/** PR-U2b — Inputs > OPEX > Years, per saved line. The server passes through the same view model the group projection is built from; the browser
 *  only lays the numbers out. Saved lines, technology-driven rows and the six group base amounts are shown apart; nothing is an all-in OPEX figure. */
type Series = Array<number | null>;
interface LineRow { sub_line_id: string; label: string; y1_keur: number; inflation_pct: number; values: Series; source: "saved_line" }
interface DriverRow { label: string; values: Series; source: "technology_driver" }
interface Group {
  code: string; name: string; derived: boolean; has_data: boolean; values: Series; lines: LineRow[]; drivers: DriverRow[];
  placeholder_rows_not_listed: number; reconciles: boolean | null;
}
interface Base { group: string; field_id: string; value: string; editable: boolean; used_by_run: boolean; note: string | null }
interface Payload {
  ok: true; unit: string; years: number[]; groups: Group[]; contingency: { rate_pct: number; by_year: Series };
  totals: { excluding_contingency: Series; including_contingency: Series }; bases: unknown; basis: string;
}
type Failure = { code: string; message?: string };

async function load(project: string): Promise<Payload | Failure> {
  try {
    const r = await fetch(`/v2/model-react/opex-projection/lines?${new URLSearchParams({ project })}`, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" } });
    const body = await r.json().catch(() => null) as (Payload | (Failure & { ok: false })) | null;
    if (r.ok && body && body.ok === true) return body;
    return { code: (body as Failure | null)?.code ?? `HTTP_${r.status}`, message: (body as Failure | null)?.message };
  } catch {
    return { code: "SERVER_UNREACHABLE" };
  }
}

function baseRows(bases: unknown): Base[] {
  return Array.isArray(bases) ? (bases as Base[]) : [];
}

export function OpexLineYears({ project, reloadKey }: { project: string; reloadKey: number }) {
  const [unit] = useCostUnit();
  const { precision } = useReportPrecision();
  const cell = (v: number | null | undefined) => (v === null || v === undefined || Number.isNaN(v) ? "—" : showKeur(v, unit, precision));
  const [data, setData] = useState<Payload | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  useEffect(() => {
    let live = true;
    void load(project).then((r) => { if (!live) return; if ("years" in r) { setData(r); setFailure(null); } else setFailure(r); });
    return () => { live = false; };
  }, [project, reloadKey]);
  if (failure) return <FriendlyError code={failure.code} message={failure.message} />;
  if (!data) return <p className="rx-boot-loading" role="status" data-opex-lines="loading">Loading OPEX lines by year…</p>;
  const bases = baseRows(data.bases);
  return (
    <section className="rx-card rcm-analysis" data-opex-lines="ready" aria-label="OPEX lines by year">
      <h3>OPEX lines by year</h3>
      <p className="rx-note" data-opex-lines-basis="true">{data.basis}</p>
      <div className="rcm-scroll" tabIndex={0} role="region" aria-label="OPEX by saved line and year">
        <table className="fm-table rcux-opex-proj" data-opex-lines-table="true">
          <thead><tr><th scope="col">Line</th><th scope="col" className="fm-num">Escalation</th>{data.years.map((y) => <th key={y} scope="col" className="fm-num">Y{y}</th>)}</tr></thead>
          <tbody>
            {data.groups.filter((g) => !g.derived).map((g) => [
              <tr key={g.code} className="u2-opex-group" data-opex-line-group={g.code} data-opex-reconciles={g.reconciles === null ? "unknown" : String(g.reconciles)}>
                <th scope="row"><strong>{groupDisplayName(g.code, g.name)}</strong>{g.reconciles === false ? " — lines do not add up to the group; reload" : ""}</th>
                <td />
                {g.values.map((v, i) => <td key={i} className="fm-num"><strong>{cell(v)}</strong></td>)}
              </tr>,
              ...g.lines.map((l) => (
                <tr key={l.sub_line_id} data-opex-line={l.sub_line_id} data-opex-line-source="saved_line">
                  <th scope="row" className="u2-opex-line">{l.label}</th>
                  <td className="fm-num">{l.inflation_pct}%</td>
                  {l.values.map((v, i) => <td key={i} className="fm-num">{cell(v)}</td>)}
                </tr>)),
              ...g.drivers.map((d, n) => (
                <tr key={`${g.code}-d${n}`} data-opex-line-source="technology_driver">
                  <th scope="row" className="u2-opex-line">{d.label} <span className="rx-note">(from technology inputs, read-only)</span></th>
                  <td />
                  {d.values.map((v, i) => <td key={i} className="fm-num">{cell(v)}</td>)}
                </tr>)),
            ])}
            <tr data-opex-lines-row="contingency"><th scope="row">Applied contingency ({data.contingency.rate_pct.toFixed(1)}%)</th><td />{data.contingency.by_year.map((v, i) => <td key={i} className="fm-num">{cell(v)}</td>)}</tr>
            <tr data-opex-lines-row="total"><th scope="row">Total of line items</th><td />{data.totals.including_contingency.map((v, i) => <td key={i} className="fm-num"><strong>{cell(v)}</strong></td>)}</tr>
          </tbody>
        </table>
      </div>
      {bases.length > 0 && (
        <div data-opex-lines-bases="true">
          <h4>Group base amounts (Year 1, not in the rows above)</h4>
          <table className="fm-table">
            <thead><tr><th scope="col">Group</th><th scope="col" className="fm-num">Year 1</th><th scope="col">Used by the Run</th></tr></thead>
            <tbody>
              {bases.map((b) => {
                const n = b.value === "" ? null : Number(b.value);
                return (
                  <tr key={b.field_id} data-opex-base={b.field_id} data-opex-base-used={b.used_by_run ? "true" : "false"}>
                    <th scope="row">{groupDisplayName(b.group, b.group)}</th>
                    <td className="fm-num">{n === null || !Number.isFinite(n) ? "—" : cell(n)}</td>
                    <td>{b.used_by_run ? "Yes, added when the model runs" : (b.note ?? "No")}</td>
                  </tr>);
              })}
            </tbody>
          </table>
        </div>)}
    </section>
  );
}
