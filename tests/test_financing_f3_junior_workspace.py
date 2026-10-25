"""Existing authorized CAS, scenarios and immutable export; candidate release stays closed."""

from tests.run_clone_csrf import post_valid_csrf
from dataclasses import replace
from io import BytesIO
import json

import pytest

from app.workbook import multisenior_config as config, junior_debt_config as junior_config
from finco_core.inputs.junior_debt import JuniorProjectInputs, JuniorDebtPolicy
from finco_core.inputs.financing_instruments import FinancingCollection, FinancingError, InstrumentType
from tests.test_model_decision_workspace_v2 import env, tokens
from tests.test_model_financing_f2 import save, run
from tests.test_model_financing_f3_workspace import collection_for_inputs
from tests.test_financing_f3_junior_contract import case


def state(pi, scope="base"):
    return json.dumps({"schema_version": config.SCHEMA, "scopes": {scope: {
        "proposal": pi.financing_collection.to_dict(), "activation": {
            "authority": junior_config.AUTHORITY, "proposal_digest": pi.financing_collection.content_digest(),
            "sponsor_funding_mode": "EQUITY_ONLY", "reserve_support_mode": "NONE",
            "junior_policy": pi.junior_debt_policy.to_dict()}}}})


def working_case(ws):
    from app.workbook.input_set import ProjectInputSet
    from finco_core.inputs.junior_debt import activate_collection
    pi = ProjectInputSet.from_snapshot(ws.draft_snapshot).to_projectinputs()
    s, j = collection_for_inputs(pi).instruments
    j = replace(j, instrument_type=InstrumentType.JUNIOR_DEBT, seniority_rank=2, fees=(), name="Junior Debt",
        repayment=replace(j.repayment, grace_months=0))
    return activate_collection(pi, FinancingCollection((s, j)), JuniorDebtPolicy(
        junior_instrument_id=j.instrument_id, day_count="act_360", idc_book_life_years=8,
        idc_tax_treatment="BOOK_BASED_POLICY" if pi.tax.tax_dep_basis_source_owned else "EXCLUDED_BY_EXISTING_POLICY",
        maximum_total_debt_gearing=.8))


