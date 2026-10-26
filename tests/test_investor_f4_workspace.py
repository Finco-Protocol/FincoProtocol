"""Real authorized CAS, canonical Run, history/export and stale lifecycle."""

from tests.model_mutation_csrf import post_valid_mutation

from tests.run_clone_csrf import post_valid_csrf
from copy import deepcopy
from io import BytesIO
import json
import re

import pytest
from openpyxl import load_workbook

from app.model_v2.investor_f4 import EVIDENCE_KEY, SNAPSHOT_KEY
from tests.test_model_decision_workspace_v2 import env, tokens
from tests.test_model_financing_f2 import run
from tests.test_investor_f4_p1 import document


def page(env, record, history_id=None):
    return env.client.get("/v2/workbook/investor/agreement", params={
        "project": record.project_code, **({"history_id": history_id} if history_id else {})})


def save(env, record, doc, *, overrides=None, remove=False):
    html = page(env, record).text
    data = dict(project=record.project_code, action="remove" if remove else "save",
        content_hash=re.search('name="content_hash" value="([^"]*)"', html).group(1),
        csrf_token=re.search('name="csrf_token" value="([^"]*)"', html).group(1),
        agreement=json.dumps(doc))
    data.update(overrides or {})
    return env.client.post("/v2/workbook/investor/agreement", data=data, headers={"HX-Request": "true"})


def funded_agreement(ws):
    doc = document()
    periods = ws.last_sponsor_schedule["periods"]
    keys = ("share_capital_contribution_keur", "share_premium_contribution_keur",
            "other_committed_equity_contribution_keur", "additional_equity_contribution_keur")
    doc["contributions"] = []
    for p in periods:
        paid = sum(p[k] for k in keys)
        if paid:
            doc["contributions"].extend([
                dict(investor_id="alpha", cash_date=p["date"], amount_keur=paid * .6),
                dict(investor_id="beta", cash_date=p["date"], amount_keur=paid * .4)])
    for i, fraction in zip(doc["investors"], (.6, .4)):
        i["commitment_keur"] = ws.last_sponsor_schedule["summary"]["total_legal_equity_contributed_keur"] * fraction + 100
    return doc


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_actual_save_stale_run_current_history_export_and_aggregate_parity(env, kind, monkeypatch):
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.run_history_repository import get_run_history
    record = env.create(kind)
    before, old = run(env, record)
    assert EVIDENCE_KEY not in old.runtime_summary
    assert 'data-testid="f4-evidence-unavailable"' in page(env, record).text
    doc = funded_agreement(before)
    response = save(env, record, doc)
    assert response.status_code == 200, response.text
    assert 'data-state="STALE"' in response.text
    dirty = get_workspace_state("decision-user", record.project_id)
    assert dirty.dirty and dirty.last_runtime_snapshot_id == before.last_runtime_snapshot_id
    assert dirty.last_runtime_summary == before.last_runtime_summary
    assert 'data-state="STALE"' in page(env, record).text
    current, rr = run(env, record)
    evidence = current.last_runtime_summary[EVIDENCE_KEY]
    assert evidence["binding"]["composite_hash"] == current.last_runtime_composite_hash
    assert evidence["binding"]["owner_id"] == "decision-user"
    assert evidence["binding"]["project_id"] == record.project_id
    assert rr.financial_statements == old.financial_statements
    assert rr.debt_schedule == old.debt_schedule
    assert rr.tax_schedule == old.tax_schedule
    assert rr.sponsor_schedule == old.sponsor_schedule
    from app.workbook.runtime_projection import thaw_runtime_payload
    old_summary = thaw_runtime_payload(old.runtime_summary)
    new_summary = thaw_runtime_payload(rr.runtime_summary)
    from m6_economic_parity import independent_economic_view
    old_summary = independent_economic_view(
        old_summary, owner_id="decision-user", project_id=record.project_id,
        snapshot_id=before.last_runtime_snapshot_id,
        composite_hash=before.last_runtime_composite_hash,
        scenario_id=before.last_runtime_scenario_id)
    new_summary = independent_economic_view(
        new_summary, owner_id="decision-user", project_id=record.project_id,
        snapshot_id=current.last_runtime_snapshot_id,
        composite_hash=current.last_runtime_composite_hash,
        scenario_id=current.last_runtime_scenario_id)
    new_summary.pop(EVIDENCE_KEY)
    old_binding = old_summary["financing_evidence"].pop("run_binding")
    new_binding = new_summary["financing_evidence"].pop("run_binding")
    assert old_binding["snapshot_id"] == before.last_runtime_snapshot_id
    assert old_binding["composite_hash"] == before.last_runtime_composite_hash
    assert new_binding["snapshot_id"] == current.last_runtime_snapshot_id
    assert new_binding["composite_hash"] == current.last_runtime_composite_hash
    assert new_summary == old_summary
    assert 'data-state="CURRENT"' in page(env, record).text
    history = get_run_history("decision-user", record.project_id)
    historical = next(h for h in history if h.runtime_snapshot_id == current.last_runtime_snapshot_id)
    captured = deepcopy(historical.runtime_summary[EVIDENCE_KEY])
    doc["version"] = 2
    doc["investors"][0]["ownership_fraction"] = .8
    doc["investors"][1]["ownership_fraction"] = .2
    assert save(env, record, doc).status_code == 200
    assert 'data-state="STALE"' in page(env, record).text
    import app.model_v2.investor_f4 as f4
    monkeypatch.setattr(f4, "run_waterfall", lambda *_: pytest.fail("read-time allocation"))
    monkeypatch.setattr(f4, "robust_xirr", lambda *_: pytest.fail("read-time IRR"))
    assert 'data-state="HISTORICAL"' in page(env, record, historical.history_id).text
    assert 'class="f4-agreement-form"' not in page(env, record, historical.history_id).text
    export = env.client.get("/v2/workbook/investor/export", params={"project": record.project_code,
                            "history_id": historical.history_id})
    assert export.status_code == 200
    wb = load_workbook(BytesIO(export.content))
    assert wb["Investor Accounts"]["B2"].value == .7
    assert get_run_history("decision-user", record.project_id)[0].runtime_summary[EVIDENCE_KEY] == captured
    assert old.runtime_summary == before.last_runtime_summary


