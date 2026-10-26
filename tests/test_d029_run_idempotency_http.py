"""D-029 canonical HTTP evidence: real route, real engine, real SQLite, real history.

Release stays CLOSED: these tests prove the implemented behaviour, they do not
activate the feature or stand in for owner approval.
"""
from __future__ import annotations

import threading
import uuid
from types import SimpleNamespace

import pytest

from tests.test_model_decision_workspace_v2 import env as _env, tokens  # noqa: F401  (fixture re-export)
from tests.test_model_credit_decision_v3_real_runs import history, last

USER = "decision-user"
env = _env


@pytest.fixture(autouse=True)
def _thread_executor(monkeypatch):
    monkeypatch.setenv("FINCO_MODEL_EXECUTION_MODE", "thread")
    monkeypatch.setenv("FINCO_NATIVE_V10_RUN", "off")
    monkeypatch.setenv("FINCO_NATIVE_V11_RUN", "off")


def run_form(e, record, intent=None, *, page=None):
    from app.workbook.financing_csrf import issue_token
    page = page or e.client.get("/v2/workbook", params={"project": record.project_code})
    req = SimpleNamespace(cookies=e.client.cookies, state=SimpleNamespace())
    data = {"project": record.project_code, **tokens(page.text),
            "csrf_token": issue_token(req, record.project_code, purpose="workbook-run-v1")}
    if intent is not None:
        data["run_intent_id"] = intent
    return data


def post(e, data, *, json=True):
    headers = {"Accept": "application/json"} if json else {"HX-Request": "true"}
    return e.client.post("/v2/workbook/run", headers=headers, data=dict(data), follow_redirects=False)


def count_engine(monkeypatch):
    import app.api.project_runner as pr
    original, calls, lock = pr.run_project, [], threading.Lock()

    def counted(*a, **k):
        with lock:
            calls.append(1)
        return original(*a, **k)
    monkeypatch.setattr(pr, "run_project", counted)
    return calls


def test_same_key_twice_commits_once_and_replays_original(env, monkeypatch):
    record = env.create("solar")
    calls = count_engine(monkeypatch)
    key = str(uuid.uuid4())
    data = run_form(env, record, key)
    first = post(env, data)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["outcome"] == "COMMITTED" and body["history_id"]
    second = post(env, data)
    assert second.status_code == 200
    replay = second.json()
    assert replay["outcome"] == "REPLAYED"
    assert replay["history_id"] == body["history_id"] and replay["runtime_snapshot_id"] == body["runtime_snapshot_id"]
    assert len(calls) == 1 and len(history(record)) == 1


def intents(record=None):
    from app.persistence.db import get_connection
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM model_run_intents ORDER BY created_at_ms").fetchall()]
    finally:
        conn.close()


def edit(e, record, raw, field="revenue.ppa.base_tariff"):
    from tests.model_mutation_csrf import post_valid_mutation
    page = e.client.get("/v2/workbook", params={"project": record.project_code})
    return post_valid_mutation(e.client, "/v2/workbook/update", headers={"HX-Request": "true"},
                               data={"project": record.project_code, "field_id": field, "value": raw, **tokens(page.text)})


def last_snapshot(record):
    from app.persistence.workspace_repository import get_workspace_state
    return get_workspace_state(USER, record.project_id).last_runtime_snapshot_id


def test_replay_after_edit_newer_run_never_overwrites_last_run(env, monkeypatch):
    record = env.create("solar")
    calls = count_engine(monkeypatch)
    key_a, key_b = str(uuid.uuid4()), str(uuid.uuid4())
    form_a = run_form(env, record, key_a)
    first = post(env, form_a).json()
    assert first["outcome"] == "COMMITTED"
    assert edit(env, record, "58").status_code in (200, 303)
    form_b = run_form(env, record, key_b)
    assert form_b["content_hash"] != form_a["content_hash"]
    second = post(env, form_b).json()
    assert second["outcome"] == "COMMITTED" and second["history_id"] != first["history_id"]
    assert len(calls) == 2
    last_before = last_snapshot(record)
    assert last_before == second["runtime_snapshot_id"]
    # Re-sending the ORIGINAL submission (original binding, a now-stale hash and a valid fresh CSRF token).
    stale = dict(form_a, csrf_token=run_form(env, record, key_a)["csrf_token"])
    replay = post(env, stale).json()
    assert replay["outcome"] == "REPLAYED"
    assert replay["history_id"] == first["history_id"] and replay["runtime_snapshot_id"] == first["runtime_snapshot_id"]
    assert len(calls) == 2 and len(history(record)) == 2
    assert last_snapshot(record) == last_before        # a replay never rewrites Last Run


