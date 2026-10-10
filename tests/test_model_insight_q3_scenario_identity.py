"""Q3 Correction A — the scenario shown with the Findings is the COMMITTED Last Run's scenario.

Defect: the Findings context read ``Scenario: UNAVAILABLE`` for a Base Case Run (``active_scenario_name`` is empty
for a Base Case that never recorded a scenario id) while the same workbook names it Base / Base Case.
Rule: identity comes from ``ws.last_runtime_scenario_id`` — NULL is the canonical Base Case; an explicit id is resolved
through the owner's and project's own scenario records; an unresolvable id stays UNAVAILABLE; the active Working Copy
scenario's name is never substituted.
"""
from __future__ import annotations

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


def page(env, user, rec):
    return env.client.get(f"/v2/workbook?project={rec.project_code}", cookies=env.cookie(user)).text


def tokens(html):
    return (re.search(r'name="content_hash" value="([^"]+)"', html).group(1),
            re.search(r'name="workbook_version" value="([^"]+)"', html).group(1))


def run(env, user, rec):
    h, v = tokens(page(env, user, rec))
    r = env.client.post("/v2/workbook/run", data={"project": rec.project_code, "content_hash": h, "workbook_version": v},
                        cookies=env.cookie(user), headers={"HX-Request": "true"})
    assert r.status_code == 200
    return r.text


def context(html):
    """The Findings run-identity block text (the Q3 context), whitespace-normalised."""
    m = re.search(r'data-testid="q3-context">(.*?)</div>', html, re.S)
    assert m, "the Q3 Findings context is missing"
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()


def scenario_line(html):
    m = re.search(r"Scenario: (.*?) · Run ", context(html))
    assert m, context(html)
    return m.group(1)


def snapshot_in(html):
    return re.search(r"snapshot (\S+)", context(html)).group(1)


def last_run(user, rec):
    from app.persistence.workspace_repository import get_workspace_state
    return get_workspace_state(user, rec.project_id)


def select(env, user, rec, scenario_id):
    r = env.client.post("/v2/workbook/scenarios/select", data={"project": rec.project_code, "scenario_id": scenario_id},
                        cookies=env.cookie(user), headers={"HX-Request": "true"})
    assert r.status_code == 200
    return r.text


def create_scenario(env, user, rec, name):
    r = env.client.post("/v2/workbook/scenarios/create", data={"project": rec.project_code, "scenario_name": name},
                        cookies=env.cookie(user), headers={"HX-Request": "true"})
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
    assert "q3-context" not in page(env, user, rec)                       # F: NOT_RUN has no committed identity
    oob = run(env, user, rec)
    html = page(env, user, rec)
    assert scenario_line(html) == "Base Case (Base Project)"
    assert "Scenario: UNAVAILABLE" not in context(html)
    assert "Scenario: Base Case" in context(html)
    assert "Scenario: Base Case" in context(oob.split('id="model-smart-panel" hx-swap-oob="true"', 1)[1]), "OOB equals GET"
    assert snapshot_in(html) == last_run(user, rec).last_runtime_snapshot_id[:22]


def test_B_base_case_stale_keeps_the_prior_run_identity_and_unbinds_thresholds(env):
    user, rec = "q3id-b", project("q3id-b", name="Stale Project")
    run(env, user, rec)
    before = page(env, user, rec)
    snap = snapshot_in(before)
    h, v = tokens(before)
    r = env.client.post("/v2/workbook/update", data={"field_id": "project_setup.technical.p50_hours", "value": "1240",
                        "project": rec.project_code, "workbook_version": v, "content_hash": h, "sheet_id": "project_setup"},
                        cookies=env.cookie(user), headers={"HX-Request": "true"})
    assert r.status_code == 200
    after = page(env, user, rec)
    assert re.search(r'data-q3-state="STALE"', after)
    assert scenario_line(after) == "Base Case (Stale Project)" and snapshot_in(after) == snap, "prior Run identity unchanged"
    assert "RUN_THRESHOLD_NOT_BOUND" in after and "PRIOR" in context(after) + after
    oob = r.text.split('id="model-smart-panel" hx-swap-oob="true"', 1)[1]
    assert "Scenario: Base Case" in context(oob) and snapshot_in(oob) == snap


