import { useEffect, useState, type ReactNode } from "react";
import "../../styles/rcm-credit.css";
import { fetchCreditDecision, fetchHeadroom, type HeadroomPayload } from "./api";
import type { CreditCell, CreditData, CreditFinding, CreditPayload, CreditRunView, Dict } from "./types";

const CLASS_LABEL: Record<string, string> = {
  CONTRACTUAL_COVENANT: "Contractual", PROJECT_INPUT_ADVISORY: "Advisory", OBSERVED_FINANCIAL_RESULT: "Observed", UNSUPPORTED_EVIDENCE_MISSING: "Not supported",
};
const label = (value: string | null | undefined) => (value ?? "").replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase());

/** A server-formatted figure.  A value the Run did not persist reads "Not available" with its reason — never zero. */
function Cell({ c, why = true }: { c: CreditCell | null | undefined; why?: boolean }) {
  if (!c) return <span className="cd-na">Not available</span>;
  if (c.v === null || c.v === undefined) return <><span className="cd-na">{c.d || "Not available"}</span>{why && c.reason && <span className="cd-why"> {c.reason}</span>}</>;
  return <>{c.d}</>;
}

function Table({ head, children, caption, testid }: { head: ReactNode; children: ReactNode; caption: string; testid?: string }) {
  return (
    <div className="cd-scroll" tabIndex={0} role="region" aria-label={caption}>
      <table className="cd-table" data-testid={testid}><caption className="sr-only">{caption}</caption><thead>{head}</thead><tbody>{children}</tbody></table>
    </div>
  );
}

function RunHeads({ runs, first = "Item" }: { runs: CreditRunView[]; first?: string }) {
  return <tr><th scope="col">{first}</th>{runs.map((r, i) => <th scope="col" key={i}>Run {i + 1} · {r.identity.scenario}</th>)}</tr>;
}

function Row({ name, runs, render }: { name: string; runs: CreditRunView[]; render: (r: CreditRunView) => ReactNode }) {
  return <tr><th scope="row">{name}</th>{runs.map((r, i) => <td key={i} className="cd-num">{render(r)}</td>)}</tr>;
}

function Identities({ data }: { data: CreditData }) {
  const runs = data.runs;
  return (
    <section className="cd-section" data-credit-identities="true" aria-label="Selected Runs">
      <h3 className="rcm-h3">Selected Runs</h3>
      <Table caption="Selected Runs" head={<tr><th scope="col">Run</th>{runs.map((_, i) => <th scope="col" key={i}>{i === 0 && runs.length > 1 ? "Reference · " : ""}Run {i + 1}</th>)}</tr>}>
        <tr><th scope="row">Status</th>{runs.map((r, i) => <td key={i} data-credit-run-state={r.identity.state}>{label(r.identity.state)}</td>)}</tr>
        <tr><th scope="row">Scenario</th>{runs.map((r, i) => <td key={i}>{r.identity.scenario}</td>)}</tr>
        <tr><th scope="row">Ran at</th>{runs.map((r, i) => <td key={i}>{r.identity.ran_at}</td>)}</tr>
        <tr><th scope="row">Model integrity</th>{runs.map((r, i) => <td key={i}>{r.identity.integrity}{r.identity.committed_with_integrity_failure && <> — <strong>failure state, not a bankable scenario</strong></>}</td>)}</tr>
      </Table>
      <details className="rcm-audit" data-credit-advanced="true">
        <summary>Advanced details / audit trail</summary>
        <Table caption="Run identities" head={<tr><th scope="col">Identity</th>{runs.map((_, i) => <th scope="col" key={i}>Run {i + 1}</th>)}</tr>}>
          <tr><th scope="row">Run id</th>{runs.map((r, i) => <td key={i}><code>{r.identity.history_id}</code></td>)}</tr>
          <tr><th scope="row">Snapshot</th>{runs.map((r, i) => <td key={i}><code>{r.identity.snapshot_id}</code></td>)}</tr>
          <tr><th scope="row">Input fingerprint</th>{runs.map((r, i) => <td key={i}><code>{String(r.identity.composite_hash || "").slice(0, 12)}</code></td>)}</tr>
          <tr><th scope="row">Engine</th>{runs.map((r, i) => <td key={i}>{r.identity.engine_version || "Not available"}</td>)}</tr>
        </Table>
      </details>
    </section>
  );
}

