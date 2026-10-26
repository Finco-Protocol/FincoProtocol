"""Isolated ledger/fence evidence, NOT canonical HTTP acceptance evidence."""
from dataclasses import replace
import multiprocessing as mp
import os
import sqlite3
import uuid

import pytest

from app.persistence import db
from app.persistence import run_intent_repository as ri
from app.persistence.run_history_repository import (
    append_run_history_cursor, prepare_run_history_payload,
)


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "ledger.sqlite"))
    conn = db.get_connection()
    ri.install_schema(conn)
    conn.execute("""INSERT INTO projects
                 (project_id,user_id,project_code,project_name,source_project_template,
                  governance_state_json,last_run_summary_json,created_at,updated_at)
                 VALUES ('immutable-project','actor','fixture-project','D029 persistence fixture',
                         'synthetic','{}','{}','2026-10-26','2026-10-26')""")
    conn.close()
    return db.DB_PATH


def intent(**changes):
    values = dict(actor_id="actor", project_id="immutable-project",
                  run_intent_id=str(uuid.uuid4()), workbook_version="v1", content_hash="a" * 64)
    values.update(changes)
    return ri.SubmittedIntent(**values)


def fingerprint(request):
    return ri.frozen_fingerprint(request, scenario_id=None,
                                 effective_input_identity={"canonical_input": "frozen"},
                                 line_override_identity={"capex": [], "opex": [], "overrides": {}},
                                 execution_contract="test-canonical-v1")


def claim(request):
    record, acquired = ri.reserve(request, fingerprint(request), lease_ms=60_000)
    assert acquired
    return ri.start(record)


def append(cursor, request):
    # The REAL history payload validator and cursor writer, with clearly
    # synthetic persistence-only output. No financial calculation is claimed.
    payload = prepare_run_history_payload(
        user_id=request.actor_id, project_id=request.project_id, project_code="fixture-project",
        runtime_snapshot_id=uuid.uuid4().hex, runtime_origin="d029-ledger-test",
        ran_at="2026-10-26T00:00:00+00:00", workbook_version=request.workbook_version,
        composite_hash=request.content_hash, runtime_summary={}, financial_statements={},
        debt_schedule={}, tax_schedule={}, distribution_schedule={}, sponsor_schedule={},
    )
    return append_run_history_cursor(cursor, payload)


def commit(request, owner, *, fault=None):
    conn = db.get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        ri.require_owner_cursor(cur, owner)
        history_id = append(cur, request)
        if fault == "before-finalize":
            raise RuntimeError("injected before-finalize crash")
        ri.finalize_cursor(cur, owner, history_id)
        if fault == "before-commit":
            raise RuntimeError("injected before-commit crash")
        conn.commit()
        return history_id
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def expire(owner):
    conn = db.get_connection()
    try:
        conn.execute("UPDATE model_run_intents SET lease_until_ms=0 WHERE reservation_id=?",
                     (owner.reservation_id,))
    finally:
        conn.close()


@pytest.mark.parametrize("value", [None, 42, "", "x" * 100,
                                 "123e4567-e89b-12d3-a456-426614174000",
                                 "123E4567-E89B-42D3-A456-426614174000", "../project"])
def test_reject_invalid_keys(value):
    with pytest.raises(ri.RunIntentError, match="RUN_INTENT_INVALID"):
        ri.validate_key(value)


def test_fingerprint_stability_and_authority():
    request = intent()
    assert ri.canonical_digest({"b": 2, "a": 1}) == ri.canonical_digest({"a": 1, "b": 2})
    original = fingerprint(request)
    for field in ("actor_id", "project_id", "workbook_version", "content_hash"):
        assert fingerprint(replace(request, **{field: "other"})) != original
    assert ri.frozen_fingerprint(request, scenario_id="different", effective_input_identity={"canonical_input": "frozen"},
                                 line_override_identity={}, execution_contract="test-canonical-v1") != original
    with pytest.raises(ValueError):
        ri.canonical_digest({"nan": float("nan")})


def test_reserve_retry_conflict_and_scoping(ledger):
    request = intent()
    owner = claim(request)
    seen, acquired = ri.reserve(request, fingerprint(request), lease_ms=60_000)
    assert not acquired and seen == owner
    with pytest.raises(ri.RunIntentError, match="CONFLICT"):
        ri.lookup(replace(request, content_hash="b" * 64))
    with pytest.raises(ri.RunIntentError, match="CONFLICT"):
        ri.reserve(request, "b" * 64, lease_ms=60_000)
    for scope in (replace(request, actor_id="another"), replace(request, project_id="another")):
        assert ri.lookup(scope) is None
    distinct = replace(request, run_intent_id=str(uuid.uuid4()))
    assert ri.reserve(distinct, fingerprint(distinct), lease_ms=60_000)[1]


