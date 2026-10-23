import type { ResultsRunStatus } from "../src/finco/_results/resultsContract.ts";
import type { StatementRunStatus, StatementWorkbookSnapshot } from "../src/finco/_workbook/statementContract.ts";
import type { ResultsPresentationSnapshot } from "../src/finco/_results/resultsContract.ts";
import {
  TRANSFER_CALLER_RESULTS_STATUS,
  TRANSFER_DEMO_RESULTS,
  TRANSFER_DEMO_RESULTS_STATUS,
  TRANSFER_EMPTY_RESULTS_STATUS,
  TRANSFER_PARTIAL_RESULTS,
} from "./resultsFixtures.ts";
import {
  TRANSFER_DEMO_RUN_STATUS,
  TRANSFER_DEMO_STATEMENT,
  TRANSFER_EMPTY_STATEMENT_STATUS,
} from "./fixtures.ts";

export type TransferDemoStateId =
  | "working-copy-not-run"
  | "last-run-current"
  | "working-copy-stale"
  | "run-attempt-failed"
  | "unavailable"
  | "protected-reference"
  | "period-mismatch";

export type TransferProductState = {
  id: TransferDemoStateId;
  label: string;
  explanation: string;
  mode: "reference" | "working-copy";
  resultsSnapshot: ResultsPresentationSnapshot | null;
  resultsStatus: ResultsRunStatus;
  statementSnapshot: StatementWorkbookSnapshot | null;
  statementStatus: StatementRunStatus;
};

const labels: Record<TransferDemoStateId, { label: string; explanation: string }> = {
  "working-copy-not-run": {
    label: "Working Copy · NOT RUN",
    explanation: "Draft context only. No Last Run values are supplied.",
  },
  "last-run-current": {
    label: "Saved demo · illustrative CURRENT",
    explanation: "Fixed synthetic reference labelled current for state review; not a real engine result.",
  },
  "working-copy-stale": {
    label: "Edited Working Copy · illustrative STALE",
    explanation: "Edited scenario is separate from the fixed prior Last Run scenario.",
  },
  "run-attempt-failed": {
    label: "Failed demo attempt · prior Last Run retained",
    explanation: "Failure is a scripted presentation state; the previous fixed sample remains unchanged.",
  },
  unavailable: {
    label: "Unknown / unavailable",
    explanation: "No result or statement snapshot is supplied; unavailable is not zero.",
  },
  "protected-reference": {
    label: "Protected Reference · read-only",
    explanation: "Reference route uses client-side demo locking only; this is not an authorization check.",
  },
  "period-mismatch": {
    label: "Run Compare · mismatched periods",
    explanation: "Open Workbook → Run Compare to inspect fixed runs with different period calendars and missing values.",
  },
};

function statusWithContext(
  status: ResultsRunStatus,
  values: ResultsRunStatus["productContext"],
): ResultsRunStatus {
  return { ...status, productContext: values };
}