function Structure({ data }: { data: CreditData }) {
  const runs = data.runs;
  const s = (r: CreditRunView): Dict => r.structure;
  return (
    <section className="cd-section" data-credit-section="structure" aria-labelledby="cd-a-h">
      <h3 className="rcm-h3" id="cd-a-h">Financing structure <small>from the committed Run</small></h3>
      <Table caption="Financing structure" head={<RunHeads runs={runs} />}>
        <tr><th scope="row">Evidence</th>{runs.map((r, i) => <td key={i}>{label(s(r).state)}{s(r).reason ? ` — ${s(r).reason}` : ""}</td>)}</tr>
        <tr><th scope="row">Financing authority</th>{runs.map((r, i) => <td key={i}>{s(r).sizing_note}</td>)}</tr>
        <Row name="Senior commitment (actual)" runs={runs} render={(r) => <><Cell c={s(r).commitment} /><br /><small>{s(r).commitment_label}</small></>} />
        <Row name="Requested gearing cap (Run)" runs={runs} render={(r) => <Cell c={s(r).requested_gearing} />} />
        <Row name="Actual gearing" runs={runs} render={(r) => <Cell c={s(r).actual_gearing} />} />
        <Row name="Total uses · sources" runs={runs} render={(r) => <><Cell c={s(r).total_uses} why={false} /> · <Cell c={s(r).total_sources} why={false} /></>} />
        <Row name="Equity (share capital and other)" runs={runs} render={(r) => <Cell c={s(r).equity_sources} />} />
        <Row name="Shareholder loan cash" runs={runs} render={(r) => <Cell c={s(r).shl_cash} />} />
        <tr><th scope="row">Debt tenor (observed)</th>{runs.map((r, i) => (
          <td key={i}><Cell c={s(r).tenor?.first_debt_service_date} why={false} /> → <Cell c={s(r).tenor?.last_debt_service_date} why={false} /> · <Cell c={s(r).tenor?.debt_service_periods} why={false} /> periods
            <br /><small>Contractual maturity: <Cell c={s(r).tenor?.contractual_maturity_date} why={false} /> — {s(r).tenor?.basis}</small></td>))}</tr>
        <tr><th scope="row">Interest policy (observed)</th>{runs.map((r, i) => (
          <td key={i}>Day count <Cell c={s(r).interest?.day_count} why={false} /> · all-in rate <Cell c={s(r).interest?.annual_rate_min} why={false} /> – <Cell c={s(r).interest?.annual_rate_max} why={false} /><br /><small>{s(r).interest?.basis}</small></td>))}</tr>
        <Row name="Fees and capitalised interest (kEUR)" runs={runs} render={(r) => <>Commitment <Cell c={s(r).fees?.commitment_fee} why={false} /><br />Structuring <Cell c={s(r).fees?.structuring_fee} why={false} /><br />Interest during construction <Cell c={s(r).fees?.capitalized_idc} why={false} /></>} />
        <Row name="Debt service reserve" runs={runs} render={(r) => <>Initial funding <Cell c={s(r).reserve?.initial_dsra_funding} why={false} /><br />Peak balance <Cell c={s(r).reserve?.dsra_peak_balance} why={false} /><br />Policy: <Cell c={s(r).reserve?.regime} /><br /><small>{s(r).reserve?.dsrf_note}</small></>} />
        <tr data-testid="cd-lender-case"><th scope="row">Lender case (P50 / P90)</th>{runs.map((r, i) => <td key={i}><Cell c={s(r).lender_case?.value} /><br /><small>{s(r).lender_case?.operating_case}<br />{s(r).lender_case?.credit_case}</small></td>)}</tr>
        <tr><th scope="row">Sizing method</th>{runs.map((r, i) => <td key={i}><Cell c={s(r).sizing_mode?.value} /><br /><small>{s(r).sizing_mode?.note}</small></td>)}</tr>
        <tr><th scope="row">Senior at contractual maturity</th>{runs.map((r, i) => <td key={i}><Cell c={s(r).maturity?.status} why={false} /></td>)}</tr>
      </Table>
      {runs.map((r, i) => (s(r).facilities?.length ? (
        <div key={i}><h4 className="rcm-h4">Facilities — Run {i + 1}</h4>
          <Table caption={`Facilities of Run ${i + 1}`} testid="cd-facilities"
                 head={<tr><th scope="col">Facility</th><th scope="col">Role</th><th scope="col">Commitment</th><th scope="col">Construction draws</th><th scope="col">Interest during construction</th><th scope="col">Upfront fee</th><th scope="col">Commitment fee</th><th scope="col">Draw state</th></tr>}>
            {(s(r).facilities as Dict[]).map((f, k) => (
              <tr key={k}><th scope="row">{f.id}</th><td>{f.role}</td><td className="cd-num">{f.commitment?.d}</td><td className="cd-num">{f.drawn?.d}</td><td className="cd-num">{f.idc?.d}</td>
                <td className="cd-num">{f.upfront_fee?.d}</td><td className="cd-num">{f.commitment_fee?.d}</td><td>{label(f.draw_state)}</td></tr>))}
          </Table></div>
      ) : s(r).instrument_note ? <p key={i} className="cd-note">Run {i + 1}: {s(r).instrument_note}</p> : null))}
      {data.working_proposal && (
        <aside className="cd-aside" data-testid="cd-working-proposal"><h4 className="rcm-h4">Working financing proposal (not committed evidence)</h4>
          {data.working_proposal.available
            ? <p>Two-Senior / facility proposal: {data.working_proposal.saved_only ? <strong>saved only — not active</strong> : data.working_proposal.active_in_working_copy ? <strong>active in the project</strong> : "none saved"}. {data.working_proposal.note}</p>
            : <p>{data.working_proposal.reason}</p>}
        </aside>
      )}
    </section>
  );
}

