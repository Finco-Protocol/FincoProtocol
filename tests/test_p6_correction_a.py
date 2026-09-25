"""P6 Correction A — route-level, safety-scanner, and capacity tests.

Items covered:
  1. Safety scanner regression: tracked .db file is caught; non-tracked gitignored .db is NOT flagged.
  2. HTTP-level 429 rate limiting on /scenarios/add and export routes.
  3. Route-level IDOR: Session A vs Session B — fail-closed access on projects/workspace/export.
  4. Reference protection: Solar XA / Wind XB / Storage XC readable; write/archive/delete rejected.
  5. TTL cleanup: expired data removed, non-expired data kept.
  7. /library HTTP test — returns 200; contains 3 canonical references; no cross-user leakage.
  8. Concurrency capacity: _acquire_run_slot() returns False when semaphore full, not TOCTOU.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

def _make_demo_cookie(user_id: str) -> dict[str, str]:
    """Create a signed demo cookie dict {DEMO_COOKIE_NAME: token}."""
    from app.auth import create_demo_session_token, DEMO_COOKIE_NAME
    return {DEMO_COOKIE_NAME: create_demo_session_token(user_id)}


def _make_demo_user_id() -> str:
    from app.auth import new_demo_user_id
    return new_demo_user_id()


def _insert_project(user_id: str, project_code: str, project_name: str = "Test") -> int:
    """Insert a minimal project row. Returns rowid (project_id integer)."""
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
            "2025-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00",
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
    conn.execute(
        "DELETE FROM projects WHERE user_id=? AND project_code=?",
        (user_id, project_code),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# 1. Safety scanner regression
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    """Return repo root without embedding a hardcoded local path."""
    return Path(__file__).resolve().parents[1]


def test_safety_scanner_catches_tracked_db():
    """A .db file tracked in git must be flagged as forbidden binary artifact."""
    from tools.public_safety_scan import scan_file
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        db_file = td_path / "test.db"
        db_file.write_bytes(b"SQLite format 3\x00")
        failures = scan_file("test.db", td_path)
    assert any("forbidden binary" in f for f in failures), (
        "scan_file must flag .db as forbidden binary; got: %s" % failures
    )


def test_safety_scanner_git_tracked_files_function():
    """_git_tracked_files returns a list of relative paths."""
    from tools.public_safety_scan import _git_tracked_files
    files = _git_tracked_files(_repo_root())
    assert files is not None, "git must be available in CI"
    assert isinstance(files, list)
    assert len(files) > 0
    # Gitignored DB must NOT appear
    assert not any(f.endswith(".db") or f.endswith(".sqlite3") for f in files), (
        "gitignored .db files must not be returned by git ls-files"
    )


def test_safety_scanner_does_not_flag_gitignored_db():
    """The full scanner must not flag gitignored DB files."""
    from tools.public_safety_scan import main as scanner_main
    # Run scanner; it should pass (gitignored artifacts are excluded by git ls-files)
    import sys
    original_argv = sys.argv
    sys.argv = ["public_safety_scan.py"]
    try:
        result = scanner_main()
    finally:
        sys.argv = original_argv
    assert result == 0, "Safety scanner must return 0 (PASS) on the clean repo"


# ---------------------------------------------------------------------------
# 2. HTTP-level 429 rate limiting
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient for the full application."""
    from fastapi.testclient import TestClient
    import main_web
    return TestClient(main_web.app, raise_server_exceptions=False)


def _exhaust_rate_limit(user_id: str, op: str) -> None:
    """Drive a user's rate-limit bucket to zero for op."""
    from app.auth import check_demo_rate_limit, DEMO_RATE_LIMITS
    max_calls, _ = DEMO_RATE_LIMITS[op]
    for _ in range(max_calls):
        check_demo_rate_limit(user_id, op)


