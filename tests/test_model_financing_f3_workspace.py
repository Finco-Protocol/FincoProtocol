"""Versioned proposals, explicit activation, scope-bound CAS and real Last Run."""
import json
from dataclasses import replace

import pytest

from app.workbook import multisenior_config as config
from finco_core.inputs.multisenior import AUTHORITY, MultiSeniorProjectInputs
from finco_core.inputs.financing_instruments import FinancingError
from tests.test_financing_f3_multisenior import case
from tests.test_model_decision_workspace_v2 import env, tokens
from tests.test_model_financing_f2 import save, run


def state(*, active=False, scope="base", collection=None):
    collection = collection or case()[0].financing_collection
    activation = None if not active else dict(authority=AUTHORITY,
        proposal_digest=collection.content_digest(), sponsor_funding_mode="EQUITY_ONLY", reserve_support_mode="NONE")
    return json.dumps(dict(schema_version=config.SCHEMA, scopes={scope: dict(proposal=collection.to_dict(), activation=activation)}))


def collection_for_inputs(pi):
    """Small independently specified commitments on this actual Working Copy axis."""
    from datetime import timedelta
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import _build_period_engine
    from finco_core.inputs.financing_instruments import FinancingCollection, DrawdownEntry
    periods = _build_period_engine(from_project_inputs(pi)).periods()
    construction = [p for p in periods if p.is_construction]
    op = [p for p in periods if p.is_operation]
    template = case()[0].financing_collection
    instruments = tuple(replace(i, commitment_keur=pi.capex.hard_capex_keur * fraction,
        drawdowns=(DrawdownEntry(construction[0].start_date + timedelta(days=index), pi.capex.hard_capex_keur * fraction),),
        repayment=replace(i.repayment, maturity_date=op[maturity - 1].end_date))
        for index, (i, fraction, maturity) in enumerate(zip(template.instruments, (.06, .04), (16, 20))))
    return FinancingCollection(instruments)


@pytest.mark.parametrize("bad", ['[]', '{"schema_version":"future","scopes":{}}',
    '{"schema_version":"f3-workspace-1.0","scopes":{},"x":1}',
    '{"schema_version":"f3-workspace-1.0","schema_version":"f3-workspace-1.0","scopes":{}}'])
def test_bad_version_and_shape_rejected(bad):
    with pytest.raises(FinancingError):
        config.parse_state(bad)


def test_proposal_inert_activation_gated_and_digest_bound_only_on_write(monkeypatch):
    monkeypatch.setattr(config, "ACTIVATION_ENABLED", False)
    pi, _ = case()
    from finco_core.inputs.multisenior import deactivate_collection
    legacy = deactivate_collection(pi)
    assert config.apply_state(legacy, state(), "base") is legacy
    with pytest.raises(FinancingError, match="ACCEPTANCE_BLOCKED"):
        config.apply_state(legacy, state(active=True), "base")
    active = config.apply_state(legacy, state(active=True), "base", enforce_release=False)
    assert isinstance(active, MultiSeniorProjectInputs)
    request = json.loads(state(active=True))
    request["scopes"]["base"]["activation"]["proposal_digest"] = "BIND_ON_SAVE"
    with pytest.raises(FinancingError):
        config.parse_state(json.dumps(request))
    assert config.parse_state(config.canonical_json(json.dumps(request))) == config.parse_state(state(active=True))
    assert config.canonical_json(config.canonical_json(state())) == config.canonical_json(state())


def test_instrument_ids_and_foreign_scenario_changes_rejected():
    old = state()
    request = json.loads(old)
    request["scopes"]["base"]["proposal"]["instruments"][0]["instrument_id"] = "different-id"
    with pytest.raises(FinancingError, match="ID_MUTATION"):
        config.validate_transition(old, json.dumps(request), "base")
    request = json.loads(old)
    request["scopes"]["base"]["proposal"]["instruments"][0]["name"] = "Other"
    with pytest.raises(FinancingError, match="CROSS_SCENARIO"):
        config.validate_transition(old, json.dumps(request), "0123456789abcdef0123456789abcdef")


def test_no_sheet_open_financial_execution(monkeypatch):
    from financial_engine import orchestrator
    pi, _ = case()
    def forbidden(*args, **kwargs):
        pytest.fail("Opening the sheet executed a model")
    monkeypatch.setattr(orchestrator, "run_operating_model", forbidden)
    monkeypatch.setattr(orchestrator, "run_senior_debt_model", forbidden)
    assert len(config.build_view(pi, None, "base", None)["entry"]["proposal"]["instruments"]) == 2


