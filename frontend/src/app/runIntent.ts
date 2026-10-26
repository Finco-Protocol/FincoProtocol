// D-029 — client half of the Run intent contract.
//
// One deliberate Run = one UUIDv4.  The intent (with the ORIGINAL submitted
// content hash / workbook version) is kept through an ambiguous outcome and a
// page reload, and a retry re-submits that SAME binding so the server can
// reconcile it by key.  Nothing here is authority: the server decides whether
// the key is new, replayed, in progress, failed or conflicting.
//
// Persistence is deliberately small: one record per project, 24 h lifetime, at
// most MAX_RECORDS records overall, and never a CSRF token, cookie or any
// financial value.

const PREFIX = "finco.run-intent.v1:";
const TTL_MS = 24 * 60 * 60 * 1000;
const MAX_RECORDS = 20;
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const HASH = /^[0-9a-f]{64}$/;

export interface RunIntent {
  id: string;
  /** The ORIGINAL submitted binding — a retry never adopts today's draft hash. */
  contentHash: string;
  workbookVersion: string;
  createdAt: number;
}

const memory = new Map<string, string>();

function store(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

function read(key: string): string | null {
  const s = store();
  try {
    if (s) return s.getItem(key);
  } catch { /* fall through to memory */ }
  return memory.get(key) ?? null;
}

function write(key: string, value: string): void {
  const s = store();
  try {
    if (s) { s.setItem(key, value); return; }
  } catch { /* quota / blocked storage: keep it in memory for this page life */ }
  memory.set(key, value);
}

function remove(key: string): void {
  try { store()?.removeItem(key); } catch { /* ignore */ }
  memory.delete(key);
}

/** A fresh RFC 4122 version-4 UUID from the platform CSPRNG; never Math.random. */
export function newRunIntentId(): string {
  const c: Crypto | undefined = typeof globalThis !== "undefined" ? globalThis.crypto : undefined;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  if (!c || typeof c.getRandomValues !== "function") throw new Error("SECURE_RANDOM_UNAVAILABLE");
  const b = c.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

function valid(value: unknown, now: number): value is RunIntent {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return typeof v.id === "string" && UUID_V4.test(v.id)
    && typeof v.contentHash === "string" && HASH.test(v.contentHash)
    && typeof v.workbookVersion === "string" && v.workbookVersion.length > 0 && v.workbookVersion.length <= 256
    && typeof v.createdAt === "number" && v.createdAt <= now + 60_000 && now - v.createdAt < TTL_MS;
}

function keys(): string[] {
  const out: string[] = [];
  const s = store();
  try {
    if (s) for (let i = 0; i < s.length; i += 1) { const k = s.key(i); if (k && k.startsWith(PREFIX)) out.push(k); }
  } catch { /* ignore */ }
  for (const k of memory.keys()) if (!out.includes(k)) out.push(k);
  return out;
}

/** Drop expired/corrupt records and keep the newest MAX_RECORDS. */
function prune(now: number): void {
  const live: Array<{ key: string; createdAt: number }> = [];
  for (const key of keys()) {
    try {
      const parsed: unknown = JSON.parse(read(key) ?? "null");
      if (valid(parsed, now)) live.push({ key, createdAt: parsed.createdAt }); else remove(key);
    } catch { remove(key); }
  }
  live.sort((a, b) => b.createdAt - a.createdAt).slice(MAX_RECORDS).forEach((r) => remove(r.key));
}

export function loadRunIntent(project: string, now: number = Date.now()): RunIntent | null {
  const key = PREFIX + project;
  try {
    const parsed: unknown = JSON.parse(read(key) ?? "null");
    if (valid(parsed, now)) return parsed;
  } catch { /* corrupt */ }
  remove(key);
  return null;
}

/** Create and persist the intent for ONE deliberate Run. */
export function createRunIntent(project: string, contentHash: string, workbookVersion: string,
                                now: number = Date.now()): RunIntent {
  const intent: RunIntent = { id: newRunIntentId(), contentHash, workbookVersion, createdAt: now };
  prune(now);
  write(PREFIX + project, JSON.stringify(intent));
  return intent;
}

export function clearRunIntent(project: string): void {
  remove(PREFIX + project);
}
