import "../../styles/rcm-financing.css";
import type { CapitalStackRow, EvidenceMetric, FinancingStudioPayload, SourcesUsesView, SuRow } from "./types";

const PRICING: Record<string, string> = {
  FLAT: "One flat all-in rate for the whole tenor (the Debt terms rate).",
  WORKING_CONFIG: "Explicit all-in rates by period from the bankability configuration.",
  CALIBRATED: "A calibrated period schedule owns the rate; the scalar rate is locked.",
  MULTI_SENIOR: "The active two-Senior configuration owns rates, fees, repayment and maturity.",
};
const DSCR: Record<string, string> = {
  FLAT_SCALAR: "One target DSCR for every period (the Debt terms value).",
  WORKING_CONFIG: "Period-specific DSCR targets from the bankability configuration.",
  CALIBRATED: "A calibrated period schedule owns the target; the scalar target is locked.",
  MULTI_SENIOR: "The active two-Senior configuration owns repayment sizing.",
};
const FRESH: Record<string, string> = { CURRENT: "CURRENT", STALE: "STALE", NOT_RUN: "NOT RUN" };
const num = (value: unknown): string => (typeof value === "number" ? value.toLocaleString("en-US", { maximumFractionDigits: 2 }) : "—");

function Metric({ m }: { m: EvidenceMetric }) {
  return (
    <div className="rcm-metric" data-evidence-metric={m.label}>
      <dt>{m.label}</dt>
      <dd>{m.display}{m.value === null && m.reason && <span className="rcm-reason">{m.reason}</span>}</dd>
    </div>
  );
}

/** Overview: authority modes, current terms, Last Run evidence, and what is editable vs derived vs not released. */
export function OverviewView({ studio }: { studio: FinancingStudioPayload }) {
  const stale = studio.freshness === "STALE";
  return (
    <section className="rx-card rcm-fin" data-financing-overview="true" aria-labelledby="rcm-fin-ov">
      <h3 id="rcm-fin-ov" className="rcm-h3">Financing overview <span className="rcm-badge" data-fin-freshness={studio.freshness}>LAST RUN · {FRESH[studio.freshness] ?? studio.freshness}</span></h3>
      {stale && <p className="rx-banner rx-banner-stale" role="status">STALE — the Working Copy changed after the last Run. The evidence below is the prior Run&rsquo;s; the terms are the current inputs.</p>}
      <div className="rcm-grid2">
        <div className="rcm-callout" data-senior-pricing={studio.senior_pricing_mode}>
          <strong>Senior pricing authority · {studio.senior_pricing_mode.replace(/_/g, " ")}</strong>
          <p>{PRICING[studio.senior_pricing_mode] ?? "Governed by the canonical financing authority."}</p>
        </div>
        <div className="rcm-callout" data-senior-dscr={studio.senior_dscr_mode}>
          <strong>Target DSCR authority · {studio.senior_dscr_mode.replace(/_/g, " ")}</strong>
          <p>{DSCR[studio.senior_dscr_mode] ?? "Governed by the canonical financing authority."}</p>
        </div>
      </div>
      {studio.senior_lock_reason && <p className="rx-note" data-senior-lock="true">{studio.senior_lock_reason}</p>}

      <h4 className="rcm-h4">Current Senior terms <span className="rcm-badge rcm-badge-input">WORKING INPUTS</span></h4>
      <dl className="rcm-facts" data-senior-terms="true">
        {studio.senior_detail_rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value ?? "—"}</dd></div>)}
      </dl>
      <p className="rx-note">Edit these in <strong>Debt terms</strong> (gearing, DSCR, rate, tenor) or <strong>Bankability</strong> (sizing, lender case, period rates and targets, fees, reserve).</p>

      <h4 className="rcm-h4">Evidence from the last Run <span className="rcm-badge rcm-badge-derived">DERIVED · READ ONLY</span></h4>
      <dl className="rcm-facts" data-financing-evidence="true">
        {studio.financing_evidence.metrics.map((m) => <Metric key={m.label} m={m} />)}
      </dl>

      <h4 className="rcm-h4">Not released</h4>
      <ul className="rcm-closed" data-financing-closed="true">
        {(studio.capital_stack.unsupported ?? []).map((u) => <li key={u.name}><strong>{u.name}</strong> — {u.reason}</li>)}
      </ul>
    </section>
  );
}

function FacilityCard({ row }: { row: CapitalStackRow }) {
  return (
    <article className="rcm-facility" data-facility={row.name}>
      <header><strong>{row.name}</strong> <span className="rcm-badge">{row.status}</span></header>
      <dl className="rcm-facts">
        <div><dt>Type · rank</dt><dd>{row.type} · {row.rank}</dd></div>
        <div><dt>Commitment</dt><dd>{num(row.commitment_keur)} kEUR ({row.currency})</dd></div>
        <div><dt>Interest</dt><dd>{row.rate_type} {row.rate_pct.toFixed(2)}% · {row.day_count}</dd></div>
        <div><dt>Repayment</dt><dd>{row.repayment} · grace {row.grace_months} months</dd></div>
        <div><dt>Maturity</dt><dd>{row.maturity_date}</dd></div>
        <div><dt>Fees</dt><dd>Upfront {row.upfront_pct.toFixed(2)}% · commitment {row.commitment_fee_pct.toFixed(2)}%</dd></div>
      </dl>
      <table className="rcm-table rcm-draws"><thead><tr><th scope="col" className="rcm-left">Drawdown date</th><th scope="col">Amount (kEUR)</th></tr></thead>
        <tbody>{row.draws.map((d) => <tr key={d.date}><td className="rcm-left">{d.date}</td><td>{num(d.amount_keur)}</td></tr>)}
          <tr className="is-base"><td className="rcm-left">Total drawn</td><td>{num(row.draws_total_keur)}</td></tr></tbody></table>
    </article>
  );
}

