"""RC-5 / S7-01 + S7-10: Run artifact integrity vs proven effective-input application; duplicate Rename prevention."""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from app.workbook.effective_input_evidence import (
    ESTABLISHED, NOT_APPLICABLE, NOT_ESTABLISHED, SCHEMA, build_effective_input_evidence, resolve_effective_input_evidence)
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401  (fixture)
from tests.test_model_financing_f2 import run

USER = "decision-user"
HX = {"HX-Request": "true"}
EDITOR_FIELDS = ["tariff_eur_mwh", "p50_hours", "opex_y1_keur", "total_capex_keur", "gearing_pct", "interest_rate_pct",
                 "tenor_years", "target_dscr"]
TARIFF_EVIDENCE = {"authority": "materialized_project_inputs", "effective_tariff_eur_mwh": 61.5, "scenario_id": "s"}


# ── pure classification: all eight exposed fields ─────────────────────────────────────────────────────────────────────────

def test_editor_fields_are_the_eight_exposed_overrides():
    from app.v2.scenario_presentation import OVERRIDE_EDITOR_FIELDS
    assert sorted(k for k, _l, _u in OVERRIDE_EDITOR_FIELDS) == sorted(EDITOR_FIELDS)


def test_tariff_is_established_only_with_matching_canonical_binding_evidence():
    ok = build_effective_input_evidence(overrides={"tariff_eur_mwh": 61.5}, scenario_revenue_input=TARIFF_EVIDENCE)
    assert (ok["status"], ok["bound_fields"], ok["unbound_fields"]) == (ESTABLISHED, ["tariff_eur_mwh"], [])
    for evidence in (None, {}, {**TARIFF_EVIDENCE, "effective_tariff_eur_mwh": 60.0}, {**TARIFF_EVIDENCE, "authority": "other"},
                     {"effective_tariff_eur_mwh": 61.5}):
        bad = build_effective_input_evidence(overrides={"tariff_eur_mwh": 61.5}, scenario_revenue_input=evidence)
        assert (bad["status"], bad["bound_fields"], bad["unbound_fields"]) == (NOT_ESTABLISHED, [], ["tariff_eur_mwh"])


@pytest.mark.parametrize("field", EDITOR_FIELDS[1:])
def test_every_other_exposed_field_is_never_claimed_as_applied(field):
    # Even with tariff evidence present and a Q4 binding for a DIFFERENT key, an unproven field stays unproven.
    q4 = {"authority": "q4_canonical_reviewed_scenario_v1", "snapshot_key": "other_key", "value": 1.0}
    block = build_effective_input_evidence(overrides={field: 1.0}, scenario_revenue_input=TARIFF_EVIDENCE, q4_effective_input=q4)
    assert block["status"] == NOT_ESTABLISHED and block["unbound_fields"] == [field] and block["bound_fields"] == []


@pytest.mark.parametrize("field", ["gearing_pct", "target_dscr"])
def test_reviewed_q4_what_if_is_established_by_its_own_binding_only(field):
    q4 = {"authority": "q4_canonical_reviewed_scenario_v1", "snapshot_key": field, "value": 1.35}
    assert build_effective_input_evidence(overrides={field: 1.35}, q4_effective_input=q4)["status"] == ESTABLISHED
    assert build_effective_input_evidence(overrides={field: 1.40}, q4_effective_input=q4)["status"] == NOT_ESTABLISHED
    assert build_effective_input_evidence(overrides={field: 1.35})["status"] == NOT_ESTABLISHED


def test_mixed_overrides_are_not_established_and_name_the_unproven_field():
    block = build_effective_input_evidence(overrides={"tariff_eur_mwh": 61.5, "gearing_pct": 55.0}, scenario_revenue_input=TARIFF_EVIDENCE)
    assert block["status"] == NOT_ESTABLISHED
    assert block["bound_fields"] == ["tariff_eur_mwh"] and block["unbound_fields"] == ["gearing_pct"]


def test_no_overrides_is_not_applicable_and_unrecorded_overrides_are_never_none():
    assert build_effective_input_evidence(overrides={})["status"] == NOT_APPLICABLE
    for unknown in (None, "x", 3):
        block = build_effective_input_evidence(overrides=unknown)
        assert block["status"] == NOT_ESTABLISHED and block["overrides_at_run"] is None


