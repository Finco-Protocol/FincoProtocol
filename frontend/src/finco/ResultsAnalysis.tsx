import React from "react";
import ResultsAnalysisView from "./ResultsAnalysisView";
import { resolveStatementRunStatus, resolveStatementSnapshot, type StatementRunStatus, type StatementWorkbookSnapshot } from "./_workbook/statementContract";
import { SYNTHETIC_STATEMENT_SNAPSHOT, SYNTHETIC_STATEMENT_STATUS } from "./_workbook/syntheticStatementProvider";
import { resolveResultsRunStatus, resolveResultsSnapshot, type ResultsPresentationSnapshot, type ResultsRunStatus } from "./_results/resultsContract";
import { SYNTHETIC_RESULTS_SNAPSHOT, SYNTHETIC_RESULTS_STATUS } from "./_results/syntheticResultsProvider";
import { SYNTHETIC_INSIGHT_FINDINGS } from "./_insight/syntheticInsightFixtures";

export type ResultsAnalysisProps = {
  /** Omitted uses the Canvas demo fixture; explicit null remains unavailable. */
  resultsSnapshot?: ResultsPresentationSnapshot | null;
  resultsStatus?: ResultsRunStatus;
  /** Omitted uses the Canvas page's fixed demo fixture; explicit null remains unavailable. */
  statementSnapshot?: StatementWorkbookSnapshot | null;
  statementStatus?: StatementRunStatus;
};

/** Canvas/demo boundary only; production-facing callers should use ResultsAnalysisView. */
export function ResultsAnalysis({
  resultsSnapshot,
  resultsStatus,
  statementSnapshot,
  statementStatus,
}: ResultsAnalysisProps = {}) {
  const resolvedResults = resolveResultsSnapshot(resultsSnapshot, SYNTHETIC_RESULTS_SNAPSHOT);
  const resolvedResultsStatus = resolveResultsRunStatus(resultsStatus, resultsSnapshot, SYNTHETIC_RESULTS_STATUS);
  const resolvedStatement = resolveStatementSnapshot(statementSnapshot, SYNTHETIC_STATEMENT_SNAPSHOT);
  const resolvedStatementStatus = resolveStatementRunStatus(statementStatus, statementSnapshot, SYNTHETIC_STATEMENT_STATUS);
  return <ResultsAnalysisView
    resultsSnapshot={resolvedResults}
    resultsStatus={resolvedResultsStatus}
    statementSnapshot={resolvedStatement}
    statementStatus={resolvedStatementStatus}
    insightFindings={SYNTHETIC_INSIGHT_FINDINGS}
  />;
}

export default ResultsAnalysis;
