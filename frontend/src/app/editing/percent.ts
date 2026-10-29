// WS-2 / M-013 — human percent <-> canonical ratio for the basic PPA form.
//
// The canonical contract stores `volume_share` and `indexation_rate` as RATIOS in 0..1
// (0.02 = 2%).  The basic form shows and accepts human percent 0..100 ("2" = 2%).  The
// conversion is an exact decimal shift of two places on the string, applied exactly once
// at the editor boundary: `toCanonical` on the way into the draft, `toDisplay` on the
// way out.  A value that is already canonical is never passed through `toCanonical` again
// (the helpers are typed by unit through `UiPercent` / `CanonicalRatio` so the compiler
// rejects a double conversion).

import { compareMagnitude, formatDecimal, parseDecimal, shift, type DecimalSeparator } from "./decimal";

declare const uiPercentBrand: unique symbol;
declare const canonicalRatioBrand: unique symbol;
/** Text exactly as shown in the percent input ("2", "12.5"). */
export type UiPercent = string & { readonly [uiPercentBrand]: true };
/** Canonical contract text ("0.02", "1"). */
export type CanonicalRatio = string & { readonly [canonicalRatioBrand]: true };

export type PercentResult =
  | { ok: true; canonical: CanonicalRatio; display: UiPercent }
  | { ok: false; code: "EMPTY" | "NOT_A_NUMBER" | "AMBIGUOUS_SEPARATOR" | "NEGATIVE" | "ABOVE_100"; message: string };

const MESSAGES = {
  EMPTY: "Enter a percentage between 0 and 100.",
  NOT_A_NUMBER: "Enter a number such as 2 or 2.5 (no % sign needed).",
  AMBIGUOUS_SEPARATOR: "The decimal separator is ambiguous; use a single decimal point, for example 2.5.",
  NEGATIVE: "A percentage cannot be negative.",
  ABOVE_100: "A percentage cannot exceed 100.",
} as const;

const fail = (code: keyof typeof MESSAGES): PercentResult => ({ ok: false, code, message: MESSAGES[code] });

/** Typed human percent (0..100, optional trailing `%`) -> canonical ratio text, exact. */
export function toCanonical(typed: string, separator: DecimalSeparator = "auto"): PercentResult {
  const parsed = parseDecimal(typed.replace(/%\s*$/, ""), separator);
  if (!parsed.ok) {
    return fail(parsed.reason === "empty" ? "EMPTY" : parsed.reason === "ambiguous" ? "AMBIGUOUS_SEPARATOR" : "NOT_A_NUMBER");
  }
  const zero = /^0*$/.test(parsed.integer) && /^0*$/.test(parsed.fraction);
  if (parsed.negative && !zero) return fail("NEGATIVE");
  if (compareMagnitude(parsed, { integer: "100", fraction: "" }) > 0) return fail("ABOVE_100");
  const ratio = shift(parsed.integer, parsed.fraction, -2);
  return {
    ok: true,
    canonical: formatDecimal({ negative: false, ...ratio }) as CanonicalRatio,
    display: formatDecimal({ negative: false, integer: parsed.integer, fraction: parsed.fraction }) as UiPercent,
  };
}

/** Canonical ratio text (0..1, may carry an exponent) -> human percent text, exact.  `null` when not a valid 0..1 ratio. */
export function toDisplay(canonical: string): UiPercent | null {
  const parsed = parseDecimal(canonical, ".");
  if (!parsed.ok || parsed.negative) return null;
  if (compareMagnitude(parsed, { integer: "1", fraction: "" }) > 0) return null;
  const percent = shift(parsed.integer, parsed.fraction, 2);
  return formatDecimal({ negative: false, ...percent }) as UiPercent;
}

/** Whether two ratio texts are the same number (`"0.020"` equals `"0.02"`). */
export function sameRatio(a: string, b: string): boolean {
  const pa = parseDecimal(a, "."), pb = parseDecimal(b, ".");
  return pa.ok && pb.ok && formatDecimal(pa) === formatDecimal(pb);
}
