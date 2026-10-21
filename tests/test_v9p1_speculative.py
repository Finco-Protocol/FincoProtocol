"""Same spawn/fallback tests execute on Windows locally and Linux CI, without skips."""
import multiprocessing as mp
import os
import time

import pytest

from financial_engine.financing import speculative as sp


def controlled(value):
    child = mp.current_process().name != "MainProcess"
    kind = value.get("kind")
    if child and kind == "crash":
        os._exit(23)
    if child and kind == "timeout":
        time.sleep(3)
    if kind in ("financial_error", "strict_error"):
        try:
            raise KeyError(value["message"])
        except KeyError as cause:
            raise ValueError("native " + value["message"]) from cause
    if kind == "scope":
        from financial_engine.run_scope import current_run_scope
        scope = current_run_scope()
        old = len(scope)
        scope["synthetic_request_only"] = value["value"]
        return old
    return (value["value"], float(value["value"]).hex())


def chain(error):
    result = []
    while error is not None:
        result.append((type(error), str(error), error.__suppress_context__))
        error = error.__cause__ if error.__cause__ is not None else error.__context__
    return result


@pytest.fixture
def pool_factory():
    pools = []
    def create(workers=2, timeout=15):
        pool = sp.SpeculativePool(workers, sp.source_identity(), timeout)
        pools.append(pool)
        return pool
    yield create
    for pool in pools:
        pool.shutdown()


@pytest.mark.parametrize("workers", [1, 2, 3])
def test_real_spawn_complete_results_and_no_children_left(pool_factory, workers):
    before = {p.pid for p in mp.active_children()}
    pool = pool_factory(workers)
    inputs = [{"value": value} for value in (0., -0., 1e-300)]
    futures = [pool.submit(controlled, value) for value in inputs]
    assert [pool.result_or_replay(f, controlled, v) for f, v in zip(futures, inputs)] == [
        controlled(value) for value in inputs]
    assert not pool.broken
    assert pool.metrics["accepted"] == len(inputs)
    assert pool.metrics["replayed"] == 0
    assert len(pool.executor._processes) <= workers
    pool.shutdown()
    assert {p.pid for p in mp.active_children()} == before


@pytest.mark.parametrize("kind", ["financial_error", "crash", "timeout"])
def test_worker_failure_or_timeout_replays_native_result_or_full_cause(pool_factory, kind):
    pool = pool_factory(1)
    # Warm first so the timeout test concerns its task, not the initial import.
    good = {"value": 1.}
    assert pool.result_or_replay(pool.submit(controlled, good), controlled, good) == controlled(good)
    pool.timeout = .1
    value = {"value": 3., "kind": kind, "message": "capacity"}
    expected = None
    try:
        controlled(value)
    except ValueError as exc:
        expected = chain(exc)
    future = pool.submit(controlled, value)
    if expected is not None:
        with pytest.raises(ValueError) as caught:
            pool.result_or_replay(future, controlled, value)
        assert chain(caught.value) == expected
    else:
        assert pool.result_or_replay(future, controlled, value) == controlled(value)
    if kind in ("crash", "timeout"):
        assert pool.broken
        assert not pool.executor._processes


def test_source_mismatch_never_accepts_a_speculative_result(pool_factory):
    pool = pool_factory(1)
    pool.identity = ("not-the-verified-source",)
    value = {"value": 4.}
    future = pool.submit(controlled, value)
    assert pool.outcome(future) is sp._REPLAY
    assert pool.result_or_replay(None, controlled, value) == controlled(value)


def test_missing_source_evidence_cannot_create_a_worker_identity(monkeypatch, tmp_path):
    monkeypatch.setattr(sp, "_ROOT", tmp_path)
    with pytest.raises(FileNotFoundError, match="SOURCE_EVIDENCE_MISSING"):
        sp.source_identity()


def test_each_task_gets_an_independent_empty_run_scope(pool_factory):
    pool = pool_factory(1)
    for value in ("owner-a", "owner-b", "project-a", "project-b"):
        model = {"kind": "scope", "value": value}
        assert pool.outcome(pool.submit(controlled, model)) == 0


