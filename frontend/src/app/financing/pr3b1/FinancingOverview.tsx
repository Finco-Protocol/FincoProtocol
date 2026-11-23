import { useState } from 'react';
import { isUnconfiguredFacility, unsupportedReason } from '../facilityState';
import type { SuRow } from '../types';
import type { CreditFinding } from '../../credit/types';
import { checkRunEvidence } from './runEvidence';
import { termSheetModel, creditTerm, type Term } from './termSheetModel';
import { sourcesUsesModel } from './sourcesUsesModel';
import { coverageModel } from './coverageModel';
import { DebtProvenance } from './DebtProvenance';
import { debtProvenance } from './debtProvenanceModel';
import type { Evidence } from './types';
import './financingOverview.css';

function Terms({ rows }: { rows: Term[] }) {
  return <dl className="pr3b1-values">{rows.map((r, i) => <div key={`${r.label}-${i}`}>
    <dt>{r.label}</dt><dd>{r.display}<small title={r.source}>{r.source.startsWith('Working') ? 'Working Copy' : r.source.startsWith('Contract') ? 'Contract limitation' : 'Last Run'}{r.reason ? ` · ${r.reason}` : ''}</small></dd>
  </div>)}</dl>;
}
const amount = (r: SuRow): Term => ({ label: r.label, display: r.value == null ? 'NOT AVAILABLE' : r.display, source: r.authority, reason: r.reason });
const number = (v: unknown): string => typeof v === 'number' && Number.isFinite(v) ? String(v) : 'NOT AVAILABLE';
function Findings({ rows }: { rows: CreditFinding[] }) {
  return rows.length ? <ul className="pr3b1-findings">{rows.map((f, i) => <li key={`${f.id}-${i}`}>
    <strong>{f.severity || f.status} · {f.title}</strong><span>{f.classification} · {f.metric}</span>
    {f.actual && <span>{f.actual.d}</span>}<small>{f.detail || f.reason_code}</small>
  </li>)}</ul> : <p>No findings supplied in these server classifications.</p>;
}
/** Presentation-only overview mounted by the existing Financing workspace. */
export function FinancingOverview({ evidence: e, onReload, onHistoryChange, onOpenExisting, embedded = false }: {
  evidence: Evidence; onReload: () => void; onHistoryChange?: (historyId: string) => void; onOpenExisting?: (view: string) => void; embedded?: boolean;
}) {
  const gate = checkRunEvidence(e), groups = termSheetModel(e, gate), su = sourcesUsesModel(e, gate), cov = coverageModel(e, gate);
  const s = e.studio, r = gate.showRun ? e.credit.data?.runs[0] : undefined, dm = cov?.debtMetrics;
  const selected = gate.showRun ? s.selected_run?.view : undefined;
  const debt = debtProvenance(e);
  const runName = gate.state === 'HISTORICAL' ? 'Historical selected Run' : 'Last Run';
  const facilities = (s.capital_stack.rows ?? []).filter(f => !isUnconfiguredFacility(f));
  const [facilityId, setFacilityId] = useState('');
  const facility = facilities.find(f => f.instrument_id === facilityId) ?? facilities[0];
  const link = (id: string) => `?${new URLSearchParams({ project: e.scope.project, ...(e.scope.historyId ? { dm_run: e.scope.historyId } : {}), financing: id })}#financing`;
  return <section className="pr3b1" aria-label="Financing one-screen overview" data-financing-read-layer="true" data-run-state={gate.state} onClick={event => {
    const anchor = (event.target as HTMLElement).closest('a');
    const href = anchor?.getAttribute('href') || '';
    if (!onOpenExisting || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || !href.startsWith('?')) return;
    const view = new URLSearchParams(href.split('#')[0]).get('financing');
    if (view) { event.preventDefault(); onOpenExisting(view); }
  }}>
    <header className="pr3b1-header"><div>{embedded ? <h3>Financing evidence</h3> : <h2>Financing</h2>}<p>Term Sheet · Working Copy and Last Run stay distinct</p></div><button type="button" onClick={onReload}>Reload evidence</button></header>
    <nav className="pr3b1-jumps" aria-label="Financing workspace sections"><a href="#pr3b1-terms">Structure &amp; Terms</a><a href="#pr3b1-funding">Facilities / Funding</a><a href="#pr3b1-run">Last Run</a><a href="#pr3b1-quality">Quality / diagnostics</a></nav>
    {e.credit.history_rows.length > 0 && <label className="pr3b1-history">Run history <select aria-label="Run history" value={e.credit.data?.runs[0]?.identity?.history_id ?? ''}
      disabled={!onHistoryChange} onChange={ev => onHistoryChange?.(ev.target.value)}>{e.credit.history_rows.map(h => <option key={h.history_id} value={h.history_id}>{h.is_last ? 'Last Run' : 'Historical'} · {h.scenario} · {h.ran_at}</option>)}</select></label>}
    <div className={`pr3b1-state pr3b1-state-${gate.state.toLowerCase()}`} role="status"><strong>{gate.state}</strong> · {gate.reason.replace(/^(CURRENT|STALE|HISTORICAL|NOT_RUN)\s+—\s+/, '')}
      {r && <small>{runName} · {r.identity.scenario} · {r.identity.ran_at} · snapshot {r.identity.snapshot_id}</small>}
      {gate.showRun && <small>Selected committed history source identity verified; Studio/credit cross-view assurance remains MITIGATED_NOT_PROVEN.</small>}
    </div>
    <div className="pr3b1-main">
      <article className="pr3b1-sheet" id="pr3b1-terms"><h3>Structure &amp; Terms <small>Working Copy</small></h3><details open={!embedded}><summary>Saved terms and source notes</summary><h4>Term Sheet</h4><small>Working Copy model values are informational.</small>
        <div className="pr3b1-term-groups">{groups.filter(g => g.label !== 'Sponsor').map(g => <details open={g.label === 'Size' || g.label === 'Pricing'} key={g.label}><summary>{g.label}</summary>{g.rows.length ? <Terms rows={g.rows} /> : <p>NOT AVAILABLE — no supplied terms.</p>}</details>)}</div>
        </details><p className="pr3b1-editors"><a data-financing-read-link={onOpenExisting ? "true" : undefined} data-financing-tab-button="terms" href={link('terms')}>Open existing Debt terms editor</a> · <a data-financing-read-link={onOpenExisting ? "true" : undefined} data-financing-tab-button="bankability" href={link('bankability')}>Open existing Bankability editor</a></p>
        <p>{s.editable ? 'Existing editors retain their Save and permission checks.' : 'Read-only project.'} Fees {s.editable && s.bankability.fees_editable ? 'editable in Bankability' : 'read-only'} · {s.bankability.available ? 'Bankability available' : s.bankability.reason || 'Bankability NOT AVAILABLE'}</p>
        {s.senior_lock_reason && <p role="note">Locked: {s.senior_lock_reason}</p>}
        <p>Lock-up DSCR and Minimum LLCR are model information, with no new edit or Run-verification claim.</p>
      </article>
      <div id="pr3b1-run" className="pr3b1-run-zones" data-run-zones={gate.showRun ? 'visible' : 'hidden'}>
        {!gate.showRun ? <div className="pr3b1-card"><h3>Last Run evidence</h3><p>{gate.reason}</p><a data-financing-read-link={onOpenExisting ? "true" : undefined} data-financing-tab-button="debt-metrics" href={link('debt-metrics')}>Open Debt metrics / historical evidence</a></div> : <>
          <article className="pr3b1-card" aria-label="Sources & Uses selected Run"><h3>Sources & Uses <small>{runName} · kEUR</small></h3>
            <div className="pr3b1-su-scroll" tabIndex={0} role="region" aria-label="Sources and Uses rows"><h4>Sources</h4><Terms rows={su!.sources.map(amount)} /><h4>Uses</h4><Terms rows={su!.uses.map(amount)} />
            <div className="pr3b1-totals"><Terms rows={su!.totals.map(amount)} /></div></div><p>Balance · {su!.balance} · Integrity · {su!.integrity}</p><small>{su!.note} {su!.reason}</small>
            <p>Saved Sources &amp; Uses: NOT AVAILABLE. No Working Copy reconstruction.</p><a data-financing-read-link={onOpenExisting ? "true" : undefined} data-financing-tab-button="sources-uses" href={link('sources-uses')}>Existing Sources &amp; Uses detail</a>
          </article>
          <article className="pr3b1-card" aria-label="Coverage selected Run"><h3>Repayment, Coverage &amp; Covenants <small>{runName}</small></h3>
            <Terms rows={[creditTerm('Minimum DSCR', cov!.capacity.min_dscr, 'Last Run · capacity.min_dscr'),creditTerm('Average DSCR', cov!.capacity.avg_dscr, 'Last Run · capacity.avg_dscr'),
              creditTerm('Sizing target DSCR', cov!.capacity.target_dscr, 'Last Run · capacity.target_dscr'),creditTerm('Binding constraint', cov!.capacity.binding_constraint, cov!.bindingScope),
              creditTerm('DSCR debt capacity', cov!.capacity.dscr_debt_capacity, runName + ' · capacity.dscr_debt_capacity (kEUR)'),
              creditTerm('Gearing debt capacity', cov!.capacity.gearing_debt_capacity, runName + ' · capacity.gearing_debt_capacity (kEUR)'),
              creditTerm('Observed annual all-in rate · min', r?.structure.interest?.annual_rate_min, runName + ' · sealed annual rate displayed as %')]} />
            <p>Coverage · {dm?.evaluation?.coverage.status || 'UNAVAILABLE'} · {dm?.evaluation?.coverage.message || dm?.evaluation?.coverage.reason || dm?.reason}</p>
            <p>DSRA · {dm?.reserves?.dsra.available ? `Initial funding ${number(dm.reserves.dsra.initial_funding_keur)} kEUR` : dm?.reserves?.dsra.reason || 'NOT AVAILABLE'}</p>
            <p>Run execution, Model Integrity and coverage are independent server verdicts.</p><p>Reserve draw / required target / top-up ledger · UNAVAILABLE — not persisted in this selected Run.</p>
          </article>
        </>}
      </div>
    </div>
    <DebtProvenance evidence={e} />
        <details id="pr3b1-funding"><summary>Facilities / Funding · Working Copy</summary>
          <p>Facility terms are read-only. Sponsor assumptions below are Working Copy; actual cash sources remain in Last Run.</p>
          <p><a data-financing-read-link={onOpenExisting ? "true" : undefined} data-financing-tab-button="facilities" href={link('facilities')}>Open existing facility details</a> · <a data-financing-read-link={onOpenExisting ? "true" : undefined} data-financing-tab-button="investors" href={link('investors')}>Open existing investor agreement</a></p>
          <p>{s.editable ? 'Investor edit availability is checked in the existing agreement editor.' : 'Read-only project.'}</p>
          <h4>Sponsor funding</h4><Terms rows={groups.find(g => g.label === 'Sponsor')!.rows} />
          <p>SHL repayment · {s.sponsor_view.repayment || 'NOT AVAILABLE'} · day count · {s.sponsor_view.day_count || 'NOT AVAILABLE'} · eligibility period · {s.sponsor_view.eligibility ?? 'NOT AVAILABLE'} · maturity period · {s.sponsor_view.maturity ?? 'NOT AVAILABLE'}</p>
          {facility ? <><label>Facility <select aria-label="Facility" value={facility.instrument_id} onChange={ev => setFacilityId(ev.target.value)}>{facilities.map(f => <option key={f.instrument_id} value={f.instrument_id}>{f.name}</option>)}</select></label>
          <Terms rows={[
            { label: facility.name, display: facility.status, source: `Working Copy · ${facility.type} · ${facility.readiness || 'No readiness conclusion'}` },
            { label: 'Recorded facility commitment', display: number(facility.commitment_keur), source: `Working Copy · ${facility.currency} · kEUR; not a distinct Last Run Committed record` },
            { label: 'Repayment', display: facility.repayment || 'NOT AVAILABLE', source: 'Working Copy · facility' },
            { label: 'Maturity', display: facility.maturity_date || 'NOT AVAILABLE', source: 'Working Copy · facility' },
          ]} /></> : <p>NOT AVAILABLE — no configured facility terms supplied.</p>}
          <p>Instrument repayment schedule · UNAVAILABLE — selected Run evidence supplies aggregate Senior periods only. Facility currency and recorded terms are Working Copy; no allocation is inferred.</p>
          <p>Two-Senior is read-only / release gated. Junior unsupported; VAT code-only. No per-tier sizing, draws or binding claim.</p>
          {(s.capital_stack.unsupported ?? []).map((u, i) => <p key={i}>{u.name} · {u.status} · {unsupportedReason(u)}</p>)}
        </details>
    <p><a href="#results">Returns and valuation · existing Results</a></p>
    {!cov && <p id="pr3b1-quality">Quality / diagnostics · Last Run evidence unavailable. {gate.reason}</p>}
    {cov && <>
      <div id="pr3b1-quality" className="pr3b1-verdicts">
        <article className="pr3b1-card"><h3>Model Integrity</h3><strong>{cov.integrity.status || 'UNAVAILABLE'}</strong><ul>{(cov.integrity.failures ?? []).map((f: { id: string; title?: string; reason?: string }) => <li key={f.id}>{f.title || f.id} · {f.reason}</li>)}</ul><Findings rows={cov.integrityFindings} /></article>
        <article className="pr3b1-card"><h3>Financial Bankability</h3><p>{cov.bindingScope}</p><Findings rows={cov.bankabilityFindings} /></article>
        <article className="pr3b1-card"><h3>Covenant Compliance</h3><p>{dm?.contract_terms?.note || dm?.contract_terms?.reason || 'NOT AVAILABLE — contract terms not supplied'}</p>
          <p>EoD · {dm?.evaluation?.eod.status || 'UNAVAILABLE'} · {dm?.evaluation?.eod.message || dm?.evaluation?.eod.reason}</p>
          <p>Covenant · {dm?.evaluation?.covenant.status || 'UNAVAILABLE'} · {dm?.evaluation?.covenant.message || dm?.evaluation?.covenant.reason}</p>
          <p>Period lock-up · {dm?.reserves?.lockup.available ? dm.reserves.lockup.note || 'Recorded period markers below' : dm?.reserves?.lockup.reason || 'NOT AVAILABLE'}</p>
        </article>
      </div>
      {cov.otherFindings.length > 0 && <details><summary>Other server findings · original classifications</summary><Findings rows={cov.otherFindings} /></details>}
      <details open><summary>Outstanding and coverage · native period schedule · {runName}</summary><p><a data-financing-read-link={onOpenExisting ? "true" : undefined} data-financing-tab-button="debt-metrics" href={link('debt-metrics')}>Open existing debt schedule / history</a></p><p>{dm?.axis?.frequency} · {dm?.axis?.note} {dm?.basis_note}</p>
        <small>{debt.source} · {gate.state} · Run {debt.identity?.history_id} · fingerprint {debt.identity?.composite_hash}. Dates are persisted period ends; period starts are unavailable.</small>
        {debt.periods.length ? <div className="pr3b1-scroll" tabIndex={0} role="region" aria-label="Native debt period schedule"><table><thead><tr>{['Period','Opening kEUR','Principal kEUR','Interest kEUR','Service kEUR','Closing kEUR','DSCR (x)','Cash before reserves kEUR','Sizing target (x)','Shortfall kEUR','Below one','EoD breach','Covenant breach','Lock-up'].map(h => <th scope="col" key={h}>{h}</th>)}</tr></thead>
          <tbody>{debt.periods.map(p => <tr key={p.period_index} title={`${debt.source} · period ${p.period_index} · ${p.date}`}><th scope="row">{p.label} · {p.date}</th><td>{number(p.senior_opening_keur)}</td><td>{number(p.principal_keur)}</td><td>{number(p.interest_keur)}</td><td>{number(p.debt_service_keur)}</td><td>{number(p.senior_closing_keur)}</td><td>{number(p.dscr)}</td><td>{number(p.cash_after_senior_keur)}</td><td>{number(p.sizing_target_dscr)}</td><td>{number(p.shortfall_keur)}</td>{[p.below_one,p.eod_breach,p.covenant_breach,p.lockup_active].map((v,i) => <td key={i}>{v == null ? 'NOT AVAILABLE' : v ? 'Yes' : 'No'}</td>)}</tr>)}</tbody></table></div> : <p>UNAVAILABLE · {debt.reason || dm?.reason || 'No native period evidence.'}</p>}
      </details>
      <details><summary>Construction sources, draws and uses · {runName} · kEUR</summary><p>Senior draw is period-specific. No browser aggregate or per-facility allocation.</p>
        <p>Separate FC/COD Senior draw · {selected?.construction.fc_senior_draw.value == null ? 'UNAVAILABLE' : number(selected.construction.fc_senior_draw.value) + ' kEUR'}.</p>
        <p>Construction opening/closing outstanding · UNAVAILABLE — no persisted construction roll-forward.</p>
        {su!.construction.length ? <div className="pr3b1-scroll" tabIndex={0} role="region" aria-label="Construction period evidence"><table><thead><tr><th scope="col">Period</th><th scope="col">Server field</th><th scope="col">kEUR</th><th scope="col">Authority / reason</th></tr></thead><tbody>{su!.construction.flatMap(p => p.fields.map((f,i) => <tr key={`${p.period}-${i}`}><th scope="row">{p.period} · {p.date}</th><td>{f.label}</td><td>{f.value == null ? 'NOT AVAILABLE' : f.display}</td><td>{f.authority} · {f.reason}</td></tr>))}</tbody></table></div> : <p>NOT AVAILABLE — no construction rows supplied.</p>}
      </details>
    </>}
    <details><summary>Evidence and limitations</summary><p>The Studio Last Run Sources &amp; Uses API has no independent snapshot ID. Selected history was bound by a separate backend read, but Studio/credit cross-view assurance stays {gate.assurance}. Individual lender commitments, construction outstanding, reserve draws and benchmark resets are UNAVAILABLE/ENGINE_ONLY.</p><Terms rows={groups.flatMap(g => g.rows).map(t => ({ ...t, display: t.source, source: 'Contract limitation', reason: undefined }))} /></details>
    <details><summary>Additional existing evidence · transition</summary><p><a data-financing-read-link={onOpenExisting ? "true" : undefined} data-financing-tab-button="overview" href={link('overview')}>Open existing detailed financing evidence</a>. Existing editors and output links remain available until the destination coverage is accepted.</p></details>
  </section>;
}