# ─────────────────────────── named scenario and scenario switch ───────────────────────────

def test_C_and_D_named_scenario_identity_and_switch_without_another_run(env):
    user, rec = "q3id-c", project("q3id-c", name="Switch Project")
    run(env, user, rec)
    base_html = page(env, user, rec)
    base_snap = snapshot_in(base_html)
    up = create_scenario(env, user, rec, "Upside")                       # becomes the active Working Copy scenario
    # D: switched, no Run for Upside yet -> the Last Run was cleared by the switch: NOT_RUN, no identity at all
    switched = page(env, user, rec)
    assert 'data-q3-state="NOT_RUN"' in switched and "q3-context" not in switched
    quality_block = switched.split('data-testid="q3-quality"', 1)[1].split('data-testid="smart-panel-inspector"', 1)[0]
    assert "Upside" not in quality_block and "Scenario:" not in quality_block, "no committed identity may be shown"
    run(env, user, rec)                                                  # explicit Run of Upside
    html = page(env, user, rec)
    ws = last_run(user, rec)
    assert scenario_line(html) == "Upside" and "Base Case" not in context(html)
    assert snapshot_in(html) == ws.last_runtime_snapshot_id[:22] != base_snap
    assert ws.last_runtime_scenario_id == up.scenario_id
    # back to the Base Case scenario: its OWN Run is restored, so the identity is the Base Case's, not "Upside"
    from app.persistence.scenarios_repository import get_base_case_scenario
    select(env, user, rec, get_base_case_scenario(user, rec.project_id).scenario_id)
    back = page(env, user, rec)
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
        cur.execute("UPDATE workspace_states SET last_runtime_summary_json=?, last_runtime_snapshot_id=?, last_runtime_scenario_id=NULL,"
                    " last_runtime_composite_hash=?, last_runtime_at=?, last_integrity_evidence_json=?, last_sponsor_schedule_json=?,"
                    " last_runtime_identity_json=? WHERE project_id=?",
                    (h["runtime_summary_json"], h["runtime_snapshot_id"], h["composite_hash"], h["ran_at"],
                     h["integrity_evidence_json"], h["sponsor_schedule_json"], h["last_runtime_identity_json"], rec.project_id))
    html = page(env, user, rec)
    line = scenario_line(html)
    assert "Selected but never run" not in context(html)
    assert line.startswith("Base Case") or line == "UNAVAILABLE"


def test_E_unresolvable_scenario_id_stays_unavailable_through_the_real_attach_path(env):
    """workspace_states.last_runtime_scenario_id is a foreign key, so a dangling id cannot be persisted; the attach
    path is therefore exercised with a record carrying an id that no owner/project-scoped scenario row proves."""
    import copy
    from app.persistence.projects_repository import get_project_by_code
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
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    html = Environment(loader=FileSystemLoader("app/templates/v2"), autoescape=select_autoescape(["html"])).get_template(
        "partials/_model_insight_q3.html").render({"smart_panel": out})
    assert scenario_line(html) == "UNAVAILABLE"


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
    html = page(env, user, rec)
    assert scenario_line(html).startswith("Base Case")
    ws = last_run(user, rec)
    pis = _build_pis_with_composite_identity(ws, get_project_by_code(user, rec.project_code), user)
    report = evaluate_model_quality(evidence_from_workspace(
        ws, freshness="CURRENT", terms=terms_from_project_inputs(pis.to_projectinputs()),
        active_scenario_id=ws.active_scenario_id, scenario_known=True))
    got = dict(re.findall(r'data-q3-check data-check-id="(QM-[A-Z]+-\d+)"\s+data-check-status="(\w+)"', html))
    assert got == {c.check_id: c.status.value for c in report.checks} and len(got) == 30
    s = report.summary
    assert (f"{s.score:.1f} / 100" in html) if s.score is not None else ("NOT SCORED" in html)
    cov = re.search(r'data-testid="q3-coverage">([^<]+)', html).group(1)
    assert f"{round(s.coverage_weighted * 100, 1)}% weighted" in cov
    lock = re.search(r'data-covenant-type="Distribution lock-up DSCR" data-covenant-status="(\w+)"', html).group(1)
    assert lock == next(c for c in report.checks if c.check_id == "QM-COV-002").status.value