@pytest.mark.parametrize("capacity_fails,funded_fails,strict_fails", [
    (True, True, True), (True, False, True), (False, True, True), (False, False, True)])
def test_capacity_then_funded_then_strict_exception_precedence(
        pool_factory, capacity_fails, funded_fails, strict_fails):
    pool = pool_factory(3)
    session = sp._Session(pool)
    session.strict_seen = True
    def value(role, fails):
        return {"value": 1., "kind": "financial_error" if fails else "ok", "message": role}
    capacity = value("capacity", capacity_fails)
    funded = value("funded", funded_fails)
    strict = value("strict", strict_fails)
    batch = sp._Batch(session, capacity, lambda: funded, lambda _: strict, controlled)
    session.batch = batch
    expected = "capacity" if capacity_fails else "funded" if funded_fails else "strict"
    try:
        with pytest.raises(ValueError, match="native " + expected) as caught:
            batch.solve("capacity", capacity)
            batch.solve("funded", batch.funded())
            batch.solve("strict", strict)
        assert chain(caught.value) == [(ValueError, "native " + expected, True),
                                      (KeyError, repr(expected), False)]
    finally:
        session.close()


@pytest.mark.parametrize("capacity_fails", [False, True])
def test_input_construction_error_waits_for_capacity_verdict(pool_factory, capacity_fails):
    session = sp._Session(pool_factory())
    capacity = {"value": 1., "kind": "financial_error" if capacity_fails else "ok",
                "message": "capacity"}
    def failed_builder():
        raise LookupError("funded input")
    batch = sp._Batch(session, capacity, failed_builder, lambda x: x, controlled)
    session.batch = batch
    try:
        expected = ValueError if capacity_fails else LookupError
        with pytest.raises(expected, match="capacity" if capacity_fails else "funded input"):
            batch.solve("capacity", capacity)
            batch.funded()
    finally:
        session.close()


def test_deferred_input_exception_preserves_the_first_exact_native_error(pool_factory):
    session = sp._Session(pool_factory(1))
    good = {"value": 1.}
    calls = []
    def failed_builder():
        calls.append(1)
        raise LookupError(f"build attempt {len(calls)}")
    batch = sp._Batch(session, good, failed_builder, lambda x: x, controlled)
    session.batch = batch
    try:
        assert batch.solve("capacity", good) == controlled(good)
        with pytest.raises(LookupError, match="build attempt 1$"):
            batch.funded()
        assert calls == [1]
    finally:
        session.close()


def test_deferred_strict_input_error_is_not_reconstructed(pool_factory):
    session = sp._Session(pool_factory(3))
    session.strict_seen = True
    good = {"value": 1.}
    calls = []
    def strict(_):
        calls.append(1)
        raise LookupError(f"strict attempt {len(calls)}")
    batch = sp._Batch(session, good, lambda: good, strict, controlled)
    session.batch = batch
    try:
        batch.solve("capacity", good)
        batch.solve("funded", batch.funded())
        batch.strict()
        with pytest.raises(LookupError, match="strict attempt 1$"):
            batch.strict_input(good)
        assert calls == [1]
    finally:
        session.close()


def test_parent_wait_cancellation_aborts_helpers_without_replaying_finance(pool_factory):
    from concurrent.futures import Future
    pool = pool_factory(1)
    future = Future()
    future.set_exception(KeyboardInterrupt("parent cancelled"))
    with pytest.raises(KeyboardInterrupt, match="parent cancelled"):
        pool.result_or_replay(future, controlled, {"value": 1.})
    assert pool.broken
    assert pool.metrics["replayed"] == 0


def test_unused_strict_error_has_no_financial_authority(pool_factory):
    session = sp._Session(pool_factory(3))
    session.strict_seen = True
    good = {"value": 1.}
    bad = {"value": 1., "kind": "strict_error", "message": "not required"}
    batch = sp._Batch(session, good, lambda: good, lambda _: bad, controlled)
    session.batch = batch
    assert batch.solve("capacity", good) == controlled(good)
    assert batch.solve("funded", batch.funded()) == controlled(good)
    session.close()
    assert batch.future == {}
    assert batch.funded_input is sp._REPLAY


