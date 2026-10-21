export type ResultsDataOrigin = "synthetic-demo" | "caller-provided" | "unavailable";

export type ResultsDisplayValue =
  | { kind: "value"; text: string; tooltip?: string }
  | { kind: "unavailable"; text?: string; reason?: string };

export type ResultsTraceTarget = {
  source: string;
  workspaceSheet: string;
  statement: string;
  row: string;
};

export type ResultsKpi = {
  id: string;
  label: string;
  value: ResultsDisplayValue;
  note: string;
  trace?: ResultsTraceTarget;
};

export type ResultsSummaryRow = {
  id: string;
  label: string;
  emphasis?: "cash" | "dscr";
  values: ResultsDisplayValue[];
};

export type ResultsChartPoint = {
  period: string;
  value: ResultsDisplayValue;
  /** SVG presentation coordinates supplied by the view-model; never financial calculations. */
  geometry?: { x: number; y: number; width?: number; height?: number };
  marker?: boolean;
};

export type ResultsChartSeries = {
  id: string;
  label: string;
  kind: "line" | "bar";
  tone: "primary" | "secondary";
  area?: boolean;
  points: ResultsChartPoint[];
};

export type ResultsChartModel = {
  ariaLabel: string;
  meta: string;
  caption?: string;
  axisTopLabel: string;
  axisBottomLabel: string;
  gridLines: number[];
  gridStartX: number;
  gridEndX: number;
  axisLabelX: number;
  baselineY: number;
  periodLabels: { label: string; x: number }[];
  series: ResultsChartSeries[];
};

export type ResultsFact = { id: string; label: string; value: ResultsDisplayValue };

export type ResultsHistoryRow = {
  id: string;
  runRef: string;
  modelVersion: string;
  scenario: string;
  timestamp: string;
  equityIrr: ResultsDisplayValue;
  state: string;
};

export type ResultsScenarioRow = {
  id: string;
  name: string;
  powerPrice: ResultsDisplayValue;
  yield: ResultsDisplayValue;
  projectIrr: ResultsDisplayValue;
  equityIrr: ResultsDisplayValue;
  minDscr: ResultsDisplayValue;
  npv: ResultsDisplayValue;
};

/** Typed display model only. It contains no finance formulas or calculation rules. */
export type ResultsPresentationSnapshot = {
  headingLabel: string;
  versionLabel: string;
  currencyLabel: string;
  periods: string[];
  kpis: ResultsKpi[];
  summaryRows: ResultsSummaryRow[];
  charts: {
    revenue: ResultsChartModel | null;
    cashDebt: ResultsChartModel | null;
    debtService: ResultsChartModel | null;
  };
  creditObservations: ResultsFact[];
  capitalStructure: ResultsFact[];
  history: ResultsHistoryRow[];
  scenarios: ResultsScenarioRow[];
};

export type ResultsRunStatus = {
  dataOrigin: ResultsDataOrigin;
  runState: "fixed-demo" | "not-run" | "stale" | "unavailable";
  runId: ResultsDisplayValue;
  freshness: "current" | "stale" | "unknown" | "not-run";
  engineCurrency: ResultsDisplayValue;
  integrity: "evaluated" | "not-evaluated" | "unknown";
  /** Optional presentation-only context used by the isolated transfer QA harness. */
  productContext?: {
    workingCopyMode: "reference" | "working-copy";
    workingCopyState: "not-run" | "saved" | "unsaved";
    workingScenarioId: string;
    lastRunScenarioId: string | null;
    lastRunTimestamp: string | null;
    runAttempt?: { kind: "illustrative-failure"; message: string } | null;
  };
};

export function resultsValueText(value: ResultsDisplayValue | null | undefined): string {
  if (!value) return "Unavailable";
  return value.kind === "value" ? value.text : value.text || "Unavailable";
}

/** An explicit null remains unavailable; only omitted Canvas demo data use its fixture. */
export function resolveResultsSnapshot(
  supplied: ResultsPresentationSnapshot | null | undefined,
  demoSnapshot: ResultsPresentationSnapshot,
): ResultsPresentationSnapshot | null {
  return supplied === undefined ? demoSnapshot : supplied;
}

export function resolveResultsRunStatus(
  supplied: ResultsRunStatus | undefined,
  suppliedSnapshot: ResultsPresentationSnapshot | null | undefined,
  demoStatus: ResultsRunStatus,
): ResultsRunStatus {
  if (supplied) return supplied;
  if (suppliedSnapshot === undefined) return demoStatus;
  return {
    dataOrigin: suppliedSnapshot === null ? "unavailable" : "caller-provided",
    runState: suppliedSnapshot === null ? "unavailable" : "not-run",
    runId: { kind: "unavailable", text: "No run identity supplied." },
    freshness: suppliedSnapshot === null ? "not-run" : "unknown",
    engineCurrency: { kind: "unavailable", reason: "No engine status supplied." },
    integrity: "not-evaluated",
  };
}
