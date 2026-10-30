import { useMemo, useState } from "react";
import "../finco/_group.css";
import "../styles/finco-live.css";
import type { CanonicalTable, StatementSheetPayload, StatementsPayload } from "./types";
import { RunIdentityLabel } from "./runIdentity";
import {
  DISPLAY_UNITS, formatFromCanonicalUnit, formatUnitLabel,
  classifyRowUnit, plotValue, resolveRowFormat, sheetUnitLabel,
  type DisplayUnit, type RowFormat, type UnitSource,
} from "./units";
import { reportCell as formatStatementCell, reportMetric as formatMetricDisplay } from "./reportFormatting";
import { useReportPrecision } from "./ReportPrecision";
import { plain } from "./productLanguage";
import { debtMetricsHref, prepareDebtMetrics } from "./debtmetrics/debtMetricsLink";

// Canonical presentation of the persisted Run.  Every figure on this page is a
// server-formatted value read from the project's saved Run (statements,
// returns metrics, distribution and sponsor tables).  The browser performs
// display-unit conversion, rounding, ordering and chart scaling ONLY - it never
// derives a financial result.  A value the Run did not persist stays visibly
// unavailable, with the canonical reason when one exists.

type Page = "results" | "analysis";

interface PeriodRow {
  key: string;
  label: string;
  texts: string[];
  /** Canonical numeric cell values aligned with `texts` (null = not persisted; absent on legacy payloads). */
  values?: Array<number | null>;
  format: RowFormat;
  /** How the row's unit was established (canonical metadata vs inference). */
  unitSource: UnitSource;
  source: string;
}

interface PeriodTableModel {
  id: string;
  title: string;
  source: string;
  periods: string[];
  rows: PeriodRow[];
  note?: string;
  /** Implementation-level source of the series: shown only behind a disclosure. */
  technical?: string;
}

const STATE_TEXT: Record<string, string> = {
  CURRENT: "CURRENT · last Run",
  STALE: "STALE · prior saved Run",
  NOT_RUN: "NOT RUN",
  UNAVAILABLE: "UNAVAILABLE",
};

function classified(label: string, rowUnit: string | undefined, sheetUnit: string | undefined): { format: RowFormat; unitSource: UnitSource } {
  const { format, source } = classifyRowUnit(label, rowUnit, sheetUnit);
  return { format, unitSource: source };
}

function sheetOf(payload: StatementsPayload, id: string): StatementSheetPayload | null {
  return payload.snapshot?.sheets.find((sheet) => sheet.id === id && sheet.available) ?? null;
}

/** Selects (never computes) canonical statement rows into a period table model. */
function statementRows(
  payload: StatementsPayload,
  sheetId: string,
  rowIds: ReadonlyArray<readonly [string, string?]>,
  basis: "annual" | "model",
): PeriodRow[] {
  const sheet = sheetOf(payload, sheetId);
  if (!sheet) return [];
  const rows: PeriodRow[] = [];
  for (const [rowId, labelOverride] of rowIds) {
    const row = sheet.rows.find((candidate) => candidate.id === rowId);
    if (!row) continue;
    const texts = basis === "annual" ? row.annual : row.model;
    if (!texts.length) continue;
    const values = basis === "annual" ? row.annual_v : row.model_v;
    rows.push({
      key: `${sheetId}.${row.id}`,
      label: labelOverride ?? row.label,
      texts,
      values: values && values.length === texts.length ? values : undefined,
      ...classified(row.label, row.unit ?? undefined, sheet.unit),
      source: `${sheet.title} · ${row.label}`,
    });
  }
  return rows;
}

function tableRows(table: CanonicalTable | null | undefined, keys: ReadonlyArray<string>, sourceTitle: string): PeriodRow[] {
  if (!table || !table.available || !table.rows) return [];
  const out: PeriodRow[] = [];
  for (const row of table.rows) {
    if (!keys.includes(row.key)) continue;
    out.push({
      key: `${table.id ?? sourceTitle}.${row.key}`,
      label: row.label,
      texts: row.cells.map((cell) => (cell.v === null ? "—" : cell.text)),
      values: row.cells.map((cell) => cell.v),
      ...classified(row.label, row.unit, "keur"),
      source: `${table.title ?? sourceTitle} · ${row.label}`,
    });
  }
  return out;
}

