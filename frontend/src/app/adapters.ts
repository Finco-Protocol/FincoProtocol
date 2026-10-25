// Adapters from the canonical server payloads to the harvested presentation
// contracts.  Pure reshaping of SERVER-FORMATTED display data — no financial
// calculation, aggregation or reconciliation happens here.

import type {
  StatementsPayload,
  WorkspacePayload,
} from "./types";
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
      // The persisted "sponsor" destination is the Run's distribution waterfall;
      // label it for what it contains (sponsor cash flows are shown in Results).
      label: sheet.id === "sponsor" ? "Distributions" : sheet.label,
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

/** Canonical persisted-Run status for the statements workbook (values are never synthetic). */
export function toStatementStatus(payload: StatementsPayload): StatementRunStatus {
  return { ...payload.status, dataOrigin: "canonical-run" };
}

export function workspaceHeading(payload: WorkspacePayload): string {
  return `${payload.project.name} (${payload.project.project_type || "project"})`;
}
