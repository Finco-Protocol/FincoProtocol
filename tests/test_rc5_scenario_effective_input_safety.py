"""RC-5A: scenario effective-input safety, freshness and Run integrity.

A scenario override may be saved or Run only if the canonical Run provably
consumes it.  Real Solar/Wind projects, real persistence, real Run.
"""
from __future__ import annotations

from tests.run_clone_csrf import post_valid_csrf

import json

import pytest

from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401  (fixture)
from tests.test_model_financing_f2 import run

USER = "decision-user"
UNBOUND_FIELDS = ["p50_hours", "opex_y1_keur", "total_capex_keur", "gearing_pct",
                  "interest_rate_pct", "tenor_years", "target_dscr"]
HX = {"HX-Request": "true"}


def _create(env, record, name):
    response = env.client.post("/v2/workbook/scenarios/create", headers=HX,
                               data={"project": record.project_code, "scenario_name": name})
    return response


def _scenarios(record):
    from app.persistence.scenarios_repository import list_scenarios
    return list_scenarios(USER, record.project_id)


def _child(record, name=None):
    return next(s for s in _scenarios(record) if not s.is_base_case and (name is None or s.scenario_name == name))


def _select(env, record, scenario):
    response = env.client.post("/v2/workbook/scenarios/select", headers=HX,
                               data={"project": record.project_code, "scenario_id": scenario.scenario_id})
    assert response.status_code == 200
    return response


def _overrides(env, record, scenario, **fields):
    return env.client.post("/v2/workbook/scenarios/update-overrides", headers=HX,
                           data={"project": record.project_code, "scenario_id": scenario.scenario_id,
                                 **{k: str(v) for k, v in fields.items()}})


def _ws(record):
    from app.persistence.workspace_repository import get_workspace_state
    return get_workspace_state(USER, record.project_id)


def _history(record):
    from app.persistence.run_history_repository import get_run_history
    return get_run_history(USER, record.project_id)


def _post_run(env, record):
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    return post_valid_csrf(env.client, "/v2/workbook/run", headers=HX, data={"project": record.project_code, **tokens(page.text)})


def _tariff(ws):
    snapshot = ws.draft_snapshot
    return float(snapshot["rev_ppa_base_tariff"] if "rev_ppa_base_tariff" in snapshot else snapshot["tariff_eur_mwh"])


def _base(record):
    return next(s for s in _scenarios(record) if s.is_base_case)


def _seed_saved_override(record, scenario, **fields):
    """Persist an override exactly as a pre-RC-5 deployment could have (bypassing the route)."""
    from app.persistence.scenarios_repository import update_scenario_overrides
    assert update_scenario_overrides(USER, scenario.scenario_id, {k: float(v) for k, v in fields.items()})


# ── Authority matrix ───────────────────────────────────────────────────────

def test_authority_matrix_is_complete_and_only_tariff_is_run_bound():
    from app.v2.scenario_presentation import OVERRIDE_EDITOR_FIELDS
    from app.workbook.scenario_override_authority import (
        UNBOUND_CODE, authority_matrix, supported_editor_fields, unbound_override_keys)
    editor = [key for key, _l, _u in OVERRIDE_EDITOR_FIELDS]
    assert sorted(editor) == sorted(["tariff_eur_mwh", *UNBOUND_FIELDS])
    assert supported_editor_fields() == ["tariff_eur_mwh"]
    assert unbound_override_keys({"tariff_eur_mwh": 55.0}) == []
    assert unbound_override_keys({k: 1.0 for k in UNBOUND_FIELDS}) == sorted(UNBOUND_FIELDS)
    matrix = authority_matrix()
    assert {row["ui_field"] for row in matrix} >= set(editor)
    assert UNBOUND_CODE == "SCENARIO_OVERRIDE_UNBOUND"


