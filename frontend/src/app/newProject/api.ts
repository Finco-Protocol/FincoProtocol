// Authorized same-origin adapters for the New Project wizard.  The single mutation is
// POST /v2/model-react/new-project/create (session + signed CSRF bound to the request id);
// an ambiguous outcome is classified "unknown" and is NEVER retried by this client.
import type {
  TemplateCard,
  CreateResult, CreatedProject, PreviewResult, StatusResult, WizardFieldError, WizardInput, WizardOptions,
} from "./types";

const BASE = "/v2/model-react/new-project";

export async function fetchWizardOptions(): Promise<{ ok: true; options: WizardOptions } | { ok: false; code: string; message: string }> {
  let response: Response;
  try {
    response = await fetch(`${BASE}/options`, { credentials: "same-origin", headers: { Accept: "application/json" } });
  } catch {
    return { ok: false, code: "SERVER_UNREACHABLE", message: "The FINCO Model server is unreachable." };
  }
  const body = await response.json().catch(() => null) as (WizardOptions | { code?: string }) | null;
  if (!response.ok || !body || !("technologies" in body)) {
    const code = (body && "code" in body && body.code) || `HTTP_${response.status}`;
    return {
      ok: false, code,
      message: response.status === 401 ? "Your session is not authorized. Sign in again." : "The New Project options could not be loaded.",
    };
  }
  return { ok: true, options: body };
}

export async function fetchWizardPreview(input: WizardInput): Promise<PreviewResult> {
  const params = new URLSearchParams({
    name: input.name, technology: input.technology, country: input.country, capacity_mw: input.capacity_mw,
  });
  let response: Response;
  try {
    response = await fetch(`${BASE}/preview?${params.toString()}`, { credentials: "same-origin", headers: { Accept: "application/json" } });
  } catch {
    return { kind: "failed", message: "The server is unreachable. Nothing was created." };
  }
  const body = await response.json().catch(() => null) as
    { ok?: boolean; errors?: WizardFieldError[]; code?: string } | null;
  if (response.ok && body && body.ok) return { kind: "ok", preview: body as unknown as import("./types").WizardPreview };
  if (response.status === 422 && body?.errors) return { kind: "invalid", errors: body.errors };
  return { kind: "failed", message: response.status === 401 ? "Your session is not authorized. Sign in again." : "The preview could not be loaded." };
}

function asProject(value: unknown): CreatedProject | null {
  const p = value as Partial<CreatedProject> | null;
  return p && typeof p.code === "string" && p.code ? (p as CreatedProject) : null;
}

export async function fetchWizardStatus(requestId: string): Promise<StatusResult> {
  try {
    const response = await fetch(`${BASE}/status?request_id=${encodeURIComponent(requestId)}`,
      { credentials: "same-origin", headers: { Accept: "application/json" } });
    const body = await response.json().catch(() => null) as { ok?: boolean; created?: boolean; project?: unknown } | null;
    if (!response.ok || !body?.ok) return { kind: "failed" };
    const project = body.created ? asProject(body.project) : null;
    return project ? { kind: "created", project } : { kind: "not_found" };
  } catch {
    return { kind: "failed" };
  }
}

export interface CreateArgs {
  requestId: string;
  csrfToken: string;
  input: WizardInput;
  acknowledgePreview: boolean;
}

const UNKNOWN_MESSAGE = "We could not confirm whether the project was created. Check My Projects before creating it again.";

export async function createNewProject(args: CreateArgs): Promise<CreateResult> {
  let response: Response;
  try {
    response = await fetch(`${BASE}/create`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        request_id: args.requestId, csrf_token: args.csrfToken, name: args.input.name,
        technology: args.input.technology, country: args.input.country,
        capacity_mw: Number(args.input.capacity_mw), acknowledge_preview: args.acknowledgePreview,
      }),
    });
  } catch {
    return { kind: "unknown", message: UNKNOWN_MESSAGE };
  }
  const body = await response.json().catch(() => null) as
    { ok?: boolean; code?: string; message?: string; errors?: WizardFieldError[]; replayed?: boolean; project?: unknown } | null;
  if (response.ok && body?.ok) {
    const project = asProject(body.project);
    return project ? { kind: "created", project, replayed: Boolean(body.replayed) } : { kind: "unknown", message: UNKNOWN_MESSAGE };
  }
  // 5xx (including the server's own CREATE_OUTCOME_UNKNOWN) and unreadable bodies: the writer may have run.
  if (response.status >= 500 || !body || !body.code) return { kind: "unknown", message: UNKNOWN_MESSAGE };
  if (response.status === 401) return { kind: "refused", code: "AUTH_REQUIRED", message: "Your session has expired. Sign in again — nothing was created." };
  if (response.status === 403) {
    return { kind: "refused", code: body.code, message: "Your session security check expired. Reload the page and try again — nothing was created." };
  }
  return { kind: "refused", code: body.code, message: body.message || "The server refused the request; nothing was created.", errors: body.errors };
}

// The identity of an in-flight Create travels in the URL hash (`#new-project:<request id>`), never in browser storage:
// after a reload the wizard reconciles that request by identity instead of ever repeating it.
const HASH_BASE = "#new-project";
const PENDING_HASH = /^#new-project:([0-9a-f]{32})$/;

/** `#new-project` opens the wizard at its first step; `/template` and `/new` open it with a creation path already chosen. */
export type WizardPath = "" | "new" | "template";
const PATH_HASH = /^#new-project\/(new|template)$/;

export function isWizardHash(hash: string): boolean {
  return hash === HASH_BASE || PENDING_HASH.test(hash) || PATH_HASH.test(hash);
}
export function pathFromHash(hash: string): WizardPath {
  const match = PATH_HASH.exec(hash);
  return match ? (match[1] as WizardPath) : "";
}
export function savePending(requestId: string): void {
  window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}${HASH_BASE}:${requestId}`);
}
export function clearPending(): void {
  if (PENDING_HASH.test(window.location.hash)) {
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}${HASH_BASE}`);
  }
}
export function readPending(): string | null {
  const match = PENDING_HASH.exec(window.location.hash);
  return match ? match[1] : null;
}

/** The Project Templates (read-only starting models) with their starting assumptions, from GET /model-react/templates. */
export async function fetchTemplates(): Promise<{ ok: true; templates: TemplateCard[] } | { ok: false; message: string }> {
  try {
    const response = await fetch("/v2/model-react/templates", { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" } });
    const body = await response.json().catch(() => null) as { ok?: boolean; templates?: TemplateCard[] } | null;
    if (response.ok && body?.ok && Array.isArray(body.templates)) return { ok: true, templates: body.templates };
  } catch { /* fall through */ }
  return { ok: false, message: "The templates could not be loaded. Nothing was changed." };
}
