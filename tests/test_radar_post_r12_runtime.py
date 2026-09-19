"""Post-R12 acquisition runtime tests — one acquisition, one immutable
snapshot, one snapshot_id; all reads reuse that exact snapshot.

Deterministic, offline.  No live network anywhere.
"""
from __future__ import annotations

import hashlib
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
    ProviderResult,
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


# ==========================================================================
# Correction A — runtime contract hardening (A1-A5)
# ==========================================================================

from app.radar_runtime.contracts import (
    AcquisitionSnapshot,
    ensure_canonical_evidence,
)

TIMEOUT_WINDOW = 0.2      # per-provider timeout for adversarial timing tests
SLOW_SLEEP = 2.0          # materially longer than the window


def _slow_service(sources, *, per_provider=TIMEOUT_WINDOW,
                  total=10.0, sleep=SLOW_SLEEP):
    calls: list = []

    def slow(request):
        calls.append(request)
        time.sleep(sleep)
        return {"evidence": {"raw": {"price": "1"}}}

    service = _service(
        {name: slow for name in sources},
        config=ServiceConfig(per_provider_timeout_seconds=per_provider,
                             total_budget_seconds=total,
                             max_concurrent_providers=4))
    return service, calls


def test_ca_timeout_01_two_simultaneous_slow_providers_both_timeout():
    service, calls = _slow_service(("a", "b"))
    snapshot = service.acquire(_request(sources=("a", "b")))
    states = {p.provider: p.state for p in snapshot.providers}
    assert states == {"a": ProviderResultState.TIMEOUT,
                      "b": ProviderResultState.TIMEOUT}
    assert len(calls) == 2  # both actually dispatched concurrently


def test_ca_timeout_02_second_provider_gets_no_fresh_window():
    service, _ = _slow_service(("a", "b"))
    snapshot = service.acquire(_request(sources=("a", "b")))
    by_name = {p.provider: p for p in snapshot.providers}
    # dispatch-start deadlines: both must time out within ~one window plus
    # scheduling jitter; a fresh full window after waiting for the first
    # provider would push B to >= 2 * TIMEOUT_WINDOW.
    assert by_name["a"].elapsed_ms < (TIMEOUT_WINDOW * 1000) * 1.9
    assert by_name["b"].elapsed_ms < (TIMEOUT_WINDOW * 1000) * 1.9


def test_ca_timeout_03_elapsed_reflects_bounded_execution_not_wait_order():
    def fast(request):
        return {"evidence": {"ok": True}}

    service, _ = _slow_service(("a", "b", "fast"))
    service._providers["fast"] = fast
    snapshot = service.acquire(_request(sources=("a", "b", "fast")))
    by_name = {p.provider: p for p in snapshot.providers}
    assert by_name["fast"].state is ProviderResultState.SUCCESS
    # processing order must never reset any provider's window
    for name in ("a", "b"):
        assert by_name[name].state is ProviderResultState.TIMEOUT
        assert by_name[name].elapsed_ms < (TIMEOUT_WINDOW * 1000) * 1.9


def test_ca_timeout_04_total_budget_still_caps_operation():
    service, _ = _slow_service(("a", "b"), per_provider=5.0, total=0.25)
    started = time.monotonic()
    snapshot = service.acquire(_request(sources=("a", "b")))
    wall = time.monotonic() - started
    assert wall < 1.5, "total budget must cap the whole operation"
    for provider in snapshot.providers:
        assert provider.state is ProviderResultState.TIMEOUT
        assert provider.error_class == "TOTAL_BUDGET_EXHAUSTED"
    assert snapshot.state is AcquisitionState.UNAVAILABLE


# -- A2: canonical nested provider evidence --------------------------------

def test_ca_evidence_05_nested_set_is_invalid_response():
    service = _service({"lifi": lambda r: {"evidence": {"nested": {1, 2}}}})
    snapshot = service.acquire(_request())
    assert snapshot.providers[0].state is ProviderResultState.INVALID_RESPONSE
    assert snapshot.providers[0].error_class == "EVIDENCE_NOT_CANONICAL"
    assert snapshot.state is AcquisitionState.UNAVAILABLE
    assert snapshot.providers[0].evidence is None  # never stringified


def test_ca_evidence_06_nested_bytes_is_invalid_response():
    service = _service({"lifi": lambda r: {"evidence": {"blob": b"\x00"}}})
    snapshot = service.acquire(_request())
    assert snapshot.providers[0].state is ProviderResultState.INVALID_RESPONSE
    assert snapshot.providers[0].error_class == "EVIDENCE_NOT_CANONICAL"


