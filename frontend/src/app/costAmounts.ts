// WF-06B — cost amounts: one stored amount (kEUR) per line, read-only per-MW figures and one display convention.
//
// * The stored amount is ``amount_keur`` and travels as exact decimal text everywhere it is edited, staged, compared or saved.
// * Display precision is NOT computational precision: a figure shown with 0 decimals never replaces the text behind it.
// * "Per MW" is a read-only division of the amount by the saved installed capacity the SERVER names. It is never saved and never
//   reaches the Run. The server sends the saved per-MW text; the only division done here is the clearly labelled unsaved preview.
import { DISPLAY_UNITS, formatMoneyText, type DisplayUnit } from "./units";

export { DISPLAY_UNITS };
export type { DisplayUnit };

const PLAIN = /^-?\d+(\.\d+)?$/;

/** Exact decimal quotient ``amount / divisor`` as plain text with ``scale`` decimals (round half away from zero); null if not computable. */
export function divideDecimalText(amount: string | null | undefined, divisor: string | null | undefined, scale = 6): string | null {
  const a = (amount ?? "").trim().replace(/,/g, "");
  const d = (divisor ?? "").trim().replace(/,/g, "");
  if (!PLAIN.test(a) || !PLAIN.test(d)) return null;
  const decimals = (t: string) => (t.split(".")[1] ?? "").length;
  const big = (t: string) => BigInt(t.replace(".", "").replace(/^-/, "")) * (t.startsWith("-") ? -1n : 1n);
  const num = big(a), den = big(d);
  if (den <= 0n) return null;
  // amount = num / 10^da, divisor = den / 10^dd  =>  quotient * 10^scale = num * 10^(dd + scale) / (den * 10^da)
  const numerator = num * 10n ** BigInt(decimals(d) + scale);
  const denominator = den * 10n ** BigInt(decimals(a));
  const negative = numerator < 0n;
  const n = negative ? -numerator : numerator;
  let q = n / denominator;
  if ((n % denominator) * 2n >= denominator) q += 1n;
  const digits = q.toString().padStart(scale + 1, "0");
  const whole = digits.slice(0, digits.length - scale);
  const fraction = digits.slice(digits.length - scale).replace(/0+$/, "");
  const text = fraction ? `${whole}.${fraction}` : whole;
  return negative && /[1-9]/.test(text) ? `-${text}` : text;
}

/** An amount stored in kEUR, shown in the chosen unit with the chosen number of decimals ("—" when there is no number). */
export function showKeur(amountKeur: string | number | null | undefined, unit: DisplayUnit, precision: number): string {
  if (amountKeur === null || amountKeur === undefined || amountKeur === "") return "—";
  return formatMoneyText(String(amountKeur), "kEUR", unit, precision);
}

export const UNIT_LABEL: Record<DisplayUnit, string> = { EUR: "EUR", kEUR: "kEUR", mEUR: "mEUR" };

/** Column / total labels follow the chosen unit. */
export const perMwLabel = (unit: DisplayUnit, perYear: boolean) => `${UNIT_LABEL[unit]}/MW${perYear ? "/yr" : ""}`;
