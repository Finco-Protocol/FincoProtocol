"""Q3 — the real /v2/workbook route: Model Quality, covenants and scenarios inside FINCO Insight.

Runs the production workbook Run for Solar, Wind, Data Center and EV Charging, then proves the rendered
panel equals the Q1 report over the persisted record, that rendering never runs the engine or writes, and
that STALE / NOT_RUN / scenario states are labelled from canonical authorities.
"""
from __future__ import annotations

import re
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


def _get(env, user, rec):
    return env.client.get(f"/v2/workbook?project={rec.project_code}", cookies=env.cookie(user))


def _tokens(html):
    return (re.search(r'name="content_hash" value="([^"]+)"', html).group(1),
            re.search(r'name="workbook_version" value="([^"]+)"', html).group(1))


def _run(env, user, rec):
    h, v = _tokens(_get(env, user, rec).text)
    r = env.client.post("/v2/workbook/run", data={"project": rec.project_code, "content_hash": h, "workbook_version": v},
                        cookies=env.cookie(user), headers={"HX-Request": "true"})
    assert r.status_code == 200


def _checks(html):
    return dict(re.findall(r'data-q3-check data-check-id="(QM-[A-Z]+-\d+)"\s+data-check-status="(\w+)"', html))


def _state(html):
    return re.search(r'data-testid="q3-quality" data-q3-state="(\w+)"', html).group(1)


@pytest.fixture(scope="module")
def runs(env):
    out = {}
    for key, template in VERTICALS.items():
        user = f"q3-{key}"
        rec = _project(env, user, template, f"Q3 {key}")
        out[key] = (user, rec, _get(env, user, rec).text)          # NOT_RUN page first
        _run(env, user, rec)
    return out


@pytest.mark.parametrize("key", list(VERTICALS))
def test_not_run_page_has_no_values_checks_or_score(runs, key):
    html = runs[key][2]
    assert _state(html) == "NOT_RUN" and not _checks(html)
    assert 'data-testid="q3-score"' not in html and "No committed Run" in html
    assert "MODEL QUALITY / LENDER READINESS ADVISORY" in html


@pytest.mark.parametrize("key", list(VERTICALS))
def test_rendered_panel_equals_q1_over_the_persisted_run(env, runs, key):
    from app.model_quality import evaluate_model_quality
    from app.model_quality.evidence import evidence_from_workspace, terms_from_project_inputs
    from app.persistence.workspace_repository import get_workspace_state
    from app.v2.router import _build_pis_with_composite_identity
    user, rec, _ = runs[key]
    html = _get(env, user, rec).text
    ws = get_workspace_state(user, rec.project_id)
    pis = _build_pis_with_composite_identity(ws, rec, user)
    report = evaluate_model_quality(evidence_from_workspace(
        ws, freshness="CURRENT", terms=terms_from_project_inputs(pis.to_projectinputs()),
        active_scenario_id=ws.active_scenario_id, scenario_known=True))
    assert _state(html) == "CURRENT"
    assert _checks(html) == {c.check_id: c.status.value for c in report.checks}
    s = report.summary
    if s.score is not None:
        assert f"{s.score:.1f} / 100" in html
    else:
        assert "NOT SCORED" in html
    assert f"{s.failed} FAIL" in html and f"{s.unavailable} UNAVAILABLE" in html
    assert "CONTRACTUAL_THRESHOLD_UNAVAILABLE" in html                  # min-DSCR / default-DSCR have no authority
    # the covenant section uses only the Q1 covenant checks plus the declared-absent default-DSCR row
    types = re.findall(r'data-covenant-type="([^"]+)"', html)
    assert types == ["Minimum DSCR covenant", "Distribution lock-up DSCR", "Minimum LLCR",
                     "Reserve account (DSRA) funding", "Default DSCR"]


def test_rendering_runs_no_engine_and_writes_nothing(env, runs):
    from app.persistence.workspace_repository import get_workspace_state
    user, rec, _ = runs["solar"]
    ws0 = get_workspace_state(user, rec.project_id)
    with mock.patch("app.services.production_financial_authority.run_clean_production",
                    side_effect=AssertionError("engine must not run from a read-only panel")):
        html = _get(env, user, rec).text
    ws1 = get_workspace_state(user, rec.project_id)
    assert "q3-quality" in html
    assert ws0.updated_at == ws1.updated_at and ws0.last_runtime_composite_hash == ws1.last_runtime_composite_hash
    assert ws0.last_runtime_snapshot_id == ws1.last_runtime_snapshot_id


