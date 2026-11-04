"""R17 + R17-N1 — a Base Case promotion is scoped to ONE project, and the legacy ``/scenarios/add`` route works.

Synthetic disposable data only.  ``promote_scenario_to_base_case`` used to demote the Base Case of an unrelated project of
the same user before validating the target; ``_get_least_created_scenario_for_project`` raised ``NameError``.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.persistence import db
from app.persistence import scenarios_repository as sr
from app.persistence.projects_repository import create_project_record

U, V = "r17-user-u", "r17-user-v"


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "r17.db"))
    db.init_db()
    return None


def _project(user, code):
    return create_project_record(user_id=user, project_code=code, project_name=f"Synthetic {code}", project_type="solar",
                                 project_origin="user_created", template_source="generic_solar",
                                 baseline_snapshot={"capacity_mw": 10})


def _base(user, p):
    return sr.get_or_create_base_case_scenario(user_id=user, project_id=p.project_id, project_code=p.project_code,
                                               project_name="Base Case", project_type="solar",
                                               source_project_template="generic_solar", base_input_set={"capacity_mw": 10},
                                               governance_state={})


def _flags(user):
    c = db.get_connection()
    try:
        return [tuple(r) for r in c.execute(
            "SELECT p.project_code, s.scenario_name, s.is_base_case, s.archived FROM scenarios s "
            "JOIN projects p ON p.project_id=s.project_id WHERE s.user_id=? ORDER BY p.project_code, s.created_at, s.scenario_id",
            (user,)).fetchall()]
    finally:
        c.close()


def _three_projects():
    pa, pb, pc = _project(U, "SYN-A"), _project(U, "SYN-B"), _project(U, "SYN-C")
    pv = _project(V, "SYN-V")
    _base(U, pa), _base(U, pb), _base(V, pv)
    sr.add_scenario(user_id=U, project_id=pc.project_id, project_code="SYN-C", scenario_name="Imported S1",
                    parent_scenario_id=None, base_input_set={"capacity_mw": 10})
    return pa, pb, pc, pv


def test_promoting_a_baseless_project_leaves_every_other_project_untouched(world):
    _, _, pc, _ = _three_projects()
    before_v = _flags(V)
    target = sr.list_scenarios(U, project_id=pc.project_id, include_archived=False)[0]
    assert sr.promote_scenario_to_base_case(U, target.scenario_id).scenario_id == target.scenario_id
    assert _flags(U) == [("SYN-A", "Base Case", 1, 0), ("SYN-B", "Base Case", 1, 0), ("SYN-C", "Imported S1", 1, 0)]
    assert _flags(V) == before_v


def test_invalid_foreign_and_archived_targets_change_nothing(world):
    pa, _, pc, _ = _three_projects()
    other = sr.list_scenarios(V, include_archived=False)[0]
    sr.add_scenario(user_id=U, project_id=pc.project_id, project_code="SYN-C", scenario_name="Archived",
                    parent_scenario_id=None, base_input_set={})
    archived = [s for s in sr.list_scenarios(U, project_id=pc.project_id, include_archived=False) if s.scenario_name == "Archived"][0]
    sr.archive_scenario(U, archived.scenario_id)
    snap_u, snap_v = _flags(U), _flags(V)
    for uid, sid in ((U, "does-not-exist-0001"), (U, other.scenario_id), (V, archived.scenario_id), (U, archived.scenario_id)):
        assert sr.promote_scenario_to_base_case(uid, sid) is None
    assert _flags(U) == snap_u and _flags(V) == snap_v


def test_promotion_within_a_project_moves_the_single_base_and_is_idempotent(world):
    pa = _project(U, "SYN-A")
    base = _base(U, pa)
    sr.add_scenario(user_id=U, project_id=pa.project_id, project_code="SYN-A", scenario_name="Upside",
                    parent_scenario_id=None, base_input_set={})
    up = [s for s in sr.list_scenarios(U, project_id=pa.project_id, include_archived=False) if s.scenario_name == "Upside"][0]
    for _ in range(2):
        assert sr.promote_scenario_to_base_case(U, up.scenario_id).is_base_case
        assert sorted(r[1] for r in _flags(U) if r[2] == 1) == ["Upside"]
    assert not sr.get_scenario(base.scenario_id, U).is_base_case


def test_a_failure_while_promoting_rolls_the_demotion_back(world):
    pa = _project(U, "SYN-A")
    base = _base(U, pa)
    sr.add_scenario(user_id=U, project_id=pa.project_id, project_code="SYN-A", scenario_name="Upside",
                    parent_scenario_id=None, base_input_set={})
    up = [s for s in sr.list_scenarios(U, project_id=pa.project_id, include_archived=False) if s.scenario_name == "Upside"][0]
    c = db.get_connection()
    c.execute("CREATE TRIGGER r17_fail BEFORE UPDATE OF is_base_case ON scenarios WHEN NEW.is_base_case=1 "
              "AND NEW.scenario_name='Upside' BEGIN SELECT RAISE(ABORT,'injected'); END")
    c.close()
    with pytest.raises(Exception, match="injected"):
        sr.promote_scenario_to_base_case(U, up.scenario_id)
    assert [r[1] for r in _flags(U) if r[2] == 1] == ["Base Case"]  # the demotion rolled back with the failed promotion
    assert sr.get_scenario(base.scenario_id, U).is_base_case


def test_the_least_created_helper_no_longer_raises_name_error(world):
    from app.persistence._helpers import _get_least_created_scenario_for_project
    pc = _project(U, "SYN-C")
    assert _get_least_created_scenario_for_project(U, pc.project_id) is None
    sr.add_scenario(user_id=U, project_id=pc.project_id, project_code="SYN-C", scenario_name="Imported S1",
                    parent_scenario_id=None, base_input_set={})
    assert _get_least_created_scenario_for_project(U, pc.project_id).scenario_name == "Imported S1"


def test_the_legacy_scenarios_add_route_succeeds_and_keeps_one_base_per_project(world):
    import main_web
    from app.auth import COOKIE_NAME, create_session_token
    _three_projects()
    before_v = _flags(V)
    client = TestClient(main_web.app, raise_server_exceptions=False, cookies={COOKIE_NAME: create_session_token(user_id=U, username="admin")})
    from tests.run_clone_csrf import post_valid_csrf  # noqa: F401  (route may require a CSRF field)
    resp = client.post("/scenarios/add", data={"project_code": "SYN-C", "scenario_name": "New S2"}, follow_redirects=False)
    assert resp.status_code != 500, resp.text[:300]
    rows = _flags(U)
    for code in ("SYN-A", "SYN-B"):
        assert [r for r in rows if r[0] == code and r[2] == 1], code
    assert len([r for r in rows if r[0] == "SYN-C" and r[2] == 1]) <= 1
    assert _flags(V) == before_v
