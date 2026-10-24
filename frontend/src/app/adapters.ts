// Adapters from the canonical server payloads to the harvested presentation
// contracts.  Pure reshaping of SERVER-FORMATTED display data — no financial
// calculation, aggregation or reconciliation happens here.

import type {
  StatementsPayload,
  WorkspacePayload,
} from "./types";
import type {
  ResultsDisplayValue,
  ResultsPresentationSnapshot,
  ResultsRunStatus,
} from "../finco/_results/resultsContract";
import type {
  StatementRunStatus,
  StatementSheetId,
  StatementWorkbookSnapshot,
} from "../finco/_workbook/statementContract";

const SHEET_IDS: StatementSheetId[] = ["pl", "balance", "cashflow", "cfads", "debt", "sponsor"];

export function toStatementSnapshot(payload: StatementsPayload): StatementWorkbookSnapshot | null {
  if (!payload.snapshot) return null;
  type Row = StatementWorkbookSnapshot["sheets"][number]["rows"][number];
  const sheets = payload.snapshot.sheets
    .filter((sheet) => (SHEET_IDS as string[]).includes(sheet.id))
    .map((sheet) => ({
      ...sheet,
      id: sheet.id as StatementSheetId,
      rows: sheet.rows.map((row): Row => ({
        ...row,
        kind: row.kind === "metric" || row.kind === "section" ? row.kind : "detail",
      })),
    }));
  return {
    annualPeriods: payload.snapshot.annualPeriods,
    modelPeriods: payload.snapshot.modelPeriods,
    periodBands: payload.snapshot.periodBands,
    sheets,
    debtRowsByFacility: payload.snapshot.debtRowsByFacility,
  };
}

export function toStatementStatus(payload: StatementsPayload): StatementRunStatus {
  return payload.status;
}

const v = (text: string): ResultsDisplayValue => ({ kind: "value", text });
const unv = (reason: string): ResultsDisplayValue => ({ kind: "unavailable", reason });

function display(cellText: string): ResultsDisplayValue {
  return cellText === "—" ? unv("Not produced by this Run") : v(cellText);
}

const UNAVAILABLE_SNAPSHOT: ResultsPresentationSnapshot = {
  headingLabel: "Results",
  versionLabel: "UNAVAILABLE",
  currencyLabel: "kEUR",
  periods: [],
  kpis: [],
  summaryRows: [],
  charts: { revenue: null, cashDebt: null, debtService: null },
  creditObservations: [],
  capitalStructure: [],
  history: [],
  scenarios: [],
};

/** Adapts the canonical returns/metrics projection into the harvested Results
 *  presentation contract.  Charts stay null (no canonical chart projection is
 *  consumed in this PR — absent values render as unavailable, never synthetic). */
export function toResultsSnapshot(payload: StatementsPayload): ResultsPresentationSnapshot {
  const results = payload.results;
  if (!results || !results.available) {
    return {
      ...UNAVAILABLE_SNAPSHOT,
      headingLabel: `Results — ${payload.project.name}`,
      versionLabel: payload.state === "NOT_RUN" ? "NOT RUN" : "UNAVAILABLE",
    };
  }
  const distributions = results.distributions;
  const periods = (distributions?.columns ?? []).map((c) => c.label);
  const summaryRows = (distributions?.rows ?? []).map((row) => ({
    id: row.key,
    label: row.label,
    emphasis: row.key === "distribution_keur" ? ("cash" as const) : undefined,
    values: row.cells.map((cell) => display(cell.text)),
  }));
  const kpis = results.metrics
    .filter((m) => m.available)
    .map((m, index) => ({
      id: `metric-${index}`,
      label: m.label,
      value: v(m.display),
      note: `Canonical source: ${m.source}`,
    }));
  const credit = results.metrics.find((m) => m.label.toUpperCase().includes("DSCR"));
  return {
    headingLabel: `Results — ${payload.project.name}`,
    versionLabel: payload.state,
    currencyLabel: "kEUR",
    periods,
    kpis,
    summaryRows,
    charts: { revenue: null, cashDebt: null, debtService: null },
    creditObservations: credit
      ? [{ id: "dscr", label: credit.label, value: v(credit.display) }]
      : [],
    capitalStructure: results.metrics
      .filter((m) => m.available && /debt|equity|capital|gearing|reserve/i.test(m.label))
      .map((m, index) => ({ id: `capital-${index}`, label: m.label, value: v(m.display) })),
    history: payload.results.ran_at
      ? [{
          id: "last-run",
          runRef: payload.status.runId,
          modelVersion: payload.results.engine_version ?? "unavailable",
          scenario: payload.results.scenario ?? "UNAVAILABLE",
          timestamp: payload.results.ran_at,
          equityIrr: (() => {
            const m = results.metrics.find((m) => /equity irr/i.test(m.label));
            return m?.available ? v(m.display) : unv("Not available from this Run");
          })(),
          state: payload.state,
        }]
      : [],
    scenarios: [],
  };
}

export function toResultsRunStatus(payload: StatementsPayload): ResultsRunStatus {
  const state = payload.state;
  return {
    dataOrigin: "caller-provided",
    runState: state === "NOT_RUN" ? "not-run"
      : state === "STALE" ? "stale"
        : state === "UNAVAILABLE" ? "unavailable"
          : "current",
    runId: v(payload.status.runId),
    freshness: state === "CURRENT" ? "current"
      : state === "STALE" ? "stale"
        : state === "NOT_RUN" ? "not-run"
          : "unknown",
    engineCurrency: payload.status.engineVersion
      ? v(`Engine ${payload.status.engineVersion}`)
      : unv("Engine identity unavailable"),
    integrity: payload.integrity_available && payload.integrity?.status !== "UNAVAILABLE"
      ? "evaluated"
      : "not-evaluated",
  };
}

export function workspaceHeading(payload: WorkspacePayload): string {
  return `${payload.project.name} (${payload.project.project_type || "project"})`;
}