def test_proposal_save_reload_cas_and_blocked_activation_are_real(env, monkeypatch):
    monkeypatch.setattr(config, "ACTIVATION_ENABLED", False)
    from app.persistence.workspace_repository import get_workspace_state
    record = env.create()
    page = env.client.get('/v2/workbook', params={'project': record.project_code})
    assert 'f3-activation-blocked' in page.text
    old_tokens = tokens(page.text)
    response = save(env, record, state(), field=config.FIELD_ID)
    assert response.status_code == 200 and 'field-error-banner' not in response.text
    ws = get_workspace_state('decision-user', record.project_id)
    assert config.parse_state(ws.draft_snapshot[config.SNAPSHOT_KEY]) == config.parse_state(state())
    assert ws.dirty and not ws.last_runtime_summary
    stored = ws
    save(env, record, state(active=True), field=config.FIELD_ID)
    assert get_workspace_state('decision-user', record.project_id) == stored
    save(env, record, state(), field=config.FIELD_ID, stale_tokens=old_tokens)
    assert get_workspace_state('decision-user', record.project_id) == stored
    page = env.client.get('/v2/workbook', params={'project': record.project_code, 'sheet': 'debt'})
    assert 'senior-a' in page.text and 'senior-b' in page.text


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_real_active_save_run_export_and_stale_last_run_binding(env, monkeypatch, kind):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.input_set import ProjectInputSet
    from app.services.export_service import resolve_canonical_last_run_from_workspace
    monkeypatch.setattr(config, "ACTIVATION_ENABLED", True)
    record = env.create(kind)
    # The amounts must belong to this actual scaled Working Copy, not a fixture's factory.
    ws = get_workspace_state('decision-user', record.project_id)
    pi = ProjectInputSet.from_snapshot(ws.draft_snapshot).to_projectinputs()
    raw = state(active=True, collection=collection_for_inputs(pi))
    response = save(env, record, raw, field=config.FIELD_ID)
    assert 'field-error-banner' not in response.text, response.text[:2000]
    committed, rr = run(env, record)
    evidence = rr.runtime_summary['financing_evidence']
    assert len(evidence['facility_schedules']) == 2
    assert evidence['facility_authority'] == AUTHORITY
    from app.v2.financing_sources_uses_router import router as sources_uses_router
    if not any(getattr(route, 'path', '') == '/v2/financing/sources-uses' for route in env.client.app.routes):
        env.client.app.include_router(sources_uses_router, prefix='/v2')
    su_page = env.client.get('/v2/financing/sources-uses', params={'project': record.project_code})
    assert su_page.status_code == 200, su_page.text
    assert 'Senior debt (contractual)' in su_page.text
    from finco_core.inputs import SponsorFundingMode
    assert SponsorFundingMode.EQUITY_ONLY.value in su_page.text
    export = resolve_canonical_last_run_from_workspace(record, 'decision-user', committed)
    assert isinstance(export.project_inputs, MultiSeniorProjectInputs)
    digest = export.project_inputs.financing_collection.content_digest()
    original_snapshot_id = committed.last_runtime_snapshot_id
    newer = json.loads(raw)
    newer['scopes']['base']['proposal']['instruments'][0]['interest']['fixed_rate'] = .05
    newer['scopes']['base']['activation']['proposal_digest'] = 'BIND_ON_SAVE'
    save(env, record, json.dumps(newer), field=config.FIELD_ID)
    latest = get_workspace_state('decision-user', record.project_id)
    assert latest.dirty and latest.last_runtime_snapshot_id == original_snapshot_id
    from app.services.export_service import _resolve_preview_working_path
    preview = _resolve_preview_working_path(record, 'decision-user', latest)
    assert isinstance(preview.project_inputs, MultiSeniorProjectInputs)
    assert preview.project_inputs.financing_collection.content_digest() != digest
    assert preview.run_id is None
    assert resolve_canonical_last_run_from_workspace(record, 'decision-user', latest).project_inputs.financing_collection.content_digest() == digest
    page = env.client.get('/v2/workbook', params={'project': record.project_code, 'sheet': 'debt'})
    assert 'Last Run facility schedules' in page.text
    after, rr2 = run(env, record)
    assert not after.dirty and rr2.snapshot_id != rr.snapshot_id
    assert rr2.runtime_summary['financing_evidence']['collection_digest'] != digest


