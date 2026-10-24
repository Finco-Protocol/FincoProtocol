import type {
  ResultsChartModel,
  ResultsDisplayValue,
  ResultsPresentationSnapshot,
  ResultsRunStatus,
} from "../src/finco/_results/resultsContract.ts";

/**
 * Independent synthetic fixtures for the standalone transfer build.
 * Intentionally does not import the Canvas demo provider.
 */
const value = (text: string, tooltip?: string): ResultsDisplayValue => ({ kind: "value", text, tooltip });
const unavailable = (reason: string): ResultsDisplayValue => ({ kind: "unavailable", text: "Unavailable", reason });
const periods = ["2027", "2028", "2029", "2030", "2031", "2032", "2033", "2034"];

const chart = (kind: "revenue" | "cash" | "debt"): ResultsChartModel => {
  const isRevenue = kind === "revenue";
  const isCash = kind === "cash";
  const axis = isRevenue ? "€18m" : isCash ? "€14m" : "€10m";
  const gridStartX = isRevenue ? 47 : isCash ? 45 : 46;
  const gridEndX = isRevenue ? 584 : isCash ? 585 : 586;
  const axisLabelX = isRevenue || !isCash ? 4 : 3;
  const periodLabels = isRevenue
    ? [50, 125, 200, 275, 350, 425, 500, 577]
    : isCash ? periods.map((_, i) => 81 + i * 72) : periods.map((_, i) => 74 + i * 66);
  const revenueValues = ["13.1", "15.2", "15.4", "15.6", "15.7", "15.9", "16.0", "16.2"];
  const debtValues = ["6.7", "8.4", "8.5", "8.6", "8.7", "8.9", "9.0", "9.2"];
  const cashValues = ["8.4", "10.6", "10.9", "11.0", "11.2", "11.4", "11.6", "11.8"];
  const lineY = [107, 85, 81, 75, 72, 65, 61, 55];
  const cashHeights = [59.4, 75.0, 77.1, 77.8, 79.2, 80.6, 82.0, 83.4];
  const debtCashHeights = [47.4, 59.4, 60.1, 60.8, 61.5, 62.9, 63.6, 65.1];
  const debtHeights = [66.3, 83.2, 84.2, 85.1, 86.1, 88.1, 89.1, 91.1];
  const makeBar = (texts: string[], heights: number[], xFor: (index: number) => number, width: number, label: string) => texts.map((text, i) => {
    const height = heights[i];
    return {
      period: periods[i],
      value: value(text, `${periods[i]} ${label}: €${text}m`),
      geometry: { x: xFor(i), y: 124 - height, width, height },
    };
  });

  const result: ResultsChartModel = {
    ariaLabel: isRevenue
      ? "Illustrative revenue by year, increasing from 13.1 to 16.2 million euros"
      : isCash ? "Illustrative cash flow and debt service trend" : "Illustrative annual debt service profile",
    meta: "€m · synthetic series",
    caption: isRevenue ? "PPA tariff with merchant tail · annual periods" : undefined,
    axisTopLabel: axis,
    axisBottomLabel: isRevenue ? "€10m" : "€0",
    gridLines: [25, 58, 91, 124],
    gridStartX,
    gridEndX,
    axisLabelX,
    baselineY: 124,
    periodLabels: periods.map((label, i) => ({ label, x: periodLabels[i] })),
    series: [],
  };

  if (isRevenue) {
    result.series = [{
      id: "revenue",
      label: "Revenue",
      kind: "line",
      tone: "primary",
      area: true,
      points: revenueValues.map((text, i) => ({
        period: periods[i],
        value: value(text, `${periods[i]} revenue: €${text}m`),
        geometry: { x: periodLabels[i], y: lineY[i] },
        marker: i === 0 || i === 1 || i === 7,
      })),
    }];
  } else if (isCash) {
    result.series = [
      { id: "cash-available", label: "Cash available", kind: "bar", tone: "primary", points: makeBar(cashValues, cashHeights, (i) => 62 + i * 72, 18, "cash available") },
      { id: "debt-service", label: "Debt service", kind: "bar", tone: "secondary", points: makeBar(debtValues, debtCashHeights, (i) => 82 + i * 72, 18, "debt service") },
    ];
  } else {
    result.series = [{
      id: "scheduled-debt-service",
      label: "Scheduled debt service",
      kind: "bar",
      tone: "primary",
      points: makeBar(debtValues, debtHeights, (i) => 58 + i * 66, 33, "scheduled debt service"),
    }];
  }
  return result;
};

