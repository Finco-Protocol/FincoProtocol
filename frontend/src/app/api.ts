// Authorized fetch adapters for the UX-02..06 React workspace.  Same-origin
// only; every mutation stays on the canonical routes (grid/save,
// cost-lines/save, workbook/update, revenue/contracts, library/clone and
// workbook/run — Run initiation goes through the canonical route's own form
// contract (303 on success / ?v2_err= on failure); Save NEVER triggers a Run).

import type {
  InputsPayload,
  LibraryPayload,
  StatementsPayload,
  WorkspacePayload,
} from "./types";

async function getJson<T>(url: string): Promise<T | { ok: false; code: string; message?: string }> {
  let response: Response;
  try {
    response = await fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } });
  } catch {
    return { ok: false, code: "SERVER_UNREACHABLE", message: "The FINCO Model server is unreachable." };
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok || !body || typeof body !== "object") {
    const failed = body as { code?: string; message?: string } | null;
    return {
      ok: false,
      code: (failed && failed.code) || `HTTP_${response.status}`,
      message: (failed && failed.message) || undefined,
    };
  }
  return body as T;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** A Save/Run committing concurrently can invalidate one read snapshot
 *  (WORKSPACE_UNAVAILABLE); retry briefly before surfacing it. */
async function withContentionRetry<T extends { ok: boolean; code?: string }>(
  fetcher: () => Promise<T>,
): Promise<T> {
  let result = await fetcher();
  for (let attempt = 0; result.ok === false && result.code === "WORKSPACE_UNAVAILABLE" && attempt < 3; attempt += 1) {
    await sleep(600 * (attempt + 1));
    result = await fetcher();
  }
  return result;
}

export const fetchLibrary = (search: string, page: number) =>
  getJson<LibraryPayload>(`/v2/model-react/library?search=${encodeURIComponent(search)}&page=${page}`);

export const fetchWorkspace = (project: string) =>
  withContentionRetry(() =>
    getJson<WorkspacePayload>(`/v2/model-react/workspace?project=${encodeURIComponent(project)}`));

export const fetchStatements = (project: string) =>
  withContentionRetry(() =>
    getJson<StatementsPayload>(`/v2/model-react/statements?project=${encodeURIComponent(project)}`));

export const fetchInputs = (project: string) =>
  withContentionRetry(() =>
    getJson<InputsPayload>(`/v2/model-react/inputs?project=${encodeURIComponent(project)}`));

export interface CreateWorkingCopyArgs {
  cloneUrlTemplate: string;
  csrfToken: string;
  sourceProjectId: string;
  requestedName: string;
}

export type CreateWorkingCopyResult =
  | { ok: true; projectCode: string }
  /** The canonical route explicitly refused (4xx with a JSON error) - nothing
   *  was created; the user may adjust and retry. */
  | { ok: false; message: string }
  /** The transport outcome could not be confirmed: the canonical route answers
   *  success with a redirect AFTER creating the copy, so a lost response does
   *  NOT prove that no Working Copy exists.  The caller must reconcile (reload
   *  the Library) and never blind-retry, which could create duplicates. */
  | { kind: "unknown"; message: string };

export function isCloneUnknown(
  result: CreateWorkingCopyResult,
): result is Extract<CreateWorkingCopyResult, { kind: "unknown" }> {
  return "kind" in result;
}

function projectCodeFromRedirectedUrl(url: string): string | null {
  try {
    return new URL(url).searchParams.get("project");
  } catch {
    return null;
  }
}

/** Working-copy creation through the EXISTING canonical `/library/clone/{id}`
 *  route (303 redirect to the new project's workbook on success, 400 JSON on a
 *  refusal, 5xx page on server failure).  Correction-A semantics apply: an
 *  ambiguous transport outcome is classified `unknown` and never retried
 *  automatically, because a retry could create a duplicate Working Copy. */