function Capacity({ data }: { data: CreditData }) {
  const runs = data.runs;
  const c = (r: CreditRunView): Dict => r.capacity;
  return (
    <section className="cd-section" data-credit-section="capacity" aria-labelledby="cd-b-h">
      <h3 className="rcm-h3" id="cd-b-h">Debt capacity and debt service <small>committed values; a missing constraint is never reconstructed</small></h3>
      <Table caption="Debt capacity and debt service" head={<RunHeads runs={runs} first="Metric" />}>
        <Row name="Actual Senior commitment (kEUR)" runs={runs} render={(r) => <Cell c={r.structure.commitment} />} />
        <Row name="DSCR debt capacity (kEUR)" runs={runs} render={(r) => <Cell c={c(r).dscr_debt_capacity} />} />
        <Row name="Gearing debt capacity (kEUR)" runs={runs} render={(r) => <Cell c={c(r).gearing_debt_capacity} />} />
        <tr data-testid="cd-binding"><th scope="row">Binding Senior constraint</th>{runs.map((r, i) => <td key={i}><Cell c={c(r).binding_constraint} /></td>)}</tr>
        <tr><th scope="row">Solver result</th>{runs.map((r, i) => <td key={i}><Cell c={c(r).convergence?.termination_reason} />{c(r).convergence?.authoritative != null && <> · authoritative: {c(r).convergence.authoritative ? "yes" : "no"}</>}<br /><small>{c(r).convergence?.note}</small></td>)}</tr>
        <Row name="Minimum · average DSCR" runs={runs} render={(r) => <><Cell c={c(r).min_dscr} why={false} /> · <Cell c={c(r).avg_dscr} why={false} /></>} />
        <Row name="Sizing target DSCR" runs={runs} render={(r) => <Cell c={c(r).target_dscr} />} />
        <Row name="Minimum LLCR" runs={runs} render={(r) => <Cell c={c(r).min_llcr} />} />
        <Row name="Σ Senior principal (kEUR)" runs={runs} render={(r) => <Cell c={c(r).principal_total} />} />
        <Row name="Σ Senior interest (kEUR)" runs={runs} render={(r) => <Cell c={c(r).interest_total} />} />
        <Row name="Σ Senior debt service (kEUR)" runs={runs} render={(r) => <Cell c={c(r).debt_service_total} />} />
        <Row name="Σ cash available: base · lender case (kEUR)" runs={runs} render={(r) => <><Cell c={c(r).base_cfads_total} why={false} /> · <Cell c={c(r).bank_cfads_total} why={false} /></>} />
        <tr><th scope="row">Tightest debt-service periods</th>{runs.map((r, i) => (
          <td key={i}>{(c(r).tightest as Dict[] | undefined)?.length
            ? (c(r).tightest as Dict[]).map((t, k) => <div key={k}>Period {t.period_index} {t.date ?? ""}: {t.dscr?.d} (target {t.target?.d})</div>)
            : <span className="cd-na">Not available</span>}</td>))}</tr>
      </Table>
      <p className="cd-note">Σ rows are presentation sums of the committed period values (the scheduled Senior-debt periods of each Run). They are not new financial outputs.</p>
    </section>
  );
}

