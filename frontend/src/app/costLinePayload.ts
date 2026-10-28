// CAPEX/OPEX staged-line payload — presentation-only wire serialization.
//
// The canonical writer (`POST /v2/workbook/grid/cost-lines/save`, `CostLinePayload` in
// app/v2/grid_router.py) takes `amount_keur` and `inflation_pct` as decimal STRINGS and the server
// stays the only validator.  The browser therefore sends the exact text the user typed (trimmed),
// never a JSON number: a number would be refused as malformed and `Number()` would also re-round
// the user's decimal.  Early validation here only spares a round trip; it never replaces the
// server rules.

import { parseStrictDecimal } from "./workflow/ModelWorkflowValidation";

export type CostSheet = "capex" | "opex";

export interface StagedCostPatch { label?: string; amount_keur?: string; inflation_pct?: string; notes?: string }

export interface StoredCostLine {
  sub_line_id: string;
  label: string;
  amount_keur: number | string | null;
  inflation_pct?: number | string | null;
  notes?: string | null;
  row_version?: string | null;
}

export interface CostLineEditWire {
  kind: CostSheet;
  sub_line_id: string;
  label: string;
  amount_keur: string;
  row_version: string;
  inflation_pct?: string;
  notes: string;
}

export type BuildCostEdits =
  | { ok: true; edits: CostLineEditWire[] }
  | { ok: false; message: string; subLineId: string };

const storedText = (value: number | string | null | undefined, fallback: string): string =>
  value === null || value === undefined || value === "" ? fallback : String(value);

/** Wire edits for every staged line; the first invalid typed number stops the whole batch (all or none). */
export function buildCostLineEdits(
  sheet: CostSheet, staged: Record<string, StagedCostPatch>, lines: readonly StoredCostLine[],
): BuildCostEdits {
  const edits: CostLineEditWire[] = [];
  for (const [subLineId, patch] of Object.entries(staged)) {
    const line = lines.find((l) => l.sub_line_id === subLineId);
    const label = line?.label ?? subLineId;
    const amountText = patch.amount_keur !== undefined ? patch.amount_keur.trim() : storedText(line?.amount_keur, "0");
    const amount = parseStrictDecimal(amountText);
    if (!amount.ok) return { ok: false, subLineId, message: `${label}: amount — ${amount.message} Nothing was saved.` };
    const edit: CostLineEditWire = {
      kind: sheet,
      sub_line_id: subLineId,
      label: patch.label ?? line?.label ?? "",
      amount_keur: amountText,
      row_version: line?.row_version ?? "",
      notes: patch.notes ?? line?.notes ?? "",
    };
    if (sheet === "opex" && patch.inflation_pct !== undefined) {
      const inflationText = patch.inflation_pct.trim();
      // Blank means "keep the stored escalation": the key is omitted, the server keeps the stored value.
      if (inflationText !== "") {
        const inflation = parseStrictDecimal(inflationText);
        if (!inflation.ok) return { ok: false, subLineId, message: `${label}: inflation — ${inflation.message} Nothing was saved.` };
        edit.inflation_pct = inflationText;
      }
    }
    edits.push(edit);
  }
  return { ok: true, edits };
}

/** Plain-decimal text equality: "1600" and "1600.0" are the same persisted number. */
export const sameDecimalText = (a: string | number | null | undefined, b: string | number | null | undefined): boolean => {
  const x = String(a ?? "").trim(); const y = String(b ?? "").trim();
  if (x === y) return true;
  if (x === "" || y === "") return false;
  const nx = Number(x); const ny = Number(y);
  return Number.isFinite(nx) && Number.isFinite(ny) && nx === ny;
};

export type BatchVerdict = "committed" | "not_committed" | "changed_elsewhere";

/** What the canonical lines say about a batch whose response was lost.  The writer is all-or-none and bound to each
 *  line's `row_version`: every line still at its old row_version = nothing was written; every line equal to the sent
 *  values = committed; anything else = another change landed in between.  Pure: it never sends anything. */
export function classifyBatchAttempt(edits: readonly CostLineEditWire[], fresh: readonly StoredCostLine[]): BatchVerdict {
  let committed = 0; let untouched = 0;
  for (const edit of edits) {
    const line = fresh.find((l) => l.sub_line_id === edit.sub_line_id);
    if (!line) return "changed_elsewhere";
    if ((line.row_version ?? "") === edit.row_version) { untouched += 1; continue; }
    const same = line.label === edit.label && sameDecimalText(line.amount_keur, edit.amount_keur)
      && (edit.inflation_pct === undefined || sameDecimalText(line.inflation_pct, edit.inflation_pct))
      && (line.notes ?? "") === edit.notes;
    if (same) committed += 1; else return "changed_elsewhere";
  }
  if (committed === edits.length) return "committed";
  if (untouched === edits.length) return "not_committed";
  return "changed_elsewhere";
}