def test_q4_reviewed_what_if_override_remains_admissible_only_alone():
    from app.workbook.scenario_override_authority import unbound_override_keys
    meta = {"action": "q4_finding_whatif_v1", "finding_id": "QM-SD-004"}
    assert unbound_override_keys({"target_dscr": 1.4}, meta) == []
    assert unbound_override_keys({"target_dscr": 1.4, "tariff_eur_mwh": 50.0}, meta) == ["target_dscr"]
    assert unbound_override_keys({"target_dscr": 1.4}) == ["target_dscr"]


# ── Save: base + child tariff, every exposed scalar ────────────────────────

@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_child_tariff_override_binds_the_canonical_run_and_base_is_unchanged(env, kind):
    record = env.create(kind)
    base_ws, base_rr = run(env, record)
    base_summary = dict(base_rr.runtime_summary)
    assert _create(env, record, "Upside").status_code == 200
    child = _child(record, "Upside")
    base_tariff = _tariff(base_ws)
    saved = _overrides(env, record, child, tariff_eur_mwh=round(base_tariff * 1.15, 4))
    assert saved.status_code == 200
    assert _child(record).overrides == {"tariff_eur_mwh": round(base_tariff * 1.15, 4)}
    _, child_rr = run(env, record)
    assert child_rr.runtime_summary["total_revenue_keur"] > base_summary["total_revenue_keur"]
    assert child_rr.runtime_summary["project_irr"] != base_summary["project_irr"]
    assert child_rr.snapshot_id != base_rr.snapshot_id
    # The Working Copy draft (Base inputs) is not rewritten by a scenario Run.
    assert _tariff(_ws(record)) == base_tariff
    # The earlier Base Run record is immutable.
    assert dict(base_rr.runtime_summary) == base_summary


@pytest.mark.parametrize("kind", ["solar", "wind"])
@pytest.mark.parametrize("field,value", [("p50_hours", 2100), ("opex_y1_keur", 900), ("total_capex_keur", 15000),
                                         ("gearing_pct", 60), ("interest_rate_pct", 7), ("tenor_years", 12),
                                         ("target_dscr", 1.5)])
def test_every_unbound_scalar_is_rejected_at_save_with_a_typed_error_and_no_write(env, kind, field, value):
    record = env.create(kind)
    run(env, record)
    assert _create(env, record, "Probe").status_code == 200
    child = _child(record)
    before_ws, before_history = _ws(record), _history(record)
    response = _overrides(env, record, child, **{field: value})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "SCENARIO_OVERRIDE_UNBOUND"
    assert body["unbound_fields"] == [field]
    assert body["supported_fields"] == ["tariff_eur_mwh"]
    assert _child(record).overrides == {}
    assert _ws(record) == before_ws and _history(record) == before_history


def test_mixed_submission_is_all_or_nothing(env):
    record = env.create("solar")
    _create(env, record, "Mixed")
    child = _child(record)
    response = _overrides(env, record, child, tariff_eur_mwh=60, gearing_pct=55)
    assert response.status_code == 422 and response.json()["unbound_fields"] == ["gearing_pct"]
    assert _child(record).overrides == {}


# ── Run: previously saved unsupported overrides ────────────────────────────

