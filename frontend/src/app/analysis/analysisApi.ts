// Same-origin fetch adapters for Analysis > Sensitivity / Goal Seek.  The read-only calls carry `X-Finco-React-Request: 1`
// (a custom header a cross-site page cannot send without a CORS preflight).  The single write — Goal Seek Apply — is a JSON POST
// with a signed, project-bound token.  Nothing here retries: a busy or ambiguous outcome is shown and the user decides.
import type {
  AdapterFailure, GoalSeekApplied, GoalSeekApplyBinding, GoalSeekCatalog, GoalSeekPreview, GoalSeekTargets, MatrixResult, SensitivityCatalog, StripResult,
} from "./types";

const BASE = "/v2/model-react/analysis";
const HEADERS = { Accept: "application/json", "X-Finco-React-Request": "1" };

async function read<T extends { ok: true }>(url: string, signal?: AbortSignal): Promise<T | AdapterFailure> {
  let response: Response;
  try {
    response = await fetch(url, { credentials: "same-origin", headers: HEADERS, signal });
  } catch (error) {
    if ((error as { name?: string })?.name === "AbortError") return { ok: false, code: "CANCELLED", message: "Cancelled. Nothing was changed.", status: 0 };
    return { ok: false, code: "SERVER_UNREACHABLE", message: "The FINCO Model server is unreachable. Nothing was changed.", status: 0 };
  }
  const body = await response.json().catch(() => null) as (T | { ok?: false; code?: string; message?: string }) | null;
  if (response.ok && body && (body as { ok?: boolean }).ok === true) return body as T;
  const failed = (body ?? {}) as { code?: string; message?: string };
  return {
    ok: false, status: response.status, code: failed.code || `HTTP_${response.status}`,
    message: failed.message || (response.status === 401 ? "Your session is not authorized. Sign in again." : undefined),
  };
}

const q = (params: Record<string, string>) => new URLSearchParams(Object.entries(params).filter(([, v]) => v !== "")).toString();

export const fetchSensitivityCatalog = (project: string) =>
  read<SensitivityCatalog>(`${BASE}/sensitivity/catalog?${q({ project })}`);

export const runStrip = (a: { project: string; driver: string; levels: string; scenarioId: string }, signal?: AbortSignal) =>
  read<StripResult>(`${BASE}/sensitivity/strip?${q({ project: a.project, driver: a.driver, levels: a.levels, scenario_id: a.scenarioId })}`, signal);

export const runMatrix = (
  a: { project: string; driverA: string; driverB: string; metric: string; grid: string; levelsA: string; levelsB: string; threshold: string; scenarioId: string },
  signal?: AbortSignal,
) => read<MatrixResult>(`${BASE}/sensitivity/matrix?${q({
  project: a.project, driver_a: a.driverA, driver_b: a.driverB, metric: a.metric, grid: a.grid,
  levels_a: a.levelsA, levels_b: a.levelsB, threshold: a.threshold, scenario_id: a.scenarioId })}`, signal);

export const fetchGoalSeekCatalog = (project: string) => read<GoalSeekCatalog>(`${BASE}/goal-seek/catalog?${q({ project })}`);

export const fetchGoalSeekTargets = (project: string) => read<GoalSeekTargets>(`${BASE}/goal-seek/targets?${q({ project })}`);

/** The target is sent in the unit the server declared for the metric (`percent` | `multiple` | `keur`); the server refuses a mismatch. */
export const solveGoalSeek = (a: { project: string; metric: string; target: string; unit: string }, signal?: AbortSignal) =>
  read<GoalSeekPreview>(`${BASE}/goal-seek/solve-typed?${q({ project: a.project, target_metric: a.metric, target_value: a.target, target_unit: a.unit })}`, signal);

export type ApplyOutcome =
  | { kind: "applied"; applied: GoalSeekApplied }
  /** Definitive refusal: the Working Copy was not changed. */
  | { kind: "refused"; code: string; message: string }
  /** Ambiguous: the writer may have committed.  Never retried; the workspace must be reloaded. */
  | { kind: "unknown"; message: string };

export async function applyGoalSeek(project: string, binding: GoalSeekApplyBinding): Promise<ApplyOutcome> {
  const unknown: ApplyOutcome = {
    kind: "unknown",
    message: "Result unknown — the tariff may have been applied. Reload the workspace to check before solving again.",
  };
  let response: Response;
  try {
    response = await fetch(`${BASE}/goal-seek/apply`, {
      method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ project, field_id: binding.field_id, value: binding.value, content_hash: binding.content_hash,
                             workbook_version: binding.workbook_version, csrf_token: binding.csrf_token }),
    });
  } catch {
    return unknown;
  }
  const body = await response.json().catch(() => null) as (GoalSeekApplied | { ok?: false; code?: string; message?: string }) | null;
  if (response.ok && body && (body as GoalSeekApplied).ok === true) return { kind: "applied", applied: body as GoalSeekApplied };
  if (response.status >= 500 || !body) return unknown;
  const failed = body as { code?: string; message?: string };
  if (response.status === 403) return { kind: "refused", code: failed.code || "CSRF_INVALID", message: "The security token expired. Solve again; nothing was changed." };
  if (response.status === 401) return { kind: "refused", code: "AUTH_REQUIRED", message: "Your session is not authorized. Sign in again; nothing was changed." };
  return { kind: "refused", code: failed.code || `HTTP_${response.status}`, message: failed.message || "The server refused the request. Nothing was changed." };
}
