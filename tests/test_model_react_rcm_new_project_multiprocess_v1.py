"""RC-M Lane A — New Project create across SEPARATE server processes (real uvicorn workers on one database file).

The fence must hold when the same request id reaches different OS processes at the same time, when the claiming process dies at
an exact point of the create, when a response is lost, across users, and for the demo budget.  Nothing is asserted from an
in-process lock.  Synthetic users; no engine Run is started.
"""
from __future__ import annotations

import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from app.persistence import db
from app.persistence.projects_repository import list_project_records

ROOT = Path(__file__).resolve().parent.parent
BASE = "/v2/model-react/new-project"
PURPOSE = "react-new-project-v1"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Server:
    def __init__(self, db_path: str, log: Path, crash_at: str = ""):
        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        env = {**os.environ, "FINCO_DB_PATH": db_path, "FINCO_MODEL_REACT_V1": "1", "RCM_CRASH_AT": crash_at,
               "PYTHONPATH": str(ROOT), "FINCO_MODEL_EXECUTION_MODE": "thread"}
        self._log = open(log, "wb")
        self.proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "tests.rcm_multiproc_app:app", "--host", "127.0.0.1",
                                      "--port", str(self.port), "--log-level", "warning"], cwd=ROOT, env=env,
                                     stdout=self._log, stderr=subprocess.STDOUT)

    def wait_ready(self, cookies: dict, timeout: float = 120.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited early with {self.proc.returncode}")
            try:
                if httpx.get(f"{self.url}{BASE}/options", cookies=cookies, timeout=5).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        raise RuntimeError("server did not become ready")

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self._log.close()


def _cookie(user_id: str, demo: bool = False) -> dict:
    from app.auth import COOKIE_NAME, DEMO_COOKIE_NAME, create_demo_session_token, create_session_token

    if demo:
        return {DEMO_COOKIE_NAME: create_demo_session_token(user_id)}
    return {COOKIE_NAME: create_session_token(user_id=user_id, username="admin")}


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    folder = tmp_path_factory.mktemp("rcm-multiproc")
    path = str(folder / "shared.db")
    mp = pytest.MonkeyPatch()
    mp.setattr(db, "DB_PATH", path)
    db.init_db()
    from app.services.project_library_service import ensure_reference_models

    ensure_reference_models()                      # the shared reference rows exist before any worker races on them
    servers: list[Server] = []

    def spawn(crash_at: str = "") -> Server:
        server = Server(path, folder / f"server-{len(servers)}.log", crash_at)
        servers.append(server)
        server.wait_ready(_cookie("rcm-mp-readiness"))
        return server

    healthy = [spawn(), spawn(), spawn()]
    try:
        yield type("Cluster", (), {"healthy": healthy, "spawn": staticmethod(spawn), "path": path})
    finally:
        for server in servers:
            server.stop()
        mp.undo()


def _options(server: Server, cookies: dict) -> dict:
    return httpx.get(f"{server.url}{BASE}/options", cookies=cookies, timeout=30).json()


def _body(opts: dict, **over) -> dict:
    data = {"request_id": opts["request_id"], "csrf_token": opts["csrf_token"], "name": "RCM multi-process",
            "technology": "solar", "country": "XA", "capacity_mw": 20.0, "acknowledge_preview": False}
    data.update(over)
    return data


def _post(server: Server, cookies: dict, body: dict):
    return httpx.post(f"{server.url}{BASE}/create", cookies=cookies, json=body, timeout=120)


def _projects(user_id: str) -> list:
    return list_project_records(user_id=user_id, include_archived=True)


def _claim_rows(user_id: str) -> list[tuple]:
    conn = sqlite3.connect(db.DB_PATH)
    try:
        return conn.execute("SELECT request_id, state, project_code FROM react_request_claims WHERE user_id = ?", (user_id,)).fetchall()
    except sqlite3.OperationalError as exc:          # the ledger table is created lazily by the first claim in any process
        assert "no such table" in str(exc)
        return []
    finally:
        conn.close()


def test_a_token_issued_by_one_process_is_valid_in_another_and_a_bad_one_is_refused_everywhere(cluster):
    uid, cookies = "rcm-mp-csrf", _cookie("rcm-mp-csrf")
    first, second, _third = cluster.healthy
    opts = _options(first, cookies)
    for tampered in (opts["csrf_token"][:-2] + "xx", "", "x" * 10):
        for server in cluster.healthy:
            response = _post(server, cookies, _body(opts, csrf_token=tampered))
            assert response.status_code == 403 and response.json()["code"] == "CSRF_INVALID"
    assert _projects(uid) == [] and _claim_rows(uid) == []                     # a refused token never claims, never writes
    other_session = _post(second, _cookie("rcm-mp-csrf-other"), _body(opts))      # token is bound to the issuing session
    assert other_session.status_code == 403
    ok = _post(second, cookies, _body(opts))                                      # issued by process 1, accepted by process 2
    assert ok.status_code == 200 and ok.json()["replayed"] is False and len(_projects(uid)) == 1


def test_simultaneous_posts_of_one_request_id_across_three_processes_create_exactly_one_project(cluster):
    uid, cookies = "rcm-mp-race", _cookie("rcm-mp-race")
    opts = _options(cluster.healthy[0], cookies)
    body = _body(opts)
    gate = threading.Barrier(12)

    def fire(index: int):
        gate.wait()
        return _post(cluster.healthy[index % 3], cookies, body)

    with ThreadPoolExecutor(max_workers=12) as pool:
        responses = list(pool.map(fire, range(12)))
    payloads = [r.json() for r in responses]
    created = [p for p in payloads if p.get("ok") and p.get("replayed") is False]
    assert len(created) == 1, payloads
    # every other request was fenced: a replay of the finished project, or an honest "unknown" while the winner was in flight
    for response, payload in zip(responses, payloads):
        if payload in created:
            continue
        assert (response.status_code == 200 and payload["replayed"] is True and payload["project"]["code"] == created[0]["project"]["code"]) \
            or (response.status_code == 503 and payload["code"] == "CREATE_IN_FLIGHT_OR_UNKNOWN"), payload
    assert len(_projects(uid)) == 1
    assert _claim_rows(uid) == [(opts["request_id"], "DONE", created[0]["project"]["code"])]
    for server in cluster.healthy:                                              # settled: every process now replays the same project
        again = _post(server, cookies, body).json()
        assert again["replayed"] is True and again["project"]["code"] == created[0]["project"]["code"]
    assert len(_projects(uid)) == 1


def test_replay_after_a_lost_response_returns_the_same_project_from_another_process(cluster):
    uid, cookies = "rcm-mp-lost", _cookie("rcm-mp-lost")
    first, second, third = cluster.healthy
    opts = _options(first, cookies)
    body = _body(opts)
    sent = _post(first, cookies, body)                  # the client "never sees" this response
    assert sent.status_code == 200
    status = httpx.get(f"{second.url}{BASE}/status", params={"request_id": opts["request_id"]}, cookies=cookies, timeout=30).json()
    assert status["created"] is True and status["conclusive"] is True and status["project"]["code"] == sent.json()["project"]["code"]
    replay = _post(third, cookies, _body(opts, name="Edited after the lost response", capacity_mw=77.0)).json()
    assert replay["replayed"] is True and replay["project"]["code"] == sent.json()["project"]["code"]
    assert len(_projects(uid)) == 1 and _projects(uid)[0].project_name == "RCM multi-process"


def test_a_process_that_dies_after_the_write_but_before_finishing_the_claim_never_allows_a_duplicate(cluster):
    uid, cookies = "rcm-mp-crash1", _cookie("rcm-mp-crash1")
    doomed = cluster.spawn("after_create_before_finish")
    opts = _options(doomed, cookies)
    body = _body(opts)
    with pytest.raises(httpx.HTTPError):
        _post(doomed, cookies, body)                    # the process died: no response at all
    doomed.proc.wait(timeout=30)
    assert doomed.proc.returncode == 137
    assert len(_projects(uid)) == 1 and _claim_rows(uid) == [(opts["request_id"], "CLAIMED", None)]
    for server in cluster.healthy:                      # replay storm against the surviving processes
        response = _post(server, cookies, body)
        assert response.status_code == 503 and response.json()["code"] == "CREATE_IN_FLIGHT_OR_UNKNOWN"
        status = httpx.get(f"{server.url}{BASE}/status", params={"request_id": opts["request_id"]}, cookies=cookies, timeout=30).json()
        assert status["created"] is False and status["conclusive"] is False and status["state"] == "IN_FLIGHT_OR_UNKNOWN"
    assert len(_projects(uid)) == 1 and _claim_rows(uid) == [(opts["request_id"], "CLAIMED", None)]      # never overwritten, never retried
    fresh = _options(cluster.healthy[0], cookies)                                # a NEW request id is a deliberate, separate create
    assert _post(cluster.healthy[1], cookies, _body(fresh)).json()["replayed"] is False and len(_projects(uid)) == 2


def test_a_process_that_dies_after_finishing_the_claim_but_before_the_stamp_still_replays_the_project(cluster):
    uid, cookies = "rcm-mp-crash2", _cookie("rcm-mp-crash2")
    doomed = cluster.spawn("after_finish_before_stamp")
    opts = _options(doomed, cookies)
    body = _body(opts)
    with pytest.raises(httpx.HTTPError):
        _post(doomed, cookies, body)
    doomed.proc.wait(timeout=30)
    assert doomed.proc.returncode == 137
    projects = _projects(uid)
    assert len(projects) == 1 and (projects[0].replay_metadata or {}).get("react_new_project") is None       # no stamp was written
    assert _claim_rows(uid) == [(opts["request_id"], "DONE", projects[0].project_code)]
    for server in cluster.healthy:
        replay = _post(server, cookies, body).json()
        assert replay["replayed"] is True and replay["project"]["code"] == projects[0].project_code
    assert len(_projects(uid)) == 1


def test_users_are_isolated_across_processes(cluster):
    users = [f"rcm-mp-iso-{n}" for n in range(3)]
    jobs = []
    for n, uid in enumerate(users):
        cookies = _cookie(uid)
        opts = _options(cluster.healthy[n], cookies)
        jobs.append((uid, cookies, _body(opts, name=f"Isolation {n}")))
    gate = threading.Barrier(len(jobs) * 2)

    def fire(job_index: int):
        uid, cookies, body = jobs[job_index // 2]
        gate.wait()
        return _post(cluster.healthy[(job_index + 1) % 3], cookies, body)

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(fire, range(6)))
    for uid, cookies, body in jobs:
        assert len(_projects(uid)) == 1
        assert [row[0] for row in _claim_rows(uid)] == [body["request_id"]]
        for other_uid, other_cookies, _ in jobs:
            if other_uid != uid:                         # another user's cookie can neither replay nor observe the request
                assert _post(cluster.healthy[0], other_cookies, body).status_code == 403
                status = httpx.get(f"{cluster.healthy[0].url}{BASE}/status", params={"request_id": body["request_id"]},
                                   cookies=other_cookies, timeout=30).json()
                assert status["created"] is False and "project" not in status
    assert sum(len(_projects(uid)) for uid in users) == 3


def test_the_demo_project_budget_holds_across_processes(cluster):
    from app.auth import DEMO_RATE_LIMITS

    limit = DEMO_RATE_LIMITS["project_create"][0]
    uid, cookies = "demo_rcmmpbudget", _cookie("demo_rcmmpbudget", demo=True)
    jobs = [_body(_options(cluster.healthy[n % 3], cookies), name=f"Budget {n}") for n in range(limit + 4)]
    gate = threading.Barrier(len(jobs))

    def fire(index: int):
        gate.wait()
        return _post(cluster.healthy[index % 3], cookies, jobs[index])

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        responses = list(pool.map(fire, range(len(jobs))))
    codes = sorted(r.status_code for r in responses)
    assert codes.count(200) == limit and codes.count(429) == len(jobs) - limit, codes
    assert len(_projects(uid)) == limit                 # each process's own in-memory limiter would have admitted more
    assert all(r.json()["retry_after"] > 0 for r in responses if r.status_code == 429)


def test_release_closed_unknown_and_extra_source_fields_create_nothing_in_any_process(cluster):
    uid, cookies = "rcm-mp-closed", _cookie("rcm-mp-closed")
    for server in cluster.healthy:
        opts = _options(server, cookies)
        for technology in ("storage", "unknown"):
            response = _post(server, cookies, _body(opts, technology=technology))
            assert response.status_code == 422 and response.json()["code"] == "VALIDATION_FAILED"
        # a protected reference (or any other project) can never be named as a source: the body forbids extra fields
        response = _post(server, cookies, {**_body(opts), "source_project_id": "any"})
        assert response.status_code == 400 and response.json()["code"] == "BODY_INVALID"
    assert _projects(uid) == [] and _claim_rows(uid) == []