function Timeline({ data }: { data: CreditData }) {
  return (
    <section className="cd-section" data-credit-section="timeline" aria-labelledby="cd-c-h">
      <h3 className="rcm-h3" id="cd-c-h">Credit-risk timeline <small>committed period values</small></h3>
      {data.runs.map((r, i) => (
        <div key={i}>
          <h4 className="rcm-h4">Run {i + 1} · {r.identity.scenario} · {label(r.identity.state)}</h4>
          {r.timeline.available ? (
            <>
              <div className="cd-scroll cd-matrix" tabIndex={0} role="region" aria-label={`Credit-risk timeline of Run ${i + 1}`}>
                <table className="cd-table cd-table--matrix" data-testid="cd-timeline">
                  <thead><tr><th scope="col" className="cd-sticky">Metric</th>{r.timeline.columns.map((col) => <th scope="col" key={col.index}>P{col.index}<br /><small>{col.date ?? ""}</small></th>)}</tr></thead>
                  <tbody>{r.timeline.rows.map((row) => (
                    <tr key={row.key} data-row={row.key}><th scope="row" className="cd-sticky">{row.label}</th>
                      {row.cells.map((cell, k) => <td key={k} className={`cd-num${cell.v === null ? " cd-na" : ""}${row.kind === "flag" && cell.v ? " cd-flag" : ""}`} title={cell.reason || undefined}>{cell.d}</td>)}</tr>))}</tbody>
                </table>
              </div>
              <p className="cd-note">{r.timeline.basis}</p>
            </>
          ) : <p className="cd-note" data-testid="cd-timeline-unavailable">{r.timeline.reason}</p>}
        </div>
      ))}
    </section>
  );
}

function Comparison({ data }: { data: CreditData }) {
  const cmp = data.comparison;
  const runs = data.runs;
  return (
    <section className="cd-section" data-credit-section="comparison" aria-labelledby="cd-d-h">
      <h3 className="rcm-h3" id="cd-d-h">Scenario comparison <small>committed Runs only</small></h3>
      {!cmp.available ? <p className="cd-note" data-testid="cd-compare-unavailable">{cmp.reason}</p> : (
        <>
          {(cmp.notes as string[] | undefined)?.map((n, i) => <p key={i} className="cd-callout" role="note">{n}</p>)}
          <div className="cd-scroll" tabIndex={0} role="region" aria-label="Scenario comparison">
            <table className="cd-table"><caption className="sr-only">Scenario comparison</caption>
              <thead><tr><th scope="col">Metric</th>{runs.map((r, i) => (
                <FragmentCols key={i} head={<>{i === 0 ? "Reference · " : ""}{r.identity.scenario}<br /><small>{label(r.identity.state)}</small></>} delta={i > 0} />))}</tr></thead>
              {(cmp.groups as Dict[]).map((g, gi) => (
                <tbody key={gi}><tr className="cd-group"><th scope="rowgroup" colSpan={1 + runs.length * 2 - 1}>{g.title}</th></tr>
                  {(g.rows as Dict[]).map((row) => (
                    <tr key={row.key} data-testid={`cd-cmp-${row.key}`}><th scope="row">{row.label}</th>
                      {(row.cells as CreditCell[]).map((c, k) => (
                        <FragmentCells key={k} cell={c} delta={k > 0 ? row.deltas?.[k] : undefined} showDelta={k > 0} />))}</tr>))}
                </tbody>))}
            </table>
          </div>
          <p className="cd-note">{cmp.basis}</p>
          {(cmp.f3 as Dict[] | undefined)?.map((f, i) => (
            <aside key={i} className="cd-aside" data-testid="cd-f3"><h4 className="rcm-h4">Debt capacity rose while revenue fell — {f.scenario}</h4>
              <p>Revenue {f.revenue_change?.d} kEUR · Senior commitment {f.commitment_change?.d} kEUR · attribution: <strong>{label(f.attribution)}</strong></p><p>{f.statement}</p></aside>))}
        </>
      )}
    </section>
  );
}
function FragmentCols({ head, delta }: { head: ReactNode; delta: boolean }) {
  return <><th scope="col">{head}</th>{delta && <th scope="col" className="cd-delta">Change vs reference</th>}</>;
}
function FragmentCells({ cell, delta, showDelta }: { cell: CreditCell; delta: { d?: string } | null | undefined; showDelta: boolean }) {
  return <><td className="cd-num"><Cell c={cell} why={false} /></td>{showDelta && <td className="cd-num cd-delta">{delta?.d ?? "—"}</td>}</>;
}

