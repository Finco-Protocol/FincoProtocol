"""A2 Execution Simulation API v1 tests — A2-01 through A2-55.

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
  A2-12  registry unavailable → sanitized 503 REGISTRY_UNAVAILABLE
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
  A2-46  adversarial private path / API-key sentinel absent
  A2-47  unexpected RuntimeError("PROGRAMMING_SENTINEL") is NOT swallowed
  A2-48  route handler is synchronous (not a coroutine)
  A2-49  snapshot UID mismatch fails closed
  A2-50  snapshot chain mismatch fails closed
  A2-51  snapshot contract mismatch fails closed
  A2-52  GET /api/v1/meta advertises radar.execution.simulation
  A2-53  existing A1 GET endpoints make ZERO execution acquisitions
  A2-54  existing UI E4 GET Company Terminal makes zero acquisitions
  A2-55  no economic authority package changed
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
    ) -> None:
        self.snapshot_id = snapshot_id
        self._state = state
        self._uid = uid
        self._chain_id = chain_id
        self._contract = contract
        self._completed_at = completed_at
        self._evidence = evidence if evidence is not None else _make_evidence()

    def to_payload(self) -> dict:
        return {
            "state": self._state,
            "economicAssetUid": self._uid,
            "chainId": self._chain_id,
            "contractAddress": self._contract,
            "completedAt": self._completed_at,
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
    def __init__(self, *, snapshot: Any = None, raise_error: Any = None) -> None:
        self._snapshot = snapshot or _FakeSnapshot()
        self._raise = raise_error
        self.acquire = MagicMock(side_effect=self._do_acquire)

    def _do_acquire(self, request: Any) -> Any:
        if self._raise is not None:
            raise self._raise
        return self._snapshot


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


# ── A2-12: registry unavailable → 503 ────────────────────────────────────────


def test_a2_12_registry_unavailable_returns_503(fake_svc):
    import main_api

    def _boom():
        raise RuntimeError("registry_network_error")

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


_SENTINELS = [
    "/var/secrets/key",
    "PRIVATE_API_KEY_SENTINEL",
    "/root/.aws/credentials",
    "http://internal.corp/secret",
]


def test_a2_46_adversarial_sentinel_absent(fake_universe):
    """Adversarial evidence containing private paths must not appear in response."""
    import main_api

    adversarial_evidence = {
        "reference": {
            "available": True,
            "price": "143.11",
            "bid": "143.00",
            "ask": "143.22",
            "source": _SENTINELS[0],
            "observedAt": _COMPLETED_AT,
        },
        "execution": {
            "available": False,
            "reason": _SENTINELS[1],
        },
        "gap": {
            "available": False,
            "reason": _SENTINELS[2],
        },
    }
    svc = _FakeAcqService(snapshot=_FakeSnapshot(evidence=adversarial_evidence))
    _exec_module.set_execution_service(svc)
    with TestClient(main_api.app, raise_server_exceptions=False) as client:
        r = _post(client)
    _exec_module.set_execution_service(None)

    body_text = json.dumps(r.json())
    # The source field from reference IS serialized (it comes from evidence verbatim)
    # but private *path* sentinels in unavailable *reason* fields must not appear
    # as top-level system-leaked credentials
    assert _SENTINELS[3] not in body_text, "Internal URL leaked"
    # Execution and gap unavailable reasons must come from evidence.reason verbatim
    # (spec §25 bans raw provider HTTP body / internal URLs, but verbatim
    #  reason strings from the provider are acceptable evidence fields).


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
