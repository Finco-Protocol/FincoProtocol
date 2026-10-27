import type { WhatIfFailure, WhatIfOptions, WhatIfPreview } from "./types";

const HEADERS = { Accept: "application/json", "X-Finco-React-Request": "1" };

async function read<T extends { ok: true }>(url: string, signal?: AbortSignal): Promise<T | WhatIfFailure> {
  try {
    const response = await fetch(url, { credentials: "same-origin", cache: "no-store", headers: HEADERS, redirect: "error", signal });
    const body = await response.json().catch(() => null) as (T | WhatIfFailure) | null;
    if (response.ok && body && body.ok === true) return body;
    const failed = (body ?? {}) as { code?: string; message?: string };
    return { ok: false, code: failed.code || `HTTP_${response.status}`, message: failed.message };
  } catch (error) {
    if ((error as { name?: string })?.name === "AbortError") return { ok: false, code: "CANCELLED" };
    return { ok: false, code: "SERVER_UNREACHABLE" };
  }
}

export const fetchWhatIfOptions = (project: string, signal?: AbortSignal) =>
  read<WhatIfOptions>(`/v2/model-react/whatif/options?${new URLSearchParams({ project })}`, signal);

export const fetchWhatIfPreview = (a: { project: string; checkId: string; value: string; name: string }, signal?: AbortSignal) =>
  read<WhatIfPreview>(`/v2/model-react/whatif/preview?${new URLSearchParams({
    project: a.project, check_id: a.checkId, proposed_value: a.value, scenario_name: a.name })}`, signal);

export type CommitOutcome =
  | { kind: "created"; scenarioId: string }
  /** Definitive refusal: nothing was created. */
  | { kind: "refused"; code: string }
  /** Ambiguous: the scenario may have been created.  Never retried; the Scenarios list must be checked. */
  | { kind: "unknown" };

/** Post the EXISTING signed-token commit route.  The answer is classified from the route's own markers; anything else is UNKNOWN. */
export async function commitWhatIf(url: string, project: string, token: string): Promise<CommitOutcome> {
  let response: Response;
  try {
    response = await fetch(url, { method: "POST", credentials: "same-origin", redirect: "follow",
      headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ project, token, confirmed: "yes" }).toString() });
  } catch {
    return { kind: "unknown" };
  }
  if (new URL(response.url).pathname === "/login") return { kind: "refused", code: "AUTH_REQUIRED" };
  const text = await response.text().catch(() => "");
  const created = /data-testid="q4-created"[\s\S]*?ID ([0-9a-f]{8,})/.exec(text);
  if (response.ok && created) return { kind: "created", scenarioId: created[1] };
  const rejected = /data-testid="q4-rejected"[^>]*>\s*([A-Z0-9_]+)\s+—\s+Nothing was changed/.exec(text);
  if (rejected && response.status >= 400 && response.status < 500) return { kind: "refused", code: rejected[1] };
  return { kind: "unknown" };
}
