"""Post-R12 acquisition runtime tests — one acquisition, one immutable
snapshot, one snapshot_id; all reads reuse that exact snapshot.

Deterministic, offline.  No live network anywhere.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from app.radar_runtime.cache import AcquisitionCache
from app.radar_runtime.contracts import (
    AcquisitionRequest,
    AcquisitionState,
    ProviderResultState,
    RadarRuntimeError,
    RuntimeContractError,
)
from app.radar_runtime.observability import RuntimeEventLogger
from app.radar_runtime.service import AcquisitionService, ServiceConfig
from app.radar_runtime.snapshot_store import SnapshotStore

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def _request(**over) -> AcquisitionRequest:
    args = dict(
        chain_id=4663,
        contract_address="0x1111111111111111111111111111111111111111",
        direction="BUY",
        sources=("lifi",),
        raw_amount="1000",
    )
    args.update(over)
    return AcquisitionRequest(**args)


def _service(providers, *, store=None, cache=None, config=None):
    return AcquisitionService(
        store or SnapshotStore(":memory:"),
        providers,
        cache=cache,
        config=config or ServiceConfig(
            per_provider_timeout_seconds=2.0,
            total_budget_seconds=5.0,
            max_concurrent_providers=4),
        event_logger=RuntimeEventLogger(),
        clock=lambda: NOW,
    )


def _ok_provider(evidence=None, observed_at="2026-09-19T11:59:00+00:00",
                 calls=None):
    def provider(request):
        if calls is not None:
            calls.append(request)
        return {"evidence": evidence or {"raw": {"price": "1"}},
                "observedAt": observed_at}
    return provider


# --------------------------------------------------------------------------
# P3 — request fingerprint contract
# --------------------------------------------------------------------------

def test_p3_01_fingerprint_stable_and_prefixed():
    a, b = _request(), _request()
    assert a.fingerprint == b.fingerprint
    assert a.fingerprint.startswith("acq-req:")
    assert len(a.fingerprint) == len("acq-req:") + 64


def test_p3_02_chain_or_address_change_changes_fingerprint():
    base = _request()
    assert _request(chain_id=1).fingerprint != base.fingerprint
    assert _request(
        contract_address="0x2222222222222222222222222222222222222222"
    ).fingerprint != base.fingerprint


def test_p3_03_amount_or_direction_change_changes_fingerprint():
    base = _request()
    assert _request(raw_amount="2000").fingerprint != base.fingerprint
    assert _request(direction="SELL").fingerprint != base.fingerprint


def test_p3_04_ticker_free_identity_is_canonical():
    # identity fields bind the request; provider set and purpose too
    assert _request(sources=("coingecko",)).fingerprint != _request().fingerprint
    assert _request(purpose="inspector").fingerprint != _request().fingerprint


# --------------------------------------------------------------------------
# P4/P6 — one acquisition -> one snapshot_id
# --------------------------------------------------------------------------

def test_p4_05_one_acquire_produces_one_snapshot_and_one_provider_call():
    calls: list = []
    service = _service({"lifi": _ok_provider(calls=calls)})
    snapshot = service.acquire(_request())
    assert snapshot.snapshot_id.startswith("acq-snap:")
    assert len(calls) == 1
    assert snapshot.state is AcquisitionState.COMPLETE
    # second read of the SAME request via cache must not reacquire
    again = service.acquire(_request())
    assert again.snapshot_id == snapshot.snapshot_id
    assert len(calls) == 1


def test_p4_06_snapshot_id_is_content_addressed_and_changes_with_content():
    service = _service({"lifi": _ok_provider(evidence={"raw": {"price": "1"}})})
    s1 = service.acquire(_request())
    # different immutable content -> different snapshot id
    s2 = _service({"lifi": _ok_provider(
        evidence={"raw": {"price": "2"}})}).acquire(_request())
    assert s1.snapshot_id != s2.snapshot_id
    material = s1.to_payload()
    import hashlib
    assert s1.snapshot_id == "acq-snap:" + hashlib.sha256(json.dumps(
        material, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# P8 — durable append-only store
# --------------------------------------------------------------------------

def test_p8_07_roundtrip_and_reopen_persist_exactly(tmp_path):
    db = str(tmp_path / "runtime.db")
    store = SnapshotStore(db)
    service = _service({"lifi": _ok_provider()}, store=store)
    snapshot = service.acquire(_request())

    reopened = SnapshotStore(db)
    read = reopened.get(snapshot.snapshot_id)
    assert read is not None
    assert read.snapshot_id == snapshot.snapshot_id
    assert read.to_payload() == snapshot.to_payload()
    assert read.providers[0].evidence["raw"]["price"] == "1"
    assert read.request["chainId"] == 4663


def test_p8_08_duplicate_identical_insert_is_idempotent():
    store = SnapshotStore(":memory:")
    service = _service({"lifi": _ok_provider()}, store=store)
    snapshot = service.acquire(_request())
    assert store.put(snapshot) == "existing"  # identical insert idempotent
    with store._lock:
        count = store._conn.execute(
            "SELECT COUNT(*) c FROM acquisition_snapshots").fetchone()["c"]
    assert count == 1


def test_p8_09_same_id_different_payload_is_hard_failure(tmp_path):
    db = str(tmp_path / "runtime.db")
    store = SnapshotStore(db)
    service = _service({"lifi": _ok_provider()}, store=store)
    snapshot = service.acquire(_request())
    # forge: same id, different stored payload -> hard failure on put
    conn = sqlite3.connect(db)
    conn.execute("UPDATE acquisition_snapshots SET payload = ? WHERE "
                 "snapshot_id = ?", ('{"tampered": true}', snapshot.snapshot_id))
    conn.commit()
    conn.close()
    with pytest.raises(RadarRuntimeError, match="conflict"):
        store.put(snapshot)
    # and a corrupted ledger row fails closed on read
    conn = sqlite3.connect(db)
    conn.execute("UPDATE acquisition_snapshots SET payload = ? WHERE "
                 "snapshot_id = ?", ('{"schemaVersion": "other"}',
                                    snapshot.snapshot_id))
    conn.commit()
    conn.close()
    with pytest.raises(RadarRuntimeError):
        store.get(snapshot.snapshot_id)


# --------------------------------------------------------------------------
# P9 — runtime cache semantics
# --------------------------------------------------------------------------

def test_p9_10_cache_hit_does_not_call_provider_again():
    calls: list = []
    service = _service({"lifi": _ok_provider(calls=calls)})
    s1 = service.acquire(_request())
    s2 = service.acquire(_request())
    assert s1.snapshot_id == s2.snapshot_id
    assert len(calls) == 1
    hits = [r for r in service._events.records if r.get("cache") == "HIT"]
    assert hits


def test_p9_11_expired_cache_causes_reacquisition():
    calls: list = []
    service = _service(
        {"lifi": _ok_provider(calls=calls)},
        cache=AcquisitionCache(ttl_seconds=0.05))
    s1 = service.acquire(_request())
    time.sleep(0.08)
    s2 = service.acquire(_request())
    assert len(calls) == 2
    assert s1.snapshot_id != s2.snapshot_id  # new composition time


def test_p9_12_cache_never_touches_provider_observed_at():
    provider_ts = "2026-09-19T11:00:00+00:00"
    calls: list = []
    service = _service(
        {"lifi": _ok_provider(observed_at=provider_ts, calls=calls)},
        cache=AcquisitionCache(ttl_seconds=3600))
    s1 = service.acquire(_request())
    s2 = service.acquire(_request())  # served from cache
    assert s1.providers[0].observed_at == provider_ts
    assert s2.providers[0].observed_at == provider_ts
    assert s1.to_payload()["providers"][0]["observedAt"] == provider_ts
    assert s1.to_payload() == s2.to_payload()


# --------------------------------------------------------------------------
# P14 — read path is network-free
# --------------------------------------------------------------------------

def test_p14_13_get_snapshot_performs_zero_network_calls():
    calls: list = []

    def provider(request):  # would explode the counter if ever called
        calls.append(request)
        return {"evidence": {}}

    service = _service({"lifi": provider})
    snapshot = service.acquire(_request())
    before = len(calls)
    # downstream rendering/inspector reads, repeatedly
    for _ in range(5):
        read = service.get_snapshot(snapshot.snapshot_id)
        assert read.to_payload() == snapshot.to_payload()
    read_model = read.to_payload()  # serializer from snapshot only
    assert read_model["state"] == "COMPLETE"
    assert len(calls) == before


def test_p14_14_read_service_without_providers_still_reads():
    store = SnapshotStore(":memory:")
    writer = _service({"lifi": _ok_provider()}, store=store)
    snapshot = writer.acquire(_request())
    reader = AcquisitionService(store, None)  # production read path
    assert reader.get_snapshot(snapshot.snapshot_id).snapshot_id == (
        snapshot.snapshot_id)


# --------------------------------------------------------------------------
# P7 — single-flight
# --------------------------------------------------------------------------

def test_p7_15_concurrent_identical_requests_acquire_exactly_once():
    calls: list = []
    start = threading.Event()

    def slow_provider(request):
        calls.append(request)
        time.sleep(0.25)
        return {"evidence": {"n": 1}}

    service = _service({"lifi": slow_provider})
    results: list = []

    def run():
        start.wait()
        results.append(service.acquire(_request()))

    threads = [threading.Thread(target=run) for _ in range(4)]
    for t in threads:
        t.start()
    start.set()
    for t in threads:
        t.join(5)
    assert len(calls) == 1, "provider acquisition must execute exactly once"
    assert len({s.snapshot_id for s in results}) == 1
    reused = [r for r in service._events.records
              if r.get("single_flight") == "reused"]
    assert reused


def test_p7_16_different_requests_do_not_single_flight_together():
    calls: list = []
    service = _service({"lifi": _ok_provider(calls=calls)})
    s1 = service.acquire(_request(raw_amount="1000"))
    s2 = service.acquire(_request(raw_amount="2000"))
    assert len(calls) == 2
    assert s1.snapshot_id != s2.snapshot_id


# --------------------------------------------------------------------------
# P10/P12 — timeouts, budget, typed states, partial honesty
# --------------------------------------------------------------------------

def test_p10_17_provider_timeout_produces_typed_runtime_state():
    def slow(request):
        time.sleep(5)
        return {"evidence": {}}

    service = _service({"lifi": slow}, config=ServiceConfig(
        per_provider_timeout_seconds=0.05,
        total_budget_seconds=5.0,
        max_concurrent_providers=2))
    snapshot = service.acquire(_request())
    assert snapshot.state is AcquisitionState.UNAVAILABLE
    assert snapshot.providers[0].state is ProviderResultState.TIMEOUT
    assert snapshot.providers[0].error_class == "PER_PROVIDER_TIMEOUT"


def test_p12_18_partial_failure_is_not_fabricated_complete():
    def good(request):
        return {"evidence": {"raw": {"price": "1"}}}

    def bad(request):
        raise OSError("transport down")

    service = _service({"lifi": good, "oracle": bad})
    snapshot = service.acquire(_request(sources=("lifi", "oracle")))
    assert snapshot.state is AcquisitionState.PARTIAL
    states = {p.provider: p.state for p in snapshot.providers}
    assert states["lifi"] is ProviderResultState.SUCCESS
    assert states["oracle"] is ProviderResultState.TRANSPORT_ERROR
    assert states["oracle"] != ProviderResultState.SUCCESS


def test_p12_19_successful_evidence_preserved_during_other_failure():
    def good(request):
        return {"evidence": {"raw": {"price": "42"}},
                "observedAt": "2026-09-19T10:00:00+00:00"}

    def failing(request):
        return {"error": "upstream unavailable"}

    service = _service({"lifi": good, "oracle": failing})
    snapshot = service.acquire(_request(sources=("lifi", "oracle")))
    lifi = next(p for p in snapshot.providers if p.provider == "lifi")
    oracle = next(p for p in snapshot.providers if p.provider == "oracle")
    assert lifi.evidence == {"raw": {"price": "42"}}
    assert lifi.observed_at == "2026-09-19T10:00:00+00:00"
    assert oracle.state is ProviderResultState.PROVIDER_ERROR
    assert snapshot.state is AcquisitionState.PARTIAL


def test_p12_20_malformed_provider_result_fails_closed():
    for bad in ("not-a-mapping", {"noEvidence": 1},
                {"evidence": "not-a-mapping"}):
        service = _service({"lifi": lambda request: bad})
        snapshot = service.acquire(_request())
        assert snapshot.state is AcquisitionState.UNAVAILABLE
        assert snapshot.providers[0].state is (
            ProviderResultState.INVALID_RESPONSE)


# --------------------------------------------------------------------------
# P5 — evidence vs request distinction
# --------------------------------------------------------------------------

def test_p5_21_request_and_provider_evidence_remain_distinguishable():
    service = _service({"lifi": _ok_provider(evidence={"raw": {"amount": "7"}})})
    snapshot = service.acquire(_request(raw_amount="1000"))
    assert snapshot.request["rawAmount"] == "1000"          # requested
    assert snapshot.providers[0].evidence["raw"]["amount"] == "7"  # observed
    assert snapshot.request["rawAmount"] != (
        snapshot.providers[0].evidence["raw"]["amount"])
    assert snapshot.chain_id == 4663          # chain identity preserved
    assert snapshot.contract_address.endswith("1111")


# --------------------------------------------------------------------------
# P13 — observability / correlation
# --------------------------------------------------------------------------

def test_p13_22_correlation_id_propagates_and_logs_stay_whitelisted():
    def leaky_provider(request):
        # secrets in payload/config must never reach the log records
        return {"evidence": {"apiKey": "SUPER-SECRET",
                             "authorization": "Bearer x"}}

    service = _service(
        {"lifi": leaky_provider},
        config=ServiceConfig(per_provider_timeout_seconds=2.0,
                             total_budget_seconds=5.0,
                             max_concurrent_providers=2))
    snapshot = service.acquire(
        _request(provider_config={"apiToken": "SECRET-TOKEN"}))
    assert snapshot.runtime_metadata["correlationId"]
    records = service._events.records
    assert records
    for record in records:
        blob = json.dumps(record)
        assert record["correlation_id"] == (
            snapshot.runtime_metadata["correlationId"]) or (
            record.get("event") == "acquisition.cache_hit")
        for secret in ("SUPER-SECRET", "Bearer x", "SECRET-TOKEN"):
            assert secret not in blob
        assert set(record) <= {
            "event", "correlation_id", "request_fingerprint", "snapshot_id",
            "provider", "result_state", "elapsed_ms", "cache",
            "single_flight", "error_class"}


# --------------------------------------------------------------------------
# Read-model / immutability extras
# --------------------------------------------------------------------------

def test_p4_23_immutable_snapshot_object_resists_mutation():
    snapshot = _service({"lifi": _ok_provider()}).acquire(_request())
    with pytest.raises(Exception):
        snapshot.chain_id = 1  # frozen dataclass
    with pytest.raises(TypeError):
        snapshot.providers[0].evidence["raw"]["price"] = "tampered"


def test_p14_24_read_model_rendering_does_not_reacquire():
    calls: list = []

    class DownstreamView:
        """Example read-model: consumes ONLY snapshot_id + service reads."""
        def __init__(self, service):
            self._service = service
            self.snapshot_id = None

        def render(self, snapshot_id):
            self.snapshot_id = snapshot_id
            snap = self._service.get_snapshot(self.snapshot_id)
            return snap.to_payload()["state"]

    service = _service({"lifi": _ok_provider(calls=calls)})
    snapshot = service.acquire(_request())
    view = DownstreamView(service)
    assert view.render(snapshot.snapshot_id) == "COMPLETE"
    assert view.render(snapshot.snapshot_id) == "COMPLETE"
    assert len(calls) == 1  # rendering never reacquires


def test_p16_25_runtime_imports_zero_frozen_authority_modules():
    # The productization runtime must be decoupled from frozen R0-R12
    # authority: provider integration is composition-time wiring only.
    import ast
    import pathlib
    root = pathlib.Path("app/radar_runtime")
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("finco"), (
                        f"{path}: imports frozen authority {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not module.startswith("finco"), (
                    f"{path}: imports frozen authority {module}")