/** Senior facilities: the Two-Senior capital stack exactly as the canonical projection reports it (read-only here). */
export function CapitalStackView({ studio, legacyUrl }: { studio: FinancingStudioPayload; legacyUrl: string }) {
  const stack = studio.capital_stack;
  return (
    <section className="rx-card rcm-fin" data-capital-stack="true" aria-labelledby="rcm-fin-cs">
      <h3 id="rcm-fin-cs" className="rcm-h3">Senior facilities <span className="rcm-badge">{stack.status ?? "UNAVAILABLE"}</span></h3>
      {!stack.available ? <p className="rx-empty" role="status" data-capital-stack-reason="true">{stack.reason}</p> : (
        <>
          <p className="rx-note" data-stack-priority="true">{stack.debt_service_priority} {studio.multisenior.active ? "The two-Senior configuration is ACTIVE and owns rates, fees, repayment and maturity." : "No two-Senior configuration is active: the single-Senior terms apply."}</p>
          {stack.working && <p className="rx-note" data-stack-working="true">{stack.working.facility_count} facilit{stack.working.facility_count === 1 ? "y" : "ies"} · commitments {num(stack.working.senior_commitments_keur)} kEUR · scheduled draws {num(stack.working.scheduled_draws_keur)} kEUR · {stack.working.reconciled ? "draws reconcile to commitments" : "draws do NOT reconcile to commitments"}</p>}
          <div className="rcm-facilities">{(stack.rows ?? []).map((row) => <FacilityCard key={row.instrument_id} row={row} />)}</div>
        </>
      )}
      <p className="rx-note" data-stack-editor-state="not-released">
        <strong>Editing facilities is NOT RELEASED in this view.</strong> The Two-Senior proposal and its digest-bound activation are edited in the classic workbook
        (<a href={legacyUrl}>Legacy workbook ↗</a>); this page shows exactly what is saved and what the last Run used.
      </p>
      <h4 className="rcm-h4">Not released</h4>
      <ul className="rcm-closed">{(stack.unsupported ?? []).map((u) => <li key={u.name}><strong>{u.name}</strong> — {u.reason}</li>)}</ul>
    </section>
  );
}

const rowValue = (v: SuRow | number | string | null | undefined): string =>
  v && typeof v === "object" ? v.display : v === null || v === undefined ? "—" : String(v);

function SuTable({ title, rows, total }: { title: string; rows: SuRow[]; total: SuRow | number | string | null | undefined }) {
  return (
    <table className="rcm-table rcm-su" data-su-table={title}>
      <thead><tr><th scope="col" className="rcm-left">{title}</th><th scope="col">kEUR</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.label}><td className="rcm-left">{r.label}{r.value === null && r.reason && <span className="rcm-reason">{r.reason}</span>}</td><td className="rcm-num">{r.display}</td></tr>
        ))}
        <tr className="is-base"><td className="rcm-left">Total {title.toLowerCase()}</td><td className="rcm-num">{rowValue(total)}</td></tr>
      </tbody>
    </table>
  );
}

/** Sources & uses of the committed Last Run (never the Working Copy), with its freshness and balance status. */
export function SourcesUsesPanel({ studio }: { studio: FinancingStudioPayload }) {
  const su = studio.sources_uses;
  const view: SourcesUsesView | undefined = su.view;
  return (
    <section className="rx-card rcm-fin" data-sources-uses="true" aria-labelledby="rcm-fin-su">
      <h3 id="rcm-fin-su" className="rcm-h3">Sources &amp; uses <span className="rcm-badge rcm-badge-derived">LAST RUN · {FRESH[view?.freshness ?? studio.freshness] ?? studio.freshness} · READ ONLY</span></h3>
      {!su.available || !view ? <p className="rx-empty" role="alert" data-su-unavailable="true">{su.reason}</p> : !view.has_financing_evidence ? (
        <p className="rx-empty" role="status" data-su-empty="true">No committed Run with financing evidence yet. Run the model to see sources and uses; nothing is estimated from the current inputs.</p>
      ) : (
        <>
          {view.freshness === "STALE" && <p className="rx-banner rx-banner-stale" role="status">STALE — these are the prior Run&rsquo;s sources and uses, not the current inputs.</p>}
          <div className="rcm-grid2">
            <SuTable title="Sources" rows={view.sources ?? []} total={view.total_sources} />
            <SuTable title="Uses" rows={view.uses ?? []} total={view.total_uses} />
          </div>
          <p className="rx-note" data-su-balance="true">Balance: {view.balance_status ?? "—"} · residual {rowValue(view.residual)} · integrity {view.integrity ?? "—"}</p>
        </>
      )}
      <p className="rx-note">Derived from the committed Run&rsquo;s persisted financing evidence. Editing happens in Debt terms and Bankability.</p>
    </section>
  );
}
