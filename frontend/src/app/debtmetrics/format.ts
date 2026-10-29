/** Presentation helpers for the Debt Metrics view.  Nothing here decides a status: every verdict is computed on the server on raw doubles. */

/** A ratio as `1.05x` with enough digits that it never reads EQUAL to a reference unless it is (mirrors `format_ratio` on the server). */
export function formatRatio(value: number | null | undefined, refs: ReadonlyArray<number> = [1], minDigits = 2, maxDigits = 12): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const references = refs.filter((r) => typeof r === "number" && Number.isFinite(r));
  const rounded = (x: number, digits: number) => Number(x.toFixed(digits));
  for (let digits = minDigits; digits <= maxDigits; digits += 1) {
    const shown = rounded(value, digits);
    if (references.every((r) => (shown === rounded(r, digits)) === (value === r) && (value === r || (shown < rounded(r, digits)) === (value < r)))) {
      return `${value.toFixed(digits)}x`;
    }
  }
  return `${value.toFixed(maxDigits)}x`;
}

/** A signed ratio difference with at least two significant digits (never `+0.00x` for a non-zero difference). */
export function formatDeltaX(delta: number | null | undefined, minDigits = 2, maxDigits = 12): string {
  if (typeof delta !== "number" || !Number.isFinite(delta)) return "—";
  if (delta === 0) return `+${(0).toFixed(minDigits)}x`;
  const digits = Math.max(minDigits, Math.min(maxDigits, 1 - Math.floor(Math.log10(Math.abs(delta)))));
  return `${delta > 0 ? "+" : ""}${delta.toFixed(digits)}x`;
}

export interface ScaleBox { left: number; right: number; top: number; bottom: number }

/** Linear scale; a degenerate domain maps to the middle of the range. */
export function linearScale(domain: readonly [number, number], range: readonly [number, number]): (v: number) => number {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  if (d1 === d0) return () => (r0 + r1) / 2;
  return (v) => r0 + ((v - d0) / (d1 - d0)) * (r1 - r0);
}

/** "Nice" tick values covering [lo, hi]. */
export function niceTicks(lo: number, hi: number, target = 5): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) return Number.isFinite(lo) ? [lo] : [];
  const raw = (hi - lo) / Math.max(1, target);
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) ?? 10 * magnitude;
  const start = Math.ceil(lo / step - 1e-9) * step;
  const ticks: number[] = [];
  for (let t = start; t <= hi + step * 1e-9; t += step) ticks.push(Number(t.toFixed(10)));
  return ticks;
}

/** SVG path of a series that is BROKEN wherever a value is null (no scheduled service): no 0x line is ever drawn across a gap. */
export function brokenPath(points: ReadonlyArray<{ x: number; y: number | null }>): string {
  let d = "";
  let pen = false;
  for (const p of points) {
    if (p.y === null || !Number.isFinite(p.y)) { pen = false; continue; }
    d += `${pen ? "L" : "M"}${p.x.toFixed(2)},${p.y.toFixed(2)}`;
    pen = true;
  }
  return d;
}

/** Y-domain that always contains every plotted value and every drawn threshold, with a small pad. */
export function yDomain(values: ReadonlyArray<number | null | undefined>, extra: ReadonlyArray<number | null | undefined>): [number, number] {
  const all = [...values, ...extra].filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  if (!all.length) return [0, 2];
  let lo = Math.min(...all);
  let hi = Math.max(...all);
  if (hi === lo) { lo -= 0.5; hi += 0.5; }
  const pad = (hi - lo) * 0.08;
  return [lo - pad, hi + pad];
}

/** Which x labels to draw (evenly spaced, always including the first and last). */
export function labelIndexes(count: number, maxLabels = 8): number[] {
  if (count <= 0) return [];
  if (count <= maxLabels) return Array.from({ length: count }, (_, i) => i);
  const step = Math.ceil((count - 1) / (maxLabels - 1));
  const out: number[] = [];
  for (let i = 0; i < count; i += step) out.push(i);
  if (out[out.length - 1] !== count - 1) out.push(count - 1);
  return out;
}

/** CSV of the schedule exactly as persisted: raw values (full precision), one column per period, `n/a` for a value the Run did not persist. */
export function scheduleCsv(periods: ReadonlyArray<{ label: string; date: string | null }>, groups: ReadonlyArray<{ label: string; rows: ReadonlyArray<{ label: string; unit: string; values: ReadonlyArray<number | boolean | null>; available: boolean }> }>): string {
  const esc = (s: string) => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
  const lines = [["Group", "Line", "Unit", ...periods.map((p) => `${p.label}${p.date ? ` (${p.date})` : ""}`)].map(esc).join(",")];
  for (const g of groups) {
    for (const r of g.rows) {
      const cells = r.values.map((v) => (v === null || !r.available ? "n/a" : typeof v === "boolean" ? (v ? "yes" : "no") : String(v)));
      lines.push([g.label, r.label, r.unit, ...cells].map(esc).join(","));
    }
  }
  return `${lines.join("\n")}\n`;
}
