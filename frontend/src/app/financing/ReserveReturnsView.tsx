import "../../styles/rcm-financing.css";
import type { DsraCashRow, EvidenceMetric, FinancingStudioPayload } from "./types";

const FRESH: Record<string, string> = { CURRENT: "CURRENT", STALE: "STALE", NOT_RUN: "NOT RUN" };

function Facts({ items, testid }: { items: EvidenceMetric[]; testid: string }) {
  return (
    <dl className="rcm-facts" data-facts={testid}>
      {items.map((m) => (
        <div key={m.label} data-evidence-metric={m.label} title={m.source}>
          <dt>{m.label}</dt>
          <dd>{m.display}{m.value === null && m.reason && <span className="rcm-reason">{m.reason}</span>}</dd>
        </div>
      ))}
    </dl>
  );
}

const periodLabel = (value: number | string | null | undefined): string => (value === null || value === undefined ? "not exposed" : String(value));

function CashRows({ rows }: { rows: DsraCashRow[] }) {
  if (!rows.length) {
    return <p className="rx-empty" data-dsra-cash-empty="true">Debt service and reserve cash by period appear after a Run that produced a cash waterfall. Nothing is estimated here.</p>;
  }
  return (
    <div className="rcm-scroll" data-dsra-cash="true">
      <table className="rcm-table">
        <caption className="sr-only">Cash available for Senior debt service and reserve movements by period</caption>
        <thead><tr><th scope="col" className="rcm-left">Period</th><th scope="col" className="rcm-left">Date</th><th scope="col">Cash available for Senior</th>
          <th scope="col">Senior debt service paid</th><th scope="col">Reserve funding</th><th scope="col">Reserve release</th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="rcm-left">{periodLabel(r.period)}</td><td className="rcm-left">{r.date ?? "—"}</td>
              <td>{r.cfads.display}</td><td>{r.service.display}</td><td>{r.funding.display}</td><td>{r.release.display}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Reserve policy, sponsor funding and returns, and the Senior debt cash rows — a read-only projection of the persisted Last Run
 *  and the Working financing inputs (shown inside the financing Overview), exactly as the Legacy Debt and Investor sheets present them.  Nothing is recomputed here;
 *  a value the Run did not persist stays "Not available" with its reason (never zero). */
export function ReserveReturnsView({ studio }: { studio: FinancingStudioPayload }) {
  const reserve = studio.reserve_view;
  const sponsor = studio.sponsor_view;
  const evidence = studio.financing_evidence;
  const stale = studio.freshness === "STALE";
  return (
    <section className="rcm-fin-reserve" data-financing-reserve-returns="true" aria-labelledby="rcm-fin-rr">
      <h3 id="rcm-fin-rr" className="rcm-h3">Reserve, sponsor funding and returns <span className="rcm-badge" data-fin-freshness={studio.freshness}>LAST RUN · {FRESH[studio.freshness] ?? studio.freshness}</span></h3>
      {stale && <p className="rx-banner rx-banner-stale" role="status">Results outdated — the project changed after the last Run. Returns and cash rows are the prior Run&rsquo;s; the policy and funding terms are the current inputs.</p>}

      <h4 className="rcm-h4">Debt service reserve policy <span className="rcm-badge rcm-badge-input">WORKING INPUTS</span></h4>
      <dl className="rcm-facts" data-reserve-policy="true">
        <div><dt>Support instrument</dt><dd>{reserve.support}</dd></div>
        <div><dt>Target policy</dt><dd>{reserve.target}</dd></div>
        <div><dt>Coverage</dt><dd>{reserve.months === null || reserve.months === undefined ? "Not available" : `${reserve.months} months of debt service`}</dd></div>
        <div><dt>{reserve.requirement.label}</dt><dd>{reserve.requirement.display}</dd></div>
        <div><dt>{reserve.facility.label}</dt><dd>{reserve.facility.display}</dd></div>
      </dl>
      <p className="rx-note">The configured requirement is the policy input, not the dynamic reserve target the Run applies. Edit the supported reserve settings in <strong>Bankability</strong>. Reserve interest and the calculated target series are not part of the persisted results.</p>

      <h4 className="rcm-h4">Sponsor funding <span className="rcm-badge rcm-badge-input">WORKING INPUTS</span></h4>
      <p className="rx-note" data-sponsor-mode="true">Funding structure: {sponsor.mode}. These assumptions are read-only here; the common-equity agreement is edited under <strong>Investors &amp; sponsor</strong>.</p>
      <h5 className="rcm-h5">Sponsor equity</h5><Facts items={sponsor.equity} testid="sponsor-equity" />
      <h5 className="rcm-h5">Shareholder loan</h5>
      <Facts items={sponsor.shl} testid="sponsor-shl" />
      <dl className="rcm-facts" data-sponsor-shl-terms="true">
        <div><dt>Repayment</dt><dd>{sponsor.repayment}</dd></div>
        <div><dt>Interest day count</dt><dd>{sponsor.day_count}</dd></div>
        <div><dt>Principal eligibility</dt><dd>{sponsor.eligibility === null || sponsor.eligibility === undefined ? "Not exposed" : `From model period ${sponsor.eligibility}`}</dd></div>
        <div><dt>Maturity</dt><dd>{sponsor.maturity === null || sponsor.maturity === undefined ? "Not exposed" : `Model period ${sponsor.maturity}`}</dd></div>
      </dl>
      <h5 className="rcm-h5">Other funding</h5><Facts items={sponsor.other} testid="sponsor-other" />

      <h4 className="rcm-h4">Equity-only and sponsor-inclusive returns <span className="rcm-badge rcm-badge-derived">DERIVED · READ ONLY</span></h4>
      <p className="rx-note">Equity-only returns cover legal equity contributions and distributions. Sponsor-inclusive returns add shareholder-loan cash. A multiple is a cash ratio, not an annual return; timing is reflected in the IRR.</p>
      <Facts items={sponsor.returns} testid="sponsor-returns" />

      <h4 className="rcm-h4">Senior debt cash by period <span className="rcm-badge rcm-badge-derived">DERIVED · READ ONLY</span></h4>
      <CashRows rows={evidence.cash_rows ?? []} />
      <p className="rx-note" data-sizing-status="true">Sizing and binding-constraint status: {evidence.sizing_status ?? "Not available"}. {evidence.sizing_reason}</p>
    </section>
  );
}