export async function createWorkingCopy(args: CreateWorkingCopyArgs): Promise<CreateWorkingCopyResult> {
  const url = args.cloneUrlTemplate.replace("{source_project_id}", encodeURIComponent(args.sourceProjectId));
  const body = new URLSearchParams({ csrf_token: args.csrfToken });
  if (args.requestedName.trim()) body.set("requested_name", args.requestedName.trim());
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
      body: body.toString(),
    });
  } catch {
    return {
      kind: "unknown",
      message: "The creation result is UNKNOWN: the connection failed before a definitive response. "
        + "The server may have created the Working Copy. Reload the Project Library to reconcile "
        + "before trying again - an immediate retry could create a duplicate.",
    };
  }
  if (response.ok) {
    // Success contract: 303 redirect to the new project's workbook (followed
    // automatically); the new project code travels in the final URL.
    const code = projectCodeFromRedirectedUrl(response.url);
    if (code) return { ok: true, projectCode: code };
    return {
      kind: "unknown",
      message: "The creation result is UNKNOWN: the server accepted the request but the new "
        + "project code could not be read from the response. Reload the Project Library to "
        + "reconcile before trying again - an immediate retry could create a duplicate.",
    };
  }
  if (response.status === 401) {
    return { ok: false, message: "Your session is not authorized. Sign in again; nothing was created." };
  }
  let payload: { error?: string } | null = null;
  try {
    payload = (await response.json()) as { error?: string };
  } catch {
    payload = null;
  }
  if (payload && payload.error) {
    return { ok: false, message: payload.error };
  }
  if (response.status >= 500) {
    return {
      ok: false,
      message: `Working-copy creation failed on the server (HTTP ${response.status}). `
        + "Check the Project Library before retrying so a partially created copy is not duplicated.",
    };
  }
  return { ok: false, message: `Working-copy creation failed (HTTP ${response.status}).` };
}

// ── UX-04/05/06 canonical surface fetchers ──────────────────────────────────

import type {
  CostLinesPayload,
  DiagnosticsPayload,
  RevenueContractsPayload,
  RunHistoryEntry,
  RunsPayload,
  SheetFieldsPayload,
  TrustPayload,
} from "./types";

export const fetchSheetFields = (project: string, sheet: string) =>
  withContentionRetry(() =>
    getJson<SheetFieldsPayload>(`/v2/model-react/fields/${encodeURIComponent(sheet)}?project=${encodeURIComponent(project)}`));

export const fetchCostLines = (project: string, sheet: "capex" | "opex") =>
  withContentionRetry(() =>
    getJson<CostLinesPayload>(`/v2/model-react/costlines?sheet=${sheet}&project=${encodeURIComponent(project)}`));

export const fetchRevenueContracts = (project: string) =>
  withContentionRetry(() =>
    getJson<RevenueContractsPayload>(`/v2/model-react/revenue?project=${encodeURIComponent(project)}`));

export const fetchRuns = (project: string) =>
  withContentionRetry(() => getJson<RunsPayload>(`/v2/model-react/runs?project=${encodeURIComponent(project)}`));

export const fetchDiagnostics = (project: string) =>
  withContentionRetry(() =>
    getJson<DiagnosticsPayload>(`/v2/model-react/diagnostics?project=${encodeURIComponent(project)}`));

export const fetchTrust = (project: string) =>
  withContentionRetry(() => getJson<TrustPayload>(`/v2/model-react/trust?project=${encodeURIComponent(project)}`));

export interface RunModelArgs {
  runUrl: string;
  project: string;
  contentHash: string;
  workbookVersion: string;
}

export type RunModelResult =
  | { ok: true }
  | { ok: false; message: string }
  | { kind: "unknown"; message: string };

/** Run initiation through the EXISTING canonical `/v2/workbook/run` route.
 *  The user presses Run explicitly; Save never triggers this.  Success answers a
 *  303 redirect to the workbook (followed); a user-safe failure redirects with
 *  `?v2_err=`.  A lost connection is UNKNOWN — the Run may or may not have
 *  committed — so the caller must reconcile from the workspace snapshot and
 *  never blind-retry an ambiguous financial mutation. */
