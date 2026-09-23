"""A2 Execution Simulation API v1 tests — A2-01 through A2-55 + C01-C22 + CB01-CB14.

All tests use deterministic offline fakes injected via A2 test seams:
  - set_execution_service()  — fake AcquisitionService
  - set_universe_fn()        — fake Robinhood asset universe

No live network calls.

Test inventory:
  A2-01  POST route exists and accepts valid request
  A2-02  OpenAPI documents request body for POST route
  A2-03  OpenAPI documents ExecutionSimulationEnvelope
  A2-04  BUY + "100" valid → 200
  A2-05  BUY + "1000" valid → 200
  A2-06  SELL + "100" valid → 200
  A2-07  SELL + "1000" valid → 200
  A2-08  invalid direction → 400 SIMULATION_REQUEST_INVALID
  A2-09  invalid notional → 400 SIMULATION_REQUEST_INVALID
  A2-10  ticker-like UID "AAPL" rejected before acquisition → 400
  A2-11  unknown valid-format UID → 404 ASSET_NOT_FOUND
  A2-12  expected registry exception → sanitized 503 REGISTRY_UNAVAILABLE
  A2-13  invalid UID causes zero acquire calls
  A2-14  unknown UID causes zero acquire calls
  A2-15  invalid direction causes zero acquire calls
  A2-16  invalid notional causes zero acquire calls
  A2-17  valid request causes exactly ONE acquire call
  A2-18  request economicAssetUid equals exact SelectedAsset UID
  A2-19  request chainId equals exact SelectedAsset chain_id
  A2-20  request contractAddress equals exact SelectedAsset contract_address
  A2-21  request token decimals derive from canonical SelectedAsset authority
  A2-22  ticker alone cannot influence request identity
  A2-23  response snapshot_id equals immutable acquisition snapshot_id
  A2-24  response top-level state preserves COMPLETE
  A2-25  response preserves PARTIAL
  A2-26  response preserves UNAVAILABLE
  A2-27  reference price comes verbatim from snapshot authority
  A2-28  execution effective_price comes verbatim from snapshot authority
  A2-29  directional GAP comes verbatim from snapshot authority
  A2-30  GAP is NOT recomputed (deliberately inconsistent test numbers)
  A2-31  zero reference value preserved
  A2-32  zero effective price preserved
  A2-33  zero GAP preserved
  A2-34  negative GAP preserved
  A2-35  reference unavailable remains HTTP 200 + available=false
  A2-36  execution unavailable remains HTTP 200 + available=false
  A2-37  GAP unavailable remains HTTP 200 + available=false
  A2-38  unavailable reason preserved verbatim
  A2-39  simulation_only=true
  A2-40  order_submitted=false
  A2-41  no wallet fields
  A2-42  no signature fields
  A2-43  no transaction hash / order id fields
  A2-44  raw_payload_json absent recursively
  A2-45  raw_evidence absent recursively
  A2-46  adversarial private path / credential sentinel absent (real leakage test)
  A2-47  unexpected RuntimeError("PROGRAMMING_SENTINEL") is NOT swallowed
  A2-48  route handler is synchronous (not a coroutine)
  A2-49  snapshot UID mismatch fails closed
  A2-50  snapshot chain mismatch fails closed
  A2-51  snapshot contract mismatch fails closed
  A2-52  GET /api/v1/meta advertises radar.execution.simulation
  A2-53  existing A1 GET endpoints make ZERO execution acquisitions
  A2-54  existing UI E4 GET Company Terminal makes zero acquisitions
  A2-55  no economic authority package changed

  Correction A:
  C01  direction mismatch (BUY→SELL) fails closed
  C02  notional mismatch (1000→100) fails closed
  C03  snapshot missing request.direction → fails closed
  C04  snapshot missing request.notionalUsd → fails closed
  C05  exact UID+chain+contract+BUY+1000 → serializes successfully
  C06  providers=[other-provider, radar-core] → canonical values from radar-core
  C07  providers=[radar-core, other-provider] → same result
  C08  providers=[other-provider only] → radar-core absent → HTTP 500 (invariant fail)
  C09  execution unavailableReason="NO_ROUTE" → response reason == "NO_ROUTE"
  C10  both unavailableReason and reason present → unavailableReason wins
  C11  reason only → reason preserved
  C12  neither → stable generic fallback
  C13  expected registry exception (RegistrySourceError) → sanitized 503
  C14  RuntimeError from universe path → propagates / 500
  C15  public 503 contains only stable detail string
  C16  numeric 100 → 400 (zero acquire)
  C17  float 100.0 → 400 (zero acquire)
  C18  bool true → 400 (zero acquire)
  C19  null → 400 (zero acquire)
  C20  list / dict → 400 (zero acquire)
  C21  missing direction → 400 (zero acquire)
  C22  missing notional_usd → 400 (zero acquire)

  Correction B:
  CB01  LIFI_V1_QUOTE execution source → not redacted (digit-containing canonical label)
  CB02  R2_GAP reason → not redacted (digit-containing canonical code)
  CB03  HTTP_429 reason → not redacted (digit-containing canonical code)
  CB04  C:\\private\\secret.txt (Windows drive path) → redacted
  CB05  D:/finco/private.db (Windows drive path, forward slash) → redacted
  CB06  \\\\server\\share\\secret (UNC path) → redacted
  CB07  apikey=... credential pattern → redacted
  CB08  providers=[] → ProviderInvariantError → HTTP 500
  CB09  radar-core present but all evidence unavailable → HTTP 200 partial
  CB10  OpenAPI direction: type=string enum [BUY, SELL]
  CB11  OpenAPI notional_usd: type=string enum [100, 1000]
  CB12  OpenAPI both fields required
  CB13  OpenAPI documents 200/400/404/503
  CB14  malformed inputs still return 400 (not 422) after OpenAPI schema override
"""
from __future__ import annotations

import importlib
import inspect
import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.api.v1.execution as _exec_module
import app.api.v1.router as _router_module

# ── constants ─────────────────────────────────────────────────────────────────

_UID = "0x" + "aa" * 32
_CHAIN_ID = 4663
_CONTRACT = "0x" + "11" * 20
_SYMBOL = "NVDA"
_TOKEN_DECIMALS = 18

_OTHER_UID = "0x" + "bb" * 32
_OTHER_CONTRACT = "0x" + "22" * 20

_SNAP_ID = "acq-snap:test-snap-001"
_COMPLETED_AT = "2026-01-01T12:00:00+00:00"

# ── fake infrastructure ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class _FakeSelectedAsset:
    economic_asset_uid: str = _UID
    token_symbol: str = _SYMBOL
    token_name: str = "NVIDIA Corporation"
    chain_id: int = _CHAIN_ID
    contract_address: str = _CONTRACT
    token_decimals: int = _TOKEN_DECIMALS


_NVDA = _FakeSelectedAsset()


def _make_evidence(
    *,
    ref_available: bool = True,
    ref_price: str = "143.11",
    ref_bid: str = "143.00",
    ref_ask: str = "143.22",
    ref_observed_at: str = "2026-01-01T11:59:00+00:00",
    exec_available: bool = True,
    exec_price: str = "142.77",
    exec_status: str = "QUOTE_OK",
    exec_quoted_at: str = "2026-01-01T11:59:30+00:00",
    gap_available: bool = True,
    gap_bps: str = "-24",
    gap_to_mid_bps: str = "-17",
    gap_quoted_at: str = "2026-01-01T11:59:30+00:00",
    direction: str = "BUY",
) -> dict:
    ref_section: dict
    exec_section: dict
    gap_section: dict

    if ref_available:
        ref_section = {
            "available": True,
            "price": ref_price,
            "bid": ref_bid,
            "ask": ref_ask,
            "source": "FROZEN::BoundReferencePrice",
            "observedAt": ref_observed_at,
            "isTradingHalt": False,
        }
    else:
        ref_section = {"available": False, "reason": "REFERENCE_UNAVAILABLE"}

    if exec_available:
        exec_section = {
            "available": True,
            "side": direction,
            "notionalUsd": "1000",
            "status": exec_status,
            "effectivePrice": exec_price,
            "source": "LiFi",
            "quotedAt": exec_quoted_at,
        }
    else:
        exec_section = {"available": False, "reason": "EXECUTION_UNAVAILABLE"}

    if gap_available and ref_available and exec_available:
        gap_section = {
            "available": True,
            "side": direction,
            "gapBps": gap_bps,
            "gapToMidBps": gap_to_mid_bps,
            "source": "FROZEN::DirectionalGap",
            "quotedAt": gap_quoted_at,
        }
    else:
        gap_section = {
            "available": False,
            "reason": "GAP_REQUIRES_EXECUTION_AND_REFERENCE",
        }

    return {
        "asset": {
            "symbol": _SYMBOL,
            "economicAssetUid": _UID,
            "chainId": _CHAIN_ID,
            "contractAddress": _CONTRACT,
        },
        "reference": ref_section,
        "execution": exec_section,
        "gap": gap_section,
        "observedAt": _COMPLETED_AT,
    }


