import { useEffect, useState } from "react";
import "../../styles/rcm-analysis.css";
import { FriendlyError } from "../productLanguage";
import { groupDisplayName } from "../costGroupDisplay";
import { showKeur } from "../costAmounts";
import { useCostUnit } from "../CostUnit";
import { useReportPrecision } from "../ReportPrecision";

/** Inputs > Studios > OPEX projection (Y1 … Yn): the saved project's operating cost by group and year, exactly as the server projects it
 *  (line amounts, each line's escalation, applied contingency).  The browser only lays the numbers out; a year the server has no value for is shown as
 *  "—", never as 0. */
interface OperatingPreview {
  available: boolean;
  status: string;
  unit: string;
  authority: string;
  date_authority_version?: string;
  fingerprint?: { content_hash?: string | null; input_fingerprint?: string | null };
  freshness?: { state: string; matches_last_run: boolean; last_run_history_id?: string | null; last_run_ran_at?: string | null; is_draft_preview?: boolean };
  calendar_years: Array<{ calendar_year: number; has_operation: boolean; operating_expenses_keur: number; revenue_keur: number; ebitda_keur: number }>;
  operating_years: Array<{ operating_year: number; operating_expenses_keur: number; revenue_keur: number; ebitda_keur: number }>;
  kpis: {
    first_operating_calendar_year_opex_keur: number | null;
    first_operating_calendar_year: number | null;
    final_operating_calendar_year_opex_keur: number | null;
    first_operating_year_opex_keur: number | null;
    final_operating_year_opex_keur: number | null;
    total_operating_opex_keur: number;
    total_operating_revenue_keur: number;
    total_operating_ebitda_keur: number;
  } | null;
  scope_note: string;
  message?: string;
}