@pytest.mark.parametrize("requested", [0, 1, 2, 3])
def test_configuration_and_resource_refusal_are_serial_not_financial_errors(monkeypatch, requested):
    monkeypatch.setenv("FINCO_G2A_WORKERS", str(requested))
    monkeypatch.setenv("FINCO_WEB_WORKERS", "1")
    monkeypatch.setenv("FINCO_MODEL_EXECUTION_CONCURRENCY", "1")
    monkeypatch.setattr(sp, "effective_cpus", lambda: 8)
    assert sp.configured_workers() == requested
    monkeypatch.setattr(sp, "effective_cpus", lambda: 1)
    assert sp.configured_workers() == 0
    monkeypatch.setattr(sp, "effective_cpus", lambda: 8)
    monkeypatch.setattr(mp, "current_process", lambda: type("Daemon", (), {"daemon": True})())
    assert sp.configured_workers() == 0


@pytest.mark.parametrize("nested,root,expected", [
    ("200000 100000", "max 100000", 2),
    ("max 100000", "300000 100000", 3),
    ("150000 100000", "max 100000", 1),
    ("max 100000", "max 100000", 8),
    ("max 0", "max 100000", 1),
])
def test_linux_nested_and_parent_cpu_quotas_both_apply(monkeypatch, nested, root, expected):
    from pathlib import Path
    monkeypatch.setattr(sp.sys, "platform", "linux")
    monkeypatch.setattr(sp.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(sp.os, "sched_getaffinity", lambda _: set(range(8)), raising=False)
    def read(path, *args, **kwargs):
        name = path.as_posix()
        if name.endswith("/proc/self/cgroup"):
            return "0::/service/model\n"
        if name.endswith("/service/model/cpu.max"):
            return nested
        if name.endswith("/cgroup/cpu.max"):
            return root
        raise FileNotFoundError(name)
    monkeypatch.setattr(Path, "read_text", read)
    assert sp.effective_cpus() == expected


def test_unreadable_active_linux_quota_cannot_be_treated_as_unlimited(monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(sp.sys, "platform", "linux")
    monkeypatch.setattr(sp.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(sp.os, "sched_getaffinity", lambda _: set(range(8)), raising=False)
    def read(path, *args, **kwargs):
        name = path.as_posix()
        if name.endswith("/proc/self/cgroup"):
            return "0::/service\n"
        if name.endswith("/service/cpu.max"):
            raise PermissionError("quota not readable")
        if name.endswith("/cgroup/cpu.max"):
            return "max 100000"
        raise FileNotFoundError(name)
    monkeypatch.setattr(Path, "read_text", read)
    assert sp.effective_cpus() == 1


def test_serial_zero_preserves_original_call_order():
    order = []
    def solver(value):
        order.append(value)
        return value
    def funded():
        order.append("build funded")
        return "funded"
    batch = sp._Batch(None, "capacity", funded, lambda _: "strict", solver)
    assert order == []
    assert batch.solve("capacity", "capacity") == "capacity"
    assert batch.solve("funded", batch.funded()) == "funded"
    assert order == ["capacity", "build funded", "funded"]


@pytest.mark.parametrize("bad", ["-1", "4", "not-a-number"])
def test_invalid_operational_configuration_cannot_reject_a_financial_run(monkeypatch, bad):
    monkeypatch.setenv("FINCO_G2A_WORKERS", bad)
    assert sp.configured_workers() == 0


@pytest.mark.parametrize("timeout", ["nan", "0", "invalid", "181"])
def test_bad_timeout_does_not_catch_and_repeat_the_canonical_failure(monkeypatch, timeout):
    monkeypatch.setattr(sp, "configured_workers", lambda: 2)
    monkeypatch.setenv("FINCO_G2A_TASK_TIMEOUT_SECONDS", timeout)
    calls = []
    @sp.financing_execution_scope
    def native():
        calls.append(1)
        raise ValueError("canonical once")
    with pytest.raises(ValueError, match="canonical once"):
        native()
    assert calls == [1]


def test_prohibited_process_creation_runs_the_canonical_call_once(monkeypatch):
    monkeypatch.setattr(sp, "configured_workers", lambda: 2)
    def refused(*args):
        raise PermissionError("processes prohibited")
    monkeypatch.setattr(sp, "_acquire_pool", refused)
    calls = []
    @sp.financing_execution_scope
    def native():
        calls.append(1)
        return "canonical"
    assert native() == "canonical"
    assert calls == [1]


def test_submit_os_error_cannot_become_a_financial_refusal(monkeypatch):
    class RefusedExecutor:
        _processes = {}
        def __init__(self, **kwargs):
            self.closed = False
        def submit(self, *args):
            raise PermissionError("spawn prohibited")
        def shutdown(self, **kwargs):
            self.closed = True
    monkeypatch.setattr(sp, "ProcessPoolExecutor", RefusedExecutor)
    pool = sp.SpeculativePool(2, ("source",), 1)
    value = {"value": 7.}
    assert pool.submit(controlled, value) is None
    assert pool.broken and pool.executor.closed
    assert pool.result_or_replay(None, controlled, value) == controlled(value)


def test_unused_strict_input_failure_is_deferred_and_ignored(pool_factory):
    session = sp._Session(pool_factory(3))
    session.strict_seen = True
    good = {"value": 1.}
    def refused(_):
        raise ValueError("strict builder not required")
    batch = sp._Batch(session, good, lambda: good, refused, controlled)
    session.batch = batch
    try:
        assert batch.solve("capacity", good) == controlled(good)
        assert batch.solve("funded", batch.funded()) == controlled(good)
    finally:
        session.close()


def test_content_lock_rejection_falls_back_without_reusing_another_request(monkeypatch):
    monkeypatch.setattr(sp, "configured_workers", lambda: 2)
    calls = []
    @sp.financing_execution_scope
    def native(value):
        calls.append(value)
        assert sp._SESSION.get() is None
        return value
    assert sp._LOCK.acquire(blocking=False)
    try:
        assert native("isolated second request") == "isolated second request"
    finally:
        sp._LOCK.release()
    assert calls == ["isolated second request"]


def nested_helpers():
    pool = sp.SpeculativePool(2, sp.source_identity(), 15)
    try:
        values = [{"value": 1.}, {"value": 2.}]
        futures = [pool.submit(controlled, v) for v in values]
        return [pool.result_or_replay(f, controlled, v) for f, v in zip(futures, values)]
    finally:
        pool.shutdown()


def test_existing_application_spawn_worker_can_join_helpers():
    from app.runtime.model_execution import ModelExecutor, ModelExecutionConfig
    executor = ModelExecutor(ModelExecutionConfig(1, "process", 60))
    try:
        assert executor.run_process_sync(nested_helpers) == [controlled({"value": 1.}),
                                                           controlled({"value": 2.})]
    finally:
        assert executor.shutdown_and_join() == []


def abandoned_owner(pipe):
    pool = sp.SpeculativePool(1, sp.source_identity(), 30)
    value = {"value": 1.}
    assert pool.result_or_replay(pool.submit(controlled, value), controlled, value) == controlled(value)
    pipe.send(list(pool.executor._processes))
    pipe.recv()
    os._exit(0)


def process_alive(pid):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            return False
        try:
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            return kernel.WaitForSingleObject(handle, 0) == 0x102
        finally:
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle(handle)
    from pathlib import Path
    try:
        status = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return False
    return status.rsplit(")", 1)[1].split()[0] != "Z"


def test_helpers_exit_when_the_owning_worker_exits_without_finalizers():
    context = mp.get_context("spawn")
    parent, child = context.Pipe()
    owner = context.Process(target=abandoned_owner, args=(child,))
    owner.start()
    try:
        assert parent.poll(30)
        pids = parent.recv()
        assert all(process_alive(pid) for pid in pids)
        parent.send("exit without finally")
        owner.join(10)
        assert not owner.is_alive()
        deadline = time.monotonic() + 10
        while any(process_alive(pid) for pid in pids) and time.monotonic() < deadline:
            time.sleep(.05)
        assert all(not process_alive(pid) for pid in pids)
    finally:
        if owner.is_alive():
            owner.terminate()
            owner.join(5)
        parent.close()
        child.close()
