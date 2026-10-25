// Presentation-only unit conversion and number formatting for canonical
// server-formatted display text.  NOTHING here derives a financial result:
// every function either re-expresses an authoritative value in another display
// unit (a pure power-of-ten decimal shift, done on the decimal STRING so no
// binary floating-point rounding can leak into the display) or classifies how
// a row must be rendered.  Absent / non-numeric text stays unavailable.

export type DisplayUnit = "EUR" | "kEUR" | "mEUR";

/** Decimal exponent of each display unit relative to EUR (value_in_EUR = n * 10^exp). */
const UNIT_EXPONENT: Record<DisplayUnit, number> = { EUR: 0, kEUR: 3, mEUR: 6 };

export const DISPLAY_UNITS: readonly DisplayUnit[] = ["EUR", "kEUR", "mEUR"];

export type RowFormat =
  | { kind: "money"; base: DisplayUnit }
  | { kind: "ratio" }
  | { kind: "percent" }
  /** No canonical unit metadata and no safe inference: shown verbatim, never converted. */
  | { kind: "unspecified" };

/** How a row's format was established (evidence for the residual label-inference limitation). */
export type UnitSource = "canonical-row-unit" | "sheet-unit" | "label-inference" | "unspecified";

/** Maps canonical unit metadata ("keur", "EUR", "m_eur", "x", "pct", "%") to a format. */
export function formatFromCanonicalUnit(raw: string | null | undefined): RowFormat | null {
  const unit = (raw ?? "").trim().toLowerCase().replace(/[\s_-]/g, "");
  if (!unit) return null;
  if (unit === "keur" || unit === "k€" || unit === "teur") return { kind: "money", base: "kEUR" };
  if (unit === "eur" || unit === "€") return { kind: "money", base: "EUR" };
  if (unit === "meur" || unit === "m€" || unit === "mneur") return { kind: "money", base: "mEUR" };
  if (unit === "x" || unit === "ratio" || unit === "multiple") return { kind: "ratio" };
  if (unit === "%" || unit === "pct" || unit === "percent") return { kind: "percent" };
  return null;
}

const RATIO_LABEL = /\(\s*x\s*\)\s*$|\b(dscr|llcr|plcr|icr|moic|tvpi|dpi|coverage ratio|cover ratio|multiple)\b/i;
const PERCENT_LABEL = /\(\s*%\s*\)\s*$|%\s*$|\b(irr|xirr|yield|margin|gearing|rate)\b/i;

/**
 * Decides how one row is rendered.  Explicit canonical unit metadata (row unit,
 * then sheet unit) wins; the label heuristic is only a fallback for projections
 * that do not yet carry per-row units (word-boundary matches only, so "Tax" or
 * "Net Tax" is never mistaken for a "x" ratio).
 */
export function resolveRowFormat(label: string, rowUnit?: string | null, sheetUnit?: string | null): RowFormat {
  return classifyRowUnit(label, rowUnit, sheetUnit).format;
}

/** Same decision as `resolveRowFormat`, with the basis it was made on. */
export function classifyRowUnit(label: string, rowUnit?: string | null, sheetUnit?: string | null): { format: RowFormat; source: UnitSource } {
  const fromRow = formatFromCanonicalUnit(rowUnit);
  if (fromRow) return { format: fromRow, source: "canonical-row-unit" };
  if (RATIO_LABEL.test(label)) return { format: { kind: "ratio" }, source: "label-inference" };
  if (PERCENT_LABEL.test(label)) return { format: { kind: "percent" }, source: "label-inference" };
  const fromSheet = formatFromCanonicalUnit(sheetUnit);
  if (fromSheet) return { format: fromSheet, source: "sheet-unit" };
  return { format: { kind: "unspecified" }, source: "unspecified" };
}

export type ParsedValue =
  | { kind: "number"; negative: boolean; integer: string; fraction: string }
  | { kind: "unavailable" }
  | { kind: "status"; text: string };

const STATUS_TEXT = /^(not evaluated|not tested|not available|unavailable|not applicable|n\/a)$/i;

/** Parses a canonical display string ("1,232.50", "(1,232.50)", "-3.1", "12.5%", "1.25x"). */
export function parseDisplayNumber(text: string | null | undefined): ParsedValue {
  const trimmed = (text ?? "").trim();
  if (!trimmed || /^(—|–|-|na)$/i.test(trimmed)) return { kind: "unavailable" };
  if (STATUS_TEXT.test(trimmed)) return { kind: "status", text: trimmed.toUpperCase() };
  let body = trimmed.replace(/[%x]$/i, "").replace(/\s*(kEUR|mEUR|EUR|€)$/i, "").trim();
  let negative = false;
  if (/^\(.*\)$/.test(body)) { negative = true; body = body.slice(1, -1).trim(); }
  if (body.startsWith("-") || body.startsWith("−")) { negative = !negative; body = body.slice(1).trim(); }
  body = body.replace(/,/g, "");
  if (!/^\d+(\.\d+)?$|^\.\d+$/.test(body)) return { kind: "status", text: trimmed };
  const [integer = "0", fraction = ""] = body.split(".");
  return { kind: "number", negative, integer: integer || "0", fraction };
}

/** Exact decimal shift: moves the decimal point `places` to the right (negative = left). */
function shiftDecimal(integer: string, fraction: string, places: number): { integer: string; fraction: string } {
  let digits = integer + fraction;
  let point = integer.length + places;
  if (point < 0) { digits = "0".repeat(-point) + digits; point = 0; }
  if (point > digits.length) digits += "0".repeat(point - digits.length);
  return { integer: digits.slice(0, point) || "0", fraction: digits.slice(point) };
}

