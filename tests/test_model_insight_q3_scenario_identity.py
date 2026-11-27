"""Q3 Correction A — the scenario shown with the Findings is the COMMITTED Last Run's scenario.

Defect: the Findings context read ``Scenario: UNAVAILABLE`` for a Base Case Run (``active_scenario_name`` is empty
for a Base Case that never recorded a scenario id) while the same workbook names it Base / Base Case.
Rule: identity comes from ``ws.last_runtime_scenario_id`` — NULL is the canonical Base Case; an explicit id is resolved
through the owner's and project's own scenario records; an unresolvable id stays UNAVAILABLE; the active Working Copy
scenario's name is never substituted.
"""
from __future__ import annotations

from tests.model_mutation_csrf import post_valid_mutation
from tests.model_react_test_helpers import react_workbook_tokens
from tests.run_clone_csrf import post_valid_csrf

import re
import uuid
from types import SimpleNamespace

import pytest

from app.persistence.scenario_insight_reads import BASE_CASE_LABEL, resolve_last_run_scenario

VERTICALS = {
    "solar": "generic_solar_reference", "wind": "generic_wind_reference",
    "data_center": "generic_data_center_reference", "ev_charging": "generic_ev_charging_reference",
}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    from app.persistence import db
    mp = pytest.MonkeyPatch()
    mp.setattr(db, "DB_PATH", str(tmp_path_factory.mktemp("q3id") / "q3id.db"))
    db.init_db()
    from fastapi.testclient import TestClient
    import main_web
    from app.auth import COOKIE_NAME, create_session_token
    yield SimpleNamespace(client=TestClient(main_web.app),
                          cookie=lambda u: {COOKIE_NAME: create_session_token(user_id=u, username="admin")})
    mp.undo()


def project(user, template="generic_solar_reference", name="Q3 ID"):
    from app.services.reference_seed_service import create_reference_seeded_project
    return create_reference_seeded_project(user_id=user, template_source=template, requested_name=name, capacity_mw=40.0)


def diag(env, user, rec):
    r = env.client.get(f"/v2/model-react/diagnostics?project={rec.project_code}", cookies=env.cookie(user))
    assert r.status_code == 200, r.text[:500]
    return r.json()


def tokens(env, user, rec):
    t = react_workbook_tokens(env.client, rec.project_code, cookies=env.cookie(user))
    return t["content_hash"], t["workbook_version"]


def run(env, user, rec):
    h, v = tokens(env, user, rec)
    r = post_valid_csrf(env.client, "/v2/workbook/run", data={"project": rec.project_code, "content_hash": h, "workbook_version": v},
                        cookies=env.cookie(user))
    assert r.status_code == 200
    return r


def scenario_line(payload):
    ident = payload["insight"].get("identity") or {}
    return ident.get("scenario_name") or ""


def snapshot_in(payload):
    return (payload["insight"].get("identity") or {}).get("snapshot_id") or ""


def last_run(user, rec):
    from app.persistence.workspace_repository import get_workspace_state
    return get_workspace_state(user, rec.project_id)


def select(env, user, rec, scenario_id):
    r = post_valid_mutation(env.client, "/v2/workbook/scenarios/select", data={"project": rec.project_code, "scenario_id": scenario_id},
                        cookies=env.cookie(user))
    assert r.status_code == 200
    return r.text


def create_scenario(env, user, rec, name):
    r = post_valid_mutation(env.client, "/v2/workbook/scenarios/create", data={"project": rec.project_code, "scenario_name": name},
                        cookies=env.cookie(user))
    assert r.status_code == 200
    from app.persistence.scenarios_repository import list_scenarios
    return next(s for s in list_scenarios(user_id=user, project_id=rec.project_id) if s.scenario_name == name)


# ─────────────────────────── resolver (SQLite, owner/project scoped) ───────────────────────────

def test_resolver_null_id_is_the_canonical_base_case_with_the_record_name(env):
    rec = project("q3id-r1", name="Resolver Project")
    got = resolve_last_run_scenario("q3id-r1", rec.project_id, None)
    assert got.proven and got.is_base_case and got.scenario_id is None
    assert got.label == f"{BASE_CASE_LABEL} (Resolver Project)"


