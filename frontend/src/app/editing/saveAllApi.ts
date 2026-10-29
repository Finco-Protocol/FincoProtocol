// WS-2 / M-008 — the single Save All HTTP call and honest classification of its outcome.
//
// One POST, one response.  The server is idempotent by `request_id`, so an UNKNOWN outcome (lost response) is
// reconciled by re-sending the IDENTICAL request: a committed request returns its stored outcome, an uncommitted one
// is applied exactly once.  Nothing here saves a section on its own or runs the model.

import type { SaveAllOutcome, SaveAllRequest } from "./saveAll";

type Json = Record<string, unknown>;

export async function postSaveAll(url: string, request: SaveAllRequest, fetchImpl: typeof fetch = fetch): Promise<SaveAllOutcome> {
  let response: Response;
  try {
    response = await fetchImpl(url, {
      method: "POST", credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request),
    });
  } catch {
    return { kind: "unknown", message: "The connection failed before the server answered. Use “Check and retry”: the same request is safe to repeat and is applied at most once." };
  }
  let body: Json | null = null;
  try { body = (await response.json()) as Json; } catch { body = null; }
  if (response.ok && body && body.ok === true) {
    return { kind: "saved", contentHash: String(body.content_hash ?? ""), runState: String(body.run_state ?? ""), savedIds: [] };
  }
  if (!body) {
    // An unreadable answer (proxy page, redirect to login) is not proof of either outcome.
    return response.status === 401 || response.status === 403
      ? { kind: "rejected", code: "AUTH", message: "Your session has expired or the request was refused. Nothing was saved.", conflicts: {} }
      : { kind: "unknown", message: "The server answer could not be read. Use “Check and retry”: the same request is safe to repeat." };
  }
  const code = String(body.code ?? "SAVE_ALL_REJECTED");
  const message = String(body.message ?? "Save All was refused. Nothing was saved.");
  if (response.status === 409 && body.reload === true) return { kind: "stale", message };
  const conflicts: Record<string, { message: string }> = {};
  const lines = Array.isArray(body.lines) ? (body.lines as Json[]) : [];
  for (const line of lines) {
    if (line && line.ok === false && typeof line.sub_line_id === "string" && typeof line.kind === "string") {
      conflicts[`${line.kind}:${line.sub_line_id}#amount`] = { message: String(line.message ?? "This line was rejected.") };
    }
  }
  return { kind: "rejected", code, message, conflicts };
}
