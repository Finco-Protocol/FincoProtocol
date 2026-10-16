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


@pytest.fixture()
def identity_case(tmp_path, monkeypatch):
    from app.persistence import db
    from app.persistence.projects_repository import _compute_baseline_snapshot, create_project_record
    from app.persistence.workspace_repository import save_workspace_state
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "identity-atomic.db"))
    db.init_db()
    snapshot = _compute_baseline_snapshot("Solar", "generic_solar_reference")
    snapshot.update(project_name="Original Name", project_origin="saved_baseline")
    record = create_project_record(
        user_id="a4-identity", project_code="a4-identity", project_name="Original Name", project_type="Solar",
        project_origin="saved_baseline", template_source="generic_solar_reference", baseline_snapshot=snapshot,
    )
    save_workspace_state(
        user_id=record.user_id, project_id=record.project_id, project_code=record.project_code,
        draft_snapshot=snapshot, saved_snapshot=snapshot,
    )
    token = assemble_consistent_for_get(user_id=record.user_id, project_id=record.project_id, workbook_version=WORKBOOK.version).composite_hash
    return record, token


def _atomic_rows(record):
    from app.persistence.db import get_connection

    conn = get_connection()
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        return {
            table: [dict(row) for row in conn.execute(f"SELECT * FROM {table} WHERE project_id=?", (record.project_id,))]
            for table in ("projects", "workspace_states", "model_run_history")
        }
    finally:
        conn.close()


@pytest.mark.parametrize("failure", ["ignore", "abort", "owner_mismatch"])
def test_rename_project_update_failure_rolls_back_entire_workspace(identity_case, failure):
    import sqlite3
    from app.persistence.db import get_cursor
    from app.persistence.workspace_repository import v2_atomic_draft_update
    from app.workbook.update_service import StaleContentError

    record, token = identity_case
    with get_cursor() as cur:
        assert cur.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        if failure == "owner_mismatch":
            cur.execute("UPDATE projects SET user_id=? WHERE project_id=?", ("other-owner", record.project_id))
        else:
            action = "IGNORE" if failure == "ignore" else "ABORT, 'synthetic project update failure'"
            cur.execute(f"CREATE TRIGGER reject_project_rename BEFORE UPDATE OF project_name ON projects BEGIN SELECT RAISE({action}); END")
    before = _atomic_rows(record)
    expected_error = sqlite3.IntegrityError if failure == "abort" else StaleContentError
    message = "synthetic project update failure" if failure == "abort" else "PROJECT_NAME_WRITE_CONFLICT"
    with pytest.raises(expected_error, match=message):
        v2_atomic_draft_update(
            user_id=record.user_id, project_id=record.project_id, expected_content_hash=token,
            field_id=NAME_FIELD, typed_value="Must Roll Back",
        )
    assert _atomic_rows(record) == before


def test_missing_project_name_mirror_fails_closed_with_foreign_keys_on(identity_case):
    from app.persistence.db import get_cursor
    from app.persistence.workspace_repository import mirror_project_name_cursor
    from app.workbook.update_service import StaleContentError

    record, _ = identity_case
    before = _atomic_rows(record)
    with pytest.raises(StaleContentError, match="PROJECT_NAME_WRITE_CONFLICT"):
        with get_cursor() as cur:
            assert cur.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            mirror_project_name_cursor(
                cur, user_id=record.user_id, project_id="missing-project",
                before={"project_name": "Original"}, after={"project_name": "Missing"}, now_iso="2026-10-16T00:00:00+00:00",
            )
    assert _atomic_rows(record) == before


def test_synthetic_stale_rename_never_attempts_project_update(identity_case):
    from app.persistence.db import get_cursor
    from app.persistence.workspace_repository import v2_atomic_draft_update

    record, _ = identity_case
    with get_cursor() as cur:
        cur.execute("CREATE TRIGGER reject_project_rename BEFORE UPDATE OF project_name ON projects BEGIN SELECT RAISE(ABORT, 'must not reach project update'); END")
    before = _atomic_rows(record)
    result = v2_atomic_draft_update(
        user_id=record.user_id, project_id=record.project_id, expected_content_hash="0" * 64,
        field_id=NAME_FIELD, typed_value="Stale",
    )
    assert result is None
    assert _atomic_rows(record) == before


def test_zero_row_project_update_is_reported_as_conflict_not_saved(env):
    from app.persistence.db import get_cursor

    record = _project(env, "a4-identity-http")
    token, version, _ = _identity(env, record)
    with get_cursor() as cur:
        assert cur.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        cur.execute("CREATE TRIGGER reject_project_rename BEFORE UPDATE OF project_name ON projects BEGIN SELECT RAISE(IGNORE); END")
    before = _atomic_rows(record)
    response = _rename(env, record, "Must Roll Back", token, version)
    events = json.loads(response.headers["HX-Trigger"])
    assert events["workbook-field-error"]["conflict"] is True
    assert "workbook-field-saved" not in events
    assert _atomic_rows(record) == before


def test_non_name_scalar_update_does_not_require_project_name_write(identity_case):
    from app.persistence.db import get_cursor
    from app.persistence.workspace_repository import v2_atomic_draft_update

    record, token = identity_case
    with get_cursor() as cur:
        cur.execute("CREATE TRIGGER reject_project_rename BEFORE UPDATE OF project_name ON projects BEGIN SELECT RAISE(ABORT, 'not a rename'); END")
    before = _atomic_rows(record)
    result = v2_atomic_draft_update(
        user_id=record.user_id, project_id=record.project_id, expected_content_hash=token,
        field_id="revenue.balancing.cost_eur_per_mwh", typed_value=5.5,
    )
    assert result is not None
    assert float(result.draft_snapshot["rev_balancing_cost_eur_per_mwh"]) == 5.5
    after = _atomic_rows(record)
    assert after["projects"] == before["projects"]
    assert after["model_run_history"] == before["model_run_history"]