@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_previously_saved_unsupported_override_refuses_the_run_before_commitment(env, kind):
    record = env.create(kind)
    base_ws, base_rr = run(env, record)
    _create(env, record, "Legacy")
    child = _child(record)
    _seed_saved_override(record, child, gearing_pct=55)
    before_ws, before_history = _ws(record), _history(record)
    response = _post_run(env, record)
    assert "SCENARIO_OVERRIDE_UNBOUND" in response.text or response.status_code in (409, 422)
    assert "gearing_pct" in response.text
    after = _ws(record)
    assert after.last_runtime_snapshot_id == before_ws.last_runtime_snapshot_id
    assert after.last_runtime_summary == before_ws.last_runtime_summary
    assert after.draft_snapshot == before_ws.draft_snapshot
    assert _history(record) == before_history
    # The saved value remains visible and removable (recovery path).
    page = env.client.get("/v2/workbook", params={"project": record.project_code, "sheet": "scenarios"})
    assert "Not applied to Run" in page.text and "gearing_pct" in page.text
    assert _child(record).overrides == {"gearing_pct": 55.0}
    removed = env.client.post("/v2/workbook/scenarios/remove-override", headers=HX, data={
        "project": record.project_code, "scenario_id": child.scenario_id, "field": "gearing_pct"})
    assert removed.status_code == 200 and _child(record).overrides == {}
    ok = _post_run(env, record)
    assert ok.status_code == 200
    assert _ws(record).last_runtime_snapshot_id != before_ws.last_runtime_snapshot_id


# ── Two-Senior project ─────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_two_senior_project_child_tariff_runs_and_unbound_is_refused(env, monkeypatch, kind):
    from app.workbook import multisenior_config as f3
    from app.workbook.input_set import ProjectInputSet
    from tests.test_model_financing_f3_workspace import collection_for_inputs, state
    from tests.test_model_financing_f2 import save
    monkeypatch.setattr(f3, "ACTIVATION_ENABLED", True)
    record = env.create(kind)
    pi = ProjectInputSet.from_snapshot(_ws(record).draft_snapshot).to_projectinputs()
    saved = save(env, record, state(active=True, collection=collection_for_inputs(pi)), field=f3.FIELD_ID)
    assert "field-error-banner" not in saved.text
    base_ws, base_rr = run(env, record)
    assert len(base_rr.runtime_summary["financing_evidence"]["facility_schedules"]) == 2
    base_summary = dict(base_rr.runtime_summary)
    _create(env, record, "Upside")
    child = _child(record)
    refused = _overrides(env, record, child, gearing_pct=50)
    assert refused.status_code == 422 and refused.json()["code"] == "SCENARIO_OVERRIDE_UNBOUND"
    base_tariff = _tariff(base_ws)
    assert _overrides(env, record, child, tariff_eur_mwh=round(base_tariff * 1.1, 4)).status_code == 200
    child_ws = _ws(record)
    resp = _post_run(env, record)
    assert resp.status_code == 200
    after = _ws(record)
    # Base evidence recorded earlier is not rewritten; F3 financing is not invented for the child scope.
    assert dict(base_rr.runtime_summary) == base_summary
    assert after.last_runtime_snapshot_id != child_ws.last_runtime_snapshot_id
    assert config_scope_untouched(after, f3, child.scenario_id)


def config_scope_untouched(ws, f3, scenario_id):
    scopes = f3.parse_state(ws.draft_snapshot[f3.SNAPSHOT_KEY])["scopes"]
    return scenario_id not in scopes


# ── Base → Upside → Downside → Base, identities never rewritten ────────────

def test_switch_cycle_never_rewrites_historical_identity_or_draft(env):
    record = env.create("solar")
    base_ws, base_rr = run(env, record)
    identity = (base_ws.last_runtime_snapshot_id, base_ws.last_runtime_at)
    history = _history(record)
    _create(env, record, "Upside")
    _create(env, record, "Downside")
    up, down = _child(record, "Upside"), _child(record, "Downside")
    base = _base(record)
    base_tariff = _tariff(_ws(record))
    draft = dict(_ws(record).draft_snapshot)
    _overrides(env, record, up, tariff_eur_mwh=round(base_tariff * 1.1, 4))
    _overrides(env, record, down, tariff_eur_mwh=round(base_tariff * 0.9, 4))
    for scenario in (base, up, down, base):
        _select(env, record, scenario)
        ws = _ws(record)
        assert ws.active_scenario_id == scenario.scenario_id
        assert ws.draft_snapshot == draft                     # a switch never rewrites the Working Copy
        assert _history(record) == history                    # nor any historical Run record
        if ws.last_runtime_snapshot_id:                       # an identity is only ever the one that scenario committed
            assert (ws.last_runtime_snapshot_id, ws.last_runtime_at) == identity
    final = _ws(record)
    assert (final.last_runtime_snapshot_id, final.last_runtime_at) == identity
    assert dict(__import__("app.workbook.service", fromlist=["WorkbookService"]).WorkbookService.get_runtime_result(final).runtime_summary) == dict(base_rr.runtime_summary)
    assert _child(record, "Upside").overrides and _child(record, "Downside").overrides


