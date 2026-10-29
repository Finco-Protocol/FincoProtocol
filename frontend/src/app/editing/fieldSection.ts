// WS-2 — which pending-change section a canonical scalar field belongs to.
// One field is ONE pending edit no matter which editor staged it (assumption grid or the sheet editor), so the section follows the field id.
import type { EditSection } from "./pendingEdits";

export const sectionOfField = (fieldId: string): EditSection => (fieldId.startsWith("debt.") ? "financing" : "inputs");
export const SCALAR_SECTIONS: readonly EditSection[] = ["inputs", "financing"];

/** Field-id prefix of each sheet whose scalar fields stage into the store.  Every other sheet (revenue, ...) has none and owns no staged edit. */
export const SHEET_FIELD_PREFIX: Readonly<Record<string, string>> = { project_setup: "project_setup.", debt: "debt." };

/** The staged edits that belong to `sheet`: exactly the keys under its own prefix.  An unknown sheet owns NONE (never "all"). */
export function editsOfSheet<T extends { key: string }>(edits: readonly T[], sheet: string): T[] {
  const prefix = Object.prototype.hasOwnProperty.call(SHEET_FIELD_PREFIX, sheet) ? SHEET_FIELD_PREFIX[sheet] : undefined;
  return prefix ? edits.filter((e) => e.key.startsWith(prefix)) : [];
}
