import type { CapexFailure, CapexPreview, CapexProfiles, Draft } from "./types";

const HEADERS = { Accept: "application/json", "X-Finco-React-Request": "1" };

async function read<T extends { ok: true }>(url: string, signal?: AbortSignal): Promise<T | CapexFailure> {
  try {
    const response = await fetch(url, { credentials: "same-origin", cache: "no-store", headers: HEADERS, redirect: "error", signal });
    const body = await response.json().catch(() => null) as (T | CapexFailure) | null;
    if (response.ok && body && body.ok === true) return body;
    const failed = (body ?? {}) as { code?: string; message?: string };
    return { ok: false, code: failed.code || `HTTP_${response.status}`,
      message: failed.message || (response.status === 401 ? "Your session is not authorized. Sign in again." : "The CAPEX profile could not be read. Nothing was changed.") };
  } catch (error) {
    if ((error as { name?: string })?.name === "AbortError") return { ok: false, code: "CANCELLED", message: "Cancelled. Nothing was changed." };
    return { ok: false, code: "SERVER_UNREACHABLE", message: "The FINCO Model server is unreachable. Nothing was changed." };
  }
}

export const fetchCapexProfiles = (project: string, signal?: AbortSignal) =>
  read<CapexProfiles>(`/v2/model-react/capex/profiles?${new URLSearchParams({ project })}`, signal);

/** The compact draft the preview adapter reads: [item_key, shape, "explicit,percent,list", milestone] per item that has a shape. */
export function encodeSpec(items: readonly string[], draft: Draft): string {
  return JSON.stringify(items.filter((key) => draft[key]?.shape).map((key) => [key, draft[key].shape, draft[key].explicit, draft[key].milestone]));
}

export const fetchCapexPreview = (project: string, spec: string, signal?: AbortSignal) =>
  read<CapexPreview>(`/v2/model-react/capex/preview?${new URLSearchParams({ project, spec })}`, signal);

export type SaveOutcome =
  | { kind: "saved" }
  /** Definitive refusal: nothing was written. */
  | { kind: "refused"; code: string; message: string }
  /** Ambiguous: the writer may have committed.  Never retried; the studio must be reloaded. */
  | { kind: "unknown"; message: string };

const REFUSAL_TEXT: Record<string, string> = {
  CAPEX_PROFILE_CSRF_INVALID: "The security token expired. Reload the studio; nothing was changed.",
  CAPEX_PROFILE_READ_ONLY: "This project is read-only for you. Nothing was changed.",
  CAPEX_PROFILE_SCENARIO_EDIT_UNSUPPORTED: "A scenario is selected. Switch to the Base case to edit the profile. Nothing was changed.",
};

/** Post the EXISTING canonical form (CSRF + composite-hash CAS).  A followed redirect is not proof of a commit: the caller re-reads the
 *  projection to verify.  Anything unverifiable is UNKNOWN and is never retried automatically. */
export async function saveCapexProfile(args: {
  url: string; project: string; csrfToken: string; contentHash: string; action: "save" | "reset"; items: readonly string[]; draft: Draft;
}): Promise<SaveOutcome> {
  const unknown: SaveOutcome = { kind: "unknown", message: "The outcome is UNKNOWN: the profile may have been saved. Reload the studio to reconcile before trying again." };
  const fields: Record<string, string> = { project: args.project, csrf_token: args.csrfToken, content_hash: args.contentHash, action: args.action };
  args.items.forEach((key, index) => {
    const row = args.draft[key] ?? { shape: "", explicit: "", milestone: "" };
    fields[`key_${index}`] = key; fields[`shape_${index}`] = row.shape; fields[`explicit_${index}`] = row.explicit; fields[`milestone_${index}`] = row.milestone;
  });
  let response: Response;
  try {
    response = await fetch(args.url, { method: "POST", credentials: "same-origin", redirect: "follow",
      headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: new URLSearchParams(fields).toString() });
  } catch {
    return unknown;
  }
  const url = new URL(response.url);
  if (url.pathname === "/login") return { kind: "refused", code: "AUTH_REQUIRED", message: "Your session has expired — sign in again. Nothing was changed." };
  if (response.ok && url.pathname === "/v2/capex/spending-profiles" && /^(saved|reset)$/.test(url.searchParams.get("saved") ?? "")) return { kind: "saved" };
  if (response.status === 409 || response.status === 403 || response.status === 422) {
    const text = await response.text().catch(() => "");
    const code = /data-testid="profile-error"[^>]*>Request rejected: ([A-Z0-9_]+)/.exec(text)?.[1] ?? `HTTP_${response.status}`;
    const stale = code.includes("CONFLICT") || response.status === 409;
    return { kind: "refused", code, message: REFUSAL_TEXT[code]
      ?? (stale ? "Another change was saved since you loaded this page. Reload, then save again. Nothing was changed."
        : `The server refused the profile (${code}). Nothing was changed.`) };
  }
  return unknown;
}
