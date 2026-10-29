// WS-2 — which pending-change section a canonical scalar field belongs to.
// One field is ONE pending edit no matter which editor staged it (assumption grid or the sheet editor), so the section follows the field id.
import type { EditSection } from "./pendingEdits";

export const sectionOfField = (fieldId: string): EditSection => (fieldId.startsWith("debt.") ? "financing" : "inputs");
export const SCALAR_SECTIONS: readonly EditSection[] = ["inputs", "financing"];
