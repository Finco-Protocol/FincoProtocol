import type { FinancingStudioPayload } from "./types";

export type StudioResult = FinancingStudioPayload | { ok: false; code: string; message?: string };

/** Authorized read of the Financing Studio projection (same-origin, no-store). */
export async function fetchFinancingStudio(project: string): Promise<StudioResult> {
  let response: Response;
  try {
    response = await fetch(`/v2/model-react/financing/studio?project=${encodeURIComponent(project)}`,
      { credentials: "same-origin", headers: { Accept: "application/json" } });
  } catch {
    return { ok: false, code: "SERVER_UNREACHABLE", message: "The FINCO Model server is unreachable." };
  }
  const body = await response.json().catch(() => null) as (FinancingStudioPayload | { code?: string; message?: string }) | null;
  if (response.ok && body && (body as { ok?: boolean }).ok === true) return body as FinancingStudioPayload;
  const failed = (body ?? {}) as { code?: string; message?: string };
  return { ok: false, code: failed.code || `HTTP_${response.status}`, message: failed.message };
}