def test_revenue_contract_payload_requires_the_exact_recorded_contract():
    contract = '{"streams":[1]}'
    evidence = {"authority": "materialized_project_inputs", "multistream_config_json": contract}
    assert build_effective_input_evidence(overrides={"rev_multistream_config_json": contract}, scenario_revenue_input=evidence)["status"] == ESTABLISHED
    assert build_effective_input_evidence(overrides={"rev_multistream_config_json": '{"streams":[2]}'}, scenario_revenue_input=evidence)["status"] == NOT_ESTABLISHED
    assert build_effective_input_evidence(overrides={"bess_native_config_json": "{}"}, scenario_revenue_input=evidence)["status"] == NOT_ESTABLISHED


# ── historical resolution reads only evidence recorded with the same Run ─────────────────────────────────────────────────

def _ws(summary=None, *, snapshot="snap-1", scenario="sc-1"):
    return SimpleNamespace(last_runtime_summary=summary, last_runtime_snapshot_id=snapshot, last_runtime_scenario_id=scenario, user_id=USER)


def test_stored_block_is_reported_exactly_as_recorded():
    block = build_effective_input_evidence(overrides={"tariff_eur_mwh": 61.5}, scenario_revenue_input=TARIFF_EVIDENCE)
    assert resolve_effective_input_evidence(_ws({"effective_input_evidence": block})) == block


def test_historical_run_without_a_block_is_explicitly_not_established_not_applied():
    for scenario_summary in ({"snapshot_id": "other", "scenario_overrides_at_run": {"tariff_eur_mwh": 61.5}},
                             {"snapshot_id": "snap-1"}):
        got = resolve_effective_input_evidence(_ws({}), scenario_run_summary=scenario_summary)
        assert got["status"] == NOT_ESTABLISHED and got["reason"] == "RUN_PREDATES_EFFECTIVE_INPUT_EVIDENCE"
        assert got["bound_fields"] == [] and got["overrides_at_run"] is None


def test_historical_run_uses_only_its_own_recorded_scenario_evidence():
    legacy = {"snapshot_id": "snap-1", "scenario_overrides_at_run": {"gearing_pct": 55.0}, "scenario_revenue_input": TARIFF_EVIDENCE}
    got = resolve_effective_input_evidence(_ws({}), scenario_run_summary=legacy)
    assert got["status"] == NOT_ESTABLISHED and got["unbound_fields"] == ["gearing_pct"] and got["basis"] == "historical_run_evidence"
    good = {"snapshot_id": "snap-1", "scenario_overrides_at_run": {"tariff_eur_mwh": 61.5}, "scenario_revenue_input": TARIFF_EVIDENCE}
    assert resolve_effective_input_evidence(_ws({}), scenario_run_summary=good)["status"] == ESTABLISHED
    base = {"snapshot_id": "snap-1", "scenario_overrides_at_run": {}}
    assert resolve_effective_input_evidence(_ws({}), scenario_run_summary=base)["status"] == NOT_APPLICABLE


def test_run_without_a_scenario_applied_nothing_and_unreadable_evidence_fails_closed(monkeypatch):
    assert resolve_effective_input_evidence(_ws({}, scenario=None))["status"] == NOT_APPLICABLE
    import app.persistence.scenarios_repository as repo
    monkeypatch.setattr(repo, "get_scenario", lambda **kw: (_ for _ in ()).throw(RuntimeError("db down")))
    got = resolve_effective_input_evidence(_ws({}))
    assert got["status"] == NOT_ESTABLISHED and got["reason"] == "SCENARIO_EVIDENCE_UNREADABLE"
    monkeypatch.setattr(repo, "get_scenario", lambda **kw: None)
    assert resolve_effective_input_evidence(_ws({}))["reason"] == "SCENARIO_EVIDENCE_UNREADABLE"


# ── real Solar / Wind Runs: recorded at commit, in the certificate payload, historical Runs untouched ─────────────────────

def _create(env, record, name):
    return env.client.post("/v2/workbook/scenarios/create", headers=HX, data={"project": record.project_code, "scenario_name": name})


def _child(record, name=None):
    from app.persistence.scenarios_repository import list_scenarios
    return next(s for s in list_scenarios(USER, record.project_id) if not s.is_base_case and (name is None or s.scenario_name == name))


def _ws_now(record):
    from app.persistence.workspace_repository import get_workspace_state
    return get_workspace_state(USER, record.project_id)


