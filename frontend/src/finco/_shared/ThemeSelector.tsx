import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import {
  applyTheme,
  FINCO_THEME_IDS,
  FINCO_THEME_LABELS,
  FINCO_THEME_STORAGE_KEY,
  loadStoredTheme,
  storeTheme,
  type FincoThemeId,
} from "./theme";

type ThemeContextValue = {
  themeId: FincoThemeId | null;
  setThemeId: (id: FincoThemeId | null) => void;
};

const ThemeContext = createContext<ThemeContextValue>({ themeId: null, setThemeId: () => undefined });

/** Mount-scoped theme provider. Persists the presentation-only preference via
 *  {@link storeTheme}; when storage refuses (private mode, quota, disabled) the
 *  choice stays in memory for this visit and rendering continues unchanged. */
export function ThemeProvider({ host, children }: { host: HTMLElement; children: ReactNode }) {
  const [themeId, setThemeState] = useState<FincoThemeId | null>(() => loadStoredTheme());
  useEffect(() => {
    applyTheme(host, themeId);
  }, [host, themeId]);
  const setThemeId = (id: FincoThemeId | null) => {
    setThemeState(id);
    storeTheme(id);
  };
  return <ThemeContext.Provider value={{ themeId, setThemeId }}>{children}</ThemeContext.Provider>;
}

export function useFincoTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}

/** Native select: keyboard operable and screen-reader labelled out of the box.
 *  Lives in the React shell top bar; changing the value never touches data. */
export function ThemeSelector() {
  const { themeId, setThemeId } = useFincoTheme();
  return (
    <label className="fm-theme-select">
      <span className="fm-theme-select-caption">Appearance</span>
      <select
        className="fm-theme-select-control"
        data-testid="finco-theme-select"
        aria-label="Visual appearance theme"
        value={themeId ?? ""}
        onChange={(event) => {
          const next = event.target.value;
          setThemeId(next === "" ? null : (FINCO_THEME_IDS as readonly string[]).includes(next) ? (next as FincoThemeId) : null);
        }}
      >
        <option value="">FINCO default</option>
        {FINCO_THEME_IDS.map((id) => (
          <option key={id} value={id}>{FINCO_THEME_LABELS[id]}</option>
        ))}
      </select>
    </label>
  );
}

export { FINCO_THEME_STORAGE_KEY };
