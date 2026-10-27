// A canonical field label may already end with its unit, e.g. "IT Capacity (MW)" with
// unit "MW".  Rendering `${label} (${unit})` then repeats the unit ("IT Capacity (MW) (MW)").
// The unit is rendered exactly once: any trailing "(unit)" the label carries is
// removed from the label text so the dedicated unit slot shows it.  Metadata only; the
// unit, value and any conversion are untouched.

const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export function splitLabelUnit(label: string, unit?: string | null): { label: string; unit: string } {
  const cleanUnit = (unit ?? "").trim();
  const text = label.trim();
  if (!cleanUnit) return { label: text, unit: "" };
  const trailing = new RegExp(`\\s*\\(\\s*${escape(cleanUnit)}\\s*\\)\\s*$`, "i");
  return { label: text.replace(trailing, "").trim() || text, unit: cleanUnit };
}

/** Plain text form (accessible names): the label and its unit, once. */
export function labelWithUnit(label: string, unit?: string | null): string {
  const parts = splitLabelUnit(label, unit);
  return parts.unit ? `${parts.label} (${parts.unit})` : parts.label;
}
