import { formatFromCanonicalUnit } from '../units';
import { reportCell, reportUnitText } from '../reportFormatting';
import type { EvidenceCell } from './types';

/** Money uses canonical numeric precision; other units retain the canonical server text. */
export function evidenceDisplay(value: number | null, text: string, unit: string, precision = 0): string {
  if (value === null || !Number.isFinite(value)) return 'Unavailable';
  const format = formatFromCanonicalUnit(unit);
  return format ? reportCell(text, format, format.kind === 'money' ? format.base : 'kEUR', precision, value) : reportUnitText(text, unit, precision);
}
export function numericCell(cell: EvidenceCell | undefined): number | null {
  return typeof cell?.v === 'number' && Number.isFinite(cell.v) ? cell.v : null;
}
export interface PlotPoint { x: number; y: number; value: number; index: number }
/** Geometry ONLY: map persisted numbers onto one series' own labelled numeric axis. Nulls break lines. */
export function timelineGeometry(cells: readonly EvidenceCell[], width = 640, height = 160) {
  const values = cells.map(numericCell);
  const finite = values.filter((value): value is number => value !== null);
  const min = Math.min(0, ...finite), max = Math.max(0, ...finite);
  const span = max - min || 1;
  const y = (value: number) => height - 16 - (value - min) / span * (height - 32);
  const points: (PlotPoint | null)[] = values.map((value, index) => value === null ? null : {
    x: 24 + index / Math.max(1, cells.length - 1) * (width - 48), y: y(value), value, index,
  });
  const segments: PlotPoint[][] = [];
  let segment: PlotPoint[] = [];
  for (const point of points) {
    if (point) segment.push(point);
    else if (segment.length) { segments.push(segment); segment = []; }
  }
  if (segment.length) segments.push(segment);
  return { min, max, zeroY: y(0), points, segments };
}
/** Only React destinations are navigable.  A classic (Legacy) workbook route is never a user-facing target (Addendum A, React-only). */
export function evidenceHref(value: string | undefined): string | undefined {
  return value?.startsWith('/v2/model-react/') && !value.includes('\\') && !/[\u0000-\u001f]/.test(value) ? value : undefined;
}

/** Avoid repeated canonical suffixes when a value already includes its unit. */
export function evidenceUnitLabel(value: number | null, text: string, unit: string): string {
  const display = evidenceDisplay(value, text, unit).trim().toLowerCase();
  const normalized = unit.trim().toLowerCase();
  if (!normalized || display.endsWith(normalized)) return '';
  if (['ratio', 'multiple'].includes(normalized) && display.endsWith('x')) return '';
  if (['pct', 'percent'].includes(normalized) && display.endsWith('%')) return '';
  return unit;
}
