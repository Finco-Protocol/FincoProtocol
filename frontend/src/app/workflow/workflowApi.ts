// WF-React-2 — authorized same-origin adapters for the editable workflows.
//
// Every call posts to an EXISTING canonical route.  The adapters classify the
// outcome truthfully: a followed redirect is never proof of a commit, so each
// caller reconciles against a fresh canonical projection, and anything
// unverifiable is UNKNOWN and is never retried automatically.

import { classifyFormPostOutcome } from "../api";
import type { CostLinesPayload } from "../types";

export type FormOutcome =
  | { outcome: "ok" }
  | { outcome: "refused"; message: string; status: number }
  | { outcome: "unknown"; message: string };

const UNKNOWN_SUFFIX = "Reload to reconcile before trying again - an immediate retry could duplicate the change.";

/** POST a urlencoded form to a canonical route and classify the answer.
 *  `expectedPath` is the clean-success destination of the route. */
export async function postWorkflowForm(
  url: string,
  fields: Record<string, string>,
  expectedPath = "/v2/workbook",
): Promise<FormOutcome> {
  const body = new URLSearchParams(fields);
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      redirect: "follow",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    });
  } catch {
    return { outcome: "unknown", message: `The outcome is UNKNOWN: the connection failed before a definitive response. ${UNKNOWN_SUFFIX}` };
  }
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    // Canonical JSON answers (auth / validation / conflict) are refusals with
    // the backend's own wording - never UNKNOWN and never a success.
    let message = `The server refused this change (HTTP ${response.status}). Nothing was changed.`;
    try {
      const payload = (await response.json()) as { error?: string; message?: string } | null;
      if (payload?.error) message = payload.error;
      else if (payload?.message) message = payload.message;
    } catch { /* keep the generic refusal */ }
    return { outcome: "refused", message, status: response.status };
  }
  const outcome = classifyFormPostOutcome(response, expectedPath);
  if (outcome.kind === "login") {
    return { outcome: "refused", status: 401, message: "Your session has expired - sign in again. Nothing was changed." };
  }
  if (outcome.kind === "error-redirect") return { outcome: "refused", status: response.status, message: outcome.v2Err };
  if (outcome.kind === "other") {
    return { outcome: "unknown", message: `The outcome is UNKNOWN: unexpected destination (${outcome.finalPath}). ${UNKNOWN_SUFFIX}` };
  }
  if (!response.ok) {
    return { outcome: "refused", status: response.status, message: `The server refused this change (HTTP ${response.status}). Nothing was changed.` };
  }
  return { outcome: "ok" };
}

// ───────────────────────────── CAPEX / OPEX line management ─────────────────────────────

export interface CostLineCas {
  project: string;
  workbookVersion: string;
  contentHash: string;
}

export function addCostLine(
  data: CostLinesPayload,
  cas: CostLineCas,
  line: { group: string; label: string; amount_keur: string; inflation_pct: string; notes: string },
): Promise<FormOutcome> {
  const mgmt = data.line_management;
  const fields: Record<string, string> = {
    project: cas.project,
    [mgmt.add.group_field]: line.group,
    label: line.label.trim(),
    amount_keur: line.amount_keur.trim(),
    notes: line.notes,
    workbook_version: cas.workbookVersion,
    content_hash: cas.contentHash,
  };
  if (data.sheet === "opex") fields.inflation_pct = line.inflation_pct.trim();
  return postWorkflowForm(mgmt.add.url, fields);
}

export function setCostLineActive(
  data: CostLinesPayload,
  cas: CostLineCas,
  subLineId: string,
  rowVersion: string,
  active: boolean,
): Promise<FormOutcome> {
  const mgmt = data.line_management;
  return postWorkflowForm((active ? mgmt.reactivate : mgmt.deactivate).url, {
    project: cas.project,
    sub_line_id: subLineId,
    row_version: rowVersion,
    workbook_version: cas.workbookVersion,
    content_hash: cas.contentHash,
  });
}

// ───────────────────────────── Last Run export ─────────────────────────────

export type ExportOutcome =
  | { ok: true; filename: string; bytes: number }
  | { ok: false; message: string };

/** Download the canonical Last Run workbook.  The route is read-only (no engine,
 *  no state change); a non-spreadsheet answer is shown as a refusal. */
export async function downloadLastRunWorkbook(project: string): Promise<ExportOutcome> {
  let response: Response;
  try {
    response = await fetch("/v2/workbook/export", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ project }).toString(),
    });
  } catch {
    return { ok: false, message: "The export could not be reached. Nothing was changed; try again." };
  }
  const type = response.headers.get("content-type") || "";
  if (!response.ok || !/spreadsheetml|octet-stream/.test(type)) {
    if (response.status === 401 || new URL(response.url).pathname === "/login") {
      return { ok: false, message: "Your session has expired - sign in again." };
    }
    return { ok: false, message: response.status === 400
      ? "No committed Run exists yet, so there is nothing to export. Run the model first."
      : `The export was refused (HTTP ${response.status}).` };
  }
  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") || "";
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  const filename = match ? match[1] : `${project}-last-run.xlsx`;
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(href);
  return { ok: true, filename, bytes: blob.size };
}

export const historicalExportUrl = (project: string, historyId: string) =>
  `/v2/workbook/run-history/export?project=${encodeURIComponent(project)}&history_id=${encodeURIComponent(historyId)}`;

// ───────────────────────────── Scenario overrides ─────────────────────────────

import type { ScenarioOverridesPayload } from "../types";

export async function fetchScenarioOverrides(project: string, scenarioId: string):
  Promise<ScenarioOverridesPayload | { ok: false; code: string; message?: string }> {
  let response: Response;
  try {
    response = await fetch(
      `/v2/model-react/scenario-overrides?project=${encodeURIComponent(project)}&scenario_id=${encodeURIComponent(scenarioId)}`,
      { credentials: "same-origin", headers: { Accept: "application/json" } },
    );
  } catch {
    return { ok: false, code: "SERVER_UNREACHABLE", message: "The FINCO Model server is unreachable." };
  }
  let body: unknown = null;
  try { body = await response.json(); } catch { body = null; }
  if (!response.ok || !body || typeof body !== "object") {
    const failed = body as { code?: string; message?: string } | null;
    return { ok: false, code: failed?.code || `HTTP_${response.status}`, message: failed?.message };
  }
  return body as ScenarioOverridesPayload;
}
