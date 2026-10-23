import type {
  ResultsChartModel,
  ResultsDisplayValue,
  ResultsPresentationSnapshot,
  ResultsRunStatus,
} from "./resultsContract.ts";

/**
 * Fixed SYNTHETIC demo display values for the Canvas composition boundary.
 * This provider has no formulas and is not linked to the statement fixture or inputs.
 */
const value = (text: string, tooltip?: string): ResultsDisplayValue => ({
  kind: "value",
  text,
  tooltip,
});
const unavailable = (reason: string): ResultsDisplayValue => ({
  kind: "unavailable",
  reason,
});
const periods = ["2027", "2028", "2029", "2030", "2031", "2032", "2033", "2034"];
const summaryRows = [
  { id: "generation", label: "Net generation (GWh)", values: ["185.0", "194.4", "193.5", "192.7", "191.8", "190.9", "190.1", "189.2"].map((text) => value(text)) },
  { id: "revenue", label: "Revenue (€m)", values: ["13.1", "15.2", "15.4", "15.6", "15.7", "15.9", "16.0", "16.2"].map((text) => value(text)) },
  { id: "opex", label: "Operating costs (€m)", values: ["(1.8)", "(1.7)", "(1.8)", "(1.8)", "(1.9)", "(1.9)", "(2.0)", "(2.0)"].map((text) => value(text)) },
  { id: "ebitda", label: "EBITDA (€m)", values: ["11.3", "13.5", "13.6", "13.8", "13.8", "14.0", "14.0", "14.2"].map((text) => value(text)) },
  { id: "cfads", label: "Cash available for debt service (€m)", emphasis: "cash" as const, values: ["8.4", "10.6", "10.9", "11.0", "11.2", "11.4", "11.6", "11.8"].map((text) => value(text)) },
  { id: "debt-service", label: "Scheduled debt service (€m)", values: ["(6.7)", "(8.4)", "(8.5)", "(8.6)", "(8.7)", "(8.9)", "(9.0)", "(9.2)"].map((text) => value(text)) },
  { id: "dscr", label: "DSCR (x)", emphasis: "dscr" as const, values: ["1.25", "1.26", "1.28", "1.28", "1.29", "1.28", "1.29", "1.28"].map((text) => value(text)) },
  { id: "equity-cash", label: "Cash flow to equity (€m)", values: ["1.1", "1.7", "1.8", "1.8", "1.9", "1.9", "2.0", "2.0"].map((text) => value(text)) },
];

const revenueChart: ResultsChartModel = {
  ariaLabel: "Illustrative revenue by year, increasing from 13.1 to 16.2 million euros",
  meta: "€m · synthetic series",
  caption: "PPA tariff with merchant tail · annual periods",
  axisTopLabel: "€18m",
  axisBottomLabel: "€10m",
  gridLines: [25, 58, 91, 124],
  gridStartX: 47,
  gridEndX: 584,
  axisLabelX: 4,
  baselineY: 124,
  periodLabels: periods.map((label, i) => ({ label, x: [50, 125, 200, 275, 350, 425, 500, 577][i] })),
  series: [{
    id: "revenue",
    label: "Revenue",
    kind: "line",
    tone: "primary",
    area: true,
    points: ["13.1", "15.2", "15.4", "15.6", "15.7", "15.9", "16.0", "16.2"].map((text, i) => ({
      period: periods[i],
      value: value(text, `${periods[i]} revenue: €${text}m`),
      geometry: { x: [50, 125, 200, 275, 350, 425, 500, 577][i], y: [107, 85, 81, 75, 72, 65, 61, 55][i] },
      marker: i === 0 || i === 1 || i === 7,
    })),
  }],
};

const cashDebtChart: ResultsChartModel = {
  ariaLabel: "Illustrative cash flow and debt service trend",
  meta: "€m · synthetic series",
  axisTopLabel: "€14m",
  axisBottomLabel: "€0",
  gridLines: [25, 58, 91, 124],
  gridStartX: 45,
  gridEndX: 585,
  axisLabelX: 3,
  baselineY: 124,
  periodLabels: periods.map((label, i) => ({ label, x: 81 + i * 72 })),
  series: [
    {
      id: "cash-available",
      label: "Cash available",
      kind: "bar",
      tone: "primary",
      points: ["8.4", "10.6", "10.9", "11.0", "11.2", "11.4", "11.6", "11.8"].map((text, i) => {
        const height = [59.4, 75.0, 77.1, 77.8, 79.2, 80.6, 82.0, 83.4][i];
        const x = 62 + i * 72;
        return { period: periods[i], value: value(text, `${periods[i]} cash available: €${text}m`), geometry: { x, y: 124 - height, width: 18, height } };
      }),
    },
    {
      id: "debt-service",
      label: "Debt service",
      kind: "bar",
      tone: "secondary",
      points: ["6.7", "8.4", "8.5", "8.6", "8.7", "8.9", "9.0", "9.2"].map((text, i) => {
        const height = [47.4, 59.4, 60.1, 60.8, 61.5, 62.9, 63.6, 65.1][i];
        const x = 82 + i * 72;
        return { period: periods[i], value: value(text, `${periods[i]} debt service: €${text}m`), geometry: { x, y: 124 - height, width: 18, height } };
      }),
    },
  ],
};

