import type { ImportConfirm, ImportContext, ImportFailure, ImportPreview, ImportResult, RowChoice } from "./types";

const HEADERS = { Accept: "application/json", "X-Finco-React-Request": "1" };

async function send<T extends { ok: true }>(url: string, init: RequestInit): Promise<T | ImportFailure> {
  try {
    const response = await fetch(url, { credentials: "same-origin", cache: "no-store", redirect: "error", ...init, headers: { ...HEADERS, ...(init.headers ?? {}) } });
    const body = await response.json().catch(() => null) as (T | ImportFailure) | null;
    if (response.ok && body && body.ok === true) return body;
    const failed = (body ?? {}) as { code?: string; message?: string };
    return { ok: false, code: failed.code || `HTTP_${response.status}`, message: failed.message };
  } catch {
    return { ok: false, code: "SERVER_UNREACHABLE" };
  }
}

const q = (project: string) => `?${new URLSearchParams({ project })}`;

export const fetchImportContext = (project: string) => send<ImportContext>(`/v2/model-react/import/context${q(project)}`, { method: "GET" });

export function uploadForReview(project: string, csrf: string, file: File, encoding: string) {
  const form = new FormData();
  form.set("project", project); form.set("csrf_token", csrf); form.set("encoding", encoding); form.set("upload", file, file.name);
  return send<ImportPreview>(`/v2/model-react/import/preview${q(project)}`, { method: "POST", body: form });
}

export function confirmSelection(project: string, csrf: string, ticket: string, choices: Record<number, RowChoice>) {
  const form = new URLSearchParams({ project, csrf_token: csrf, preview_ticket: ticket });
  for (const [id, c] of Object.entries(choices)) {
    if (!c.keep) continue;
    form.set(`keep_${id}`, "on"); form.set(`field_${id}`, c.field); form.set(`unit_${id}`, c.unit);
    if (c.manual.trim()) form.set(`manual_${id}`, c.manual.trim());
  }
  return send<ImportConfirm>(`/v2/model-react/import/confirm${q(project)}`, { method: "POST", body: form, headers: { "Content-Type": "application/x-www-form-urlencoded" } });
}

export const applyApproved = (project: string, csrf: string, ticket: string) =>
  send<ImportResult>(`/v2/model-react/import/apply${q(project)}`, { method: "POST",
    body: new URLSearchParams({ project, csrf_token: csrf, approved_ticket: ticket }), headers: { "Content-Type": "application/x-www-form-urlencoded" } });
