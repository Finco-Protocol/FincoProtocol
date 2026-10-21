export type StatementSheetId = "pl" | "balance" | "cashflow" | "cfads" | "debt" | "sponsor";
export type StatementViewId = "annual" | "model";
export type StatementFacilityId = "senior" | "mezzanine";

export type StatementRow = {
  id: string;
  label: string;
  annual: string[];
  model: string[];
  kind?: "section" | "detail" | "metric";
  children?: StatementRow[];
  indent?: boolean;
};

export type StatementSheet = {
  id: StatementSheetId;
  label: string;
  title: string;
  unit: string;
  rows: StatementRow[];
};

export type StatementPeriodBand = { label: string; span: number };

/** Immutable-by-convention read-only snapshot input for the statement presentation. */
export type StatementWorkbookSnapshot = {
  annualPeriods: string[];
  modelPeriods: string[];
  periodBands: StatementPeriodBand[];
  sheets: StatementSheet[];
  debtRowsByFacility?: Partial<Record<StatementFacilityId, StatementRow[]>>;
};

export type StatementRunStatus = {
  label: string;
  runId: string;
  freshness: "unknown" | "current" | "stale" | "not run";
  integrity: "not evaluated";
  engineVersion: string | null;
  /** Defaults to the current demo only for existing callers; integrations should identify caller-provided data. */
  dataOrigin?: "synthetic-demo" | "caller-provided" | "unavailable";
};

export type StatementWorkbookProps = {
  onSheetChange?: (id: string) => void;
  /** Explicit null means no statement snapshot is available; never substitute demo rows. */
  snapshot: StatementWorkbookSnapshot | null;
  status: StatementRunStatus;
};

/** Only omitted demo-page data may select a demo fixture; explicit null stays unavailable. */
export function resolveStatementSnapshot(
  supplied: StatementWorkbookSnapshot | null | undefined,
  demoSnapshot: StatementWorkbookSnapshot,
): StatementWorkbookSnapshot | null {
  return supplied === undefined ? demoSnapshot : supplied;
}

/** Omitted snapshot props may use demo status; supplied/null props cannot inherit its provenance. */
export function resolveStatementRunStatus(
  suppliedStatus: StatementRunStatus | undefined,
  suppliedSnapshot: StatementWorkbookSnapshot | null | undefined,
  demoStatus: StatementRunStatus,
): StatementRunStatus {
  if (suppliedStatus) return suppliedStatus;
  if (suppliedSnapshot === undefined) return demoStatus;
  return {
    label: suppliedSnapshot === null ? "Statement snapshot unavailable" : "Caller-provided statement snapshot",
    runId: "Not supplied",
    freshness: suppliedSnapshot === null ? "not run" : "unknown",
    integrity: "not evaluated",
    engineVersion: null,
    dataOrigin: suppliedSnapshot === null ? "unavailable" : "caller-provided",
  };
}

/** Keeps the valid numeric string "0" distinct from an unavailable cell. */
export function statementCellText(value: string | null | undefined): string {
  if (value === null || value === undefined || !value.trim() || /^(—|–|-|n\/a|na)$/i.test(value.trim())) return "—";
  return value;
}

/** Keeps one statement data cell in the page Tab order; arrow keys move within the grid. */
export function statementCellTabIndex(
  rowId: string,
  column: number,
  activeRowId: string | null,
  activeColumn: number,
  isFirstCell: boolean,
): 0 | -1 {
  return (activeRowId === null
    ? isFirstCell
    : activeRowId === rowId && activeColumn === column) ? 0 : -1;
}

export function statementStatusText(status: StatementRunStatus): {
  run: string;
  freshness: string;
  integrity: string;
  engine: string;
} {
  return {
    run: `${status.label} · ${status.runId}`,
    freshness: `Freshness: ${status.freshness}`,
    integrity: `Integrity: ${status.integrity}`,
    engine: `Engine: ${status.engineVersion || "unknown / not connected"}`,
  };
}