@pytest.mark.parametrize("token_kind", ["missing", "forged", "expired"])
def test_csrf_rejected_before_any_mutation(env, token_kind):
    from app.persistence.workspace_repository import get_workspace_state
    from app.auth import CSRF_SECRET
    from itsdangerous import URLSafeTimedSerializer, TimestampSigner
    record = env.create()
    before = get_workspace_state("decision-user", record.project_id)
    token = "" if token_kind == "missing" else "forged"
    if token_kind == "expired":
        class OldSigner(TimestampSigner):
            def get_timestamp(self):
                return super().get_timestamp() - 86401
        token = URLSafeTimedSerializer(CSRF_SECRET, signer=OldSigner).dumps("a" * 48)
    response = save(env, record, document(), overrides={"csrf_token": token})
    assert response.status_code == 403
    assert get_workspace_state("decision-user", record.project_id) == before


def test_owner_project_isolation_and_protected_write_rejection(env):
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.db import get_connection
    record, other = env.create(), env.create("wind")
    before = get_workspace_state("decision-user", other.project_id)
    assert save(env, record, document()).status_code == 200
    assert get_workspace_state("decision-user", other.project_id) == before
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id="f4-other-owner", username="admin"))
    assert page(env, record).status_code == 404
    from app.auth import generate_csrf_token
    response = env.client.post("/v2/workbook/investor/agreement", data=dict(project=record.project_code,
        csrf_token=generate_csrf_token(), action="save", agreement=json.dumps(document()), content_hash="irrelevant"))
    assert response.status_code == 404
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id="decision-user", username="admin"))
    conn = get_connection()
    conn.execute("UPDATE projects SET is_protected=1 WHERE project_id=?", (record.project_id,))
    conn.commit()
    conn.close()
    assert 'class="f4-agreement-form"' not in page(env, record).text
    original = get_workspace_state("decision-user", record.project_id)
    response = env.client.post("/v2/workbook/investor/agreement", data=dict(project=record.project_code,
        csrf_token=generate_csrf_token(), action="remove", content_hash="irrelevant"))
    assert response.status_code == 409
    assert get_workspace_state("decision-user", record.project_id) == original


