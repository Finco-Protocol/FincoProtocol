import { Assumptions, assumptionLabels, InputKey, validateAssumptions } from "../_shared/validation";
export const scalarKeys = Object.keys(assumptionLabels) as InputKey[];
export function gridErrors(values: Assumptions) {
  return { ...validateAssumptions(values, "Fixed").errors, ...validateAssumptions(values, "Indexed").errors, ...validateAssumptions(values, "Scheduled").errors };
}
export function pasteScalars(text: string, start: number, current: Assumptions): { values?: Assumptions; error?: string } {
  const rows = text.replace(/\r/g, "").replace(/\n+$/, "").split("\n").map(row => row.split("\t"));
  if (!text.trim() || rows.length > scalarKeys.length) return { error: "Paste rejected: empty or oversized scalar batch. Nothing staged." };
  const named = rows.every(row => row.length === 2);
  if (!named && !rows.every(row => row.length === 1)) return { error: "Paste rejected: use one value column or two columns (metric / value). Nothing staged." };
  const next = { ...current };
  const seen = new Set<InputKey>();
  for (let i = 0; i < rows.length; i++) {
    const key = named ? scalarKeys.find(k => k.toLowerCase() === rows[i][0].trim().toLowerCase() || assumptionLabels[k].toLowerCase() === rows[i][0].trim().toLowerCase()) : scalarKeys[start + i];
    if (!key || seen.has(key)) return { error: "Paste rejected: unknown/duplicate metric or locked/out-of-range row. Nothing staged." };
    seen.add(key);
    next[key] = rows[i][named ? 1 : 0].trim();
  }
  const errors = gridErrors(next);
  const first = Object.keys(errors)[0] as InputKey | undefined;
  if (first) return { error: `Paste rejected: ${assumptionLabels[first]} — ${errors[first]} Nothing staged; batch is all-or-nothing.` };
  return { values: next };
}
