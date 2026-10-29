// WS-2 — exact decimal-string helpers for editor input.
//
// Presentation only.  Nothing here derives a financial result: values are re-expressed
// by an exact decimal shift on the STRING (no binary floating point), so `2` percent is
// always the canonical `0.02` and back, and a paste of `0.1 + 0.2`-like input can never
// pick up a rounding artefact.  Validation of the economic meaning stays server-side.

export type DecimalParse =
  | { ok: true; negative: boolean; integer: string; fraction: string }
  | { ok: false; reason: "empty" | "format" | "ambiguous" };

export type DecimalSeparator = "auto" | "." | ",";

/**
 * Parses a typed or pasted number.
 *
 * - `auto`: when both `.` and `,` occur the LAST one is the decimal mark and the other is
 *   grouping; a single separator is the decimal mark when it occurs once, and an
 *   ambiguous repeated one (`1,234,567`) is grouping only if every group has 3 digits.
 * - `"."` / `","`: that character is the decimal mark, the other is grouping.
 * Spaces and thin/no-break spaces are grouping.  Exponents (`1e-3`) are expanded exactly.
 */
export function parseDecimal(text: string, separator: DecimalSeparator = "auto"): DecimalParse {
  let body = text.replace(/[\s  ]/g, "");
  if (body === "") return { ok: false, reason: "empty" };
  let negative = false;
  if (body.startsWith("-") || body.startsWith("−")) { negative = true; body = body.slice(1); }
  else if (body.startsWith("+")) body = body.slice(1);

  let exponent = 0;
  const exp = /[eE]([+-]?\d+)$/.exec(body);
  if (exp) {
    exponent = Number(exp[1]);
    if (!Number.isSafeInteger(exponent) || Math.abs(exponent) > 40) return { ok: false, reason: "format" };
    body = body.slice(0, exp.index);
  }
  if (!/^[\d.,]+$/.test(body)) return { ok: false, reason: "format" };

  const dots = (body.match(/\./g) ?? []).length;
  const commas = (body.match(/,/g) ?? []).length;
  let decimalMark: "." | "," | "";
  if (separator === "." || separator === ",") {
    decimalMark = separator;
  } else if (dots && commas) {
    decimalMark = body.lastIndexOf(".") > body.lastIndexOf(",") ? "." : ",";
  } else if (dots + commas === 0) {
    decimalMark = "";
  } else {
    const mark = (dots ? "." : ",") as "." | ",";
    const count = dots || commas;
    if (count === 1) decimalMark = mark;
    else {
      const groups = body.split(mark);
      const grouping = groups.slice(1).every((g) => g.length === 3) && groups[0].length >= 1 && groups[0].length <= 3;
      if (!grouping) return { ok: false, reason: "ambiguous" };
      decimalMark = "";
    }
  }
  const grouping = decimalMark === "." ? "," : decimalMark === "," ? "." : (dots ? "." : ",");
  let integer = body, fraction = "";
  const at = decimalMark ? body.lastIndexOf(decimalMark) : -1;
  if (at >= 0) {
    integer = body.slice(0, at);
    fraction = body.slice(at + 1);
    if (fraction.includes(decimalMark)) return { ok: false, reason: "ambiguous" };
  }
  integer = integer.split(grouping).join("");
  fraction = fraction.split(grouping).join("");
  if (decimalMark && (integer.includes(decimalMark) || fraction.includes(decimalMark))) return { ok: false, reason: "ambiguous" };
  if (!/^\d*$/.test(integer) || !/^\d*$/.test(fraction)) return { ok: false, reason: "format" };
  if (integer === "" && fraction === "") return { ok: false, reason: "format" };
  const shifted = shift(integer || "0", fraction, exponent);
  return { ok: true, negative, ...shifted };
}

/** Moves the decimal point `places` to the right (negative = left), exactly. */
export function shift(integer: string, fraction: string, places: number): { integer: string; fraction: string } {
  let digits = integer + fraction;
  let point = integer.length + places;
  if (point < 0) { digits = "0".repeat(-point) + digits; point = 0; }
  if (point > digits.length) digits += "0".repeat(point - digits.length);
  return { integer: digits.slice(0, point) || "0", fraction: digits.slice(point) };
}

/** Canonical plain-decimal text: no grouping, no leading/trailing zeros, no exponent, `-0` is `0`. */
export function formatDecimal(value: { negative: boolean; integer: string; fraction: string }): string {
  const integer = value.integer.replace(/^0+(?=\d)/, "") || "0";
  const fraction = value.fraction.replace(/0+$/, "");
  const zero = /^0*$/.test(integer) && fraction === "";
  const body = fraction ? `${integer}.${fraction}` : integer;
  return value.negative && !zero ? `-${body}` : body;
}

/** `-1 / 0 / 1` comparison of two parsed non-negative magnitudes (sign ignored). */
export function compareMagnitude(a: { integer: string; fraction: string }, b: { integer: string; fraction: string }): number {
  const ai = a.integer.replace(/^0+(?=\d)/, ""), bi = b.integer.replace(/^0+(?=\d)/, "");
  if (ai.length !== bi.length) return ai.length < bi.length ? -1 : 1;
  if (ai !== bi) return ai < bi ? -1 : 1;
  const len = Math.max(a.fraction.length, b.fraction.length);
  const af = a.fraction.padEnd(len, "0"), bf = b.fraction.padEnd(len, "0");
  return af === bf ? 0 : af < bf ? -1 : 1;
}

/** Exact sum of plain-decimal texts (display-only arithmetic on what the user typed; never a model result).  `null` if any term is not a number. */
export function sumDecimals(texts: readonly string[]): string | null {
  let scale = 0;
  const terms: Array<{ negative: boolean; digits: string; scale: number }> = [];
  for (const text of texts) {
    const parsed = parseDecimal(text, ".");
    if (!parsed.ok) return null;
    const fraction = parsed.fraction.replace(/0+$/, "");
    scale = Math.max(scale, fraction.length);
    terms.push({ negative: parsed.negative, digits: parsed.integer + fraction, scale: fraction.length });
  }
  let total = 0n;
  for (const term of terms) {
    const value = BigInt(term.digits || "0") * 10n ** BigInt(scale - term.scale);
    total += term.negative ? -value : value;
  }
  const negative = total < 0n;
  const digits = (negative ? -total : total).toString().padStart(scale + 1, "0");
  const integer = digits.slice(0, digits.length - scale) || "0";
  return formatDecimal({ negative, integer, fraction: digits.slice(digits.length - scale) });
}
