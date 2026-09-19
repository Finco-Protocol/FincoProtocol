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
    """Deterministic done()-late control via a pre-completed future and a
    controlled monotonic clock:

    - dispatch at t=100.00, provider window 0.15 s -> deadline 100.15;
    - the worker envelope captured completion at t=100.25 (AFTER the
      deadline) with a perfectly valid observation payload;
    - the future is ALREADY done when the coordinator collects it.

    The old implementation accepted such futures as SUCCESS merely
    because ``future.done()`` was true; N02 requires TIMEOUT
    (PER_PROVIDER_TIMEOUT).  A second control with an on-time completion
    (t=100.10) must keep its genuine SUCCESS."""
    from concurrent.futures import Future
    from app.radar_runtime.service import ProviderExecutionOutcome

    def run_case(completed_mono):
        # the coordinator's fake clock is pinned to 100.20 at dispatch;
        # the provider window (0.15 s) puts the deadline at 100.35
        service = _make_service(
            lambda r: (_ for _ in ()).throw(AssertionError("must not run")),
            capacity=1, per_provider=0.15)
        envelope = ProviderExecutionOutcome(
            provider="lifi", dispatch_mono=100.20,
            completed_mono=completed_mono,
            observation={"evidence": {"x": 1}})
        done = Future()
        done.set_result(envelope)

        class FakePool:
            _shutdown = False
            _work_queue = __import__("queue").Queue()

            def submit(self, fn, *args):
                return done

            def shutdown(self, *a, **k):
                pass

        service._provider_pool = FakePool()
        clock = {"t": 100.20}
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
    from app.radar_runtime.service import _deadline_outcome

    # completion within both deadlines -> not timed out
    assert _deadline_outcome(0.50, 5.0, 0.22, 9.9) == (False, None)
    # completion after the provider window (provider limiting)
    timed_out, code = _deadline_outcome(0.15, 5.0, 0.22, 9.9)
    assert timed_out is True and code == "PER_PROVIDER_TIMEOUT"
    # completion after the total budget (budget limiting)
    timed_out, code = _deadline_outcome(2.0, 0.25, 0.60, 9.9)
    assert timed_out is True and code == "TOTAL_BUDGET_EXHAUSTED"
    # still running at the decision point -> decision time vs limiting
    timed_out, code = _deadline_outcome(0.15, 5.0, None, 0.16)
    assert timed_out is True and code == "PER_PROVIDER_TIMEOUT"
    timed_out, code = _deadline_outcome(2.0, 0.25, None, 0.30)
    assert timed_out is True and code == "TOTAL_BUDGET_EXHAUSTED"
    # still running but BEFORE the limiting deadline -> keep waiting
    assert _deadline_outcome(2.0, 5.0, None, 0.30) == (False, None)
    # equal deadlines, budget wins the tie
    timed_out, code = _deadline_outcome(0.25, 0.25, 0.40, 9.9)
    assert timed_out is True and code == "TOTAL_BUDGET_EXHAUSTED"