function LenderScreening({ data }: { data: CreditData }) {
  const v4 = data.credit_v4;
  if (!v4) return null;
  const cmp = v4.period_comparison as Dict | undefined;
  return (
    <section className="cd-section" data-credit-section="screening" aria-labelledby="cd-e-h">
      <h3 className="rcm-h3" id="cd-e-h">Lender risk evidence <small>observed committed Runs only — not an approval</small></h3>
      <p className="cd-note">This screening compares saved DSCR and period evidence. A converged solver cannot prove debt feasibility, and an observed 1.0x threshold is not a negotiated covenant.</p>
      <Table caption="Committed Run risk quality" testid="cd-v4-run-risk"
             head={<tr><th scope="col">Run</th><th scope="col">Screening</th><th scope="col">Model integrity</th><th scope="col">Minimum DSCR</th><th scope="col">Debt periods</th><th scope="col">Missing / invalid</th><th scope="col">Observed shortfalls</th></tr>}>
        {(v4.run_risks as Dict[]).map((r, i) => (
          <tr key={i}><th scope="row">{r.scenario} · {label(r.state)}</th>
            <td><strong>{label(r.status)}</strong>{(r.reasons as string[] | undefined)?.map((x, k) => <div key={k}><small>{label(x)}</small></div>)}</td>
            <td>{r.integrity || "Not available"}</td><td className="cd-num">{r.min_dscr}</td><td className="cd-num">{r.period_count}</td>
            <td className="cd-num">{r.missing_count}{(r.missing_reasons as string[] | undefined)?.map((w, k) => <div key={k}><small>{w}</small></div>)}</td>
            <td>{(r.bad_period_dates as string[] | undefined)?.length ? (r.bad_period_dates as string[]).join(", ") : "None identified; not a credit pass"}</td></tr>))}
      </Table>
      <p className="cd-note">An unavailable DSCR, a missing period, failed or incomplete model integrity or a shortfall means <strong>review required</strong>. “No shortfall identified” is an observed screening outcome, not a lender approval, compliance finding or default determination.</p>
      <h3 className="rcm-h3">Period differences between Runs <small>exact committed dates, never ordinal alignment</small></h3>
      {!cmp?.available ? <p className="cd-note" data-testid="cd-v4-compare-unavailable">Not available — {cmp?.reason}</p> : (
        <>
          <p className="cd-note">{cmp.common_periods} identical period-end dates · {cmp.changed} changed cells · {cmp.unavailable} unavailable cells · {cmp.unchanged} unchanged cells.
            {cmp.not_comparable_count ? ` ${cmp.not_comparable_count} shared period-end date(s) are not comparable (period start differs or is not committed); they are excluded, not inferred.` : ""}
            {cmp.truncated ? " Showing the first 90 changed or unavailable cells; the complete comparison is not rendered." : ""}</p>
          <Table caption="Date-matched period differences" testid="cd-v4-period-table"
                 head={<tr><th scope="col">Period end</th><th scope="col">Metric</th><th scope="col">Evidence</th>{data.runs.map((r, i) => <FragmentCols key={i} head={<>{i === 0 ? "Reference" : `Run ${i + 1}`}<br /><small>{r.identity.scenario}</small></>} delta={i > 0} />)}</tr>}>
            {(cmp.rows as Dict[]).length ? (cmp.rows as Dict[]).map((row, i) => (
              <tr key={i}><th scope="row">{row.date}</th><td>{row.metric} <small>({row.unit})</small></td><td>{label(row.state)}{row.reason && <small> — {row.reason}</small>}</td>
                {(row.values as string[]).map((amount, k) => <FragmentCells key={k} cell={{ v: amount, d: amount }} delta={k > 0 ? { d: row.deltas?.[k - 1] } : undefined} showDelta={k > 0} />)}</tr>))
              : <tr><td colSpan={9}>No changed or missing date-matched credit cells; unchanged values are not repeated here.</td></tr>}
          </Table>
          <p className="cd-note">{cmp.basis} Differences use stored figures only and do not prove what caused them.</p>
        </>
      )}
      <h3 className="rcm-h3">Lender evidence not available <small>typed financial and contractual gaps</small></h3>
      <Table caption="Unavailable credit policy evidence" head={<tr><th scope="col">Metric / policy</th><th scope="col">Status</th><th scope="col">Missing authority</th></tr>}>
        {(v4.unavailable as Dict[]).map((row, i) => <tr key={i}><th scope="row">{row.metric}</th><td>Not available</td><td>{row.reason}</td></tr>)}
      </Table>
      <p className="cd-note">Contractual covenants, covenant dates, events of default and reserve coverage need source-proven lender documentation and separately approved definitions. Advice and sizing targets never imply contractual compliance.</p>
    </section>
  );
}

