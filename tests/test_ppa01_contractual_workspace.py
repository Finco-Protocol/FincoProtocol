"""Dated PPA Save/Scenario/Run/history integration, without a second financial writer."""

from tests.run_clone_csrf import post_valid_csrf
import copy
from datetime import date
from decimal import Decimal
import json

import pytest

from tests.test_developer_economics_persistence_v1 import OWNER, Flow, env  # noqa: F401
from tests.test_rc2_integration_acceptance import _pi, _save_revenue
from tests.test_ppa01_contractual_timing import terms, dated, book
from tests.test_ppa01_index_series_revenue import _operating


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_dated_contract_save_stale_run_scenario_and_history(env, kind):
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.scenarios_repository import list_scenarios, get_scenario
    flow = Flow(env, kind); pi = _pi(flow); op = _operating(pi)
    raw = book(pi, kind, terms())
    assert _save_revenue(flow, raw).status_code == 200
    run = flow.run()
    for evidence, p in zip(run["revenue_multistream_audit"], op):
        row = next(s for s in evidence["streams"] if s["id"] == "ppa-1")
        n = sum(date(y,12,31) <= p.start_date for y in range(2029,p.start_date.year+1))
        price = Decimal(60) * Decimal("1.02") ** n
        assert row["price_eur_mwh"] == pytest.approx(float(price), abs=1e-12)
        assert row["revenue_keur"] == pytest.approx(float(Decimal(str(row["quantity_mwh"])) * price / 1000), abs=1e-8)
    before = copy.deepcopy(get_run_history(OWNER, flow.record.project_id))
    page = env.client.get('/v2/workbook', params=flow.project)
    assert 'CURRENT' in page.text and 'data-calendar-preview' in page.text
    assert env.client.post('/v2/workbook/scenarios/create', data={**flow.project, 'scenario_name':'Dated alternative'}).status_code == 200
    child = next(s for s in list_scenarios(OWNER,flow.record.project_id) if not s.is_base_case)
    assert env.client.post('/v2/workbook/scenarios/select', data={**flow.project,'scenario_id':child.scenario_id}).status_code == 200
    alt = book(pi,kind,dated(terms(),op[-1].end_date.isoformat()),rate=0)
    assert _save_revenue(flow,alt).status_code == 200
    assert json.loads(flow.ws().draft_snapshot['rev_multistream_config_json']) == raw
    assert json.loads(get_scenario(child.scenario_id,OWNER).overrides['rev_multistream_config_json']) == alt
    child_run = flow.run()
    assert child_run['total_revenue_keur'] != run['total_revenue_keur']
    history = get_run_history(OWNER,flow.record.project_id)
    assert len(history) == 2
    assert next(h for h in history if h.history_id==before[0].history_id).runtime_summary == before[0].runtime_summary
    alt['streams'][0]['price_eur_mwh'] = 61
    assert _save_revenue(flow,alt).status_code == 200
    assert flow.ws().dirty and 'STALE' in env.client.get('/v2/workbook',params=flow.project).text
    flow.run()
    assert not flow.ws().dirty and len(get_run_history(OWNER,flow.record.project_id)) == 3


@pytest.mark.parametrize('kind',['solar','wind'])
def test_unaligned_save_and_genuine_run_refusal_preserve_last_run(env,kind):
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.db import get_connection
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get
    flow=Flow(env,kind); pi=_pi(flow); good=book(pi,kind,terms())
    assert _save_revenue(flow,good).status_code==200
    flow.run(); ws=flow.ws(); summary=copy.deepcopy(ws.last_runtime_summary)
    history=copy.deepcopy(get_run_history(OWNER,flow.record.project_id))
    bad=copy.deepcopy(good)
    bad['streams'][0]['indexation_timing']=terms('CUSTOM',anchor='2029-04-15')
    rejected=_save_revenue(flow,bad)
    assert rejected.status_code==422 and 'REVIEW_PERIOD_ALIGNMENT' in rejected.text
    assert flow.ws().draft_snapshot==ws.draft_snapshot
    assert flow.ws().last_runtime_summary==summary
    # Simulate a previously persisted stale contract; the actual canonical Run
    # must refuse it, independently of the Save-time validation.
    snapshot=copy.deepcopy(ws.draft_snapshot)
    snapshot['rev_multistream_config_json']=json.dumps(bad)
    conn=get_connection()
    try:
        conn.execute('UPDATE workspace_states SET draft_snapshot_json=?,dirty=1 WHERE user_id=? AND project_id=?',
                     (json.dumps(snapshot),OWNER,flow.record.project_id))
        conn.commit()
    finally:
        conn.close()
    # No successful GET is needed to prove the Run refusal for invalid persisted inputs.
    identity=assemble_consistent_for_get(OWNER,flow.record.project_id,WORKBOOK.version)
    response=post_valid_csrf(env.client, '/v2/workbook/run',headers={'HX-Request':'true'},data={**flow.project,
        'content_hash':identity.composite_hash,'workbook_version':WORKBOOK.version})
    assert response.headers.get('X-Finco-Run-Outcome')=='FAILED', response.text[:500]
    assert flow.ws().last_runtime_summary==summary
    assert [h.history_id for h in get_run_history(OWNER,flow.record.project_id)]==[h.history_id for h in history]
    assert flow.ws().draft_snapshot['rev_multistream_config_json']==snapshot['rev_multistream_config_json']


def test_editor_keeps_timeline_available_for_stale_contract_dates_without_rebinding(env):
    from datetime import timedelta
    from app.workbook.input_set import ProjectInputSet
    from app.v2.router import _build_revenue_contract_editor
    flow=Flow(env,'solar'); pi=_pi(flow)
    raw=book(pi,'solar',terms('COD',anchor=pi.info.cod_date.isoformat()),end=1)
    assert _save_revenue(flow,raw).status_code==200
    ws=flow.ws(); changed=copy.deepcopy(ws.draft_snapshot)
    new_cod=(pi.info.cod_date+timedelta(days=1)).isoformat()
    changed['cod_date']=new_cod
    context=_build_revenue_contract_editor(ProjectInputSet.from_snapshot(changed),ws)
    assert context['project_cod']==new_cod
    assert context['operating_window']['start']==new_cod
    assert context['calendar_preview_error'] and context['calendar_preview']=={}
    assert json.loads(context['raw'])==raw  # no derived or contractual date rewritten by GET
    assert flow.ws().draft_snapshot==ws.draft_snapshot