function columnLabels(table: CanonicalTable | null | undefined): string[] {
  return (table?.columns ?? []).map((column) => column.label);
}

function RunContext({ payload }: { payload: StatementsPayload }) {
  const { status, results, state } = payload;
  const identity = status.runId && status.runId !== "Not supplied" ? status.runId : null;
  const integrity: string = status.integrity;   // the server sends the evaluated status (PASS / FAIL / INCOMPLETE / UNAVAILABLE); the shared type is narrower than the payload
  return (
    <section className="rx-live-context" aria-label="Run context" data-run-context="true" data-run-state={state}>
      <div className={`rx-live-state rx-live-state-${state.toLowerCase()}`} data-run-state-label={state}>{STATE_TEXT[state] ?? state}</div>
      <dl>
        <div><dt>Run</dt><dd><RunIdentityLabel snapshotId={identity} /></dd></div>
        <div><dt>Ran</dt><dd>{results.ran_at || "unavailable"}</dd></div>
        <div><dt>Scenario</dt><dd>{results.scenario || "unavailable"}</dd></div>
        <div><dt>Engine</dt><dd>{status.engineVersion || "identity unavailable"}</dd></div>
        <div><dt>Integrity</dt><dd data-integrity={integrity}>Integrity: {integrity}{integrity === "FAIL" && <> — this Run completed but failed Run Integrity; its results are not a bankable scenario. <a href="#diagnostics">Failed checks</a></>}</dd></div>
        <div><dt>Debt Metrics</dt><dd data-results-debt-metrics="true"><a href={debtMetricsHref()} onClick={(event) => prepareDebtMetrics(event)}>Covenants, DSCR profile and schedule</a></dd></div>
      </dl>
    </section>
  );
}