function Findings({ data }: { data: CreditData }) {
  const [filter, setFilter] = useState("ALL");
  const rows: CreditFinding[] = filter === "ALL" ? data.findings : data.findings.filter((f) => f.classification === filter);
  const runNo = (id: string) => data.runs.findIndex((r) => r.identity.history_id === id) + 1;
  return (
    <section className="cd-section" data-credit-section="findings" aria-labelledby="cd-f-h">
      <h3 className="rcm-h3" id="cd-f-h">Credit findings <small>deterministic · grounded in committed evidence</small></h3>
      <div className="cd-filters" role="group" aria-label="Filter findings by class">
        <button type="button" className={`cd-chip${filter === "ALL" ? " is-on" : ""}`} aria-pressed={filter === "ALL"} onClick={() => setFilter("ALL")}>All ({data.findings.length})</button>
        {Object.entries(data.finding_counts).map(([k, n]) => (
          <button key={k} type="button" className={`cd-chip${filter === k ? " is-on" : ""}`} aria-pressed={filter === k} onClick={() => setFilter(k)}>{CLASS_LABEL[k] ?? label(k)} ({n})</button>))}
      </div>
      <Table caption="Credit findings" testid="cd-findings"
             head={<tr><th scope="col">Finding</th><th scope="col">Class</th><th scope="col">Status</th><th scope="col">Run · scenario</th><th scope="col">Period</th><th scope="col">Actual</th><th scope="col">Threshold · authority</th><th scope="col">Headroom</th><th scope="col">Evidence</th></tr>}>
        {rows.map((f, i) => (
          <tr key={`${f.id}-${i}`} data-class={f.classification} data-testid="cd-finding" data-finding={f.check_id || f.id.split(":").pop()}>
            <th scope="row">{f.title}{f.severity && f.severity !== "INFORMATION" && <><br /><small>severity {f.severity}</small></>}<br /><small>{f.metric}</small></th>
            <td><span className={`cd-class cd-class--${f.classification.toLowerCase()}`}>{CLASS_LABEL[f.classification] ?? label(f.classification)}</span></td>
            <td>{label(f.status)}</td><td>Run {runNo(f.run_history_id)} · {f.scenario}</td><td>{f.period ?? "—"}</td>
            <td className="cd-num"><Cell c={f.actual} /></td>
            <td className="cd-num"><Cell c={f.threshold} why={false} /><br /><small>{f.threshold_authority}</small></td>
            <td className="cd-num"><Cell c={f.headroom} why={false} /></td>
            <td><small>{f.evidence_source}{f.reason_code ? ` · ${f.reason_code}` : ""}</small>{f.detail && <><br /><small>{f.detail}</small></>}</td></tr>))}
      </Table>
      <dl className="cd-classes">{Object.entries(data.policy.classes).map(([k, text]) => <div key={k}><dt><span className={`cd-class cd-class--${k.toLowerCase()}`}>{CLASS_LABEL[k] ?? label(k)}</span></dt><dd>{text}</dd></div>)}</dl>
      <p className="cd-note">{data.policy.disclosure}</p>
    </section>
  );
}


const THRESHOLDS: ReadonlyArray<{ metric: string; label: string; hint: string }> = [
  { metric: "min_dscr", label: "Minimum Senior DSCR (x)", hint: "for example 1.30" },
  { metric: "min_llcr", label: "Minimum LLCR (x)", hint: "for example 1.40" },
  { metric: "max_gearing", label: "Maximum Senior gearing (fraction)", hint: "0.80 means 80%" },
  { metric: "min_equity_keur", label: "Minimum initial equity (kEUR)", hint: "kEUR" },
  { metric: "max_balloon_keur", label: "Maximum Senior balloon (kEUR)", hint: "kEUR" },
];
const num4 = (v: unknown) => (typeof v === "number" ? v.toLocaleString("en-GB", { maximumFractionDigits: 4 }) : "Not available");