def test_version_and_concurrent_scalar_saves_reject_stale_agreement_cas(env):
    from app.persistence.workspace_repository import get_workspace_state
    from tests.test_model_financing_f2 import save as scalar_save
    record = env.create()
    assert save(env, record, document()).status_code == 200
    assert save(env, record, document()).status_code == 409
    old_page = page(env, record).text
    old_hash = re.search('name="content_hash" value="([^"]*)"', old_page).group(1)
    assert scalar_save(env, record, "12", field="debt.senior.tenor_years").status_code == 200
    before = get_workspace_state("decision-user", record.project_id)
    doc = document()
    doc["version"] = 2
    assert save(env, record, doc, overrides={"content_hash": old_hash}).status_code == 409
    assert get_workspace_state("decision-user", record.project_id) == before


def test_scenario_isolation_and_selection_cas(env):
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.scenarios_repository import list_scenarios, get_scenario
    record = env.create()
    assert save(env, record, document()).status_code == 200
    base = get_workspace_state("decision-user", record.project_id).draft_snapshot[SNAPSHOT_KEY]
    old = page(env, record).text
    old_hash = re.search('name="content_hash" value="([^"]*)"', old).group(1)
    post_valid_mutation(env.client, '/v2/workbook/scenarios/create', headers={'HX-Request': 'true'},
        data={'project': record.project_code, 'scenario_name': 'Explicit alternative'})
    scenario = next(s for s in list_scenarios('decision-user', record.project_id) if not s.is_base_case)
    post_valid_mutation(env.client, '/v2/workbook/scenarios/select', headers={'HX-Request': 'true'},
        data={'project': record.project_code, 'scenario_id': scenario.scenario_id})
    assert save(env, record, document(), overrides={"content_hash": old_hash}).status_code == 409
    doc = document()
    doc["agreement_id"] = "alternative-common-agreement"
    assert save(env, record, doc).status_code == 200
    assert get_workspace_state("decision-user", record.project_id).draft_snapshot[SNAPSHOT_KEY] == base
    assert json.loads(get_scenario(scenario.scenario_id, 'decision-user').overrides[SNAPSHOT_KEY])["agreement_id"] == doc["agreement_id"]


def test_failed_funding_reconciliation_cannot_commit_a_run(env):
    from app.persistence.workspace_repository import get_workspace_state
    record = env.create()
    before, _ = run(env, record)
    assert save(env, record, document()).status_code == 200
    page_html = env.client.get('/v2/workbook', params={'project': record.project_code}).text
    response = post_valid_csrf(env.client, '/v2/workbook/run', headers={'HX-Request': 'true'},
        data=dict(project=record.project_code, **tokens(page_html)))
    assert "No Run was committed" in response.text
    after = get_workspace_state("decision-user", record.project_id)
    assert after.dirty
    assert after.last_runtime_snapshot_id == before.last_runtime_snapshot_id
    assert after.last_runtime_summary == before.last_runtime_summary


def test_shared_scalar_writer_cannot_bypass_agreement_version_and_scenario_writer(env):
    from tests.test_model_financing_f2 import save as scalar_save
    from app.persistence.workspace_repository import get_workspace_state
    from app.model_v2.investor_f4 import FIELD_ID
    record = env.create()
    env.client.get('/v2/workbook', params={'project': record.project_code})
    before = get_workspace_state("decision-user", record.project_id)
    response = scalar_save(env, record, json.dumps(document()), field=FIELD_ID)
    assert "Use Investor agreement Save" in response.text
    assert get_workspace_state("decision-user", record.project_id) == before


def test_concurrent_read_fails_closed_and_legacy_export_is_unavailable(env, monkeypatch):
    from app.v2.post_run_context import PostRunRequestContext, PostRunContextChanged
    record = env.create()
    assert page(env, record).status_code == 200
    assert env.client.get('/v2/workbook/investor/export', params={'project': record.project_code}).status_code == 409
    monkeypatch.setattr(PostRunRequestContext, "validate_current", lambda *_: (_ for _ in ()).throw(PostRunContextChanged("changed")))
    response = page(env, record)
    assert response.status_code == 200 and "UNAVAILABLE" in response.text
    assert "f4-capital-accounts" not in response.text


