export type InsightMode = "review" | "explain" | "changes";
export type InsightPriorityGroup = "needs-attention" | "worth-a-look" | "could-not-check";
export type InsightSeverity = "high" | "moderate" | "information";
export type InsightArea = "project" | "inputs" | "financing" | "results" | "scenarios" | "analysis" | "tax";
export type InsightEvidenceState = "current" | "stale" | "unavailable";

export type InsightDestination = {
  sheet: string;
  elementId?: string;
  label: string;
};

export type InsightFinding = {
  id: string;
  area: InsightArea;
  severity: InsightSeverity;
  title: string;
  why: string;
  evidenceLabel: string;
  evidenceValue: string;
  thresholdLabel: string;
  thresholdValue: string;
  evidenceRequiresCurrentRun: boolean;
  comparison: "below-reference" | "above-reference" | "not-evaluated";
  priorityWhenFlagged: InsightPriorityGroup;
  advice?: string;
  destination?: InsightDestination;
};

export type InsightFindingPresentation = InsightFinding & {
  priorityGroup: InsightPriorityGroup;
  evidenceState: InsightEvidenceState;
  displayedValue: string;
  displayedThreshold: string;
  adviceText?: string;
  checkNote: string;
};

export type InsightExplainItem = {
  id: string;
  kind: "Input" | "Indicator" | "Statement row" | "Finding";
  title: string;
  value: string;
  unit?: string;
  period?: string;
  contextLabel: string;
  basis: string;
  destination?: InsightDestination;
};

export type InsightExplainInput = Omit<InsightExplainItem, "contextLabel">;

export type InsightContext = {
  projectName: string;
  projectId: string;
  technology: string;
  scenarioId: string;
  activeArea: InsightArea | "overview" | "findings";
  activeScreen: string;
  statusLabel: string;
  statusDetail: string;
  readOnly: boolean;
  hasUnsavedEdits: boolean;
  savedInPreview: boolean;
  conflict: boolean;
  runState: "current" | "stale" | "not-run" | "unknown";
  runId: string;
  runScenario: string | null;
  resultOriginLabel: string;
  resultDateLabel: string;
  engineCurrencyLabel: string;
  resultChecksLabel: string;
};

export type InsightFindingsFilters = {
  severity: "all" | InsightSeverity;
  area: "all" | InsightArea;
  status: "all" | InsightPriorityGroup;
};

const priorityOrder: Record<InsightPriorityGroup, number> = {
  "needs-attention": 0,
  "worth-a-look": 1,
  "could-not-check": 2,
};

function numericValue(value: string): number | null {
  const number = Number(value.replace(/[^\d.+-]/g, ""));
  return Number.isFinite(number) ? number : null;
}

function flagIsPresent(finding: InsightFinding): boolean {
  if (finding.comparison === "not-evaluated") return false;
  const value = numericValue(finding.evidenceValue);
  const threshold = numericValue(finding.thresholdValue);
  if (value === null || threshold === null) return false;
  return finding.comparison === "below-reference" ? value < threshold : value > threshold;
}

/** Produces presentation states only; it does not calculate financial measures. */
export function presentFinding(
  finding: InsightFinding,
  context: Pick<InsightContext, "runState" | "hasUnsavedEdits" | "readOnly" | "conflict">,
): InsightFindingPresentation {
  const evidenceIsCurrent =
    finding.evidenceRequiresCurrentRun &&
    context.runState === "current" &&
    !context.hasUnsavedEdits &&
    !context.readOnly &&
    !context.conflict;

  if (!evidenceIsCurrent || !flagIsPresent(finding)) {
    return {
      ...finding,
      priorityGroup: "could-not-check",
      evidenceState: context.runState === "stale" ? "stale" : "unavailable",
      displayedValue: "Unavailable",
      displayedThreshold: "Unavailable",
      adviceText: undefined,
      checkNote: context.runState === "stale"
        ? "The displayed example is earlier than the current inputs, so this check was not assessed."
        : context.readOnly
          ? "This reference is for inspection only; no current check is supplied."
          : "No current example evidence is available for this check.",
    };
  }

  return {
    ...finding,
    priorityGroup: finding.priorityWhenFlagged,
    evidenceState: "current",
    displayedValue: finding.evidenceValue,
    displayedThreshold: finding.thresholdValue,
    adviceText: finding.advice,
    checkNote: "Fixed illustrative values and review reference; not a lender or financial conclusion.",
  };
}

export function presentFindings(
  findings: readonly InsightFinding[],
  context: Pick<InsightContext, "runState" | "hasUnsavedEdits" | "readOnly" | "conflict">,
): InsightFindingPresentation[] {
  return findings
    .map((finding) => presentFinding(finding, context))
    .sort((a, b) => priorityOrder[a.priorityGroup] - priorityOrder[b.priorityGroup]);
}

export function filterFindings(
  findings: readonly InsightFindingPresentation[],
  filters: InsightFindingsFilters,
): InsightFindingPresentation[] {
  return findings.filter((finding) =>
    (filters.severity === "all" || finding.severity === filters.severity) &&
    (filters.area === "all" || finding.area === filters.area) &&
    (filters.status === "all" || finding.priorityGroup === filters.status),
  );
}

export function contextualFindings(
  findings: readonly InsightFindingPresentation[],
  activeArea: InsightContext["activeArea"],
): InsightFindingPresentation[] {
  if (activeArea === "overview" || activeArea === "findings" || activeArea === "analysis") return [...findings];
  if (activeArea === "results") return findings.filter((finding) => finding.area === "results" || finding.area === "financing");
  if (activeArea === "scenarios") return findings.filter((finding) => finding.area === "scenarios" || finding.area === "results");
  return findings.filter((finding) => finding.area === activeArea);
}

export function insightChangesSummary(context: InsightContext): {
  inputs: string;
  results: string;
  currentStatus: string;
  workingScenario: string;
  lastRunScenario: string;
  lastRunReference: string;
  resultOrigin: string;
  resultDate: string;
  freshness: string;
  calculationVersion: string;
  resultChecks: string;
  conflict: string | null;
  note: string;
} {
  const inputs = context.readOnly
    ? "Read-only reference"
    : context.conflict
      ? "Project update needs review"
      : context.hasUnsavedEdits
        ? "You have unsaved changes"
        : context.savedInPreview
          ? "Changes saved in this preview"
          : "No saved changes in this preview";
  const results = context.runState === "current"
    ? "Results are up to date"
    : context.runState === "stale"
      ? "Showing earlier results"
      : context.runState === "not-run"
        ? "No results yet"
        : "Result status is unavailable";
  return {
    inputs,
    results,
    currentStatus: context.statusLabel,
    workingScenario: context.scenarioId || "Unavailable",
    lastRunScenario: context.runScenario || "No committed example",
    lastRunReference: context.runId,
    resultOrigin: context.resultOriginLabel,
    resultDate: context.resultDateLabel,
    freshness: context.runState === "current" ? "Up to date" : context.runState === "stale" ? "Earlier results" : context.runState === "not-run" ? "No results yet" : "Status unavailable",
    calculationVersion: context.engineCurrencyLabel,
    resultChecks: context.resultChecksLabel,
    conflict: context.conflict
      ? "This project changed since it was opened. A real reload may discard local drafts."
      : null,
    note: "This summary shows the overall preview state only. It does not contain a field-by-field change history.",
  };
}

