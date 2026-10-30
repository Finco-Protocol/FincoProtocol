import { useEffect, useState } from "react";
import { TimeSeriesChart, useModels } from "./FinancialResults";
import type { StatementsPayload } from "./types";
import type { SourcesUsesView, SuRow } from "./financing/types";
import { useReportPrecision } from "./ReportPrecision";
import { reportAmount, reportMetric, reportUnitText } from "./reportFormatting";
import { RunIdentityLabel } from "./runIdentity";
import { debtMetricsHref, prepareDebtMetrics } from "./debtmetrics/debtMetricsLink";

export interface OverviewSupplement {
  ok: true;
  project: { code: string };
  snapshot_id: string | null;
  content_hash: string | null;
  scenario_id: string | null;
  assumptions: Array<{ field_id: string; label: string; display: string; unit: string; available: boolean; value: number | null }>;
  sources_uses: { available: boolean; view?: SourcesUsesView; reason?: string };
}

function AmountRows({ rows, total }: { rows: SuRow[]; total: SourcesUsesView["total_sources"] }) {
  const { precision } = useReportPrecision();
  const sum = total && typeof total === "object" ? total : null;
  return <table className="rx-table"><thead><tr><th scope="col">Item</th><th scope="col">kEUR</th></tr></thead>
    <tbody>{rows.map((row) => <tr key={row.authority || row.label}><th scope="row" title={row.reason || row.authority}>{row.label}</th>
      <td title={row.value == null ? undefined : String(row.value)}>{row.value == null ? "Unavailable" : reportAmount(row.value, precision)}</td></tr>)}</tbody>
    <tfoot><tr><th scope="row">{sum?.label || "Total"}</th><td>{sum?.value == null ? "Unavailable" : reportAmount(sum.value, precision)}</td></tr></tfoot></table>;
}