def test_schema_restart_unique_and_immutable(ledger):
    request = intent()
    owner = claim(request)
    history_id = commit(request, owner)
    conn = db.get_connection()
    try:
        ri.install_schema(conn)
        for statement in (
            "UPDATE model_run_intents SET history_id='different'",
            "UPDATE model_run_intents SET request_fingerprint='different'",
            "UPDATE model_run_intents SET state='RESERVED', history_id=NULL",
            "DELETE FROM model_run_intents",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(statement)
        # Direct SQL bypass of the service STILL meets database uniqueness.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO model_run_intents SELECT * FROM model_run_intents")
    finally:
        conn.close()
    replay = ri.lookup(request)
    assert replay.state == "COMMITTED" and replay.history_id == history_id
    # Fresh connection/process-local schema cache reset doesn't lose identity.
    db._SCHEMA_READY.clear()
    assert ri.lookup(request) == replay


@pytest.mark.parametrize("fault", ["before-finalize", "before-commit"])
def test_fault_rolls_back_history_and_finalization(ledger, fault):
    request = intent()
    owner = claim(request)
    with pytest.raises(RuntimeError, match="injected"):
        commit(request, owner, fault=fault)
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM model_run_history").fetchone()[0] == 0
    finally:
        conn.close()
    assert ri.lookup(request).state == "RUNNING"
    assert commit(request, owner) == ri.lookup(request).history_id


def test_expired_live_worker_cannot_commit_after_takeover(ledger):
    request = intent()
    a = claim(request)
    with pytest.raises(ri.RunIntentError, match="NOT_RECOVERABLE"):
        ri.recover(request, fingerprint(request), lease_ms=60_000)
    expire(a)
    b = ri.recover(request, fingerprint(request), lease_ms=60_000)
    b = ri.start(b)
    assert b.generation == a.generation + 1 and b.owner_nonce != a.owner_nonce
    with pytest.raises(ri.RunIntentError, match="OWNERSHIP_LOST"):
        commit(request, a)
    original = commit(request, b)
    with pytest.raises(ri.RunIntentError, match="OWNERSHIP_LOST"):
        commit(request, a)
    assert ri.lookup(request).history_id == original
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM model_run_history").fetchone()[0] == 1
    finally:
        conn.close()


def test_expired_owner_without_takeover_also_cannot_commit(ledger):
    request = intent()
    owner = claim(request)
    expire(owner)
    with pytest.raises(ri.RunIntentError, match="OWNERSHIP_LOST"):
        commit(request, owner)


def test_start_is_not_a_second_execution_permit(ledger):
    request = intent()
    owner = claim(request)
    with pytest.raises(ri.RunIntentError, match="ALREADY_RUNNING"):
        ri.start(owner)
    assert ri.lookup(request).state == "RUNNING"


def test_migration_refusal_rolls_back_new_objects(ledger):
    conn = db.get_connection()
    try:
        # Preexisting incompatible table: migration must neither adopt it nor
        # leave half-installed triggers behind after refusing its schema.
        definition = conn.execute("SELECT sql FROM sqlite_master WHERE name='model_run_intents'").fetchone()[0]
        conn.execute("DROP TABLE model_run_intents")
        conn.execute(definition.replace("UNIQUE (actor_id, project_id, run_intent_id),", ""))
        with pytest.raises(ri.RunIntentError, match="SCHEMA_INVALID"):
            ri.install_schema(conn)
        assert not conn.in_transaction
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'model_run_intents_%'").fetchone()[0] == 0
    finally:
        conn.close()


def test_finalization_rejects_unrelated_history_and_requires_transaction(ledger):
    request = intent()
    owner = claim(request)
    conn = db.get_connection()
    try:
        with pytest.raises(ri.RunIntentError, match="TRANSACTION_REQUIRED"):
            ri.finalize_cursor(conn.cursor(), owner, "absent")
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        unrelated = append(cur, replace(request, content_hash="b" * 64))
        with pytest.raises(ri.RunIntentError, match="HISTORY_MISMATCH"):
            ri.finalize_cursor(cur, owner, unrelated)
        conn.rollback()
    finally:
        conn.close()
    assert ri.lookup(request).state == "RUNNING"


@pytest.mark.parametrize("code", ["ADMISSION_REFUSED", "ENGINE_FAILED", "ENGINE_TIMEOUT",
                                "FINANCIAL_REFUSED", "FINAL_CAS_CONFLICT", "CANCELLED"])
def test_terminal_failure_keeps_same_key_closed_new_intent_available(ledger, code):
    request = intent()
    owner = claim(request)
    ri.fail(owner, code)
    failed = ri.lookup(request)
    assert failed.state == "FAILED" and failed.error_code == code and failed.history_id is None
    assert not ri.reserve(request, fingerprint(request), lease_ms=60_000)[1]
    with pytest.raises(ri.RunIntentError, match="NOT_RECOVERABLE"):
        ri.recover(request, fingerprint(request), lease_ms=60_000)
    assert ri.reserve(replace(request, run_intent_id=str(uuid.uuid4())), fingerprint(request), lease_ms=60_000)[1]


def _worker(path, values, barrier, queue):
    """Independent spawned OS process, independent connections and module state."""
    db.DB_PATH = path
    try:
        request = ri.SubmittedIntent(**values)
        barrier.wait(timeout=30)
        owner, acquired = ri.reserve(request, fingerprint(request), lease_ms=60_000)
        history_id = commit(request, ri.start(owner)) if acquired else None
        queue.put(("ok", acquired, history_id))
    except BaseException as exc:
        queue.put((type(exc).__name__, str(exc)))


def test_five_independent_processes_one_claim_one_history(ledger):
    request = intent()
    context = mp.get_context("spawn")
    barrier = context.Barrier(5)
    queue = context.Queue()
    workers = [context.Process(target=_worker, args=(ledger, request.__dict__, barrier, queue)) for _ in range(5)]
    try:
        for worker in workers:
            worker.start()
        results = [queue.get(timeout=45) for _ in workers]
        for worker in workers:
            worker.join(timeout=10)
            assert worker.exitcode == 0
        assert all(result[0] == "ok" for result in results), results
        assert sum(result[1] for result in results) == 1, results
        assert ri.lookup(request).history_id == next(result[2] for result in results if result[1])
        conn = db.get_connection()
        try:
            assert conn.execute("SELECT COUNT(*) FROM model_run_history").fetchone()[0] == 1
        finally:
            conn.close()
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=10)
        queue.close()
        queue.join_thread()


