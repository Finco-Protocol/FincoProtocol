"""P0-B Radar reliability: one bounded coordinator for every live RPC path, per-client
amplification control, collector liveness, collector failure isolation, outage handling."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from app.radar_rwa import collector_health as ch
from app.radar_rwa import r_live_public_acquisition as acq
from app.radar_rwa import r_live_service
from app.radar_rwa.jev_intelligence.config import JevIntelligenceConfig
from app.radar_rwa.jev_intelligence.contracts import JevMode
from app.radar_rwa.jev_intelligence.service import evaluate_intelligence
from app.runtime import client_rate_limit as crl
from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID

IDS = list(APPROVED_BY_CANONICAL_ID)
CID = IDS[0]
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ROBINHOOD_RPC_URL", "https://rpc.example.invalid/")
    monkeypatch.setenv("FINCO_CLIENT_REFRESH_LIMIT_PER_MINUTE", "30")
    crl.reset_client_limiter_for_tests()
    yield
    crl.reset_client_limiter_for_tests()


@pytest.fixture
def small_coordinator(monkeypatch):
    coordinator = acq.PublicAcquisitionCoordinator(process_limit=1, max_coalesced_callers=8)
    monkeypatch.setattr(acq, "PUBLIC_RLIVE_ACQUISITION", coordinator)
    return coordinator


class _Blocker:
    """Fake ``collect_r_live`` that holds the acquisition open and counts real RPC reads."""

    def __init__(self):
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()
        self._lock = threading.Lock()

    def __call__(self, **kwargs):
        with self._lock:
            self.calls += 1
        self.started.set()
        assert self.release.wait(timeout=5)
        return object()


def _subscribe_in_thread(uid, out):
    def run():
        try:
            out.append(("ok", acq.acquire_single_current(uid, "https://rpc.example.invalid/")))
        except Exception as exc:  # noqa: BLE001 - recorded for assertions
            out.append(("err", type(exc).__name__))
    thread = threading.Thread(target=run)
    thread.start()
    return thread


def test_identical_single_asset_requests_coalesce_to_one_rpc(monkeypatch, small_coordinator):
    blocker = _Blocker()
    monkeypatch.setattr(r_live_service, "collect_r_live", blocker)
    monkeypatch.setattr(r_live_service, "collect_aapl_r_live", blocker)
    out: list = []
    first = _subscribe_in_thread(CID, out)
    assert blocker.started.wait(timeout=5)
    peers = [_subscribe_in_thread(CID, out) for _ in range(5)]
    blocker.release.set()
    for thread in [first, *peers]:
        thread.join(timeout=10)
    assert blocker.calls == 1
    assert [kind for kind, _ in out] == ["ok"] * 6


def test_distinct_asset_beyond_capacity_is_typed_busy_not_market_state(monkeypatch, small_coordinator):
    blocker = _Blocker()
    monkeypatch.setattr(r_live_service, "collect_r_live", blocker)
    monkeypatch.setattr(r_live_service, "collect_aapl_r_live", blocker)
    out: list = []
    holder = _subscribe_in_thread(IDS[0], out)
    assert blocker.started.wait(timeout=5)
    with pytest.raises(acq.RLiveServiceBusy):
        acq.acquire_single_current(IDS[1], "https://rpc.example.invalid/")
    blocker.release.set()
    holder.join(timeout=10)
    assert blocker.calls == 1  # the rejected request never reached the RPC


def test_get_r_live_service_reraises_busy_and_maps_failure_to_unavailable(monkeypatch):
    from app.api.v1_1 import institutional

    def busy(*a, **k):
        raise acq.RLiveServiceBusy(acq.R_LIVE_SERVICE_BUSY)

    monkeypatch.setattr(acq, "acquire_single_current", busy)
    with pytest.raises(acq.RLiveServiceBusy):
        institutional.get_r_live(CID)

    def broken(*a, **k):
        raise RuntimeError("rpc exploded https://secret.example/key")

    monkeypatch.setattr(acq, "acquire_single_current", broken)
    state, data = institutional.get_r_live(CID)
    assert state == "UNAVAILABLE" and data == {"reason": "RADAR_AUTHORITY_UNAVAILABLE"}


@pytest.fixture
def client():
    import main_web
    from fastapi.testclient import TestClient
    return TestClient(main_web.app)


def test_public_route_returns_429_service_busy_when_saturated(client, monkeypatch):
    def busy(*a, **k):
        raise acq.RLiveServiceBusy(acq.R_LIVE_SERVICE_BUSY)

    monkeypatch.setattr(acq, "acquire_single_current", busy)
    response = client.get(f"/api/v1.1/radar/r-live/{CID}")
    assert response.status_code == 429
    assert response.json() == {"state": "SERVICE_BUSY", "reason": acq.R_LIVE_SERVICE_BUSY}
    assert response.headers["retry-after"] == "5"


def test_aapl_snapshot_route_uses_coordinator_and_reports_busy(client, monkeypatch):
    def busy(*a, **k):
        raise acq.RLiveServiceBusy(acq.R_LIVE_SERVICE_BUSY)

    monkeypatch.setattr(acq, "acquire_single_current", busy)
    response = client.get("/radar/crypto/rwa/r-live/aapl/snapshot")
    assert response.status_code == 429
    assert response.json()["state"] == "SERVICE_BUSY"


def test_mcp_tool_busy_is_typed_unavailable_not_market_data(monkeypatch):
    from app.mcp.v1 import server

    def busy(*a, **k):
        raise acq.RLiveServiceBusy(acq.R_LIVE_SERVICE_BUSY)

    monkeypatch.setattr(acq, "acquire_single_current", busy)
    result = server.finco_r_live(CID)
    assert "price_usd_per_token" not in str(result) or "None" in str(result)
    assert "SERVICE" in str(result).upper() or "UNAVAILABLE" in str(result).upper()


def test_jev_busy_is_typed_reason_and_makes_exactly_one_canonical_read(monkeypatch):
    calls = {"n": 0}
    from app.api.v1_1 import institutional

    def counting(uid):
        calls["n"] += 1
        return institutional.get_r_live(uid)

    def busy(*a, **k):
        raise acq.RLiveServiceBusy(acq.R_LIVE_SERVICE_BUSY)

    monkeypatch.setattr(acq, "acquire_single_current", busy)
    result = evaluate_intelligence(
        CID, config=JevIntelligenceConfig(mode=JevMode.VISIBLE), current_provider=counting,
        environ={})
    assert result.reason == "R_LIVE_SERVICE_BUSY"
    assert calls["n"] == 1


def test_jev_visible_makes_one_coordinated_rpc_read(monkeypatch, small_coordinator):
    reads = {"n": 0}

    def collect(**kwargs):
        reads["n"] += 1
        raise RuntimeError("upstream down")

    monkeypatch.setattr(r_live_service, "collect_r_live", collect)
    monkeypatch.setattr(r_live_service, "collect_aapl_r_live", collect)
    result = evaluate_intelligence(CID, config=JevIntelligenceConfig(mode=JevMode.VISIBLE), environ={})
    assert result.state.value == "UNAVAILABLE"
    assert reads["n"] == 1  # no second canonical read from JEV


def test_client_limiter_bounds_one_client_without_affecting_others():
    limiter = crl.ClientRateLimiter(limit=2, window_seconds=60, max_keys=3)
    assert limiter.check("f", "a")[0] and limiter.check("f", "a")[0]
    allowed, retry = limiter.check("f", "a")
    assert not allowed and retry >= 1
    assert limiter.check("f", "b")[0]
    for i in range(10):
        limiter.check("f", f"c{i}")
    assert limiter.key_count() <= 3  # memory bounded


def test_client_limiter_window_expires():
    now = [0.0]
    limiter = crl.ClientRateLimiter(limit=1, window_seconds=10, clock=lambda: now[0])
    assert limiter.check("f", "a")[0]
    assert not limiter.check("f", "a")[0]
    now[0] = 11.0
    assert limiter.check("f", "a")[0]


def test_route_rate_limits_repeated_refresh_from_one_client(client, monkeypatch):
    monkeypatch.setenv("FINCO_CLIENT_REFRESH_LIMIT_PER_MINUTE", "2")
    crl.reset_client_limiter_for_tests()
    from app.api.v1_1 import institutional
    monkeypatch.setattr(institutional, "get_r_live", lambda uid: ("UNAVAILABLE", {"reason": "X"}))
    codes = [client.get(f"/api/v1.1/radar/r-live/{CID}").status_code for _ in range(4)]
    assert codes == [200, 200, 429, 429]
    body = client.get(f"/api/v1.1/radar/r-live/{CID}").json()
    assert body == {"state": "RATE_LIMITED", "reason": "CLIENT_RATE_LIMITED"}


def test_invalid_limit_config_is_rejected_without_echoing_value():
    with pytest.raises(ValueError) as info:
        crl._limit_from_env({"FINCO_CLIENT_REFRESH_LIMIT_PER_MINUTE": "banana"})
    assert "banana" not in str(info.value)
    with pytest.raises(ValueError):
        crl._limit_from_env({"FINCO_CLIENT_REFRESH_LIMIT_PER_MINUTE": "0"})


def test_per_client_scope_is_honestly_process_local():
    assert acq.PER_CLIENT_RATE_LIMIT == "PROCESS_LOCAL"
    assert crl.SCOPE == "PROCESS_LOCAL"


# ---- Collector Health liveness (M-7) --------------------------------------------------------

def _snapshot(last_attempt, state=ch.HEALTHY):
    return ch.CollectorHealthSnapshot(
        last_attempt_at=last_attempt.isoformat() if last_attempt else None,
        last_success_at=last_attempt.isoformat() if last_attempt else None,
        batch_outcome="SUCCESS", assets_attempted=3, available_count=3, stale_count=0,
        unavailable_count=0, systemic_failure_reason=None, consecutive_systemic_failures=0,
        health_state=state, updated_at=last_attempt.isoformat() if last_attempt else None)


def test_recent_heartbeat_keeps_stored_health():
    snap = ch.apply_liveness(_snapshot(NOW - timedelta(seconds=120)), now=NOW)
    assert (snap.health_state, snap.liveness) == (ch.HEALTHY, ch.LIVENESS_LIVE)
    assert snap.heartbeat_age_seconds == 120


def test_stopped_scheduler_degrades_then_becomes_unhealthy():
    stale = ch.apply_liveness(_snapshot(NOW - timedelta(seconds=1000)), now=NOW)
    assert (stale.health_state, stale.liveness) == (ch.DEGRADED, ch.LIVENESS_STALE)
    stopped = ch.apply_liveness(_snapshot(NOW - timedelta(hours=3)), now=NOW)
    assert (stopped.health_state, stopped.liveness) == (ch.UNHEALTHY, ch.LIVENESS_STOPPED)
    assert stopped.stored_health_state == ch.HEALTHY  # stored outcome kept for the operator


def test_liveness_never_improves_a_bad_stored_state():
    snap = ch.apply_liveness(_snapshot(NOW - timedelta(seconds=1000), state=ch.UNHEALTHY), now=NOW)
    assert snap.health_state == ch.UNHEALTHY
    live = ch.apply_liveness(_snapshot(NOW, state=ch.DEGRADED), now=NOW)
    assert live.health_state == ch.DEGRADED


def test_missing_or_corrupt_heartbeat_is_never_healthy():
    assert ch.apply_liveness(_snapshot(None), now=NOW).liveness == ch.LIVENESS_UNKNOWN
    bad = ch.replace(_snapshot(NOW), last_attempt_at="not-a-time")
    assert ch.apply_liveness(bad, now=NOW).health_state == ch.UNHEALTHY


def test_readonly_reader_degrades_when_timer_stops(tmp_path):
    db = tmp_path / "h.db"
    with ch.CollectorHealthStore(path=str(db)) as store:
        store.record_attempt(now=NOW)
        store.record_success(attempted=3, available=3, stale=0, unavailable=0, now=NOW)
    assert ch.read_collector_health_readonly(path=str(db), now=NOW + timedelta(minutes=2)).health_state == ch.HEALTHY
    assert ch.read_collector_health_readonly(path=str(db), now=NOW + timedelta(minutes=20)).health_state == ch.DEGRADED
    assert ch.read_collector_health_readonly(path=str(db), now=NOW + timedelta(hours=2)).health_state == ch.UNHEALTHY
    public = ch.read_collector_health_readonly(path=str(db), now=NOW + timedelta(hours=2)).public_dict()
    assert public["liveness"] == ch.LIVENESS_STOPPED


def test_collector_isolates_one_asset_failure(monkeypatch, tmp_path):
    from app.radar_rwa import r_live_collect
    keys = [f"4663:0x{i:040x}" for i in range(3)]
    monkeypatch.setattr(r_live_collect, "APPROVED_BY_CANONICAL_ID", {k: object() for k in keys})
    seen = []

    class _Ledger:
        def close(self):
            return None

    def acquire(*, canonical_asset_id, **kwargs):
        seen.append(canonical_asset_id)
        if canonical_asset_id == keys[0]:
            raise RuntimeError("asset 0 RPC failure")
        raise ValueError("later asset also reachable")

    response, _ = r_live_collect.collect_all_approved(
        rpc_url="https://rpc.example.invalid/", history_factory=lambda **_: _Ledger(),
        rpc_healthcheck=lambda _u: None, acquire=acquire,
        health_factory=lambda: ch.CollectorHealthStore(path=str(tmp_path / "h.db")))
    assert seen == keys  # the first failure did not stop the remaining assets
    assert len(response["results"]) == 3
    assert all(row["state"] == "UNAVAILABLE" for row in response["results"])