/** Composes only statements and a supplement bound to that same immutable Run. */
export function FinancialOverview({ project, payload }: { project: string; payload: StatementsPayload }) {
  const models = useModels(payload);
  const { precision } = useReportPrecision();
  const [read, setRead] = useState<{ snapshot: string; data: OverviewSupplement | null } | null>(null);
  const snapshot = payload.status.runId;
  useEffect(() => {
    const controller = new AbortController();
    if (!payload.snapshot) return;
    void (async () => {
      try {
        const response = await fetch(`/v2/model-react/overview?project=${encodeURIComponent(project)}`, {
          credentials: "same-origin", cache: "no-store", signal: controller.signal, headers: { Accept: "application/json" },
        });
        const body = await response.json() as OverviewSupplement;
        if (!controller.signal.aborted) setRead({ snapshot, data: response.ok && body.ok && body.project.code === project && body.snapshot_id === snapshot ? body : null });
      } catch { if (!controller.signal.aborted) setRead({ snapshot, data: null }); }
    })();
    return () => controller.abort();
  }, [project, snapshot, payload.snapshot]);
  const supplement = read?.snapshot === snapshot ? read.data : null;
  const integrity = payload.integrity?.status ?? payload.status.integrity;
  const usable = payload.snapshot && (payload.state === "CURRENT" || payload.state === "STALE");
  const sources = supplement?.sources_uses;
  const cash = models.charts.find((chart) => chart.id === "overview-waterfall");
  const dscr = models.charts.find((chart) => chart.id === "dscr");

  return <section data-financial-overview="true" data-overview-snapshot={usable ? snapshot : ""}>
    <div className="wsv2-overview-heading"><h2>Financial Overview</h2><span className="rx-badge">{payload.state === "NOT_RUN" ? "NOT RUN" : payload.state}</span></div>
    {usable && <p className="rx-note">Last Run: <RunIdentityLabel snapshotId={snapshot} /> · {payload.results.scenario || "Scenario unavailable"} · amounts in kEUR</p>}
    {usable && <p className="rx-note" data-overview-debt-metrics="true"><a href={debtMetricsHref()} onClick={(event) => prepareDebtMetrics(event)}>Open Debt Metrics</a> — covenants, DSCR profile, reserves and the dated debt schedule of this Run.</p>}
    {payload.state === "STALE" && <p className="rx-banner rx-banner-stale" role="status">STALE — these figures and assumptions belong to the prior saved Run. Save changes, then Run explicitly to update them.</p>}
    {integrity === "FAIL" && <div className="rx-status rx-status-error" role="alert" data-overview-integrity="FAIL">
      <strong>INTEGRITY FAIL — review this Run before relying on its financial results.</strong>
      <p>A completed calculation or CURRENT inputs do not establish financial viability. The financial verdict is unchanged.</p>
      <a href="#diagnostics">Open Model checks and authoritative failure details</a>
      <ul>{payload.integrity?.failures.map((failure, index) => <li key={failure.id || index}>{failure.title || failure.id || "Failed check"}{failure.reason ? `: ${failure.reason}` : ""}</li>)}</ul>
    </div>}
    {integrity === "INCOMPLETE" && <div className="rx-status rx-status-conflict" role="status" data-overview-integrity="INCOMPLETE">
      <strong>INTEGRITY INCOMPLETE — some Run checks could not be evaluated from the saved evidence.</strong>
      <p>Missing evidence is not a pass and not a breach. <a href="#diagnostics">Open Model checks</a></p>
    </div>}
    {!usable ? <p className="rx-empty" role="status">{payload.state === "NOT_RUN" ? "No committed Run yet. Enter and save inputs, then choose Run model. No financial values are estimated." : payload.message || "Run evidence is unavailable. Refresh to retry."}</p> : <>
      <div className="wsv2-overview-grid">
        <section className="rx-card wsv2-assumptions"><h3>Project & contract assumptions</h3>
          {supplement ? <dl>{supplement.assumptions.map((field) => <div key={field.field_id}><dt>{field.label}</dt><dd title={field.value == null ? field.display : String(field.value)}>{field.available ? `${reportUnitText(field.value == null ? field.display : String(field.value), field.unit, precision)}${field.unit && field.unit !== "x" && field.unit !== "%" ? ` ${field.unit}` : ""}` : "Unavailable"}</dd></div>)}</dl>
            : <p className="rx-note" role="status">{read?.snapshot === snapshot ? "Assumptions could not be bound to this Run. Current draft inputs are not substituted." : "Reading saved Run assumptions…"}</p>}
        </section>
        <section className="rx-card wsv2-overview-metrics"><h3>Returns & financing</h3><dl className="wsv2-return-facts">{payload.results.metrics.filter((metric) => /^(Project IRR|Pure Equity IRR|Total Sponsor IRR|Sponsor MOIC)$/i.test(metric.label)).map((metric) =>
            <div key={metric.label}><dt>{metric.label}</dt><dd>{metric.available ? reportMetric(metric.display || "", "kEUR", precision) : "Unavailable"}</dd></div>)}
            {payload.results.lender_metrics?.filter((metric) => /dscr/i.test(metric.key)).map((metric) => <div key={metric.key}><dt>{metric.label}</dt><dd>{metric.available ? reportMetric(metric.display || "", "kEUR", precision) : "Unavailable"}</dd></div>)}
          </dl><details className="rx-advanced"><summary>Return conventions</summary><p className="rx-note">Project IRR is before financing. Pure Equity IRR measures share capital; Total Sponsor IRR includes shareholder-loan flows. Each is published by this Run.</p></details></section>
        <div className="wsv2-overview-charts">{cash && <TimeSeriesChart chart={cash} unit="kEUR" precision={precision} />}{dscr && <TimeSeriesChart chart={dscr} unit="kEUR" precision={precision} />}</div>
      </div>
      <section className="rx-card" data-overview-sources-uses="true"><h3>Sources & Uses · kEUR</h3>
        {sources?.available && sources.view?.has_run ? <><p className="rx-note">{sources.view.balance_status || "Balance status unavailable"} · {sources.view.integrity_note}</p>
          <div className="wsv2-sources-uses"><div><h4>Sources</h4><AmountRows rows={sources.view.sources || []} total={sources.view.total_sources} /></div>
            <div><h4>Uses</h4><AmountRows rows={sources.view.uses || []} total={sources.view.total_uses} /></div></div></>
          : <p className="rx-note">{sources?.reason || "Bound Sources & Uses evidence is unavailable for this Run. No funding values are estimated."}</p>}
      </section>
      <p className="rx-note"><a href="#results">Full Results and Run history</a> · <a href="#statements">Cash-flow waterfall and financial statements</a> · <a href="#analysis">Period DSCR and financial analysis</a></p>
    </>}
  </section>;
}
