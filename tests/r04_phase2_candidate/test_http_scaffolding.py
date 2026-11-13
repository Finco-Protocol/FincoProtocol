"""Real endpoints: current annual-format refusals and legacy combined Save All.

These tests never claim new absolute-volume positive Save/Run support. They use
unchanged production routes and disposable DB fixtures, not an alternate route
or raw insert to evade source/financial admission.
"""
import hashlib
import json
import os
from pathlib import Path

from app.persistence import db
from tests.test_model_decision_workspace_v2 import env  # noqa: F401
from tests.test_save_all_atomic_v1 import world, _project, _body, _contracts_json, URL, OWNER  # noqa: F401
from tests.test_wf07_revenue_workspace import contract_tokens
from tests.r04_phase2_candidate.test_candidate import document

TABLES = ("projects", "workspace_states", "scenarios", "model_run_history", "save_all_requests", "model_run_intents", "capex_sub_lines", "opex_sub_lines")


def digest():
    with db.get_cursor() as cur:
        available = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        values = {table: [dict(row) for row in cur.execute("SELECT * FROM " + table + " ORDER BY rowid")]
                  for table in TABLES if table in available}
    return {"sha256": hashlib.sha256(json.dumps(values,sort_keys=True,default=str).encode()).hexdigest(),
            "counts": {table:len(rows) for table,rows in values.items()}}


def evidence(label, response, before, after, scope):
    target = os.environ.get("R04_P2_EVIDENCE_DIR")
    if target:
        out=Path(target);out.mkdir(parents=True,exist_ok=True)
        (out/(label+'.json')).write_text(json.dumps({"evidence_id":label,"status":response.status_code,
            "scope":scope,"response":response.json(),"before":before,"after":after,
            "absolute_annual_positive_acceptance_proven":False},indent=2)+'\n')


def test_new_annual_dto_direct_save_is_still_closed_and_does_not_write(env):
    rec=env.create("solar")
    page=env.client.get("/v2/workbook",params={"project":rec.project_code})
    assert page.status_code==200
    tokens=contract_tokens(page.text)
    before=digest()
    response=env.client.post('/v2/workbook/revenue/contracts',headers={"HX-Request":"true"},
        data={"project":rec.project_code,**tokens,"contracts":json.dumps(document())})
    after=digest()
    assert response.status_code==422 and before==after,response.text
    evidence("R04P2-HTTP-CURRENT-REFUSAL",response,before,after,"CURRENT_SCHEMA_REFUSAL_NOT_NEW_CAP_IMPLEMENTATION")
    bad=env.client.post('/v2/workbook/revenue/contracts',data={"project":rec.project_code,**tokens,
        "csrf_token":"invalid","contracts":json.dumps(document())})
    assert bad.status_code==403 and digest()==before
    evidence("R04P2-HTTP-CSRF",bad,before,digest(),"EXISTING_CSRF_GUARD")


def test_new_annual_dto_combined_save_all_rolls_back_the_real_cells_costs_and_receipt(world):
    from app.workbook.revenue_contracts_service import read_document_token
    rec=_project()
    body=_body(rec,world.owner,contracts_json=json.dumps(document(("80","15"))),
        contracts_base_token=read_document_token(OWNER,rec.project_id),
        cells=[{"field_id":"project_setup.technical.p50_hours","value":"1425"}])
    before=digest()
    response=world.owner.post(URL,json=body)
    after=digest()
    assert response.status_code==422 and before==after,response.text
    evidence("R04P2-SAVEALL-CURRENT-ROLLBACK",response,before,after,
             "REAL_ATOMIC_ROLLBACK_NEW_ANNUAL_FORMAT_NOT_ADMITTED")


def test_legacy_share_combined_forecast_save_all_and_replay_keep_existing_semantics(world,monkeypatch):
    from app.workbook.revenue_contracts_service import read_document_token
    monkeypatch.setenv("FINCO_MODEL_REACT_V1","1")
    rec=_project()
    legacy=_contracts_json(world,rec,indexation=.02)
    body=_body(rec,world.owner,contracts_json=legacy,
        contracts_base_token=read_document_token(OWNER,rec.project_id),
        cells=[{"field_id":"project_setup.technical.p50_hours","value":"1425"}])
    before=digest()
    response=world.owner.post(URL,json=body)
    assert response.status_code==200,response.text
    after=digest()
    assert before!=after and response.json()["model_executed"] is False
    assert after["counts"]["model_run_history"]==before["counts"]["model_run_history"]
    evidence("R04P2-LEGACY-COMBINED-SAVEALL",response,before,after,
             "EXISTING_SHARE_BOOK_NOT_ABSOLUTE_QUANTITY")
    replay=world.owner.post(URL,json=body)
    assert replay.status_code==200 and replay.json()["replayed"] and digest()==after,replay.text
    evidence("R04P2-LEGACY-IDEMPOTENT-REPLAY",replay,after,digest(),"EXISTING_SAVEALL_IDEMPOTENCY")


def test_candidate_cannot_smuggle_an_undeclared_p90_writer_through_save_all(world):
    rec=_project()
    body=_body(rec,world.owner,contracts_json=None,cost_lines=[],
        cells=[{"field_id":"project_setup.technical.yield_scenario","value":"P90-10y"}])
    before=digest()
    response=world.owner.post(URL,json=body)
    after=digest()
    assert response.status_code==422 and before==after,response.text
    evidence("R04P2-P90-WRITER-REFUSAL",response,before,after,
             "UNDECLARED_FIELD_REFUSAL_NOT_A_NEW_P90_PERSISTENCE_FEATURE")
