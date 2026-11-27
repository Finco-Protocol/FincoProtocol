"""Q3 — the real /v2/workbook route: Model Quality, covenants and scenarios inside FINCO Insight.

Runs the production workbook Run for Solar, Wind, Data Center and EV Charging, then proves the rendered
panel equals the Q1 report over the persisted record, that rendering never runs the engine or writes, and
that STALE / NOT_RUN / scenario states are labelled from canonical authorities.
"""
from __future__ import annotations

from tests.model_mutation_csrf import post_valid_mutation
from tests.model_react_test_helpers import react_workbook_tokens
from tests.run_clone_csrf import post_valid_csrf

from unittest import mock

import pytest

VERTICALS = {
    "solar": "generic_solar_reference",
    "wind": "generic_wind_reference",
    "data_center": "generic_data_center_reference",
    "ev_charging": "generic_ev_charging_reference",
}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    from app.persistence import db
    mp = pytest.MonkeyPatch()
    mp.setattr(db, "DB_PATH", str(tmp_path_factory.mktemp("q3route") / "q3.db"))
    db.init_db()
    from fastapi.testclient import TestClient
    import main_web
    from app.auth import COOKIE_NAME, create_session_token
    client = TestClient(main_web.app)
    yield SimpleNs(client=client, cookie=lambda u: {COOKIE_NAME: create_session_token(user_id=u, username="admin")})
    mp.undo()


class SimpleNs:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _project(env, user, template, name):
    from app.services.reference_seed_service import create_reference_seeded_project
    return create_reference_seeded_project(user_id=user, template_source=template, requested_name=name, capacity_mw=40.0)


def _diag(env, user, rec):
    res = env.client.get(f"/v2/model-react/diagnostics?project={rec.project_code}", cookies=env.cookie(user))
    assert res.status_code == 200, res.text[:500]
    return res.json()


def _tokens(env, user, rec):
    t = react_workbook_tokens(env.client, rec.project_code, cookies=env.cookie(user))
    return t["content_hash"], t["workbook_version"]


def _run(env, user, rec):
    h, v = _tokens(env, user, rec)
    r = post_valid_csrf(env.client, "/v2/workbook/run", data={"project": rec.project_code, "content_hash": h, "workbook_version": v},
                        cookies=env.cookie(user))
    assert r.status_code == 200


def _checks(diag_payload):
    groups = diag_payload["insight"].get("groups") or {}
    return {
        row["check_id"]: row["status"]
        for rows in groups.values()
        for row in rows
    }


def _state(diag_payload):
    return diag_payload["insight"]["state"]


@pytest.fixture(scope="module")
def runs(env):
    out = {}
    for key, template in VERTICALS.items():
        user = f"q3-{key}"
        rec = _project(env, user, template, f"Q3 {key}")
        out[key] = (user, rec, _diag(env, user, rec))          # NOT_RUN state first
        _run(env, user, rec)
    return out


@pytest.mark.parametrize("key", list(VERTICALS))
def test_not_run_page_has_no_values_checks_or_score(runs, key):
    payload = runs[key][2]
    insight = payload["insight"]
    assert _state(payload) == "NOT_RUN" and not _checks(payload)
    assert insight.get("score") is None and "No committed Run" in insight["message"]
    assert "MODEL QUALITY / LENDER READINESS ADVISORY" in insight["label"]


@pytest.mark.parametrize("key", list(VERTICALS))
def test_rendered_panel_equals_q1_over_the_persisted_run(env, runs, key):
    from app.model_quality import evaluate_model_quality
    from app.model_quality.evidence import evidence_from_workspace, terms_from_project_inputs
    from app.persistence.workspace_repository import get_workspace_state
    from app.v2.router import _build_pis_with_composite_identity
    user, rec, _ = runs[key]
    payload = _diag(env, user, rec)
    insight = payload["insight"]
    ws = get_workspace_state(user, rec.project_id)
    pis = _build_pis_with_composite_identity(ws, rec, user)
    report = evaluate_model_quality(evidence_from_workspace(
        ws, freshness="CURRENT", terms=terms_from_project_inputs(pis.to_projectinputs()),
        active_scenario_id=ws.active_scenario_id, scenario_known=True))
    assert _state(payload) == "CURRENT"
    assert _checks(payload) == {c.check_id: c.status.value for c in report.checks}
    s = report.summary
    score = insight["score"]
    if s.score is not None:
        assert score["score_display"] == f"{s.score:.1f} / 100"
    else:
        assert score["score_display"] is None and "Not scored" in score["score_note"]
    assert score["counts"]["fail"] == s.failed and score["counts"]["unavailable"] == s.unavailable
    assert any(c["threshold"] == "CONTRACTUAL_THRESHOLD_UNAVAILABLE" for c in insight["covenants"])
    types = [c["type"] for c in insight["covenants"]]
    assert types == ["Minimum DSCR covenant", "Distribution lock-up DSCR", "Minimum LLCR",
                     "Reserve account (DSRA) funding", "Default DSCR"]


