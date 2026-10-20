"""Operational admission and startup must never become financial authority."""
from collections import OrderedDict
import hashlib
import importlib.metadata
import multiprocessing as mp
import os
import pickle
import platform
import sys
from types import SimpleNamespace

import pytest

from financial_engine.financing import speculative as sp
from financial_engine.run_scope import engine_run_scope, current_run_scope
from tests.test_v9p1_speculative import controlled


def inspect_seed(value):
    scope = current_run_scope()
    if scope is None:
        return None
    cache = scope.get("financial_engine.orchestrator.run_operating_model", {})
    original = cache.get(b"key")
    if cache:
        cache[b"key"] = ("changed in helper",)
    return original, sorted(scope)


def owner_readiness():
    return {"concurrency": sp._OWNER_RUN_CONCURRENCY, "cpus": sp.effective_cpus(),
            "configured": sp.configured_workers(), "readiness": sp._PREWARM_EVIDENCE,
            "helper_pids": list(sp._POOL.executor._processes) if sp._POOL else [],
            "financial_submissions": sp._POOL.metrics["submitted"] if sp._POOL else 0}


@pytest.fixture(autouse=True)
def isolated_owner(monkeypatch):
    sp.shutdown_helpers()
    monkeypatch.setattr(sp, "_OWNER_RUN_CONCURRENCY", None)
    monkeypatch.setattr(sp, "_STARTUP_DISABLED", None)
    monkeypatch.setattr(sp, "_PREWARM_EVIDENCE", None)
    yield
    sp.shutdown_helpers()