def test_ca_evidence_07_arbitrary_object_is_invalid_response():
    class Opaque:
        pass

    service = _service({"lifi": lambda r: {"evidence": {"obj": Opaque()}}})
    snapshot = service.acquire(_request())
    assert snapshot.providers[0].state is ProviderResultState.INVALID_RESPONSE
    assert snapshot.providers[0].error_class == "EVIDENCE_NOT_CANONICAL"


def test_ca_evidence_08_invalid_mapping_key_is_invalid_response():
    service = _service({"lifi": lambda r: {"evidence": {1: "v"}}})
    snapshot = service.acquire(_request())
    assert snapshot.providers[0].state is ProviderResultState.INVALID_RESPONSE
    assert snapshot.providers[0].error_class == "EVIDENCE_NOT_CANONICAL"


def test_ca_evidence_09_multilevel_malformation_fails_closed_but_persists():
    def bad(request):
        return {"evidence": {"a": {"b": [{"c": {"d": {"ok": 1,
                                                      "bad": set()}}}]}}}

    store = SnapshotStore(":memory:")
    service = _service({"lifi": bad}, store=store)
    snapshot = service.acquire(_request())
    assert snapshot.providers[0].state is ProviderResultState.INVALID_RESPONSE
    assert snapshot.providers[0].error_class == "EVIDENCE_NOT_CANONICAL"
    # the overall acquisition snapshot still constructs and persists
    # (the service already persisted it; the ledger stays append-only)
    assert store.put(snapshot) == "existing"
    assert store.get(snapshot.snapshot_id).snapshot_id == snapshot.snapshot_id


# -- A3: provider-declared errors are secret-safe --------------------------

def test_ca_logging_10_provider_declared_error_never_leaks_text():
    service = _service({"lifi": lambda r: {
        "error": "Authorization: Bearer SUPER-SECRET-TOKEN"}})
    snapshot = service.acquire(_request())
    provider = snapshot.providers[0]
    assert provider.state is ProviderResultState.PROVIDER_ERROR
    assert provider.error_class == "PROVIDER_DECLARED_ERROR"
    blob = json.dumps(service._events.records)
    assert "SUPER-SECRET-TOKEN" not in blob
    assert "Authorization" not in blob
    assert "Bearer" not in blob


# -- A4: exact ASCII raw-amount contract ------------------------------------

def test_ca_amount_11_whitespace_and_signed_forms_rejected():
    for bad in (" 1000 ", "1000 ", " 1000", "+1000", "-1000", "1.0",
                "1e3", "", "1 000"):
        with pytest.raises(RuntimeContractError):
            _request(raw_amount=bad)


def test_ca_amount_12_unicode_digit_forms_rejected():
    for bad in ("١٢٣", "¹²³", "一二三"):
        with pytest.raises(RuntimeContractError):
            _request(raw_amount=bad)


def test_ca_amount_13_numeric_types_rejected_and_ascii_preserved_exactly():
    for bad in (1000, 10.5, True, [1000], {"raw": 1}, 0):
        with pytest.raises(RuntimeContractError):
            _request(raw_amount=bad)
    request = _request(raw_amount="0001000")  # accepted verbatim
    assert request.raw_amount == "0001000"
    assert request.payload()["rawAmount"] == "0001000"
    assert request.fingerprint == _request(raw_amount="0001000").fingerprint
    assert request.fingerprint != _request(raw_amount="1000").fingerprint


# -- A5: persisted snapshot semantic consistency ----------------------------

def _two_provider_snapshot():
    service = _service({"lifi": _ok_provider(), "oracle": _ok_provider()})
    return service.acquire(_request(sources=("lifi", "oracle")))


def _forged(mutator):
    payload = _two_provider_snapshot().to_payload()
    mutator(payload)
    return AcquisitionSnapshot.from_payload(payload)


def test_ca_consistency_14_wrong_request_fingerprint_rejected():
    def mutate(payload):
        payload["requestFingerprint"] = "acq-req:" + "0" * 64

    with pytest.raises(RuntimeContractError):
        _forged(mutate)


def test_ca_consistency_15_identity_mismatch_rejected():
    def chain(payload):
        payload["chainId"] = 1  # not fingerprint material -> isolates check
    with pytest.raises(RuntimeContractError):
        _forged(chain)

    def address(payload):
        payload["contractAddress"] = "0x" + "9" * 40
    with pytest.raises(RuntimeContractError):
        _forged(address)

    with_uid = AcquisitionService(
        SnapshotStore(":memory:"),
        {"lifi": _ok_provider()},
        config=ServiceConfig(per_provider_timeout_seconds=2.0,
                             total_budget_seconds=5.0,
                             max_concurrent_providers=2),
        event_logger=RuntimeEventLogger(), clock=lambda: NOW,
    ).acquire(_request(economic_asset_uid="AAPL"))
    payload = with_uid.to_payload()
    payload["economicAssetUid"] = "MSFT"
    with pytest.raises(RuntimeContractError):
        AcquisitionSnapshot.from_payload(payload)