def test_rendering_runs_no_engine_and_writes_nothing(env, runs):
    from app.persistence.workspace_repository import get_workspace_state
    user, rec, _ = runs["solar"]
    ws0 = get_workspace_state(user, rec.project_id)
    with mock.patch("app.services.production_financial_authority.run_clean_production",
                    side_effect=AssertionError("engine must not run from a read-only panel")):
        payload = _diag(env, user, rec)
    ws1 = get_workspace_state(user, rec.project_id)
    assert payload["ok"] is True and payload["insight"]["available"] is True
    assert ws0.updated_at == ws1.updated_at and ws0.last_runtime_composite_hash == ws1.last_runtime_composite_hash
    assert ws0.last_runtime_snapshot_id == ws1.last_runtime_snapshot_id


def test_unsaved_change_makes_the_run_stale_and_unbinds_thresholds(env, runs):
    from app.persistence.workspace_repository import get_workspace_state
    user, rec, _ = runs["solar"]
    h, v = _tokens(env, user, rec)
    r = post_valid_mutation(env.client, "/v2/workbook/update", follow_redirects=False, data={
        "field_id": "project_setup.technical.p50_hours", "value": "1434", "project": rec.project_code,
        "workbook_version": v, "content_hash": h, "sheet_id": "project_setup"},
        cookies=env.cookie(user))
    assert r.status_code == 303 and "v2_err=" not in r.headers.get("location", "")
    ws_after = get_workspace_state(user, rec.project_id)
    assert float(ws_after.draft_snapshot["p50_hours"]) == 1434.0
    assert float(ws_after.draft_snapshot["operating_hours_p90_10y"]) == 1400.0
    payload = _diag(env, user, rec)
    h_after, _ = _tokens(env, user, rec)
    assert h_after != h
    assert _state(payload) == "STALE" and "PRIOR" in payload["insight"]["context_note"]
    lock = next(c for c in payload["insight"]["covenants"] if c["type"] == "Distribution lock-up DSCR")
    assert lock["status"] == "UNAVAILABLE" and "RUN_THRESHOLD_NOT_BOUND" in lock["reason"]
    assert "STALE — describes the prior Last Run" in lock["freshness"]
    # the prior Run's recorded values are not replaced by Working Copy numbers
    assert _checks(payload), "the prior Run is still evaluated"


def test_scenarios_mode_lists_own_runs_and_labels_missing_ones(env):
    user = "q3-scn"
    rec = _project(env, user, "generic_solar_reference", "Q3 scenarios")
    _run(env, user, rec)
    c, ck = env.client, env.cookie(user)
    r = post_valid_mutation(c, "/v2/workbook/scenarios/create", data={"project": rec.project_code, "scenario_name": "Upside"},
               cookies=ck)
    assert r.status_code == 200
    hist = c.get(f"/v2/model-react/insights/history?project={rec.project_code}", cookies=ck)
    assert hist.status_code == 200
    scenarios = hist.json()["scenarios"]
    assert sorted(s["availability"] for s in scenarios) == ["available", "not_run"]
    not_run = next(s for s in scenarios if s["availability"] == "not_run")
    assert "No committed Run exists" in not_run["reason"]
    assert _diag(env, user, rec)["insight"]["state"] == "NOT_RUN"