export async function runModel(args: RunModelArgs): Promise<RunModelResult> {
  // Correction A (UX-07 workstream A): a followed redirect that lands on a 200
  // HTML page is NOT proof of a committed Run.  Success is established only by
  // the canonical redirect contract AND fresh persisted Run History evidence:
  // the committed-history count must grow after a clean redirect.
  const runsUrl = `/v2/model-react/runs?project=${encodeURIComponent(args.project)}`;
  const before = await getJson<RunsPayload>(runsUrl);
  const beforeCount = before.ok === true ? before.runs.length : null;

  const body = new URLSearchParams({
    project: args.project,
    content_hash: args.contentHash,
    workbook_version: args.workbookVersion,
  });
  let response: Response;
  try {
    response = await fetch(args.runUrl, {
      method: "POST",
      credentials: "same-origin",
      redirect: "follow",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    });
  } catch {
    return {
      kind: "unknown",
      message: "The Run outcome is UNKNOWN: the connection failed before a definitive response. "
        + "Reload the workspace to reconcile the persisted Last Run before running again — never re-run blindly.",
    };
  }
  const outcome = classifyFormPostOutcome(response, "/v2/workbook");
  if (outcome.kind === "login") {
    return { ok: false, message: "Your session has expired — sign in again. No Run was started." };
  }
  if (outcome.kind === "error-redirect") {
    return { ok: false, message: outcome.v2Err };
  }
  if (outcome.kind === "other") {
    return {
      kind: "unknown",
      message: `The Run outcome is UNKNOWN: the server redirected to an unexpected destination (${outcome.finalPath}). `
        + "Reload the workspace to reconcile the persisted Last Run before running again.",
    };
  }
  // Clean canonical success redirect.  Reconcile against persisted evidence:
  // the committed Run History must show a NEW entry, otherwise the outcome is
  // UNKNOWN (never success).
  const after = await getJson<RunsPayload>(runsUrl);
  if (after.ok === true && beforeCount !== null && after.runs.length > beforeCount) {
    return { ok: true };
  }
  return {
    kind: "unknown",
    message: "The Run outcome is UNKNOWN: the canonical redirect arrived but the persisted Run History "
      + "could not confirm a new committed Run. Reload the workspace to reconcile — do not re-run blindly.",
  };
}

export type HistoryRow = RunHistoryEntry;

// ── Correction A: truthful mutation-outcome classification ──────────────────
//
// The canonical non-HTMX form routes answer with REDIRECTS (303 success /
// 303 + ?v2_err= failure / 302 → /login on an expired session), and a browser
// fetch follows them, so the FINAL response can be a 200 HTML page whose URL is
// the only honest signal.  HTTP 200 alone is never proof that a financial
// mutation committed: these helpers classify the final destination and, where a
// redirect still cannot prove a commit, reconcile against a fresh canonical
// projection before any success is claimed.  Anything unverifiable is UNKNOWN
// and is never retried automatically.

export type FormPostOutcome =
  | { kind: "login" }
  | { kind: "error-redirect"; v2Err: string }
  | { kind: "clean"; finalPath: string }
  | { kind: "other"; finalPath: string };

export function classifyFormPostOutcome(response: Response, expectedPath: string): FormPostOutcome {
  let url: URL;
  try {
    url = new URL(response.url);
  } catch {
    return { kind: "other", finalPath: "<unreadable>" };
  }
  if (url.pathname === "/login") return { kind: "login" };
  const v2Err = url.searchParams.get("v2_err");
  if (v2Err !== null) return { kind: "error-redirect", v2Err };
  if (url.pathname === expectedPath) return { kind: "clean", finalPath: url.pathname };
  return { kind: "other", finalPath: url.pathname };
}

async function postForm(url: string, body: URLSearchParams): Promise<Response | null> {
  try {
    return await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      redirect: "follow",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    });
  } catch {
    return null;
  }
}

