// WF-06B — the one "show amounts in" choice for the Inputs cost figures (EUR | kEUR | mEUR, default kEUR).
// Presentation only: it re-expresses read-only figures; stored amounts are always kEUR text and are never rewritten by it.
// Decimals come from the existing report-precision control (0–3, default 0).
import { useSyncExternalStore } from "react";
import { DISPLAY_UNITS, type DisplayUnit } from "./costAmounts";

let current: DisplayUnit = "kEUR";
const listeners = new Set<() => void>();
const subscribe = (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; };

export function useCostUnit(): [DisplayUnit, (unit: DisplayUnit) => void] {
  const unit = useSyncExternalStore(subscribe, () => current, () => "kEUR" as DisplayUnit);
  return [unit, (next) => { if (next !== current) { current = next; listeners.forEach((fn) => fn()); } }];
}

export function CostUnitSelect() {
  const [unit, setUnit] = useCostUnit();
  return (
    <label className="ci-unit">Show amounts in
      <select className="fm-input" data-ci-unit="true" aria-label="Show amounts in" value={unit} onChange={(e) => setUnit(e.target.value as DisplayUnit)}>
        {DISPLAY_UNITS.map((u) => <option key={u} value={u}>{u}</option>)}
      </select>
    </label>
  );
}