def test_ca_consistency_16_provider_set_mismatch_rejected():
    def missing(payload):
        payload["providers"] = [p for p in payload["providers"]
                                if p["provider"] != "oracle"]
    with pytest.raises(RuntimeContractError):
        _forged(missing)

    def duplicate(payload):
        payload["providers"].append(dict(payload["providers"][0]))
    with pytest.raises(RuntimeContractError):
        _forged(duplicate)

    def invented(payload):
        payload["providers"].append({
            "provider": "invented", "state": "SUCCESS", "elapsedMs": 1.0,
            "evidence": {"a": 1}, "observedAt": None, "errorClass": None})
    with pytest.raises(RuntimeContractError):
        _forged(invented)


def test_ca_consistency_17_forged_aggregate_state_rejected():
    def forged_complete(payload):
        payload["providers"][1]["state"] = "TIMEOUT"
        payload["providers"][1]["errorClass"] = "PER_PROVIDER_TIMEOUT"
        payload["state"] = "COMPLETE"
    with pytest.raises(RuntimeContractError):
        _forged(forged_complete)

    def forged_partial(payload):
        payload["state"] = "PARTIAL"  # every provider SUCCESS in fixture
    with pytest.raises(RuntimeContractError):
        _forged(forged_partial)


def test_ca_consistency_18_honest_payloads_still_reconstruct():
    snapshot = _two_provider_snapshot()
    rebuilt = AcquisitionSnapshot.from_payload(snapshot.to_payload())
    assert rebuilt.snapshot_id == snapshot.snapshot_id
    assert rebuilt.state is AcquisitionState.COMPLETE


# ==========================================================================
# Correction B — final runtime contract closure (B1-B5)

def _digest(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True,
                                     separators=(",", ":"),
                                     ensure_ascii=False)
                          .encode("utf-8")).hexdigest()
# ==========================================================================

def test_cb_timeout_01_budget_limited_is_total_budget_exhausted():
    # B1: when the total budget is the limiting deadline, the wait expires
    # because of THAT deadline — never misclassified as the provider's.
    service, _ = _slow_service(("a", "b"), per_provider=5.0, total=0.25)
    snapshot = service.acquire(_request(sources=("a", "b")))
    for provider in snapshot.providers:
        assert provider.state is ProviderResultState.TIMEOUT
        assert provider.error_class == "TOTAL_BUDGET_EXHAUSTED"
        assert provider.error_class != "PER_PROVIDER_TIMEOUT"


def test_cb_timeout_02_provider_limited_is_per_provider_timeout():
    # B1: the provider-window-limited case keeps exactly
    # PER_PROVIDER_TIMEOUT.
    service, _ = _slow_service(("a", "b"), per_provider=TIMEOUT_WINDOW,
                               total=10.0)
    snapshot = service.acquire(_request(sources=("a", "b")))
    for provider in snapshot.providers:
        assert provider.state is ProviderResultState.TIMEOUT
        assert provider.error_class == "PER_PROVIDER_TIMEOUT"
        assert provider.error_class != "TOTAL_BUDGET_EXHAUSTED"


def test_cb_timeout_03_classification_is_deadline_based_not_order_based():
    # Mixed request: the fast provider succeeds, the slow ones expire.
    # Each timeout code is determined by its own deadline comparison,
    # independent of the coordinator's processing order.
    def fast(request):
        return {"evidence": {"ok": True}}

    service, _ = _slow_service(("a", "zslow", "fast"),
                               per_provider=TIMEOUT_WINDOW, total=0.35)
    service._providers["fast"] = fast
    snapshot = service.acquire(_request(sources=("a", "zslow", "fast")))
    by_name = {p.provider: p for p in snapshot.providers}
    assert by_name["fast"].state is ProviderResultState.SUCCESS
    for name in ("a", "zslow"):
        assert by_name[name].state is ProviderResultState.TIMEOUT
        assert by_name[name].error_class == "PER_PROVIDER_TIMEOUT"


