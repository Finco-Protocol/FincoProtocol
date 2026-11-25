// OD-R04-02 — server-authoritative review of the UNSAVED contract book against ONE global P50 envelope.
//
// Presentation only: the numbers come from POST /v2/model-react/revenue/review (read-only, owner/project/revision bound, same exact slice
// arithmetic as the canonical Save/Run validation).  Nothing here computes quantities, caps or prices, and nothing here saves: the canonical
// writer re-validates every Save and its refusal is displayed by the editor.  A late answer for an older draft never replaces a newer one.

import { useEffect, useRef, useState } from "react";
import { reviewRevenueContracts, type R04ReviewResult } from "../api";

type Props = {
  project: string;
  csrfToken: string;
  contentHash: string;
  /** Canonical contract document of the CURRENT draft, or null while the draft still has field errors. */
  contractsJson: string | null;
};

const mwh = (v: number) => `${v.toLocaleString("en-US", { minimumFractionDigits: 3, maximumFractionDigits: 3 })} MWh`;
const gwh = (v: number) => `${(v / 1000).toLocaleString("en-US", { minimumFractionDigits: 3, maximumFractionDigits: 3 })} GWh`;
const pct = (v: number) => `${(v * 100).toFixed(2)}%`;

export function R04CapReview({ project, csrfToken, contentHash, contractsJson }: Props) {
  const [result, setResult] = useState<R04ReviewResult | null>(null);
  const [pending, setPending] = useState(false);
  const seq = useRef(0);

  useEffect(() => {
    if (contractsJson === null) { setResult(null); setPending(false); return; }
    const mine = ++seq.current;
    setPending(true);
    const timer = window.setTimeout(async () => {
      const answer = await reviewRevenueContracts({ project, csrfToken, contentHash, contractsJson });
      if (mine !== seq.current) return;                     // a newer draft was reviewed meanwhile: never overwrite it with an older answer
      setResult(answer);
      setPending(false);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [project, csrfToken, contentHash, contractsJson]);

  return (
    <section className="fm-card wf-r04-review" aria-label="Global P50 cap review" data-r04-review={pending ? "pending" : result ? result.kind : "idle"}>
      <h4>Global P50 cap review <small>(all physical PPA contracts, one envelope; server-calculated, advisory until you save)</small></h4>
      {contractsJson === null && <p className="fm-info-note" data-r04-state="incomplete" role="status">Complete the highlighted contract fields to see the cap review. Nothing is saved.</p>}
      {contractsJson !== null && pending && <p className="fm-info-note" data-r04-state="pending" role="status">Reviewing the proposed contracts against the P50 envelope…</p>}
      {contractsJson !== null && !pending && result?.kind === "unavailable" && (
        <p className="fm-info-note" data-r04-state="unavailable" role="alert">{result.message}</p>
      )}
      {contractsJson !== null && !pending && result?.kind === "refused" && (
        <p className="wf-error" data-r04-state="refused" data-r04-code={result.code} role="alert">{result.code}: {result.message}</p>
      )}
      {contractsJson !== null && !pending && result?.kind === "ok" && !result.applicable && (
        <p className="fm-info-note" data-r04-state="not-applicable" role="status">No fixed annual quantity in this draft: the percentage-share contracts follow the existing rules.</p>
      )}
      {contractsJson !== null && !pending && result?.kind === "ok" && result.applicable && result.review && (
        <>
          {result.stale && <p className="fm-info-note" role="alert" data-r04-state="stale">The project changed since this page loaded; the review reflects the current saved project. Reload before saving.</p>}
          <p className="fm-info-note" data-r04-basis="P50" data-r04-selected-scenario={result.review.selected_yield_scenario}>
            Cap basis: <strong>P50</strong> ({result.review.p50_hours} h/year). The selected case ({result.review.selected_yield_scenario}, {result.review.selected_case_hours} h/year)
            does not change the cap. Horizon {result.review.horizon_start} → {result.review.horizon_end_exclusive} (end exclusive); partial calendar years are prorated by eligible days / 365 or 366.
          </p>
          {result.review.blocked && (
            <p className="wf-error" role="alert" data-r04-state="blocked" data-r04-blocked="true">
              Over the P50 cap in {result.review.exceeded_slices.length} period(s); first: {result.review.exceeded_slices[0].period_start} → {result.review.exceeded_slices[0].period_end_exclusive}
              {" "}committed {mwh(result.review.exceeded_slices[0].committed_mwh)} &gt; available {mwh(result.review.exceeded_slices[0].available_p50_mwh)}
              {" "}(excess {mwh(result.review.exceeded_slices[0].excess_mwh)}). Saving is refused by the server until the commitment fits.
            </p>
          )}
          {!result.review.blocked && result.review.warning && (
            <p className="fm-info-note" role="status" data-r04-state="warning">At least one year commits 95% or more of the P50 envelope.</p>
          )}
          {result.review.shortfall_slices.length > 0 && (
            <p className="wf-error" role="alert" data-r04-state="shortfall" data-r04-code={result.review.shortfall_error_code ?? ""}>
              The selected case ({result.review.selected_yield_scenario}) cannot deliver the fixed commitments in {result.review.shortfall_slices.length} period(s)
              (first shortfall {mwh(result.review.shortfall_slices[0].shortfall_mwh)} in {result.review.shortfall_slices[0].period_start} → {result.review.shortfall_slices[0].period_end_exclusive}).
              A Run on this case is refused ({result.review.shortfall_error_code}); the obligation is never reduced and no settlement is invented.
            </p>
          )}
          {result.review.p90_shortfall_slices.length > 0 && result.review.shortfall_slices.length === 0 && (
            <p className="fm-info-note" role="status" data-r04-state="p90-note" data-r04-p90-shortfall="true">
              On the P90 case ({result.review.p90_hours} h/year) these fixed quantities exceed generation in {result.review.p90_shortfall_slices.length} period(s)
              (first shortfall {mwh(result.review.p90_shortfall_slices[0].shortfall_mwh)}). Saving is allowed because the cap is P50, but a Run or debt sizing on the P90 case is
              refused (R04_PHYSICAL_SHORTFALL_NO_SETTLEMENT_CONTRACT); the fixed quantity is never reduced.
            </p>
          )}
          {result.bank_case_readiness && result.bank_case_readiness.status === "BANK_CASE_SHORTFALL_BLOCKED" && (
            <div className="wf-error" role="alert" data-r04-bank-readiness={result.bank_case_readiness.status}>
              <strong>Bank-case Run readiness: BLOCKED ({result.bank_case_readiness.error_code})</strong>
              <p>{result.bank_case_readiness.message}</p>
              {result.bank_case_readiness.remediation && <p>{result.bank_case_readiness.remediation}</p>}
            </div>
          )}
          {result.bank_case_readiness && result.bank_case_readiness.status === "READY" && (
            <p className="fm-info-note" role="status" data-r04-bank-readiness="READY">
              Bank-case Run readiness ({result.bank_case_readiness.bank_yield_scenario}): READY.
            </p>
          )}
          <div className="wf-table-wrap" tabIndex={0} role="region" aria-label="P50 envelope by calendar year" style={{ overflowX: "auto" }}>
            <table className="fm-table" data-r04-table="years">
              <thead><tr><th scope="col">Year</th><th scope="col">Available P50</th><th scope="col">Committed</th><th scope="col">Remaining</th><th scope="col">Used</th><th scope="col">Status</th></tr></thead>
              <tbody>
                {result.review.years.map((y) => (
                  <tr key={y.year} data-r04-year={y.year} data-r04-exceeded={y.exceeded ? "true" : "false"} data-r04-warning={y.warning ? "true" : "false"}>
                    <th scope="row">{y.year}</th>
                    <td>{mwh(y.available_p50_mwh)} <small>({gwh(y.available_p50_mwh)})</small></td>
                    <td>{mwh(y.committed_mwh)}</td>
                    <td>{mwh(y.remaining_p50_mwh)}</td>
                    <td>{pct(y.utilization_ratio)}</td>
                    <td>{y.exceeded ? "EXCEEDED" : y.warning ? "≥95%" : "OK"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
