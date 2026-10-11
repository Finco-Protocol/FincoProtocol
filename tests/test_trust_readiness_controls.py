"""WF-10A: each control and known gap in the trust registry is proven (or pinned) here.

The registry cites these test names as evidence, so a rename here fails the registry tests.
Controls assert behaviour that exists today. ``test_known_gap_*`` tests pin a deviation that
is documented as a gap: when someone closes the gap the test fails, which forces the
registry (and the published pages) to be updated in the same change.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def client():
    import main_web

    return TestClient(main_web.app)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    from app.persistence import backup_restore, db

    path = str(tmp_path / "trust.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(backup_restore, "DB_PATH", path)
    monkeypatch.setattr(backup_restore, "BACKUP_DIR", str(tmp_path / "backups"))
    db.get_connection().close()
    return path


def _insert_project(path: str, user_id: str, code: str, updated_at: str) -> str:
    pid = f"p_{user_id}_{code}"
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO projects (project_id, user_id, project_code, project_name, "
        "source_project_template, governance_state_json, last_run_summary_json, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (pid, user_id, code, code, "t", "{}", "{}", updated_at, updated_at),
    )
    conn.commit()
    conn.close()
    return pid


# ── Access control ──────────────────────────────────────────────────────────

def test_operator_password_is_bcrypt_hashed():
    from app import auth

    hashed = auth._hash_password("a-test-password")
    assert hashed.startswith(b"$2") and b"$12$" in hashed[:8]
    assert auth._verify_password("a-test-password", hashed)
    assert not auth._verify_password("another-password", hashed)


def test_session_cookie_flags_are_hardened():
    from app import auth

    for cookie in (auth.make_session_cookie("t"), auth.make_demo_cookie("t")):
        assert cookie["httponly"] is True
        assert cookie["samesite"].lower() in {"lax", "strict"}
        assert cookie["path"] == "/"
        assert "secure" in cookie and cookie["max_age"] > 0


def test_login_rate_limit_locks_out_after_repeated_failures(monkeypatch):
    from app import auth

    monkeypatch.setattr(auth, "_rate_limit_store", {})
    for _ in range(auth.MAX_LOGIN_FAILURES):
        auth._record_failed_login("203.0.113.9")
    allowed, wait = auth._check_rate_limit("203.0.113.9")
    assert allowed is False and wait > 0
    assert auth._check_rate_limit("203.0.113.10") == (True, 0)


def test_login_requires_valid_csrf_token(client, monkeypatch):
    from app import auth

    monkeypatch.setattr(auth, "_rate_limit_store", {})
    bad = client.post("/login", data={"username": "x", "password": "y", "csrf_token": "forged"},
                      follow_redirects=False)
    assert bad.status_code == 403
    page = client.get("/login", follow_redirects=False)
    token = re.search(r'name="csrf_token"\s+value="([^"]+)"', page.text)
    assert token, "login form must carry a CSRF token"
    wrong_password = client.post(
        "/login", data={"username": "x", "password": "y", "csrf_token": token.group(1)},
        follow_redirects=False)
    assert wrong_password.status_code == 401  # token accepted, credentials rejected


def test_rate_limit_counters_are_in_memory_and_stale_ones_are_purged(monkeypatch):
    import time

    from app import auth

    monkeypatch.setattr(auth, "_demo_op_store", {
        "demo_stale": {"model_run": [time.time() - 3 * 3600]},
        "demo_fresh": {"model_run": [time.time()]},
    })
    auth.purge_expired_demo_rate_entries()
    assert set(auth._demo_op_store) == {"demo_fresh"}
    assert isinstance(auth._demo_op_store, dict)  # process memory, not the database


# ── Tenant isolation ────────────────────────────────────────────────────────

def test_project_resolution_never_crosses_tenants(temp_db):
    from app.persistence.projects_repository import resolve_accessible_project

    now = datetime.now(timezone.utc).isoformat()
    _insert_project(temp_db, "demo_alice", "alice_only", now)
    own, owner = resolve_accessible_project("demo_alice", "alice_only")
    assert own is not None and owner == "demo_alice"
    other, _ = resolve_accessible_project("demo_bob", "alice_only")
    assert other is None


def test_every_persisted_table_is_tenant_keyed_and_classified(temp_db):
    from app.trust_readiness.registry import DATA_STORES

    conn = sqlite3.connect(temp_db)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    columns = {t: {r[1] for r in conn.execute(f"PRAGMA table_info({t})")} for t in tables}
    conn.close()
    classified = [t for d in DATA_STORES for t in d.tables]
    assert sorted(classified) == sorted(set(classified)), "a table is listed in two entries"
    assert set(classified) == tables, f"unclassified or stale tables: {set(classified) ^ tables}"
    for table, cols in columns.items():
        assert "user_id" in cols or "project_id" in cols, f"{table} has no tenant key"


# ── Security controls ───────────────────────────────────────────────────────

def test_security_headers_are_present_on_every_response(client):
    from app.middleware.security_headers import SecurityHeadersMiddleware

    for path in ("/trust", "/login", "/does-not-exist-xyz"):
        h = client.get(path, follow_redirects=False).headers
        assert h["x-frame-options"] == "DENY", path
        assert h["x-content-type-options"] == "nosniff", path
        assert "frame-ancestors 'none'" in h["content-security-policy"], path
        assert h["referrer-policy"] == "same-origin", path
    # Known gap pinned here: the policy still allows inline scripts and styles.
    assert "'unsafe-inline'" in SecurityHeadersMiddleware.CSP


def test_request_log_contains_no_cookie_or_body(client, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="finco.requests"):
        client.get("/trust/security", headers={"cookie": "finco_demo=SECRET-COOKIE-VALUE"})
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "path=/trust/security" in text and "status=200" in text
    assert "SECRET-COOKIE-VALUE" not in text


def test_templates_load_no_external_resources():
    files = list((ROOT / "app" / "templates" / "trust").glob("*.html")) + [ROOT / "static" / "trust_readiness.css"]
    assert files
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"""(?:src|href|url\()\s*=?\s*["']?(?:https?:)?//""", text), f.name


def test_model_import_never_writes_uploads_to_disk():
    src = (ROOT / "app" / "model_import" / "intake.py").read_text(encoding="utf-8")
    for needle in ("open(", ".write(", "tempfile", "NamedTemporaryFile", "extractall(", "shutil"):
        assert needle not in src, needle


def test_sqlite_backup_roundtrip_and_prune(temp_db, tmp_path):
    from app.persistence import backup_restore as br

    meta = br.create_sqlite_backup()
    ok, _ = br.validate_sqlite_backup(meta.backup_path)
    assert ok
    backups = Path(br.get_backup_dir())
    manual = next(backups.glob("finco_runs_*.db"))
    for i in range(12):
        f = backups / f"auto_finco_runs_{i:02d}.db"
        f.write_bytes(manual.read_bytes())
        os.utime(f, (1_000_000 + i, 1_000_000 + i))
    assert br.prune_auto_backups(10) == 2
    assert len(list(backups.glob("auto_finco_runs_*.db"))) == 10
    assert manual.exists(), "manual backups are never pruned"


# ── Known gaps (pinned) ─────────────────────────────────────────────────────

def test_known_gap_run_history_survives_demo_ttl_cleanup(temp_db):
    from app.demo_cleanup import _TABLES_WITH_USER_ID, cleanup_expired_demo_data

    old = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
    pid = _insert_project(temp_db, "demo_expired", "old_project", old)
    conn = sqlite3.connect(temp_db)
    conn.execute(
        "INSERT INTO model_run_history (history_id, user_id, project_id, project_code, "
        "runtime_snapshot_id, ran_at, runtime_summary_json, financial_statements_json, "
        "debt_schedule_json, tax_schedule_json, distribution_schedule_json, sponsor_schedule_json, "
        "created_at) VALUES ('h1','demo_expired',?,?,?,?,'{}','{}','{}','{}','{}','{}',?)",
        (pid, "old_project", "s1", old, old),
    )
    conn.commit()
    conn.close()

    assert "model_run_history" not in _TABLES_WITH_USER_ID
    cleanup_expired_demo_data(ttl_hours=24)

    conn = sqlite3.connect(temp_db)
    assert conn.execute("SELECT COUNT(*) FROM projects WHERE project_id=?", (pid,)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM model_run_history").fetchone()[0] == 1
    conn.close()


def test_known_gap_no_product_route_deletes_user_data(client):
    import main_web

    for route in main_web.app.routes:
        methods = getattr(route, "methods", None) or set()
        path = route.path
        if path.startswith("/yield"):
            continue  # Yield is outside the FINCO Model pack
        assert "DELETE" not in methods, path
        assert not re.search(r"/(delete|erase|purge|forget)(/|$)", path), path
    source = (ROOT / "main_web.py").read_text(encoding="utf-8")
    assert len(re.findall(r"\bdelete_run\b", source)) == 1, "delete_run is imported but must have no caller"


def test_known_gap_readyz_discloses_server_paths(client, monkeypatch, tmp_path):
    monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "secret-location.db"))
    r = client.get("/readyz")
    assert r.status_code in (200, 503)
    assert "secret-location.db" in r.text


def test_known_gap_state_changing_posts_have_no_csrf_token():
    users = set()
    for path in list(ROOT.joinpath("app").rglob("*.py")) + [ROOT / "main_web.py"]:
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("app/trust_readiness/"):
            continue
        if re.search(r"(?<!def )validate_csrf_token\(", path.read_text(encoding="utf-8", errors="ignore")):
            users.add(rel)
    # Login, the model-import steps, the Inputs grid validate/save routes and one crypto action.
    # Nothing else validates a token.
    assert users == {"main_web.py", "app/v2/import_router.py", "app/v2/grid_router.py", "app/crypto_ui.py"}


def test_other_public_pages_still_provision_demo_session(client):
    fresh = TestClient(client.app)
    assert "finco_demo" in (fresh.get("/roadmap").headers.get("set-cookie") or "")
    assert fresh.get("/trust", headers={"cookie": ""}).headers.get("set-cookie") is None


def test_known_gap_sessions_are_stateless_and_not_revocable():
    src = (ROOT / "app" / "auth.py").read_text(encoding="utf-8")
    assert "Server-side session data (no DB, no Redis)" in src
    assert not re.search(r"revoke|revocation|session_store|blocklist", src, re.IGNORECASE)
