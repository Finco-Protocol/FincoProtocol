"""Independent interest arithmetic plus real canonical Save/Run/history evidence."""
from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import json,sqlite3,uuid
import pytest
from bs4 import BeautifulSoup
from tests.test_finval_rate_contract import env, USER, KINDS, _prime, _ws, _snapshot, _save, _emit
from app.input_adapter import senior_rate_authority
from app.workbook.input_set import ProjectInputSet
from app.services.production_financial_authority import run_clean_production


def _metrics(pi):
    from app.services.production_financial_authority import CleanProductionRunUnavailable
    try:
        r=run_clean_production(pi)
    except CleanProductionRunUnavailable as exc:
        return {'status':'REFUSED','reason_code':exc.reason_code,'detail':str(exc),
                'rate_pct':senior_rate_authority(pi)[1]*100,
                'typed_ratio':senior_rate_authority(pi)[1]}
    g=r.g2c_result;m=g.financing_result.project_model_result;sd=m.senior_debt
    by_idx={p.period_index:p for p in m.periods};human=senior_rate_authority(pi)[1]*100
    annual={}
    for idx,opening,interest,principal,service in zip(sd.period_indices,sd.senior_debt_opening_keur,sd.senior_interest_keur,sd.senior_principal_keur,sd.senior_debt_service_keur):
        period=by_idx[idx];days=(period.period_end-period.period_start).days
        denom=360 if '360' in str(pi.financing.senior_debt_interest_config.day_count) else 365
        independent=Decimal(str(opening))*Decimal(str(human))/Decimal(100)*Decimal(days)/Decimal(denom)
        assert interest==pytest.approx(float(independent),abs=1e-8)
        assert service==pytest.approx(interest+principal,abs=1e-8)
        year=str((period.period_end-timedelta(days=1)).year);annual[year]=annual.get(year,0)+interest
    return {'status':'OK','rate_pct':human,'typed_ratio':senior_rate_authority(pi)[1],
        'first_interest_keur':sd.senior_interest_keur[0],'annual_interest_keur':annual,
        'total_interest_keur':sum(sd.senior_interest_keur),'debt_size_keur':sd.debt_size_keur,
        'debt_service_keur':list(sd.senior_debt_service_keur),
        'cfads_keur':list(m.tax_and_cfads.cfads_keur),
        'pure_equity_xirr':g.pure_equity_xirr,'total_sponsor_xirr':g.total_sponsor_xirr}


def _run(env,record,keyed):
    page=env.client.get('/v2/workbook',params={'project':record.project_code})
    form=BeautifulSoup(page.text,'html.parser').select_one('#v2-canonical-run-form');assert form
    data={f['name']:f.get('value','') for f in form.select('input[name]')}
    data['csrf_token']=data.pop('run_csrf_token')
    if keyed:data['run_intent_id']=str(uuid.uuid4())
    else:data.pop('run_intent_id',None)
    response=env.client.post('/v2/workbook/run',headers={'Accept':'application/json','HX-Request':'true'},data=data,follow_redirects=False)
    assert response.status_code==200,response.text[:500]
    if keyed:assert response.json()['outcome']=='COMMITTED',response.text
    else:assert 'FAILED'!=response.headers.get('x-finco-run-outcome')
    return response

@pytest.mark.parametrize('kind',KINDS)
@pytest.mark.parametrize('human',[.056,.56,5.6,9.])
def test_independent_interest_equation_and_cashflow_evidence(env,kind,human):
    record=env.create(kind,capacity=20);_prime(env,record)
    before=ProjectInputSet.from_snapshot(_snapshot(record)).to_projectinputs();baseline=_metrics(before)
    _save(env,record,human)
    after=ProjectInputSet.from_snapshot(_snapshot(record)).to_projectinputs();corrected=_metrics(after)
    assert corrected['rate_pct']==pytest.approx(human,abs=1e-13)
    assert baseline['status']=='OK'
    expected_refusals={
        ('data_center',.056):'G2A_FIXED_SOURCES_EXCEED_TOTAL_PROJECT_USES',
        ('wind',9.):'SHL_MATURITY_RESIDUAL_FAILS_CLOSED',
        ('data_center',9.):'SHL_MATURITY_RESIDUAL_FAILS_CLOSED',
    }
    if (kind,human) in expected_refusals:
        assert corrected['status']=='REFUSED'
        assert expected_refusals[kind,human] in corrected['detail']
        assert corrected['reason_code']=='PR8_CLEAN_ENGINE_FAIL_CLOSED'
    else:
        assert corrected['status']=='OK'
        assert corrected['total_interest_keur']!=baseline['total_interest_keur']
    # These are intentionally different economics, never claimed bit identical.
    # Three exact engine refusals are evidence, not replaced with made-up KPIs.
    _emit(f'{kind}-rate-{human}',{'baseline':baseline,'corrected':corrected})

@pytest.mark.parametrize('kind',KINDS)
@pytest.mark.parametrize('keyed',[False,True])
def test_real_run_history_is_immutable_after_save_and_replay(env,kind,keyed):
    record=env.create(kind,capacity=20);_prime(env,record);_save(env,record,5.6)
    first=_run(env,record,keyed)
    def rows():
        with sqlite3.connect(env.db_path) as c:
            return c.execute('SELECT * FROM model_run_history WHERE project_id=? ORDER BY rowid',(record.project_id,)).fetchall()
    old=rows();assert len(old)==1
    _save(env,record,.56,'batch');assert rows()==old
    _run(env,record,keyed);new=rows();assert len(new)==2 and new[0]==old[0]
    projection=env.client.get('/v2/model-react/runs',params={'project':record.project_code}).json()
    _emit(f'{kind}-history-{keyed}',{'runs':projection['runs'],'snapshot_rate':_snapshot(record)['interest_rate_pct']})
