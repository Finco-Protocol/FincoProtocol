export interface TrustFailure { ok: false; code: string; message?: string }
export interface TrustCertificate {
  state: string; reason?: string | null; schema_version?: string | null; issuer?: string | null; issued_at?: string | null; snapshot_id?: string | null;
  composite_hash?: string | null; composite_hash_short?: string | null; workbook_version?: string | null; engine_version?: string | null;
  active_scenario_id?: string | null; effective_input_status?: string | null; effective_input_unbound?: string[] | null; run_origin?: string | null;
  key_id?: string | null; payload_digest?: string | null; signature_algorithm?: string | null; not_verify?: boolean; authority?: string | null;
}
export interface TrustValidation {
  state: string; reason?: string | null; validation_state?: string | null; passed?: boolean | null; framework_passed?: boolean | null;
  product_reconciled?: boolean | null; pass_count?: number | null; fail_count?: number | null; gap_count?: number | null; authority?: string | null;
  gaps: Array<{ name?: string | null; detail?: string | null }>;
}

const HEADERS = { Accept: "application/json", "X-Finco-React-Request": "1" };

async function get<T>(path: string, project: string, pick: string): Promise<T | TrustFailure> {
  try {
    const response = await fetch(`/v2/model-react/trust/${path}?${new URLSearchParams({ project })}`, {
      credentials: "same-origin", cache: "no-store", redirect: "error", headers: HEADERS });
    const body = await response.json().catch(() => null) as ({ ok: true } & Record<string, unknown>) | TrustFailure | null;
    if (response.ok && body && body.ok === true && pick in body) return (body as Record<string, unknown>)[pick] as T;
    const failed = (body ?? {}) as { code?: string; message?: string };
    return { ok: false, code: failed.code || `HTTP_${response.status}`, message: failed.message };
  } catch {
    return { ok: false, code: "SERVER_UNREACHABLE" };
  }
}

export const requestCertificate = (project: string) => get<TrustCertificate>("certificate", project, "certificate");
export const requestReferenceRegression = (project: string) => get<TrustValidation>("validation", project, "validation");
export const isFailure = (value: unknown): value is TrustFailure => typeof value === "object" && value !== null && (value as TrustFailure).ok === false;
