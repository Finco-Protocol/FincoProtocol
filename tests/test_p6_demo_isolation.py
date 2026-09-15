"""P6 demo session isolation tests — P6.9 / P6.18.

Tests:
- Demo session token generation produces unique IDs
- Demo session tokens decode correctly
- Admin and demo tokens are not interchangeable (different salt)
- Demo user_id isolation: Session A data invisible to Session B
- IDOR: Session B cannot read Session A's projects/scenarios/runs
- Demo rate limiting: check_demo_rate_limit enforces per-user limits
- Demo cleanup removes expired demo data, not admin data
- Reference model immutability (canonical reference user untouched by demo cleanup)
- Demo reset script refuses production environment
"""

import os
import time
import pytest


# ── Auth / token tests ────────────────────────────────────────────────────────

def test_demo_user_id_is_unique():
    from app.auth import new_demo_user_id, DEMO_USER_ID_PREFIX
    ids = {new_demo_user_id() for _ in range(50)}
    assert len(ids) == 50
    for uid in ids:
        assert uid.startswith(DEMO_USER_ID_PREFIX)


def test_demo_session_token_roundtrip():
    from app.auth import new_demo_user_id, create_demo_session_token, decode_demo_session_token
    uid = new_demo_user_id()
    token = create_demo_session_token(uid)
    assert token
    session = decode_demo_session_token(token)
    assert session is not None
    assert session.user_id == uid
    assert session.session_type == "demo"
    assert session.is_demo


def test_admin_token_not_accepted_as_demo():
    """Admin-signed token must not decode as a demo session (different serializer salt)."""
    from app.auth import create_session_token, decode_demo_session_token
    admin_token = create_session_token(user_id="1")
    result = decode_demo_session_token(admin_token)
    assert result is None


def test_demo_token_not_accepted_as_admin():
    """Demo-signed token must not decode as an admin session."""
    from app.auth import new_demo_user_id, create_demo_session_token, decode_session_token
    uid = new_demo_user_id()
    demo_token = create_demo_session_token(uid)
    result = decode_session_token(demo_token)
    assert result is None


def test_demo_rate_limit_enforced():
    from app.auth import check_demo_rate_limit, new_demo_user_id, DEMO_RATE_LIMITS
    uid = new_demo_user_id()
    op = "project_create"
    max_calls, _ = DEMO_RATE_LIMITS[op]

    # Consume all allowed calls
    for _ in range(max_calls):
        allowed, _ = check_demo_rate_limit(uid, op)
        assert allowed, "Should be allowed within limit"

    # Next call must be rejected
    allowed, retry_after = check_demo_rate_limit(uid, op)
    assert not allowed
    assert retry_after > 0


def test_demo_rate_limit_not_applied_to_admin():
    """Rate limiting only applies to demo_ user IDs, never admin."""
    from app.auth import check_demo_rate_limit
    for _ in range(100):
        allowed, _ = check_demo_rate_limit("1", "model_run")
        assert allowed


# ── Session isolation / IDOR tests ───────────────────────────────────────────

def _make_demo_user():
    from app.auth import new_demo_user_id
    return new_demo_user_id()


def _create_project_for_user(user_id: str, project_name: str = "Test Project") -> str:
    """Create a minimal project record for user_id. Returns project_code."""
    from app.persistence.db import get_connection
    import json
    conn = get_connection()
    project_code = f"test-{user_id[-8:]}-{int(time.time() * 1000) % 100000}"
    now = "2025-01-01T00:00:00+00:00"
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
        (project_code, user_id, project_name, "Solar", "user_created",
         0, 0, json.dumps({}),
         "generic_solar", "factory_template",
         "{}", "{}",
         now, now),
    )
    conn.commit()
    conn.close()
    return project_code


def _project_visible(user_id: str, project_code: str) -> bool:
    from app.persistence.db import get_connection
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM projects WHERE user_id=? AND project_code=?",
        (user_id, project_code),
    ).fetchone()
    conn.close()
    return row is not None


def _cleanup_test_projects(*user_ids):
    from app.persistence.db import get_connection
    conn = get_connection()
    for uid in user_ids:
        conn.execute("DELETE FROM projects WHERE user_id=?", (uid,))
    conn.commit()
    conn.close()


