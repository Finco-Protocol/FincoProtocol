// Adapters from the canonical server payloads to the harvested presentation
// contracts.  Pure reshaping of SERVER-FORMATTED display data — no financial
// calculation, aggregation or reconciliation happens here.

import type {
  StatementRowPayload,
  StatementsPayload,
  WorkspacePayload,
} from "./types";
import type {
  StatementRunStatus,
  StatementSheetId,
  StatementWorkbookSnapshot,
} from "../finco/_workbook/statementContract";

const SHEET_IDS: StatementSheetId[] = ["pl", "balance", "cashflow", "cfads", "debt", "sponsor"];

type Row = StatementWorkbookSnapshot["sheets"][number]["rows"][number];

/** Canonical row -> workbook row: unit and numeric values travel with the display text. */
function toStatementRow(row: StatementRowPayload): Row {
  const { model_v, annual_v, unit, ...rest } = row;
  return {
    ...rest,
    kind: row.kind === "metric" || row.kind === "section" ? row.kind : "detail",
    unit: unit ?? undefined,
    modelValues: model_v,
    annualValues: annual_v && annual_v.length ? annual_v : undefined,
  };
}

export function toStatementSnapshot(payload: StatementsPayload): StatementWorkbookSnapshot | null {
  if (!payload.snapshot) return null;
  const sheets = payload.snapshot.sheets
    .filter((sheet) => (SHEET_IDS as string[]).includes(sheet.id))
    .map((sheet) => ({
      ...sheet,
      id: sheet.id as StatementSheetId,
      // The persisted "sponsor" destination is the Run's distribution waterfall;
      // label it for what it contains (sponsor cash flows are shown in Results).
      label: sheet.id === "sponsor" ? "Distributions" : sheet.label,
      rows: sheet.rows.map(toStatementRow),
    }));
  return {
    annualPeriods: payload.snapshot.annualPeriods,
    modelPeriods: payload.snapshot.modelPeriods,
    periodBands: payload.snapshot.periodBands,
    sheets,
    debtRowsByFacility: Object.fromEntries(
      Object.entries(payload.snapshot.debtRowsByFacility).map(([key, rows]) => [key, rows.map(toStatementRow)])),
  };
}

/** Canonical persisted-Run status for the statements workbook (values are never synthetic). */
export function toStatementStatus(payload: StatementsPayload): StatementRunStatus {
  return { ...payload.status, dataOrigin: "canonical-run" };
}

export function workspaceHeading(payload: WorkspacePayload): string {
  return `${payload.project.name} (${payload.project.project_type || "project"})`;
}
