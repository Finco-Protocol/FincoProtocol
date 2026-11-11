// Hand-authored public contract fixture; no captured project/client data.
export function synthetic(state = 'CURRENT') {
  const cell = (v, d = String(v)) => ({ v, d });
  const amount = (label, value) => ({ label, value, display: String(value), authority: 'Synthetic canonical Last Run', reason: '' });
  const run = { identity: { snapshot_id: 'synthetic-snapshot', history_id: 'synthetic-history', ran_at: '2026-01-01', composite_hash: 'run-hash', scenario_id: null, scenario: 'Synthetic Base', state: `LAST RUN · ${state}` },
    integrity: { status: 'PASS' }, structure: { requested_gearing: cell(.8,'80.0%'), total_sources: cell(100), total_uses: cell(100), tenor: { first_debt_service_date: cell('2027-06-30'), last_debt_service_date: cell('2030-12-31'), contractual_maturity_date: cell(null,'UNAVAILABLE') } },
    capacity: { final_commitment: cell(70,'70 kEUR'), min_dscr: cell(.9,'0.90x'), avg_dscr: cell(1.1,'1.10x'), target_dscr: cell(1.2,'1.20x'), binding_constraint: cell('DSCR') }, findings: [], links: {},
    debt_metrics: { schema: 'WF04_DEBT_METRICS_V1', available: true, reason: '', axis: { frequency: 'SEMIANNUAL', note: 'Native synthetic axis' },
      contract_terms: { recorded: true, note: 'Recorded terms' }, evaluation: { coverage: { status: 'WARN', message: 'Debt-service shortfall warning' }, eod: { status: 'BREACH', reason: 'Server verdict' }, covenant: { status: 'BREACH', reason: 'Server verdict' } },
      reserves: { dsra: { available: true, initial_funding_keur: 0 }, lockup: { available: true, note: 'Persisted markers' } },
      periods: [{ period_index: 1, label: 'H1', date: '2027-06-30', senior_opening_keur: 70, senior_closing_keur: 65, dscr: .9, sizing_target_dscr: 1.2, shortfall_keur: 2, below_one: true, eod_breach: true, covenant_breach: true, lockup_active: true }], kpis: {}, schedule: [] } };
  const hash = state === 'STALE' ? 'working-hash' : 'run-hash';
  const workspace = { ok: true, project: { code: 'synthetic-project' }, workbook: { version: 'v1', composite_hash: hash, scenario_id: null, scenario_name: 'Synthetic Base' }, freshness: { state }, identity: { snapshot_id: 'synthetic-snapshot', composite_hash: 'run-hash', ran_at: '2026-01-01' } };
  const credit = { ok: true, project: { code: 'synthetic-project' }, freshness: state, requested: ['synthetic-history'], max_runs: 3,
    history_rows: [{ history_id: 'synthetic-history', ran_at: '2026-01-01', scenario: 'Synthetic Base', is_last: true, selected: true }], data: { project_code: 'synthetic-project', runs: [run], findings: [
      { id: 'integrity', title: 'Funding provenance', classification: 'PROVENANCE', severity: 'INFO', status: 'PASS', metric: 'identity', run_history_id: 'synthetic-history' },
      { id: 'coverage', title: 'Coverage warning', classification: 'SENIOR_DEBT', severity: 'WARNING', status: 'WARN', metric: 'DSCR', run_history_id: 'synthetic-history' } ] } };
  const studio = { ok: true, project: { code: 'synthetic-project', protected_reference: false }, freshness: state, editable: true,
    identity: { content_hash: hash, workbook_version: 'v1', scenario_id: null, scenario_name: 'Synthetic Base' },
    bankability: { available: true, fees_editable: false }, senior_pricing_mode: 'FLAT', senior_dscr_mode: 'FLAT_SCALAR', senior_lock_reason: 'Synthetic calibrated schedule',
    senior_detail_rows: [['All-in interest rate','5%'],['Base rate','3%'],['Margin','2%'],['Lock-up DSCR','1.20x'],['Minimum LLCR','1.30x'],['Amortization','Sculpted']],
    sponsor_view: { equity: [], other: [], shl: [], returns: [] }, reserve_view: { support: 'NONE', requirement: { label: 'Reserve requirement', value: null, display: 'Unavailable', source: 'Working Copy', reason: 'Not configured' } },
    multisenior: { active: false }, capital_stack: { available: true, rows: [ { instrument_id: 'senior', name: 'Synthetic Senior', status: 'ACTIVE', type: 'SENIOR', commitment_keur: 70, currency: 'EUR', repayment: 'SCULPTED' }, { instrument_id: 'senior2', name: 'Synthetic Senior 2', status: 'DRAFT', commitment_keur: 0, draws_total_keur: 0 } ], unsupported: [{ name: 'Junior', status: 'NOT_SUPPORTED', reason: 'Not released' }] },
    sources_uses: { available: true, view: { run_kind: 'LAST_RUN', freshness: state, has_run: true, has_financing_evidence: true,
      sources: [amount('Actual sized Senior debt',70),amount('Share capital and other equity',30),amount('SHL cash contributed',0)],
      uses: [amount('Hard project CAPEX',100),amount('Other project uses',null)], total_sources: amount('Total Sources',100),total_uses: amount('Total Uses',100),residual: amount('Funding Residual',0),balance_status:'BALANCED',integrity:'PASS',
      construction_rows:[{ period:1,date:'2026-06-30',fields:[amount('Senior draw',50),amount('Project uses',60)] },{period:2,date:'2026-12-31',fields:[amount('Senior draw',20)]}] } } };
  const selected_run = {available:state!=='NOT_RUN',view:{
    schema:'F02_PERIOD_EVIDENCE_PHASE_A_V1',
    identity:{history_id:run.identity.history_id,snapshot_id:run.identity.snapshot_id,composite_hash:run.identity.composite_hash,scenario_id:run.identity.scenario_id,state},
    sources_uses:studio.sources_uses.view,
    construction:{rows:studio.sources_uses.view.construction_rows.map(p=>({period_index:p.period,date:p.date,fields:p.fields})),fc_senior_draw:{value:0,unit:'kEUR',source:'Synthetic committed source'}},
    repayment:{available:true,reason:'',rows:run.debt_metrics.periods.map(p=>({...p,axis:'RUN_DEBT_SERVICE_PERIOD'}))},
    source_authority:'ONE_COMMITTED_RUN_HISTORY_ENTRY',internal_run_binding:'PROVEN_BACKEND_ENTRY',studio_credit_cross_view:'MITIGATED_NOT_PROVEN'
  }};
  studio.selected_run=selected_run;
  const fields = { ok:true,project:{code:'synthetic-project'},save:{content_hash:hash,workbook_version:'v1'},fields:[{field_id:'debt.senior.gearing_pct',value:85,display_value:'85.0%'}] };
  return structuredClone({scope:{project:'synthetic-project',scenarioId:null},before:workspace,after:workspace,studio,creditBefore:credit,credit,fields});
}
