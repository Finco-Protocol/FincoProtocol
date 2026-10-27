"""All sixteen rates use real canonical HTTP Run; refusals never invent history."""
import copy,json,sqlite3,uuid
import pytest
from bs4 import BeautifulSoup
from tests.test_finval_rate_contract import env,KINDS,USER,_prime,_save,_ws,_snapshot,_emit

@pytest.mark.parametrize('kind',KINDS)
@pytest.mark.parametrize('human',[.056,.56,5.6,9.])
def test_saved_rate_run_commits_coherent_financial_history_or_refuses(env,kind,human,monkeypatch):
    record=env.create(kind,capacity=20);_prime(env,record)
    _save(env,record,human,'batch')
    page=env.client.get('/v2/workbook',params={'project':record.project_code})
    form=BeautifulSoup(page.text,'html.parser').select_one('#v2-canonical-run-form')
    data={i['name']:i.get('value','') for i in form.select('input[name]')}
    data['csrf_token']=data.pop('run_csrf_token');data['run_intent_id']=str(uuid.uuid4())
    # Observe, without substituting, the actual post-fold inputs passed to Run.
    import app.api.project_runner as runner
    from app.input_adapter import senior_rate_authority
    from app.workbook.input_set import ProjectInputSet
    from tests.test_finval_rate_run_acceptance import _metrics
    from dataclasses import asdict
    original_inputs=ProjectInputSet.from_snapshot(_snapshot(record)).to_projectinputs()
    original_run=runner.run_project;captured=[]
    def observed_run(*args,**kwargs):
        captured.append(kwargs['project_inputs_override'])
        return original_run(*args,**kwargs)
    monkeypatch.setattr(runner,'run_project',observed_run)
    response=env.client.post('/v2/workbook/run',headers={'Accept':'application/json','HX-Request':'true'},data=data,follow_redirects=False)
    assert len(captured)==1
    assert senior_rate_authority(captured[0])[1]==pytest.approx(human/100,abs=1e-17)
    oracle=_metrics(captured[0])  # independent Decimal opening * rate * day-count
    refused=oracle['status']=='REFUSED'
    old,new=asdict(original_inputs),asdict(captured[0])
    folded_changes=[key for key in old if old[key]!=new[key]]
    payload=response.json()
    assert payload['outcome']==('FAILED' if refused else 'COMMITTED'),payload
    with sqlite3.connect(env.db_path) as c:
        c.row_factory=sqlite3.Row
        rows=[dict(row) for row in c.execute('SELECT * FROM model_run_history WHERE project_id=?',(record.project_id,))]
    assert len(rows)==(0 if refused else 1)
    ws=_ws(record)
    if not refused:
        assert ws.last_runtime_snapshot_id==rows[0]['runtime_snapshot_id']
        assert ws.last_debt_schedule and ws.last_financial_statements
        interest=[p['senior_interest_keur'] for p in ws.last_debt_schedule['periods'] if p.get('senior_interest_keur') is not None]
        assert interest
        # Persisted presentation is intentionally rounded to 2 decimals per period.
        assert sum(interest)==pytest.approx(oracle['total_interest_keur'],abs=len(interest)*.0051)
        assert json.loads(rows[0]['debt_schedule_json'])==ws.last_debt_schedule
        assert json.loads(rows[0]['financial_statements_json'])==ws.last_financial_statements
        before=copy.deepcopy(rows)
        _save(env,record,.56 if human!=.56 else 5.6)
        with sqlite3.connect(env.db_path) as c:
            c.row_factory=sqlite3.Row
            assert [dict(row) for row in c.execute('SELECT * FROM model_run_history WHERE project_id=?',(record.project_id,))]==before
    _emit(f'http-{kind}-{human}',{'kind':kind,'human_pct':human,'outcome':payload['outcome'],'effective_input_changes_from_existing_run_folds':folded_changes,'independent_interest_oracle':oracle,'history_rows':len(rows),'persisted_debt_schedule':ws.last_debt_schedule,'persisted_financial_statements':ws.last_financial_statements,'persisted_summary':ws.last_runtime_summary})