def test_reconcile_original_history_after_newer_intent(ledger):
    from app.services.run_intent_service import RELEASE_POLICY, reconcile
    old_request = intent()
    assert not RELEASE_POLICY.enabled
    assert reconcile(old_request).kind == "NEW"
    first_owner = claim(old_request)
    assert reconcile(old_request).kind == "IN_PROGRESS"
    first = commit(old_request, first_owner)
    later_request = intent(content_hash="b" * 64)
    later = commit(later_request, claim(later_request))
    replay = reconcile(old_request)
    assert replay.kind == "REPLAYED" and replay.history_id == first and first != later
    assert reconcile(later_request).history_id == later
    assert reconcile(replace(old_request, actor_id="other")).kind == "NEW"
    assert reconcile(replace(old_request, project_id="other")).kind == "NEW"
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM model_run_history").fetchone()[0] == 2
    finally:
        conn.close()


def test_reconcile_missing_history_never_reopens_committed_intent(ledger, monkeypatch):
    from app.services import run_intent_service as service
    request = intent()
    commit(request, claim(request))
    monkeypatch.setattr(service, "get_run_history_entry", lambda *args: None)
    assert service.reconcile(request).kind == "HISTORY_UNAVAILABLE"
    assert ri.lookup(request).state == "COMMITTED"


@pytest.mark.parametrize("damage", ["unique", "fence"])
def test_missing_database_guards_fail_closed(ledger, damage):
    conn = db.get_connection()
    try:
        if damage == "unique":
            definition = conn.execute("SELECT sql FROM sqlite_master WHERE name='model_run_intents'").fetchone()[0]
            weakened = definition.replace("UNIQUE (actor_id, project_id, run_intent_id),", "")
            assert weakened != definition
            conn.execute("DROP TABLE model_run_intents")
            conn.execute(weakened)
        else:
            conn.execute("DROP TRIGGER model_run_intents_identity_immutable")
        with pytest.raises(ri.RunIntentError, match="SCHEMA_INVALID"):
            ri.lookup(intent())
        with pytest.raises(ri.RunIntentError, match="SCHEMA_INVALID"):
            ri.reserve(intent(), "a" * 64, lease_ms=60_000)
    finally:
        conn.close()