export function resolveTransferProductState(id: TransferDemoStateId): TransferProductState {
  const copy = labels[id];
  const sharedFixed = {
    resultsSnapshot: TRANSFER_DEMO_RESULTS,
    statementSnapshot: TRANSFER_DEMO_STATEMENT,
    statementStatus: TRANSFER_DEMO_RUN_STATUS,
  };

  switch (id) {
    case "working-copy-not-run":
      return {
        id, ...copy, mode: "working-copy", resultsSnapshot: null,
        resultsStatus: statusWithContext(TRANSFER_EMPTY_RESULTS_STATUS, {
          workingCopyMode: "working-copy", workingCopyState: "not-run", workingScenarioId: "base",
          lastRunScenarioId: null, lastRunTimestamp: null,
        }),
        statementSnapshot: null, statementStatus: TRANSFER_EMPTY_STATEMENT_STATUS,
      };
    case "last-run-current":
      return {
        id, ...copy, mode: "working-copy", ...sharedFixed,
        resultsStatus: statusWithContext({
          ...TRANSFER_DEMO_RESULTS_STATUS,
          freshness: "current",
        }, {
          workingCopyMode: "working-copy", workingCopyState: "saved", workingScenarioId: "base",
          lastRunScenarioId: "base", lastRunTimestamp: "18 Jun 2025 · synthetic example",
        }),
      };
    case "working-copy-stale":
      return {
        id, ...copy, mode: "working-copy", ...sharedFixed,
        resultsStatus: statusWithContext({
          ...TRANSFER_CALLER_RESULTS_STATUS, dataOrigin: "synthetic-demo",
          runId: { kind: "value", text: "DEMO-LAST-022" },
          engineCurrency: { kind: "unavailable", reason: "Engine currency/version is unknown." },
          integrity: "not-evaluated",
        }, {
          workingCopyMode: "working-copy", workingCopyState: "unsaved", workingScenarioId: "downside",
          lastRunScenarioId: "base", lastRunTimestamp: "17 Jun 2025 · fixed synthetic example",
        }),
      };
    case "run-attempt-failed":
      return {
        id, ...copy, mode: "working-copy", ...sharedFixed,
        resultsStatus: statusWithContext({
          ...TRANSFER_CALLER_RESULTS_STATUS, dataOrigin: "synthetic-demo",
          runId: { kind: "value", text: "DEMO-LAST-022" },
          engineCurrency: { kind: "unavailable", reason: "Engine currency/version is unknown." },
          integrity: "not-evaluated",
        }, {
          workingCopyMode: "working-copy", workingCopyState: "unsaved", workingScenarioId: "downside",
          lastRunScenarioId: "base", lastRunTimestamp: "17 Jun 2025 · fixed synthetic example",
          runAttempt: {
            kind: "illustrative-failure",
            message: "Illustrative failed Run attempt. The prior fixed Last Run is retained; no Run was executed.",
          },
        }),
      };
    case "unavailable":
      return {
        id, ...copy, mode: "working-copy", resultsSnapshot: null,
        resultsStatus: statusWithContext({
          ...TRANSFER_EMPTY_RESULTS_STATUS,
          runState: "unavailable",
          freshness: "unknown",
          engineCurrency: { kind: "unavailable", reason: "Engine currency/version is unknown." },
        }, {
          workingCopyMode: "working-copy", workingCopyState: "not-run", workingScenarioId: "base",
          lastRunScenarioId: null, lastRunTimestamp: null,
        }),
        statementSnapshot: null, statementStatus: TRANSFER_EMPTY_STATEMENT_STATUS,
      };
    case "protected-reference":
      return {
        id, ...copy, mode: "reference", ...sharedFixed,
        resultsStatus: statusWithContext(TRANSFER_DEMO_RESULTS_STATUS, {
          workingCopyMode: "reference", workingCopyState: "saved", workingScenarioId: "base",
          lastRunScenarioId: "base", lastRunTimestamp: "18 Jun 2025 · synthetic example",
        }),
      };
    case "period-mismatch":
      return {
        id, ...copy, mode: "working-copy",
        resultsSnapshot: TRANSFER_PARTIAL_RESULTS,
        resultsStatus: statusWithContext({
          ...TRANSFER_CALLER_RESULTS_STATUS,
          runId: { kind: "value", text: "QA-PERIOD-MISMATCH" },
          engineCurrency: { kind: "unavailable", reason: "Engine version not supplied." },
          integrity: "not-evaluated",
        }, {
          workingCopyMode: "working-copy", workingCopyState: "unsaved", workingScenarioId: "upside",
          lastRunScenarioId: "base", lastRunTimestamp: null,
        }),
        statementSnapshot: null,
        statementStatus: TRANSFER_EMPTY_STATEMENT_STATUS,
      };
  }
}

export const TRANSFER_DEMO_STATE_OPTIONS = Object.entries(labels).map(([id, value]) => ({
  id: id as TransferDemoStateId,
  label: value.label,
}));
