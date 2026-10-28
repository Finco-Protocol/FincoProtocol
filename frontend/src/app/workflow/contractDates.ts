// Boundary-date guidance for a PPA contract's start / end date (Audit A GAP-R23).
//
// The operating-period boundaries and period starts come from the server (the periods the model already derives from the project's own
// dates).  This module only picks the nearest accepted boundary dates and counts the server-provided period starts inside the term, so the
// user can fix a date in one click.  It never rounds a date for them, never changes a value on its own and decides nothing: the canonical
// validator still accepts or refuses the saved contract.

export interface DateSuggestion { field: "start_date" | "end_date"; value: string; label: string }
export interface DateGuidance { message: string; suggestions: DateSuggestion[] }
export interface OperatingCalendar { boundaries: string[]; starts: string[]; windowEnd: string | null }

const time = (iso: string) => Date.parse(`${iso}T00:00:00Z`);
const ISO = /^\d{4}-\d{2}-\d{2}$/;

export function calendarFrom(contracts: Record<string, unknown>): OperatingCalendar | null {
  const boundaries = Array.isArray(contracts.operating_boundaries) ? (contracts.operating_boundaries as unknown[]).filter((d): d is string => typeof d === "string") : [];
  const starts = Array.isArray(contracts.operating_starts) ? (contracts.operating_starts as unknown[]).filter((d): d is string => typeof d === "string") : [];
  if (!boundaries.length) return null;
  const window = contracts.operating_window as { end?: string } | null | undefined;
  return { boundaries, starts, windowEnd: window?.end ?? boundaries[boundaries.length - 1] ?? null };
}

const covered = (calendar: OperatingCalendar, from: string, to: string) => calendar.starts.filter((d) => d >= from && d < to).length;
const meaning = (calendar: OperatingCalendar, from: string, to: string) => {
  const n = covered(calendar, from, to);
  return `${n} operating period${n === 1 ? "" : "s"}`;
};

/** Why the entered date cannot be saved and which accepted dates are closest; null when the date is acceptable (or not yet a complete date). */
export function dateGuidance(field: "start_date" | "end_date", start: string, end: string, calendar: OperatingCalendar | null): DateGuidance | null {
  if (!calendar || !ISO.test(start) || !ISO.test(end)) return null;
  const value = field === "start_date" ? start : end;
  const other = field === "start_date" ? end : start;
  const pick = (candidates: string[]): DateSuggestion[] => {
    const earlier = candidates.filter((d) => d < value).pop();
    const later = candidates.find((d) => d > value);
    const nearest = [earlier, later].filter((d): d is string => Boolean(d))
      .sort((a, b) => Math.abs(time(a) - time(value)) - Math.abs(time(b) - time(value)) || (a < b ? -1 : 1));
    return nearest.map((d) => ({ field, value: d, label: `Use ${d} (${field === "end_date" ? meaning(calendar, other, d) : meaning(calendar, d, other)})` }));
  };
  if (field === "start_date") {
    if (calendar.boundaries.includes(start)) return null;
    return { message: `The start date ${start} is not the first day of a model operating period, so the contract cannot be saved as entered.`,
             suggestions: pick(calendar.boundaries.filter((d) => d < end)) };
  }
  if (calendar.windowEnd && end > calendar.windowEnd) {
    return { message: `The end date ${end} is after the model operating period ends (${calendar.windowEnd}). Only the modelled periods are priced; choose an end on or before ${calendar.windowEnd}.`,
             suggestions: [{ field, value: calendar.windowEnd, label: `Use ${calendar.windowEnd} (${meaning(calendar, start, calendar.windowEnd)})` }] };
  }
  if (calendar.boundaries.includes(end)) return null;
  return { message: `The end date ${end} is not an operating-period boundary, so the contract cannot be saved as entered. The end date is exclusive: the contract covers every operating period that starts before it. Choose one of the nearest accepted dates; the term is never rounded for you.`,
           suggestions: pick(calendar.boundaries.filter((d) => d > start)) };
}