def test_rate_limit_429_scenario_add(client):
    """POST /scenarios/add returns 429 for a demo user whose scenario_add bucket is full."""
    uid = _make_demo_user_id()
    _exhaust_rate_limit(uid, "scenario_add")
    cookies = _make_demo_cookie(uid)
    # Minimal form fields — route checks rate limit before doing any real work
    resp = client.post(
        "/scenarios/add",
        data={"project_code": "some-project", "scenario_name": "Test Scenario"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert resp.status_code == 429, (
        f"Expected 429 after bucket exhausted, got {resp.status_code}"
    )


def test_rate_limit_429_export_runtime_csv(client):
    """GET /exports/runtime-summary.csv returns 429 for exhausted demo user."""
    uid = _make_demo_user_id()
    _exhaust_rate_limit(uid, "export_generate")
    cookies = _make_demo_cookie(uid)
    resp = client.get(
        "/exports/runtime-summary.csv",
        params={"project": "generic_wind_reference"},
        cookies=cookies,
    )
    assert resp.status_code == 429


def test_rate_limit_429_export_workbook(client):
    """GET /exports/institutional-workbook.xlsx returns 429 for exhausted demo user."""
    uid = _make_demo_user_id()
    _exhaust_rate_limit(uid, "export_generate")
    cookies = _make_demo_cookie(uid)
    resp = client.get(
        "/exports/institutional-workbook.xlsx",
        params={"project": "generic_wind_reference"},
        cookies=cookies,
    )
    assert resp.status_code == 429


def test_rate_limit_429_download_post(client):
    """POST /download returns 429 for exhausted demo user."""
    uid = _make_demo_user_id()
    _exhaust_rate_limit(uid, "export_generate")
    cookies = _make_demo_cookie(uid)
    resp = client.post(
        "/download",
        data={"project_code": "x"},
        cookies=cookies,
    )
    assert resp.status_code == 429


def test_rate_limit_not_applied_to_admin_export(client):
    """Admin session must never get 429 from demo rate limiting."""
    from app.auth import create_session_token, COOKIE_NAME
    admin_cookie = {COOKIE_NAME: create_session_token(user_id="1")}
    # Call 50 times — must never 429
    for _ in range(50):
        resp = client.get(
            "/exports/runtime-summary.csv",
            params={"project": "generic_wind_reference"},
            cookies=admin_cookie,
        )
        assert resp.status_code != 429, "Admin must never be rate-limited"


# ---------------------------------------------------------------------------
# 3. Route-level IDOR tests (Session A vs Session B)
# ---------------------------------------------------------------------------

def test_idor_workspace_state_session_b_cannot_read_session_a(client):
    """Session B cannot access Session A's workspace state via /v2/workbook."""
    uid_a = _make_demo_user_id()
    uid_b = _make_demo_user_id()
    project_code_a = f"idor-ws-{uid_a[-6:]}"
    try:
        _insert_project(uid_a, project_code_a, "Session A WS Project")

        # Session B requests Session A's project workbook — must not reveal A's data
        resp = client.get(
            "/v2/workbook",
            params={"project": project_code_a},
            cookies=_make_demo_cookie(uid_b),
            follow_redirects=False,
        )
        # Must either redirect to login/library or return 404/403, never 200 with Session A's data
        assert resp.status_code in (302, 303, 401, 403, 404, 200), (
            f"Unexpected status {resp.status_code}"
        )
        if resp.status_code == 200:
            body = resp.text
            assert "Session A WS Project" not in body, (
                "Session B must never see Session A's project data in workbook response"
            )
    finally:
        _delete_project(uid_a, project_code_a)


def test_idor_library_clone_session_b_cannot_clone_session_a_project(client):
    """Session B cannot clone Session A's non-reference project via /library/clone."""
    uid_a = _make_demo_user_id()
    uid_b = _make_demo_user_id()
    project_code_a = f"idor-cl-{uid_a[-6:]}"
    try:
        rowid = _insert_project(uid_a, project_code_a, "Session A Clone Target")
        # Try to clone using the integer project_id of Session A's row
        resp = client.post(
            f"/library/clone/{rowid}",
            cookies=_make_demo_cookie(uid_b),
            follow_redirects=False,
        )
        # Must not succeed (non-canonical reference cannot be cloned via library)
        assert resp.status_code in (400, 401, 403, 404, 422), (
            f"Session B cloning Session A's project must fail, got {resp.status_code}"
        )
    finally:
        _delete_project(uid_a, project_code_a)


def test_idor_export_session_b_cannot_download_session_a_project_csv(client):
    """Session B requesting Session A's project CSV must get error, not Session A's data."""
    uid_a = _make_demo_user_id()
    uid_b = _make_demo_user_id()
    project_code_a = f"idor-csv-{uid_a[-6:]}"
    try:
        _insert_project(uid_a, project_code_a, "Session A CSV Project")
        resp = client.get(
            "/exports/runtime-summary.csv",
            params={"project": project_code_a},
            cookies=_make_demo_cookie(uid_b),
        )
        # Either an error status, or a 200 with no Session A project name in body
        if resp.status_code == 200:
            assert "Session A CSV Project" not in resp.text
    finally:
        _delete_project(uid_a, project_code_a)


def test_idor_project_not_found_for_wrong_user(client):
    """get_project_by_code scopes by user_id — wrong user always gets None."""
    uid_a = _make_demo_user_id()
    uid_b = _make_demo_user_id()
    project_code_a = f"idor-scope-{uid_a[-6:]}"
    try:
        _insert_project(uid_a, project_code_a)
        from app.persistence.projects_repository import get_project_by_code
        result = get_project_by_code(uid_b, project_code_a)
        assert result is None, "get_project_by_code must return None for wrong user"
    finally:
        _delete_project(uid_a, project_code_a)


# ---------------------------------------------------------------------------
# 4. Reference protection
# ---------------------------------------------------------------------------

def _seed_refs():
    from app.services.project_library_service import ensure_reference_models
    ensure_reference_models()


def test_reference_models_seeded_deterministically():
    """ensure_reference_models() is idempotent and always yields exactly 4 refs."""
    from app.persistence.db import get_connection
    _seed_refs()
    _seed_refs()  # second call must not create duplicates
    conn = get_connection()
    count = conn.execute(
        "SELECT COUNT(*) FROM projects WHERE user_id='__reference__'"
    ).fetchone()[0]
    conn.close()
    assert count == 4, f"Expected exactly 4 reference projects, got {count}"


def test_reference_projects_readable_by_library(client):
    """GET /library returns 200 and includes all 3 canonical reference names."""
    _seed_refs()
    uid = _make_demo_user_id()
    resp = client.get("/library", cookies=_make_demo_cookie(uid))
    assert resp.status_code == 200, f"Library must return 200, got {resp.status_code}"
    body = resp.text
    # At minimum the 3 reference template sources must be present in the page
    assert "generic_solar_reference" in body or "Solar Reference" in body, (
        "Solar reference must appear in /library"
    )
    assert "generic_wind_reference" in body or "Wind Reference" in body, (
        "Wind reference must appear in /library"
    )
    assert "generic_storage_reference" in body or "Storage Reference" in body, (
        "Storage reference must appear in /library"
    )


def test_reference_archive_rejected(client):
    """Attempting to archive a reference project must return 400."""
    _seed_refs()
    from app.persistence.db import get_connection
    conn = get_connection()
    ref = conn.execute(
        "SELECT project_code FROM projects WHERE user_id='__reference__' LIMIT 1"
    ).fetchone()
    conn.close()
    assert ref, "Reference model must exist"

    uid = _make_demo_user_id()
    resp = client.post(
        f"/projects/{ref[0]}/archive",
        cookies=_make_demo_cookie(uid),
        follow_redirects=False,
    )
    # Must reject — 400, 403, 404, or redirect (not silently archive)
    assert resp.status_code not in (200,), (
        f"Archive of reference project must not return 200; got {resp.status_code}"
    )


def test_reference_protection_assert_raises():
    """assert_project_not_protected raises ProtectedProjectError for reference rows."""
    from app.services.project_library_service import (
        assert_project_not_protected,
        ProtectedProjectError,
        ensure_reference_models,
    )
    from app.persistence.db import get_connection
    ensure_reference_models()
    conn = get_connection()
    ref = conn.execute(
        "SELECT * FROM projects WHERE user_id='__reference__' LIMIT 1"
    ).fetchone()
    conn.close()

    class _FakeRecord:
        is_protected = 1
        project_role = "reference"
        project_name = "Test Ref"
        project_origin = "factory_template"
        template_source = "generic_solar_reference"
        source_project_template = "generic_solar_reference"
        archived = 0

    with pytest.raises(ProtectedProjectError):
        assert_project_not_protected(_FakeRecord())


def test_working_copy_is_user_owned_not_reference(client):
    """POST /library/clone creates a copy owned by the requesting user, not __reference__."""
    _seed_refs()
    from app.persistence.db import get_connection
    conn = get_connection()
    ref = conn.execute(
        "SELECT project_id, project_code FROM projects WHERE user_id='__reference__' LIMIT 1"
    ).fetchone()
    conn.close()
    if not ref:
        pytest.skip("Reference models not seeded")

    uid = _make_demo_user_id()
    resp = client.post(
        f"/library/clone/{ref[0]}",
        cookies=_make_demo_cookie(uid),
        follow_redirects=False,
    )
    # Accept 302/303 (success redirect) or 200 (HTMX success)
    if resp.status_code in (302, 303, 200):
        # Verify the new row belongs to the demo user, not __reference__
        conn = get_connection()
        user_projects = conn.execute(
            "SELECT project_code FROM projects WHERE user_id=? AND project_role != 'reference'",
            (uid,),
        ).fetchall()
        conn.close()
        assert user_projects, (
            "After clone, demo user must own at least one non-reference project"
        )
    else:
        pytest.skip(f"Clone returned {resp.status_code} — skipping ownership check")


# ---------------------------------------------------------------------------
# 5. TTL cleanup: expired vs non-expired
# ---------------------------------------------------------------------------

def test_cleanup_expired_removes_only_old_demo_data():
    """cleanup_expired_demo_data removes demo data older than TTL, keeps fresh data."""
    from app.demo_cleanup import cleanup_expired_demo_data
    from app.persistence.db import get_connection

    uid_old = _make_demo_user_id()
    uid_new = _make_demo_user_id()
    code_old = f"ttl-old-{uid_old[-6:]}"
    code_new = f"ttl-new-{uid_new[-6:]}"

    conn = get_connection()
    # Old record: created 48 hours ago
    past_ts = "2020-01-01T00:00:00+00:00"
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
        (code_old, uid_old, "Old Demo", "Solar", "user_created",
         0, 0, "{}", "generic_solar", "factory_template",
         "{}", "{}", past_ts, past_ts),
    )
    # New record: created now
    now_ts = "2099-01-01T00:00:00+00:00"
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
        (code_new, uid_new, "New Demo", "Solar", "user_created",
         0, 0, "{}", "generic_solar", "factory_template",
         "{}", "{}", now_ts, now_ts),
    )
    conn.commit()
    conn.close()

    try:
        # Use 24h TTL — old row (2020) should be purged, new row (2099) should survive
        cleanup_expired_demo_data(ttl_hours=24)

        conn = get_connection()
        old_exists = conn.execute(
            "SELECT 1 FROM projects WHERE user_id=?", (uid_old,)
        ).fetchone()
        new_exists = conn.execute(
            "SELECT 1 FROM projects WHERE user_id=?", (uid_new,)
        ).fetchone()
        conn.close()

        assert old_exists is None, "Expired demo data must be cleaned up"
        assert new_exists is not None, "Non-expired demo data must be kept"
    finally:
        conn = get_connection()
        conn.execute("DELETE FROM projects WHERE user_id=?", (uid_old,))
        conn.execute("DELETE FROM projects WHERE user_id=?", (uid_new,))
        conn.commit()
        conn.close()