def test_protected_reference_panel_is_read_only_and_not_run(env):
    from app.services.project_library_service import ensure_reference_models
    ensure_reference_models()
    ck = env.cookie("q3-ref")
    diag = env.client.get("/v2/model-react/diagnostics?project=generic_solar_reference-reference", cookies=ck)
    assert diag.status_code == 200
    assert diag.json()["project"]["protected_reference"] is True
    inputs = env.client.get("/v2/model-react/inputs?project=generic_solar_reference-reference", cookies=ck)
    assert inputs.status_code == 200 and inputs.json()["project"]["protected_reference"] is True
    ins_hist = env.client.get("/v2/model-react/insights/history?project=generic_solar_reference-reference", cookies=ck)
    assert ins_hist.status_code == 409 and ins_hist.json()["code"] == "PROTECTED_REFERENCE"


def test_other_users_cannot_read_the_panel_of_an_owner_project(env, runs):
    user, rec, _ = runs["solar"]
    intruder = env.cookie("q3-intruder")
    assert env.client.get(f"/v2/model-react/diagnostics?project={rec.project_code}", cookies=intruder).status_code == 404
    assert env.client.get(f"/v2/model-react/insights/history?project={rec.project_code}", cookies=intruder).status_code == 404


def test_post_run_post_save_and_scenario_views_carry_consistent_q3(env):
    from app.persistence.workspace_repository import get_workspace_state
    user = "q3-oob"
    rec = _project(env, user, "generic_solar_reference", "Q3 oob")
    h, v = _tokens(env, user, rec)
    ck = env.cookie(user)
    run = post_valid_csrf(env.client, "/v2/workbook/run", data={"project": rec.project_code, "content_hash": h, "workbook_version": v},
                          cookies=ck)
    assert run.status_code == 200
    cur_diag = _diag(env, user, rec)
    assert _state(cur_diag) == "CURRENT" and len(_checks(cur_diag)) == 30
    h, v = _tokens(env, user, rec)
    save = post_valid_mutation(env.client, "/v2/workbook/update", follow_redirects=False, data={
        "field_id": "project_setup.technical.p50_hours", "value": "1401", "project": rec.project_code,
        "workbook_version": v, "content_hash": h, "sheet_id": "project_setup"}, cookies=ck)
    assert save.status_code == 303 and "v2_err=" not in save.headers.get("location", "")
    assert float(get_workspace_state(user, rec.project_id).draft_snapshot["p50_hours"]) == 1401.0
    stale_diag = _diag(env, user, rec)
    assert _state(stale_diag) == "STALE"
    lock = next(c for c in stale_diag["insight"]["covenants"] if c["type"] == "Distribution lock-up DSCR")
    assert "RUN_THRESHOLD_NOT_BOUND" in lock["reason"]
    h_after, _ = _tokens(env, user, rec)
    assert h_after != h
    created = post_valid_mutation(env.client, "/v2/workbook/scenarios/create", data={"project": rec.project_code, "scenario_name": "OOB"},
                              cookies=ck)
    assert created.status_code == 200
    assert _state(_diag(env, user, rec)) == "NOT_RUN"


def test_invalid_p50_below_saved_p90_refuses_save_and_keeps_q3_current(env):
    from app.persistence.workspace_repository import get_workspace_state
    import urllib.parse
    user = "q3-inv-p50"
    rec = _project(env, user, "generic_solar_reference", "Q3 invalid P50")
    _run(env, user, rec)
    before_diag = _diag(env, user, rec)
    assert _state(before_diag) == "CURRENT"
    h0, v0 = _tokens(env, user, rec)
    ws0 = get_workspace_state(user, rec.project_id)

    bad = post_valid_mutation(env.client, "/v2/workbook/update", follow_redirects=False, data={
        "field_id": "project_setup.technical.p50_hours", "value": "1234", "project": rec.project_code,
        "workbook_version": v0, "content_hash": h0, "sheet_id": "project_setup"},
        cookies=env.cookie(user))
    assert bad.status_code == 303
    err = urllib.parse.unquote_plus(bad.headers.get("location", ""))
    assert "P90_EXCEEDS_P50" in err or "cannot exceed P50" in err

    ws1 = get_workspace_state(user, rec.project_id)
    assert ws1.draft_snapshot == ws0.draft_snapshot
    assert ws1.updated_at == ws0.updated_at
    assert ws1.last_runtime_snapshot_id == ws0.last_runtime_snapshot_id
    after_diag = _diag(env, user, rec)
    assert _state(after_diag) == "CURRENT"
    assert _tokens(env, user, rec) == (h0, v0)