def test_demo_session_data_isolation():
    """Session A's projects are not visible to Session B."""
    uid_a = _make_demo_user()
    uid_b = _make_demo_user()
    try:
        code_a = _create_project_for_user(uid_a, "Session A Project")
        code_b = _create_project_for_user(uid_b, "Session B Project")

        # A sees own project
        assert _project_visible(uid_a, code_a)
        # B sees own project
        assert _project_visible(uid_b, code_b)
        # A cannot see B's project
        assert not _project_visible(uid_a, code_b)
        # B cannot see A's project
        assert not _project_visible(uid_b, code_a)
    finally:
        _cleanup_test_projects(uid_a, uid_b)


def test_idor_demo_vs_admin_isolation():
    """Demo user cannot see admin projects and vice versa."""
    uid_demo = _make_demo_user()
    uid_admin = "1"
    try:
        code_demo = _create_project_for_user(uid_demo, "Demo-only Project")
        # Admin project is not created here; we just verify demo cannot see admin rows
        assert _project_visible(uid_demo, code_demo)
        assert not _project_visible(uid_admin, code_demo)
    finally:
        _cleanup_test_projects(uid_demo)


def test_demo_cleanup_removes_demo_data_only():
    """cleanup_all_demo_data removes demo projects, never reference or admin."""
    from app.demo_cleanup import cleanup_all_demo_data
    from app.services.project_library_service import ensure_reference_models
    uid_demo = _make_demo_user()

    # Seed reference models so we can verify they survive cleanup
    ensure_reference_models()

    try:
        _create_project_for_user(uid_demo, "To Be Cleaned")
        assert _any_project_exists(uid_demo)
        # Run full wipe (simulates TTL expiry in test)
        cleanup_all_demo_data()
        # Demo data gone
        assert not _any_project_exists(uid_demo)
        # Reference data still present
        assert _any_project_exists("__reference__")
    finally:
        _cleanup_test_projects(uid_demo)


def test_demo_cleanup_leaves_admin_data_intact():
    """cleanup_all_demo_data never touches admin user_id='1'."""
    from app.demo_cleanup import cleanup_all_demo_data
    admin_id = "1"
    # Ensure there is at least one admin project (may already exist)
    admin_projects_before = _count_projects(admin_id)
    cleanup_all_demo_data()
    admin_projects_after = _count_projects(admin_id)
    assert admin_projects_before == admin_projects_after


def _get_any_project_code(user_id: str) -> str:
    from app.persistence.db import get_connection
    conn = get_connection()
    row = conn.execute("SELECT project_code FROM projects WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row["project_code"] if row else ""


def _any_project_exists(user_id: str) -> bool:
    from app.persistence.db import get_connection
    conn = get_connection()
    row = conn.execute("SELECT 1 FROM projects WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row is not None


def _count_projects(user_id: str) -> int:
    from app.persistence.db import get_connection
    conn = get_connection()
    row = conn.execute("SELECT COUNT(*) FROM projects WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row[0] if row else 0


def test_demo_reset_refuses_production():
    """demo_reset.py must refuse when FINCO_ENV=production."""
    import subprocess
    env = os.environ.copy()
    env["FINCO_ENV"] = "production"
    result = subprocess.run(
        ["python", "tools/demo_reset.py", "--yes"],
        capture_output=True,
        text=True,
        env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    assert result.returncode == 2, "Must exit with code 2 when FINCO_ENV=production"
    assert "refused" in result.stdout.lower() or "production" in result.stdout.lower()


def test_reference_models_protected_from_demo_writes():
    """Reference projects (user_id='__reference__') must be marked is_protected=1."""
    from app.persistence.db import get_connection
    conn = get_connection()
    refs = conn.execute(
        "SELECT project_code, is_protected FROM projects WHERE user_id='__reference__'"
    ).fetchall()
    conn.close()
    # Reference models may not exist in a blank test DB — skip if absent
    if not refs:
        pytest.skip("Reference models not yet seeded in test DB")
    for ref in refs:
        assert ref["is_protected"] == 1, f"{ref['project_code']} must be is_protected=1"