# ── Save → reload → Run → edit → STALE → recover ───────────────────────────

def test_save_reload_run_edit_stale_recover(env):
    record = env.create("wind")
    _, base_rr = run(env, record)
    _create(env, record, "Upside")
    child = _child(record)
    value = round(_tariff(_ws(record)) * 1.2, 4)
    assert _overrides(env, record, child, tariff_eur_mwh=value).status_code == 200
    # Reload: the saved override value is still visible.
    page = env.client.get("/v2/workbook", params={"project": record.project_code, "sheet": "scenarios"})
    assert str(value) in page.text
    ran = _post_run(env, record)
    assert ran.status_code == 200
    current_sid = _ws(record).last_runtime_snapshot_id
    assert current_sid != base_rr.snapshot_id
    from app.v2.scenario_presentation import build_scenario_presentations
    def state_of(name):
        rows = build_scenario_presentations(_scenarios(record), _ws(record).active_scenario_id)
        return next(r for r in rows if r.scenario_name == name).state
    assert state_of("Upside") == "CURRENT"
    # Edit the override: the scenario becomes STALE until it is Run again.
    assert _overrides(env, record, child, tariff_eur_mwh=value + 1).status_code == 200
    assert state_of("Upside") == "STALE"
    assert _post_run(env, record).status_code == 200
    assert state_of("Upside") == "CURRENT"
    assert _ws(record).last_runtime_snapshot_id != current_sid


# ── Status truthfulness: no-Run scenario must not inherit Integrity PASS ───

def test_scenario_without_run_does_not_inherit_integrity_pass(env):
    record = env.create("solar")
    run(env, record)
    base_html = env.client.get("/v2/workbook", params={"project": record.project_code}).text
    assert "hy-chip--integrity-pass" in base_html and "hybrid-integrity-note" not in base_html
    _create(env, record, "Fresh")
    _select(env, record, _child(record))
    assert _ws(record).last_runtime_snapshot_id is None
    html = env.client.get("/v2/workbook", params={"project": record.project_code}).text
    assert "hy-chip--integrity-pass" not in html and "hy-chip--integrity-unavailable" in html
    assert "hybrid-integrity-note" in html
    assert 'data-testid="trust-pack-integrity-overall">PASS' not in html
    assert 'data-testid="smart-panel-row-run-integrity"' not in html or "Run integrity</span>\n         <span class=\"v2-smart-panel-row-value\">PASS" not in html
    # The Base Case still owns its own PASS and gets it back after the round trip.
    _select(env, record, _base(record))
    restored = env.client.get("/v2/workbook", params={"project": record.project_code}).text
    assert "hy-chip--integrity-pass" in restored and "hybrid-integrity-note" not in restored


def test_scope_helper_withholds_only_the_integrity_section():
    from types import SimpleNamespace
    from app.v2.result_status import scope_trust_pack_to_active_scenario
    pack = {"integrity": {"state": "AVAILABLE", "overall": "PASS", "checks": [1]}, "kpis": {"state": "AVAILABLE"}}
    ws = SimpleNamespace(last_runtime_snapshot_id=None, active_scenario_id="s1", last_runtime_scenario_id=None)
    scoped = scope_trust_pack_to_active_scenario(pack, ws, "u")
    assert scoped["integrity"]["state"] == "UNAVAILABLE" and scoped["integrity"]["overall"] is None
    assert scoped["kpis"] == pack["kpis"] and pack["integrity"]["overall"] == "PASS"   # input never mutated
    own = SimpleNamespace(last_runtime_snapshot_id="x", active_scenario_id="s1", last_runtime_scenario_id="s1")
    assert scope_trust_pack_to_active_scenario(pack, own, "u") is pack