const debtServiceChart: ResultsChartModel = {
  ariaLabel: "Illustrative annual debt service profile",
  meta: "€m · fixed illustrative series",
  axisTopLabel: "€10m",
  axisBottomLabel: "€0",
  gridLines: [25, 58, 91, 124],
  gridStartX: 46,
  gridEndX: 586,
  axisLabelX: 4,
  baselineY: 124,
  periodLabels: periods.map((label, i) => ({ label, x: 74 + i * 66 })),
  series: [{
    id: "scheduled-debt-service",
    label: "Scheduled debt service",
    kind: "bar",
    tone: "primary",
    points: ["6.7", "8.4", "8.5", "8.6", "8.7", "8.9", "9.0", "9.2"].map((text, i) => {
      const height = [66.3, 83.2, 84.2, 85.1, 86.1, 88.1, 89.1, 91.1][i];
      const x = 58 + i * 66;
      return { period: periods[i], value: value(text, `${periods[i]}: €${text}m scheduled debt service`), geometry: { x, y: 124 - height, width: 33, height } };
    }),
  }],
};

export const SYNTHETIC_RESULTS_SNAPSHOT: ResultsPresentationSnapshot = {
  headingLabel: "Shared demo v1.4 · 18 Jun 2025",
  versionLabel: "Shared synthetic example · EUR nominal",
  currencyLabel: "EUR millions, unless stated",
  periods,
  kpis: [
    { id: "project-irr", label: "Project IRR", value: value("7.82%"), note: "Unlevered · nominal EUR", trace: { source: "Sponsor Returns", workspaceSheet: "investor", statement: "sponsor", row: "sponsor-irr" } },
    { id: "equity-irr", label: "Equity IRR", value: value("12.46%"), note: "Levered · post-tax", trace: { source: "Investor / sponsor returns", workspaceSheet: "investor", statement: "sponsor", row: "sponsor-irr" } },
    { id: "npv", label: "NPV @ 7.0%", value: value("€8.7m"), note: "Project cash flow · nominal", trace: { source: "Cash Flow", workspaceSheet: "inputs", statement: "cashflow", row: "net-change" } },
    { id: "minimum-dscr", label: "Minimum DSCR", value: value("1.25x"), note: "Year 2027 · senior debt", trace: { source: "CFADS", workspaceSheet: "credit-decision", statement: "cfads", row: "dscr" } },
  ],
  summaryRows,
  charts: { revenue: revenueChart, cashDebt: cashDebtChart, debtService: debtServiceChart },
  creditObservations: [
    { id: "lowest-dscr", label: "Lowest DSCR", value: value("1.25x · 2027") },
    { id: "weighted-average-dscr", label: "Weighted average DSCR", value: value("1.28x") },
    { id: "debt-total-uses", label: "Debt / total uses", value: value("63.9%") },
    { id: "ppa-contracted-generation", label: "PPA contracted generation", value: value("82% · 18 years") },
    { id: "debt-maturity", label: "Debt maturity", value: value("2045") },
  ],
  capitalStructure: [
    { id: "senior-debt", label: "Senior secured debt", value: value("€67.0m · 63.9%") },
    { id: "sponsor-equity", label: "Sponsor equity", value: value("€37.8m · 36.1%") },
    { id: "total-project-cost", label: "Total project cost", value: value("€104.8m") },
  ],
  history: [
    { id: "DEMO-FIXED-018", runRef: "DEMO-FIXED-018", modelVersion: "v1.4", scenario: "Base case", timestamp: "18 Jun 2025 · synthetic", equityIrr: value("12.46%"), state: "Fixed illustrative record" },
    { id: "DEMO-FIXED-017", runRef: "DEMO-FIXED-017", modelVersion: "v1.3", scenario: "Downside", timestamp: "16 Jun 2025 · synthetic", equityIrr: value("9.18%"), state: "Fixed illustrative record" },
    { id: "DEMO-FIXED-014", runRef: "DEMO-FIXED-014", modelVersion: "Unverified", scenario: "P90 reference", timestamp: "12 Jun 2025 · synthetic", equityIrr: value("8.74%"), state: "Fixed illustrative record" },
  ],
  scenarios: [
    { id: "base", name: "Base case", powerPrice: value("€62.50/MWh"), yield: value("P50"), projectIrr: value("7.82%"), equityIrr: value("12.46%"), minDscr: value("1.25x"), npv: value("€8.7m") },
    { id: "downside", name: "Downside", powerPrice: value("−12%"), yield: value("P90"), projectIrr: value("6.11%"), equityIrr: value("9.18%"), minDscr: value("1.08x"), npv: value("€(4.2)m") },
    { id: "upside", name: "Upside", powerPrice: value("+8%"), yield: value("P50 +3%"), projectIrr: value("9.06%"), equityIrr: value("15.31%"), minDscr: value("1.39x"), npv: value("€21.3m") },
  ],
};

export const SYNTHETIC_RESULTS_STATUS: ResultsRunStatus = {
  dataOrigin: "synthetic-demo",
  runState: "fixed-demo",
  runId: value("DEMO-FIXED-018"),
  freshness: "unknown",
  engineCurrency: unavailable("No live engine connection."),
  integrity: "not-evaluated",
};