def _tariff(ws):
    snapshot = ws.draft_snapshot
    return float(snapshot["rev_ppa_base_tariff"] if "rev_ppa_base_tariff" in snapshot else snapshot["tariff_eur_mwh"])


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_real_runs_record_evidence_and_certificate_separates_integrity_from_effectiveness(env, kind):
    from app.services.run_certificate_service import build_certificate_payload, _canonical_json_bytes
    record = env.create(kind)
    base_ws, base_rr = run(env, record)
    assert base_ws.last_runtime_summary["effective_input_evidence"]["status"] == NOT_APPLICABLE
    payload = build_certificate_payload(_ws_now(record))
    assert payload["effective_input_evidence"]["status"] == NOT_APPLICABLE
    _create(env, record, "Upside")
    child = _child(record)
    value = round(_tariff(base_ws) * 1.12, 4)
    assert env.client.post("/v2/workbook/scenarios/update-overrides", headers=HX, data={
        "project": record.project_code, "scenario_id": child.scenario_id, "tariff_eur_mwh": str(value)}).status_code == 200
    run(env, record)
    committed = _ws_now(record)
    block = committed.last_runtime_summary["effective_input_evidence"]
    assert (block["schema"], block["status"], block["bound_fields"], block["unbound_fields"]) == (SCHEMA, ESTABLISHED, ["tariff_eur_mwh"], [])
    assert block["overrides_at_run"] == {"tariff_eur_mwh": value}
    cert = build_certificate_payload(committed)
    assert cert["effective_input_evidence"] == block
    # The evidence block is part of the signed bytes: altering it changes the canonical payload.
    tampered = copy.deepcopy(cert)
    tampered["effective_input_evidence"]["status"] = NOT_APPLICABLE
    assert _canonical_json_bytes(tampered) != _canonical_json_bytes(cert)
    # Editing the override afterwards never rewrites what the committed Run proved.
    assert env.client.post("/v2/workbook/scenarios/update-overrides", headers=HX, data={
        "project": record.project_code, "scenario_id": child.scenario_id, "tariff_eur_mwh": str(value + 3)}).status_code == 200
    assert _ws_now(record).last_runtime_summary["effective_input_evidence"] == block
    assert build_certificate_payload(_ws_now(record))["effective_input_evidence"]["overrides_at_run"] == {"tariff_eur_mwh": value}


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_pre_rc5_run_resolves_from_its_own_scenario_record_and_is_never_rewritten(env, kind):
    from app.persistence.scenarios_repository import get_scenario
    record = env.create(kind)
    base_ws, _ = run(env, record)
    _create(env, record, "Upside")
    child = _child(record)
    value = round(_tariff(base_ws) * 1.1, 4)
    env.client.post("/v2/workbook/scenarios/update-overrides", headers=HX, data={
        "project": record.project_code, "scenario_id": child.scenario_id, "tariff_eur_mwh": str(value)})
    run(env, record)
    ws = _ws_now(record)
    # Reproduce a pre-RC-5 workspace summary: the same committed Run without the block.
    legacy_summary = {k: v for k, v in ws.last_runtime_summary.items() if k != "effective_input_evidence"}
    legacy = SimpleNamespace(last_runtime_summary=legacy_summary, last_runtime_snapshot_id=ws.last_runtime_snapshot_id,
                             last_runtime_scenario_id=ws.last_runtime_scenario_id, user_id=USER)
    before = (copy.deepcopy(legacy_summary), ws.last_runtime_composite_hash, ws.last_runtime_snapshot_id)
    got = resolve_effective_input_evidence(legacy)
    assert got["status"] == ESTABLISHED and got["basis"] == "historical_run_evidence" and got["bound_fields"] == ["tariff_eur_mwh"]
    assert (legacy_summary, ws.last_runtime_composite_hash, ws.last_runtime_snapshot_id) == before
    # A legacy Run that recorded an override the engine never consumed is NOT claimed effective.
    record_summary = dict(get_scenario(child.scenario_id, USER).last_run_summary)
    record_summary["scenario_overrides_at_run"] = {"gearing_pct": 55.0}
    got = resolve_effective_input_evidence(legacy, scenario_run_summary=record_summary)
    assert got["status"] == NOT_ESTABLISHED and got["unbound_fields"] == ["gearing_pct"]


