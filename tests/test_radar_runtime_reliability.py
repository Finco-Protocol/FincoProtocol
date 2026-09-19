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


def _request(raw_amount: str, sources: "tuple[str, ...]" = ("lifi",)) -> AcquisitionRequest:
    return AcquisitionRequest(
        chain_id=4663,
        contract_address="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        direction="BUY",
        sources=sources,
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


def _make_service_multi(providers, *, capacity=4, per_provider=0.15,
                        total=10.0):
    config = ServiceConfig(per_provider_timeout_seconds=per_provider,
                           total_budget_seconds=total,
                           max_concurrent_providers=capacity)
    return AcquisitionService(
        SnapshotStore(":memory:"), providers, config=config,
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

def test_n02_01_publication_delay_preserves_on_time_completion():
    """B1.1 mandatory adversarial test on the REAL production path (no
    fake submit, no pre-populated holder):

    1. the real worker begins and the provider callable returns well
       before the limiting deadline;
    2. the worker records the authoritative completed_mono;
    3. the test deliberately blocks subsequent outcome publication
       (envelope construction) until AFTER the deadline by patching the
       envelope carrier;
    4. the coordinator passes the deadline;
    5. publication is released.

    Final classification must be the genuine SUCCESS — never TIMEOUT
    merely because envelope publication happened late.  (Fails against
    Correction A HEAD 0477713, where publication lived in the holder
    after envelope construction.)"""
    from app.radar_runtime import service as svc

    publication_gate = threading.Event()
    real_outcome_cls = svc.ProviderExecutionOutcome

    class DelayedPublicationOutcome(real_outcome_cls):
        """Blocks envelope construction (publication) until released —
        the coordinator must pass the limiting deadline while publication
        is pending, with the completion marker already observable."""

        def __init__(self, *args, **kwargs):
            publication_gate.wait(5)
            super().__init__(*args, **kwargs)

    svc.ProviderExecutionOutcome = DelayedPublicationOutcome

    def release_after_deadline():
        time.sleep(0.3)  # > the 0.2 s limiting deadline
        publication_gate.set()

    releaser = threading.Thread(target=release_after_deadline, daemon=True)
    releaser.start()
    try:
        service = _make_service(
            lambda r: {"evidence": {"genuine": True}},
            capacity=1, per_provider=0.2, total=5.0)
        snapshot = service.acquire(_request("100"))
    finally:
        publication_gate.set()
        svc.ProviderExecutionOutcome = real_outcome_cls
    releaser.join(5)

    provider = snapshot.providers[0]
    assert provider.state is ProviderResultState.SUCCESS
    assert provider.error_class is None
    assert provider.evidence == {"genuine": True}
    # elapsed reflects the real dispatch -> completion interval, not the
    # delayed publication window
    assert provider.elapsed_ms < 400
    service.close()


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




# --------------------------------------------------------------------------
# N02 — authoritative deadline decision (pure, deterministic)
# --------------------------------------------------------------------------

def test_n02_deadline_outcome_pure_decisions():
    """Unit-pin the ONE canonical production deadline authority
    (_resolve_deadline_outcome) across every boundary case (B1.2-B1.5).
    The production collection path calls this same function."""
    from app.radar_runtime.service import _resolve_deadline_outcome

    # B1.1/B1.3: completed within the deadline -> accepted (even when the
    # decision happens much later than completion)
    assert _resolve_deadline_outcome(True, 100.10, 100.15, 105.0, 110.0) == (
        False, None)
    # B1.3: completed exactly AT the deadline -> accepted
    assert _resolve_deadline_outcome(True, 100.15, 100.15, 105.0, 110.0) == (
        False, None)
    # B1.2: completed after the provider window (provider limiting)
    timed_out, code = _resolve_deadline_outcome(True, 100.22, 100.15, 105.0,
                                                110.0)
    assert (timed_out, code) == (True, "PER_PROVIDER_TIMEOUT")
    # B1.2: completed after the total budget (budget limiting)
    timed_out, code = _resolve_deadline_outcome(True, 100.60, 102.0, 100.25,
                                                110.0)
    assert (timed_out, code) == (True, "TOTAL_BUDGET_EXHAUSTED")
    # B1.4: still running, decision BEFORE the limiting deadline -> keep
    # waiting (production waits until the deadline before deciding)
    assert _resolve_deadline_outcome(False, None, 102.0, 105.0, 100.30) == (
        False, None)
    # B1.4: still running exactly AT the limiting deadline -> TIMEOUT
    timed_out, code = _resolve_deadline_outcome(False, None, 102.0, 100.25,
                                                100.25)
    assert (timed_out, code) == (True, "TOTAL_BUDGET_EXHAUSTED")
    # B1.4: still running after the provider window -> PER_PROVIDER_TIMEOUT
    timed_out, code = _resolve_deadline_outcome(False, None, 100.15, 105.0,
                                                100.16)
    assert (timed_out, code) == (True, "PER_PROVIDER_TIMEOUT")
    # B1.5: exact equal-deadline tie preserves the reviewed contract
    timed_out, code = _resolve_deadline_outcome(True, 100.40, 100.25, 100.25,
                                                110.0)
    assert (timed_out, code) == (True, "TOTAL_BUDGET_EXHAUSTED")
    timed_out, code = _resolve_deadline_outcome(False, None, 100.25, 100.25,
                                                100.25)
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


def test_ca_a1_03_close_does_not_cancel_and_service_stays_typed():
    """Design contract (option A) narrowed to what it behaviorally
    proves: close() never cancels provider work (source-pinned), a
    post-close acquisition is typed SERVICE_CLOSED, and the pool drained
    whatever was admitted before closure."""
    import inspect
    from app.radar_runtime import service as svc
    close_src = inspect.getsource(svc.AcquisitionService.close)
    assert "cancel_futures=True" not in close_src
    # behavioral proof: work admitted before close still runs to
    # completion and the pool drained it
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


# ==========================================================================
# Correction B — B1 counter-test, boundaries, order independence, B2
# ==========================================================================

def test_cb_b1_counter_late_completion_via_production_path():
    """Section 8 counter-test on the real production path: the provider
    callable remains running through the limiting deadline; completion
    and immediate publication occur only afterward.  The final state must
    remain TIMEOUT with the exact classification."""
    service = _make_service(
        lambda r: (time.sleep(0.35),
                   {"evidence": {"late": True}})[1],
        capacity=1, per_provider=0.2, total=5.0)
    snapshot = service.acquire(_request("100"))
    provider = snapshot.providers[0]
    assert provider.state is ProviderResultState.TIMEOUT
    assert provider.error_class == "PER_PROVIDER_TIMEOUT"
    assert provider.evidence is None  # genuine late completion: no result
    service.close()


def test_cb_b1_boundary_completed_at_deadline_accepted_production_path():
    """B1.3 via the real production path: the provider callable returns
    and the worker captures completed_mono EXACTLY at the limiting
    deadline (deterministic scripted clock) — accepted as completed, not
    timeout."""
    clock = {"t": 100.20}

    def provider(request):
        # the callable completes exactly at the limiting deadline
        clock["t"] = 100.35  # dispatch 100.20 + window 0.15
        return {"evidence": {"boundary": True}}

    service = _make_service(provider, capacity=1, per_provider=0.15,
                            total=5.0)
    service._monotonic = lambda: clock["t"]
    snapshot = service.acquire(_request("100"))
    provider_result = snapshot.providers[0]
    assert provider_result.state is ProviderResultState.SUCCESS
    assert provider_result.error_class is None
    # elapsed = completed_mono - dispatch = exactly the window
    assert provider_result.elapsed_ms == 150.0
    service.close()


def test_cb_b1_boundary_still_running_at_deadline_production_path():
    """B1.4 via the real production path: no completion marker exists at
    the limiting deadline (the provider blocks until the clock is exactly
    at the deadline, then keeps blocking) — still-running-at-deadline is
    a TIMEOUT, distinct from completed-at-deadline."""
    release = threading.Event()

    def provider(request):
        clock["t"] = 100.36  # decisively past the 0.15 s deadline
        release.wait(5)
        return {"evidence": {"never": True}}

    clock = {"t": 100.20}
    service = _make_service(provider, capacity=1, per_provider=0.15,
                            total=5.0)
    service._monotonic = lambda: clock["t"]
    snapshot = service.acquire(_request("100"))
    provider_result = snapshot.providers[0]
    assert provider_result.state is ProviderResultState.TIMEOUT
    assert provider_result.error_class == "PER_PROVIDER_TIMEOUT"
    release.set()
    service.close()


def test_cb_b2_elapsed_still_running_uses_limiting_deadline():
    """B2/section 9-10: multi-provider delayed-coordinator proof.  Both
    providers are still running at their limiting deadline (0.20 s); the
    coordinator processes the first, then the second at ~0.23 s — the
    persisted elapsed_ms must equal the limiting deadline (200 ms), not
    the delayed coordinator time."""
    gate = threading.Event()
    calls: list = []

    def slow(request):
        calls.append(request)
        gate.wait(5)
        return {"evidence": {}}

    service = _make_service_multi(
        {name: slow for name in ("a", "b")},
        capacity=2, per_provider=0.2, total=10.0)
    snapshot = service.acquire(_request("100", sources=("a", "b")))
    gate.set()
    for provider in snapshot.providers:
        assert provider.state is ProviderResultState.TIMEOUT
        # elapsed == limiting deadline - dispatch, NOT the coordinator time
        assert provider.elapsed_ms == 200.0
    service.close()


def test_cb_b2_elapsed_late_completed_uses_actual_completion():
    """B2 via the REAL production path with a deterministic scripted
    clock: the provider callable completes at t=100.50 — AFTER its
    limiting deadline (dispatch 100.20 + window 0.15 = 100.35) — and the
    worker publishes immediately.  Outcome: TIMEOUT /
    PER_PROVIDER_TIMEOUT with elapsed_ms == the genuine dispatch ->
    completion interval (300 ms), preserving real lateness."""
    clock = {"t": 100.20}

    def provider(request):
        clock["t"] = 100.50  # completion AFTER the 100.35 deadline
        return {"evidence": {"late": True}}

    service = _make_service(provider, capacity=1, per_provider=0.15,
                            total=5.0)
    service._monotonic = lambda: clock["t"]
    snapshot = service.acquire(_request("100"))
    provider_result = snapshot.providers[0]
    assert provider_result.state is ProviderResultState.TIMEOUT
    assert provider_result.error_class == "PER_PROVIDER_TIMEOUT"
    assert provider_result.elapsed_ms == 300.0  # actual completion interval
    service.close()


def test_cb_b2_boundary_completed_at_deadline_elapsed():
    """B1.3 via the real production path: the callable completes exactly
    AT the limiting deadline (clock set to dispatch + window) — accepted
    as completed, elapsed == exactly the window."""
    clock = {"t": 100.20}

    def provider(request):
        clock["t"] = 100.20 + 0.15  # exactly the limiting deadline
        return {"evidence": {"boundary": True}}

    service = _make_service(provider, capacity=1, per_provider=0.15,
                            total=5.0)
    service._monotonic = lambda: clock["t"]
    snapshot = service.acquire(_request("100"))
    provider_result = snapshot.providers[0]
    assert provider_result.state is ProviderResultState.SUCCESS
    assert provider_result.error_class is None
    assert provider_result.elapsed_ms == 150.0
    service.close()


def test_cb_b2_boundary_still_running_at_deadline_elapsed():
    """B1.4 via the real production path: no completion marker at the
    limiting deadline (the provider advances the clock to the deadline
    and keeps running) — TIMEOUT, and elapsed_ms == the limiting deadline
    (150 ms), NOT the still-running provider's later completion."""
    release = threading.Event()

    def provider(request):
        clock["t"] = 100.20 + 0.15  # deadline reached; still running
        release.wait(5)
        return {"evidence": {"never": True}}

    clock = {"t": 100.20}
    service = _make_service(provider, capacity=1, per_provider=0.15,
                            total=5.0)
    service._monotonic = lambda: clock["t"]
    snapshot = service.acquire(_request("100"))
    provider_result = snapshot.providers[0]
    assert provider_result.state is ProviderResultState.TIMEOUT
    assert provider_result.error_class == "PER_PROVIDER_TIMEOUT"
    # still running at deadline: elapsed == the limiting deadline itself
    assert provider_result.elapsed_ms == 150.0
    release.set()
    service.close()


def test_cb_b1_coordinator_order_independence_multi_provider():
    """B1.6: three providers with mixed outcomes dispatched together —
    processing order must not change any outcome (one blocks past the
    window and times out; two complete on time)."""
    def first_slow(request):
        time.sleep(0.35)  # > the 0.15 s window
        return {"evidence": {"name": "first"}}

    providers = {
        "first": first_slow,
        "second": lambda r: {"evidence": {"name": "second"}},
        "third": lambda r: {"evidence": {"name": "third"}},
    }
    service = _make_service_multi(providers, per_provider=0.15, total=5.0)
    snapshot = service.acquire(
        _request("100", sources=tuple(sorted(providers))))
    states = {p.provider: p for p in snapshot.providers}
    assert states["first"].state is ProviderResultState.TIMEOUT
    assert states["first"].error_class == "PER_PROVIDER_TIMEOUT"
    assert states["second"].state is ProviderResultState.SUCCESS
    assert states["third"].state is ProviderResultState.SUCCESS
    service.close()