def test_source_identity_is_identical_to_full_original_identity_algorithm():
    digest = hashlib.sha256()
    for package in ("financial_engine", "finco_core", "domain", "app"):
        for path in sorted((sp._ROOT / package).rglob("*.py")):
            digest.update(path.relative_to(sp._ROOT).as_posix().encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    for path in sorted(sp._ROOT.glob("requirements*.txt")):
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    versions = sorted((d.metadata["Name"], d.version) for d in importlib.metadata.distributions())
    numeric = tuple((key, os.environ.get(key)) for key in (
        "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS", "PYTHONHASHSEED"))
    assert sp.source_identity() == (digest.hexdigest(), sys.version, platform.machine(),
                                    tuple(versions), numeric)


@pytest.mark.parametrize("cpus,web,runs,expected", [
    (12, 2, 2, 1), (8, 1, 2, 2), (4, 1, 1, 2),
    (2, 1, 1, 0), (16, 2, 2, 2), (1, 1, 1, 0),
])
def test_budget_reserves_service_cpu_and_all_actual_run_owners(monkeypatch, cpus, web, runs, expected):
    monkeypatch.setenv("FINCO_G2A_WORKERS", "3")
    monkeypatch.setenv("FINCO_WEB_WORKERS", str(web))
    monkeypatch.setenv("FINCO_MODEL_EXECUTION_CONCURRENCY", "1")
    monkeypatch.setattr(sp, "effective_cpus", lambda: cpus)
    sp.configure_run_owner(runs)
    assert sp.configured_workers() == expected
    if expected:
        assert web * runs * (1 + expected) + 1 <= cpus


def test_no_pool_or_first_use_source_work_is_allowed_inside_a_cold_run(monkeypatch):
    monkeypatch.setattr(sp, "_acquire_pool", lambda *args: pytest.fail("cold financial path spawned helpers"))
    session = sp._Session(workers=3, timeout=15)
    session.strict_seen, session.binding = True, "DSCR"
    assert not sp.parallel_admitted(session)
    value = {"value": 1.}
    batch = sp._Batch(session, value, lambda: value, lambda x: x, controlled)
    assert batch.solve("capacity", value) == controlled(value)
    assert batch.solve("funded", batch.funded()) == controlled(value)


def test_admission_requires_warm_capacity_dscr_binding_and_observed_strict(monkeypatch):
    warm = SimpleNamespace(ready=True, broken=False, workers=2, shutdown=lambda: None)
    monkeypatch.setattr(sp, "_POOL", warm)
    session = sp._Session(workers=2, timeout=15)
    session.binding = "DSCR"
    assert not sp.parallel_admitted(session)
    session.strict_seen = True
    assert sp.parallel_admitted(session)
    for binding in (None, "GEARING", "UNAVAILABLE"):
        session.binding = binding
        assert not sp.parallel_admitted(session)
    session.binding = "DSCR"
    session.workers = 1
    assert not sp.parallel_admitted(session)
    session.workers = 3
    assert not sp.parallel_admitted(session)
    session.workers = 2
    warm.broken = True
    assert not sp.parallel_admitted(session)


def test_warm_proves_every_helper_identity_without_executing_finance():
    before = {p.pid for p in mp.active_children()}
    pool = sp.SpeculativePool(3, sp.source_identity(), 30)
    try:
        assert pool.warm()
        assert len(pool.startup["workers"]) == 3
        assert pool.metrics["submitted"] == pool.metrics["accepted"] == 0
        assert all(v["identity_metrics"]["source_files"] > 0 for v in pool.startup["workers"].values())
    finally:
        pool.shutdown()
    assert {p.pid for p in mp.active_children()} == before


def test_only_existing_pure_memos_are_copied_and_each_task_still_has_fresh_scope():
    pool = sp.SpeculativePool(1, sp.source_identity(), 30)
    try:
        for owner in ("a", "b"):
            with engine_run_scope():
                scope = current_run_scope()
                scope["financial_engine.orchestrator.run_operating_model"] = OrderedDict([(b"key", (owner,))])
                scope["unrelated_private_state"] = owner
                snapshot = sp._memo_snapshot()
                result = pool.outcome(pool.submit(inspect_seed, {}, snapshot))
                assert result == ((owner,), ["financial_engine.orchestrator.run_operating_model"])
                assert scope["financial_engine.orchestrator.run_operating_model"][b"key"] == (owner,)
            assert pool.outcome(pool.submit(inspect_seed, {})) == (None, [])
    finally:
        pool.shutdown()


def test_invalid_memo_scope_replays_native_without_retaining_data():
    pool = sp.SpeculativePool(1, sp.source_identity(), 30)
    try:
        bad = pickle.dumps({"unapproved_scope": {}})
        future = pool.submit(inspect_seed, {}, bad)
        assert pool.result_or_replay(future, inspect_seed, {}) is None
        assert pool.outcome(pool.submit(inspect_seed, {})) == (None, [])
    finally:
        pool.shutdown()


def test_memo_transport_is_recent_and_bounded_not_a_copy_of_the_whole_run():
    with engine_run_scope():
        scope = current_run_scope()
        for name in sp._PURE_MEMO_NAMES:
            scope[name] = OrderedDict((str(i).encode(), (i, bytes([i]) * 4096)) for i in range(32))
        snapshot = sp._memo_snapshot()
        assert snapshot is not None and len(snapshot) <= 65536
        restored = pickle.loads(snapshot)
        assert all(list(cache) == [b"30", b"31"] for cache in restored.values())
        assert all(len(cache) == 32 for cache in scope.values())
    with engine_run_scope():
        name = next(iter(sp._PURE_MEMO_NAMES))
        current_run_scope()[name] = OrderedDict([(b"large", (b"x" * 100000,))])
        assert sp._memo_snapshot() is None


def test_unused_strict_speculation_spends_only_observed_demand_credit():
    pool = sp.SpeculativePool(3, sp.source_identity(), 30)
    session = sp._Session(pool)
    session.strict_credit = 0
    value = {"value": 1.}
    try:
        observed = sp._Batch(session, value, lambda: value, lambda x: x, controlled)
        observed.solve("capacity", value)
        observed.solve("funded", value)
        observed.strict()
        observed.solve("strict", value)
        observed.close()
        first = sp._Batch(session, value, lambda: value, lambda x: x, controlled)
        first.solve("capacity", value)
        first.solve("funded", value)
        first.close()
        assert pool.metrics["speculative_strict"] == pool.metrics["unused_strict"] == 1
        second = sp._Batch(session, value, lambda: value, lambda x: x, controlled)
        assert "strict" not in second.future
        second.close()
    finally:
        pool.shutdown()


def test_disabled_startup_does_not_create_helpers_or_compute_identity(monkeypatch):
    monkeypatch.setenv("FINCO_G2A_WORKERS", "0")
    monkeypatch.setattr(sp, "_acquire_pool", lambda *args: pytest.fail("disabled startup created a pool"))
    assert sp.prewarm_worker(1)["workers"] == 0
    assert sp._POOL is None


def test_denied_startup_remains_serial_and_preserves_native_exception(monkeypatch):
    monkeypatch.setenv("FINCO_G2A_WORKERS", "2")
    monkeypatch.setenv("FINCO_WEB_WORKERS", "1")
    monkeypatch.setattr(sp, "effective_cpus", lambda: 8)
    def denied(*args):
        raise PermissionError("no processes")
    monkeypatch.setattr(sp, "_acquire_pool", denied)
    assert sp.prewarm_worker(1)["ready"] is False
    assert sp.configured_workers() == 0
    calls = []
    @sp.financing_execution_scope
    def native():
        calls.append(1)
        raise ValueError("native once")
    with pytest.raises(ValueError, match="native once"):
        native()
    assert calls == [1]


def test_actual_executor_readiness_uses_actual_config_not_mismatched_environment(monkeypatch):
    from app.runtime.model_execution import ModelExecutor, ModelExecutionConfig
    from tests.test_v9p1_speculative import process_alive
    monkeypatch.setenv("FINCO_G2A_WORKERS", "3")
    monkeypatch.setenv("FINCO_WEB_WORKERS", "1")
    monkeypatch.setenv("FINCO_MODEL_EXECUTION_CONCURRENCY", "8")
    executor = ModelExecutor(ModelExecutionConfig(1, "process", 180))
    info = None
    try:
        assert executor.warm_up()["warm"]
        info = executor.run_process_sync(owner_readiness)
        assert info["concurrency"] == 1
        expected = min(3, max(0, info["cpus"] - 2))
        assert info["configured"] == expected
        assert info["financial_submissions"] == 0
        if expected >= 2:
            assert info["readiness"]["ready"]
            assert len(info["helper_pids"]) == expected
        else:
            assert info["helper_pids"] == []
    finally:
        assert executor.shutdown_and_join() == []
    assert all(not process_alive(pid) for pid in info["helper_pids"])