def test_sqlite_busy_is_not_acquired_or_committed(ledger, monkeypatch):
    original = ri.get_connection

    blocked = original()
    blocked.execute("PRAGMA busy_timeout=25")
    holder = db.get_connection()
    try:
        holder.execute("BEGIN IMMEDIATE")
        request = intent()
        with monkeypatch.context() as patch:
            patch.setattr(ri, "get_connection", lambda: blocked)
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                ri.reserve(request, fingerprint(request), lease_ms=60_000)
    finally:
        holder.rollback()
        holder.close()
    assert ri.lookup(request) is None
    assert ri.reserve(request, fingerprint(request), lease_ms=60_000)[1]


def _crashing_worker(path, values, boundary, pipe):
    db.DB_PATH = path
    request = ri.SubmittedIntent(**values)
    owner = claim(request)
    history_id = None
    if boundary == "precommit":
        conn = db.get_connection()
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        ri.require_owner_cursor(cur, owner)
        history_id = append(cur, request)
        ri.finalize_cursor(cur, owner, history_id)
        # Real abrupt process exit with uncommitted history/ledger writes.
    elif boundary == "postcommit":
        history_id = commit(request, owner)
    pipe.send(history_id)
    pipe.close()
    os._exit(0)


@pytest.mark.parametrize("boundary", ["reservation", "precommit", "postcommit"])
def test_abrupt_process_exit_and_restart(ledger, boundary):
    request = intent()
    context = mp.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    worker = context.Process(target=_crashing_worker, args=(ledger, request.__dict__, boundary, sender))
    try:
        worker.start()
        sender.close()
        assert receiver.poll(30), "worker did not reach crash boundary"
        possible_history = receiver.recv()
        worker.join(timeout=10)
        assert worker.exitcode == 0
        stored = ri.lookup(request)
        if boundary == "postcommit":
            assert stored.state == "COMMITTED" and stored.history_id == possible_history
        else:
            assert stored.state == "RUNNING" and stored.history_id is None
            conn = db.get_connection()
            try:
                assert conn.execute("SELECT COUNT(*) FROM model_run_history").fetchone()[0] == 0
            finally:
                conn.close()
            expire(stored)
            recovered = ri.start(ri.recover(request, fingerprint(request), lease_ms=60_000))
            assert commit(request, recovered) == ri.lookup(request).history_id
    finally:
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=10)
        receiver.close()
        sender.close()


def _late_worker(path, values, pipe):
    db.DB_PATH = path
    request = ri.SubmittedIntent(**values)
    owner = claim(request)
    pipe.send(owner)
    if pipe.poll(30) and pipe.recv() == "resume":
        try:
            commit(request, owner)
        except ri.RunIntentError as exc:
            pipe.send(exc.code)
        else:
            pipe.send("UNEXPECTED_COMMIT")
    pipe.close()


@pytest.mark.parametrize("new_owner_commits_first", [False, True])
def test_live_stalled_process_fenced_before_and_after_new_owner_commit(ledger, new_owner_commits_first):
    request = intent()
    context = mp.get_context("spawn")
    parent, child = context.Pipe()
    worker = context.Process(target=_late_worker, args=(ledger, request.__dict__, child))
    try:
        worker.start()
        child.close()
        assert parent.poll(30)
        a = parent.recv()
        assert worker.is_alive(), "A must still be alive when B takes over"
        expire(a)  # Controlled lease-clock fault; generation fence is real SQL.
        b = ri.start(ri.recover(request, fingerprint(request), lease_ms=60_000))
        expected = commit(request, b) if new_owner_commits_first else None
        parent.send("resume")
        assert parent.poll(30)
        assert parent.recv() == "RUN_INTENT_OWNERSHIP_LOST"
        worker.join(timeout=10)
        assert worker.exitcode == 0
        if expected is None:
            expected = commit(request, b)
        assert ri.lookup(request).history_id == expected
        conn = db.get_connection()
        try:
            assert conn.execute("SELECT COUNT(*) FROM model_run_history").fetchone()[0] == 1
        finally:
            conn.close()
    finally:
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=10)
        parent.close()
        child.close()