def test_candidate_release_closed_no_silent_downgrade():
    from finco_core.inputs.multisenior import deactivate_collection
    pi, _ = case()
    original = deactivate_collection(pi)
    assert junior_config.ACTIVATION_ENABLED is False
    with pytest.raises(FinancingError, match="CANDIDATE_CONTENT_REVIEW_REQUIRED"):
        config.apply_state(original, state(pi), "base")
    assert isinstance(config.apply_state(original, state(pi), "base", enforce_release=False), JuniorProjectInputs)
    view = config.build_view(original, state(pi), "base", None, owner_id="synthetic-owner", project_id="synthetic-project")
    assert not view["available"]
    assert config.apply_state(original, state(pi), "0123456789abcdef") is original


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_actual_cas_run_and_immutable_export(env, monkeypatch, kind):
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.export_service import resolve_canonical_last_run_from_workspace
    from app.services.v2_export_service import build_canonical_last_run_institutional_workbook_export
    from openpyxl import load_workbook
    # Test-only candidate execution; no released governance authority is added.
    monkeypatch.setattr(junior_config, "ACTIVATION_ENABLED", True)
    record = env.create(kind)
    ws = get_workspace_state("decision-user", record.project_id)
    pi = working_case(ws)
    response = save(env, record, state(pi), field=config.FIELD_ID)
    assert response.status_code == 200 and "field-error-banner" not in response.text, response.text[:1500]
    saved = get_workspace_state("decision-user", record.project_id)
    assert saved.dirty and not saved.last_runtime_summary
    assert config.parse_state(saved.draft_snapshot[config.SNAPSHOT_KEY]) == config.parse_state(state(pi))
    committed, rr = run(env, record)
    evidence = rr.runtime_summary["financing_evidence"]
    assert evidence["facility_authority"] == junior_config.AUTHORITY
    assert evidence["junior_facility"]["commitment_keur"] == pi.financing_collection.instruments[1].commitment_keur
    from app.api.v1_1.institutional import get_run_integrity_checks
    integrity_state, integrity = get_run_integrity_checks("decision-user", record.project_id)
    assert integrity_state == "AVAILABLE" and integrity["overall"] == "PASS", integrity
    authority = resolve_canonical_last_run_from_workspace(record, "decision-user", committed)
    assert isinstance(authority.project_inputs, JuniorProjectInputs)
    from app.services import production_financial_authority
    with monkeypatch.context() as guard:
        guard.setattr(production_financial_authority, "run_clean_production", lambda *a, **kw: pytest.fail("Export re-executed engine"))
        result = build_canonical_last_run_institutional_workbook_export("generic_" + kind + "_reference",
            project_record=record, user_id="decision-user")
    assert result.status_code == 200, result.error_content
    wb = load_workbook(BytesIO(result.bytes_data))
    labels = {cell.value for sheet in wb for row in sheet for cell in row if isinstance(cell.value, str)}
    assert {"Junior Interest", "Junior Debt Service", "Junior Debt Balance"} <= labels
    previous = committed.last_runtime_snapshot_id
    newer = json.loads(state(pi))
    newer["scopes"]["base"]["proposal"]["instruments"][1]["interest"]["fixed_rate"] = .08
    newer["scopes"]["base"]["activation"]["proposal_digest"] = "BIND_ON_SAVE"
    response = save(env, record, json.dumps(newer), field=config.FIELD_ID)
    assert "field-error-banner" not in response.text
    stale = get_workspace_state("decision-user", record.project_id)
    assert stale.dirty and stale.last_runtime_snapshot_id == previous
    assert resolve_canonical_last_run_from_workspace(record, "decision-user", stale).project_inputs == authority.project_inputs
    after, new_rr = run(env, record)
    assert not after.dirty and new_rr.snapshot_id != rr.snapshot_id
    assert new_rr.runtime_summary["financing_evidence"]["collection_digest"] != evidence["collection_digest"]


def test_candidate_write_owner_reference_and_cas_isolation(env, monkeypatch):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.update_service import WorkbookUpdateService, ProtectedReferenceError
    from app.workbook.registry import WORKBOOK
    from app.auth import COOKIE_NAME, create_session_token
    monkeypatch.setattr(junior_config, "ACTIVATION_ENABLED", True)
    record, other = env.create(), env.create("wind")
    original = get_workspace_state("decision-user", record.project_id)
    raw = state(working_case(original))
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    original = get_workspace_state("decision-user", record.project_id)
    with pytest.raises(ProtectedReferenceError):
        WorkbookUpdateService.apply_draft_update(ws=original, project_record=replace(record, project_origin="factory_template"),
            field_id=config.FIELD_ID, raw_value=raw, workbook_version=WORKBOOK.version, content_hash="before-cas")
    assert get_workspace_state("decision-user", record.project_id) == original
    assert "field-error-banner" not in save(env, record, raw, field=config.FIELD_ID).text
    saved = get_workspace_state("decision-user", record.project_id)
    assert config.SNAPSHOT_KEY not in get_workspace_state("decision-user", other.project_id).draft_snapshot
    save(env, record, raw, field=config.FIELD_ID, stale_tokens=tokens(page.text))
    assert get_workspace_state("decision-user", record.project_id) == saved
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id="junior-other-owner", username="admin"))
    response = env.client.post("/v2/workbook/update", data=dict(project=record.project_code,
        field_id=config.FIELD_ID, value=raw, sheet_id="debt", **tokens(page.text)))
    assert response.status_code == 404


def test_scope_and_policy_binding_cannot_be_tampered():
    pi, _ = case()
    raw = state(pi)
    with pytest.raises(FinancingError, match="CROSS_SCENARIO"):
        config.validate_transition(None, raw, "0123456789abcdef")
    tampered = json.loads(raw)
    tampered["scopes"]["base"]["activation"]["proposal_digest"] = "0" * 64
    with pytest.raises(FinancingError, match="BINDING_INVALID"):
        config.parse_state(json.dumps(tampered))


