/** Display-only contract for WS1 and WS2. Never use its strings as editor baselines or Save payloads. */
import { decimalFromNumber, formatMoneyValue, formatMoneyText, formatMetricDisplay, formatStatementCell as canonicalCell, parseDisplayNumber, type RowFormat, type DisplayUnit } from "./units";

export const DEFAULT_REPORT_PRECISION = 0;

export function reportAmount(value: number | null | undefined, precision = DEFAULT_REPORT_PRECISION): string {
  return formatMoneyValue(value, "kEUR", "kEUR", precision);
}

/** Dedicated ratios/rates retain canonical digits with a minimum of two decimals. */
export function dedicatedPrecision(text: string, suffix: "x" | "%", numeric?: number | null): string {
  let parsed = parseDisplayNumber(text);
  if (suffix === "x" && typeof numeric === "number" && Number.isFinite(numeric)) {
    const displayed = parsed.kind === "number" ? Number(`${parsed.negative ? "-" : ""}${parsed.integer}.${parsed.fraction}`) : null;
    // Never round a sub-unit coverage breach up to 1x, or a tiny nonzero ratio to zero.
    if (displayed !== null && ((numeric < 1 && numeric > 0 && displayed >= 1) || (numeric !== 0 && displayed === 0))) {
      parsed = parseDisplayNumber(decimalFromNumber(numeric));
    }
  }
  if (parsed.kind !== "number") return text || "—";
  return `${parsed.negative ? "-" : ""}${parsed.integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}.${parsed.fraction.padEnd(2, "0")}${suffix}`;
}

export function reportCell(text: string | null | undefined, format: RowFormat, display: DisplayUnit, precision: number, value?: number | null): string {
  if (value === null) return "—";
  if (format.kind === "ratio") return dedicatedPrecision(text || "—", "x", value);
  if (format.kind === "percent") return dedicatedPrecision(text || "—", "%");
  return canonicalCell(text, format, display, precision, value);
}

export function reportMetric(text: string, unit: DisplayUnit, precision: number): string {
  if (/x\s*$/.test(text)) return dedicatedPrecision(text, "x");
  if (/%\s*$/.test(text)) return dedicatedPrecision(text, "%");
  return formatMetricDisplay(text, unit, precision);
}

export function reportEvidence(value: number | null | undefined, text: string, label: string, precision: number): string {
  if (value == null && parseDisplayNumber(text).kind === "number") return "Unavailable";
  if (/x\s*$/.test(text)) return dedicatedPrecision(text, "x", value);
  if (/%\s*$/.test(text)) return reportMetric(text, "kEUR", precision);
  if (/\b(dscr|llcr|plcr|coverage|moic|multiple)\b/i.test(label)) return dedicatedPrecision(text, "x", value);
  if (/\b(irr|interest|inflation|rate|margin|gearing)\b/i.test(label)) return text;
  const money = /\b(kEUR|mEUR|EUR)\s*$/.exec(text);
  if (money) {
    const unit = money[1] as DisplayUnit;
    return typeof value === "number" ? `${formatMoneyValue(value, unit, unit, precision)} ${unit}` : text;
  }
  return typeof value === "number" ? reportAmount(value, precision) : text;
}

/** Numeric display strings with an explicit amount unit; no guessing for dates/codes/ratios. */
export function reportUnitText(text: string, unit: string, precision: number): string {
  if (unit === "x" || unit === "%") return dedicatedPrecision(text, unit);
  if (/^(EUR|kEUR|mEUR|MW|MWh|h\/yr|months|years)$/i.test(unit) && parseDisplayNumber(text).kind === "number") {
    return formatMoneyText(text, "kEUR", "kEUR", precision);
  }
  return text;
}

export function reportComparisonText(text: string, label: string, precision: number): string {
  if (/[x%]\s*$|\b(EUR|kEUR|mEUR)\s*$/.test(text)) return reportMetric(text, "kEUR", precision);
  if (/\b(dscr|llcr|plcr|coverage|moic|multiple)\b/i.test(label)) return dedicatedPrecision(text, "x");
  if (/\b(irr|interest|inflation|rate|margin|gearing)\b/i.test(label)) return text;
  return reportUnitText(text, "kEUR", precision);
}

/** Format a server-authored monetary delta; never derive a delta in the browser. */
export function reportDelta(text: string, unit: string, precision: number): string {
  if (!/^(EUR|kEUR|mEUR|MW|MWh)$/i.test(unit)) return text;
  const match = /^(\+?)(-?[\d,]+(?:\.\d+)?)(\s*(?:EUR|kEUR|mEUR|MW|MWh))?$/.exec(text.trim());
  if (!match) return text;
  return `${match[1]}${reportUnitText(match[2], unit, precision)}${match[3] || ""}`;
}
