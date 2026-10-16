"""SC-07: one canonical project name. The Project setup field writes through to the project record in the same transaction, so the navigation
header, page title, Project library card and the field itself agree after Save, reload and scenario navigation. Stable ids/codes, owner isolation
and committed Run History are not touched; a stale or invalid rename changes neither side."""
from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

HTMX = {"HX-Request": "true"}
NAME_FIELD = "project_setup.identity.project_name"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from app.persistence import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "id.db"))
    db.init_db()
    import main_web
    return TestClient(main_web.app, raise_server_exceptions=False)


def _login(client, uid):
    from app.auth import COOKIE_NAME, create_session_token
    client.cookies.set(COOKIE_NAME, create_session_token(user_id=uid, username="admin"))


def _project(client, uid, name="Original Name"):
    from app.services.reference_seed_service import create_reference_seeded_project
    rec = create_reference_seeded_project(user_id=uid, template_source="generic_solar_reference", requested_name=name, capacity_mw=40.0)
    _login(client, uid)
    return rec


def _identity(client, rec):
    html = client.get(f"/v2/workbook?project={rec.project_code}").text
    return (re.search(r'data-content-hash="([^"]+)"', html).group(1), re.search(r'data-workbook-version="([^"]+)"', html).group(1), html)


def _rename(client, rec, value, content_hash, version):
    return client.post("/v2/workbook/update", headers=HTMX, data={
        "project": rec.project_code, "sheet_id": "project_setup", "field_id": NAME_FIELD, "value": value,
        "content_hash": content_hash, "workbook_version": version})


def _record(uid, rec):
    from app.persistence.projects_repository import resolve_accessible_project
    return resolve_accessible_project(uid, rec.project_code)[0]


def _snapshot_name(uid, rec):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.input_set import ProjectInputSet
    return ProjectInputSet.from_snapshot(get_workspace_state(uid, rec.project_id).draft_snapshot).get(NAME_FIELD)


def test_rename_is_coherent_across_record_header_library_and_reload(env):
    rec = _project(env, "sc34-id-1")
    ch, wv, html = _identity(env, rec)
    assert re.findall(r'v2-toolbar-name">([^<]*)', html) == ["Original Name"]
    r = _rename(env, rec, "  Renamed Project  ", ch, wv)
    assert r.status_code == 200
    after = _record("sc34-id-1", rec)
    assert after.project_name == "Renamed Project"                                    # canonical owner, trimmed
    assert (after.project_id, after.project_code) == (rec.project_id, rec.project_code)      # stable identity
    assert _snapshot_name("sc34-id-1", rec) == "Renamed Project"                        # the field mirrors the same value
    page = env.get(f"/v2/workbook?project={rec.project_code}").text
    assert re.findall(r'v2-toolbar-name">([^<]*)', page) == ["Renamed Project"]
    assert "<title>Renamed Project — Workbook</title>" in page
    library = env.get("/library").text
    assert "Renamed Project" in library and "Original Name" not in library


def test_a_stale_rename_changes_neither_the_record_nor_the_working_copy(env):
    rec = _project(env, "sc34-id-2")
    ch, wv, _ = _identity(env, rec)
    r = _rename(env, rec, "Stale Name", "0" * 64, wv)
    assert r.headers.get("HX-Trigger") and "conflict" in r.headers["HX-Trigger"]
    assert _record("sc34-id-2", rec).project_name == "Original Name"
    assert _snapshot_name("sc34-id-2", rec) == "Original Name"


def test_a_blank_rename_is_refused_and_the_record_name_survives(env):
    rec = _project(env, "sc34-id-3")
    ch, wv, _ = _identity(env, rec)
    _rename(env, rec, "   ", ch, wv)
    assert _record("sc34-id-3", rec).project_name == "Original Name"
    assert _snapshot_name("sc34-id-3", rec) == "Original Name"


def test_scenario_navigation_keeps_the_renamed_identity(env):
    rec = _project(env, "sc34-id-4")
    ch, wv, _ = _identity(env, rec)
    _rename(env, rec, "Scenario Safe Name", ch, wv)
    made = env.post("/v2/workbook/scenarios/create", headers=HTMX, data={"project": rec.project_code, "scenario_name": "Upside"})
    assert made.status_code == 200, made.text
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.scenarios_repository import list_scenarios
    scenarios = list_scenarios("sc34-id-4", rec.project_id)
    for sc in scenarios:
        assert env.post("/v2/workbook/scenarios/select", headers=HTMX, data={"project": rec.project_code, "scenario_id": sc.scenario_id}).status_code == 200
        page = env.get(f"/v2/workbook?project={rec.project_code}").text
        assert re.findall(r'v2-toolbar-name">([^<]*)', page) == ["Scenario Safe Name"]
    assert _snapshot_name("sc34-id-4", rec) == "Scenario Safe Name"
    assert get_workspace_state("sc34-id-4", rec.project_id) is not None


def test_a_rename_never_touches_committed_run_history_or_other_owners(env):
    from app.persistence.run_history_repository import get_run_history
    rec = _project(env, "sc34-id-5")
    other = _project(env, "sc34-id-6", name="Other Owner Project")
    _login(env, "sc34-id-5")
    ch, wv, _ = _identity(env, rec)
    run = env.post("/v2/workbook/run", headers=HTMX, data={"project": rec.project_code, "workbook_version": wv, "content_hash": ch})
    assert run.status_code == 200, run.text
    before = json.dumps(get_run_history("sc34-id-5", rec.project_id), default=str, sort_keys=True)
    assert before != "[]"
    ch2, wv2, _ = _identity(env, rec)
    assert _rename(env, rec, "Renamed After Run", ch2, wv2).status_code == 200
    assert json.dumps(get_run_history("sc34-id-5", rec.project_id), default=str, sort_keys=True) == before
    assert _record("sc34-id-6", other).project_name == "Other Owner Project"            # owner isolation
