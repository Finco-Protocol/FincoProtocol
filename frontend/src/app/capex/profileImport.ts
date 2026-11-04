// PR-U2a (owner D14) — monthly percentages for the EXPLICIT spending-profile shape: parsing a pasted row / column and an exact check.
//
// Text handling and a hint only. The canonical contract (app/capex_profiles/contract.py `build_weights`) stays the authority: exactly N finite,
// non-negative values whose total is 100 % within 1e-9 of the whole (1e-7 percentage points). Nothing here rounds, rescales or normalises a value:
// the user's digits are kept as typed (only a decimal comma becomes a point). Ambiguous text is never guessed — the caller must ask the user.

export type CommaMode = "decimal" | "separator";
export type ParseResult =
  | { status: "ok"; values: string[] }
  | { status: "ambiguous"; reason: string }
  | { status: "error"; message: string };

const NUMBER = /^\d+(?:\.\d+)?$/;
const DECIMAL_COMMA = /^\d+,\d+$/;

function cleanCell(raw: string): string {
  return raw.trim().replace(/\s*%$/, "").trim();
}

/** Split pasted text into cells.
 *  - Tab, newline or semicolon present (an Excel row / column, a CSV with ";"): those separate the cells, and a comma inside a cell is a DECIMAL comma.
 *  - Otherwise "a, b, c" (comma + space) is a list; several whitespace-separated numbers are cells (a comma inside is then a decimal comma).
 *  - One token with a point and commas ("12.5,87.5") is a comma list.
 *  - One token with commas and no point ("12,5" or "10,20,70") is AMBIGUOUS unless `commaMode` says how to read the comma. */
export function parsePercentages(text: string, commaMode?: CommaMode): ParseResult {
  const t = text.replace(/^﻿/, "").trim();
  if (!t) return { status: "ok", values: [] };
  let cells: string[];
  let commaIsDecimal: boolean;
  if (/[\t\r\n;]/.test(t)) {
    cells = t.split(/[\t\r\n;]+/);
    commaIsDecimal = true;
  } else if (/,\s/.test(t)) {
    cells = t.split(/,\s*/);
    commaIsDecimal = false;
  } else {
    const tokens = t.split(/\s+/).filter(Boolean);
    if (tokens.length > 1) {
      cells = tokens;
      commaIsDecimal = true;
    } else if (!t.includes(",")) {
      cells = [t];
      commaIsDecimal = false;
    } else if (t.includes(".")) {
      cells = t.split(",");
      commaIsDecimal = false;
    } else if (commaMode === "decimal") {
      cells = [t];
      commaIsDecimal = true;
    } else if (commaMode === "separator") {
      cells = t.split(",");
      commaIsDecimal = false;
    } else {
      return { status: "ambiguous", reason: `"${t.length > 40 ? t.slice(0, 40) + "…" : t}" — is the comma a decimal separator or does it separate months?` };
    }
  }
  const values: string[] = [];
  for (const [i, raw] of cells.entries()) {
    const cell = cleanCell(raw);
    if (!cell) continue;
    const normalised = commaIsDecimal && DECIMAL_COMMA.test(cell) ? cell.replace(",", ".") : cell;
    if (/^-/.test(normalised)) return { status: "error", message: `Month ${values.length + 1}: "${cell}" is negative; percentages must be 0 or more.` };
    if (!NUMBER.test(normalised)) return { status: "error", message: `Month ${values.length + 1}: "${cell}" is not a number (entry ${i + 1}).` };
    values.push(normalised);
  }
  return { status: "ok", values };
}

/** One number typed into a single month box: a comma there can only be a decimal comma. Returns the normalised text, or null if not a number ≥ 0. */
export function parseOneMonth(text: string): string | null {
  const cell = cleanCell(text);
  const normalised = DECIMAL_COMMA.test(cell) ? cell.replace(",", ".") : cell;
  return NUMBER.test(normalised) ? normalised : null;
}

// Exact decimal arithmetic on the typed digits (scaled BigInt); no floating point ever touches a percentage here.
function scale(values: readonly string[]): number {
  return values.reduce((m, v) => Math.max(m, (v.split(".")[1] ?? "").length), 0);
}
function toUnits(v: string, s: number): bigint {
  const [i, f = ""] = v.split(".");
  return BigInt(i) * 10n ** BigInt(s) + BigInt((f + "0".repeat(s)).slice(0, s) || "0");
}
function fromUnits(u: bigint, s: number): string {
  const neg = u < 0n; const a = neg ? -u : u; const base = 10n ** BigInt(s);
  const i = a / base; const f = (a % base).toString().padStart(s, "0").replace(/0+$/, "");
  return (neg ? "-" : "") + i.toString() + (f ? "." + f : "");
}

export interface ExplicitCheck {
  ok: boolean;
  count: number;
  months: number;
  total: string;          // exact decimal text of the sum
  difference: string;     // exact 100 − total ("0" when exact)
  problems: string[];
}

/** The contract check, exactly: count == months, every value a non-negative decimal, |total − 100| ≤ 1e-7 (1e-9 of the whole). */
export function checkExplicit(values: readonly string[], months: number): ExplicitCheck {
  const problems: string[] = [];
  const bad = values.findIndex((v) => !NUMBER.test(v));
  if (bad >= 0) problems.push(`Month ${bad + 1}: "${values[bad]}" is not a non-negative number.`);
  if (values.length !== months) problems.push(`${values.length} value${values.length === 1 ? "" : "s"} for ${months} construction month${months === 1 ? "" : "s"} — exactly ${months} needed.`);
  if (bad >= 0) return { ok: false, count: values.length, months, total: "—", difference: "—", problems };
  const s = Math.max(scale(values), 7);
  const total = values.reduce((acc, v) => acc + toUnits(v, s), 0n);
  const diff = toUnits("100", s) - total;
  const tolerance = 10n ** BigInt(s - 7);                     // 1e-7 percentage points
  const within = (diff < 0n ? -diff : diff) <= tolerance;
  if (!within) problems.push(`The months add up to ${fromUnits(total, s)} % — ${diff > 0n ? "missing " + fromUnits(diff, s) : "over by " + fromUnits(-diff, s)} %. The total must be exactly 100 %.`);
  return { ok: problems.length === 0, count: values.length, months, total: fromUnits(total, s), difference: fromUnits(diff, s), problems };
}

export type StaleKind = "none" | "too_few" | "too_many" | "milestone_out_of_range";

/** A saved / drafted row that no longer fits the current construction length (the duration changed after it was entered). */
export function staleness(shape: string, explicit: string, milestone: string, months: number): StaleKind {
  if (shape === "EXPLICIT" && explicit.trim()) {
    const n = explicit.split(",").length;
    if (n < months) return "too_few";
    if (n > months) return "too_many";
  }
  if (shape === "MILESTONE" && /^\d+$/.test(milestone) && Number(milestone) > months) return "milestone_out_of_range";
  return "none";
}

/** Explicit, user-triggered corrections (never applied automatically). Each returns the new comma list, or null when it cannot be applied safely. */
export function padWithZeros(explicit: string, months: number): string | null {
  const values = explicit.split(",");
  return values.length < months ? [...values, ...Array(months - values.length).fill("0")].join(",") : null;
}
export function trimTrailingZeros(explicit: string, months: number): string | null {
  const values = explicit.split(",");
  if (values.length <= months) return null;
  const tail = values.slice(months);
  return tail.every((v) => NUMBER.test(v) && /^0+(?:\.0+)?$/.test(v)) ? values.slice(0, months).join(",") : null;
}
