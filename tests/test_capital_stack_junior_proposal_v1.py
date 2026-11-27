"""F3.6: a saved Junior proposal is visible and reviewable but never executable; activation stays closed."""
from dataclasses import replace
import json

from app.workbook import junior_debt_config as junior_config, multisenior_config as config
from finco_core.inputs.financing_instruments import FinancingCollection, InstrumentType
from tests.test_model_decision_workspace_v2 import env  # noqa: F401
from tests.test_model_financing_f2 import save
from tests.test_model_financing_f3_workspace import collection_for_inputs

import pytest


def _proposal(ws):
    from app.workbook.input_set import ProjectInputSet
    pi = ProjectInputSet.from_snapshot(ws.draft_snapshot).to_projectinputs()
    s, j = collection_for_inputs(pi).instruments
    j = replace(j, instrument_type=InstrumentType.JUNIOR_DEBT, seniority_rank=2, fees=(), name="Junior Debt")
    return json.dumps({"schema_version": config.SCHEMA, "scopes": {"base": {
        "proposal": FinancingCollection((s, j)).to_dict(), "activation": None}}})


def test_saved_junior_proposal_renders_read_only_and_never_executes(env):
    from app.persistence.workspace_repository import get_workspace_state
    assert junior_config.ACTIVATION_ENABLED is False
    record = env.create("solar")
    ws = get_workspace_state("decision-user", record.project_id)
    response = save(env, record, _proposal(ws), field=config.FIELD_ID)
    assert response.status_code == 200 and "field-error-banner" not in response.text, response.text[:800]
    studio_resp = env.client.get("/v2/model-react/financing/studio", params={"project": record.project_code})
    assert studio_resp.status_code == 200, studio_resp.text[:300]
    stack = studio_resp.json()["capital_stack"]
    assert stack["status"] == "SAVED PROPOSAL" and stack["junior_activation_closed"] is True
    assert any(r["junior"] and r["type"] == "Junior term loan" for r in stack["rows"])
    assert sum(1 for r in stack["rows"] if r["junior"] and not r["executable"]) == 1
    assert all(not r["executable"] for r in stack["rows"])
    assert any("Junior" in u["name"] and u["status"] == "UNSUPPORTED" for u in stack["unsupported"])
    assert stack["last_run"] is None      # a proposal is never calculated financing
    saved = get_workspace_state("decision-user", record.project_id)
    assert saved.dirty is True and not saved.last_runtime_summary      # no Run happened
    assert json.loads(saved.draft_snapshot[config.SNAPSHOT_KEY])["scopes"]["base"]["activation"] is None