def test_conflicting_binding_for_same_key_is_refused_without_running(env, monkeypatch):
    record = env.create("solar")
    calls = count_engine(monkeypatch)
    key = str(uuid.uuid4())
    form = run_form(env, record, key)
    assert post(env, form).json()["outcome"] == "COMMITTED"
    assert edit(env, record, "58").status_code in (200, 303)
    other = run_form(env, record, key)
    assert other["content_hash"] != form["content_hash"]
    response = post(env, other)
    assert response.status_code == 409 and response.json()["outcome"] == "CONFLICT"
    assert len(calls) == 1 and len(history(record)) == 1


def test_different_keys_keep_released_admission_and_each_intent_binds_its_own_history(env, monkeypatch):
    record = env.create("solar")
    count_engine(monkeypatch)
    keys = [str(uuid.uuid4()), str(uuid.uuid4())]
    results = [post(env, run_form(env, record, key)).json() for key in keys]
    committed = [r for r in results if r["outcome"] == "COMMITTED"]
    assert committed and all(r["outcome"] in ("COMMITTED", "FAILED") for r in results)
    rows = history(record)
    bound = {i["history_id"] for i in intents() if i["state"] == "COMMITTED"}
    assert bound == {r["history_id"] for r in committed} and len(rows) == len(committed)


def test_invalid_key_and_missing_key(env, monkeypatch):
    record = env.create("solar")
    calls = count_engine(monkeypatch)
    for bad in ("not-a-uuid", "../../etc/passwd", "A" * 300, str(uuid.uuid1())):
        response = post(env, run_form(env, record, bad))
        assert response.status_code == 422 and response.json()["outcome"] == "INVALID", bad
    assert not calls and not history(record) and not intents()
    # Missing key keeps the released, non-idempotent behaviour (owner-policy candidate).
    ok = post(env, run_form(env, record), json=False)
    assert ok.status_code in (200, 303) and len(history(record)) == 1 and not intents()


def test_security_gates_precede_the_ledger(env, monkeypatch):
    record = env.create("solar")
    calls = count_engine(monkeypatch)
    key = str(uuid.uuid4())
    form = run_form(env, record, key)
    # Missing / wrong-purpose CSRF: nothing reserved, nothing run.
    for csrf in ("", "forged"):
        response = post(env, dict(form, csrf_token=csrf))
        assert response.status_code == 403
    assert not calls and not intents() and not history(record)
    # A foreign project code is not reachable with an intent id either.
    response = post(env, dict(form, project="no-such-project"))
    assert response.status_code in (403, 404, 409) and not intents()


def test_intent_id_is_not_authorization_for_another_actor(env, monkeypatch):
    from app.auth import COOKIE_NAME, create_session_token
    record = env.create("solar")
    count_engine(monkeypatch)
    key = str(uuid.uuid4())
    form = run_form(env, record, key)
    assert post(env, form).json()["outcome"] == "COMMITTED"
    previous = env.client.cookies.get(COOKIE_NAME)
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id="someone-else", username="admin"))
    try:
        response = post(env, form)
        print(response.status_code, response.text[:200])
        assert response.status_code in (403, 404)       # ownership gate precedes the ledger
        assert "history_id" not in response.text
    finally:
        env.client.cookies.set(COOKIE_NAME, previous)
    assert len(history(record)) == 1


def test_protected_reference_is_refused_even_with_a_key(env, monkeypatch):
    record = env.create("solar")
    calls = count_engine(monkeypatch)
    from app.persistence.db import get_connection
    conn = get_connection()
    try:
        conn.execute("UPDATE projects SET is_protected=1, project_role='reference' WHERE project_id=?", (record.project_id,))
        conn.commit()
    finally:
        conn.close()
    response = post(env, run_form(env, record, str(uuid.uuid4())))
    assert response.status_code in (403, 409) and not calls and not intents()


# --- financial integrity: atomic commit, fencing, crash windows ------------------------------------------------------

def workspace(record):
    from app.persistence.workspace_repository import get_workspace_state
    return get_workspace_state(USER, record.project_id)


def intent_state(key):
    return next((i for i in intents() if i["run_intent_id"] == key), None)


