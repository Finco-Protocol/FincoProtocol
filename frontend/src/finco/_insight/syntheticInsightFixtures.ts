import type { InsightFinding } from "./insightContract";

/**
 * Fixed, illustrative review examples for the isolated Design preview.
 * These values are not calculated and are not a production check registry.
 */
export const SYNTHETIC_INSIGHT_FINDINGS: readonly InsightFinding[] = [
  {
    id: "ppa-term-reference",
    area: "inputs",
    severity: "moderate",
    title: "The PPA example ends before the stated operating life",
    why: "The fixed example shows an 18-year PPA term and a 30-year operating-life reference.",
    evidenceLabel: "PPA term",
    evidenceValue: "18",
    thresholdLabel: "Operating-life reference",
    thresholdValue: "30",
    evidenceRequiresCurrentRun: true,
    comparison: "below-reference",
    priorityWhenFlagged: "worth-a-look",
    advice: "Review contract coverage and merchant-period assumptions.",
    destination: {
      sheet: "input-grid",
      elementId: "wb-cell-5-0",
      label: "PPA tenor input",
    },
  },
  {
    id: "mezz-dscr-reference",
    area: "financing",
    severity: "high",
    title: "A fixed debt-service example is below its review reference",
    why: "One pre-authored Mezzanine DSCR example is 1.08x against a 1.20x illustrative review reference.",
    evidenceLabel: "Fixed Mezzanine example",
    evidenceValue: "1.08x",
    thresholdLabel: "Illustrative review reference",
    thresholdValue: "1.20x",
    evidenceRequiresCurrentRun: true,
    comparison: "below-reference",
    priorityWhenFlagged: "needs-attention",
    advice: "Review the debt-service assumptions.",
    destination: {
      sheet: "input-grid",
      elementId: "wb-cell-15-0",
      label: "Minimum DSCR assumption",
    },
  },
  {
    id: "tax-schedule-detail",
    area: "tax",
    severity: "information",
    title: "Tax schedule detail is not available in this example",
    why: "The preview does not supply a period-level tax schedule or supporting evidence.",
    evidenceLabel: "Tax schedule",
    evidenceValue: "",
    thresholdLabel: "Review reference",
    thresholdValue: "",
    evidenceRequiresCurrentRun: true,
    comparison: "not-evaluated",
    priorityWhenFlagged: "could-not-check",
  },
  {
    id: "scenario-run-evidence",
    area: "scenarios",
    severity: "information",
    title: "Scenario-specific results are not supplied",
    why: "The example results remain fixed and are not recalculated when the selected scenario changes.",
    evidenceLabel: "Selected-scenario result",
    evidenceValue: "",
    thresholdLabel: "Committed result",
    thresholdValue: "",
    evidenceRequiresCurrentRun: true,
    comparison: "not-evaluated",
    priorityWhenFlagged: "could-not-check",
  },
];