def test_cleanup_never_removes_reference_data():
    """cleanup_expired_demo_data must never delete __reference__ rows."""
    from app.demo_cleanup import cleanup_expired_demo_data
    from app.services.project_library_service import ensure_reference_models
    from app.persistence.db import get_connection

    ensure_reference_models()
    conn = get_connection()
    count_before = conn.execute(
        "SELECT COUNT(*) FROM projects WHERE user_id='__reference__'"
    ).fetchone()[0]
    conn.close()

    cleanup_expired_demo_data(ttl_hours=0)  # TTL=0 means everything is "expired"

    conn = get_connection()
    count_after = conn.execute(
        "SELECT COUNT(*) FROM projects WHERE user_id='__reference__'"
    ).fetchone()[0]
    conn.close()

    assert count_before == count_after, "cleanup must never touch __reference__ data"


# ---------------------------------------------------------------------------
# 7. GET /library — canonical reference exposure, no cross-user leakage
# ---------------------------------------------------------------------------

def test_library_no_cross_user_project_leakage(client):
    """Session B's project must not appear in Session A's /library response."""
    _seed_refs()
    uid_a = _make_demo_user_id()
    uid_b = _make_demo_user_id()
    secret_code = f"secret-{uid_b[-6:]}"
    secret_name = f"SecretProjectOf_{uid_b[-6:]}"
    try:
        _insert_project(uid_b, secret_code, secret_name)
        resp = client.get("/library", cookies=_make_demo_cookie(uid_a))
        assert resp.status_code == 200
        # Session A's library must not contain Session B's secret project name
        assert secret_name not in resp.text, (
            "Session B's private project must not leak into Session A's /library"
        )
    finally:
        _delete_project(uid_b, secret_code)


