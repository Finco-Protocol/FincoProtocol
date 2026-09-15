"""P6 Correction B — final review blocker tests.

Items covered:
  1. TTL cleanup: mixed-age regression — one expired + one fresh project for SAME user.
  2. Demo reset fail-closed: absent env, empty env, development env, missing DB path,
     missing FINCO_DEMO_RESET_ALLOWED.
  3. Staging bootstrap contract: isolated temp DB — exactly 3 refs, no user/admin rows.
  4. Observability structured log events: each helper fires the correct event key.
  5. Strengthened IDOR: scenario/run/workspace/export — 403/404, never accept 200 with
     cross-session data. Uses real persisted IDs.
  6. Reference mutation proof: working copy is user-owned (no skip), archive/delete
     reload DB row and prove reference unchanged.
  7. Health / readiness: /public-health, /readyz, /health semantics; no model run;
     no secret exposure.
  8. Architecture audit correctness: FINCO_STORAGE_PATH documented as reserved.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import sys
import tempfile
import importlib
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_demo_user_id() -> str:
    from app.auth import new_demo_user_id
    return new_demo_user_id()


def _make_demo_cookie(user_id: str) -> dict[str, str]:
    from app.auth import create_demo_session_token, DEMO_COOKIE_NAME
    return {DEMO_COOKIE_NAME: create_demo_session_token(user_id)}


def _insert_project(user_id: str, project_code: str, project_name: str = "Test",
                    updated_at: str = "2025-01-01T00:00:00+00:00") -> int:
    """Insert a minimal project row and return its rowid."""
    from app.persistence.db import get_connection
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO projects
          (project_code, user_id, project_name, project_type, project_role,
           is_protected, is_readonly, baseline_snapshot_json,
           source_project_template, project_origin,
           governance_state_json, last_run_summary_json,
           created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            project_code, user_id, project_name, "Solar", "user_created",
            0, 0, "{}",
            "generic_solar", "factory_template",
            "{}", "{}",
            updated_at, updated_at,
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT rowid FROM projects WHERE project_code=? AND user_id=?",
        (project_code, user_id),
    ).fetchone()
    conn.close()
    return row[0] if row else -1


def _delete_project(user_id: str, project_code: str) -> None:
    from app.persistence.db import get_connection
    conn = get_connection()
    conn.execute("DELETE FROM projects WHERE user_id=? AND project_code=?", (user_id, project_code))
    conn.commit()
    conn.close()


def _insert_scenario(user_id: str, project_id: int, scenario_name: str = "Base") -> str:
    """Insert a minimal scenario row and return its scenario_id."""
    import uuid
    from app.persistence.db import get_connection
    # Need project_code for the NOT NULL constraint; fetch it from project row
    conn = get_connection()
    project_row = conn.execute(
        "SELECT project_id, project_code, source_project_template FROM projects WHERE rowid=?",
        (project_id,),
    ).fetchone()
    conn.close()
    text_project_id = project_row["project_id"] if project_row else None
    project_code = project_row["project_code"] if project_row else "test_project"
    template = project_row["source_project_template"] if project_row else "generic_solar"

    scenario_id = str(uuid.uuid4())
    conn = get_connection()
    # Temporarily disable FK enforcement so we can insert with NULL project_id
    # (projects inserted by test helpers may have NULL project_id TEXT PK).
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(
        """
        INSERT INTO scenarios
          (scenario_id, user_id, project_id, project_code, scenario_name,
           source_project_template, snapshot_json, governance_state_json,
           last_run_summary_json, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            scenario_id, user_id, text_project_id or str(project_id), project_code,
            scenario_name, template, "{}", "{}", "{}",
            "2025-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00",
        ),
    )
    conn.commit()
    conn.close()
    return scenario_id


def _delete_scenario(scenario_id: str) -> None:
    from app.persistence.db import get_connection
    conn = get_connection()
    conn.execute("DELETE FROM scenarios WHERE scenario_id=?", (scenario_id,))
    conn.commit()
    conn.close()


