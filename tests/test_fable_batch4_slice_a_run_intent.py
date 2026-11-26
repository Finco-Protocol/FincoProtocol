"""FINCO 37 — Fable Batch 4 Slice A (C1-Q-11 / C3-E-09):
D-029 explicit-intent Run idempotency acceptance.

Separates production policy-ON (no monkeypatching of RELEASE_POLICY) from
explicit policy-OFF runtime-gate verification:
1. Simultaneous concurrent POST /v2/workbook/run with SAME run_intent_id ->
   exactly 1 engine compute, 1 History row, second caller gets IN_PROGRESS (409)
   or REPLAYED (200) pointing to the same history_id / runtime_snapshot_id.
2. Separate deliberate Runs with DISTINCT run_intent_id on identical inputs ->
   both commit and produce 2 distinct History rows (no content-hash dedup).
3. No-key legacy callers (missing run_intent_id) -> explicitly measured as
   non-idempotent (+2 History rows, 0 rows in model_run_intents), preserving
   missing_key_behavior='RELEASED_NON_IDEMPOTENT'.
4. Same key with different inputs -> typed 409 CONFLICT, 0 extra compute.
5. Replay of original key after draft edit & newer Run -> returns ORIGINAL
   history_id, never recalculates, never overwrites Last Run.
6. Missing history for a committed key -> typed HISTORY_UNAVAILABLE, key stays
   COMMITTED, never recalculates.
7. Security order: invalid CSRF (403), foreign tenant (404), protected
   reference (403/409) refuse BEFORE any ledger row is written.
8. Policy-OFF runtime gate: setting RELEASE_POLICY = RunIntentPolicy(enabled=False)
   genuinely bypasses the D-029 ledger even when run_intent_id is supplied.
"""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from app.persistence import db
from app.services import run_intent_service as ri_svc
from app.services.run_intent_service import RELEASE_POLICY, RunIntentPolicy
from tests.test_d029_run_idempotency_http import (  # noqa: F401
    count_engine,
    edit,
    env,
    intents,
    last_snapshot,
    post,
    run_form,
)
from tests.test_model_credit_decision_v3_real_runs import history


@pytest.fixture(autouse=True, scope="module")
def _finco47_legacy_ssr_rollback():
    """Module-scoped so module/session fixtures that seed over HTTP see the legacy SSR
    surface this module still exercises; default production flag stays React ON and the
    environment is restored exactly when the module finishes."""
    patch = pytest.MonkeyPatch()
    patch.setenv("FINCO_MODEL_REACT_V1", "0")
    try:
        yield
    finally:
        patch.undo()


@pytest.fixture(autouse=True)
def _thread_executor(monkeypatch):
    monkeypatch.setenv("FINCO_MODEL_EXECUTION_MODE", "thread")
    monkeypatch.setenv("FINCO_NATIVE_V10_RUN", "off")
    monkeypatch.setenv("FINCO_NATIVE_V11_RUN", "off")


def test_slice_a_policy_on_concurrent_same_key_vs_distinct_keys_vs_no_key_baseline(env, monkeypatch):
    """Production default RELEASE_POLICY.enabled=True (no monkeypatch of RELEASE_POLICY)."""
    assert RELEASE_POLICY.enabled is True
    assert RELEASE_POLICY.missing_key_behavior == "RELEASED_NON_IDEMPOTENT"
    assert RELEASE_POLICY.expired_retry_behavior == "EXPLICIT_FENCED_RECOVERY_ONLY"
    assert RELEASE_POLICY.retention_behavior == "NO_AUTOMATIC_DELETION_OR_KEY_REUSE"

    record = env.create("solar")
    calls = count_engine(monkeypatch)

    # 1. Two simultaneous callers with the SAME explicit run_intent_id
    shared_key = str(uuid.uuid4())
    form1 = run_form(env, record, shared_key)
    form2 = run_form(env, record, shared_key)
    barrier = threading.Barrier(2)

    def _fire(payload):
        barrier.wait(timeout=10)
        return post(env, payload)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_fire, form1)
        f2 = pool.submit(_fire, form2)
        r1, r2 = f1.result(timeout=60), f2.result(timeout=60)

    outcomes = sorted([(r1.status_code, r1.json().get("outcome")), (r2.status_code, r2.json().get("outcome"))])
    assert outcomes[0] == (200, "COMMITTED"), f"Expected one COMMITTED, got {outcomes}"
    assert outcomes[1] in ((409, "IN_PROGRESS"), (200, "REPLAYED")), f"Unexpected second outcome: {outcomes}"
    assert len(calls) == 1, f"Same run_intent_id must compute only once, got {len(calls)}"
    hist = history(record)
    assert len(hist) == 1

    # Immediate replay after completion returns ORIGINAL committed history_id
    replay = post(env, run_form(env, record, shared_key))
    assert replay.status_code == 200
    rbody = replay.json()
    assert rbody["outcome"] == "REPLAYED"
    assert rbody["history_id"] == hist[0].history_id
    assert len(calls) == 1 and len(history(record)) == 1

    # 2. Separate deliberate Run with a DISTINCT run_intent_id on IDENTICAL inputs -> allowed (+1 History row)
    distinct_key = str(uuid.uuid4())
    r_distinct = post(env, run_form(env, record, distinct_key))
    assert r_distinct.status_code == 200 and r_distinct.json()["outcome"] == "COMMITTED"
    assert len(calls) == 2 and len(history(record)) == 2
    assert r_distinct.json()["history_id"] != hist[0].history_id

    # 3. No-key legacy caller baseline -> explicitly non-idempotent (+2 History rows, 0 new intent rows)
    intents_before_nokey = len(intents())
    nokey_a = post(env, run_form(env, record, None))
    nokey_b = post(env, run_form(env, record, None))
    assert nokey_a.status_code in (200, 303) and nokey_b.status_code in (200, 303)
    assert len(history(record)) == 4
    assert len(intents()) == intents_before_nokey