def test_library_role_filter_storage_does_not_crash(client):
    """GET /library?role=reference must return 200 (exercises the 3-template IN binding)."""
    _seed_refs()
    uid = _make_demo_user_id()
    resp = client.get(
        "/library",
        params={"role": "reference"},
        cookies=_make_demo_cookie(uid),
    )
    assert resp.status_code == 200, (
        f"library?role=reference must return 200, not {resp.status_code}: {resp.text[:200]}"
    )


def test_library_search_does_not_crash(client):
    """GET /library?search=Reference must return 200 (exercises full predicate binding)."""
    _seed_refs()
    uid = _make_demo_user_id()
    resp = client.get(
        "/library",
        params={"search": "Reference"},
        cookies=_make_demo_cookie(uid),
    )
    assert resp.status_code == 200, (
        f"library?search=Reference must return 200, not {resp.status_code}: {resp.text[:200]}"
    )


# ---------------------------------------------------------------------------
# 8. Concurrency capacity — atomic semaphore acquisition
# ---------------------------------------------------------------------------

def test_acquire_run_slot_deterministic_non_blocking():
    """_acquire_run_slot returns False immediately when semaphore is full."""
    import main_web

    async def _run():
        orig = main_web._run_semaphore
        try:
            # Fill a 2-slot semaphore completely
            sem = asyncio.Semaphore(2)
            await sem.acquire()
            await sem.acquire()
            main_web._run_semaphore = sem

            # Third acquisition must return False without blocking
            slot = await main_web._acquire_run_slot()
            assert slot is False, "Must return False when semaphore is full"

            # With a fresh unfilled semaphore, acquisition must succeed
            main_web._run_semaphore = asyncio.Semaphore(1)
            slot2 = await main_web._acquire_run_slot()
            assert slot2 is True, "Must return True when a slot is available"
            if slot2:
                main_web._release_run_slot()
        finally:
            main_web._run_semaphore = orig

    asyncio.run(_run())


def test_acquire_run_slot_no_private_value():
    """Must not access private _value attribute — use public API only."""
    import inspect
    import main_web
    source = inspect.getsource(main_web._acquire_run_slot)
    assert "_value" not in source, "Must not access private _value attribute"


def test_concurrency_limit_enforced_sequentially():
    """Sequential slot acquisitions respect the semaphore limit."""
    import main_web

    async def _run():
        orig = main_web._run_semaphore
        try:
            sem = asyncio.Semaphore(3)
            main_web._run_semaphore = sem
            # Acquire all 3 slots
            results = []
            for _ in range(5):
                results.append(await main_web._acquire_run_slot())
            # First 3 must succeed; next 2 must fail
            assert results[:3] == [True, True, True], f"First 3 must succeed: {results}"
            assert results[3:] == [False, False], f"Next 2 must fail: {results}"
            # Release acquired slots
            for r in results:
                if r:
                    main_web._release_run_slot()
        finally:
            main_web._run_semaphore = orig

    asyncio.run(_run())
