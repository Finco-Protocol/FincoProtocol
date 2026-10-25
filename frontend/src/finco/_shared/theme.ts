/** UX-03B — owner-selected visual themes (B/D/G decision, 2026-10-23).
 *
 *  Presentation only. A selection changes CSS custom properties scoped to the
 *  React mount root; it never mutates project data, Save/Run outcomes,
 *  authorization or any financial value. The absence of a selection is the
 *  shipped FINCO default look, which stays the production default.
 */

export const FINCO_THEME_IDS = ["b-slate-teal", "d-high-contrast", "g-forest-green-white"] as const;
export type FincoThemeId = (typeof FINCO_THEME_IDS)[number];

export const FINCO_THEME_LABELS: Record<FincoThemeId, string> = {
  "b-slate-teal": "Slate & Teal",
  "d-high-contrast": "High-Contrast",
  "g-forest-green-white": "Forest Green / White Workbook",
};

/** Attribute set on the React mount root (never on documentElement), so the
 *  scoped theme CSS cannot reach the legacy Jinja/HTMX UI. */
export const FINCO_THEME_ATTRIBUTE = "data-fm-theme";
export const FINCO_THEME_STORAGE_KEY = "fincoReactTheme";

export function isFincoThemeId(value: unknown): value is FincoThemeId {
  return typeof value === "string" && (FINCO_THEME_IDS as readonly string[]).includes(value);
}

/** Read the persisted theme. Storage failures, missing storage and unknown
 *  values all fall back to the shipped default (null). Never throws. */
export function loadStoredTheme(storage?: Storage | null): FincoThemeId | null {
  try {
    const s = storage === undefined ? (globalThis as { localStorage?: Storage | null }).localStorage ?? null : storage;
    if (!s) return null;
    const raw = s.getItem(FINCO_THEME_STORAGE_KEY);
    return isFincoThemeId(raw) ? raw : null;
  } catch {
    return null;
  }
}

/** Persist the selection; null clears it. Returns false when storage refuses
 *  (private mode, quota, disabled). Never throws — the caller keeps the
 *  in-memory choice either way. */
export function storeTheme(id: FincoThemeId | null, storage?: Storage | null): boolean {
  try {
    const s = storage === undefined ? (globalThis as { localStorage?: Storage | null }).localStorage ?? null : storage;
    if (!s) return false;
    if (id === null) s.removeItem(FINCO_THEME_STORAGE_KEY);
    else s.setItem(FINCO_THEME_STORAGE_KEY, id);
    return true;
  } catch {
    return false;
  }
}

/** Apply (or clear) the theme attribute on the React mount root. */
export function applyTheme(host: HTMLElement | null, id: FincoThemeId | null): void {
  if (!host) return;
  if (id === null) host.removeAttribute(FINCO_THEME_ATTRIBUTE);
  else host.setAttribute(FINCO_THEME_ATTRIBUTE, id);
}
