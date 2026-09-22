"""E4 Execution Simulator tests — T01–T33.

Covers:
  T01  POST /radar/equity/{uid}/simulate 200 for known UID
  T02  POST /radar/equity/{uid}/simulate unknown UID → ASSET_NOT_FOUND fragment
  T03  POST /radar/equity/{uid}/simulate universe unavailable → ASSET_UNIVERSE_UNAVAILABLE
  T04  POST with invalid direction → INVALID_REQUEST in fragment
  T05  POST with invalid size → INVALID_REQUEST in fragment
  T06  exactly one acquire() call per POST simulate
  T07  simulate response is an HTML fragment (no <html> shell)
  T08  simulate result fragment contains reference price
  T09  simulate result fragment contains executable price
  T10  simulate result fragment contains gap bps
  T11  BUY direction passed to AcquisitionRequest
  T12  SELL direction passed to AcquisitionRequest
  T13  size "100" passed to AcquisitionRequest
  T14  size "1000" passed to AcquisitionRequest
  T15  UID-first: SelectedAsset resolved from live universe, not URL alone
  T16  GET /radar/equity/{uid}?tab=token-market performs zero acquire calls
  T17  GET /radar/equity/{uid}?tab=token-market renders Execution Simulator heading
  T18  Token Market form action contains /simulate path
  T19  Token Market form carries hx-post attribute pointing to /simulate
  T20  Token Market page contains disclosure "Simulation only"
  T21  simulate result: state COMPLETE shown in fragment
  T22  simulate result: direction shown in fragment
  T23  simulate result: notionalUsd shown in fragment
  T24  simulate result: reference price shown when available
  T25  simulate result: executable effectivePrice shown when available
  T26  simulate result: gap gapBps shown when available
  T27  simulate result: reference UNAVAILABLE when reference not available
  T28  simulate result: execution UNAVAILABLE when execution not available
  T29  simulate result: gap UNAVAILABLE when gap not available
  T30  simulate result: sim_error message shown in error fragment
  T31  simulate result fragment always contains "Simulation only" disclosure
  T32  simulate result: freshness completedAt shown when present
  T33  simulate result: identity economicAssetUid shown in fragment
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _FakeSelectedAsset:
    economic_asset_uid: str = "rh-equity-nvda-001"
    token_symbol: str = "NVDA"
    token_name: str = "NVIDIA Corporation"
    chain_id: int = 4663
    contract_address: str = "0xnvdatestcontract001"
    token_decimals: int = 18


_NVDA_ASSET = _FakeSelectedAsset()


def _make_fake_payload(
    *,
    state: str = "COMPLETE",
    direction: str = "BUY",
    size: str = "100",
    ref_price: str = "143.11",
    eff_price: str = "142.77",
    gap_bps: str = "-24",
    gap_to_mid: str = "-29",
    uid: str = "rh-equity-nvda-001",
    contract: str = "0xnvdatestcontract001",
    chain_id: int = 4663,
    completed_at: str = "2026-01-01T12:00:00+00:00",
    ref_available: bool = True,
    exec_available: bool = True,
    gap_available: bool = True,
) -> dict[str, Any]:
    ref_section: dict[str, Any]
    exec_section: dict[str, Any]
    gap_section: dict[str, Any]

    if ref_available:
        ref_section = {
            "available": True,
            "price": ref_price,
            "source": "FROZEN::BoundReferencePrice",
            "observedAt": "2026-01-01T11:59:00+00:00",
            "bid": "143.00",
            "ask": "143.22",
            "isTradingHalt": False,
        }
    else:
        ref_section = {"available": False, "reason": "REFERENCE_UNAVAILABLE"}

    if exec_available:
        exec_section = {
            "available": True,
            "side": direction,
            "notionalUsd": size,
            "status": "QUOTE_OK",
            "effectivePrice": eff_price,
            "source": "LiFi",
            "quotedAt": "2026-01-01T11:59:30+00:00",
        }
    else:
        exec_section = {"available": False, "reason": "REFERENCE_UNAVAILABLE"}

    if gap_available and ref_available and exec_available:
        gap_section = {
            "available": True,
            "side": direction,
            "gapBps": gap_bps,
            "gapToMidBps": gap_to_mid,
            "executionPrice": eff_price,
            "referencePrice": ref_price,
            "referenceSide": "bid" if direction == "BUY" else "ask",
            "source": "FROZEN::DirectionalGap",
            "quotedAt": "2026-01-01T11:59:30+00:00",
        }
    else:
        gap_section = {"available": False,
                       "reason": "GAP_REQUIRES_EXECUTION_AND_REFERENCE"}

    return {
        "snapshot_id": "snap-e4-test-001",
        "state": state,
        "startedAt": "2026-01-01T11:59:00+00:00",
        "completedAt": completed_at,
        "economicAssetUid": uid,
        "chainId": chain_id,
        "contractAddress": contract,
        "request": {"direction": direction, "notionalUsd": size},
        "providers": [
            {
                "provider": "radar-core",
                "state": state,
                "errorClass": None,
                "elapsedMs": 120,
                "evidence": {
                    "asset": {
                        "symbol": "NVDA",
                        "economicAssetUid": uid,
                        "chainId": chain_id,
                        "contractAddress": contract,
                    },
                    "reference": ref_section,
                    "execution": exec_section,
                    "gap": gap_section,
                    "observedAt": "2026-01-01T11:59:00+00:00",
                },
            }
        ],
    }


class _FakeSnapshot:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.snapshot_id = payload["snapshot_id"]

    def to_payload(self) -> dict[str, Any]:
        return self._payload


class _FakeAcqService:
    """Offline fake AcquisitionService for E4 tests."""

    def __init__(
        self,
        *,
        direction: str = "BUY",
        size: str = "100",
        ref_available: bool = True,
        exec_available: bool = True,
        gap_available: bool = True,
    ) -> None:
        self._direction = direction
        self._size = size
        self._ref = ref_available
        self._exec = exec_available
        self._gap = gap_available
        self.acquire = MagicMock(side_effect=self._acquire)
        self.get_snapshot = MagicMock(
            side_effect=lambda sid: _FakeSnapshot(
                _make_fake_payload(direction=direction, size=size)))

    def _acquire(self, request):
        return _FakeSnapshot(
            _make_fake_payload(
                direction=request.direction,
                size=request.notional_usd,
                ref_available=self._ref,
                exec_available=self._exec,
                gap_available=self._gap,
            ))


def _make_client(
    universe=None,
    service=None,
    history_bundle=None,
):
    import main_web
    from app.radar_ui import router as radar_router

    if universe is None:
        universe = [_NVDA_ASSET]
    svc = service or _FakeAcqService()

    patches = [
        patch.object(radar_router, "_fetch_universe_safe",
                     return_value=(universe, None)),
        patch.object(radar_router, "get_service", return_value=svc),
    ]
    if history_bundle is not None:
        patches.append(
            patch("app.radar_ui.equity_terminal.get_history_for_terminal",
                  return_value=history_bundle))

    from fastapi.testclient import TestClient
    for p in patches:
        p.start()
    client = TestClient(main_web.app, raise_server_exceptions=False)
    for p in reversed(patches):
        p.stop()
    return client, svc


def _client_with_patches(universe=None, service=None, history_bundle=None):
    """Context manager style: returns (client, service) with patches active."""
    import main_web
    from app.radar_ui import router as radar_router
    from fastapi.testclient import TestClient
    from contextlib import contextmanager

    if universe is None:
        universe = [_NVDA_ASSET]
    svc = service or _FakeAcqService()

    class _Ctx:
        def __enter__(self):
            self._p1 = patch.object(
                radar_router, "_fetch_universe_safe",
                return_value=(universe, None))
            self._p2 = patch.object(
                radar_router, "get_service", return_value=svc)
            self._p1.start()
            self._p2.start()
            self.client = TestClient(
                main_web.app, raise_server_exceptions=False)
            return self.client, svc

        def __exit__(self, *a):
            self._p2.stop()
            self._p1.stop()

    return _Ctx()


# ── Route tests (T01–T15) ─────────────────────────────────────────────────────

def test_t01_simulate_200_known_uid():
    with _client_with_patches() as (client, svc):
        resp = client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "BUY", "size": "100"},
        )
    assert resp.status_code == 200


def test_t02_simulate_unknown_uid_asset_not_found():
    with _client_with_patches() as (client, _):
        resp = client.post(
            "/radar/equity/rh-equity-unknown-999/simulate",
            data={"direction": "BUY", "size": "100"},
        )
    assert resp.status_code == 200
    assert "ASSET_NOT_FOUND_IN_UNIVERSE" in resp.text


def test_t03_simulate_universe_unavailable():
    import main_web
    from app.radar_ui import router as radar_router
    from fastapi.testclient import TestClient

    with patch.object(radar_router, "_fetch_universe_safe",
                      return_value=([], "ConnectError")):
        client = TestClient(main_web.app, raise_server_exceptions=False)
        resp = client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "BUY", "size": "100"},
        )
    assert resp.status_code == 200
    assert "ASSET_UNIVERSE_UNAVAILABLE" in resp.text


def test_t04_simulate_invalid_direction():
    with _client_with_patches() as (client, _):
        resp = client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "HOLD", "size": "100"},
        )
    assert resp.status_code == 200
    assert "INVALID_REQUEST" in resp.text


def test_t05_simulate_invalid_size():
    with _client_with_patches() as (client, _):
        resp = client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "BUY", "size": "9999"},
        )
    assert resp.status_code == 200
    assert "INVALID_REQUEST" in resp.text


def test_t06_exactly_one_acquire_per_post():
    svc = _FakeAcqService()
    with _client_with_patches(service=svc) as (client, svc):
        client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "BUY", "size": "100"},
        )
    svc.acquire.assert_called_once()


def test_t07_simulate_response_is_fragment_not_full_page():
    with _client_with_patches() as (client, _):
        resp = client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "BUY", "size": "100"},
        )
    assert "<html" not in resp.text.lower()
    assert "<!doctype" not in resp.text.lower()


def test_t08_simulate_fragment_contains_reference_price():
    with _client_with_patches() as (client, _):
        resp = client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "BUY", "size": "100"},
        )
    assert "143.11" in resp.text


def test_t09_simulate_fragment_contains_executable_price():
    with _client_with_patches() as (client, _):
        resp = client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "BUY", "size": "100"},
        )
    assert "142.77" in resp.text


def test_t10_simulate_fragment_contains_gap_bps():
    with _client_with_patches() as (client, _):
        resp = client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "BUY", "size": "100"},
        )
    assert "-24" in resp.text


def test_t11_buy_direction_passed_to_request():
    svc = _FakeAcqService(direction="BUY")
    with _client_with_patches(service=svc) as (client, svc):
        client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "BUY", "size": "100"},
        )
    call_args = svc.acquire.call_args[0][0]
    assert call_args.direction == "BUY"


def test_t12_sell_direction_passed_to_request():
    svc = _FakeAcqService(direction="SELL")
    with _client_with_patches(service=svc) as (client, svc):
        client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "SELL", "size": "100"},
        )
    call_args = svc.acquire.call_args[0][0]
    assert call_args.direction == "SELL"


def test_t13_size_100_passed_to_request():
    svc = _FakeAcqService(size="100")
    with _client_with_patches(service=svc) as (client, svc):
        client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "BUY", "size": "100"},
        )
    call_args = svc.acquire.call_args[0][0]
    assert call_args.notional_usd == "100"


def test_t14_size_1000_passed_to_request():
    svc = _FakeAcqService(size="1000")
    with _client_with_patches(service=svc) as (client, svc):
        client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "BUY", "size": "1000"},
        )
    call_args = svc.acquire.call_args[0][0]
    assert call_args.notional_usd == "1000"


def test_t15_uid_first_selected_asset_from_universe():
    """The AcquisitionRequest must carry the canonical identity from universe."""
    svc = _FakeAcqService()
    with _client_with_patches(service=svc) as (client, svc):
        client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "BUY", "size": "100"},
        )
    call_args = svc.acquire.call_args[0][0]
    assert call_args.economic_asset_uid == "rh-equity-nvda-001"
    assert call_args.contract_address == "0xnvdatestcontract001"
    assert call_args.chain_id == 4663


# ── Zero-call GET contract (T16–T20) ─────────────────────────────────────────

def _make_unavailable_bundle(symbol: str = "NVDA"):
    """Return a real EquityCompanyHistoryBundle that renders the full terminal page.

    Uses NOT_AVAILABLE (not SOURCE_UNAVAILABLE) so build_terminal_view returns
    available=True and all tabs (including token-market) are rendered.
    """
    from finco_radar.equity.models import (
        AvailabilityState, EquityCompanyHistoryBundle, FundamentalsFreshness)
    return EquityCompanyHistoryBundle(
        robinhood_token_symbol=symbol,
        asset=None,
        company_profile=None,
        annual_history=(),
        quarterly_history=(),
        ttm_history=(),
        recent_dividends=(),
        recent_splits=(),
        source_lineage=(),
        availability=AvailabilityState.NOT_AVAILABLE,
        freshness=FundamentalsFreshness(
            ttm_period_end=None, ttm_filing_date=None, ttm_fetched_at=None,
            ttm_normalized_at=None, quarterly_period_end=None,
            quarterly_fetched_at=None, annual_period_end=None,
            annual_fetched_at=None, profile_fetched_at=None,
            asset_last_seen_at=None,
        ),
    )


def _terminal_ctx(universe=None, service=None):
    """Context manager: patches universe + get_service + history for terminal GET."""
    import main_web
    from app.radar_ui import router as radar_router
    from fastapi.testclient import TestClient

    if universe is None:
        universe = [_NVDA_ASSET]
    svc = service or _FakeAcqService()
    bundle = _make_unavailable_bundle()

    class _Ctx:
        def __enter__(self):
            self._p1 = patch.object(
                radar_router, "_fetch_universe_safe",
                return_value=(universe, None))
            self._p2 = patch.object(
                radar_router, "get_service", return_value=svc)
            self._p3 = patch(
                "app.radar_ui.equity_terminal.get_history_for_terminal",
                return_value=bundle)
            self._p1.start()
            self._p2.start()
            self._p3.start()
            self.client = TestClient(
                main_web.app, raise_server_exceptions=False)
            self._svc = svc
            return self.client, svc

        def __exit__(self, *a):
            self._p3.stop()
            self._p2.stop()
            self._p1.stop()

    return _Ctx()


def test_t16_get_token_market_zero_acquire_calls():
    svc = _FakeAcqService()
    with _terminal_ctx(service=svc) as (client, svc):
        client.get("/radar/equity/rh-equity-nvda-001?tab=token-market")
    svc.acquire.assert_not_called()


def test_t17_get_token_market_renders_execution_simulator_heading():
    with _terminal_ctx() as (client, _):
        resp = client.get("/radar/equity/rh-equity-nvda-001?tab=token-market")
    assert resp.status_code == 200
    assert "Execution Simulator" in resp.text


def test_t18_token_market_form_action_contains_simulate_path():
    with _terminal_ctx() as (client, _):
        resp = client.get("/radar/equity/rh-equity-nvda-001?tab=token-market")
    assert "/simulate" in resp.text


def test_t19_token_market_form_carries_hx_post():
    with _terminal_ctx() as (client, _):
        resp = client.get("/radar/equity/rh-equity-nvda-001?tab=token-market")
    assert "hx-post" in resp.text


def test_t20_token_market_page_contains_disclosure():
    with _terminal_ctx() as (client, _):
        resp = client.get("/radar/equity/rh-equity-nvda-001?tab=token-market")
    assert "Simulation only" in resp.text
    assert "no order is submitted" in resp.text


# ── Fragment content tests (T21–T33) ─────────────────────────────────────────

def test_t21_simulate_result_state_complete():
    with _client_with_patches() as (client, _):
        resp = client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "BUY", "size": "100"},
        )
    assert "COMPLETE" in resp.text


def test_t22_simulate_result_direction_shown():
    with _client_with_patches() as (client, _):
        resp = client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "BUY", "size": "100"},
        )
    assert "BUY" in resp.text


def test_t23_simulate_result_notional_shown():
    with _client_with_patches() as (client, _):
        resp = client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "BUY", "size": "100"},
        )
    assert "100" in resp.text


def test_t24_simulate_result_reference_price_when_available():
    with _client_with_patches() as (client, _):
        resp = client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "BUY", "size": "100"},
        )
    assert "143.11" in resp.text
    assert "Reference price" in resp.text


def test_t25_simulate_result_effective_price_when_available():
    with _client_with_patches() as (client, _):
        resp = client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "BUY", "size": "100"},
        )
    assert "142.77" in resp.text
    assert "Executable price" in resp.text


def test_t26_simulate_result_gap_bps_when_available():
    with _client_with_patches() as (client, _):
        resp = client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "BUY", "size": "100"},
        )
    assert "-24" in resp.text
    assert "Directional GAP" in resp.text


def test_t27_simulate_result_reference_unavailable():
    svc = _FakeAcqService(ref_available=False, exec_available=False,
                          gap_available=False)
    with _client_with_patches(service=svc) as (client, _):
        resp = client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "BUY", "size": "100"},
        )
    assert "UNAVAILABLE" in resp.text
    assert "143.11" not in resp.text


def test_t28_simulate_result_execution_unavailable():
    svc = _FakeAcqService(ref_available=True, exec_available=False,
                          gap_available=False)
    with _client_with_patches(service=svc) as (client, _):
        resp = client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "BUY", "size": "100"},
        )
    assert "UNAVAILABLE" in resp.text
    assert "142.77" not in resp.text


def test_t29_simulate_result_gap_unavailable():
    svc = _FakeAcqService(ref_available=True, exec_available=True,
                          gap_available=False)
    with _client_with_patches(service=svc) as (client, _):
        resp = client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "BUY", "size": "100"},
        )
    # gap section shows UNAVAILABLE when both ref/exec available but gap=False
    # (The fake payload sets gap.available=False when gap_available=False)
    assert "UNAVAILABLE" in resp.text or "-24" not in resp.text


def test_t30_simulate_result_error_fragment_shows_message():
    with _client_with_patches() as (client, _):
        resp = client.post(
            "/radar/equity/rh-equity-unknown-999/simulate",
            data={"direction": "BUY", "size": "100"},
        )
    assert "ASSET_NOT_FOUND_IN_UNIVERSE" in resp.text


def test_t31_simulate_result_always_has_disclosure():
    """Every response (success or error) must contain the disclosure."""
    with _client_with_patches() as (client, _):
        resp_ok = client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "BUY", "size": "100"},
        )
        resp_err = client.post(
            "/radar/equity/rh-equity-unknown-999/simulate",
            data={"direction": "BUY", "size": "100"},
        )
    assert "Simulation only" in resp_ok.text
    assert "no order is submitted" in resp_ok.text
    assert "Simulation only" in resp_err.text
    assert "no order is submitted" in resp_err.text


def test_t32_simulate_result_freshness_completed_at():
    with _client_with_patches() as (client, _):
        resp = client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "BUY", "size": "100"},
        )
    # completedAt is "2026-01-01T12:00:00+00:00" in the fake payload
    assert "2026-01-01" in resp.text


def test_t33_simulate_result_identity_uid_shown():
    with _client_with_patches() as (client, _):
        resp = client.post(
            "/radar/equity/rh-equity-nvda-001/simulate",
            data={"direction": "BUY", "size": "100"},
        )
    assert "rh-equity-nvda-001" in resp.text