def test_unfundable_run_preserves_immutable_last_run(env, monkeypatch, caplog):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import run_operating_model
    from finco_core.inputs.financing_instruments import RepaymentMode
    monkeypatch.setattr(junior_config, "ACTIVATION_ENABLED", True)
    record = env.create()
    prior, previous = run(env, record)
    pi = working_case(prior)
    periods = run_operating_model(from_project_inputs(pi)).periods
    first = next(p.period_end for p in periods if p.is_operation)
    s, j = pi.financing_collection.instruments
    j = replace(j, repayment=replace(j.repayment, mode=RepaymentMode.BULLET,
        grace_months=0, maturity_date=first))
    raw = state(replace(pi, financing_collection=FinancingCollection((s, j))))
    assert "field-error-banner" not in save(env, record, raw, field=config.FIELD_ID).text
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    before = get_workspace_state("decision-user", record.project_id)
    response = post_valid_csrf(env.client, "/v2/workbook/run", headers={"HX-Request": "true"},
        data=dict(project=record.project_code, **tokens(page.text)))
    after = get_workspace_state("decision-user", record.project_id)
    assert "v2-banner-error" in response.text
    assert "F35_CONTRACTUAL_SERVICE_CASH_SHORTFALL" in caplog.text
    assert after.dirty and after.last_runtime_snapshot_id == prior.last_runtime_snapshot_id
    assert after.last_runtime_summary == before.last_runtime_summary
    assert WorkbookService.get_runtime_result(after) == previous


def test_scenario_activation_isolated_from_base_history(env, monkeypatch):
    from app.persistence.scenarios_repository import list_scenarios
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.export_service import resolve_canonical_last_run_from_workspace
    monkeypatch.setattr(junior_config, "ACTIVATION_ENABLED", True)
    record = env.create("wind")
    base, base_rr = run(env, record)
    env.client.post("/v2/workbook/scenarios/create", headers={"HX-Request": "true"},
        data={"project": record.project_code, "scenario_name": "Junior financing case"})
    scenarios = list_scenarios("decision-user", record.project_id)
    scenario = next(s for s in scenarios if not s.is_base_case)
    env.client.post("/v2/workbook/scenarios/select", headers={"HX-Request": "true"},
        data={"project": record.project_code, "scenario_id": scenario.scenario_id})
    selected = get_workspace_state("decision-user", record.project_id)
    pi = working_case(selected)
    assert "field-error-banner" not in save(env, record, state(pi, scenario.scenario_id), field=config.FIELD_ID).text
    committed, rr = run(env, record)
    assert rr.snapshot_id != base_rr.snapshot_id
    assert isinstance(resolve_canonical_last_run_from_workspace(record, "decision-user", committed).project_inputs,
                      JuniorProjectInputs)
    base_scenario = next(s for s in scenarios if s.is_base_case)
    env.client.post("/v2/workbook/scenarios/select", headers={"HX-Request": "true"},
        data={"project": record.project_code, "scenario_id": base_scenario.scenario_id})
    restored = get_workspace_state("decision-user", record.project_id)
    assert restored.last_runtime_snapshot_id == base.last_runtime_snapshot_id
    assert restored.last_runtime_summary == base.last_runtime_summary
    assert restored.dirty and not restored.last_runtime_snapshot
    with pytest.raises(ValueError, match="last-run snapshot is missing"):
        resolve_canonical_last_run_from_workspace(record, "decision-user", restored)
    # The Base authority remains inactive; no scenario-only financing is inherited.
    from app.workbook.input_set import ProjectInputSet
    ordinary = ProjectInputSet.from_snapshot(restored.draft_snapshot).to_projectinputs()
    assert config.apply_state(ordinary, restored.draft_snapshot[config.SNAPSHOT_KEY], "base") is ordinary