/** Round half away from zero on the decimal string (matches conventional statement rounding). */
function roundDecimal(integer: string, fraction: string, precision: number): { integer: string; fraction: string } {
  if (fraction.length <= precision) return { integer, fraction: fraction.padEnd(precision, "0") };
  const kept = fraction.slice(0, precision);
  const roundUp = fraction.charCodeAt(precision) >= 53; // '5'
  if (!roundUp) return { integer, fraction: kept };
  const all = (integer + kept).split("").map(Number);
  let i = all.length - 1;
  while (i >= 0) {
    if (all[i] === 9) { all[i] = 0; i -= 1; } else { all[i] += 1; break; }
  }
  if (i < 0) all.unshift(1);
  const joined = all.join("");
  const intLen = joined.length - precision;
  return { integer: joined.slice(0, intLen), fraction: joined.slice(intLen) };
}

function group(integer: string): string {
  const stripped = integer.replace(/^0+(?=\d)/, "");
  return stripped.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

export const UNAVAILABLE_TEXT = "—";

/**
 * Re-expresses a canonical money text (in `base`) in the chosen display unit
 * with the chosen precision.  Negative money renders in parentheses; a value
 * that rounds to zero renders as plain zero.
 */
export function formatMoneyText(text: string | null | undefined, base: DisplayUnit, display: DisplayUnit, precision: number): string {
  const parsed = parseDisplayNumber(text);
  if (parsed.kind === "unavailable") return UNAVAILABLE_TEXT;
  if (parsed.kind === "status") return parsed.text;
  const shifted = shiftDecimal(parsed.integer, parsed.fraction, UNIT_EXPONENT[base] - UNIT_EXPONENT[display]);
  const rounded = roundDecimal(shifted.integer, shifted.fraction, precision);
  const body = precision > 0 ? `${group(rounded.integer)}.${rounded.fraction}` : group(rounded.integer);
  const isZero = /^[0.,]*$/.test(body);
  return parsed.negative && !isZero ? `(${body})` : body;
}

const MONETARY_METRIC = /^(.*?)\s*(kEUR|mEUR|EUR)$/;

/**
 * Key-metric display text -> chosen unit and precision.  A metric is monetary ONLY
 * when its canonical text carries an explicit EUR/kEUR/mEUR unit suffix; it is then
 * ALWAYS re-expressed through the exact-decimal authority (even when the selected
 * unit equals the canonical unit, so the selected precision always applies).
 * IRR, XIRR, MOIC, DSCR, percentages and any text without a currency suffix, and
 * non-numeric text, are returned verbatim.  The canonical source string is never
 * modified (callers keep it separately).
 */
export function formatMetricDisplay(display: string, unit: DisplayUnit, precision: number): string {
  const money = MONETARY_METRIC.exec(display.trim());
  if (!money) return display;
  const base = money[2] as DisplayUnit;
  if (parseDisplayNumber(money[1]).kind !== "number") return display;
  return `${formatMoneyText(money[1], base, unit, precision)} ${unit}`;
}

/** Ratios and percentages keep the canonical precision; only the suffix and sign convention are applied. */
export function formatRatioText(text: string | null | undefined, kind: "ratio" | "percent"): string {
  const parsed = parseDisplayNumber(text);
  if (parsed.kind === "unavailable") return UNAVAILABLE_TEXT;
  if (parsed.kind === "status") return parsed.text;
  const body = `${group(parsed.integer)}${parsed.fraction ? `.${parsed.fraction}` : ""}`;
  const isZero = /^[0.,]*$/.test(body);
  return `${parsed.negative && !isZero ? "-" : ""}${body}${kind === "ratio" ? "x" : "%"}`;
}

/** One entry point for table cells. */
export function formatStatementCell(
  text: string | null | undefined,
  format: RowFormat,
  display: DisplayUnit,
  precision: number,
): string {
  if (format.kind === "unspecified") return (text ?? "").trim() ? String(text).trim() : UNAVAILABLE_TEXT;
  return format.kind === "money"
    ? formatMoneyText(text, format.base, display, precision)
    : formatRatioText(text, format.kind);
}

/** Unit label shown next to a row/column header (never claims a unit for ratios). */
export function formatUnitLabel(format: RowFormat, display: DisplayUnit): string {
  return format.kind === "money" ? display : format.kind === "ratio" ? "x" : format.kind === "percent" ? "%" : "unit unavailable";
}

/** Canonical sheet unit ("keur") as a display label ("kEUR"). */
export function sheetUnitLabel(raw: string | null | undefined): string {
  const format = formatFromCanonicalUnit(raw);
  if (!format) return raw ? String(raw) : "unit unavailable";
  return format.kind === "money" ? format.base : format.kind === "ratio" ? "x" : "%";
}

/**
 * Chart geometry input: the authoritative displayed number as a JS number.  Used
 * ONLY to position marks; labels/tooltips always show the canonical text.
 */
export function plotValue(text: string | null | undefined): number | null {
  const parsed = parseDisplayNumber(text);
  if (parsed.kind !== "number") return null;
  const n = Number(`${parsed.integer}.${parsed.fraction || "0"}`);
  return Number.isFinite(n) ? (parsed.negative ? -n : n) : null;
}