export const TRANSFER_DEMO_RESULTS: ResultsPresentationSnapshot = {
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
  summaryRows: [
    { id: "generation", label: "Net generation (GWh)", values: ["185.0", "194.4", "193.5", "192.7", "191.8", "190.9", "190.1", "189.2"].map((text) => value(text)) },
    { id: "revenue", label: "Revenue (€m)", values: ["13.1", "15.2", "15.4", "15.6", "15.7", "15.9", "16.0", "16.2"].map((text) => value(text)) },
    { id: "opex", label: "Operating costs (€m)", values: ["(1.8)", "(1.7)", "(1.8)", "(1.8)", "(1.9)", "(1.9)", "(2.0)", "(2.0)"].map((text) => value(text)) },
    { id: "ebitda", label: "EBITDA (€m)", values: ["11.3", "13.5", "13.6", "13.8", "13.8", "14.0", "14.0", "14.2"].map((text) => value(text)) },
    { id: "cfads", label: "Cash available for debt service (€m)", emphasis: "cash", values: ["8.4", "10.6", "10.9", "11.0", "11.2", "11.4", "11.6", "11.8"].map((text) => value(text)) },
    { id: "debt-service", label: "Scheduled debt service (€m)", values: ["(6.7)", "(8.4)", "(8.5)", "(8.6)", "(8.7)", "(8.9)", "(9.0)", "(9.2)"].map((text) => value(text)) },
    { id: "dscr", label: "DSCR (x)", emphasis: "dscr", values: ["1.25", "1.26", "1.28", "1.28", "1.29", "1.28", "1.29", "1.28"].map((text) => value(text)) },
    { id: "equity-cash", label: "Cash flow to equity (€m)", values: ["1.1", "1.7", "1.8", "1.8", "1.9", "1.9", "2.0", "2.0"].map((text) => value(text)) },
  ],
  charts: { revenue: chart("revenue"), cashDebt: chart("cash"), debtService: chart("debt") },
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

export const TRANSFER_DEMO_RESULTS_STATUS: ResultsRunStatus = {
  dataOrigin: "synthetic-demo",
  runState: "fixed-demo",
  runId: value("DEMO-FIXED-018"),
  freshness: "unknown",
  engineCurrency: unavailable("No live engine connection."),
  integrity: "not-evaluated",
};

export const TRANSFER_PARTIAL_RESULTS: ResultsPresentationSnapshot = {
  headingLabel: "Partial view-model fixture",
  versionLabel: "QA-only · caller-provided sample",
  currencyLabel: "No common period basis supplied",
  periods: ["2027", "2028"],
  kpis: [
    { id: "project-irr", label: "Project IRR", value: value("0.00%"), note: "Valid zero display fixture" },
    { id: "equity-irr", label: "Equity IRR", value: unavailable("No value supplied."), note: "Unavailable fixture" },
  ],
  summaryRows: [{
    id: "availability-check",
    label: "Zero vs unavailable test",
    values: [value("0"), unavailable("No 2028 value supplied.")],
  }],
  charts: { revenue: null, cashDebt: null, debtService: null },
  creditObservations: [],
  capitalStructure: [],
  history: [],
  scenarios: [],
};

export const TRANSFER_EMPTY_RESULTS_STATUS: ResultsRunStatus = {
  dataOrigin: "unavailable",
  runState: "not-run",
  runId: unavailable("No run identity supplied."),
  freshness: "not-run",
  engineCurrency: unavailable("No engine connection."),
  integrity: "not-evaluated",
};

export const TRANSFER_CALLER_RESULTS_STATUS: ResultsRunStatus = {
  dataOrigin: "caller-provided",
  runState: "stale",
  runId: value("QA-STALE-REFERENCE"),
  freshness: "stale",
  engineCurrency: unavailable("Engine version not supplied."),
  integrity: "not-evaluated",
};