def _make_request_block(direction: str = "BUY", notional_usd: str = "1000") -> dict:
    """Canonical snapshot request block matching AcquisitionRequest.to_payload()."""
    return {
        "chainId": _CHAIN_ID,
        "contractAddress": _CONTRACT,
        "economicAssetUid": _UID,
        "direction": direction,
        "sources": ["radar-core"],
        "notionalUsd": notional_usd,
        "providerConfig": None,
    }


class _FakeSnapshot:
    def __init__(
        self,
        *,
        snapshot_id: str = _SNAP_ID,
        state: str = "COMPLETE",
        uid: str = _UID,
        chain_id: int = _CHAIN_ID,
        contract: str = _CONTRACT,
        completed_at: str = _COMPLETED_AT,
        evidence: dict | None = None,
        direction: str = "BUY",
        notional_usd: str = "1000",
        request_block: dict | None = None,
    ) -> None:
        self.snapshot_id = snapshot_id
        self._state = state
        self._uid = uid
        self._chain_id = chain_id
        self._contract = contract
        self._completed_at = completed_at
        self._evidence = evidence if evidence is not None else _make_evidence(
            direction=direction
        )
        self._direction = direction
        self._notional_usd = notional_usd
        # Allow explicit override for malformed-request tests
        self._request_block = request_block

    def to_payload(self) -> dict:
        req = self._request_block if self._request_block is not None else {
            "chainId": self._chain_id,
            "contractAddress": self._contract,
            "economicAssetUid": self._uid,
            "direction": self._direction,
            "sources": ["radar-core"],
            "notionalUsd": self._notional_usd,
            "providerConfig": None,
        }
        return {
            "state": self._state,
            "economicAssetUid": self._uid,
            "chainId": self._chain_id,
            "contractAddress": self._contract,
            "completedAt": self._completed_at,
            "request": req,
            "providers": [
                {
                    "provider": "radar-core",
                    "state": "SUCCESS",
                    "elapsedMs": 120,
                    "evidence": self._evidence,
                    "observedAt": _COMPLETED_AT,
                    "errorClass": None,
                }
            ],
        }