def test_cb_evidence_04_success_requires_canonical_evidence():
    # B2: SUCCESS + evidence=None -> typed contract violation
    with pytest.raises(RuntimeContractError):
        ProviderResult(provider="lifi", state=ProviderResultState.SUCCESS,
                       elapsed_ms=1.0, evidence=None)
    # SUCCESS + malformed evidence -> typed contract violation
    with pytest.raises(RuntimeContractError):
        ProviderResult(provider="lifi", state=ProviderResultState.SUCCESS,
                       elapsed_ms=1.0, evidence={"bad": {1, 2}})
    # SUCCESS + canonical Mapping -> valid (empty Mapping is canonical)
    ProviderResult(provider="lifi", state=ProviderResultState.SUCCESS,
                   elapsed_ms=1.0, evidence={})


def test_cb_evidence_05_persisted_success_without_evidence_rejected():
    # B2: a COMPLETE persisted snapshot with a SUCCESS provider carrying
    # no evidence must be impossible.
    def mutate(payload):
        payload["providers"][0]["evidence"] = None
        payload["providers"][0]["state"] = "SUCCESS"
        payload["providers"][1]["evidence"] = None
        payload["providers"][1]["state"] = "SUCCESS"
        payload["state"] = "COMPLETE"

    with pytest.raises(RuntimeContractError):
        _forged(mutate)


def test_cb_error_field_06_malformed_error_field_fails_closed():
    bad_values = (
        {"unexpected": "shape"}, ["x"], 5, True, 1.5, b"x", "", "   ")
    for bad in bad_values:
        service = _service({"lifi": lambda r, bad=bad: {
            "error": bad, "evidence": {"price": "1"}}})
        snapshot = service.acquire(_request())
        provider = snapshot.providers[0]
        assert provider.state is ProviderResultState.INVALID_RESPONSE, bad
        assert provider.error_class == "ERROR_FIELD_MALFORMED"
        assert provider.state is not ProviderResultState.SUCCESS
        blob = json.dumps(service._events.records)
        assert "unexpected" not in blob  # raw malformed value never logged


def test_cb_error_field_07_absent_or_none_error_is_valid_no_error():
    for no_error in ({"evidence": {"price": "1"}},
                     {"error": None, "evidence": {"price": "1"}}):
        service = _service({"lifi": lambda r, n=no_error: n})
        snapshot = service.acquire(_request())
        assert snapshot.providers[0].state is ProviderResultState.SUCCESS
        assert snapshot.providers[0].error_class is None


def test_cb_request_08_persisted_request_contract_enforced():
    # B4: a persisted request payload carrying a fingerprint recomputed
    # over its own (contract-violating) content is still rejected —
    # from_payload applies the live construction contract, not just
    # content hashing.
    def forged(mutator):
        payload = _two_provider_snapshot().to_payload()
        mutator(payload["request"])
        payload["requestFingerprint"] = "acq-req:" + _digest(
            payload["request"])
        return AcquisitionSnapshot.from_payload(payload)

    with pytest.raises(RuntimeContractError):
        forged(lambda request: request.update(direction="SIDEWAYS"))
    with pytest.raises(RuntimeContractError):
        forged(lambda request: request.update(rawAmount=" 1000"))
    with pytest.raises(RuntimeContractError):
        forged(lambda request: request.update(sources=["lifi", "lifi",
                                                      "oracle"]))
    with pytest.raises(RuntimeContractError):
        forged(lambda request: request.update(chainId="4663"))
    with pytest.raises(RuntimeContractError):
        forged(lambda request: request.update(notionalUsd="1e3"))
    with pytest.raises(RuntimeContractError):
        forged(lambda request: request.update(schemaVersion="other-v9"))


def test_cb_request_09_honest_persisted_request_reconstructs():
    snapshot = _two_provider_snapshot()
    request_payload = snapshot.to_payload()["request"]
    request = AcquisitionRequest.from_payload(request_payload)
    assert request.fingerprint == snapshot.request_fingerprint
    assert request.chain_id == 4663
    assert request.direction == "BUY"
    assert request.sources == ("lifi", "oracle")


def test_cb_state_10_unknown_persisted_provider_state_typed_rejection():
    def mutate(payload):
        payload["providers"][0]["state"] = "MADE_UP_STATE"

    with pytest.raises(RuntimeContractError) as excinfo:
        _forged(mutate)
    assert type(excinfo.value) is RuntimeContractError  # not a raw ValueError


def test_cb_state_11_missing_provider_state_typed_rejection():
    def mutate(payload):
        del payload["providers"][0]["state"]

    with pytest.raises(RuntimeContractError) as excinfo:
        _forged(mutate)
    assert type(excinfo.value) is RuntimeContractError