def test_scenario_run_binds_its_own_agreement_and_base_history_is_immutable(env):
    from app.persistence.scenarios_repository import list_scenarios
    from app.persistence.run_history_repository import get_run_history
    record = env.create()
    base_ws, _ = run(env, record)
    assert save(env, record, funded_agreement(base_ws)).status_code == 200
    base_ws, _ = run(env, record)
    base_evidence = deepcopy(base_ws.last_runtime_summary[EVIDENCE_KEY])
    post_valid_mutation(env.client, '/v2/workbook/scenarios/create', headers={'HX-Request': 'true'},
        data={'project': record.project_code, 'scenario_name': 'Alternative ownership'})
    scenarios = list_scenarios('decision-user', record.project_id)
    alternative = next(s for s in scenarios if not s.is_base_case)
    base = next(s for s in scenarios if s.is_base_case)
    post_valid_mutation(env.client, '/v2/workbook/scenarios/select', headers={'HX-Request': 'true'},
        data={'project': record.project_code, 'scenario_id': alternative.scenario_id})
    doc = funded_agreement(base_ws)
    doc['agreement_id'] = 'alternative-ownership'
    assert save(env, record, doc).status_code == 200
    scenario_ws, _ = run(env, record)
    evidence = scenario_ws.last_runtime_summary[EVIDENCE_KEY]
    assert evidence['binding']['scenario_id'] == alternative.scenario_id
    assert evidence['agreement']['agreement_id'] == 'alternative-ownership'
    assert 'data-state="CURRENT"' in page(env, record).text
    post_valid_mutation(env.client, '/v2/workbook/scenarios/select', headers={'HX-Request': 'true'},
        data={'project': record.project_code, 'scenario_id': base.scenario_id})
    assert 'data-state="CURRENT"' in page(env, record).text
    restored = next(h for h in get_run_history('decision-user', record.project_id)
                    if h.runtime_snapshot_id == base_ws.last_runtime_snapshot_id)
    assert restored.runtime_summary[EVIDENCE_KEY] == base_evidence
    other = env.create('wind')
    assert page(env, other, restored.history_id).status_code == 404


def test_two_simultaneous_agreement_saves_have_one_cas_winner(env):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.workbook.investor_agreement_service import save_agreement, InvestorAgreementConflict
    from app.persistence.workspace_repository import get_workspace_state
    record = env.create()
    html = page(env, record).text
    expected = re.search('name="content_hash" value="([^"]*)"', html).group(1)
    barrier = Barrier(2)

    def attempt(identity):
        doc = document()
        doc['agreement_id'] = identity
        barrier.wait(timeout=10)
        try:
            save_agreement(owner='decision-user', project_id=record.project_id,
                           expected_hash=expected, raw=json.dumps(doc))
            return 'saved'
        except InvestorAgreementConflict:
            return 'conflict'

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ('agreement-one', 'agreement-two')))
    assert sorted(results) == ['conflict', 'saved']
    assert json.loads(get_workspace_state('decision-user', record.project_id)
                      .draft_snapshot[SNAPSHOT_KEY])['version'] == 1


def test_agreement_edit_during_run_rejects_commit_without_mutating_last_run(env, monkeypatch):
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.run_history_repository import get_run_history
    from app.workbook.investor_agreement_service import save_agreement
    import app.model_v2.investor_f4 as f4
    record = env.create()
    before, _ = run(env, record)
    doc = funded_agreement(before)
    assert save(env, record, doc).status_code == 200
    history = get_run_history('decision-user', record.project_id)
    original = f4.allocate_run

    def concurrent_edit(terms, receipt, *, binding):
        result = original(terms, receipt, binding=binding)
        changed = deepcopy(doc)
        changed['version'] = 2
        changed['investors'][0]['ownership_fraction'] = .8
        changed['investors'][1]['ownership_fraction'] = .2
        save_agreement(owner='decision-user', project_id=record.project_id,
                       expected_hash=binding['composite_hash'], raw=json.dumps(changed))
        return result

    monkeypatch.setattr(f4, 'allocate_run', concurrent_edit)
    html = env.client.get('/v2/workbook', params={'project': record.project_code}).text
    response = post_valid_csrf(env.client, '/v2/workbook/run', headers={'HX-Request': 'true'},
                              data=dict(project=record.project_code, **tokens(html)))
    assert response.status_code == 200
    after = get_workspace_state('decision-user', record.project_id)
    assert after.dirty
    assert after.last_runtime_snapshot_id == before.last_runtime_snapshot_id
    assert after.last_runtime_summary == before.last_runtime_summary
    assert get_run_history('decision-user', record.project_id) == history