def test_resolver_null_id_without_a_readable_record_still_proves_the_base_case(env):
    got = resolve_last_run_scenario("q3id-nobody", "no-such-project", None)
    assert got.proven and got.label == BASE_CASE_LABEL


def test_resolver_explicit_scenario_uses_its_own_record_name_not_base_case(env):
    from app.persistence.db import get_cursor
    rec = project("q3id-r2")
    sid = uuid.uuid4().hex[:16]
    with get_cursor() as cur:
        cur.execute("INSERT INTO scenarios (scenario_id, project_id, user_id, scenario_name, project_code, source_project_template,"
                    " snapshot_json, governance_state_json, last_run_summary_json, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, rec.project_id, "q3id-r2", "Downside", rec.project_code, "t", "{}", "{}", "{}", "2026-01-01", "2026-01-01"))
    got = resolve_last_run_scenario("q3id-r2", rec.project_id, sid)
    assert got.proven and not got.is_base_case and got.label == "Downside" and got.scenario_id == sid


def test_unresolved_explicit_id_is_unavailable_never_base_case_never_invented(env):
    rec = project("q3id-r3")
    got = resolve_last_run_scenario("q3id-r3", rec.project_id, "deadbeefdeadbeef")
    assert not got.proven and got.label is None and not got.is_base_case


def test_scenario_of_another_owner_or_project_is_not_resolved(env):
    from app.persistence.db import get_cursor
    mine, other_owner, other_project = project("q3id-o1"), project("q3id-o2"), project("q3id-o1", name="Other project")
    sid = uuid.uuid4().hex[:16]
    with get_cursor() as cur:
        cur.execute("INSERT INTO scenarios (scenario_id, project_id, user_id, scenario_name, project_code, source_project_template,"
                    " snapshot_json, governance_state_json, last_run_summary_json, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, other_owner.project_id, "q3id-o2", "Secret scenario", other_owner.project_code, "t", "{}", "{}", "{}", "2026-01-01", "2026-01-01"))
    assert resolve_last_run_scenario("q3id-o1", mine.project_id, sid).label is None          # other owner
    assert resolve_last_run_scenario("q3id-o2", other_project.project_id, sid).label is None  # other project
    assert resolve_last_run_scenario("q3id-o2", other_owner.project_id, sid).label == "Secret scenario"


def test_resolver_makes_no_write_and_one_bounded_read(env, monkeypatch):
    import inspect
    from app.persistence import scenario_insight_reads as mod
    src = inspect.getsource(mod.resolve_last_run_scenario)
    assert not re.search(r"\b(INSERT|UPDATE|DELETE)\b", src) and src.count("cur.execute") == 2 and src.count("LIMIT 1") == 2


# ─────────────────────────── real route: Base Case, CURRENT and STALE ───────────────────────────

def test_A_base_case_current_names_base_case_never_unavailable(env):
    user, rec = "q3id-a", project("q3id-a", name="Base Project")
    initial = diag(env, user, rec)
    assert initial["insight"]["state"] == "NOT_RUN" and "identity" not in initial["insight"]
    run(env, user, rec)
    payload = diag(env, user, rec)
    assert scenario_line(payload) == "Base Case (Base Project)"
    assert "UNAVAILABLE" not in scenario_line(payload)
    assert scenario_line(payload).startswith("Base Case")
    assert snapshot_in(payload) == last_run(user, rec).last_runtime_snapshot_id


def test_B_base_case_stale_keeps_the_prior_run_identity_and_unbinds_thresholds(env):
    from app.persistence.workspace_repository import get_workspace_state
    user, rec = "q3id-b", project("q3id-b", name="Stale Project")
    run(env, user, rec)
    before = diag(env, user, rec)
    snap = snapshot_in(before)
    h, v = tokens(env, user, rec)
    r = post_valid_mutation(env.client, "/v2/workbook/update", follow_redirects=False, data={
        "field_id": "project_setup.technical.p50_hours", "value": "1440",
        "project": rec.project_code, "workbook_version": v, "content_hash": h, "sheet_id": "project_setup"},
        cookies=env.cookie(user))
    assert r.status_code == 303 and "v2_err=" not in r.headers.get("location", "")
    ws_after = get_workspace_state(user, rec.project_id)
    assert float(ws_after.draft_snapshot["p50_hours"]) == 1440.0
    assert float(ws_after.draft_snapshot["operating_hours_p90_10y"]) == 1400.0
    after = diag(env, user, rec)
    h_after, _ = tokens(env, user, rec)
    assert h_after != h
    assert after["insight"]["state"] == "STALE"
    assert scenario_line(after) == "Base Case (Stale Project)" and snapshot_in(after) == snap, "prior Run identity unchanged"
    assert any("RUN_THRESHOLD_NOT_BOUND" in c["reason"] for c in after["insight"]["covenants"])
    assert "PRIOR" in after["insight"]["context_note"]


# ─────────────────────────── named scenario and scenario switch ───────────────────────────

def test_C_and_D_named_scenario_identity_and_switch_without_another_run(env):
    user, rec = "q3id-c", project("q3id-c", name="Switch Project")
    run(env, user, rec)
    base_diag = diag(env, user, rec)
    base_snap = snapshot_in(base_diag)
    up = create_scenario(env, user, rec, "Upside")                       # becomes the active Working Copy scenario
    # D: switched, no Run for Upside yet -> the Last Run was cleared by the switch: NOT_RUN, no identity at all
    switched = diag(env, user, rec)
    assert switched["insight"]["state"] == "NOT_RUN" and "identity" not in switched["insight"]
    assert "Upside" not in str(switched["insight"]), "no committed identity may be shown"
    run(env, user, rec)                                                  # explicit Run of Upside
    payload = diag(env, user, rec)
    ws = last_run(user, rec)
    assert scenario_line(payload) == "Upside" and "Base Case" not in scenario_line(payload)
    assert snapshot_in(payload) == ws.last_runtime_snapshot_id != base_snap
    assert ws.last_runtime_scenario_id == up.scenario_id
    # back to the Base Case scenario: its OWN Run is restored, so the identity is the Base Case's, not "Upside"
    from app.persistence.scenarios_repository import get_base_case_scenario
    select(env, user, rec, get_base_case_scenario(user, rec.project_id).scenario_id)
    back = diag(env, user, rec)
    assert scenario_line(back).startswith("Base Case") and snapshot_in(back) == base_snap


def test_D2_selected_scenario_name_is_never_substituted_for_a_different_last_run(env):
    """Last Run committed by the Base Case while another scenario is the active Working Copy scenario."""
    from app.persistence.db import get_cursor
    user, rec = "q3id-d2", project("q3id-d2", name="Other Active")
    run(env, user, rec)
    up = create_scenario(env, user, rec, "Selected but never run")
    ws0 = last_run(user, rec)
    assert ws0.active_scenario_id == up.scenario_id
    # restore the Base Run into the workspace Last Run while the other scenario stays selected (legacy shape)
    with get_cursor() as cur:
        cur.execute("SELECT * FROM model_run_history WHERE project_id=? ORDER BY ran_at DESC LIMIT 1", (rec.project_id,))
        h = dict(cur.fetchone())
    # Historical/noncanonical shape: seeded OFFLINE (WF03 refuses this on an application connection), then the
    # normal guarded read path below is what is under test.
    from app.persistence import db as _db
    from tests.wf03_offline_fixture import seed_historical_workspace_state
    seed_historical_workspace_state(
        _db.DB_PATH, user, rec.project_id,
        last_runtime_summary_json=h["runtime_summary_json"], last_runtime_snapshot_id=h["runtime_snapshot_id"],
        last_runtime_scenario_id=None, last_runtime_composite_hash=h["composite_hash"], last_runtime_at=h["ran_at"],
        last_integrity_evidence_json=h["integrity_evidence_json"], last_sponsor_schedule_json=h["sponsor_schedule_json"],
        last_runtime_identity_json=h["last_runtime_identity_json"])
    seeded = last_run(user, rec)
    assert seeded.last_runtime_snapshot_id == h["runtime_snapshot_id"] and seeded.last_runtime_scenario_id is None
    assert seeded.active_scenario_id == up.scenario_id
    payload = diag(env, user, rec)
    line = scenario_line(payload)
    assert "Selected but never run" not in str(payload["insight"].get("identity") or {})
    assert line.startswith("Base Case") or line == "UNAVAILABLE"


def test_E_unresolvable_scenario_id_stays_unavailable_through_the_real_attach_path(env):
    """workspace_states.last_runtime_scenario_id is a foreign key, so a dangling id cannot be persisted; the attach
    path is therefore exercised with a record carrying an id that no owner/project-scoped scenario row proves."""
    from app.persistence.projects_repository import get_project_by_code
    from app.services.react_insights_service import scenario_label
    from app.v2.router import _attach_insight
    from app.v2.smart_panel_projection import build_smart_panel_projection
    user, rec = "q3id-e", project("q3id-e", name="Unresolved")
    run(env, user, rec)
    real = last_run(user, rec)
    ws = SimpleNamespace(**{k: getattr(real, k) for k in (
        "last_runtime_summary", "last_integrity_evidence", "last_sponsor_schedule", "last_debt_schedule",
        "last_runtime_snapshot_id", "last_runtime_composite_hash", "last_runtime_identity", "last_runtime_at",
        "active_scenario_id")})
    ws.active_scenario_name = "The selected scenario"
    ws.last_runtime_scenario_id = "0123456789abcdef"
    panel = build_smart_panel_projection(trust_pack=None, runtime_state="STALE", has_runtime=True, project_key="")
    out = _attach_insight(panel, ws=ws, pis=None, project_record=get_project_by_code(user, rec.project_code),
                          workspace_owner=user, runtime_state="STALE", register_view=None)
    ident = out.insight["quality"]["identity"]
    assert ident["scenario_name"] == "" and ident["scenario_id"] == "0123456789abcdef"
    assert "Base Case" not in str(ident) and "selected scenario" not in str(ident)
    assert scenario_label(SimpleNamespace(
        last_runtime_scenario_id="0123456789abcdef",
        active_scenario_id=real.active_scenario_id,
        active_scenario_name="The selected scenario",
    )) == "UNAVAILABLE"


# ─────────────────────────── four verticals: Q1 unchanged, identity shown ───────────────────────────

@pytest.mark.parametrize("key", list(VERTICALS))
def test_G_verticals_identity_and_q1_results_unchanged(env, key):
    from app.model_quality import evaluate_model_quality
    from app.model_quality.evidence import evidence_from_workspace, terms_from_project_inputs
    from app.persistence.projects_repository import get_project_by_code
    from app.v2.router import _build_pis_with_composite_identity
    user = f"q3id-g-{key}"
    rec = project(user, VERTICALS[key], name=f"Vertical {key}")
    run(env, user, rec)
    payload = diag(env, user, rec)
    assert scenario_line(payload).startswith("Base Case")
    ws = last_run(user, rec)
    pis = _build_pis_with_composite_identity(ws, get_project_by_code(user, rec.project_code), user)
    report = evaluate_model_quality(evidence_from_workspace(
        ws, freshness="CURRENT", terms=terms_from_project_inputs(pis.to_projectinputs()),
        active_scenario_id=ws.active_scenario_id, scenario_known=True))
    got = {row["check_id"]: row["status"] for rows in payload["insight"]["groups"].values() for row in rows}
    assert got == {c.check_id: c.status.value for c in report.checks} and len(got) == 30
    s = report.summary
    score = payload["insight"]["score"]
    if s.score is not None:
        assert score["score_display"] == f"{s.score:.1f} / 100"
    else:
        assert score["score_display"] is None and "Not scored" in score["score_note"]
    assert score["coverage_weighted_pct"] == round(s.coverage_weighted * 100, 1)
    lock = next(c for c in payload["insight"]["covenants"] if c["type"] == "Distribution lock-up DSCR")["status"]
    assert lock == next(c for c in report.checks if c.check_id == "QM-COV-002").status.value