def test_certificate_fragment_states_integrity_and_effectiveness_separately():
    from app.v2.router import _templates
    template = _templates.get_template("partials/_trust_certificate_body.html")
    base = {"state": "AVAILABLE", "authority": "signed provenance", "schema_version": "v1", "key_id": "k", "payload_digest": "d"}
    established = template.render({"trust_certificate": {**base, "effective_input_status": ESTABLISHED}})
    assert 'data-testid="trust-pack-certificate-effective-inputs">ESTABLISHED' in established
    assert "not that scenario overrides were applied" in established
    legacy = template.render({"trust_certificate": {**base, "effective_input_status": NOT_ESTABLISHED, "effective_input_unbound": ["gearing_pct"]}})
    assert NOT_ESTABLISHED in legacy and "gearing_pct" in legacy and "Effectiveness is not established" in legacy
    missing = template.render({"trust_certificate": base})
    assert NOT_ESTABLISHED in missing                    # an absent status is never rendered as applied


# ── S7-10: duplicate Rename prevention inside the repository transaction ─────────────────────────────────────────────────

def _rename(env, record, scenario, name):
    return env.client.post("/v2/workbook/scenarios/rename", headers=HX, data={
        "project": record.project_code, "scenario_id": scenario.scenario_id, "new_name": name})


def _names(record):
    from app.persistence.scenarios_repository import list_scenarios
    return sorted(s.scenario_name for s in list_scenarios(USER, record.project_id) if not s.is_base_case)


def test_rename_to_an_existing_name_is_rejected_without_a_write(env):
    record = env.create("solar")
    _create(env, record, "Upside")
    _create(env, record, "Downside")
    down = _child(record, "Downside")
    for attempt in ("Upside", "upside", "  UPSIDE  "):
        response = _rename(env, record, down, attempt)
        assert response.status_code == 409 and response.json()["code"] == "SCENARIO_NAME_DUPLICATE"
    assert _names(record) == ["Downside", "Upside"]
    assert _rename(env, record, down, "Stress").status_code == 200
    assert _names(record) == ["Stress", "Upside"]


def test_rename_own_name_case_change_and_repeated_submission_are_safe(env):
    record = env.create("solar")
    _create(env, record, "Upside")
    up = _child(record, "Upside")
    assert _rename(env, record, up, "UPSIDE").status_code == 200
    assert _rename(env, record, up, "UPSIDE").status_code == 200       # idempotent resubmission of the same rename
    assert _names(record) == ["UPSIDE"]


def test_rename_ignores_archived_base_and_other_project_names(env):
    one, two = env.create("solar"), env.create("wind")
    _create(env, one, "Upside")
    _create(env, one, "Draft")
    _create(env, two, "Upside")
    draft = _child(one, "Draft")
    assert _rename(env, one, draft, "Upside").status_code == 409
    up = _child(one, "Upside")
    assert env.client.post("/v2/workbook/scenarios/archive", headers=HX, data={
        "project": one.project_code, "scenario_id": up.scenario_id}).status_code == 200
    assert _rename(env, one, draft, "Upside").status_code == 200       # an archived name is reusable
    assert _names(two) == ["Upside"]                                   # a clash in another project is irrelevant


def test_rename_repository_transaction_is_authoritative(env):
    from app.persistence.scenarios_repository import DuplicateScenarioName, rename_scenario
    record = env.create("solar")
    _create(env, record, "Upside")
    _create(env, record, "Downside")
    down = _child(record, "Downside")
    with pytest.raises(DuplicateScenarioName):
        rename_scenario(USER, down.scenario_id, "upside", reject_duplicate_name=True)
    assert _child(record, "Downside").scenario_id == down.scenario_id
    assert rename_scenario(USER, down.scenario_id, "upside") is True      # existing callers keep their behaviour unless they opt in


def test_rename_cross_owner_is_isolated_and_history_is_untouched(env):
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence.run_history_repository import get_run_history
    record = env.create("solar")
    run(env, record)
    _create(env, record, "Upside")
    _create(env, record, "Downside")
    down = _child(record, "Downside")
    history = get_run_history(USER, record.project_id)
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id="intruder", username="admin"))
    assert _rename(env, record, down, "Hijack").status_code == 404
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id=USER, username="admin"))
    assert _rename(env, record, down, "Upside").status_code == 409
    assert get_run_history(USER, record.project_id) == history and _names(record) == ["Downside", "Upside"]