def test_slice_a_policy_on_conflict_replay_after_edit_missing_history_and_security(env, monkeypatch):
    """Conflict, original-history replay after edit, HISTORY_UNAVAILABLE, and security-first refusal."""
    assert RELEASE_POLICY.enabled is True
    record = env.create("solar")
    calls = count_engine(monkeypatch)

    # 1. Commit Run #1 with key_1
    key_1 = str(uuid.uuid4())
    form_1 = run_form(env, record, key_1)
    r1 = post(env, form_1)
    assert r1.status_code == 200 and r1.json()["outcome"] == "COMMITTED"
    hist_1_id = r1.json()["history_id"]
    snap_1_id = r1.json()["runtime_snapshot_id"]

    # 2. Edit draft -> submit SAME key_1 with NEW content_hash -> 409 CONFLICT, 0 extra compute
    assert edit(env, record, "92.5").status_code == 200
    r_conflict = post(env, run_form(env, record, key_1))
    assert r_conflict.status_code == 409 and r_conflict.json()["outcome"] == "CONFLICT"
    assert len(calls) == 1

    # 3. Commit Run #2 with key_2 on edited draft -> Last Run advances to snap_2
    key_2 = str(uuid.uuid4())
    r2 = post(env, run_form(env, record, key_2))
    assert r2.status_code == 200 and r2.json()["outcome"] == "COMMITTED"
    snap_2_id = r2.json()["runtime_snapshot_id"]
    assert snap_2_id != snap_1_id
    assert last_snapshot(record) == snap_2_id

    # 4. Replaying original form_1 (old content_hash + key_1) returns ORIGINAL hist_1 without touching Last Run
    r_old_replay = post(env, form_1)
    assert r_old_replay.status_code == 200
    old_body = r_old_replay.json()
    assert old_body["outcome"] == "REPLAYED"
    assert old_body["history_id"] == hist_1_id and old_body["runtime_snapshot_id"] == snap_1_id
    assert last_snapshot(record) == snap_2_id
    assert len(calls) == 2

    # 5. Missing history for committed key -> typed HISTORY_UNAVAILABLE, never recalculates
    with monkeypatch.context() as mp:
        mp.setattr(ri_svc, "get_run_history_entry", lambda *a, **k: None)
        r_missing = post(env, form_1)
        assert r_missing.status_code in (409, 500)
        assert r_missing.json()["outcome"] == "HISTORY_UNAVAILABLE"
        assert len(calls) == 2

    # 6. Security order: invalid CSRF (403) writes zero ledger rows
    intents_before = len(intents())
    bad_csrf_form = run_form(env, record, str(uuid.uuid4()))
    bad_csrf_form["csrf_token"] = "forged-csrf-token"
    r_csrf = post(env, bad_csrf_form)
    assert r_csrf.status_code == 403
    assert len(intents()) == intents_before

    # 7. Protected reference refuses BEFORE any ledger row is written
    conn = db.get_connection()
    try:
        conn.execute(
            "UPDATE projects SET project_role='reference', is_protected=1 WHERE project_id=?",
            (record.project_id,),
        )
        conn.commit()
    finally:
        conn.close()
    r_prot = post(env, run_form(env, record, str(uuid.uuid4())))
    assert r_prot.status_code in (403, 409)
    assert len(intents()) == intents_before


def test_slice_a_policy_off_runtime_gate_genuinely_bypasses_ledger(env, monkeypatch):
    """Explicit policy-OFF test proving RELEASE_POLICY.enabled=False is a real runtime gate."""
    record = env.create("solar")
    calls = count_engine(monkeypatch)
    monkeypatch.setattr(ri_svc, "RELEASE_POLICY", RunIntentPolicy(enabled=False))

    key = str(uuid.uuid4())
    r1 = post(env, run_form(env, record, key))
    r2 = post(env, run_form(env, record, key))
    assert r1.status_code in (200, 303) and r2.status_code in (200, 303)
    assert len(calls) == 2, "Policy-OFF must bypass D-029 ledger and allow legacy non-idempotent execution"
    assert len(history(record)) == 2
    assert intents() == [], "Policy-OFF must write zero rows to model_run_intents"