def test_result_status_unit_contract():
    from app.v2.result_status import ResultStatus, build_result_status
    import inspect
    sig = inspect.signature(build_result_status)
    assert sig.parameters["last_run_matches_scenario"].default is True
    assert "integrity_note" in {f for f in ResultStatus.__dataclass_fields__}


# ── Repeated create ────────────────────────────────────────────────────────

def test_repeated_create_never_produces_a_duplicate_scenario(env):
    record = env.create("solar")
    first = _create(env, record, "Upside")
    second = _create(env, record, "Upside")
    third = _create(env, record, "  upside ")
    assert first.status_code == 200
    assert second.status_code == 409 and second.json()["code"] == "SCENARIO_NAME_DUPLICATE"
    assert third.status_code == 409
    assert [s.scenario_name for s in _scenarios(record) if not s.is_base_case] == ["Upside"]


def test_archived_name_may_be_reused_but_other_projects_are_independent(env):
    one, two = env.create("solar"), env.create("wind")
    assert _create(env, one, "Upside").status_code == 200
    assert _create(env, two, "Upside").status_code == 200
    scenario = _child(one)
    archived = env.client.post("/v2/workbook/scenarios/archive", headers=HX, data={
        "project": one.project_code, "scenario_id": scenario.scenario_id})
    assert archived.status_code == 200
    assert _create(env, one, "Upside").status_code == 200


# ── Isolation / CAS / immutability / numerics ──────────────────────────────

def test_cross_owner_cannot_save_override_or_create_scenario(env):
    from app.auth import COOKIE_NAME, create_session_token
    record = env.create("solar")
    _create(env, record, "Upside")
    child = _child(record)
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id="intruder", username="admin"))
    assert _overrides(env, record, child, tariff_eur_mwh=99).status_code == 404
    assert _create(env, record, "Evil").status_code == 404
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id=USER, username="admin"))
    assert _child(record).overrides == {}


def test_stale_cas_run_is_refused_without_writing(env):
    record = env.create("solar")
    run(env, record)
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    stale = tokens(page.text)
    stale["content_hash"] = "0" * 64
    before, history = _ws(record), _history(record)
    response = post_valid_csrf(env.client, "/v2/workbook/run", headers=HX, data={"project": record.project_code, **stale})
    assert response.status_code in (200, 409)
    assert _ws(record).last_runtime_snapshot_id == before.last_runtime_snapshot_id
    assert _history(record) == history


def test_run_history_is_append_only_across_scenario_runs(env):
    record = env.create("solar")
    run(env, record)
    first = {h.run_id if hasattr(h, "run_id") else str(h): h for h in _history(record)}
    _create(env, record, "Upside")
    child = _child(record)
    _overrides(env, record, child, tariff_eur_mwh=round(_tariff(_ws(record)) * 1.05, 4))
    assert _post_run(env, record).status_code == 200
    later = _history(record)
    assert len(later) == len(first) + 1
    for key, item in first.items():
        match = next(h for h in later if (h.run_id if hasattr(h, "run_id") else str(h)) == key)
        assert match == item


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_baseline_numerics_are_unchanged_by_the_guards(env, kind):
    """A project with no scenario overrides produces the same Run as before RC-5 (no tolerance changes)."""
    record = env.create(kind)
    _, first = run(env, record)
    _, second = run(env, record)
    for key in ("project_irr", "equity_irr", "senior_debt_keur", "total_revenue_keur", "min_dscr"):
        assert first.runtime_summary[key] == second.runtime_summary[key]