interface Projection {
  ok: true; unit: string; years: number[];
  rows: Array<{ code: string; name: string; derived: boolean; has_data: boolean; escalation: string; values: Array<number | null> }>;
  contingency: { rate_pct: number; by_year: Array<number | null> };
  totals: { excluding_contingency: Array<number | null>; including_contingency: Array<number | null> };
  kpis: { year1_total_keur: number | null; final_year_total_keur: number | null; per_mw_year1_keur: number | null; per_mwh_year1_eur: number | null };
  escalation: { value: string | null; label: string | null }; basis: string;
  operating_preview?: OperatingPreview;
}
type Failure = { code: string; message?: string };


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
  const [unit] = useCostUnit();
  const { precision } = useReportPrecision();
  // Amounts follow the chosen unit and report precision (default kEUR, 0 decimals); the server numbers are only re-expressed.
  const cell = (v: number | null | undefined) => (v === null || v === undefined || Number.isNaN(v) ? "—" : showKeur(v, unit, precision));
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
  const op = data.operating_preview;
  const freshLabel = op?.freshness
    ? (op.freshness.matches_last_run
      ? `Draft matches Last Run (${op.freshness.last_run_history_id?.slice(0, 8) ?? "CURRENT"})`
      : op.freshness.state === "STALE"
        ? `Draft preview (Last Run ${op.freshness.last_run_history_id?.slice(0, 8) ?? ""} is STALE)`
        : "Draft preview (No committed Run yet)")
    : "Draft preview";
  return (
    <section className="rx-card rcm-analysis" data-opex-projection="ready" aria-label="OPEX projection">
      <h3>Nominal annual OPEX budget (Y1–Y{last})</h3>
      <p className="rx-note">Nominal full-year operating cost budget of the saved project by group and operating year, in {unit}. {data.basis}</p>
      <p className="rx-note" data-opex-years-scope="true">These are the project's nominal annual line items by year. The six group base amounts (first row of their group on the Lines view) are added by the model when it runs and are not part of this budget table.</p>
      <dl className="rcm-facts">
        <div><dt>Year 1 nominal budget incl. contingency</dt><dd data-opex-y1="true">{cell(data.kpis.year1_total_keur)} {unit}</dd></div>
        <div><dt>Year {last} nominal budget</dt><dd>{cell(data.kpis.final_year_total_keur)} {unit}</dd></div>
        <div><dt>Line items per MW (Y1 nominal)</dt><dd>{cell(data.kpis.per_mw_year1_keur)} {unit}/MW</dd></div>
        <div><dt>Escalation</dt><dd>{data.escalation.value ?? "—"}{data.escalation.label ? ` · ${data.escalation.label}` : ""}</dd></div>
      </dl>
      <div className="rcm-scroll" tabIndex={0} role="region" aria-label="OPEX by group and year">
        <table className="fm-table rcux-opex-proj" data-opex-projection-table="true">
          <thead><tr><th scope="col">Group</th>{data.years.map((y) => <th key={y} scope="col" className="fm-num">Y{y}</th>)}</tr></thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.code} data-opex-row={r.code} data-opex-has-data={r.has_data ? "true" : "false"}>
                <th scope="row">{groupDisplayName(r.code, r.name)}{r.derived ? " (calculated)" : ""}</th>
                {r.values.map((v, i) => <td key={i} className="fm-num" data-opex-cell={`${r.code}:${data.years[i]}`}>{cell(v)}</td>)}
              </tr>
            ))}
            <tr data-opex-row="contingency"><th scope="row">Applied contingency ({data.contingency.rate_pct.toFixed(1)}%)</th>{data.contingency.by_year.map((v, i) => <td key={i} className="fm-num">{cell(v)}</td>)}</tr>
            <tr data-opex-row="total"><th scope="row">Total nominal annual budget</th>{data.totals.including_contingency.map((v, i) => <td key={i} className="fm-num" data-opex-total={data.years[i]}><strong>{cell(v)}</strong></td>)}</tr>
          </tbody>
        </table>
      </div>
      {op && (
        <div className="rcm-analysis" style={{ marginTop: "1rem" }} data-opex-operating-preview={op.status}>
          <h4>Calculated operating preview (canonical period basis)</h4>
          <p className="rx-note" data-opex-preview-freshness="true">
            {freshLabel}
            {op.fingerprint?.content_hash ? ` · hash ${op.fingerprint.content_hash.slice(0, 8)}` : ""}
            {op.date_authority_version ? ` · ${op.date_authority_version}` : ""}
          </p>
          <p className="rx-note">{op.scope_note}</p>
          {!op.available ? (
            <p className="rx-note" role="status" data-opex-preview-unavailable="true">{op.message ?? op.status}</p>
          ) : (
            <>
              <dl className="rcm-facts">
                <div>
                  <dt>First operating calendar year OPEX ({op.kpis?.first_operating_calendar_year ?? "Y1"})</dt>
                  <dd data-opex-preview-cal-y1="true">{cell(op.kpis?.first_operating_calendar_year_opex_keur)} {unit}</dd>
                </div>
                <div>
                  <dt>Operating Year 1 OPEX</dt>
                  <dd data-opex-preview-op-y1="true">{cell(op.kpis?.first_operating_year_opex_keur)} {unit}</dd>
                </div>
                <div>
                  <dt>Total operating OPEX</dt>
                  <dd>{cell(op.kpis?.total_operating_opex_keur)} {unit}</dd>
                </div>
                <div>
                  <dt>Total operating EBITDA (pre-tax/financing)</dt>
                  <dd>{cell(op.kpis?.total_operating_ebitda_keur)} {unit}</dd>
                </div>
              </dl>
              <div className="rcm-scroll" tabIndex={0} role="region" aria-label="Canonical operating preview by calendar year">
                <table className="fm-table rcux-opex-proj" data-opex-operating-preview-table="true">
                  <thead>
                    <tr>
                      <th scope="col">Calendar metric</th>
                      {op.calendar_years.map((c) => <th key={c.calendar_year} scope="col" className="fm-num">{c.calendar_year}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    <tr data-opex-preview-row="opex">
                      <th scope="row">Canonical OPEX</th>
                      {op.calendar_years.map((c) => <td key={c.calendar_year} className="fm-num" data-opex-preview-cal-cell={c.calendar_year}>{cell(c.operating_expenses_keur)}</td>)}
                    </tr>
                    <tr data-opex-preview-row="revenue">
                      <th scope="row">Canonical Revenue</th>
                      {op.calendar_years.map((c) => <td key={c.calendar_year} className="fm-num">{cell(c.revenue_keur)}</td>)}
                    </tr>
                    <tr data-opex-preview-row="ebitda">
                      <th scope="row">Canonical EBITDA</th>
                      {op.calendar_years.map((c) => <td key={c.calendar_year} className="fm-num">{cell(c.ebitda_keur)}</td>)}
                    </tr>
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