/** Hypothetical lender thresholds against the saved Runs.  Thresholds live only in this form and the request: nothing is saved, solved or run. */
function Headroom({ project, historyIds }: { project: string; historyIds: string[] }) {
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<HeadroomPayload | null>(null);
  const [error, setError] = useState("");
  const any = Object.values(inputs).some((v) => v.trim() !== "");

  async function evaluate() {
    setBusy(true); setError("");
    const r = await fetchHeadroom(project, historyIds, inputs);
    if (r.ok) setResult(r); else { setResult(null); setError(r.message ?? "The headroom could not be evaluated."); }
    setBusy(false);
  }
  const runs = (result?.data?.runs ?? []) as Dict[];
  return (
    <section className="cd-section" data-credit-section="headroom" aria-labelledby="cd-h-h">
      <h3 className="rcm-h3" id="cd-h-h">Covenant headroom <small>hypothetical thresholds — not contractual compliance or approval</small></h3>
      <p className="cd-note">Type the thresholds a lender might propose. FINCO measures every period of the saved Run against them. Nothing you type here is saved, and the model is not run.</p>
      <form className="rcm-controls" data-headroom-form="true" onSubmit={(e) => { e.preventDefault(); void evaluate(); }}>
        {THRESHOLDS.map((t) => (
          <label key={t.metric}>{t.label}
            <input type="text" inputMode="decimal" autoComplete="off" placeholder={t.hint} value={inputs[t.metric] ?? ""} data-headroom-input={t.metric}
                   onChange={(e) => setInputs((current) => ({ ...current, [t.metric]: e.target.value }))} />
          </label>
        ))}
        <button type="submit" className="rx-button" data-headroom-evaluate="true" disabled={busy || !any}>{busy ? "Evaluating…" : "Evaluate headroom"}</button>
      </form>
      {error && <p className="rx-empty" role="alert" data-headroom-error="true">{error}</p>}
      {result && !result.data && <p className="rx-empty" role="status">No saved Run to evaluate.</p>}
      {runs.map((run, i) => (
        <div key={i} data-headroom-run={run.history_id}>
          <h4 className="rcm-h4">Run {i + 1} · {run.ran_at} <small>Model checks: {run.integrity}</small></h4>
          {run.integrity !== "PASS" && <p className="cd-callout" role="alert">Review required: the model checks are not proven to pass for this Run.</p>}
          <Table caption={`Headroom of Run ${i + 1}`} testid="cd-headroom-table"
                 head={<tr><th scope="col">Constraint</th><th scope="col">Proposed threshold</th><th scope="col">Smallest headroom</th><th scope="col">Unit</th><th scope="col">Tightest period</th><th scope="col">First breach</th><th scope="col">Breaches</th><th scope="col">Evaluation</th></tr>}>
            {(run.constraints as Dict[]).map((c) => (
              <tr key={c.metric} data-headroom-metric={c.metric}>
                <th scope="row">{label(c.metric)}</th><td className="cd-num">{num4(c.threshold)}</td><td className="cd-num">{num4(c.minimum_headroom)}</td><td>{c.unit}</td>
                <td>{c.worst_period || "Not dated"}</td><td>{c.first_breach || "—"}</td><td className="cd-num">{num4(c.breach_count)}</td>
                <td>{label(c.state)}{c.reason && <span className="cd-why">{label(c.reason).toLowerCase()}</span>}</td>
              </tr>))}
          </Table>
          <details className="rcm-audit"><summary>Period headroom and audit details</summary>
            {(run.constraints as Dict[]).map((c) => (
              <div key={c.metric}><h5 className="rcm-h5">{label(c.metric)}</h5>
                <Table caption={`Period headroom for ${label(c.metric)}`} head={<tr><th scope="col">Period start</th><th scope="col">Period end</th><th scope="col">Value</th><th scope="col">Headroom</th><th scope="col">Relative</th><th scope="col">State</th></tr>}>
                  {(c.observations as Dict[]).map((p, k) => (
                    <tr key={k}><td>{p.start || "—"}</td><td>{p.end || "—"}</td><td className="cd-num">{num4(p.value)}</td><td className="cd-num">{num4(p.absolute)}</td>
                      <td className="cd-num">{typeof p.relative === "number" ? `${num4(p.relative * 100)}%` : "Not available"}</td><td>{label(p.state)}</td></tr>))}
                </Table></div>))}
            <p className="cd-note">Run record {run.snapshot_id} · saved inputs version {String(run.composite_hash || "").slice(0, 12)} · model {run.engine_version}. Historical results are not asserted current against the project inputs. Persisted sizing evidence only: a different debt amount needs a new financing solve.</p>
          </details>
        </div>
      ))}
      {(result?.data?.comparisons as Dict[] | undefined)?.length ? (
        <div><h4 className="rcm-h4">Changes against Run 1</h4>
          <Table caption="Changes against Run 1" head={<tr><th scope="col">Run</th><th scope="col">Minimum DSCR change</th><th scope="col">Senior change (kEUR)</th><th scope="col">Debt service change (kEUR)</th><th scope="col">Equity change (kEUR)</th><th scope="col">Comparison</th></tr>}>
            {(result?.data?.comparisons as Dict[]).map((c, i) => (
              <tr key={i}><td>Run {i + 2}</td><td className="cd-num">{num4(c.delta_min_dscr)}</td><td className="cd-num">{num4(c.delta_senior_keur)}</td><td className="cd-num">{num4(c.delta_service_keur)}</td><td className="cd-num">{num4(c.delta_equity_keur)}</td><td>{label(c.state)}</td></tr>))}
          </Table></div>
      ) : null}
    </section>
  );
}

