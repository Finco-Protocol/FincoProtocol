"""FINCO45C (C1-Q-08 / C3-E-08): the login and demo rate limits are ONE budget across worker processes.

Every multi-process test uses genuine independent OS processes (``subprocess``, not threads) that share one temp store,
released together at a barrier file so the requests really race at the boundary. Also: 429 + Retry-After contract over
HTTP, no 5xx at saturation, client-address spoofing via X-Forwarded-For, expiry/restart, retention, busy/unavailable
fail-closed with bounded latency, and no raw subject in the store.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app import auth
from app.persistence import rate_limit_store as store

ROOT = Path(__file__).resolve().parents[1]

_WORKER = r"""
import json, os, sys, time
sys.path.insert(0, os.getcwd())
from app.persistence import rate_limit_store as store
kind, subject, n, barrier = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
while not os.path.exists(barrier):
    time.sleep(0.001)
out = []
for _ in range(n):
    if kind == "demo":
        out.append(store.consume("demo", subject, "model_run", 20, 3600))
    else:
        out.append(store.login_reserve(subject, 5, 300))
print(json.dumps(out))
"""


@pytest.fixture
def shared_store(tmp_path, monkeypatch):
    path = tmp_path / "shared_rate_limit.sqlite"
    monkeypatch.setenv("FINCO_RATE_LIMIT_DB_PATH", str(path))
    return path


def _race(path, kind, subject, processes, per_process, tmp_path):
    barrier = tmp_path / f"go-{kind}-{subject}"
    env = dict(os.environ, FINCO_RATE_LIMIT_DB_PATH=str(path))
    procs = [subprocess.Popen([sys.executable, "-c", _WORKER, kind, subject, str(per_process), str(barrier)],
                              cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for _ in range(processes)]
    time.sleep(1.5)                                              # let every interpreter start and wait
    barrier.write_text("go")
    results, pids = [], set()
    for p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0, err
        results.extend(tuple(r) for r in json.loads(out.strip().splitlines()[-1]))
        pids.add(p.pid)
    assert len(pids) == processes
    return results


def test_demo_budget_is_total_across_independent_processes(shared_store, tmp_path):
    results = _race(shared_store, "demo", "demo_race_user", processes=4, per_process=10, tmp_path=tmp_path)
    allowed = [r for r in results if r[0]]
    denied = [r for r in results if not r[0]]
    assert len(allowed) == 20 and len(denied) == 20               # exactly the hourly budget, not 20 per process
    assert all(1 <= retry <= 3601 for _ok, retry in denied)


def test_login_verifications_are_bounded_across_independent_processes(shared_store, tmp_path):
    results = _race(shared_store, "login", "198.51.100.7", processes=4, per_process=3, tmp_path=tmp_path)
    assert sum(1 for ok, _ in results if ok) == 5                 # MAX_LOGIN_FAILURES verifications in total
    assert all(retry > 0 for ok, retry in results if not ok)


def test_buckets_are_per_principal_and_operation(shared_store):
    for _ in range(20):
        assert store.consume("demo", "demo_a", "model_run", 20, 3600)[0]
    assert store.consume("demo", "demo_a", "model_run", 20, 3600)[0] is False
    assert store.consume("demo", "demo_b", "model_run", 20, 3600) == (True, 0)      # other principal
    assert store.consume("demo", "demo_a", "export_generate", 10, 3600) == (True, 0)  # other operation


def test_window_expiry_and_restart_persistence(shared_store, monkeypatch):
    t0 = 1_000_000.0
    monkeypatch.setattr(store, "_clock", lambda: t0)
    for _ in range(5):
        assert store.consume("demo", "demo_exp", "project_create", 5, 3600)[0]
    ok, retry = store.consume("demo", "demo_exp", "project_create", 5, 3600)
    assert ok is False and retry == 3601
    store._ready.clear()                                          # a "restarted" worker reopens the same store
    assert store.consume("demo", "demo_exp", "project_create", 5, 3600)[0] is False
    monkeypatch.setattr(store, "_clock", lambda: t0 + 3600.5)    # window elapsed
    assert store.consume("demo", "demo_exp", "project_create", 5, 3600) == (True, 0)


def test_login_semantics_match_the_former_limiter(shared_store, monkeypatch):
    t0 = 2_000_000.0
    monkeypatch.setattr(store, "_clock", lambda: t0)
    for _ in range(auth.MAX_LOGIN_FAILURES):
        assert auth._check_rate_limit("203.0.113.50") == (True, 0)
        auth._record_failed_login("203.0.113.50")
    assert auth._check_rate_limit("203.0.113.50") == (False, auth.LOCKOUT_SECONDS)
    monkeypatch.setattr(store, "_clock", lambda: t0 + 100)
    assert auth._check_rate_limit("203.0.113.50") == (False, auth.LOCKOUT_SECONDS - 100)
    monkeypatch.setattr(store, "_clock", lambda: t0 + auth.LOCKOUT_SECONDS + 1)   # lock expired: fresh budget
    assert auth._check_rate_limit("203.0.113.50") == (True, 0)
    for _ in range(auth.MAX_LOGIN_FAILURES):
        assert store.login_reserve("203.0.113.50", auth.MAX_LOGIN_FAILURES, auth.LOCKOUT_SECONDS)[0]
    assert store.login_reserve("203.0.113.50", auth.MAX_LOGIN_FAILURES, auth.LOCKOUT_SECONDS) == (False, auth.LOCKOUT_SECONDS)
    monkeypatch.setattr(store, "_clock", lambda: t0 + 2 * 86400)                   # never a permanent lockout
    assert auth._check_rate_limit("203.0.113.50") == (True, 0)
    auth._clear_failed_logins("203.0.113.50")
    assert auth._check_rate_limit("203.0.113.50") == (True, 0)
    assert auth._check_rate_limit("203.0.113.51") == (True, 0)


def test_retention_is_bounded(shared_store, monkeypatch):
    t0 = 3_000_000.0
    monkeypatch.setattr(store, "_clock", lambda: t0)
    for i in range(50):
        store.consume("demo", f"demo_{i}", "model_run", 20, 3600)
        store.login_record_failure(f"192.0.2.{i}")
    monkeypatch.setattr(store, "_clock", lambda: t0 + store.LOGIN_RETENTION_SECONDS + 1)
    removed = store.purge(7200)
    assert removed == {"operation_events": 50, "login_attempts": 50}
    assert store.counts() == {"operation_events": 0, "login_attempts": 0}


def test_store_never_holds_raw_subjects(shared_store):
    store.login_record_failure("203.0.113.77")
    store.consume("demo", "demo_secret_identity", "model_run", 20, 3600)
    raw = Path(shared_store).read_bytes() + b"".join(p.read_bytes() for p in Path(shared_store).parent.glob("*-wal"))
    assert b"203.0.113.77" not in raw and b"demo_secret_identity" not in raw


def test_busy_store_fails_closed_within_bounded_latency(shared_store, monkeypatch):
    store.consume("demo", "warm", "model_run", 20, 3600)          # create schema
    monkeypatch.setattr(store, "BUSY_TIMEOUT_MS", 200)
    blocker = sqlite3.connect(str(shared_store), isolation_level=None)
    blocker.execute("BEGIN EXCLUSIVE")
    try:
        start = time.monotonic()
        result = store.consume("demo", "demo_busy", "model_run", 20, 3600)
        elapsed = time.monotonic() - start
        login = store.login_reserve("198.51.100.99", 5, 300)
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()
    assert result == (False, store.UNAVAILABLE_RETRY_AFTER) and login == (False, store.UNAVAILABLE_RETRY_AFTER)
    assert elapsed < 2.0
    assert store.consume("demo", "demo_busy", "model_run", 20, 3600) == (True, 0)   # recovers


def test_unavailable_store_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("FINCO_RATE_LIMIT_DB_PATH", str(tmp_path / "missing-dir" / "x.sqlite"))
    assert store.consume("demo", "demo_x", "model_run", 20, 3600) == (False, store.UNAVAILABLE_RETRY_AFTER)
    assert auth._check_rate_limit("203.0.113.1") == (False, store.UNAVAILABLE_RETRY_AFTER)
    auth._record_failed_login("203.0.113.1")                       # best effort, never raises


def test_admin_principal_is_never_demo_limited(shared_store):
    for _ in range(50):
        assert auth.check_demo_rate_limit("1", "model_run") == (True, 0)


def _login_page_token(client):
    page = client.get("/login", follow_redirects=False)
    return re.search(r'name="csrf_token"\s+value="([^"]+)"', page.text).group(1)


def test_http_login_lockout_returns_429_with_retry_after_and_ignores_spoofed_forwarded_for(shared_store, monkeypatch):
    from fastapi.testclient import TestClient

    import main_web
    monkeypatch.setattr(auth, "ADMIN_PASSWORD_HASH_ENV", None)
    monkeypatch.setattr(auth, "ADMIN_PASSWORD_PLAIN", "test-only-operator-pw-456")
    client = TestClient(main_web.app)
    token = _login_page_token(client)
    codes = []
    for i in range(auth.MAX_LOGIN_FAILURES + 3):
        r = client.post("/login", data={"username": "x", "password": "wrong", "csrf_token": token},
                        headers={"X-Forwarded-For": f"10.9.{i}.1"}, follow_redirects=False)   # rotating spoof
        codes.append(r.status_code)
        if r.status_code == 429:
            assert int(r.headers["Retry-After"]) > 0
    assert codes[:auth.MAX_LOGIN_FAILURES] == [401] * auth.MAX_LOGIN_FAILURES
    assert codes[auth.MAX_LOGIN_FAILURES:] == [429] * 3          # the spoofed header did not create fresh buckets
    assert all(c < 500 for c in codes)
    good = client.post("/login", data={"username": auth.ADMIN_USERNAME, "password": "test-only-operator-pw-456",
                                       "csrf_token": token}, follow_redirects=False)
    assert good.status_code == 429                                # locked out even with the right password
    bad_csrf = client.post("/login", data={"username": "x", "password": "y", "csrf_token": "forged"},
                           follow_redirects=False)
    assert bad_csrf.status_code == 429                            # lock is checked first, as before


def test_http_invalid_csrf_does_not_consume_login_budget(shared_store, monkeypatch):
    from fastapi.testclient import TestClient

    import main_web
    monkeypatch.setattr(auth, "ADMIN_PASSWORD_HASH_ENV", None)
    monkeypatch.setattr(auth, "ADMIN_PASSWORD_PLAIN", "test-only-operator-pw-789")
    client = TestClient(main_web.app)
    for _ in range(10):
        assert client.post("/login", data={"username": "x", "password": "y", "csrf_token": "forged"},
                           follow_redirects=False).status_code == 403
    token = _login_page_token(client)
    ok = client.post("/login", data={"username": auth.ADMIN_USERNAME, "password": "test-only-operator-pw-789",
                                     "csrf_token": token}, follow_redirects=False)
    assert ok.status_code == 302


def test_latency_overhead_is_small(shared_store):
    store.consume("demo", "warm", "model_run", 20, 3600)
    samples = []
    for i in range(200):
        start = time.perf_counter()
        store.consume("demo", f"lat_{i % 10}", "model_run", 10_000, 3600)
        samples.append(time.perf_counter() - start)
    samples.sort()
    p95 = samples[int(len(samples) * 0.95)]
    print(json.dumps({"rate_limit_consume_p50_ms": round(samples[100] * 1000, 3), "p95_ms": round(p95 * 1000, 3)}))
    assert p95 < 0.25                                             # generous bound for shared CI runners