@pytest.mark.parametrize("where", ["finalize", "history_append"])
def test_commit_is_one_transaction_a_fault_before_commit_rolls_back_everything(env, monkeypatch, where):
    import app.persistence.run_history_repository as hist
    import app.persistence.run_intent_repository as repo
    record = env.create("solar")
    calls = count_engine(monkeypatch)
    before = workspace(record)

    def boom(*a, **k):
        raise RuntimeError("injected fault inside the commit transaction")
    saved = (repo.finalize_cursor, hist.append_run_history_cursor)
    if where == "finalize":
        monkeypatch.setattr(repo, "finalize_cursor", boom)
    else:
        monkeypatch.setattr(hist, "append_run_history_cursor", boom)
    key = str(uuid.uuid4())
    failed = post(env, run_form(env, record, key))
    assert failed.status_code == 409 and failed.json()["outcome"] == "FAILED"
    after = workspace(record)
    assert not history(record)                                           # no history row
    assert after.last_runtime_snapshot_id == before.last_runtime_snapshot_id   # Last Run not promoted
    assert after.dirty == before.dirty and after.last_runtime_summary == before.last_runtime_summary
    assert intent_state(key)["state"] == "FAILED" and intent_state(key)["history_id"] is None
    monkeypatch.setattr(repo, "finalize_cursor", saved[0])
    monkeypatch.setattr(hist, "append_run_history_cursor", saved[1])
    # Terminal: the same key never re-runs; a deliberate new key can.
    again = post(env, run_form(env, record, key))
    assert again.status_code == 409 and again.json()["outcome"] == "FAILED"
    new_key = str(uuid.uuid4())
    ok = post(env, run_form(env, record, new_key))
    assert ok.json()["outcome"] == "COMMITTED" and len(history(record)) == 1


def test_crash_after_commit_before_response_replays_the_committed_run(env, monkeypatch):
    import app.services.run_intent_service as service
    record = env.create("solar")
    calls = count_engine(monkeypatch)
    key = str(uuid.uuid4())
    form = run_form(env, record, key)
    original = service.committed_decision

    def crash(*a, **k):
        raise RuntimeError("process died after COMMIT, before the response")
    monkeypatch.setattr(service, "committed_decision", crash)
    with pytest.raises(RuntimeError):
        post(env, form)
    monkeypatch.setattr(service, "committed_decision", original)
    assert len(history(record)) == 1 and intent_state(key)["state"] == "COMMITTED"
    snapshot = last_snapshot(record)
    replay = post(env, dict(form, csrf_token=run_form(env, record, key)["csrf_token"])).json()
    assert replay["outcome"] == "REPLAYED" and replay["runtime_snapshot_id"] == snapshot
    assert len(calls) == 1 and len(history(record)) == 1


def test_lost_response_then_retry_with_same_key_is_replayed(env, monkeypatch):
    import httpx
    record = env.create("solar")
    calls = count_engine(monkeypatch)
    key = str(uuid.uuid4())
    form = run_form(env, record, key)
    transport = env.client._transport
    original = transport.handle_request

    def lose(request):
        response = original(request)
        if request.method == "POST" and request.url.path == "/v2/workbook/run":
            raise httpx.ReadError("simulated response loss after server completion", request=request)
        return response
    monkeypatch.setattr(transport, "handle_request", lose)
    with pytest.raises(httpx.ReadError):
        post(env, form)
    monkeypatch.setattr(transport, "handle_request", original)
    replay = post(env, form).json()
    assert replay["outcome"] == "REPLAYED" and len(calls) == 1 and len(history(record)) == 1
    assert replay["runtime_snapshot_id"] == last_snapshot(record)


def test_restart_between_attempts_replays_from_the_durable_ledger(env, monkeypatch):
    from app.persistence import db
    from app.runtime.model_execution import reset_model_executor_for_tests
    record = env.create("solar")
    calls = count_engine(monkeypatch)
    key = str(uuid.uuid4())
    form = run_form(env, record, key)
    first = post(env, form).json()
    reset_model_executor_for_tests()
    db._reset_schema_cache_for_tests()           # a fresh process starts with no schema cache
    replay = post(env, form).json()
    assert replay["outcome"] == "REPLAYED" and replay["history_id"] == first["history_id"] and len(calls) == 1