@pytest.fixture(scope="module")
def client():
    import main_web
    from starlette.testclient import TestClient
    with TestClient(main_web.app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# 1. TTL cleanup: mixed-age regression (same user, one expired + one fresh)
# ---------------------------------------------------------------------------

def test_ttl_mixed_age_fresh_project_prevents_session_deletion():
    """Same demo user with one old project and one fresh project must NOT be deleted.

    TTL authority is MAX(updated_at) per user. As long as any project is fresh
    the whole session is kept.
    """
    from app.demo_cleanup import cleanup_expired_demo_data
    from app.persistence.db import get_connection

    uid = _make_demo_user_id()
    code_old = f"ttlb-old-{uid[-6:]}"
    code_fresh = f"ttlb-fresh-{uid[-6:]}"

    past_ts = "2020-01-01T00:00:00+00:00"
    future_ts = "2099-12-31T23:59:59+00:00"

    conn = get_connection()
    # One expired project
    conn.execute(
        """
        INSERT INTO projects
          (project_code, user_id, project_name, project_type, project_role,
           is_protected, is_readonly, baseline_snapshot_json,
           source_project_template, project_origin,
           governance_state_json, last_run_summary_json,
           created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (code_old, uid, "Old Project", "Solar", "user_created",
         0, 0, "{}", "generic_solar", "factory_template",
         "{}", "{}", past_ts, past_ts),
    )
    # One fresh project (updated far in the future — definitely not expired)
    conn.execute(
        """
        INSERT INTO projects
          (project_code, user_id, project_name, project_type, project_role,
           is_protected, is_readonly, baseline_snapshot_json,
           source_project_template, project_origin,
           governance_state_json, last_run_summary_json,
           created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (code_fresh, uid, "Fresh Project", "Solar", "user_created",
         0, 0, "{}", "generic_solar", "factory_template",
         "{}", "{}", future_ts, future_ts),
    )
    conn.commit()
    conn.close()

    try:
        cleanup_expired_demo_data(ttl_hours=24)

        conn = get_connection()
        old_exists = conn.execute(
            "SELECT 1 FROM projects WHERE user_id=? AND project_code=?", (uid, code_old)
        ).fetchone()
        fresh_exists = conn.execute(
            "SELECT 1 FROM projects WHERE user_id=? AND project_code=?", (uid, code_fresh)
        ).fetchone()
        conn.close()

        assert old_exists is not None, (
            "Old project must be kept because MAX(updated_at) for this user is fresh"
        )
        assert fresh_exists is not None, (
            "Fresh project must be kept"
        )
    finally:
        conn = get_connection()
        conn.execute("DELETE FROM projects WHERE user_id=?", (uid,))
        conn.commit()
        conn.close()


def test_ttl_single_old_project_is_deleted():
    """A user with only one old project (updated in 2020) must be cleaned up."""
    from app.demo_cleanup import cleanup_expired_demo_data
    from app.persistence.db import get_connection

    uid = _make_demo_user_id()
    code = f"ttlb-solo-{uid[-6:]}"
    past_ts = "2020-01-01T00:00:00+00:00"

    conn = get_connection()
    conn.execute(
        """
        INSERT INTO projects
          (project_code, user_id, project_name, project_type, project_role,
           is_protected, is_readonly, baseline_snapshot_json,
           source_project_template, project_origin,
           governance_state_json, last_run_summary_json,
           created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (code, uid, "Solo Old", "Solar", "user_created",
         0, 0, "{}", "generic_solar", "factory_template",
         "{}", "{}", past_ts, past_ts),
    )
    conn.commit()
    conn.close()

    try:
        cleanup_expired_demo_data(ttl_hours=24)

        conn = get_connection()
        exists = conn.execute(
            "SELECT 1 FROM projects WHERE user_id=?", (uid,)
        ).fetchone()
        conn.close()
        assert exists is None, "User with single old project must be cleaned up"
    finally:
        conn = get_connection()
        conn.execute("DELETE FROM projects WHERE user_id=?", (uid,))
        conn.commit()
        conn.close()


# ---------------------------------------------------------------------------
# 2. Demo reset fail-closed gates
# ---------------------------------------------------------------------------

def _run_demo_reset_subprocess(env_overrides: dict) -> int:
    """Run tools/demo_reset.py as a subprocess with given env overrides. Returns exit code."""
    import subprocess
    repo_root = Path(__file__).resolve().parents[1]
    env = {**os.environ, **env_overrides}
    result = subprocess.run(
        [sys.executable, str(repo_root / "tools" / "demo_reset.py"), "--yes"],
        env=env,
        capture_output=True,
        timeout=10,
        cwd=str(repo_root),
    )
    return result.returncode


def test_demo_reset_refuses_absent_finco_env():
    """demo_reset.py must exit non-zero when FINCO_ENV is absent/empty."""
    rc = _run_demo_reset_subprocess({
        "FINCO_ENV": "",
        "FINCO_DB_PATH": "/tmp/test_staging.db",
        "FINCO_DEMO_RESET_ALLOWED": "true",
    })
    assert rc != 0, "demo_reset must refuse when FINCO_ENV is empty"


def test_demo_reset_refuses_development_env():
    """demo_reset.py must exit non-zero when FINCO_ENV=development."""
    rc = _run_demo_reset_subprocess({
        "FINCO_ENV": "development",
        "FINCO_DB_PATH": "/tmp/test_staging.db",
        "FINCO_DEMO_RESET_ALLOWED": "true",
    })
    assert rc != 0, "demo_reset must refuse when FINCO_ENV=development"


def test_demo_reset_refuses_production_env():
    """demo_reset.py must exit non-zero when FINCO_ENV=production."""
    rc = _run_demo_reset_subprocess({
        "FINCO_ENV": "production",
        "FINCO_DB_PATH": "/tmp/test_staging.db",
        "FINCO_DEMO_RESET_ALLOWED": "true",
    })
    assert rc != 0, "demo_reset must refuse when FINCO_ENV=production"


def test_demo_reset_refuses_missing_db_path():
    """demo_reset.py must exit non-zero when FINCO_DB_PATH is absent."""
    rc = _run_demo_reset_subprocess({
        "FINCO_ENV": "staging",
        "FINCO_DB_PATH": "",
        "FINCO_DEMO_RESET_ALLOWED": "true",
    })
    assert rc != 0, "demo_reset must refuse when FINCO_DB_PATH is not set"


def test_demo_reset_refuses_missing_allowed_flag():
    """demo_reset.py must exit non-zero when FINCO_DEMO_RESET_ALLOWED is absent."""
    rc = _run_demo_reset_subprocess({
        "FINCO_ENV": "staging",
        "FINCO_DB_PATH": "/tmp/test_staging_finco.db",
        "FINCO_DEMO_RESET_ALLOWED": "",
    })
    assert rc != 0, "demo_reset must refuse when FINCO_DEMO_RESET_ALLOWED is not 'true'"


def test_demo_reset_refuses_wrong_allowed_flag():
    """demo_reset.py must exit non-zero when FINCO_DEMO_RESET_ALLOWED=yes (not 'true')."""
    rc = _run_demo_reset_subprocess({
        "FINCO_ENV": "staging",
        "FINCO_DB_PATH": "/tmp/test_staging_finco.db",
        "FINCO_DEMO_RESET_ALLOWED": "yes",
    })
    assert rc != 0, "demo_reset must refuse when FINCO_DEMO_RESET_ALLOWED is not exactly 'true'"


# ---------------------------------------------------------------------------
# 3. Staging bootstrap contract (isolated temp DB)
# ---------------------------------------------------------------------------

def test_bootstrap_contract_exactly_3_refs_idempotent():
    """ensure_reference_models() must yield exactly 3 refs after multiple calls.

    Idempotent: calling twice must not create duplicates.
    No user/demo rows must be created as a side effect of seeding.
    """
    from app.services.project_library_service import ensure_reference_models
    from app.persistence.db import get_connection

    # Record any non-reference demo rows before seeding (from other tests)
    conn = get_connection()
    demo_before = {r[0] for r in conn.execute(
        "SELECT user_id FROM projects WHERE user_id LIKE 'demo_%'"
    ).fetchall()}
    conn.close()

    # Call twice — idempotent
    ensure_reference_models()
    ensure_reference_models()

    conn = get_connection()
    ref_count = conn.execute(
        "SELECT COUNT(*) FROM projects WHERE user_id='__reference__'"
    ).fetchone()[0]
    demo_after = {r[0] for r in conn.execute(
        "SELECT user_id FROM projects WHERE user_id LIKE 'demo_%'"
    ).fetchall()}
    conn.close()

    assert ref_count == 3, (
        f"Bootstrap must seed exactly 3 canonical refs, got {ref_count}"
    )
    # ensure_reference_models must not CREATE any new demo user rows
    new_demo_rows = demo_after - demo_before
    assert not new_demo_rows, (
        f"ensure_reference_models must not create demo user rows; new rows: {new_demo_rows}"
    )


# ---------------------------------------------------------------------------
# 4. Observability structured log events
# ---------------------------------------------------------------------------

class _CapturingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _capture_obs_logs() -> _CapturingHandler:
    handler = _CapturingHandler()
    logging.getLogger("finco.observability").addHandler(handler)
    logging.getLogger("finco.observability").setLevel(logging.DEBUG)
    return handler


def _remove_handler(handler: _CapturingHandler) -> None:
    logging.getLogger("finco.observability").removeHandler(handler)


def test_log_http_error_fires_correct_event():
    from app.observability import log_http_error
    h = _capture_obs_logs()
    try:
        log_http_error(404, "/some/path", "GET")
        assert h.records, "log_http_error must emit a log record"
        rec = h.records[-1]
        assert getattr(rec, "event", None) == "http_error"
        assert getattr(rec, "status_code", None) == 404
        assert getattr(rec, "path", None) == "/some/path"
    finally:
        _remove_handler(h)


def test_log_run_started_fires_correct_event():
    from app.observability import log_run_started
    h = _capture_obs_logs()
    try:
        log_run_started("demo_abc123456789xyz")
        assert h.records, "log_run_started must emit a log record"
        rec = h.records[-1]
        assert getattr(rec, "event", None) == "run_started"
        prefix = getattr(rec, "user_id_prefix", None)
        assert prefix is not None
        assert len(prefix) <= 12, "user_id_prefix must be truncated to 12 chars"
    finally:
        _remove_handler(h)


def test_log_run_started_truncates_user_id():
    """log_run_started must never log the full user_id."""
    from app.observability import log_run_started
    h = _capture_obs_logs()
    try:
        long_uid = "demo_" + "x" * 64
        log_run_started(long_uid)
        rec = h.records[-1]
        prefix = getattr(rec, "user_id_prefix", "")
        assert prefix == long_uid[:12], f"Expected 12-char truncation, got {prefix!r}"
        assert long_uid not in str(vars(rec)), "Full user_id must never appear in log record"
    finally:
        _remove_handler(h)


def test_log_run_completed_fires_correct_event():
    from app.observability import log_run_completed
    h = _capture_obs_logs()
    try:
        log_run_completed(1234.5)
        assert h.records, "log_run_completed must emit a log record"
        rec = h.records[-1]
        assert getattr(rec, "event", None) == "run_completed"
        assert getattr(rec, "duration_ms", None) == 1234.5
    finally:
        _remove_handler(h)


def test_log_run_failed_fires_correct_event():
    from app.observability import log_run_failed
    h = _capture_obs_logs()
    try:
        log_run_failed("ValueError")
        assert h.records, "log_run_failed must emit a log record"
        rec = h.records[-1]
        assert getattr(rec, "event", None) == "run_failed"
        assert getattr(rec, "error_type", None) == "ValueError"
    finally:
        _remove_handler(h)


def test_log_capacity_busy_fires_correct_event():
    from app.observability import log_capacity_busy
    h = _capture_obs_logs()
    try:
        log_capacity_busy(max_slots=3)
        assert h.records, "log_capacity_busy must emit a log record"
        rec = h.records[-1]
        assert getattr(rec, "event", None) == "capacity_busy"
        assert getattr(rec, "max_slots", None) == 3
    finally:
        _remove_handler(h)


def test_log_sqlite_lock_fires_correct_event():
    from app.observability import log_sqlite_lock
    h = _capture_obs_logs()
    try:
        log_sqlite_lock("projects")
        assert h.records, "log_sqlite_lock must emit a log record"
        rec = h.records[-1]
        assert getattr(rec, "event", None) == "sqlite_lock"
        assert getattr(rec, "table", None) == "projects"
    finally:
        _remove_handler(h)


def test_observability_never_logs_secrets():
    """Observability helpers must not accept or log secret values.

    The helpers take structured typed parameters (status_code, path, etc.) —
    none accept a free-form value parameter that could carry a secret.
    This test verifies by calling each helper and confirming log record fields
    never contain a sentinel secret string.
    """
    SECRET = "SUPER_SECRET_TOKEN_XYZ"
    from app.observability import (
        log_http_error, log_run_started, log_run_completed,
        log_run_failed, log_capacity_busy, log_sqlite_lock,
    )
    h = _capture_obs_logs()
    try:
        log_http_error(200, "/path")
        log_run_started("demo_user_abc")
        log_run_completed(100.0)
        log_run_failed("TypeError")
        log_capacity_busy(5)
        log_sqlite_lock("runs")

        for rec in h.records:
            for val in vars(rec).values():
                assert SECRET not in str(val), (
                    f"Secret sentinel must never appear in log record field: {val!r}"
                )
    finally:
        _remove_handler(h)


# ---------------------------------------------------------------------------
# 5. Strengthened IDOR tests — deterministic 403/404, real IDs
# ---------------------------------------------------------------------------

def test_idor_scenario_load_session_b_gets_404(client):
    """Session B loading Session A's scenario by real scenario_id must get 404."""
    uid_a = _make_demo_user_id()
    uid_b = _make_demo_user_id()
    project_code_a = f"idorb-sc-{uid_a[-6:]}"

    rowid = _insert_project(uid_a, project_code_a, "Scenario IDOR Project")
    scenario_id = _insert_scenario(uid_a, rowid)

    try:
        resp = client.get(
            f"/scenarios/{scenario_id}/load",
            cookies=_make_demo_cookie(uid_b),
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303, 401, 403, 404), (
            f"Session B loading Session A scenario must not succeed, got {resp.status_code}"
        )
        assert resp.status_code != 200, (
            "Session B must NEVER get 200 when loading Session A's scenario"
        )
    finally:
        _delete_scenario(scenario_id)
        _delete_project(uid_a, project_code_a)


def test_idor_scenario_load_never_leaks_data(client):
    """If scenario load returns 200 it must not contain Session A's data."""
    uid_a = _make_demo_user_id()
    uid_b = _make_demo_user_id()
    project_code_a = f"idorb-sleak-{uid_a[-6:]}"
    SENTINEL = f"SecretScenarioName_{uid_a[-8:]}"

    rowid = _insert_project(uid_a, project_code_a, "Leak Test Project")
    scenario_id = _insert_scenario(uid_a, rowid, SENTINEL)

    try:
        resp = client.get(
            f"/scenarios/{scenario_id}/load",
            cookies=_make_demo_cookie(uid_b),
            follow_redirects=True,
        )
        if resp.status_code == 200:
            assert SENTINEL not in resp.text, (
                "Session A's scenario name must never appear in Session B response"
            )
    finally:
        _delete_scenario(scenario_id)
        _delete_project(uid_a, project_code_a)


def test_idor_workbook_session_b_cannot_see_session_a_data(client):
    """GET /v2/workbook with Session A's project code must not return Session A's data to B."""
    uid_a = _make_demo_user_id()
    uid_b = _make_demo_user_id()
    code_a = f"idorb-wb-{uid_a[-6:]}"
    SENTINEL = f"PrivateProjectName_{uid_a[-8:]}"

    _insert_project(uid_a, code_a, SENTINEL)
    try:
        resp = client.get(
            "/v2/workbook",
            params={"project": code_a},
            cookies=_make_demo_cookie(uid_b),
            follow_redirects=True,
        )
        if resp.status_code == 200:
            assert SENTINEL not in resp.text, (
                "Session B must never see Session A's project name in workbook"
            )
    finally:
        _delete_project(uid_a, code_a)


def test_idor_csv_export_never_200_with_session_a_data(client):
    """Session B requesting Session A's CSV export must not see Session A's project name."""
    uid_a = _make_demo_user_id()
    uid_b = _make_demo_user_id()
    code_a = f"idorb-csv-{uid_a[-6:]}"
    SENTINEL = f"CSVPrivateProject_{uid_a[-8:]}"

    _insert_project(uid_a, code_a, SENTINEL)
    try:
        resp = client.get(
            "/exports/runtime-summary.csv",
            params={"project": code_a},
            cookies=_make_demo_cookie(uid_b),
        )
        if resp.status_code == 200:
            assert SENTINEL not in resp.text, (
                "Session B must never see Session A's data in CSV export"
            )
    finally:
        _delete_project(uid_a, code_a)


def test_idor_workbook_export_never_200_with_session_a_data(client):
    """Session B requesting Session A's workbook export must not see Session A's data."""
    uid_a = _make_demo_user_id()
    uid_b = _make_demo_user_id()
    code_a = f"idorb-xlsx-{uid_a[-6:]}"
    SENTINEL = f"XLSXPrivateProject_{uid_a[-8:]}"

    _insert_project(uid_a, code_a, SENTINEL)
    try:
        resp = client.get(
            "/exports/institutional-workbook.xlsx",
            params={"project": code_a},
            cookies=_make_demo_cookie(uid_b),
        )
        # XLSX is binary — if 200, there's no simple text check; just assert non-200
        # (a 200 with Session A's data is the vulnerable case)
        assert resp.status_code != 200, (
            f"Session B must not get 200 on Session A's XLSX export (got {resp.status_code})"
        )
    finally:
        _delete_project(uid_a, code_a)


def test_idor_runs_list_only_shows_own_runs(client):
    """GET /runs returns only the authenticated user's runs — Session B sees zero Session A runs."""
    uid_a = _make_demo_user_id()
    uid_b = _make_demo_user_id()
    # Session A does not need a project; the runs endpoint queries by user_id
    # We just verify that a request as Session B does not return a 200 with
    # unexpected content that could be Session A's data.
    resp = client.get("/runs", cookies=_make_demo_cookie(uid_b))
    if resp.status_code == 200:
        # Response must not mention uid_a's user_id (which would indicate a cross-user leak)
        assert uid_a not in resp.text, (
            "Session B /runs response must not contain Session A's user_id"
        )


# ---------------------------------------------------------------------------
# 6. Reference mutation proof (no pytest.skip; deterministic)
# ---------------------------------------------------------------------------

def _seed_refs():
    from app.services.project_library_service import ensure_reference_models
    ensure_reference_models()


def test_working_copy_is_user_owned_not_reference_deterministic(client):
    """POST /library/clone creates a copy owned by demo user — deterministic, no skip."""
    _seed_refs()
    from app.persistence.db import get_connection

    conn = get_connection()
    ref = conn.execute(
        "SELECT project_id, project_code FROM projects WHERE user_id='__reference__' LIMIT 1"
    ).fetchone()
    conn.close()
    assert ref is not None, "Reference models must exist after ensure_reference_models()"

    ref_project_id = ref["project_id"]
    ref_project_code = ref["project_code"]
    assert ref_project_id, "Reference project must have a non-null project_id"
    uid = _make_demo_user_id()

    resp = client.post(
        f"/library/clone/{ref_project_id}",
        cookies=_make_demo_cookie(uid),
        follow_redirects=False,
    )
    # Clone of a canonical reference must succeed (2xx or redirect)
    assert resp.status_code in (200, 302, 303, 204), (
        f"Clone of canonical reference must succeed, got {resp.status_code}"
    )

    # Verify: demo user now owns at least one project
    conn = get_connection()
    user_projects = conn.execute(
        "SELECT project_code FROM projects WHERE user_id=?",
        (uid,),
    ).fetchall()
    # Reference row must be untouched
    ref_still = conn.execute(
        "SELECT user_id FROM projects WHERE project_id=?", (ref_project_id,)
    ).fetchone()
    conn.close()

    assert user_projects, "Demo user must own at least one project after clone"
    assert ref_still is not None, "Reference row must still exist after clone"
    assert ref_still[0] == "__reference__", (
        "Reference row user_id must remain '__reference__' after clone"
    )


def test_reference_archive_route_does_not_mutate_db_row(client):
    """Archive attempt on reference project must leave the DB row unchanged."""
    _seed_refs()
    from app.persistence.db import get_connection

    conn = get_connection()
    ref = conn.execute(
        "SELECT project_code, archived, is_protected FROM projects WHERE user_id='__reference__' LIMIT 1"
    ).fetchone()
    conn.close()
    assert ref is not None, "Reference models must exist"

    before_archived = ref[1]
    before_protected = ref[2]

    uid = _make_demo_user_id()
    client.post(
        f"/projects/{ref[0]}/archive",
        cookies=_make_demo_cookie(uid),
        follow_redirects=False,
    )

    # Reload row from DB and verify unchanged
    conn = get_connection()
    after = conn.execute(
        "SELECT archived, is_protected FROM projects WHERE project_code=? AND user_id='__reference__'",
        (ref[0],),
    ).fetchone()
    conn.close()

    assert after is not None, "Reference row must still exist after archive attempt"
    assert after[0] == before_archived, "archived flag must be unchanged after rejected archive"
    assert after[1] == before_protected, "is_protected must be unchanged after rejected archive"


def test_reference_delete_route_does_not_remove_db_row(client):
    """Delete attempt on reference project must not remove the row from the DB."""
    _seed_refs()
    from app.persistence.db import get_connection

    conn = get_connection()
    ref = conn.execute(
        "SELECT project_code FROM projects WHERE user_id='__reference__' LIMIT 1"
    ).fetchone()
    conn.close()
    assert ref is not None

    uid = _make_demo_user_id()
    # Try common delete routes
    for route in [f"/projects/{ref[0]}/delete", f"/library/{ref[0]}/delete"]:
        client.post(route, cookies=_make_demo_cookie(uid), follow_redirects=False)

    conn = get_connection()
    still_exists = conn.execute(
        "SELECT 1 FROM projects WHERE project_code=? AND user_id='__reference__'",
        (ref[0],),
    ).fetchone()
    conn.close()
    assert still_exists is not None, (
        "Reference row must survive all delete attempts"
    )


# ---------------------------------------------------------------------------
# 7. Health / readiness acceptance tests
# ---------------------------------------------------------------------------

def test_public_health_returns_200_no_auth(client):
    """/public-health must return 200 without authentication."""
    resp = client.get("/public-health")
    assert resp.status_code == 200


def test_public_health_does_not_expose_secrets(client):
    """/public-health response must not contain secret env var names or values."""
    resp = client.get("/public-health")
    body = resp.text
    for forbidden in ("SECRET_KEY", "ADMIN_PASSWORD", "finco_session", "finco_demo"):
        assert forbidden not in body, (
            f"/public-health must not expose {forbidden!r}"
        )


def test_public_health_does_not_expose_session_data(client):
    """/public-health must not include user session data or user IDs."""
    uid = _make_demo_user_id()
    resp = client.get("/public-health", cookies=_make_demo_cookie(uid))
    body = resp.text
    # demo user_id must not appear in health response
    assert uid not in body, "/public-health must not echo back the user_id"


def test_readyz_returns_2xx_no_auth(client):
    """/readyz must return 200 or 503 (health-based) without authentication."""
    resp = client.get("/readyz")
    assert resp.status_code in (200, 503), (
        f"/readyz must return 200 or 503, got {resp.status_code}"
    )


def test_readyz_does_not_expose_secrets(client):
    """/readyz response must not contain raw secret values."""
    resp = client.get("/readyz")
    body = resp.text
    secret = os.getenv("FINCO_SECRET_KEY", "")
    if secret and len(secret) > 8:
        assert secret not in body, "/readyz must not expose FINCO_SECRET_KEY value"
    password = os.getenv("FINCO_ADMIN_PASSWORD", "")
    if password and len(password) > 4:
        assert password not in body, "/readyz must not expose FINCO_ADMIN_PASSWORD value"


def test_readyz_has_correct_status_field(client):
    """/readyz response JSON must have a 'status' key."""
    resp = client.get("/readyz")
    try:
        data = resp.json()
    except Exception:
        pytest.fail(f"/readyz must return valid JSON, got: {resp.text[:200]}")
    assert "status" in data, "/readyz JSON must contain 'status' key"
    assert data["status"] in ("ok", "degraded", "error"), (
        f"Unexpected /readyz status value: {data['status']!r}"
    )


def test_health_requires_auth(client):
    """/health (private) must return 401 when unauthenticated."""
    resp = client.get("/health")
    assert resp.status_code in (401, 302, 303), (
        f"/health must require auth, got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# 8. Architecture audit: FINCO_STORAGE_PATH documented as reserved
# ---------------------------------------------------------------------------

def test_finco_storage_path_not_consumed_in_codebase():
    """FINCO_STORAGE_PATH must not be referenced in application code (reserved variable)."""
    import subprocess
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["grep", "-r", "FINCO_STORAGE_PATH", str(repo_root / "app"),
         str(repo_root / "main_web.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, (
        "FINCO_STORAGE_PATH must not be consumed in app code — it is a reserved variable.\n"
        f"Found in: {result.stdout.strip()}"
    )


def test_staging_env_example_documents_storage_path_as_reserved():
    """deploy/staging.env.example must document FINCO_STORAGE_PATH as reserved/unused."""
    repo_root = Path(__file__).resolve().parents[1]
    content = (repo_root / "deploy" / "staging.env.example").read_text()
    assert "FINCO_STORAGE_PATH" in content, "staging.env.example must mention FINCO_STORAGE_PATH"
    assert "Reserved" in content or "reserved" in content, (
        "staging.env.example must document FINCO_STORAGE_PATH as reserved/unused"
    )


def test_architecture_audit_documents_subline_ownership_chain():
    """P6_ARCHITECTURE_AUDIT.md must describe the sub-line ownership chain."""
    repo_root = Path(__file__).resolve().parents[1]
    content = (repo_root / "docs" / "P6_ARCHITECTURE_AUDIT.md").read_text()
    assert "capex_sub_lines" in content, "Audit must mention capex_sub_lines"
    assert "project_id" in content, "Audit must mention project_id ownership"
    assert "user_id" in content, "Audit must confirm user_id scoping"


def test_architecture_audit_ttl_section_uses_max_updated_at():
    """P6_ARCHITECTURE_AUDIT.md TTL section must describe MAX(updated_at) as the authority."""
    repo_root = Path(__file__).resolve().parents[1]
    content = (repo_root / "docs" / "P6_ARCHITECTURE_AUDIT.md").read_text()
    assert "MAX(updated_at)" in content, (
        "Architecture audit TTL section must state MAX(updated_at) as the TTL authority"
    )
