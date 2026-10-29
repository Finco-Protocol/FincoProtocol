// WS-2 / M-013 — human percent input over a canonical ratio.
//
// The user types `2` or `100`; the owning editor keeps the canonical ratio (`0.02`, `1`).  The
// conversion is the exact decimal shift in percent.ts, applied once at this boundary.  While the
// user is typing, the raw text is kept as typed (so `2.` or `2,5` is never rewritten under the
// cursor); an invalid entry is reported to the parent and the canonical value is left unchanged.

import { useEffect, useRef, useState } from "react";
import "../../styles/ws2-editing.css";
import { toCanonical, toDisplay } from "./percent";

interface Props {
  id: string;
  /** Canonical ratio text ("0.02"); "" when empty. */
  canonical: string;
  disabled?: boolean;
  /** Called with the new canonical ratio ("" when cleared) or with an error and no value. */
  onChange: (result: { canonical: string; error?: undefined } | { canonical?: undefined; error: string }) => void;
  /** Allow an empty value (merchant share = residual).  Otherwise empty is an error. */
  allowEmpty?: boolean;
  describedBy?: string;
  invalid?: boolean;
}

export function PercentInput({ id, canonical, disabled, onChange, allowEmpty = false, describedBy, invalid }: Props) {
  const shown = canonical === "" ? "" : toDisplay(canonical) ?? canonical;
  const [text, setText] = useState<string>(shown);
  const lastCanonical = useRef(canonical);
  // The canonical value changed from outside (reset, Undo, reload): show it.  Our own echo does not rewrite the text.
  useEffect(() => {
    if (canonical !== lastCanonical.current) { lastCanonical.current = canonical; setText(canonical === "" ? "" : toDisplay(canonical) ?? canonical); }
  }, [canonical]);

  const handle = (next: string) => {
    setText(next);
    if (next.trim() === "") {
      if (allowEmpty) { lastCanonical.current = ""; onChange({ canonical: "" }); }
      else onChange({ error: "Enter a percentage between 0 and 100." });
      return;
    }
    const result = toCanonical(next);
    if (result.ok) { lastCanonical.current = result.canonical; onChange({ canonical: result.canonical }); }
    else onChange({ error: result.message });
  };

  return (
    <span className="ws2-pct">
      <input id={id} className="fm-input" type="text" inputMode="decimal" autoComplete="off" value={text} disabled={disabled}
             aria-describedby={describedBy} aria-invalid={invalid ? true : undefined}
             onChange={(e) => handle(e.target.value)} />
      <span className="ws2-pct-suffix" aria-hidden="true">%</span>
    </span>
  );
}