def test_scopes_do_not_inherit_or_accept_foreign_writes_after_scenario_selection(env):
    from app.persistence.scenarios_repository import list_scenarios
    from app.persistence.workspace_repository import get_workspace_state
    record = env.create()
    assert save(env, record, state(), field=config.FIELD_ID).status_code == 200
    env.client.post('/v2/workbook/scenarios/create', headers={'HX-Request': 'true'},
        data={'project': record.project_code, 'scenario_name': 'Independent financing'})
    scenario = next(s for s in list_scenarios('decision-user', record.project_id) if not s.is_base_case)
    env.client.post('/v2/workbook/scenarios/select', headers={'HX-Request': 'true'},
        data={'project': record.project_code, 'scenario_id': scenario.scenario_id})
    ws = get_workspace_state('decision-user', record.project_id)
    selected_scope = config.scope_for_workspace(ws)
    assert selected_scope == scenario.scenario_id
    from app.workbook.input_set import ProjectInputSet
    pi = ProjectInputSet.from_snapshot(ws.draft_snapshot).to_projectinputs()
    assert config.apply_state(pi, state(active=True), selected_scope) is pi
    previous = ws
    bad = json.loads(state())
    bad['scopes']['base']['proposal']['instruments'][0]['name'] = 'Foreign Base edit'
    response = save(env, record, json.dumps(bad), field=config.FIELD_ID)
    assert 'CROSS_SCENARIO' in response.text
    assert get_workspace_state('decision-user', record.project_id) == previous
    request = json.loads(state())
    request['scopes'][selected_scope] = json.loads(state(scope=selected_scope))['scopes'][selected_scope]
    save(env, record, json.dumps(request), field=config.FIELD_ID)
    current = get_workspace_state('decision-user', record.project_id)
    assert set(config.parse_state(current.draft_snapshot[config.SNAPSHOT_KEY])['scopes']) == {'base', selected_scope}
    assert config.parse_state(current.draft_snapshot[config.SNAPSHOT_KEY])['scopes']['base'] == json.loads(state())['scopes']['base']


def test_cross_owner_protected_reference_and_unrelated_project_are_isolated(env):
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.update_service import WorkbookUpdateService, ProtectedReferenceError
    from app.workbook.registry import WORKBOOK
    record, other = env.create(), env.create('wind')
    page = env.client.get('/v2/workbook', params={'project': record.project_code})
    original = get_workspace_state('decision-user', record.project_id)
    with pytest.raises(ProtectedReferenceError):
        WorkbookUpdateService.apply_draft_update(ws=original,
            project_record=replace(record, project_origin='factory_template'), field_id=config.FIELD_ID,
            raw_value=state(), workbook_version=WORKBOOK.version, content_hash='before-cas')
    assert get_workspace_state('decision-user', record.project_id) == original
    save(env, record, state(), field=config.FIELD_ID)
    assert config.SNAPSHOT_KEY not in get_workspace_state('decision-user', other.project_id).draft_snapshot
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id='f3-other-owner', username='admin'))
    response = env.client.post('/v2/workbook/update', data=dict(project=record.project_code,
        field_id=config.FIELD_ID, value=state(), sheet_id='debt', **tokens(page.text)))
    assert response.status_code == 404


def test_selected_scope_changes_invalidate_pre_selection_cas_token(env):
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.scenarios_repository import list_scenarios
    record = env.create()
    page = env.client.get('/v2/workbook', params={'project': record.project_code})
    env.client.post('/v2/workbook/scenarios/create', headers={'HX-Request': 'true'},
        data={'project': record.project_code, 'scenario_name': 'Concurrent selection'})
    scenario = next(s for s in list_scenarios('decision-user', record.project_id) if not s.is_base_case)
    env.client.post('/v2/workbook/scenarios/select', headers={'HX-Request': 'true'},
        data={'project': record.project_code, 'scenario_id': scenario.scenario_id})
    before = get_workspace_state('decision-user', record.project_id)
    save(env, record, state(), field=config.FIELD_ID, stale_tokens=tokens(page.text))
    assert get_workspace_state('decision-user', record.project_id) == before


def test_active_configuration_locks_competing_editor_and_export_corruption_fails_closed(env, monkeypatch):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.input_set import ProjectInputSet
    from app.services.export_service import resolve_canonical_last_run_from_workspace
    monkeypatch.setattr(config, 'ACTIVATION_ENABLED', True)
    record = env.create()
    pi = ProjectInputSet.from_snapshot(get_workspace_state('decision-user', record.project_id).draft_snapshot).to_projectinputs()
    raw = state(active=True, collection=collection_for_inputs(pi))
    save(env, record, raw, field=config.FIELD_ID)
    before = get_workspace_state('decision-user', record.project_id)
    assert 'COMPETING_FINANCING_EDITOR' in save(env, record, '12', field='debt.senior.tenor_years').text
    assert get_workspace_state('decision-user', record.project_id) == before
    committed, _ = run(env, record)
    summary = dict(committed.last_runtime_summary)
    summary['financing_evidence'] = dict(summary['financing_evidence'], collection_digest='corrupt')
    with pytest.raises(ValueError, match='collection does not match'):
        resolve_canonical_last_run_from_workspace(record, 'decision-user', replace(committed, last_runtime_summary=summary))


def test_f3_template_protected_and_no_context_safe():
    from app.v2.router import _templates
    pi, _ = case()
    view = config.build_view(pi, state(), 'base', None)
    template = _templates.get_template('partials/_financing_multisenior.html')
    assert 'read-only' in template.render(multisenior=view, project_editable=False)
    assert 'data-f3-form' not in template.render(multisenior=view, project_editable=False)
    assert template.render() == ''
