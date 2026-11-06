import { useState } from 'react';
import { isUnconfiguredFacility, unsupportedReason } from '../facilityState';
import type { SuRow } from '../types';
import type { CreditFinding } from '../../credit/types';
import { checkRunEvidence } from './runEvidence';
import { termSheetModel, creditTerm, type Term } from './termSheetModel';
import { sourcesUsesModel } from './sourcesUsesModel';
import { coverageModel } from './coverageModel';
import type { Evidence } from './types';
import './financingOverview.css';

export const LEGACY_VIEWS = [ ['terms', 'Debt terms'], ['overview', 'Overview'], ['debt-metrics', 'Debt metrics / history'],
  ['bankability', 'Bankability'], ['facilities', 'Senior facilities'], ['sources-uses', 'Sources & uses'], ['investors', 'Investors & sponsor'] ] as const;
function Terms({ rows }: { rows: Term[] }) {
  return <dl className="pr3b1-values">{rows.map((r, i) => <div key={`${r.label}-${i}`}>
    <dt>{r.label}</dt><dd>{r.display}<small>{r.source}{r.reason ? ` · ${r.reason}` : ''}</small></dd>
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
/** Source-only component: mounting is deferred until the shared-bundle owner (#429) merges. */
export function FinancingOverview({ evidence: e, onReload, onHistoryChange }: {
  evidence: Evidence; onReload: () => void; onHistoryChange?: (historyId: string) => void;
}) {
  const gate = checkRunEvidence(e), groups = termSheetModel(e, gate), su = sourcesUsesModel(e, gate), cov = coverageModel(e, gate);
  const s = e.studio, r = gate.showRun ? e.credit.data?.runs[0] : undefined, dm = cov?.debtMetrics;
  const facilities = (s.capital_stack.rows ?? []).filter(f => !isUnconfiguredFacility(f));
  const [facilityId, setFacilityId] = useState('');
  const facility = facilities.find(f => f.instrument_id === facilityId) ?? facilities[0];
  const link = (id: string) => `?${new URLSearchParams({ project: e.scope.project, financing: id })}#financing`;
  const blocks = [
    { label: 'Scalars', path: 'terms', availability: s.senior_lock_reason ? `Locked: ${s.senior_lock_reason}` : s.editable ? 'Existing Debt terms editor' : 'Read-only project' },
    { label: 'Bankability', path: 'bankability', availability: s.bankability.available ? `Existing editor · fees ${s.editable && s.bankability.fees_editable ? 'editable' : 'read-only'}` : s.bankability.reason || 'NOT AVAILABLE' },
    { label: 'Facilities (read-only)', path: 'facilities', availability: s.multisenior.active ? 'Two-Senior · read-only / release gated' : s.capital_stack.reason || 'Existing facility view' },
    { label: 'Investors', path: 'investors', availability: 'Existing agreement editor · access and CAS checked there' },
    { label: 'Valuation (read-only)', path: 'debt-metrics', availability: 'No valuation editor · recorded metrics only' },
  ];
  return <section className="pr3b1" aria-label="Financing one-screen overview" data-run-state={gate.state}>
    <header className="pr3b1-header"><div><h2>Financing</h2><p>Term Sheet · Working Copy and Last Run stay distinct</p></div><button type="button" onClick={onReload}>Reload evidence</button></header>
    <nav className="pr3b1-blocks" aria-label="Existing financing functions">{blocks.map(b => <a key={b.label} href={link(b.path)}><strong>{b.label}</strong><small>{b.availability}</small></a>)}</nav>
    {e.credit.history_rows.length > 0 && <label className="pr3b1-history">Run history <select aria-label="Run history" value={e.credit.data?.runs[0]?.identity.history_id ?? ''}
      disabled={!onHistoryChange} onChange={ev => onHistoryChange?.(ev.target.value)}>{e.credit.history_rows.map(h => <option key={h.history_id} value={h.history_id}>{h.is_last ? 'Last Run' : 'Historical'} · {h.scenario} · {h.ran_at}</option>)}</select></label>}
    <div className={`pr3b1-state pr3b1-state-${gate.state.toLowerCase()}`} role="status"><strong>{gate.state}</strong> · {gate.reason}
      {r && <small>Last Run · {r.identity.scenario} · {r.identity.ran_at} · snapshot {r.identity.snapshot_id}</small>}
      {gate.showRun && <small>Totals and read identities agree; Studio snapshot identity is not proven.</small>}
    </div>
    <div className="pr3b1-main">
      <article className="pr3b1-sheet"><h3>Term Sheet</h3><small>Working Copy model values are informational. No new editing or financial calculation.</small>
        <div className="pr3b1-term-groups">{groups.map(g => <details open key={g.label}><summary>{g.label}</summary>{g.rows.length ? <Terms rows={g.rows} /> : <p>NOT AVAILABLE — no supplied terms.</p>}</details>)}</div>
        {s.senior_lock_reason && <p role="note">Scalar editing locked · {s.senior_lock_reason}</p>}
        <p>Lock-up DSCR and Minimum LLCR are model information, with no new edit or Run-verification claim.</p>
        <details><summary>Facility terms · Working Copy · read-only</summary>
          {facility ? <><label>Facility <select aria-label="Facility" value={facility.instrument_id} onChange={ev => setFacilityId(ev.target.value)}>{facilities.map(f => <option key={f.instrument_id} value={f.instrument_id}>{f.name}</option>)}</select></label>
          <Terms rows={[
            { label: facility.name, display: facility.status, source: `${facility.type} · ${facility.readiness || 'No readiness conclusion'}` },
            { label: 'Recorded facility commitment', display: number(facility.commitment_keur), source: `Working Copy · ${facility.currency} · kEUR; not a distinct Last Run Committed record` },
            { label: 'Repayment', display: facility.repayment || 'NOT AVAILABLE', source: 'Working Copy · facility' },
            { label: 'Maturity', display: facility.maturity_date || 'NOT AVAILABLE', source: 'Working Copy · facility' },
          ]} /></> : <p>NOT AVAILABLE — no configured facility terms supplied.</p>}
          <p>Two-Senior is read-only / release gated. Junior unsupported; VAT code-only. No per-tier sizing, draws or binding claim.</p>
          {(s.capital_stack.unsupported ?? []).map((u, i) => <p key={i}>{u.name} · {u.status} · {unsupportedReason(u)}</p>)}
        </details>
      </article>
      <div className="pr3b1-run-zones" data-run-zones={gate.showRun ? 'visible' : 'hidden'}>
        {!gate.showRun ? <div className="pr3b1-card"><h3>Last Run evidence</h3><p>{gate.reason}</p><a href={link('debt-metrics')}>Open Debt metrics / historical evidence</a></div> : <>
          <article className="pr3b1-card" aria-label="Sources & Uses Last Run"><h3>Sources & Uses <small>Last Run · kEUR</small></h3>
            <h4>Sources</h4><Terms rows={su!.sources.map(amount)} /><h4>Uses</h4><Terms rows={su!.uses.map(amount)} />
            <div className="pr3b1-totals"><Terms rows={su!.totals.map(amount)} /></div><p>Balance · {su!.balance} · Integrity · {su!.integrity}</p><small>{su!.note} {su!.reason}</small>
            <p>Saved Sources & Uses: NOT AVAILABLE. No Working Copy reconstruction.</p>
          </article>
          <article className="pr3b1-card" aria-label="Coverage Last Run"><h3>Coverage <small>Last Run</small></h3>
            <Terms rows={[creditTerm('Minimum DSCR', cov!.capacity.min_dscr, 'Last Run · capacity.min_dscr'),creditTerm('Average DSCR', cov!.capacity.avg_dscr, 'Last Run · capacity.avg_dscr'),
              creditTerm('Sizing target DSCR', cov!.capacity.target_dscr, 'Last Run · capacity.target_dscr'),creditTerm('Binding constraint', cov!.capacity.binding_constraint, cov!.bindingScope)]} />
            <p>Coverage · {dm?.evaluation?.coverage.status || 'UNAVAILABLE'} · {dm?.evaluation?.coverage.message || dm?.evaluation?.coverage.reason || dm?.reason}</p>
            <p>DSRA · {dm?.reserves?.dsra.available ? `Initial funding ${number(dm.reserves.dsra.initial_funding_keur)} kEUR` : dm?.reserves?.dsra.reason || 'NOT AVAILABLE'}</p>
            <p>Run execution, Model Integrity and coverage are independent server verdicts. No client threshold engine.</p>
          </article>
        </>}
      </div>
    </div>
    {cov && <>
      <div className="pr3b1-verdicts">
        <article className="pr3b1-card"><h3>Model Integrity</h3><strong>{cov.integrity.status || 'UNAVAILABLE'}</strong><Findings rows={cov.integrityFindings} /></article>
        <article className="pr3b1-card"><h3>Financial Bankability</h3><p>{cov.bindingScope}</p><Findings rows={cov.bankabilityFindings} /></article>
        <article className="pr3b1-card"><h3>Covenant Compliance</h3><p>{dm?.contract_terms?.note || dm?.contract_terms?.reason || 'NOT AVAILABLE — contract terms not supplied'}</p>
          <p>EoD · {dm?.evaluation?.eod.status || 'UNAVAILABLE'} · {dm?.evaluation?.eod.message || dm?.evaluation?.eod.reason}</p>
          <p>Covenant · {dm?.evaluation?.covenant.status || 'UNAVAILABLE'} · {dm?.evaluation?.covenant.message || dm?.evaluation?.covenant.reason}</p>
          <p>Period lock-up · {dm?.reserves?.lockup.available ? dm.reserves.lockup.note || 'Recorded period markers below' : dm?.reserves?.lockup.reason || 'NOT AVAILABLE'}</p>
        </article>
      </div>
      <details open><summary>Outstanding and coverage · native period schedule · Last Run</summary><p>{dm?.axis?.frequency} · {dm?.axis?.note} {dm?.basis_note}</p>
        {cov.periods.length ? <div className="pr3b1-scroll" tabIndex={0} role="region" aria-label="Native debt period schedule"><table><thead><tr>{['Period','Opening kEUR','Closing kEUR','DSCR (x)','Sizing target (x)','Shortfall kEUR','Below one','EoD breach','Covenant breach','Lock-up'].map(h => <th scope="col" key={h}>{h}</th>)}</tr></thead>
          <tbody>{cov.periods.map(p => <tr key={p.period_index}><th scope="row">{p.label} · {p.date}</th><td>{number(p.senior_opening_keur)}</td><td>{number(p.senior_closing_keur)}</td><td>{number(p.dscr)}</td><td>{number(p.sizing_target_dscr)}</td><td>{number(p.shortfall_keur)}</td>{[p.below_one,p.eod_breach,p.covenant_breach,p.lockup_active].map((v,i) => <td key={i}>{v == null ? 'NOT AVAILABLE' : v ? 'Yes' : 'No'}</td>)}</tr>)}</tbody></table></div> : <p>NOT AVAILABLE · {dm?.reason || 'No native period evidence.'}</p>}
      </details>
      <details><summary>Construction sources, draws and uses · Last Run · kEUR</summary><p>Senior draw is period-specific. No browser aggregate or per-facility allocation.</p>
        {su!.construction.length ? <div className="pr3b1-scroll" tabIndex={0} role="region" aria-label="Construction period evidence"><table><thead><tr><th scope="col">Period</th><th scope="col">Server field</th><th scope="col">kEUR</th><th scope="col">Authority / reason</th></tr></thead><tbody>{su!.construction.flatMap(p => p.fields.map((f,i) => <tr key={`${p.period}-${i}`}><th scope="row">{p.period} · {p.date}</th><td>{f.label}</td><td>{f.value == null ? 'NOT AVAILABLE' : f.display}</td><td>{f.authority} · {f.reason}</td></tr>))}</tbody></table></div> : <p>NOT AVAILABLE — no construction rows supplied.</p>}
      </details>
    </>}
    <details><summary>All existing Financing views</summary><nav className="pr3b1-legacy" aria-label="All existing Financing views">{LEGACY_VIEWS.map(([id,label]) => <a key={id} href={link(id)}>{label}</a>)}</nav></details>
  </section>;
}
