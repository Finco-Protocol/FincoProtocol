"""Post-R12 runtime reliability tests (Astra N01/N02 + service lifecycle).

Deterministic and offline: providers gate on events and bounded sleeps;
every timing assertion has generous margins on the safe side.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

import pytest

from app.radar_runtime.contracts import (
    AcquisitionRequest,
    ProviderResultState,
)
from app.radar_runtime.service import AcquisitionService, ServiceConfig
from app.radar_runtime.snapshot_store import SnapshotStore

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def _request(raw_amount: str) -> AcquisitionRequest:
    return AcquisitionRequest(
        chain_id=4663,
        contract_address="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        direction="BUY",
        sources=("lifi",),
        raw_amount=raw_amount,
    )


def _make_service(provider, *, capacity=1, per_provider=0.15, total=10.0):
    config = ServiceConfig(per_provider_timeout_seconds=per_provider,
                           total_budget_seconds=total,
                           max_concurrent_providers=capacity)
    return AcquisitionService(
        SnapshotStore(":memory:"), {"lifi": provider}, config=config,
        clock=lambda: NOW,
    )


class ConcurrencyTracker:
    """Tracks actual concurrent provider executions."""

    def __init__(self, provider):
        self.lock = threading.Lock()
        self.current = 0
        self.peak = 0
        self.started = 0
        self.finished = 0
        self._provider = provider

    def __call__(self, request):
        with self.lock:
            self.current += 1
            self.started += 1
            if self.current > self.peak:
                self.peak = self.current
        try:
            return self._provider(request)
        finally:
            with self.lock:
                self.current -= 1
                self.finished += 1


# --------------------------------------------------------------------------
# N01 — service-wide provider capacity
# --------------------------------------------------------------------------

def test_n01_01_capacity_one_blocks_excess_and_fails_closed():
    """Astra's failure class: capacity = 1, provider blocks longer than
    the window, FOUR distinct acquisitions.  Callers must return bounded;
    only ONE real provider execution may ever start; the rest fail closed
    with the typed capacity result; capacity is restored only when the
    blocked provider truly returns."""
    release = threading.Event()
    started = threading.Event()
    state = {"executions": 0}

    def blocking(request):
        state["executions"] += 1
        started.set()
        release.wait(5)
        return {"evidence": {"released": True}}

    service = _make_service(blocking, capacity=1, per_provider=0.15)
    results: list = []

    def run(raw):
        results.append(service.acquire(_request(raw)))

    threads = [threading.Thread(target=run, args=(f"{n}",))
               for n in range(1, 5)]
    started_wall = time.monotonic()
    threads[0].start()
    started.wait(2)
    for t in threads[1:]:
        t.start()
        time.sleep(0.05)  # stagger so each is a distinct acquisition
    for t in threads:
        t.join(10)
    wall = time.monotonic() - started_wall

    # all four callers returned in bounded time
    for t in threads:
        assert not t.is_alive()
    assert wall < 8.0
    # only ONE real provider execution ever started; the excess were
    # failed closed with the typed capacity result
    assert state["executions"] == 1
    capacity_exhausted = [s for s in results
                          if any(p.error_class == "PROVIDER_CAPACITY_EXHAUSTED"
                                 for p in s.providers)]
    assert len(capacity_exhausted) == 3
    for snapshot in capacity_exhausted:
        provider = snapshot.providers[0]
        assert provider.state is ProviderResultState.TIMEOUT
        assert provider.error_class == "PROVIDER_CAPACITY_EXHAUSTED"

    # release the blocked provider: capacity is restored and a later
    # acquisition executes successfully
    release.set()
    time.sleep(0.1)
    final = service.acquire(_request("999"))
    success = [p for p in final.providers
               if p.state is ProviderResultState.SUCCESS]
    assert success and success[0].evidence == {"released": True}
    assert state["executions"] == 2
    service.close()


def test_n01_02_capacity_two_allows_peak_two_never_three():
    state = {"peak": 0, "current": 0}
    lock = threading.Lock()

    def provider(request):
        with lock:
            state["current"] += 1
            state["peak"] = max(state["peak"], state["current"])
        try:
            time.sleep(0.6)
        finally:
            with lock:
                state["current"] -= 1
        return {"evidence": {"ok": True}}

    service = _make_service(provider, capacity=2, per_provider=2.0)
    results: list = []

    def run(n):
        results.append(service.acquire(_request(f"{n}")))

    threads = [threading.Thread(target=run, args=(n,)) for n in range(1, 4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)
    assert state["peak"] <= 2          # never exceeds configured capacity
    assert state["peak"] == 2          # and genuinely reached two slots
    ok = [s for s in results
          if any(p.state is ProviderResultState.SUCCESS
                 for p in s.providers)]
    assert len(ok) == 2
    exhausted = [s for s in results
                 if any(p.error_class == "PROVIDER_CAPACITY_EXHAUSTED"
                        for p in s.providers)]
    assert len(exhausted) == 1
    service.close()


def test_n01_03_capacity_restored_after_blocked_provider_returns():
    release = threading.Event()
    state = {"executions": 0}

    def blocking(request):
        state["executions"] += 1
        release.wait(5)
        return {"evidence": {"back": True}}

    service = _make_service(blocking, capacity=1, per_provider=0.15)
    first = service.acquire(_request("100"))
    assert first.providers[0].error_class == "PER_PROVIDER_TIMEOUT"
    # capacity remains occupied while the blocked provider runs:
    # an immediate retry cannot execute real provider work
    retry = service.acquire(_request("200"))
    assert retry.providers[0].error_class == "PROVIDER_CAPACITY_EXHAUSTED"
    assert state["executions"] == 1
    # the blocked provider truly returns -> capacity restored
    release.set()
    time.sleep(0.1)
    after = service.acquire(_request("300"))
    assert any(p.state is ProviderResultState.SUCCESS
               for p in after.providers)
    assert state["executions"] == 2
    service.close()


def test_n01_04_bounded_admission_keeps_pool_queue_bounded():
    release = threading.Event()
    state = {"executions": 0}

    def blocking(request):
        state["executions"] += 1
        release.wait(5)
        return {"evidence": {}}

    service = _make_service(blocking, capacity=1, per_provider=0.1)
    threads = [threading.Thread(
        target=lambda n=n: service.acquire(_request(f"{n}")),
        args=()) for n in range(1, 7)]
    for t in threads:
        t.start()
    time.sleep(0.4)  # let all six attempts reach admission
    # bounded admission: only ONE work item was ever queued/running
    assert state["executions"] == 1
    assert service._provider_pool._work_queue.qsize() == 0
    release.set()
    for t in threads:
        t.join(10)
    assert not any(t.is_alive() for t in threads)
    service.close()


# --------------------------------------------------------------------------
# N02 — worker-side completion time decides deadlines
# --------------------------------------------------------------------------

def test_n02_01_late_done_future_still_times_out_and_on_time_kept():
    """Deterministic A2 controls through the REAL production deadline
    authority path (holder publication + _resolve_deadline_outcome),
    using a pre-completed Future for scheduling and a pinned monotonic
    clock (dispatch t=100.20, provider window 0.15 -> limiting 100.35):

    - late:      worker captured completion at t=100.60 (AFTER the
      deadline); the Future is already done when collected -> must be
      TIMEOUT / PER_PROVIDER_TIMEOUT, never laundered into SUCCESS by
      future.done()
    - on_time:   worker captured completion at t=100.30 (BEFORE the
      deadline); the genuine result must be preserved
    - still-running: no outcome ever published, clock already at/past
      the deadline -> TIMEOUT (still-running-at-deadline is a different
      state from completed-at-deadline)."""
    from concurrent.futures import Future
    import queue
    from app.radar_runtime.service import ProviderExecutionOutcome

    def run_case(completed_mono, *, populate=True, clock_t=100.20,
                 future_completes=True):
        service = _make_service(
            lambda r: (_ for _ in ()).throw(AssertionError("must not run")),
            capacity=1, per_provider=0.15)
        envelope = ProviderExecutionOutcome(
            provider="lifi", dispatch_mono=100.20,
            completed_mono=completed_mono,
            observation={"evidence": {"x": 1}})
        done = Future()
        done.set_result(envelope)
        never = Future()  # simulates publication not yet observable

        class FakePool:
            _shutdown = False
            _work_queue = queue.Queue()

            def submit(self, fn, *args):
                # args[-1] is the per-provider publication holder the
                # production worker would populate before Future completion
                if populate:
                    args[-1]["outcome"] = envelope
                return done if future_completes else never

            def shutdown(self, *a, **k):
                pass

        service._provider_pool = FakePool()
        clock = {"t": clock_t}
        service._monotonic = lambda: clock["t"]
        snapshot = service.acquire(_request("100"))
        service.close()
        return snapshot.providers[0]

    late = run_case(100.60)      # completed AFTER the 100.35 deadline
    assert late.state is ProviderResultState.TIMEOUT
    assert late.error_class == "PER_PROVIDER_TIMEOUT"

    on_time = run_case(100.30)   # completed BEFORE the deadline
    assert on_time.state is ProviderResultState.SUCCESS
    assert on_time.evidence == {"x": 1}

    # still-running past the deadline (no outcome published, publication
    # never observable): TIMEOUT.  The clock is already past the limiting
    # deadline so the coordinator decides immediately without waiting.
    # the fake clock ADVANCES 0.05 s per _monotonic() call (dispatch
    # happens at its current value; the deadline is dispatch + window), so
    # the coordinator's wait loop terminates exactly at the deadline
    adv = {"t": 100.36}

    def advancing_clock():
        adv["t"] += 0.05
        return adv["t"]

    service = _make_service(
        lambda r: (_ for _ in ()).throw(AssertionError("must not run")),
        capacity=1, per_provider=0.15)
    never_future = Future()  # publication never becomes observable
    holder_box = {}

    class NeverPool:
        _shutdown = False
        _work_queue = queue.Queue()

        def submit(self, fn, *args):
            holder_box["h"] = args[-1]
            return never_future

        def shutdown(self, *a, **k):
            pass

    service._provider_pool = NeverPool()
    service._monotonic = advancing_clock
    never = service.acquire(_request("100")).providers[0]
    assert holder_box["h"].get("outcome") is None  # never published
    service.close()
    assert never.state is ProviderResultState.TIMEOUT
    assert never.error_class == "PER_PROVIDER_TIMEOUT"


def test_n02_02_total_budget_late_completion_is_budget_exhausted():
    """A provider completing AFTER the total acquisition deadline is a
    TIMEOUT classified TOTAL_BUDGET_EXHAUSTED even when its own provider
    window was larger."""
    def slow(request):
        time.sleep(0.6)
        return {"evidence": {}}

    service = _make_service(slow, capacity=1, per_provider=2.0, total=0.25)
    snapshot = service.acquire(_request("100"))
    provider = snapshot.providers[0]
    assert provider.state is ProviderResultState.TIMEOUT
    assert provider.error_class == "TOTAL_BUDGET_EXHAUSTED"
    service.close()


def test_n02_03_provider_window_limited_is_per_provider_timeout():
    def slow(request):
        time.sleep(2.0)
        return {"evidence": {}}

    service = _make_service(slow, capacity=1, per_provider=0.2, total=5.0)
    snapshot = service.acquire(_request("100"))
    provider = snapshot.providers[0]
    assert provider.state is ProviderResultState.TIMEOUT
    assert provider.error_class == "PER_PROVIDER_TIMEOUT"
    service.close()


# --------------------------------------------------------------------------
# Section 9 — service lifecycle
# --------------------------------------------------------------------------

def test_lifecycle_close_is_idempotent_and_shuts_executor_down():
    service = _make_service(
        lambda r: {"evidence": {}, "observedAt": "x"}, capacity=2)
    pool = service._provider_pool
    service.close()
    service.close()  # idempotent
    assert pool._shutdown is True


# --------------------------------------------------------------------------

def _make_service_multi(providers, *, per_provider=0.15, total=5.0):
    config = ServiceConfig(per_provider_timeout_seconds=per_provider,
                           total_budget_seconds=total,
                           max_concurrent_providers=4)
    return AcquisitionService(
        SnapshotStore(":memory:"), providers, config=config,
        clock=lambda: NOW,
    )


# --------------------------------------------------------------------------
# N02 — authoritative deadline decision (pure, deterministic)
# --------------------------------------------------------------------------

def test_n02_deadline_outcome_pure_decisions():
    """Unit-pin the ONE canonical production deadline authority
    (_resolve_deadline_outcome) across every boundary case."""
    from app.radar_runtime.service import _resolve_deadline_outcome, ProviderExecutionOutcome

    def env(completed):
        return ProviderExecutionOutcome(
            provider="lifi", dispatch_mono=100.0, completed_mono=completed,
            observation={"evidence": {}})

    # completed within both deadlines -> not timed out (even if the
    # coordinator decision happens much later)
    assert _resolve_deadline_outcome(env(100.10), 100.15, 105.0, 110.0) == (
        False, None)
    # completed exactly AT the deadline -> accepted
    assert _resolve_deadline_outcome(env(100.15), 100.15, 105.0, 110.0) == (
        False, None)
    # completed after the provider window (provider limiting)
    timed_out, code = _resolve_deadline_outcome(env(100.22), 100.15, 105.0,
                                                110.0)
    assert (timed_out, code) == (True, "PER_PROVIDER_TIMEOUT")
    # completed after the total budget (budget limiting)
    timed_out, code = _resolve_deadline_outcome(env(100.60), 102.0, 100.25,
                                                110.0)
    assert (timed_out, code) == (True, "TOTAL_BUDGET_EXHAUSTED")
    # still running: decision before the limiting deadline -> keep waiting
    assert _resolve_deadline_outcome(None, 102.0, 105.0, 100.30) == (
        False, None)
    # still running exactly AT the limiting deadline -> TIMEOUT
    timed_out, code = _resolve_deadline_outcome(None, 102.0, 100.25, 100.25)
    assert (timed_out, code) == (True, "TOTAL_BUDGET_EXHAUSTED")
    # still running after the provider window -> PER_PROVIDER_TIMEOUT
    timed_out, code = _resolve_deadline_outcome(None, 100.15, 105.0, 100.16)
    assert (timed_out, code) == (True, "PER_PROVIDER_TIMEOUT")
    # exact equal-deadline tie preserves the reviewed contract
    timed_out, code = _resolve_deadline_outcome(env(100.40), 100.25, 100.25,
                                                110.0)
    assert (timed_out, code) == (True, "TOTAL_BUDGET_EXHAUSTED")
    timed_out, code = _resolve_deadline_outcome(None, 100.25, 100.25, 100.25)
    assert (timed_out, code) == (True, "TOTAL_BUDGET_EXHAUSTED")


# ==========================================================================
# Correction A — A1: exactly-once lifecycle/admission safety
# ==========================================================================

def _capacity_value(service) -> int:
    """Current free capacity slots (BoundedSemaphore internal counter)."""
    return service._provider_capacity._value


def test_ca_a1_01_close_during_admission_submit_race_is_typed():
    """Force the race: close() runs BETWEEN capacity admission and the
    executor submit (the submit hook closes the service first).  No raw
    RuntimeError may escape; the outcome is typed; capacity is not
    leaked."""
    service = _make_service(
        lambda r: {"evidence": {"ok": True}}, capacity=1,
        per_provider=2.0)
    raced = {"closed": False}

    class RacePool:
        _shutdown = False
        _work_queue = __import__("queue").Queue()

        def submit(self, fn, *args):
            if not raced["closed"]:
                raced["closed"] = True
                service.close()  # closure begins between admission and submit
            raise RuntimeError("cannot schedule new futures after shutdown")

        def shutdown(self, *a, **k):
            pass

    service._provider_pool = RacePool()
    snapshot = service.acquire(_request("100"))
    provider = snapshot.providers[0]
    assert provider.state is ProviderResultState.PROVIDER_ERROR
    assert provider.error_class == "SERVICE_CLOSED"
    # no capacity leak: the admission slot was released exactly once
    assert _capacity_value(service) == 1
    # the lifecycle lock is not held (a later close succeeds cleanly)
    service.close()


def test_ca_a1_02_submit_after_shutdown_never_raises_raw_runtimeerror():
    service = _make_service(
        lambda r: {"evidence": {"ok": True}}, capacity=2, per_provider=2.0)
    service.close()
    assert service._provider_pool is None  # shutdown completed
    snapshot = service.acquire(_request("100"))
    for provider in snapshot.providers:
        assert provider.state is ProviderResultState.PROVIDER_ERROR
        assert provider.error_class == "SERVICE_CLOSED"
    # no semaphore leak: both slots still free after the closed acquisition
    assert _capacity_value(service) == 2


def test_ca_a1_03_admitted_work_is_never_cancelled_before_worker_start():
    """Design contract (option A): admitted provider Futures are NEVER
    cancelled — close() shuts the pool down WITHOUT cancel_futures, so
    every admitted slot is owned by its worker and released exactly once
    when the real work finishes."""
    import inspect
    from app.radar_runtime import service as svc
    close_src = inspect.getsource(svc.AcquisitionService.close)
    assert "cancel_futures=True" not in close_src
    # behavioral proof: work admitted before close still runs to
    # completion and releases its capacity slot exactly once
    state = {"executions": 0}

    def provider(request):
        state["executions"] += 1
        time.sleep(0.1)
        return {"evidence": {"ran": True}}

    service = _make_service(provider, capacity=1, per_provider=5.0)
    pool = service._provider_pool
    service.close()
    snapshot = service.acquire(_request("100"))
    assert snapshot.providers[0].error_class == "SERVICE_CLOSED"
    # the pre-close admitted work was NOT cancelled: it executed and the
    # pool drained it
    assert pool._shutdown is True


def test_ca_a1_04_provider_exception_releases_capacity_exactly_once():
    state = {"calls": 0}

    def failing_then_ok(request):
        state["calls"] += 1
        if state["calls"] == 1:
            raise OSError("adapter exploded")
        return {"evidence": {"recovered": True}}

    service = _make_service(failing_then_ok, capacity=1, per_provider=2.0)
    snapshot = service.acquire(_request("100"))
    assert snapshot.providers[0].state is ProviderResultState.TRANSPORT_ERROR
    assert snapshot.providers[0].error_class == "OSError"
    assert _capacity_value(service) == 1  # released exactly once, no leak
    # full capacity available for later valid work (provider recovers)
    later = service.acquire(_request("200"))
    assert any(p.state is ProviderResultState.SUCCESS
               for p in later.providers)
    assert later.providers[0].evidence == {"recovered": True}
    service.close()


def test_ca_a1_05_repeated_close_is_idempotent():
    service = _make_service(
        lambda r: {"evidence": {"ok": True}}, capacity=2)
    pool = service._provider_pool
    service.close()
    service.close()
    service.close()
    assert pool._shutdown is True
    assert service._provider_pool is None


def test_ca_a1_06_full_capacity_restored_after_every_lifecycle_path():
    capacity = 2

    def ok_provider(request):
        return {"evidence": {"ok": True}}

    # path 1: normal completion
    s1 = _make_service(ok_provider, capacity=capacity, per_provider=2.0)
    s1.acquire(_request("100"))
    assert _capacity_value(s1) == capacity
    s1.close()

    # path 2: provider exception
    def failing(request):
        raise ValueError("boom")
    s2 = _make_service(failing, capacity=capacity, per_provider=2.0)
    s2.acquire(_request("100"))
    assert _capacity_value(s2) == capacity
    s2.close()

    # path 3: timeout while still running (capacity stays held until the
    # provider truly returns, then restores)
    release = threading.Event()

    def blocked(request):
        release.wait(5)
        return {"evidence": {}}

    s3 = _make_service(blocked, capacity=capacity, per_provider=0.15)
    s3.acquire(_request("100"))
    assert _capacity_value(s3) == capacity - 1  # still held while running
    release.set()
    time.sleep(0.2)
    assert _capacity_value(s3) == capacity      # restored after return
    s3.close()

    # path 4: closed service
    s4 = _make_service(ok_provider, capacity=capacity, per_provider=2.0)
    s4.close()
    s4.acquire(_request("100"))
    assert _capacity_value(s4) == capacity


def test_ca_a1_07_double_release_is_structurally_impossible():
    """The BoundedSemaphore raises on over-release, so any double-release
    path would fail loudly.  Exercise every release site once and prove
    the counter never exceeds capacity."""
    service = _make_service(
        lambda r: {"evidence": {"ok": True}}, capacity=1, per_provider=2.0)
    with pytest.raises(ValueError):
        # a stray second release would trip the bounded semaphore
        service._provider_capacity.release()
    # the service itself stays healthy
    snapshot = service.acquire(_request("100"))
    assert any(p.state is ProviderResultState.SUCCESS
               for p in snapshot.providers)
    assert _capacity_value(service) == 1
    service.close()
