"""F3.6: a saved Junior proposal is visible and reviewable but never executable; activation stays closed."""
from dataclasses import replace
import json

from app.workbook import junior_debt_config as junior_config, multisenior_config as config
from finco_core.inputs.financing_instruments import FinancingCollection, InstrumentType
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401
from tests.test_model_financing_f2 import save
from tests.test_model_financing_f3_workspace import collection_for_inputs


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
    page = env.client.get("/v2/workbook", params={"project": record.project_code, "sheet": "debt"}).text
    assert "Junior term loan" in page and "Activation closed" in page and "SAVED PROPOSAL" in page
    assert page.count("data-f3-instrument=") == 1               # only the Senior row is a posted instrument
    assert "data-cs-readonly-instrument=" in page
    assert 'data-testid="cs-summary-last-run"' not in page      # a proposal is never calculated financing
    saved = get_workspace_state("decision-user", record.project_id)
    assert saved.dirty is True and not saved.last_runtime_summary      # no Run happened
    assert json.loads(saved.draft_snapshot[config.SNAPSHOT_KEY])["scopes"]["base"]["activation"] is None