def test_failed_engine_attempt_is_terminal_and_a_new_key_may_run(env, monkeypatch):
    import app.api.project_runner as pr
    record = env.create("solar")
    original = pr.run_project
    monkeypatch.setattr(pr, "run_project", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("engine boom")))
    key = str(uuid.uuid4())
    form = run_form(env, record, key)
    failed = post(env, form)
    assert failed.status_code == 409 and failed.json()["outcome"] == "FAILED"
    assert intent_state(key)["state"] == "FAILED" and not history(record)
    monkeypatch.setattr(pr, "run_project", original)
    again = post(env, form)
    assert again.json()["outcome"] == "FAILED"                 # same key: terminal, no re-execution
    assert not history(record)
    assert post(env, run_form(env, record, str(uuid.uuid4()))).json()["outcome"] == "COMMITTED"


def test_in_progress_second_request_does_not_start_a_second_engine(env, monkeypatch):
    import app.api.project_runner as pr
    from concurrent.futures import ThreadPoolExecutor
    record = env.create("solar")
    original, entered, release, calls = pr.run_project, threading.Event(), threading.Event(), []

    def gated(*a, **k):
        calls.append(1)
        entered.set()
        assert release.wait(20)
        return original(*a, **k)
    monkeypatch.setattr(pr, "run_project", gated)
    key = str(uuid.uuid4())
    form = run_form(env, record, key)
    with ThreadPoolExecutor(1) as pool:
        running = pool.submit(post, env, form)
        assert entered.wait(15)
        second = post(env, dict(form, csrf_token=run_form(env, record, key)["csrf_token"]))
        assert second.status_code == 409 and second.json()["outcome"] == "IN_PROGRESS"
        release.set()
        assert running.result(30).json()["outcome"] == "COMMITTED"
    assert len(calls) == 1 and len(history(record)) == 1


def test_stale_owner_is_fenced_and_commits_nothing(env, monkeypatch):
    import app.api.project_runner as pr
    import app.persistence.run_intent_repository as repo
    from app.persistence.db import get_connection
    from concurrent.futures import ThreadPoolExecutor
    record = env.create("solar")
    original, entered, release = pr.run_project, threading.Event(), threading.Event()

    def gated(*a, **k):
        entered.set()
        assert release.wait(20)
        return original(*a, **k)
    monkeypatch.setattr(pr, "run_project", gated)
    key = str(uuid.uuid4())
    form = run_form(env, record, key)
    before = workspace(record)
    with ThreadPoolExecutor(1) as pool:
        running = pool.submit(post, env, form)
        assert entered.wait(15)
        row = intent_state(key)
        conn = get_connection()
        try:   # lease expiry + explicit fenced takeover by a second owner
            conn.execute("UPDATE model_run_intents SET lease_until_ms=0 WHERE run_intent_id=?", (key,))
            conn.commit()
        finally:
            conn.close()
        submitted = repo.SubmittedIntent(USER, record.project_id, key, form["workbook_version"], form["content_hash"])
        takeover = repo.recover(submitted, row["request_fingerprint"], lease_ms=60_000)
        assert takeover.generation == 2
        release.set()
        stale = running.result(30)
    assert stale.status_code == 409 and stale.json()["outcome"] == "FAILED"
    assert not history(record) and last_snapshot(record) == before.last_runtime_snapshot_id
    current = intent_state(key)
    assert current["state"] == "RESERVED" and current["generation"] == 2    # the new owner's claim is untouched


def test_expired_active_intent_fails_closed_without_running(env, monkeypatch):
    import app.persistence.run_intent_repository as repo
    from app.persistence.db import get_connection
    record = env.create("solar")
    calls = count_engine(monkeypatch)
    key = str(uuid.uuid4())
    form = run_form(env, record, key)
    reservation, acquired = repo.reserve(
        repo.SubmittedIntent(USER, record.project_id, key, form["workbook_version"], form["content_hash"]),
        "a" * 64, lease_ms=60_000)
    assert acquired
    conn = get_connection()
    try:
        conn.execute("UPDATE model_run_intents SET lease_until_ms=0 WHERE run_intent_id=?", (key,))
        conn.commit()
    finally:
        conn.close()
    response = post(env, form)
    assert response.status_code == 409 and response.json()["outcome"] == "EXPIRED"
    assert not calls and not history(record)


# --- ledger/history integrity at the HTTP boundary -------------------------------------------------------------------

def test_missing_or_malformed_history_is_typed_and_never_recalculates(env, monkeypatch):
    import app.services.run_intent_service as service
    record = env.create("solar")
    calls = count_engine(monkeypatch)
    key = str(uuid.uuid4())
    form = run_form(env, record, key)
    assert post(env, form).json()["outcome"] == "COMMITTED"
    for broken in (lambda *a: None, lambda *a: (_ for _ in ()).throw(ValueError("malformed history row"))):
        monkeypatch.setattr(service, "get_run_history_entry", broken)
        response = post(env, form)
        assert response.status_code == 409 and response.json()["outcome"] == "HISTORY_UNAVAILABLE"
    assert len(calls) == 1 and intent_state(key)["state"] == "COMMITTED"