export interface SaveWorkbookFieldArgs {
  updateUrl: string;
  project: string;
  fieldId: string;
  value: string;
  workbookVersion: string;
  contentHash: string;
  csrfToken: string;
  /** The bound financing CSRF token — required ONLY by
   *  `debt.financing.instruments` (the canonical route 403s otherwise). */
  financingCsrfToken?: string;
  /** Reconcile a clean canonical redirect against fresh authorized evidence
   *  before success is claimed (e.g. re-read the projection and compare the
   *  persisted field value). */
  verifyCommitted?: () => Promise<boolean>;
}

export type SaveWorkbookFieldResult =
  | { ok: true; verified: boolean }
  | { ok: false; message: string }
  | { kind: "unknown"; message: string };

export async function saveWorkbookField(args: SaveWorkbookFieldArgs): Promise<SaveWorkbookFieldResult> {
  const body = new URLSearchParams({
    project: args.project,
    field_id: args.fieldId,
    value: args.value,
    workbook_version: args.workbookVersion,
    content_hash: args.contentHash,
    sheet_id: "debt",
    // The canonical route requires the BOUND financing token for
    // debt.financing.instruments and the grid token for every other field.
    csrf_token: args.fieldId === "debt.financing.instruments"
      ? (args.financingCsrfToken ?? "")
      : args.csrfToken,
  });
  const response = await postForm(args.updateUrl, body);
  if (response === null) {
    return {
      kind: "unknown",
      message: "The Save outcome is UNKNOWN: the connection failed before a definitive response. "
        + "Reload to reconcile — do not re-submit blindly.",
    };
  }
  const outcome = classifyFormPostOutcome(response, "/v2/workbook");
  if (outcome.kind === "login") {
    return { ok: false, message: "Your session has expired — sign in again. The field was NOT saved." };
  }
  if (outcome.kind === "error-redirect") {
    return { ok: false, message: outcome.v2Err };
  }
  if (outcome.kind === "other") {
    return {
      kind: "unknown",
      message: `The Save outcome is UNKNOWN: the server redirected to an unexpected destination (${outcome.finalPath}). `
        + "Reload to reconcile before saving again.",
    };
  }
  // Canonical success redirect.  Where the caller can reconcile, a clean
  // redirect alone is not treated as proof: verify through fresh evidence.
  if (args.verifyCommitted) {
    let committed = false;
    try {
      committed = await args.verifyCommitted();
    } catch {
      committed = false;
    }
    if (!committed) {
      return {
        kind: "unknown",
        message: "The Save outcome is UNKNOWN: the canonical redirect arrived but the fresh projection "
          + "could not confirm the saved value. Reload to reconcile — the edit may or may not be committed.",
      };
    }
    return { ok: true, verified: true };
  }
  return { ok: true, verified: false };
}

export interface SaveCostLinesBatchArgs {
  saveUrl: string;
  project: string;
  csrfToken: string;
  workbookVersion: string;
  contentHash: string;
  sheet: "capex" | "opex";
  edits: Array<Record<string, unknown>>;
}

export type SaveCostLinesBatchResult =
  | { ok: true; savedCount: number }
  | { ok: false; message: string }
  | { kind: "unknown"; message: string };

/** Atomic CAPEX/OPEX line batch through the canonical writer.  Success is the
 *  `X-Cost-Batch-Saved` header on the canonical response — a redirect to the
 *  login page or any other HTML answer without the header is NOT a success. */
