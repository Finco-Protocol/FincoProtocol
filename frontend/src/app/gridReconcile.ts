// Reconciliation of a staged-cell Save whose response was lost (or that met a CAS conflict) — PURE, presentation-only.
// It compares what the browser attempted with a fresh canonical read; it never sends, retries or rewrites anything.

/** Plain-decimal text equality: "22" and "22.0" are the same persisted number; anything else compares as text. */
export function sameCellValue(a: string | null | undefined, b: string | null | undefined): boolean {
  const x = (a ?? "").trim(); const y = (b ?? "").trim();
  if (x === y) return true;
  if (x === "" || y === "") return false;
  const nx = Number(x); const ny = Number(y);
  return Number.isFinite(nx) && Number.isFinite(ny) && nx === ny;
}

export type ReconcileVerdict = "committed" | "not_committed" | "changed_elsewhere";

/** What the canonical server state says about a Save whose response was lost (or that hit a CAS conflict).
 *  Same composite hash as before the Save = the server never changed (not committed).  Every attempted cell equal
 *  to its staged value = committed.  Anything else = another change landed in between. */
export function classifyAttempt(
  attempt: { cells: Array<{ field_id: string; value: string }>; baselineHash: string },
  fresh: { save: { content_hash: string }; rows: Array<{ field_id: string; value: string }> },
): ReconcileVerdict {
  if (fresh.save.content_hash === attempt.baselineHash) return "not_committed";
  const byId = new Map(fresh.rows.map((r) => [r.field_id, r.value]));
  const all = attempt.cells.every((c) => sameCellValue(byId.get(c.field_id), c.value));
  return all ? "committed" : "changed_elsewhere";
}