def test_foreign_history_id_is_never_returned(env, monkeypatch):
    import app.persistence.run_intent_repository as repo
    from app.persistence.db import get_connection
    mine = env.create("solar")
    other = env.create("wind")
    count_engine(monkeypatch)
    assert post(env, run_form(env, other), json=False).status_code in (200, 303)   # keyless: no ledger binding
    foreign = history(other)[0].history_id
    key = str(uuid.uuid4())
    form = run_form(env, mine, key)
    submitted = repo.SubmittedIntent(USER, mine.project_id, key, form["workbook_version"], form["content_hash"])
    conn = get_connection()
    try:   # a corrupted ledger row pointing at a history row of ANOTHER project
        conn.execute("INSERT INTO model_run_intents VALUES (?,?,?,?,?,?,?,?, 'COMMITTED',1,?,?,?,?,?,NULL)",
                     (uuid.uuid4().hex, USER, mine.project_id, key, submitted.binding, "b" * 64,
                      form["workbook_version"], form["content_hash"], uuid.uuid4().hex, 0, 0, 0, foreign))
        conn.commit()
    finally:
        conn.close()
    response = post(env, form)
    assert response.status_code == 409 and response.json()["outcome"] == "HISTORY_UNAVAILABLE"
    assert foreign not in response.text and not history(mine)


def test_schema_corruption_fails_closed_before_any_run(env, monkeypatch):
    from app.persistence.db import get_connection
    record = env.create("solar")
    calls = count_engine(monkeypatch)
    form = run_form(env, record, str(uuid.uuid4()))
    conn = get_connection()
    try:
        conn.execute("DROP TRIGGER model_run_intents_no_delete")
        conn.commit()
    finally:
        conn.close()
    from app.persistence.run_intent_repository import RunIntentError
    with pytest.raises(RunIntentError, match="SCHEMA_INVALID"):
        post(env, form)
    assert not calls        # fail closed: the engine never started; the damaged database is not read further


# --- real OS processes and real workers ------------------------------------------------------------------------------

def _process_client(base, db_path, counter, cookie, form, barrier, queue, mode):
    """Spawned OS process: one client of the same intent (module-level so 'spawn' can import it)."""
    import os
    os.environ.update(FINCO_D029_DB=db_path, FINCO_D029_COUNTER=counter, FINCO_MODEL_EXECUTION_MODE="thread",
                      FINCO_NATIVE_V10_RUN="off", FINCO_NATIVE_V11_RUN="off")
    from app.auth import COOKIE_NAME
    try:
        if mode == "http":
            import httpx
            client = httpx.Client(base_url=base, timeout=120, cookies={COOKIE_NAME: cookie})
        else:   # in-process app instance in THIS process, sharing only the SQLite file
            from fastapi.testclient import TestClient
            from tests import d029_worker_app
            client = TestClient(d029_worker_app.app, cookies={COOKIE_NAME: cookie})
        barrier.wait(60)
        response = client.post("/v2/workbook/run", data=form, headers={"Accept": "application/json"},
                               follow_redirects=False)
        queue.put((os.getpid(), response.status_code, response.json()))
    except BaseException as exc:   # noqa: BLE001 - surfaced to the parent
        queue.put((os.getpid(), -1, {"error": repr(exc)}))


def _spawn_clients(env, record, tmp_path, base, mode, n=5):
    import multiprocessing as mp
    from app.auth import COOKIE_NAME
    from app.persistence import db
    key = str(uuid.uuid4())
    form = run_form(env, record, key)
    counter = str(tmp_path / ("engine-%s.log" % mode))
    open(counter, "w").close()
    ctx = mp.get_context("spawn")
    barrier, queue = ctx.Barrier(n), ctx.Queue()
    procs = [ctx.Process(target=_process_client, args=(base, db.DB_PATH, counter, env.client.cookies.get(COOKIE_NAME),
                                                       form, barrier, queue, mode)) for _ in range(n)]
    for proc in procs:
        proc.start()
    results = [queue.get(timeout=240) for _ in procs]
    for proc in procs:
        proc.join(timeout=60)
    engine_runs = [line for line in open(counter, encoding="utf-8").read().splitlines() if line]
    return key, results, engine_runs


