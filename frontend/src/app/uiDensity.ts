// WF-06B — one non-sensitive UI preference shared by the Inputs grid and the CAPEX/OPEX grid: normal (~14px text, 32px controls) or compact
// (27px controls). It stores the word "compact" or "normal" and never any project value; every storage access is optional.
import { useCallback, useEffect, useState } from "react";

export type Density = "normal" | "compact";
const KEY = "finco.ui.density";
const EVENT = "finco-density-change";

export const readDensity = (): Density => {
  try { return window.localStorage.getItem(KEY) === "compact" ? "compact" : "normal"; } catch { return "normal"; }
};

export function useDensity(): [Density, () => void] {
  const [density, setDensity] = useState<Density>(readDensity);
  useEffect(() => {
    const sync = () => setDensity(readDensity());
    window.addEventListener(EVENT, sync);
    return () => window.removeEventListener(EVENT, sync);
  }, []);
  const toggle = useCallback(() => {
    const next: Density = readDensity() === "compact" ? "normal" : "compact";
    try { window.localStorage.setItem(KEY, next); } catch { /* the preference is optional */ }
    setDensity(next);
    window.dispatchEvent(new Event(EVENT));
  }, []);
  return [density, toggle];
}
