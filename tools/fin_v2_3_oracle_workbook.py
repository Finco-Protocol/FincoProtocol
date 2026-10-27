"""Independent Excel-compatible FIN-V2-3 oracle over disposable committed Runs.

Only the capture phase calls FINCO. Workbook formulas and Decimal expectations
rebuild BASE CFADS from full-precision persisted statement components. BANK
CFADS and C1 unlevered components remain explicitly engine-derived inputs.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.fin_v2_3_oracle import npv


def capture(senior_source=None):
    from app.persistence import db
    from app.persistence.run_history_repository import get_run_history
    from app.export.run_evidence import evidence_from_history_entry
    from app.workbook.input_set import ProjectInputSet
    from app.workbook.registry import WORKBOOK
    from app.workbook.update_service import WorkbookUpdateService
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.workbook_identity import assemble_consistent_for_get
    from app.services import financial_core_evidence as core_module
    from tests.rc7_helpers import create_project, commit_run
    from tests.fin_v2_3_support import config_json
    external = None
    if senior_source:
        raw = Path(senior_source).read_bytes()
        blob = hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        if blob != 'f9e0caefd74d86c368ae2b74cef2cfc035b937b1':
            raise ValueError('FIN-V2-2 source must match inspected PR #390 blob exactly')
        spec = importlib.util.spec_from_file_location('fin_v2_2_exact_external_fixture', senior_source)
        external = importlib.util.module_from_spec(spec); spec.loader.exec_module(external)
    original_attach = core_module.attach_financial_core
    def composed_attach(payload, clean_run):
        if external:
            payload['financing_evidence']['senior_debt_evidence'] = external.build_from_clean_run(clean_run)
        original_attach(payload, clean_run)
    output = []
    with tempfile.TemporaryDirectory(prefix='fin-v2-3-oracle-') as folder, patch.object(db,'DB_PATH',folder+'/oracle.db'), patch.object(core_module,'attach_financial_core',composed_attach):
        db.init_db()
        for kind in ('solar','wind','data_center','ev'):
            for case in ('BASE','BANK'):
                pr, uid, snap, pi, scenario = create_project(kind, suffix=case)
                ws = get_workspace_state(uid,pr.project_id)
                identity = assemble_consistent_for_get(user_id=uid,project_id=pr.project_id,workbook_version=WORKBOOK.version)
                WorkbookUpdateService.apply_batch_draft_update(ws=ws,
                    updates=[('debt.valuation.configuration',config_json(case))],content_hash=identity.composite_hash,
                    workbook_version=WORKBOOK.version,expected_scenario_id=ws.active_scenario_id,project_record=pr,actor_user_id=uid)
                ws = get_workspace_state(uid,pr.project_id)
                typed = ProjectInputSet.from_snapshot(dict(ws.draft_snapshot)).to_projectinputs()
                commit_run(pr,uid,typed,scenario,kind)
                entry = get_run_history(uid,pr.project_id)[0]
                ev = evidence_from_history_entry(entry,pr,last_run_snapshot_id=entry.runtime_snapshot_id,
                    last_run_is_stale=False,freshness_source='disposable actual CAS commit')
                output.append({'kind':kind,'case':case,'snapshot_id':ev.snapshot_id,'history_id':ev.history_id,
                    'composite_hash':ev.composite_hash,'evidence_digest':ev.evidence_digest,
                    'core':ev.financial_core,'sponsor_schedule':ev.sponsor_schedule})
    return output


def workbook(evidences, destination):
    import xlsxwriter
    book = xlsxwriter.Workbook(str(destination))
    fmt_date = book.add_format({'num_format':'yyyy-mm-dd'})
    overview = book.add_worksheet('Oracle_Review')
    overview.write_row(0,0,['Independent verification: synthetic disposable committed Runs; no commercial default rates'])
    overview.write_row(1,0,['BASE CFADS rebuilt from persisted statement EBITDA + financing income - cash tax.'])
    overview.write_row(2,0,['BANK CFADS, C1 unlevered components, debt opening and sponsor receipts are engine-derived input evidence.'])
    overview.write_row(3,0,['Formula caches are independently calculated using Decimal(50). Excel recalculates formulas on open.'])
    overview.write_row(4,0,['FIN-V2-2 composition uses exact PR #390 module in disposable test capture only; source branches remain separate.'])
    overview.write_row(6,0,['Case','Metric','Persisted FINCO','Independent oracle','Difference','Run snapshot','Evidence digest'])
    output=[]; review_row=7
    def parsed(s):return date.fromisoformat(s)
    for n,e in enumerate(evidences):
        core=e['core']; policy=core['valuation_policy']; case=e['case']; prefix=f'{n+1}_{e["kind"][:3]}_{case}'
        inp=book.add_worksheet(prefix+'_Inputs'); cf=book.add_worksheet(prefix+'_CF'); rolling=book.add_worksheet(prefix+'_Roll')
        inp.write_row(0,0,['Immutable Run',e['snapshot_id'],e['evidence_digest']])
        rate=policy['coverage']['annual_discount_rate']
        coverage=core['loan_life_coverage']
        if coverage['status']!='OK':raise ValueError('Oracle requires explicit integrated maturity/payoff fixture: '+coverage['status'])
        c=coverage['contractual'];a=coverage['actual_repayment'];p=coverage['plcr']
        inp.write_row(1,0,['Coverage rate (annual ratio)',rate]);inp.write_datetime(2,1,parsed(c['observation_date']),fmt_date)
        inp.write_row(2,0,['Observation date']); inp.write_datetime(3,1,parsed(c['horizon_end_date']),fmt_date)
        inp.write(3,0,'Contractual maturity');inp.write_datetime(4,1,parsed(a['horizon_end_date']),fmt_date);inp.write(4,0,'Actual extinguishment')
        inp.write_datetime(5,1,parsed(p['horizon_end_date']),fmt_date);inp.write(5,0,'Project life end')
        inp.write_row(7,0,['BANK input authority: canonical debt-sizing CFADS; never relabelled P50'])
        inp.write_row(10,0,['End date','Start date','Index','Engine BASE','Engine BANK','Statement EBITDA','Statement FI','Statement cash tax','Rebuilt BASE','BASE difference','Senior opening','Selected CFADS','Discount divisor','Contractual PV','Actual PV','Project-life PV'])
        rows=[r for r in core['coverage_input_periods'] if r['is_operation']]
        selected=[]
        for j,r in enumerate(rows,12):
            row=j-1;inp.write_datetime(row,0,parsed(r['period_end']),fmt_date);inp.write_datetime(row,1,parsed(r['period_start']),fmt_date)
            vals=[r['period_index'],r['base_cfads_keur'],r['bank_cfads_keur'],r['statement_ebitda_keur'],r['statement_financing_income_keur'],r['statement_cash_tax_keur']]
            if any(v is None for v in vals):raise ValueError('Full-precision persisted statement components required')
            inp.write_row(row,2,vals)
            rebuilt=r['statement_ebitda_keur']+r['statement_financing_income_keur']-r['statement_cash_tax_keur']
            inp.write_formula(row,8,f'=F{j}+G{j}-H{j}',None,rebuilt)
            inp.write_formula(row,9,f'=I{j}-D{j}',None,rebuilt-r['base_cfads_keur'])
            if r['senior_opening_balance_keur'] is not None:
                inp.write_number(row,10,r['senior_opening_balance_keur'])
            value=rebuilt if case=='BASE' else r['bank_cfads_keur'];selected.append(value)
            inp.write_formula(row,11,f'={"I" if case=="BASE" else "E"}{j}',None,value)
            divisor=(1+rate)**((parsed(r['period_end'])-parsed(c['observation_date'])).days/365)
            inp.write_formula(row,12,f'=(1+$B$2)^((A{j}-$B$3)/365)',None,divisor)
            for col,end in [(13,c['horizon_end_date']),(14,a['horizon_end_date']),(15,p['horizon_end_date'])]:
                include=r['period_index']<= {'13':c['horizon_end_period_index'],'14':a['horizon_end_period_index'],'15':p['horizon_end_period_index']}[str(col)]
                inp.write_formula(row,col,f'=IF(A{j}<=$B${col-9},L{j}/M{j},0)',None,value/divisor if include else 0)
        endrow=11+len(rows)
        calculated={}
        for key,obs in [('llcr_contractual_maturity',c),('llcr_actual_repayment',a),('plcr',p)]:
            use=[(r,v) for r,v in zip(rows,selected) if r['period_index']<=obs['horizon_end_period_index']]
            calculated[key]=float(npv([parsed(r['period_end']) for r,v in use],[v for r,v in use],rate,parsed(obs['observation_date'])))/obs['opening_senior_balance_keur']
        rolling.write_row(0,0,['Observation date','Index','Opening Senior','Remaining horizon','Independent LLCR','Persisted ratio','Difference'])
        roll_values=[]
        for j,o in enumerate(coverage['rolling'],2):
            use=[(r,v) for r,v in zip(rows,selected) if o['period_index']<=r['period_index']<=o['horizon_end_period_index']]
            v=float(npv([parsed(r['period_end']) for r,_ in use],[v for _,v in use],rate,parsed(o['observation_date'])))/o['opening_senior_balance_keur'];roll_values.append(v)
            rolling.write_datetime(j-1,0,parsed(o['observation_date']),fmt_date);rolling.write_row(j-1,1,[o['period_index'],o['opening_senior_balance_keur'],o['horizon_end_period_index']])
            q="'"+inp.name+"'!";ids=f'{q}$C$12:$C${endrow}';dates=f'{q}$A$12:$A${endrow}';amounts=f'{q}$L$12:$L${endrow}'
            formula=f'=SUMPRODUCT(({ids}>=B{j})*({ids}<=D{j})*{amounts}/((1+{q}$B$2)^(({dates}-A{j})/365)))/C{j}'
            rolling.write_formula(j-1,4,formula,None,v);rolling.write_number(j-1,5,o['ratio']);rolling.write_formula(j-1,6,f'=E{j}-F{j}',None,v-o['ratio'])
        calculated['min_rolling_llcr']=min(roll_values)
        cf.write_row(0,0,['Project discount',policy['project']['annual_discount_rate'],'Sponsor hurdle',policy['sponsor']['annual_discount_rate']])
        cf.write_row(2,0,['Project date','Investment','Operating','Tax','Terminal','Rebuilt net project CF','Discounted project CF','Sponsor date','Equity cash out','SHL cash out','Equity distributions','SHL interest','SHL principal','Rebuilt sponsor net CF','Discounted sponsor CF'])
        projects=core['project_cashflows'];sponsors=e['sponsor_schedule']['periods'];pdate=parsed(projects[0]['cashflow_date']);sdate=parsed(sponsors[0]['date'])
        for j,r in enumerate(projects,4):
            cf.write_datetime(j-1,0,parsed(r['cashflow_date']),fmt_date)
            vals=[r['project_investment_outflow_keur'],r['project_operating_inflow_keur'],r['project_tax_outflow_keur'],r['terminal_component_keur']]
            cf.write_row(j-1,1,vals);net=-vals[0]+vals[1]-vals[2]+vals[3]
            pv=float(npv([parsed(r['cashflow_date'])],[net],policy['project']['annual_discount_rate'],pdate))
            cf.write_formula(j-1,5,f'=-B{j}+C{j}-D{j}+E{j}',None,net);cf.write_formula(j-1,6,f'=F{j}/((1+$B$1)^((A{j}-$A$4)/365))',None,pv)
        for j,r in enumerate(sponsors,4):
            cf.write_datetime(j-1,7,parsed(r['date']),fmt_date)
            equity=sum(r[k] for k in ['share_capital_contribution_keur','share_premium_contribution_keur','other_committed_equity_contribution_keur','additional_equity_contribution_keur'])
            vals=[equity,r['shl_cash_contribution_keur'],r['legal_equity_distribution_keur'],r['shl_cash_interest_receipt_keur'],r['shl_principal_receipt_keur']]
            cf.write_row(j-1,8,vals);net=-vals[0]-vals[1]+sum(vals[2:]);pv=float(npv([parsed(r['date'])],[net],policy['sponsor']['annual_discount_rate'],sdate))
            cf.write_formula(j-1,13,f'=-I{j}-J{j}+K{j}+L{j}+M{j}',None,net);cf.write_formula(j-1,14,f'=N{j}/((1+$D$1)^((H{j}-$H$4)/365))',None,pv)
        calculated['project_npv_keur']=float(npv([parsed(r['cashflow_date']) for r in projects],[-r['project_investment_outflow_keur']+r['project_operating_inflow_keur']-r['project_tax_outflow_keur']+r['terminal_component_keur'] for r in projects],policy['project']['annual_discount_rate'],pdate))
        calculated['sponsor_npv_keur']=float(npv([parsed(r['date']) for r in sponsors],[-sum(r[k] for k in ('share_capital_contribution_keur','share_premium_contribution_keur','other_committed_equity_contribution_keur','additional_equity_contribution_keur'))-r['shl_cash_contribution_keur']+r['legal_equity_distribution_keur']+r['shl_cash_interest_receipt_keur']+r['shl_principal_receipt_keur'] for r in sponsors],policy['sponsor']['annual_discount_rate'],sdate))
        formulas={
            'llcr_contractual_maturity':f"=SUM('{inp.name}'!N12:N{endrow})/'{inp.name}'!K12",
            'llcr_actual_repayment':f"=SUM('{inp.name}'!O12:O{endrow})/'{inp.name}'!K12",
            'plcr':f"=SUM('{inp.name}'!P12:P{endrow})/'{inp.name}'!K12",
            'min_rolling_llcr':f"=MIN('{rolling.name}'!E2:E{len(coverage['rolling'])+1})",
            'project_npv_keur':f"=SUM('{cf.name}'!G4:G{len(projects)+3})",
            'sponsor_npv_keur':f"=SUM('{cf.name}'!O4:O{len(sponsors)+3})"}
        for key,value in calculated.items():
            difference=value-core[key]
            if abs(difference)>max(1e-9,abs(value)*1e-12):raise AssertionError((e['kind'],case,key,difference))
            overview.write_row(review_row,0,[prefix,key,core[key],value,difference,e['snapshot_id'],e['evidence_digest']])
            overview.write_formula(review_row,3,formulas[key],None,value)
            overview.write_formula(review_row,4,f'=D{review_row+1}-C{review_row+1}',None,difference)
            review_row+=1
            output.append({'kind':e['kind'],'case':case,'metric':key,'oracle':value,'engine':core[key],'difference':difference})
        for sheet in (inp,cf,rolling):sheet.freeze_panes(11 if sheet==inp else 3,1);sheet.set_column(0,15,21)
    overview.set_column(0,6,32)
    book.close()
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output-dir',required=True);parser.add_argument('--senior-evidence-source');parser.add_argument('--inputs')
    args=parser.parse_args();out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    if args.inputs:
        import gzip
        raw=Path(args.inputs).read_bytes()
        inputs=json.loads(gzip.decompress(raw) if str(args.inputs).endswith('.gz') else raw)
    else:
        inputs=capture(args.senior_evidence_source)
    (out/'oracle-committed-inputs.json').write_text(json.dumps(inputs,indent=2))
    results=workbook(inputs,out/'FIN_V2_3_INDEPENDENT_ORACLE.xlsx')
    (out/'oracle-reconciliation.json').write_text(json.dumps(results,indent=2))
    print(f'{len(inputs)} immutable synthetic Runs; {len(results)} independent metric comparisons PASS')