def _assert_single_winner(record, key, results, engine_runs):
    assert all(r[1] != -1 for r in results), results
    outcomes = sorted(r[2]["outcome"] for r in results)
    assert outcomes.count("COMMITTED") == 1, outcomes
    assert set(outcomes) <= {"COMMITTED", "IN_PROGRESS", "REPLAYED"}, outcomes
    assert len(engine_runs) == 1                         # ONE engine execution across all processes
    rows = history(record)
    assert len(rows) == 1
    assert intent_state(key)["history_id"] == rows[0].history_id and intent_state(key)["state"] == "COMMITTED"
    winner = next(r[2] for r in results if r[2]["outcome"] == "COMMITTED")
    assert winner["history_id"] == rows[0].history_id
    for r in results:   # every replay names the one original history row
        if r[2]["outcome"] == "REPLAYED":
            assert r[2]["history_id"] == rows[0].history_id


def test_five_concurrent_os_processes_one_intent_one_engine_run(env, tmp_path):
    record = env.create("solar")
    key, results, engine_runs = _spawn_clients(env, record, tmp_path, None, "process")
    _assert_single_winner(record, key, results, engine_runs)
    assert len({r[0] for r in results}) == 5             # five distinct OS processes


def test_multi_worker_server_five_clients_one_intent_one_engine_run(env, tmp_path):
    import os
    import socket
    import subprocess
    import sys
    import time
    import httpx
    from app.persistence import db
    record = env.create("solar")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    counter = str(tmp_path / "engine-http.log")
    open(counter, "w").close()
    server_env = dict(os.environ, FINCO_D029_DB=db.DB_PATH, FINCO_D029_COUNTER=counter,
                      FINCO_MODEL_EXECUTION_MODE="thread", FINCO_NATIVE_V10_RUN="off", FINCO_NATIVE_V11_RUN="off")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tests.d029_worker_app:app", "--workers", "2", "--port", str(port),
         "--host", "127.0.0.1", "--log-level", "warning"], env=server_env, cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    try:
        base = "http://127.0.0.1:%d" % port
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                httpx.get(base + "/openapi.json", timeout=2)
                break
            except httpx.HTTPError:
                time.sleep(.5)
        else:
            pytest.fail("worker server did not start")
        key, results, engine_runs = _spawn_clients(env, record, tmp_path, base, "http")   # engine log is the servers'
        _assert_single_winner(record, key, results, engine_runs)
    finally:
        server.terminate()
        try:
            server.wait(30)
        except subprocess.TimeoutExpired:
            server.kill()


# --- financial parity: the intent lifecycle must not change a single persisted number --------------------------------

ECONOMIC = ("runtime_summary", "financial_statements", "debt_schedule", "tax_schedule", "distribution_schedule",
            "sponsor_schedule", "integrity_evidence", "composite_hash", "engine_version", "workbook_version",
            "active_scenario_id", "last_runtime_scenario_id")


# The ONLY values that legitimately differ between two Runs of identical inputs are the per-run
# snapshot identity and the one digest that covers it.  Everything else must be bit-identical.
RUN_IDENTITY_PATHS = (("acquisition_source_candidate_v1", "binding", "snapshot_id"),
                      ("acquisition_source_candidate_v1", "digest"),
                      ("financing_evidence", "run_binding", "snapshot_id"))


def economic_payload(entry):
    import copy
    payload = copy.deepcopy({f: entry[f] for f in ECONOMIC})
    for path in RUN_IDENTITY_PATHS:
        node = payload["runtime_summary"]
        for part in path[:-1]:
            node = node.get(part) if isinstance(node, dict) else None
        if isinstance(node, dict):
            node.pop(path[-1], None)
    return payload


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_keyed_run_is_bit_identical_to_the_released_keyless_run(env, kind):
    import json
    record = env.create(kind)
    assert post(env, run_form(env, record), json=False).status_code in (200, 303)         # released path
    key = str(uuid.uuid4())
    keyed = post(env, run_form(env, record, key))
    assert keyed.json()["outcome"] == "COMMITTED", keyed.text
    rows = sorted(history(record), key=lambda r: r.ran_at)
    assert len(rows) == 2
    plain, with_key = (r.to_dict() for r in rows)
    a, b = economic_payload(plain), economic_payload(with_key)
    for field in ECONOMIC:
        assert json.dumps(a[field], sort_keys=True) == json.dumps(b[field], sort_keys=True), field
    assert plain["runtime_snapshot_id"] != with_key["runtime_snapshot_id"]