export async function saveCostLinesBatch(args: SaveCostLinesBatchArgs): Promise<SaveCostLinesBatchResult> {
  const body = new URLSearchParams({
    project: args.project,
    csrf_token: args.csrfToken,
    workbook_version: args.workbookVersion,
    content_hash: args.contentHash,
    sheet: args.sheet,
    payload: JSON.stringify(args.edits),
  });
  const response = await postForm(args.saveUrl, body);
  if (response === null) {
    return {
      kind: "unknown",
      message: "The batch outcome is UNKNOWN: the connection failed before a definitive response. "
        + "Reload to reconcile — do not re-submit blindly.",
    };
  }
  const savedCount = response.headers.get("X-Cost-Batch-Saved");
  if (response.ok && savedCount !== null) return { ok: true, savedCount: Number(savedCount) };
  const outcome = classifyFormPostOutcome(response, "/v2/workbook");
  if (outcome.kind === "login") {
    return { ok: false, message: "Your session has expired — sign in again. No line was saved." };
  }
  let message = `Batch refused (HTTP ${response.status}). No line was saved.`;
  try {
    const payload = (await response.json()) as { message?: string };
    if (payload && payload.message) message = payload.message;
  } catch { /* HTML answers (redirects) keep the generic refusal */ }
  if (outcome.kind === "error-redirect") message = outcome.v2Err;
  return { ok: false, message };
}

// ── UX-07: scenario management & compare + revenue contract writer ──────────

import type { ScenariosPayload, ScenarioComparePayload } from "./types";

export const fetchScenarios = (project: string) =>
  withContentionRetry(() => getJson<ScenariosPayload>(`/v2/model-react/scenarios?project=${encodeURIComponent(project)}`));

export const fetchScenarioCompare = (project: string, scenarioId: string) =>
  withContentionRetry(() =>
    getJson<ScenarioComparePayload>(`/v2/model-react/scenario-compare?project=${encodeURIComponent(project)}&scenario_id=${encodeURIComponent(scenarioId)}`));

export interface RevenueContractsSaveArgs {
  saveUrl: string;
  project: string;
  csrfToken: string;
  contentHash: string;
  /** The canonical revenue payload JSON string (streams + products); the
   *  canonical writer validates it — the client never prices anything. */
  contractsJson: string;
}

export type RevenueContractsSaveResult =
  | { ok: true }
  | { ok: false; message: string }
  | { kind: "unknown"; message: string };

/** Revenue/PPA contract save through the canonical writer (composite CAS,
 *  bound CSRF, atomic).  Validation errors are the canonical service's own
 *  typed errors — the client displays them verbatim. */
export async function saveRevenueContracts(args: RevenueContractsSaveArgs): Promise<RevenueContractsSaveResult> {
  const body = new URLSearchParams({
    project: args.project,
    csrf_token: args.csrfToken,
    content_hash: args.contentHash,
    contracts: args.contractsJson,
    action: "save",
  });
  const response = await postForm(args.saveUrl, body);
  if (response === null) {
    return {
      kind: "unknown",
      message: "The contracts-save outcome is UNKNOWN: the connection failed before a definitive response. "
        + "Reload to reconcile — do not re-submit blindly.",
    };
  }
  // The canonical writer answers DIRECT JSON errors (401/403/404/409/422) on
  // its own route — surface them as refusals with the typed message; a success
  // is the clean workbook redirect.
  let payload: { error?: string } | null = null;
  if (!response.ok || response.headers.get("content-type")?.includes("application/json")) {
    try {
      payload = (await response.json()) as { error?: string } | null;
    } catch { payload = null; }
  }
  if (payload && payload.error) return { ok: false, message: payload.error };
  if (!response.ok) return { ok: false, message: `The contracts save was refused (HTTP ${response.status}). Nothing was saved.` };
  const outcome = classifyFormPostOutcome(response, "/v2/workbook");
  if (outcome.kind === "login") {
    return { ok: false, message: "Your session has expired — sign in again. The contracts were NOT saved." };
  }
  if (outcome.kind === "error-redirect") return { ok: false, message: outcome.v2Err };
  if (outcome.kind === "other") {
    return {
      kind: "unknown",
      message: `The contracts-save outcome is UNKNOWN: unexpected destination (${outcome.finalPath}). Reload to reconcile.`,
    };
  }
  return { ok: true };
}
