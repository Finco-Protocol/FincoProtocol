import { fetchCreditDecision } from "../credit/api";
import type { CreditHistoryRow } from "../credit/types";
import type { DebtMetricsView } from "./types";

export interface DebtMetricsRun {
  identity: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any -- server-projected Run identity, rendered as given
  integrity: { status: string; failures: Array<{ id: string; title?: string; reason?: string }> };
  links: Record<string, string>;
  findings: Array<Record<string, any>>; // eslint-disable-line @typescript-eslint/no-explicit-any
  debt_metrics: DebtMetricsView;
}
export interface DebtMetricsPayload {
  ok: true; project: { code: string; name: string }; freshness: string; history_rows: CreditHistoryRow[]; run: DebtMetricsRun | null; disclosure: string;
}
export interface DebtMetricsFailure { ok: false; code: string; message?: string }

/** Read-only: ONE committed Run (the explicit history id, or the Last Run when none is given) through the existing credit-decision adapter.
 *  The server fences owner, project, protected references and unknown Run ids; the answer is accepted only if it IS the Run that was asked for. */
export async function fetchDebtMetrics(project: string, historyId: string | null, signal?: AbortSignal): Promise<DebtMetricsPayload | DebtMetricsFailure> {
  const result = await fetchCreditDecision(project, historyId ? [historyId] : [], signal);
  if (!result.ok) return { ok: false, code: result.code, message: result.message };
  const runs = (result.data?.runs ?? []) as unknown as DebtMetricsRun[];
  const run = runs[0] ?? null;
  if (historyId && run && String(run.identity.history_id) !== historyId) {
    return { ok: false, code: "RUN_MISMATCH", message: "The server answered for a different Run than the one requested. Nothing is shown." };
  }
  if (run && (!run.debt_metrics || run.debt_metrics.schema !== "WF04_DEBT_METRICS_V1")) {
    return { ok: false, code: "DEBT_METRICS_UNAVAILABLE", message: "This server version does not provide Debt Metrics for the Run." };
  }
  return { ok: true, project: result.project, freshness: result.freshness, history_rows: result.history_rows, run, disclosure: result.data?.policy.disclosure ?? "" };
}