def test_unsaved_change_makes_the_run_stale_and_unbinds_thresholds(env, runs):
    user, rec, _ = runs["solar"]
    page = _get(env, user, rec).text
    h, v = _tokens(page)
    r = env.client.post("/v2/workbook/update", data={
        "field_id": "project_setup.technical.p50_hours", "value": "1234", "project": rec.project_code,
        "workbook_version": v, "content_hash": h, "sheet_id": "project_setup"},
        cookies=env.cookie(user), headers={"HX-Request": "true"})
    assert r.status_code == 200
    html = _get(env, user, rec).text
    assert _state(html) == "STALE" and "PRIOR" in html
    lock = re.search(r'data-covenant-type="Distribution lock-up DSCR" data-covenant-status="(\w+)"', html).group(1)
    assert lock == "UNAVAILABLE" and "RUN_THRESHOLD_NOT_BOUND" in html
    assert "STALE — describes the prior Last Run" in html
    # the prior Run's recorded values are not replaced by Working Copy numbers
    assert _checks(html), "the prior Run is still evaluated"


def test_scenarios_mode_lists_own_runs_and_labels_missing_ones(env):
    user = "q3-scn"
    rec = _project(env, user, "generic_solar_reference", "Q3 scenarios")
    _run(env, user, rec)
    c, ck = env.client, env.cookie(user)
    r = c.post("/v2/workbook/scenarios/create", data={"project": rec.project_code, "scenario_name": "Upside"},
               cookies=ck, headers={"HX-Request": "true"})
    assert r.status_code == 200
    html = _get(env, user, rec).text
    rows = re.findall(r'data-scenario-id="[^"]+" data-scenario-basis="(\w+)"', html)
    assert sorted(rows) == ["HISTORICAL_RUN", "NO_RUN"] or sorted(rows) == ["CURRENT", "NO_RUN"]
    assert "q3-compare-unavailable" in html and "nothing is estimated" in html
    # create/select are explicit user actions on the existing workspace; the panel itself exposes none
    assert 'hx-post="/v2/workbook/scenarios' not in html.split('id="model-smart-panel"')[1].split("</aside>")[0]
    assert 'data-nav-tab="tab-scenarios"' in html


def test_protected_reference_panel_is_read_only_and_not_run(env):
    from app.services.project_library_service import ensure_reference_models
    ensure_reference_models()
    r = env.client.get("/v2/workbook?project=generic_solar_reference-reference", cookies=env.cookie("q3-ref"))
    assert r.status_code == 200
    assert "model-smart-panel" in r.text
    assert not re.search(r'<input[^>]+class="[^"]*v2-field-input', r.text)
    panel = r.text.split('id="model-smart-panel"')[1].split("</aside>")[0]
    for forbidden in ("<form", "<textarea", "contenteditable", "hx-post", "onclick"):
        assert forbidden not in panel
    assert panel.count("<select") == 1


def test_other_users_cannot_read_the_panel_of_an_owner_project(env, runs):
    user, rec, _ = runs["solar"]
    r = env.client.get(f"/v2/workbook?project={rec.project_code}", cookies=env.cookie("q3-intruder"),
                       follow_redirects=False)
    assert "q3-quality" not in r.text and rec.project_code not in r.text.replace(f"project={rec.project_code}", "")


# ───────── the OOB fragments (Run / Save / scenario actions) must carry the same Q3 views as GET ─────────

def _oob_panel(text):
    assert 'id="model-smart-panel" hx-swap-oob="true"' in text, "the action response must refresh FINCO Insight"
    return text.split('id="model-smart-panel" hx-swap-oob="true"', 1)[1].split("</aside>", 1)[0]


def test_post_run_post_save_and_scenario_oob_panels_carry_q3(env):
    user = "q3-oob"
    rec = _project(env, user, "generic_solar_reference", "Q3 oob")
    h, v = _tokens(_get(env, user, rec).text)
    ck = env.cookie(user)
    run = env.client.post("/v2/workbook/run", data={"project": rec.project_code, "content_hash": h, "workbook_version": v},
                          cookies=ck, headers={"HX-Request": "true"})
    oob = _oob_panel(run.text)
    assert 'data-q3-state="CURRENT"' in oob and "Scenarios workspace" in oob
    assert _checks(oob) == _checks(_get(env, user, rec).text) and len(_checks(oob)) == 30
    h, v = _tokens(_get(env, user, rec).text)
    save = env.client.post("/v2/workbook/update", data={
        "field_id": "project_setup.technical.p50_hours", "value": "1301", "project": rec.project_code,
        "workbook_version": v, "content_hash": h, "sheet_id": "project_setup"}, cookies=ck, headers={"HX-Request": "true"})
    oob = _oob_panel(save.text)
    assert 'data-q3-state="STALE"' in oob and "RUN_THRESHOLD_NOT_BOUND" in oob
    h, v = _tokens(_get(env, user, rec).text)
    created = env.client.post("/v2/workbook/scenarios/create", data={"project": rec.project_code, "scenario_name": "OOB"},
                              cookies=ck, headers={"HX-Request": "true"})
    if 'id="model-smart-panel"' in created.text:
        oob = _oob_panel(created.text)
        assert "data-q3-state" in oob