/** Credit decision for one to three committed Runs (Audit A GAP-R12): the evidence the Legacy credit page presents, as saved by the Run.
 *  Read-only: it never starts a Run, writes, recalculates or mixes the current inputs into a saved Run; unavailable is never zero. */
export function CreditDecisionPanel({ project, historyIds, workbookHash }: { project: string; historyIds: string[]; workbookHash: string }) {
  const [open, setOpen] = useState(false);
  const [payload, setPayload] = useState<CreditPayload | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const key = historyIds.join("|");

  useEffect(() => {
    if (!open) return undefined;
    const controller = new AbortController();
    setBusy(true); setError(null);
    void fetchCreditDecision(project, historyIds, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (result.ok) setPayload(result); else { setPayload(null); setError({ code: result.code, message: result.message ?? "The credit evidence could not be read." }); }
      setBusy(false);
    }).catch(() => { /* effect cancelled */ });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, project, key, workbookHash]);

  const tooMany = historyIds.length > 3;
  return (
    <section className="rx-card rcm-fin cd-panel" data-credit-decision="true" aria-labelledby="cd-title">
      <h2 id="cd-title" className="rcm-h3">Credit decision <span className="rcm-badge rcm-badge-derived">SAVED RUN EVIDENCE · READ ONLY</span></h2>
      <p className="rx-note">How much debt do the saved Runs support, which constraints bind, where is debt service tight and how does credit change across scenarios? Every figure is stored by a saved Run — nothing is recalculated here. This is decision intelligence, not lender certification.</p>
      {!open ? (
        <button type="button" className="rx-button rx-button-secondary" data-credit-open="true" disabled={tooMany}
                onClick={() => setOpen(true)}>{historyIds.length ? `Review credit decision for ${historyIds.length} selected Run${historyIds.length > 1 ? "s" : ""}` : "Review credit decision for the Last Run"}</button>
      ) : (
        <>
          {busy && !payload && <p className="rx-boot-loading" role="status" data-credit-loading="true">Reading the saved Run evidence…</p>}
          {error && <p className="rx-empty" role="alert" data-credit-unavailable={error.code}>{error.message}</p>}
          {payload && !payload.data && <p className="rx-empty" role="status" data-credit-no-run="true">No saved Run yet. Run the model to create credit evidence; nothing is estimated here.</p>}
          {payload?.data && (
            <div data-credit-ready="true" data-credit-runs={payload.data.runs.length}>
              <p className="cd-policy" data-testid="cd-policy">{payload.data.policy.failed_runs}</p>
              <nav className="cd-toc" aria-label="Credit decision sections"><a href="#cd-a-h">Financing structure</a><a href="#cd-b-h">Debt capacity</a><a href="#cd-c-h">Timeline</a><a href="#cd-d-h">Scenario comparison</a><a href="#cd-e-h">Lender risk evidence</a><a href="#cd-f-h">Findings</a><a href="#cd-h-h">Covenant headroom</a></nav>
              <Identities data={payload.data} />
              <Structure data={payload.data} />
              <Capacity data={payload.data} />
              <Timeline data={payload.data} />
              <Comparison data={payload.data} />
              <LenderScreening data={payload.data} />
              <Findings data={payload.data} />
              <Headroom project={project} historyIds={historyIds} />
            </div>
          )}
        </>
      )}
      {tooMany && <p className="rx-note" role="status">Select at most three Runs to review their credit decision.</p>}
    </section>
  );
}