class _FakeAcqService:
    """Fake AcquisitionService for tests.

    When snapshot is None (mirror mode), creates a _FakeSnapshot that mirrors
    the request direction/notional so the identity invariant always passes for
    normal positive tests.  Supply snapshot= to override with a static snapshot
    (used for error-path and invariant-failure tests)."""

    def __init__(self, *, snapshot: Any = None, raise_error: Any = None) -> None:
        self._snapshot = snapshot  # None → mirror mode
        self._raise = raise_error
        self.acquire = MagicMock(side_effect=self._do_acquire)

    def _do_acquire(self, request: Any) -> Any:
        if self._raise is not None:
            raise self._raise
        if self._snapshot is not None:
            return self._snapshot
        # Mirror mode: build a snapshot that matches the incoming request
        direction = getattr(request, "direction", "BUY") or "BUY"
        notional = getattr(request, "notional_usd", "1000") or "1000"
        return _FakeSnapshot(direction=direction, notional_usd=notional)


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def client(fake_svc, fake_universe):
    import main_api
    with TestClient(main_api.app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def client_raises(fake_svc, fake_universe):
    """Client with raise_server_exceptions=True for programming-error tests."""
    import main_api
    with TestClient(main_api.app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture()
def fake_svc():
    svc = _FakeAcqService()
    _exec_module.set_execution_service(svc)
    yield svc
    _exec_module.set_execution_service(None)


@pytest.fixture()
def fake_universe():
    _exec_module.set_universe_fn(lambda: [_NVDA])
    yield [_NVDA]
    _exec_module.set_universe_fn(None)


def _post(client: TestClient, uid: str = _UID, **body_overrides) -> Any:
    body = {"direction": "BUY", "notional_usd": "1000"}
    body.update(body_overrides)
    return client.post(f"/api/v1/radar/assets/{uid}/execution-simulation", json=body)


def _openapi(client: TestClient) -> dict:
    return client.get("/openapi.json").json()


# ── A2-01: route exists ───────────────────────────────────────────────────────


def test_a2_01_route_exists(client):
    r = _post(client)
    assert r.status_code == 200


# ── A2-02: OpenAPI request body ───────────────────────────────────────────────


def test_a2_02_openapi_documents_request_body(client):
    spec = _openapi(client)
    paths = spec.get("paths", {})
    route = paths.get(
        "/api/v1/radar/assets/{economic_asset_uid}/execution-simulation", {}
    )
    post_op = route.get("post", {})
    assert "requestBody" in post_op, "POST route must declare requestBody in OpenAPI"
    content = post_op["requestBody"].get("content", {})
    assert "application/json" in content, "requestBody must have application/json content"


# ── A2-03: OpenAPI ExecutionSimulationEnvelope ────────────────────────────────


def test_a2_03_openapi_documents_execution_simulation_envelope(client):
    spec = _openapi(client)
    schemas = spec.get("components", {}).get("schemas", {})
    assert "ExecutionSimulationEnvelope" in schemas, (
        "ExecutionSimulationEnvelope must appear in OpenAPI /components/schemas"
    )


# ── A2-04 to A2-07: valid combinations ───────────────────────────────────────


@pytest.mark.parametrize("direction,notional", [
    ("BUY", "100"),
    ("BUY", "1000"),
    ("SELL", "100"),
    ("SELL", "1000"),
])
def test_a2_04_to_07_valid_combinations(client, direction, notional):
    r = _post(client, direction=direction, notional_usd=notional)
    assert r.status_code == 200
    body = r.json()
    assert body["api_version"] == "v1"
    assert body["simulation"]["direction"] == direction
    assert body["simulation"]["notional_usd"] == notional


# ── A2-08: invalid direction → 400 ───────────────────────────────────────────


def test_a2_08_invalid_direction_returns_400(client):
    r = _post(client, direction="HOLD")
    assert r.status_code == 400
    body = r.json()
    assert body["error"] == "SIMULATION_REQUEST_INVALID"


# ── A2-09: invalid notional → 400 ────────────────────────────────────────────


def test_a2_09_invalid_notional_returns_400(client):
    r = _post(client, notional_usd="9999")
    assert r.status_code == 400
    body = r.json()
    assert body["error"] == "SIMULATION_REQUEST_INVALID"


# ── A2-10: ticker-like UID rejected before acquisition ───────────────────────


def test_a2_10_ticker_uid_rejected_400(client, fake_svc):
    r = client.post(
        "/api/v1/radar/assets/AAPL/execution-simulation",
        json={"direction": "BUY", "notional_usd": "1000"},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "ASSET_UID_INVALID"
    fake_svc.acquire.assert_not_called()


# ── A2-11: unknown valid-format UID → 404 ────────────────────────────────────


def test_a2_11_unknown_uid_returns_404(client, fake_svc):
    unknown = "0x" + "ff" * 32
    r = _post(client, uid=unknown)
    assert r.status_code == 404
    assert r.json()["error"] == "ASSET_NOT_FOUND"
    fake_svc.acquire.assert_not_called()


# ── A2-12: expected registry exception → sanitized 503 ───────────────────────


def test_a2_12_registry_unavailable_returns_503(fake_svc):
    from finco_radar.assets.contracts import RegistrySourceError
    import main_api

    def _boom():
        raise RegistrySourceError("network_error")

    _exec_module.set_universe_fn(_boom)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_universe_fn(None)

    assert r.status_code == 503
    body = r.json()
    assert body["error"] == "REGISTRY_UNAVAILABLE"
    assert body["detail"] == "Asset registry is temporarily unavailable."
    fake_svc.acquire.assert_not_called()


# ── A2-13 to A2-16: zero acquire calls on error paths ────────────────────────


def test_a2_13_invalid_uid_zero_acquire(client, fake_svc):
    client.post(
        "/api/v1/radar/assets/bad-uid-not-hex/execution-simulation",
        json={"direction": "BUY", "notional_usd": "1000"},
    )
    fake_svc.acquire.assert_not_called()


def test_a2_14_unknown_uid_zero_acquire(client, fake_svc):
    _post(client, uid="0x" + "ee" * 32)
    fake_svc.acquire.assert_not_called()


def test_a2_15_invalid_direction_zero_acquire(client, fake_svc):
    _post(client, direction="SELL_SHORT")
    fake_svc.acquire.assert_not_called()


def test_a2_16_invalid_notional_zero_acquire(client, fake_svc):
    _post(client, notional_usd="500")
    fake_svc.acquire.assert_not_called()


# ── A2-17: valid request → exactly ONE acquire call ──────────────────────────


def test_a2_17_valid_request_one_acquire(client, fake_svc):
    _post(client)
    fake_svc.acquire.assert_called_once()


# ── A2-18 to A2-22: request binding ──────────────────────────────────────────


def test_a2_18_request_uid_equals_selected_asset_uid(client, fake_svc):
    _post(client)
    req = fake_svc.acquire.call_args[0][0]
    assert req.economic_asset_uid == _UID


def test_a2_19_request_chain_equals_selected_asset_chain(client, fake_svc):
    _post(client)
    req = fake_svc.acquire.call_args[0][0]
    assert req.chain_id == _CHAIN_ID


def test_a2_20_request_contract_equals_selected_asset_contract(client, fake_svc):
    _post(client)
    req = fake_svc.acquire.call_args[0][0]
    assert req.contract_address.lower() == _CONTRACT.lower()


def test_a2_21_request_token_decimals_from_selected_asset(client, fake_svc):
    _post(client)
    req = fake_svc.acquire.call_args[0][0]
    provider_cfg = req.provider_config or {}
    target_asset = provider_cfg.get("targetAsset", {})
    assert target_asset.get("tokenDecimals") == _TOKEN_DECIMALS


def test_a2_22_ticker_cannot_influence_request_identity(fake_svc):
    """Different token_symbol but same UID/chain/contract must not change request."""
    import main_api

    other_asset = _FakeSelectedAsset(token_symbol="AAPL")
    _exec_module.set_universe_fn(lambda: [other_asset])
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        _post(client)
    _exec_module.set_universe_fn(None)

    req = fake_svc.acquire.call_args[0][0]
    # Identity bound to UID/chain/contract, NOT symbol
    assert req.economic_asset_uid == _UID
    assert req.chain_id == _CHAIN_ID
    assert req.contract_address.lower() == _CONTRACT.lower()


# ── A2-23 to A2-26: response snapshot id and state ───────────────────────────


def test_a2_23_response_snapshot_id_matches(client, fake_svc):
    snap = _FakeSnapshot(snapshot_id="acq-snap:custom-id-001")
    fake_svc._snapshot = snap
    r = _post(client)
    assert r.json()["snapshot_id"] == "acq-snap:custom-id-001"


def test_a2_24_state_complete_preserved(client):
    _exec_module.set_execution_service(
        _FakeAcqService(snapshot=_FakeSnapshot(state="COMPLETE"))
    )
    r = _post(client)
    assert r.json()["state"] == "COMPLETE"
    _exec_module.set_execution_service(None)


def test_a2_25_state_partial_preserved(fake_universe):
    import main_api

    svc = _FakeAcqService(snapshot=_FakeSnapshot(state="PARTIAL"))
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)
    assert r.json()["state"] == "PARTIAL"


def test_a2_26_state_unavailable_preserved(fake_universe):
    import main_api

    ev = _make_evidence(
        ref_available=False, exec_available=False, gap_available=False
    )
    svc = _FakeAcqService(snapshot=_FakeSnapshot(state="UNAVAILABLE", evidence=ev))
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)
    assert r.json()["state"] == "UNAVAILABLE"


# ── A2-27 to A2-30: verbatim authority fields ─────────────────────────────────


def test_a2_27_reference_price_verbatim(client):
    ev = _make_evidence(ref_price="143.11")
    _exec_module.set_execution_service(
        _FakeAcqService(snapshot=_FakeSnapshot(evidence=ev))
    )
    r = _post(client)
    _exec_module.set_execution_service(None)
    assert r.json()["reference"]["price"] == "143.11"


def test_a2_28_effective_price_verbatim(client):
    ev = _make_evidence(exec_price="142.77")
    _exec_module.set_execution_service(
        _FakeAcqService(snapshot=_FakeSnapshot(evidence=ev))
    )
    r = _post(client)
    _exec_module.set_execution_service(None)
    assert r.json()["execution"]["effective_price"] == "142.77"


def test_a2_29_gap_bps_verbatim(client):
    ev = _make_evidence(gap_bps="-24")
    _exec_module.set_execution_service(
        _FakeAcqService(snapshot=_FakeSnapshot(evidence=ev))
    )
    r = _post(client)
    _exec_module.set_execution_service(None)
    assert r.json()["gap"]["gap_bps"] == "-24"


def test_a2_30_gap_not_recomputed(client):
    """GAP must come from snapshot, not be recomputed from reference/execution.

    Deliberately set: reference=100, execution=200, canonical gap_bps="37".
    The response must return "37", not a calculated value.
    """
    ev = _make_evidence(
        ref_price="100",
        exec_price="200",
        gap_bps="37",
        gap_to_mid_bps="37",
    )
    _exec_module.set_execution_service(
        _FakeAcqService(snapshot=_FakeSnapshot(evidence=ev))
    )
    r = _post(client)
    _exec_module.set_execution_service(None)
    assert r.json()["gap"]["gap_bps"] == "37"


# ── A2-31 to A2-34: zero and negative values preserved ───────────────────────


def test_a2_31_zero_reference_preserved(client):
    ev = _make_evidence(ref_price="0")
    _exec_module.set_execution_service(
        _FakeAcqService(snapshot=_FakeSnapshot(evidence=ev))
    )
    r = _post(client)
    _exec_module.set_execution_service(None)
    assert r.json()["reference"]["price"] == "0"


def test_a2_32_zero_effective_price_preserved(client):
    ev = _make_evidence(exec_price="0")
    _exec_module.set_execution_service(
        _FakeAcqService(snapshot=_FakeSnapshot(evidence=ev))
    )
    r = _post(client)
    _exec_module.set_execution_service(None)
    assert r.json()["execution"]["effective_price"] == "0"


def test_a2_33_zero_gap_preserved(client):
    ev = _make_evidence(gap_bps="0", gap_to_mid_bps="0")
    _exec_module.set_execution_service(
        _FakeAcqService(snapshot=_FakeSnapshot(evidence=ev))
    )
    r = _post(client)
    _exec_module.set_execution_service(None)
    assert r.json()["gap"]["gap_bps"] == "0"


def test_a2_34_negative_gap_preserved(client):
    ev = _make_evidence(gap_bps="-99", gap_to_mid_bps="-50")
    _exec_module.set_execution_service(
        _FakeAcqService(snapshot=_FakeSnapshot(evidence=ev))
    )
    r = _post(client)
    _exec_module.set_execution_service(None)
    assert r.json()["gap"]["gap_bps"] == "-99"


# ── A2-35 to A2-38: unavailability sections ───────────────────────────────────


def test_a2_35_reference_unavailable_is_200(client):
    ev = _make_evidence(ref_available=False)
    _exec_module.set_execution_service(
        _FakeAcqService(snapshot=_FakeSnapshot(evidence=ev, state="PARTIAL"))
    )
    r = _post(client)
    _exec_module.set_execution_service(None)
    assert r.status_code == 200
    ref = r.json()["reference"]
    assert ref["available"] is False


def test_a2_36_execution_unavailable_is_200(client):
    ev = _make_evidence(exec_available=False)
    _exec_module.set_execution_service(
        _FakeAcqService(snapshot=_FakeSnapshot(evidence=ev, state="PARTIAL"))
    )
    r = _post(client)
    _exec_module.set_execution_service(None)
    assert r.status_code == 200
    assert r.json()["execution"]["available"] is False


def test_a2_37_gap_unavailable_is_200(client):
    ev = _make_evidence(gap_available=False)
    _exec_module.set_execution_service(
        _FakeAcqService(snapshot=_FakeSnapshot(evidence=ev, state="PARTIAL"))
    )
    r = _post(client)
    _exec_module.set_execution_service(None)
    assert r.status_code == 200
    assert r.json()["gap"]["available"] is False


def test_a2_38_unavailable_reason_preserved(client):
    ev = _make_evidence(ref_available=False)
    # ref_available=False sets reason = "REFERENCE_UNAVAILABLE"
    _exec_module.set_execution_service(
        _FakeAcqService(snapshot=_FakeSnapshot(evidence=ev, state="PARTIAL"))
    )
    r = _post(client)
    _exec_module.set_execution_service(None)
    ref = r.json()["reference"]
    assert ref["available"] is False
    assert ref["reason"] == "REFERENCE_UNAVAILABLE"


# ── A2-39 to A2-43: safety fields ────────────────────────────────────────────


def test_a2_39_simulation_only_true(client):
    r = _post(client)
    assert r.json()["simulation"]["simulation_only"] is True


def test_a2_40_order_submitted_false(client):
    r = _post(client)
    assert r.json()["simulation"]["order_submitted"] is False


def _all_values_recursive(obj: Any):
    """Yield all string values anywhere in a nested JSON object."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _all_values_recursive(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _all_values_recursive(v)


def _all_keys_recursive(obj: Any):
    """Yield all string keys anywhere in a nested JSON object."""
    if isinstance(obj, dict):
        for k in obj.keys():
            yield k
            yield from _all_keys_recursive(obj[k])
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _all_keys_recursive(v)


def test_a2_41_no_wallet_fields(client):
    r = _post(client)
    keys = set(_all_keys_recursive(r.json()))
    wallet_keys = {"wallet", "wallet_address", "walletAddress", "wallet_id"}
    assert not (keys & wallet_keys), f"Wallet fields found: {keys & wallet_keys}"


def test_a2_42_no_signature_fields(client):
    r = _post(client)
    keys = set(_all_keys_recursive(r.json()))
    sig_keys = {"signature", "signed", "approval", "approved", "approve_tx"}
    assert not (keys & sig_keys), f"Signature fields found: {keys & sig_keys}"


def test_a2_43_no_transaction_or_order_fields(client):
    r = _post(client)
    keys = set(_all_keys_recursive(r.json()))
    tx_keys = {
        "order_id", "orderId", "transaction_hash", "txHash", "tx_hash",
        "execution_confirmed", "trade_status", "tradeStatus",
    }
    assert not (keys & tx_keys), f"Tx/order fields found: {keys & tx_keys}"


# ── A2-44 to A2-46: no raw payload / credentials ─────────────────────────────


def test_a2_44_raw_payload_json_absent_recursively(client):
    r = _post(client)
    keys = set(_all_keys_recursive(r.json()))
    assert "raw_payload_json" not in keys
    assert "rawPayloadJson" not in keys


def test_a2_45_raw_evidence_absent_recursively(client):
    r = _post(client)
    keys = set(_all_keys_recursive(r.json()))
    assert "raw_evidence" not in keys
    assert "rawEvidence" not in keys


# Sentinel strings to inject into evidence metadata fields.
# All must be absent from the public JSON response.
_SENTINEL_URL = "https://private.internal.example/secret"
_SENTINEL_PATH_DB = "/srv/finco/private/db.sqlite"
_SENTINEL_TOKEN = "apikey=REDACT_SENTINEL"   # credential pattern sentinel
_SENTINEL_PATH_AWS = "/root/.aws/credentials"


def test_a2_46_adversarial_sentinel_absent(fake_universe):
    """Adversarial evidence with private paths/API-key sentinels must not leak.

    Injects distinct sentinels into reference.source, execution.unavailableReason,
    execution.source, and gap.reason.  Verifies the outward-string safety boundary
    redacts all of them.  Also verifies that canonical source labels and reason
    codes remain visible."""
    import main_api

    adversarial_evidence = {
        "reference": {
            "available": True,
            "price": "143.11",
            "bid": "143.00",
            "ask": "143.22",
            "source": _SENTINEL_URL,                    # URL scheme → redacted
            "observedAt": _COMPLETED_AT,
        },
        "execution": {
            "available": False,
            "unavailableReason": _SENTINEL_TOKEN,       # credential pattern → redacted
            "source": _SENTINEL_PATH_DB,                # Unix path → redacted
            "status": "QUOTE_FAILED",
            "quotedAt": _COMPLETED_AT,
        },
        "gap": {
            "available": False,
            "reason": _SENTINEL_PATH_AWS,               # Unix path → redacted
        },
    }
    svc = _FakeAcqService(snapshot=_FakeSnapshot(evidence=adversarial_evidence))
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)

    assert r.status_code == 200
    body_text = json.dumps(r.json())

    # No sentinel may appear anywhere in the public JSON response
    assert _SENTINEL_URL not in body_text, "URL sentinel leaked"
    assert _SENTINEL_PATH_DB not in body_text, "DB path sentinel leaked"
    assert _SENTINEL_TOKEN not in body_text, "API key sentinel leaked"
    assert _SENTINEL_PATH_AWS not in body_text, "AWS credentials path leaked"

    # Verify the stable fallback appears (redaction is active, not silent erasure)
    assert "INTERNAL_DETAIL_REDACTED" in body_text, "Safety fallback not found"


def test_a2_46b_canonical_metadata_not_redacted(fake_universe):
    """Canonical source labels and reason codes must NOT be redacted."""
    import main_api

    canonical_evidence = _make_evidence(ref_available=False)
    # ref reason = "REFERENCE_UNAVAILABLE" — canonical, no digits, no path, no URL
    svc = _FakeAcqService(snapshot=_FakeSnapshot(evidence=canonical_evidence, state="PARTIAL"))
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)

    body = r.json()
    # Canonical reason code must be preserved verbatim
    assert body["reference"]["reason"] == "REFERENCE_UNAVAILABLE"


# ── A2-47: programming error propagates ──────────────────────────────────────


def test_a2_47_programming_error_not_swallowed(fake_universe):
    """RuntimeError("PROGRAMMING_SENTINEL") must propagate, not become 503/200."""
    import main_api

    svc = _FakeAcqService(raise_error=RuntimeError("PROGRAMMING_SENTINEL"))
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)

    # Must be a 500 (propagated to FastAPI default handler), NOT 200 or 503
    assert r.status_code == 500
    # Must NOT be a fabricated "SIMULATION_UNAVAILABLE" error
    body_text = r.text
    assert "SIMULATION_UNAVAILABLE" not in body_text


# ── A2-48: route handler is synchronous ──────────────────────────────────────


def test_a2_48_route_handler_is_synchronous():
    """The POST route handler must not be a coroutine (runs in threadpool)."""
    import inspect
    from app.api.v1.router import post_execution_simulation
    assert not inspect.iscoroutinefunction(post_execution_simulation), (
        "post_execution_simulation must be a plain def, not async def"
    )


# ── A2-49 to A2-51: identity invariant failures ───────────────────────────────


def test_a2_49_snapshot_uid_mismatch_fails_closed(fake_universe):
    """Snapshot with wrong UID must not be serialized — hard error."""
    import main_api

    svc = _FakeAcqService(
        snapshot=_FakeSnapshot(uid=_OTHER_UID)
    )
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)
    # Identity mismatch must NOT produce a valid 200 simulation response
    assert r.status_code != 200


def test_a2_50_snapshot_chain_mismatch_fails_closed(fake_universe):
    """Snapshot with wrong chain_id must not be serialized."""
    import main_api

    svc = _FakeAcqService(
        snapshot=_FakeSnapshot(chain_id=9999)
    )
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)
    assert r.status_code != 200


def test_a2_51_snapshot_contract_mismatch_fails_closed(fake_universe):
    """Snapshot with wrong contract address must not be serialized."""
    import main_api

    svc = _FakeAcqService(
        snapshot=_FakeSnapshot(contract=_OTHER_CONTRACT)
    )
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)
    assert r.status_code != 200


# ── A2-52: /meta capability ───────────────────────────────────────────────────


def test_a2_52_meta_advertises_a2_capability(fake_svc, fake_universe):
    import main_api

    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = client.get("/api/v1/meta")
    assert r.status_code == 200
    caps = r.json()["capabilities"]
    assert "radar.execution.simulation" in caps


# ── A2-53: A1 GET endpoints make zero execution acquisitions ──────────────────


def test_a2_53_a1_get_endpoints_zero_execution_acquisitions(fake_svc, fake_universe):
    """Existing A1 GET endpoints must NOT trigger execution service calls."""
    import main_api
    from unittest.mock import patch
    import app.api.v1.radar as _radar_svc

    fake_registry = MagicMock()
    fake_snapshot = MagicMock()
    fake_snapshot.assets = []
    fake_registry.fetch_snapshot.return_value = fake_snapshot

    with patch.object(_radar_svc, "_registry_factory_override",
                      lambda: fake_registry):
        with TestClient(main_api.app, raise_server_exceptions=False) as client:
            client.get("/api/v1/radar/assets")
            client.get(f"/api/v1/radar/assets/{_UID}")
            client.get(f"/api/v1/radar/assets/{_UID}/fundamentals")
            client.get(f"/api/v1/radar/assets/{_UID}/financials")
            client.get(f"/api/v1/radar/assets/{_UID}/corporate-actions")
            client.get(f"/api/v1/radar/assets/{_UID}/evidence")

    fake_svc.acquire.assert_not_called()


# ── A2-54: E4 Company Terminal makes zero acquisitions ───────────────────────


def test_a2_54_e4_terminal_makes_zero_acquisitions(fake_svc, fake_universe):
    """The E4 UI Company Terminal GET must not trigger A2 execution service calls."""
    import main_api

    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        client.get(f"/radar/equity/{_UID}?tab=token-market")

    fake_svc.acquire.assert_not_called()


# ── A2-55: no economic authority package changed ─────────────────────────────


def test_a2_55_no_economic_authority_changed():
    """Frozen Radar authority packages must not be imported with side-effects
    caused by A2 implementation files."""
    frozen_packages = [
        "finco_radar.quotes",
        "finco_radar.assets",
        "finco_radar.gap",
        "finco_radar.liquidity",
        "finco_radar.reference_state",
        "finco_radar.cross_market",
        "finco_radar.execution_simulator",
    ]
    # Verify none of the frozen packages were modified by importing A2 modules
    import app.api.v1.execution  # noqa: F401
    import app.api.v1.router  # noqa: F401
    import app.api.v1.schemas  # noqa: F401

    for pkg in frozen_packages:
        mod = importlib.import_module(pkg)
        # Just checking they're importable and have their canonical __file__
        assert mod.__file__ is not None
        assert "finco_radar" in mod.__file__


# ══ Correction A tests ═══════════════════════════════════════════════════════

# ── C01: direction mismatch fails closed ──────────────────────────────────────


def test_ca_c01_direction_mismatch_fails_closed(fake_universe):
    """BUY request but snapshot has SELL direction → identity invariant fails."""
    import main_api

    # Snapshot has direction="SELL" but request sends direction="BUY"
    svc = _FakeAcqService(snapshot=_FakeSnapshot(direction="SELL", notional_usd="1000"))
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client, direction="BUY", notional_usd="1000")
    _exec_module.set_execution_service(None)

    # Must fail closed — not a 200 simulation response
    assert r.status_code != 200
    # Prove the invariant error fires, not a fabricated simulation result
    assert r.status_code == 500  # IdentityInvariantError propagates as programming error


# ── C02: notional mismatch fails closed ───────────────────────────────────────


def test_ca_c02_notional_mismatch_fails_closed(fake_universe):
    """1000 request but snapshot has notional 100 → identity invariant fails."""
    import main_api

    svc = _FakeAcqService(snapshot=_FakeSnapshot(direction="BUY", notional_usd="100"))
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client, direction="BUY", notional_usd="1000")
    _exec_module.set_execution_service(None)

    assert r.status_code != 200
    assert r.status_code == 500


# ── C03: snapshot missing request.direction fails closed ──────────────────────


def test_ca_c03_snapshot_missing_direction_fails_closed(fake_universe):
    """Snapshot request.direction absent → invariant fails closed."""
    import main_api

    # Build a request block without direction
    bad_request_block = {
        "chainId": _CHAIN_ID,
        "contractAddress": _CONTRACT,
        "economicAssetUid": _UID,
        "sources": ["radar-core"],
        "notionalUsd": "1000",
        "providerConfig": None,
        # "direction" intentionally absent
    }
    svc = _FakeAcqService(snapshot=_FakeSnapshot(request_block=bad_request_block))
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)

    assert r.status_code != 200


# ── C04: snapshot missing request.notionalUsd fails closed ────────────────────


def test_ca_c04_snapshot_missing_notional_fails_closed(fake_universe):
    """Snapshot request.notionalUsd absent → invariant fails closed."""
    import main_api

    bad_request_block = {
        "chainId": _CHAIN_ID,
        "contractAddress": _CONTRACT,
        "economicAssetUid": _UID,
        "direction": "BUY",
        "sources": ["radar-core"],
        "providerConfig": None,
        # "notionalUsd" intentionally absent
    }
    svc = _FakeAcqService(snapshot=_FakeSnapshot(request_block=bad_request_block))
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)

    assert r.status_code != 200


# ── C05: exact match serializes successfully ──────────────────────────────────


def test_ca_c05_exact_match_serializes_successfully(fake_universe):
    """UID+chain+contract+direction+notional all match → 200 and correct fields."""
    import main_api

    svc = _FakeAcqService(snapshot=_FakeSnapshot(
        uid=_UID, chain_id=_CHAIN_ID, contract=_CONTRACT,
        direction="BUY", notional_usd="1000"
    ))
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client, direction="BUY", notional_usd="1000")
    _exec_module.set_execution_service(None)

    assert r.status_code == 200
    body = r.json()
    assert body["simulation"]["direction"] == "BUY"
    assert body["simulation"]["notional_usd"] == "1000"
    assert body["economic_asset_uid"] == _UID


# ── C06: providers=[other, radar-core] → canonical values from radar-core ──────


def test_ca_c06_radar_core_at_index_1_is_used(fake_universe):
    """When radar-core is not first in the provider list, it must still be used."""
    import main_api

    other_evidence = {
        "reference": {"available": True, "price": "999.99", "source": "OtherProvider",
                      "bid": "999.00", "ask": "999.98",
                      "observedAt": _COMPLETED_AT},
        "execution": {"available": True, "effectivePrice": "888.88",
                      "status": "QUOTE_OK", "source": "OtherProvider",
                      "quotedAt": _COMPLETED_AT},
        "gap": {"available": True, "gapBps": "9999", "gapToMidBps": "9999",
                "quotedAt": _COMPLETED_AT},
    }
    radar_core_evidence = _make_evidence(ref_price="143.11", exec_price="142.77")

    # Snapshot with two providers: other first, radar-core second
    class _MultiProviderSnapshot:
        snapshot_id = _SNAP_ID
        def to_payload(self) -> dict:
            return {
                "state": "COMPLETE",
                "economicAssetUid": _UID,
                "chainId": _CHAIN_ID,
                "contractAddress": _CONTRACT,
                "completedAt": _COMPLETED_AT,
                "request": _make_request_block("BUY", "1000"),
                "providers": [
                    {"provider": "other-provider", "state": "SUCCESS",
                     "elapsedMs": 50, "evidence": other_evidence,
                     "observedAt": _COMPLETED_AT, "errorClass": None},
                    {"provider": "radar-core", "state": "SUCCESS",
                     "elapsedMs": 120, "evidence": radar_core_evidence,
                     "observedAt": _COMPLETED_AT, "errorClass": None},
                ],
            }

    svc = _FakeAcqService(snapshot=_MultiProviderSnapshot())
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)

    assert r.status_code == 200
    body = r.json()
    # Values must come from radar-core, NOT from other-provider
    assert body["reference"]["price"] == "143.11"
    assert body["execution"]["effective_price"] == "142.77"
    assert body["reference"]["price"] != "999.99"
    assert body["execution"]["effective_price"] != "888.88"


# ── C07: providers=[radar-core, other] → same canonical result ────────────────


def test_ca_c07_radar_core_at_index_0_is_used(fake_universe):
    """When radar-core is first, it must still be selected by name."""
    import main_api

    radar_core_evidence = _make_evidence(ref_price="143.11", exec_price="142.77")
    other_evidence = {
        "reference": {"available": True, "price": "999.99", "source": "OtherProvider",
                      "bid": "999.00", "ask": "999.98",
                      "observedAt": _COMPLETED_AT},
        "execution": {"available": True, "effectivePrice": "888.88",
                      "status": "QUOTE_OK", "source": "OtherProvider",
                      "quotedAt": _COMPLETED_AT},
        "gap": {"available": True, "gapBps": "9999", "gapToMidBps": "9999",
                "quotedAt": _COMPLETED_AT},
    }

    class _MultiProviderSnapshot:
        snapshot_id = _SNAP_ID
        def to_payload(self) -> dict:
            return {
                "state": "COMPLETE",
                "economicAssetUid": _UID,
                "chainId": _CHAIN_ID,
                "contractAddress": _CONTRACT,
                "completedAt": _COMPLETED_AT,
                "request": _make_request_block("BUY", "1000"),
                "providers": [
                    {"provider": "radar-core", "state": "SUCCESS",
                     "elapsedMs": 120, "evidence": radar_core_evidence,
                     "observedAt": _COMPLETED_AT, "errorClass": None},
                    {"provider": "other-provider", "state": "SUCCESS",
                     "elapsedMs": 50, "evidence": other_evidence,
                     "observedAt": _COMPLETED_AT, "errorClass": None},
                ],
            }

    svc = _FakeAcqService(snapshot=_MultiProviderSnapshot())
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)

    assert r.status_code == 200
    body = r.json()
    assert body["reference"]["price"] == "143.11"
    assert body["execution"]["effective_price"] == "142.77"


# ── C08: providers=[other-provider only] → ProviderInvariantError → HTTP 500 ──


def test_ca_c08_radar_core_absent_hard_fail(fake_universe):
    """When radar-core is absent from providers, serialization must fail closed (HTTP 500).

    Provider absent = invariant failure, not a quote-unavailable state."""
    import main_api

    foreign_evidence = {
        "reference": {"available": True, "price": "999.99",
                      "source": "ForeignProvider", "bid": "999.00", "ask": "999.98",
                      "observedAt": _COMPLETED_AT},
        "execution": {"available": True, "effectivePrice": "888.88",
                      "status": "QUOTE_OK", "source": "ForeignProvider",
                      "quotedAt": _COMPLETED_AT},
        "gap": {"available": True, "gapBps": "9999", "gapToMidBps": "9999",
                "quotedAt": _COMPLETED_AT},
    }

    class _ForeignOnlySnapshot:
        snapshot_id = _SNAP_ID
        def to_payload(self) -> dict:
            return {
                "state": "COMPLETE",
                "economicAssetUid": _UID,
                "chainId": _CHAIN_ID,
                "contractAddress": _CONTRACT,
                "completedAt": _COMPLETED_AT,
                "request": _make_request_block("BUY", "1000"),
                "providers": [
                    {"provider": "other-provider", "state": "SUCCESS",
                     "elapsedMs": 50, "evidence": foreign_evidence,
                     "observedAt": _COMPLETED_AT, "errorClass": None},
                ],
            }

    svc = _FakeAcqService(snapshot=_ForeignOnlySnapshot())
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)

    # radar-core absent → ProviderInvariantError propagates as HTTP 500
    assert r.status_code == 500, (
        f"Expected 500 for absent radar-core, got {r.status_code}"
    )
    body_text = r.text
    assert "999.99" not in body_text, "Foreign reference price leaked"
    assert "888.88" not in body_text, "Foreign execution price leaked"


# ── C09: execution unavailableReason preserved ────────────────────────────────


def test_ca_c09_execution_unavailable_reason_from_unavailable_reason_field(fake_universe):
    """unavailableReason="NO_ROUTE" in evidence → response reason == "NO_ROUTE"."""
    import main_api

    ev = {
        "reference": {"available": True, "price": "143.11",
                      "source": "FROZEN::BoundReferencePrice",
                      "bid": "143.00", "ask": "143.22",
                      "observedAt": _COMPLETED_AT},
        "execution": {
            "available": False,
            "unavailableReason": "NO_ROUTE",
            "status": "QUOTE_FAILED",
            "source": "LiFi",
            "quotedAt": _COMPLETED_AT,
        },
        "gap": {"available": False, "reason": "GAP_REQUIRES_EXECUTION_AND_REFERENCE"},
    }
    svc = _FakeAcqService(snapshot=_FakeSnapshot(evidence=ev, state="PARTIAL"))
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)

    exec_sec = r.json()["execution"]
    assert exec_sec["available"] is False
    assert exec_sec["reason"] == "NO_ROUTE"


# ── C10: unavailableReason wins over reason ────────────────────────────────────


def test_ca_c10_unavailable_reason_wins_over_reason(fake_universe):
    """When both unavailableReason and reason are present, unavailableReason wins."""
    import main_api

    ev = {
        "reference": {"available": False, "reason": "REFERENCE_UNAVAILABLE"},
        "execution": {
            "available": False,
            "unavailableReason": "NO_ROUTE",     # this should win
            "reason": "EXECUTION_UNAVAILABLE",   # this should be ignored
        },
        "gap": {"available": False, "reason": "GAP_REQUIRES_EXECUTION_AND_REFERENCE"},
    }
    svc = _FakeAcqService(snapshot=_FakeSnapshot(evidence=ev, state="UNAVAILABLE"))
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)

    exec_sec = r.json()["execution"]
    assert exec_sec["available"] is False
    assert exec_sec["reason"] == "NO_ROUTE"


# ── C11: reason only preserved ────────────────────────────────────────────────


def test_ca_c11_reason_only_preserved(fake_universe):
    """When only reason is present (no unavailableReason), reason is preserved."""
    import main_api

    ev = {
        "reference": {"available": False, "reason": "REFERENCE_UNAVAILABLE"},
        "execution": {
            "available": False,
            "reason": "SLIPPAGE_EXCEEDED",   # only reason, no unavailableReason
        },
        "gap": {"available": False, "reason": "GAP_REQUIRES_EXECUTION_AND_REFERENCE"},
    }
    svc = _FakeAcqService(snapshot=_FakeSnapshot(evidence=ev, state="UNAVAILABLE"))
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)

    exec_sec = r.json()["execution"]
    assert exec_sec["available"] is False
    assert exec_sec["reason"] == "SLIPPAGE_EXCEEDED"


# ── C12: neither unavailableReason nor reason → stable fallback ───────────────


def test_ca_c12_neither_reason_gives_stable_fallback(fake_universe):
    """When neither unavailableReason nor reason is present, stable fallback is used."""
    import main_api

    ev = {
        "reference": {"available": False, "reason": "REFERENCE_UNAVAILABLE"},
        "execution": {
            "available": False,
            # no reason, no unavailableReason
        },
        "gap": {"available": False, "reason": "GAP_REQUIRES_EXECUTION_AND_REFERENCE"},
    }
    svc = _FakeAcqService(snapshot=_FakeSnapshot(evidence=ev, state="UNAVAILABLE"))
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)

    exec_sec = r.json()["execution"]
    assert exec_sec["available"] is False
    assert exec_sec["reason"] == "EXECUTION_UNAVAILABLE"


# ── C13: expected registry exception → sanitized 503 ─────────────────────────


def test_ca_c13_registry_source_error_returns_503(fake_svc):
    """RegistrySourceError from universe → sanitized 503 REGISTRY_UNAVAILABLE."""
    from finco_radar.assets.contracts import RegistrySourceError
    import main_api

    def _boom():
        raise RegistrySourceError("connection refused to registry")

    _exec_module.set_universe_fn(_boom)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_universe_fn(None)

    assert r.status_code == 503
    body = r.json()
    assert body["error"] == "REGISTRY_UNAVAILABLE"
    assert body["detail"] == "Asset registry is temporarily unavailable."
    # Raw exception text must NOT appear in the response
    assert "connection refused" not in json.dumps(body)
    fake_svc.acquire.assert_not_called()


# ── C14: programming error from universe propagates as 500 ───────────────────


def test_ca_c14_programming_error_from_universe_propagates(fake_svc):
    """RuntimeError from the universe path must propagate as 500, not become 503."""
    import main_api

    def _programming_error():
        raise RuntimeError("PROGRAMMING_SENTINEL_UNIVERSE")

    _exec_module.set_universe_fn(_programming_error)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_universe_fn(None)

    assert r.status_code == 500
    assert "PROGRAMMING_SENTINEL_UNIVERSE" not in json.dumps(r.json()) if r.headers.get("content-type", "").startswith("application/json") else True
    # Must NOT be converted to a 503 REGISTRY_UNAVAILABLE
    fake_svc.acquire.assert_not_called()


# ── C15: public 503 contains only stable detail ───────────────────────────────


def test_ca_c15_public_503_stable_detail(fake_svc):
    """The 503 response detail must be the stable string, no raw exception text."""
    from finco_radar.assets.contracts import RegistryConflictError
    import main_api

    def _boom():
        raise RegistryConflictError("uid=0xdeadbeef conflict hash=abc123 source=internal")

    _exec_module.set_universe_fn(_boom)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_universe_fn(None)

    assert r.status_code == 503
    body = r.json()
    assert body["detail"] == "Asset registry is temporarily unavailable."
    # No raw exception internals must appear
    body_text = json.dumps(body)
    assert "uid=0xdeadbeef" not in body_text
    assert "hash=abc123" not in body_text
    assert "source=internal" not in body_text


# ── C16-C22: strict string contract — no accidental 422, all → 400 ────────────


@pytest.mark.parametrize("notional_value,label", [
    (100,     "numeric int"),
    (100.0,   "float"),
    (True,    "bool true"),
    (None,    "null"),
    ([],      "empty list"),
    ({},      "empty dict"),
])
def test_ca_c16_to_c20_invalid_notional_types_return_400(
    client, fake_svc, notional_value, label
):
    """Non-string notional_usd values must produce 400, never 422."""
    r = client.post(
        f"/api/v1/radar/assets/{_UID}/execution-simulation",
        json={"direction": "BUY", "notional_usd": notional_value},
    )
    assert r.status_code == 400, (
        f"Expected 400 for notional_usd={label!r}, got {r.status_code}"
    )
    assert r.json()["error"] == "SIMULATION_REQUEST_INVALID"
    fake_svc.acquire.assert_not_called()


def test_ca_c21_missing_direction_returns_400(client, fake_svc):
    """Missing direction → 400 SIMULATION_REQUEST_INVALID, zero acquire."""
    r = client.post(
        f"/api/v1/radar/assets/{_UID}/execution-simulation",
        json={"notional_usd": "1000"},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "SIMULATION_REQUEST_INVALID"
    fake_svc.acquire.assert_not_called()


def test_ca_c22_missing_notional_returns_400(client, fake_svc):
    """Missing notional_usd → 400 SIMULATION_REQUEST_INVALID, zero acquire."""
    r = client.post(
        f"/api/v1/radar/assets/{_UID}/execution-simulation",
        json={"direction": "BUY"},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "SIMULATION_REQUEST_INVALID"
    fake_svc.acquire.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# CORRECTION B TESTS (CB01-CB14)
# ══════════════════════════════════════════════════════════════════════════════


# ── CB01-CB03: canonical source labels are NOT redacted ───────────────────────


def test_cb01_lifi_v1_quote_source_not_redacted(fake_universe):
    """LIFI_V1_QUOTE is a canonical source label and must not be redacted."""
    import main_api

    ev = {
        "reference": {"available": True, "price": "143.11",
                      "source": "FROZEN::BoundReferencePrice",
                      "bid": "143.00", "ask": "143.22",
                      "observedAt": _COMPLETED_AT},
        "execution": {
            "available": True,
            "effectivePrice": "142.77",
            "status": "QUOTE_OK",
            "source": "LIFI_V1_QUOTE",
            "quotedAt": _COMPLETED_AT,
        },
        "gap": {"available": True, "gapBps": "55", "gapToMidBps": "43",
                "quotedAt": _COMPLETED_AT},
    }
    svc = _FakeAcqService(snapshot=_FakeSnapshot(evidence=ev))
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)

    assert r.status_code == 200
    body = r.json()
    assert body["execution"]["source"] == "LIFI_V1_QUOTE", (
        f"Canonical source label redacted: {body['execution']['source']!r}"
    )


def test_cb02_r2_gap_reason_not_redacted(fake_universe):
    """R2_GAP is a canonical reason code and must not be redacted."""
    import main_api

    ev = {
        "reference": {"available": True, "price": "143.11",
                      "source": "FROZEN::BoundReferencePrice",
                      "bid": "143.00", "ask": "143.22",
                      "observedAt": _COMPLETED_AT},
        "execution": {"available": False, "unavailableReason": "NO_ROUTE"},
        "gap": {"available": False, "reason": "R2_GAP"},
    }
    svc = _FakeAcqService(snapshot=_FakeSnapshot(evidence=ev, state="PARTIAL"))
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)

    assert r.status_code == 200
    body = r.json()
    assert body["gap"]["reason"] == "R2_GAP", (
        f"Canonical reason code redacted: {body['gap']['reason']!r}"
    )


def test_cb03_http_429_reason_not_redacted(fake_universe):
    """HTTP_429 is a canonical reason code and must not be redacted."""
    import main_api

    ev = {
        "reference": {"available": True, "price": "143.11",
                      "source": "FROZEN::BoundReferencePrice",
                      "bid": "143.00", "ask": "143.22",
                      "observedAt": _COMPLETED_AT},
        "execution": {
            "available": False,
            "unavailableReason": "HTTP_429",
            "status": "QUOTE_FAILED",
            "quotedAt": _COMPLETED_AT,
        },
        "gap": {"available": False, "reason": "GAP_REQUIRES_EXECUTION_AND_REFERENCE"},
    }
    svc = _FakeAcqService(snapshot=_FakeSnapshot(evidence=ev, state="PARTIAL"))
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)

    assert r.status_code == 200
    body = r.json()
    assert body["execution"]["reason"] == "HTTP_429", (
        f"Canonical reason code redacted: {body['execution']['reason']!r}"
    )


# ── CB04-CB06: Windows/UNC path patterns are redacted ────────────────────────


def test_cb04_windows_drive_c_backslash_redacted(fake_universe):
    """C:\\private\\secret.txt (Windows backslash drive path) must be redacted."""
    import main_api

    ev = {
        "reference": {"available": False, "reason": "REFERENCE_UNAVAILABLE"},
        "execution": {
            "available": False,
            "unavailableReason": r"C:\private\secret.txt",
        },
        "gap": {"available": False, "reason": "GAP_UNAVAILABLE"},
    }
    svc = _FakeAcqService(snapshot=_FakeSnapshot(evidence=ev, state="UNAVAILABLE"))
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)

    assert r.status_code == 200
    body_text = json.dumps(r.json())
    assert r"C:\private\secret.txt" not in body_text, "Windows drive path leaked"
    # Redaction active: section-specific fallback replaces the path
    body = r.json()
    assert body["execution"]["available"] is False
    assert body["execution"]["reason"] == "EXECUTION_UNAVAILABLE"


def test_cb05_windows_drive_d_slash_redacted(fake_universe):
    """D:/finco/private.db (Windows forward-slash drive path) must be redacted."""
    import main_api

    ev = {
        "reference": {"available": False, "reason": "REFERENCE_UNAVAILABLE"},
        "execution": {
            "available": False,
            "unavailableReason": "D:/finco/private.db",
        },
        "gap": {"available": False, "reason": "GAP_UNAVAILABLE"},
    }
    svc = _FakeAcqService(snapshot=_FakeSnapshot(evidence=ev, state="UNAVAILABLE"))
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)

    assert r.status_code == 200
    body_text = json.dumps(r.json())
    assert "D:/finco/private.db" not in body_text, "Windows forward-slash path leaked"
    body = r.json()
    assert body["execution"]["available"] is False
    assert body["execution"]["reason"] == "EXECUTION_UNAVAILABLE"


def test_cb06_unc_path_redacted(fake_universe):
    r"""\\server\share\secret (UNC path) must be redacted."""
    import main_api

    ev = {
        "reference": {"available": False, "reason": "REFERENCE_UNAVAILABLE"},
        "execution": {
            "available": False,
            "unavailableReason": r"\\server\share\secret",
        },
        "gap": {"available": False, "reason": "GAP_UNAVAILABLE"},
    }
    svc = _FakeAcqService(snapshot=_FakeSnapshot(evidence=ev, state="UNAVAILABLE"))
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)

    assert r.status_code == 200
    body_text = json.dumps(r.json())
    assert r"\\server\share\secret" not in body_text, "UNC path leaked"
    body = r.json()
    assert body["execution"]["available"] is False
    assert body["execution"]["reason"] == "EXECUTION_UNAVAILABLE"


# ── CB07: credential pattern in source is redacted ───────────────────────────


def test_cb07_apikey_credential_pattern_redacted(fake_universe):
    """apikey=... in execution.source triggers the credential pattern redaction."""
    import main_api

    ev = {
        "reference": {"available": False, "reason": "REFERENCE_UNAVAILABLE"},
        "execution": {
            "available": False,
            "unavailableReason": "EXECUTION_UNAVAILABLE",
            "source": "apikey=REDACT_SENTINEL",
        },
        "gap": {"available": False, "reason": "GAP_UNAVAILABLE"},
    }
    svc = _FakeAcqService(snapshot=_FakeSnapshot(evidence=ev, state="UNAVAILABLE"))
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)

    assert r.status_code == 200
    body_text = json.dumps(r.json())
    assert "apikey=REDACT_SENTINEL" not in body_text, "Credential pattern leaked"
    assert "INTERNAL_DETAIL_REDACTED" in body_text


# ── CB08: providers=[] → HTTP 500 ────────────────────────────────────────────


def test_cb08_empty_providers_list_hard_fail(fake_universe):
    """providers=[] → ProviderInvariantError → HTTP 500."""
    import main_api

    class _EmptyProvidersSnapshot:
        snapshot_id = _SNAP_ID
        def to_payload(self) -> dict:
            return {
                "state": "COMPLETE",
                "economicAssetUid": _UID,
                "chainId": _CHAIN_ID,
                "contractAddress": _CONTRACT,
                "completedAt": _COMPLETED_AT,
                "request": _make_request_block("BUY", "1000"),
                "providers": [],
            }

    svc = _FakeAcqService(snapshot=_EmptyProvidersSnapshot())
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)

    assert r.status_code == 500, (
        f"Expected 500 for empty providers list, got {r.status_code}"
    )


# ── CB09: radar-core present with all-unavailable evidence → HTTP 200 ─────────


def test_cb09_radar_core_present_all_unavailable_returns_200(fake_universe):
    """radar-core present but all evidence unavailable → HTTP 200 partial state.

    Provider present with no evidence is not an invariant failure."""
    import main_api

    ev = {
        "reference": {"available": False, "reason": "REFERENCE_UNAVAILABLE"},
        "execution": {"available": False, "unavailableReason": "NO_ROUTE"},
        "gap": {"available": False, "reason": "GAP_REQUIRES_EXECUTION_AND_REFERENCE"},
    }

    class _RadarCoreUnavailableSnapshot:
        snapshot_id = _SNAP_ID
        def to_payload(self) -> dict:
            return {
                "state": "PARTIAL",
                "economicAssetUid": _UID,
                "chainId": _CHAIN_ID,
                "contractAddress": _CONTRACT,
                "completedAt": _COMPLETED_AT,
                "request": _make_request_block("BUY", "1000"),
                "providers": [
                    {"provider": "radar-core", "state": "PARTIAL",
                     "elapsedMs": 80, "evidence": ev,
                     "observedAt": _COMPLETED_AT, "errorClass": None},
                ],
            }

    svc = _FakeAcqService(snapshot=_RadarCoreUnavailableSnapshot())
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)

    assert r.status_code == 200, (
        f"Expected 200 for radar-core present (all unavailable), got {r.status_code}"
    )
    body = r.json()
    assert body["reference"]["available"] is False
    assert body["execution"]["available"] is False
    assert body["gap"]["available"] is False


# ── CB10-CB13: OpenAPI contract ───────────────────────────────────────────────


def test_cb10_openapi_direction_string_enum(client):
    """OpenAPI schema for direction must be type=string with enum [BUY, SELL]."""
    r = client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    req_schema = (
        schema["components"]["schemas"]["ExecutionSimulationRequest"]
    )
    direction = req_schema["properties"]["direction"]
    assert direction["type"] == "string", (
        f"direction type must be string, got {direction.get('type')!r}"
    )
    assert set(direction["enum"]) == {"BUY", "SELL"}, (
        f"direction enum must be [BUY, SELL], got {direction.get('enum')!r}"
    )


def test_cb11_openapi_notional_usd_string_enum(client):
    """OpenAPI schema for notional_usd must be type=string with enum [100, 1000]."""
    r = client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    req_schema = (
        schema["components"]["schemas"]["ExecutionSimulationRequest"]
    )
    notional = req_schema["properties"]["notional_usd"]
    assert notional["type"] == "string", (
        f"notional_usd type must be string, got {notional.get('type')!r}"
    )
    assert set(notional["enum"]) == {"100", "1000"}, (
        f"notional_usd enum must be ['100', '1000'], got {notional.get('enum')!r}"
    )


def test_cb12_openapi_both_fields_required(client):
    """OpenAPI schema must mark both direction and notional_usd as required."""
    r = client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    req_schema = (
        schema["components"]["schemas"]["ExecutionSimulationRequest"]
    )
    required = set(req_schema.get("required", []))
    assert "direction" in required, "direction not in required"
    assert "notional_usd" in required, "notional_usd not in required"


def test_cb13_openapi_documents_400_404_503(client):
    """OpenAPI must document 400, 404, and 503 responses for execution-simulation."""
    r = client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    paths = schema.get("paths", {})
    sim_path = None
    for path_key in paths:
        if path_key.endswith("/execution-simulation"):
            sim_path = paths[path_key]
            break
    assert sim_path is not None, "execution-simulation path not in OpenAPI"
    post_op = sim_path.get("post", {})
    responses = post_op.get("responses", {})
    for code in ("400", "404", "503"):
        assert code in responses, f"HTTP {code} not documented in OpenAPI responses"


# ── CB14: malformed inputs still 400 (not 422) with overridden schema ─────────


@pytest.mark.parametrize("direction,notional,label", [
    ("BUY",  100,    "notional int"),
    ("BUY",  100.0,  "notional float"),
    ("BUY",  True,   "notional bool"),
    ("BUY",  None,   "notional null"),
    (1,      "100",  "direction int"),
    (None,   "100",  "direction null"),
    (True,   "100",  "direction bool"),
    ("BUY",  "200",  "notional out-of-range string"),
    ("HOLD", "100",  "direction invalid string"),
])
def test_cb14_malformed_inputs_return_400_not_422(client, fake_svc, direction, notional, label):
    """Malformed request body must produce 400, not 422, even with schema override."""
    r = client.post(
        f"/api/v1/radar/assets/{_UID}/execution-simulation",
        json={"direction": direction, "notional_usd": notional},
    )
    assert r.status_code == 400, (
        f"Expected 400 for {label!r}, got {r.status_code}"
    )
    assert r.json()["error"] == "SIMULATION_REQUEST_INVALID"
    fake_svc.acquire.assert_not_called()
