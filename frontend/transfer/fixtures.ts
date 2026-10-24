import type {
  StatementRow,
  StatementRunStatus,
  StatementSheet,
  StatementWorkbookSnapshot,
} from "../src/finco/_workbook/statementContract";

const years = ["2027", "2028", "2029", "2030", "2031", "2032", "2033", "2034"];
const modelPeriods = ["2026 M10", "2026 M12", "2027 Q3", "2027 Q4", "2028 Q1", "2028 Q2", "2029 6M", "2030 6M"];

const row = (id: string, label: string, values: string[], model = values): StatementRow => ({
  id,
  label,
  annual: values,
  model,
  kind: "metric",
});

/**
 * Isolated fixture provider for the full-React transfer entry. These values are
 * fixed synthetic samples and are never calculated from editable inputs.
 */
export const TRANSFER_DEMO_STATEMENT: StatementWorkbookSnapshot = {
  annualPeriods: years,
  modelPeriods,
  periodBands: [
    { label: "Construction snapshots", span: 2 },
    { label: "Operating quarter snapshots", span: 4 },
    { label: "Operating half-year snapshots", span: 2 },
  ],
  sheets: [
    {
      id: "pl",
      label: "P&L",
      title: "Profit & loss",
      unit: "EUR millions, synthetic example",
      rows: [
        row("revenue", "Revenue · transfer fixture", ["13.1", "15.2", "15.4", "15.6", "15.7", "15.9", "16.0", "16.2"]),
        row("ebitda", "EBITDA · transfer fixture", ["11.3", "13.5", "13.6", "13.8", "13.8", "14.0", "14.0", "14.2"]),
      ],
    },
    {
      id: "balance",
      label: "Balance sheet",
      title: "Balance sheet",
      unit: "EUR millions, synthetic example",
      rows: [row("cash", "Cash & cash equivalents · transfer fixture", ["4.3", "4.8", "5.1", "5.4", "5.8", "6.1", "6.5", "6.9"])],
    },
    {
      id: "cashflow",
      label: "Cash flow",
      title: "Cash flow statement",
      unit: "EUR millions, synthetic example",
      rows: [row("net-change", "Net change in cash · transfer fixture", ["0.5", "0.5", "0.3", "0.3", "0.4", "0.4", "0.4", "0.4"])],
    },
    {
      id: "cfads",
      label: "CFADS",
      title: "Cash flow available for debt service",
      unit: "EUR millions, synthetic example",
      rows: [row("dscr", "DSCR · transfer fixture", ["1.25", "1.26", "1.28", "1.28", "1.29", "1.28", "1.29", "1.28"])],
    },
    {
      id: "debt",
      label: "Debt schedule",
      title: "Debt schedule",
      unit: "EUR millions, synthetic example",
      rows: [row("senior-opening", "Opening principal · transfer fixture", ["64.8", "60.2", "55.5", "50.8", "46.1", "41.5", "36.8", "32.1"])],
    },
    {
      id: "sponsor",
      label: "Sponsor returns",
      title: "Sponsor returns",
      unit: "EUR millions, synthetic example",
      rows: [row("sponsor-net-cash", "Net sponsor cash flow · transfer fixture", ["(37.8)", "1.1", "1.7", "1.8", "1.8", "1.9", "1.9", "2.0"])],
    },
  ] satisfies StatementSheet[],
};

export const TRANSFER_DEMO_RUN_STATUS: StatementRunStatus = {
  label: "Synthetic reference snapshot",
  runId: "DEMO-FIXED-018",
  freshness: "unknown",
  integrity: "not evaluated",
  engineVersion: null,
  dataOrigin: "synthetic-demo",
};

export const TRANSFER_CALLER_STATEMENT_STATUS: StatementRunStatus = {
  label: "Caller-supplied snapshot",
  runId: "UNVERIFIED-SUPPLIED-ID",
  freshness: "unknown",
  integrity: "not evaluated",
  engineVersion: null,
  dataOrigin: "caller-provided",
};

export const TRANSFER_EMPTY_STATEMENT_STATUS: StatementRunStatus = {
  label: "No statement snapshot",
  runId: "UNAVAILABLE",
  freshness: "not run",
  integrity: "not evaluated",
  engineVersion: null,
  dataOrigin: "unavailable",
};