function UnitControls({ unit, precision, onUnit, onPrecision, showPrecision }: {
  showPrecision: boolean; unit: DisplayUnit; precision: number; onUnit: (unit: DisplayUnit) => void; onPrecision: (precision: number) => void;
}) {
  return (
    <div className="rx-live-controls" role="group" aria-label="Display units">
      <label>Units
        <select value={unit} aria-label="Display units" data-control="unit" onChange={(event) => onUnit(event.target.value as DisplayUnit)}>
          {DISPLAY_UNITS.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
      </label>
      {showPrecision && <label>Precision
        <select value={precision} aria-label="Display precision" data-control="precision" onChange={(event) => onPrecision(Number(event.target.value))}>
          {[0, 1, 2, 3].map((item) => <option key={item} value={item}>{item === 1 ? "1 decimal" : `${item} decimals`}</option>)}
        </select>
      </label>}

      <span className="rx-note">Values are held in kEUR; units and precision change the display only.</span>
    </div>
  );
}

// ── metrics ────────────────────────────────────────────────────────────────

const METRIC_GROUPS: ReadonlyArray<{ id: string; title: string; match: RegExp }> = [
  { id: "returns", title: "Returns", match: /irr|moic|npv|return/i },
  { id: "funding", title: "Equity funding and distributions", match: /equity|shl|sponsor|distribution|funded|invested/i },
  { id: "other", title: "Other metrics", match: /.*/ },
];

/** What each persisted figure means, in finance language (matched on the canonical label). */
const METRIC_MEANING: ReadonlyArray<{ match: RegExp; text: string }> = [
  { match: /^project irr$/i, text: "Return on the project's cash flows before financing." },
  { match: /pure equity irr/i, text: "Share-capital return: only the equity paid in and the dividends received on it." },
  { match: /total sponsor irr/i, text: "Total sponsor return: share capital and shareholder-loan (SHL) cash flows together." },
  { match: /moic/i, text: "Multiple of the sponsor capital invested, from the sponsor schedule." },
  { match: /total equity invested/i, text: "Share capital contributed by the sponsor." },
  { match: /total shl funded/i, text: "Shareholder-loan cash contributed by the sponsor." },
  { match: /total sponsor distributions/i, text: "Distributions paid on share capital." },
];

const meaningOf = (label: string) => METRIC_MEANING.find((item) => item.match.test(label))?.text ?? "";

/** Monetary KPI display text -> selected unit and precision (never touches ratios, IRR or percentages). */
const metricDisplay = formatMetricDisplay;

export function MetricCards({ payload, unit, precision }: { payload: StatementsPayload; unit: DisplayUnit; precision: number }) {
  const metrics = payload.results.metrics;
  if (!metrics.length) {
    return <p className="rx-empty" role="status" data-metrics-state="unavailable">This Run has no key financial metrics.</p>;
  }
  const groups = METRIC_GROUPS.map((group) => ({ ...group, items: [] as typeof metrics }));
  for (const metric of metrics) {
    (groups.find((group) => group.match.test(metric.label)) ?? groups[groups.length - 1]).items.push(metric);
  }
  return (
    <div data-metrics="true">
      {groups.filter((group) => group.items.length).map((group) => (
        <div key={group.id} className="rx-live-metric-group" data-metric-group={group.id}>
          <h3>{group.title}</h3>
          {group.id === "returns" && (
            <p className="rx-note" data-returns-explainer="true">
              These returns measure different things and none is derived from another. Project IRR is before financing.
              Pure Equity IRR is the share-capital return. Total Sponsor IRR is the return on all sponsor capital,
              including shareholder-loan (SHL) flows, so it can differ materially from Pure Equity IRR.
            </p>
          )}
          <div className="rx-live-kpis">
            {group.items.map((metric) => (
              <div key={metric.label} className={`rx-live-kpi${metric.available ? "" : " rx-live-kpi-unavailable"}`}
                data-metric-label={metric.label} data-metric-available={metric.available ? "true" : "false"}
                data-metric-canonical={metric.display} data-metric-source={metric.available ? undefined : metric.source}>
                <div className="rx-live-kpi-label">{metric.label}</div>
                <div className="rx-live-kpi-value">{metric.available ? metricDisplay(metric.display, unit, precision) : "Not available"}</div>
                <div className="rx-live-kpi-source">
                  {metric.available ? meaningOf(metric.label) : `Not available in this Run: ${plain(metric.source).replace(/^Not saved by the (.*)$/i, "the $1 does not provide it")}`}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
      <details className="rx-live-tech" data-metric-sources="true">
        <summary>Technical source of each figure</summary>
        <ul>
          {metrics.map((metric) => <li key={metric.label}><strong>{metric.label}</strong>: <code>{metric.source}</code></li>)}
        </ul>
      </details>
    </div>
  );
}

/**
 * Lender and valuation metrics the committed Run did or did not publish.  A metric the Run
 * does not publish is explicitly unavailable: never zero, never a proxy.  Nothing here claims
 * that full lender-grade metrics are supported.
 */
function LenderMetrics({ payload, unit, precision }: { payload: StatementsPayload; unit: DisplayUnit; precision: number }) {
  const rows = payload.results.lender_metrics ?? [];
  if (!rows.length) return null;
  return (
    <div className="rx-live-metric-group" data-metric-group="lender" data-lender-metrics="true">
      <h3>Lender and valuation metrics</h3>
      <div className="rx-live-kpis">
        {rows.map((row) => (
          <div key={row.key} className={`rx-live-kpi${row.available ? "" : " rx-live-kpi-unavailable"}`}
            data-lender-metric={row.key} data-lender-metric-available={row.available ? "true" : "false"}>
            <div className="rx-live-kpi-label">{row.label}</div>
            <div className="rx-live-kpi-value">{row.available && row.display ? metricDisplay(row.display, unit, precision) : "Not available"}</div>
            <div className="rx-live-kpi-source">{row.available ? "Published by this Run." : row.reason}</div>
          </div>
        ))}
      </div>
      <p className="rx-note" data-lender-note="true">
        Only metrics the committed Run publishes are shown. Any other lender metric stays unavailable; none is
        estimated or replaced by zero. This is not a full set of lender-grade metrics.
      </p>
    </div>
  );
}

// ── tables ─────────────────────────────────────────────────────────────────

function PeriodTable({ model, unit, precision }: { model: PeriodTableModel; unit: DisplayUnit; precision: number }) {
  if (!model.rows.length || !model.periods.length) {
    return (
      <section className="rx-live-card" data-period-table={model.id} data-table-state="unavailable">
        <h3>{model.title}</h3>
        <p className="rx-empty" role="status">{plain(model.note) || "This Run has no such series."}</p>
      </section>
    );
  }
  return (
    <section className="rx-live-card" data-period-table={model.id} data-table-state="available">
      <div className="rx-live-card-head"><h3>{model.title}</h3><span className="rx-note">{model.source}</span></div>
      <div className="rx-live-scroll" role="region" tabIndex={0} aria-label={`${model.title}, scrollable periods`}>
        <table className="rx-live-table">
          <caption className="fm-sr-only">{model.title}. Values in {unit} unless a row states another unit.</caption>
          <thead>
            <tr>
              <th scope="col">Line · {unit}</th>
              {model.periods.map((period, index) => <th scope="col" key={`${period}-${index}`}>{period}</th>)}
            </tr>
          </thead>
          <tbody>
            {model.rows.map((row) => (
              <tr key={row.key}>
                <th scope="row" title={row.source} data-unit-source={row.unitSource}>
                  {row.label}{row.format.kind !== "money" && !row.label.includes(`(${formatUnitLabel(row.format, unit)})`) && <span className="rx-live-row-unit"> ({formatUnitLabel(row.format, unit)})</span>}
                </th>
                {model.periods.map((period, index) => {
                  const canonical = row.texts[index] ?? "—";
                  const numeric = row.values?.[index];
                  const shown = formatStatementCell(canonical, row.format, unit, precision, numeric);
                  return (
                    <td key={`${row.key}-${index}`} data-canonical={canonical} data-v={numeric === undefined || numeric === null ? undefined : String(numeric)} data-row={row.key} data-period={period}
                      data-unit={formatUnitLabel(row.format, unit)}
                      className={shown === "—" ? "rx-live-na" : undefined}>{shown}</td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {model.note && <p className="rx-note">{plain(model.note)}</p>}
      {model.technical && (
        <details className="rx-live-tech"><summary>Technical source</summary><p className="rx-note">{model.technical}</p></details>
      )}
    </section>
  );
}

// ── charts ─────────────────────────────────────────────────────────────────

interface ChartSeries { key: string; label: string; texts: string[]; values?: Array<number | null>; format: RowFormat; kind: "bar" | "line" }

interface ChartModel {
  id: string;
  title: string;
  source: string;
  periods: string[];
  series: ChartSeries[];
}

const W = 640;
const H = 210;
const PLOT = { left: 62, right: 628, top: 14, bottom: 168 };

export function TimeSeriesChart({ chart, unit, precision }: { chart: ChartModel; unit: DisplayUnit; precision: number }) {
  const series = chart.series.filter((item) => item.texts.length > 0);
  // geometry from the canonical numeric value; the display-text parse is only a legacy-payload fallback
  const numeric = series.map((item) => item.values ?? item.texts.map((text) => plotValue(text)));
  const all = numeric.flat().filter((value): value is number => value !== null);
  if (!series.length || !chart.periods.length || !all.length) {
    return (
      <section className="rx-live-card" data-chart={chart.id} data-chart-state="unavailable">
        <h3>{chart.title}</h3>
        <p className="rx-empty" role="status">Chart data is unavailable: this Run did not persist the series. No sample series is shown.</p>
      </section>
    );
  }
  const lo = Math.min(0, ...all);
  const hi = Math.max(0, ...all);
  const span = hi - lo || 1;
  const y = (value: number) => PLOT.bottom - ((value - lo) / span) * (PLOT.bottom - PLOT.top);
  const n = chart.periods.length;
  const slot = (PLOT.right - PLOT.left) / n;
  const barSeries = series.filter((item) => item.kind === "bar");
  const barWidth = Math.max(1, (slot * 0.72) / Math.max(1, barSeries.length));
  const x = (index: number) => PLOT.left + slot * index + slot / 2;
  const show = (item: ChartSeries, text: string, index: number) => formatStatementCell(text, item.format, unit, precision, item.values?.[index]);
  const unitText = (item: ChartSeries) => formatUnitLabel(item.format, unit);
  const tickEvery = Math.max(1, Math.ceil(n / 8));
  const firstMoney = series.find((item) => item.format.kind === "money");
  const axisUnit = firstMoney ? unit : unitText(series[0]);
  const extremeText = (target: number) => {
    for (let s = 0; s < series.length; s++) {
      const index = numeric[s].findIndex((value) => value === target);
      if (index >= 0) return show(series[s], series[s].texts[index], index);
    }
    return null;
  };
  const topLabel = extremeText(Math.max(...all));
  const bottomLabel = lo < 0 ? extremeText(Math.min(...all)) : "0";
  return (
    <section className="rx-live-card" data-chart={chart.id} data-chart-state="available">
      <div className="rx-live-card-head"><h3>{chart.title}</h3><span className="rx-note">{chart.source} · {axisUnit}</span></div>
      <svg className="rx-live-chart" viewBox={`0 0 ${W} ${H}`} role="img"
        aria-label={`${chart.title}. ${series.map((item) => item.label).join(", ")}. ${n} periods, values in ${axisUnit}.`}>
        <line x1={PLOT.left} x2={PLOT.right} y1={y(0)} y2={y(0)} className="rx-live-axis" />
        <text x={PLOT.left - 6} y={PLOT.top + 8} textAnchor="end" className="rx-live-axis-label">{topLabel}</text>
        {bottomLabel && <text x={PLOT.left - 6} y={lo < 0 ? PLOT.bottom : y(0) + 3} textAnchor="end" className="rx-live-axis-label">{bottomLabel}</text>}
        {series.map((item, s) => {
          if (item.kind === "bar") {
            const barIndex = barSeries.indexOf(item);
            return (
              <g key={item.key} className={`rx-live-bars rx-live-s${s}`} data-series={item.key}>
                {numeric[s].map((value, index) => value === null ? null : (
                  <rect key={index} x={x(index) - (barSeries.length * barWidth) / 2 + barIndex * barWidth}
                    y={Math.min(y(value), y(0))} width={barWidth} height={Math.max(0.5, Math.abs(y(value) - y(0)))}
                    data-point={chart.periods[index]} data-canonical={item.texts[index]} data-v={numeric[s][index] === null ? undefined : String(numeric[s][index])}>
                    <title>{`${item.label} · ${chart.periods[index]}: ${show(item, item.texts[index], index)} ${unitText(item)}`}</title>
                  </rect>
                ))}
              </g>
            );
          }
          const segments: Array<Array<{ index: number; value: number }>> = [];
          let current: Array<{ index: number; value: number }> = [];
          numeric[s].forEach((value, index) => {
            if (value === null) { if (current.length) segments.push(current); current = []; } else current.push({ index, value });
          });
          if (current.length) segments.push(current);
          return (
            <g key={item.key} className={`rx-live-line rx-live-s${s}`} data-series={item.key}>
              {segments.map((segment, k) => (
                <polyline key={k} fill="none" points={segment.map((p) => `${x(p.index)},${y(p.value)}`).join(" ")} />
              ))}
              {n <= 60 && numeric[s].map((value, index) => value === null ? null : (
                <circle key={index} cx={x(index)} cy={y(value)} r={2.2} data-point={chart.periods[index]} data-canonical={item.texts[index]} data-v={numeric[s][index] === null ? undefined : String(numeric[s][index])}>
                  <title>{`${item.label} · ${chart.periods[index]}: ${show(item, item.texts[index], index)} ${unitText(item)}`}</title>
                </circle>
              ))}
            </g>
          );
        })}
        {chart.periods.map((period, index) => index % tickEvery === 0 ? (
          <text key={`${period}-${index}`} x={x(index)} y={PLOT.bottom + 16} textAnchor="middle" className="rx-live-axis-label">{period}</text>
        ) : null)}
      </svg>
      <div className="rx-live-legend">
        {series.map((item, s) => <span key={item.key}><i className={`rx-live-swatch rx-live-s${s}`} data-kind={item.kind} />{item.label}{item.format.kind !== "money" ? ` (${unitText(item)})` : ""}</span>)}
      </div>
      <details className="rx-live-values">
        <summary>View {chart.title.toLowerCase()} values</summary>
        <div className="rx-live-scroll" role="region" tabIndex={0} aria-label={`${chart.title} values`}>
          <table className="rx-live-table">
            <thead><tr><th scope="col">Period</th>{series.map((item) => <th scope="col" key={item.key}>{item.label}</th>)}</tr></thead>
            <tbody>
              {chart.periods.map((period, index) => (
                <tr key={`${period}-${index}`}>
                  <th scope="row">{period}</th>
                  {series.map((item) => <td key={item.key}>{show(item, item.texts[index] ?? "—", index)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

// ── page ───────────────────────────────────────────────────────────────────

export function useModels(payload: StatementsPayload) {
  return useMemo(() => {
    const snapshot = payload.snapshot;
    const annual = snapshot?.annualPeriods ?? [];
    const model = snapshot?.modelPeriods ?? [];
    const distributions = payload.results.distributions;
    const sponsor = payload.results.sponsor_table;

    const operating: PeriodTableModel = {
      id: "operating-performance",
      title: "Operating performance and cash flow (annual)",
      source: "Saved Run · Profit & Loss and Cash Flow statements",
      periods: annual,
      rows: [
        ...statementRows(payload, "pl", [["revenues_keur", "Revenue"], ["operating_expenses_keur"], ["ebit_keur"], ["net_income_keur"]], "annual"),
        ...statementRows(payload, "cashflow", [
          ["ebitda_cash_keur", "EBITDA (cash)"], ["fcf_banks_keur", "CFADS (cash flow available for debt service)"],
          ["senior_total_ds_keur", "Senior debt service"], ["fcf_for_distribution_keur"]], "annual"),
      ],
      note: "Annual values are the Run's annual statement columns; no totals are computed in the browser.",
    };
    const sponsorTable: PeriodTableModel = {
      id: "sponsor-cash-flow",
      title: "Sponsor cash flow",
      source: sponsor?.title ? `Saved Run · ${sponsor.title}` : "Saved Run · sponsor schedule",
      periods: columnLabels(sponsor),
      rows: tableRows(sponsor, [
        "share_capital_contribution_keur", "share_premium_contribution_keur", "additional_equity_contribution_keur",
        "shl_principal_receipt_keur", "shl_cash_interest_receipt_keur", "legal_equity_distribution_keur"], "Sponsor cash flows"),
      note: payload.results.sponsor_source ? "Sponsor cash flows exactly as the Run saved them." : "The Run has no sponsor cash-flow schedule.",
      technical: payload.results.sponsor_source ? `Source: ${payload.results.sponsor_source}` : undefined,
    };
    const waterfall: PeriodTableModel = {
      id: "distribution-waterfall",
      title: "Distribution waterfall",
      source: distributions?.title ? `Saved Run · ${distributions.title}` : "Saved Run · distributions",
      periods: columnLabels(distributions),
      rows: tableRows(distributions, ["cf_after_reserves_keur", "distribution_keur", "dsra_balance_keur"], "Distribution waterfall"),
      note: payload.results.distribution_source ? "Distribution waterfall exactly as the Run saved it." : "The Run has no distribution waterfall.",
      technical: payload.results.distribution_source ? `Source: ${payload.results.distribution_source}` : undefined,
    };
    const debtSheet = sheetOf(payload, "debt");
    const debt: PeriodTableModel = {
      id: "debt-summary",
      title: "Debt summary (model periods)",
      source: "Saved Run · Debt schedule",
      periods: model,
      rows: debtSheet ? debtSheet.rows.map((row) => ({
        key: `debt.${row.id}`, label: row.label, texts: row.model,
        values: row.model_v && row.model_v.length === row.model.length ? row.model_v : undefined,
        ...classified(row.label, row.unit ?? undefined, debtSheet.unit),
        source: `${debtSheet.title} · ${row.label}`,
      })) : [],
      note: debtSheet?.note || "This Run has no debt schedule.",
    };
    const cfadsRows = statementRows(payload, "cfads", [["cfads_keur", "CFADS"], ["senior_service_keur", "Senior debt service"], ["dscr", "DSCR"]], "model");

    const charts: ChartModel[] = [
      {
        id: "overview-waterfall", title: "Cash-flow waterfall components",
        source: "Saved Run · Cash Flow (PF waterfall)", periods: model,
        series: statementRows(payload, "cashflow", [
          ["opex_cash_keur", "Operating costs"], ["cash_tax_keur", "Cash tax"],
          ["senior_total_ds_keur", "Senior debt service"], ["shl_cash_interest_keur", "SHL interest"],
          ["shl_principal_keur", "SHL principal"], ["revenue_cash_keur", "Revenue"],
        ], "model").map((row) => ({ key: row.key, label: row.label, texts: row.texts, values: row.values,
          format: row.format, kind: row.key === "cashflow.revenue_cash_keur" ? "line" as const : "bar" as const })),
      },
      {
        id: "revenue-opex", title: "Revenue and operating performance (annual)",
        source: "Saved Run · Profit & Loss", periods: annual,
        series: statementRows(payload, "pl", [["revenues_keur", "Revenue"], ["operating_expenses_keur", "Operating expenses"], ["ebit_keur", "EBIT"]], "annual")
          .map((row, index) => ({ key: row.key, label: row.label, texts: row.texts, values: row.values, format: row.format, kind: index === 2 ? "line" as const : "bar" as const })),
      },
      {
        id: "ebitda-cash", title: "EBITDA and operating cash flow",
        source: "Saved Run · Cash Flow (PF waterfall)", periods: model,
        series: statementRows(payload, "cashflow", [["ebitda_cash_keur", "EBITDA (cash)"], ["revenue_cash_keur", "Revenue cash"], ["opex_cash_keur", "Operating cash costs"]], "model")
          .map((row, index) => ({ key: row.key, label: row.label, texts: row.texts, values: row.values, format: row.format, kind: index === 0 ? "bar" as const : "line" as const })),
      },
      {
        id: "cfads-debt-service", title: "CFADS and debt service",
        source: "Saved Run · CFADS", periods: model,
        series: cfadsRows.filter((row) => row.key !== "cfads.dscr")
          .map((row, index) => ({ key: row.key, label: row.label, texts: row.texts, values: row.values, format: row.format, kind: index === 0 ? "bar" as const : "line" as const })),
      },
      {
        id: "dscr", title: "Debt service coverage ratio (DSCR)",
        source: "Saved Run · CFADS", periods: model,
        series: cfadsRows.filter((row) => row.key === "cfads.dscr")
          .map((row) => ({ key: row.key, label: "DSCR", texts: row.texts, values: row.values, format: { kind: "ratio" } as RowFormat, kind: "line" as const })),
      },
      {
        id: "debt-balance", title: "Debt balance and service",
        source: "Saved Run · Debt schedule", periods: model,
        series: (debtSheet?.rows ?? []).filter((row) => /closing|service/i.test(row.id))
          .map((row) => ({ key: `debt.${row.id}`, label: row.label, texts: row.model,
            values: row.model_v && row.model_v.length === row.model.length ? row.model_v : undefined,
            format: resolveRowFormat(row.label, row.unit ?? undefined, debtSheet?.unit), kind: /closing/i.test(row.id) ? "bar" as const : "line" as const })),
      },
      {
        id: "distributions", title: "Distributions and cash after reserves",
        source: "Saved Run · Distribution waterfall", periods: columnLabels(distributions),
        series: waterfall.rows.filter((row) => !/dsra/i.test(row.key))
          .map((row, index) => ({ key: row.key, label: row.label, texts: row.texts, values: row.values, format: row.format, kind: index === 1 ? "bar" as const : "line" as const })),
      },
      {
        id: "sponsor-cash-flow-chart", title: "Sponsor cash flow",
        source: "Saved Run · Sponsor cash flows", periods: columnLabels(sponsor),
        series: sponsorTable.rows.filter((row) => /legal_equity_distribution|additional_equity|shl_cash_interest/.test(row.key))
          .map((row) => ({ key: row.key, label: row.label, texts: row.texts, values: row.values, format: row.format, kind: /legal_equity/.test(row.key) ? "bar" as const : "line" as const })),
      },
    ];
    return { operating, sponsorTable, waterfall, debt, charts };
  }, [payload]);
}

export function FinancialResults({ payload, page }: { payload: StatementsPayload; page: Page }) {
  const [unit, setUnit] = useState<DisplayUnit>(() => {
    const canonical = formatFromCanonicalUnit(payload.snapshot?.sheets[0]?.unit);
    return canonical?.kind === "money" ? canonical.base : "kEUR";
  });
  const { precision, setPrecision, shared } = useReportPrecision();
  const models = useModels(payload);
  const state = payload.state;
  const heading = page === "results" ? "Results" : "Financial analysis";

  if (state === "NOT_RUN" || state === "UNAVAILABLE" || !payload.snapshot) {
    return (
      <section className="rx-live-page" data-financial-page={page} data-financial-state={state}>
        <h2>{heading} — {payload.project.name}</h2>
        <RunContext payload={payload} />
        <p className="rx-empty" role="status">
          {state === "NOT_RUN"
            ? "No saved Run exists for this project, so there are no results to show. Run the model to produce them; nothing is estimated here."
            : payload.message || "The saved Run evidence could not be projected. Nothing is estimated."}
        </p>
      </section>
    );
  }

  const stale = state === "STALE";
  return (
    <section className="rx-live-page" data-financial-page={page} data-financial-state={state}>
      <div className="rx-live-heading">
        <div>
          <h2>{heading} — {payload.project.name}</h2>
          <p className="rx-note">
            {page === "results"
              ? `Key financial metrics, operating performance and sponsor returns from the saved Run. Unit: ${sheetUnitLabel(payload.snapshot.sheets[0]?.unit)}.`
              : "Time-series charts and debt and equity summaries from the same saved Run."}
          </p>
        </div>
        <UnitControls showPrecision={!shared} unit={unit} precision={precision} onUnit={setUnit} onPrecision={setPrecision} />
      </div>
      <RunContext payload={payload} />
      {stale && (
        <p className="rx-banner rx-banner-stale" role="status" data-stale-banner="true">
          Results outdated — the project changed after the last Run. These are the prior Run&rsquo;s values, not the current inputs.
        </p>
      )}
      {page === "results" ? (
        <>
          <section className="rx-live-section" aria-labelledby="rx-key-metrics">
            <h3 id="rx-key-metrics">Key financial metrics</h3>
            <MetricCards payload={payload} unit={unit} precision={precision} />
            <LenderMetrics payload={payload} unit={unit} precision={precision} />
            <p className="rx-note" data-dscr-note="true">
              The year-by-year DSCR series is shown in Analysis, as saved. Credit indicators for committed Runs you select are in Analysis → Financial intelligence.
            </p>
            <p className="rx-note" data-analysis-link="true">
              <a href="#analysis">Open deeper financial analysis and credit intelligence</a> · <a href="#scenarios">Compare committed scenario Runs</a>
            </p>
          </section>
          <PeriodTable model={models.operating} unit={unit} precision={precision} />
          <PeriodTable model={models.sponsorTable} unit={unit} precision={precision} />
        </>
      ) : (
        <>
          <div className="rx-live-chart-grid">
            {models.charts.map((chart) => <TimeSeriesChart key={chart.id} chart={chart} unit={unit} precision={precision} />)}
          </div>
          <PeriodTable model={models.debt} unit={unit} precision={precision} />
          <PeriodTable model={models.waterfall} unit={unit} precision={precision} />
          <PeriodTable model={models.sponsorTable} unit={unit} precision={precision} />
        </>
      )}
    </section>
  );
}
