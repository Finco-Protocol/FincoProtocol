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
};

export type StatementWorkbookProps = {
  onSheetChange?: (id: string) => void;
  snapshot?: StatementWorkbookSnapshot;
  status?: StatementRunStatus;
};

/** Keeps the valid numeric string "0" distinct from an unavailable cell. */
export function statementCellText(value: string | null | undefined): string {
  if (value === null || value === undefined || !value.trim() || /^(—|–|-|n\/a|na)$/i.test(value.trim())) return "—";
  return value;
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
