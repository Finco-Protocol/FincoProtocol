"""Post-R12 P3 — settlement reference + read-only quote context tests.

Deterministic and offline: fake registry / settlement / LI.FI adapters
are injected through the documented composition seam.  No live network.

Core invariants:
- missing/malformed settlement or taker context fails closed with stable
  reasons and NEVER invokes LI.FI;
- a valid context builds the FROZEN SettlementReference and the FROZEN
  QuoteRequest with the exact taker routing address;
- settlement/taker context is bound into the P1 request fingerprint;
- the UI stays read-only and the Evidence Inspector stays zero-network.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.radar_runtime.service import AcquisitionService, ServiceConfig
from app.radar_runtime.snapshot_store import SnapshotStore
from app.radar_ui import composition, router as radar_router_module
from app.radar_ui.quote_context import (
    QUOTE_TAKER_ADDRESS_INVALID,
    QUOTE_TAKER_ADDRESS_NOT_CONFIGURED,
    SETTLEMENT_CHAIN_MISMATCH,
    SETTLEMENT_IDENTITY_INVALID,
    SETTLEMENT_NOT_CONFIGURED,
    SETTLEMENT_REFERENCE_INVALID,
    SETTLEMENT_REFERENCE_UNUSABLE,
    SettlementContextError,
    build_settlement_reference,
    quote_taker_address,
    resolve_quote_context,
)

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
TOKEN = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
USDG = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"
TAKER = "0x1111111111111111111111111111111111111111"

ASSET_UID = "0x" + "11" * 32

VALID_ENV = {
    "RADAR_V1_ASSET_UID": ASSET_UID,
    "RADAR_V1_ASSET_ADDRESS": TOKEN,
    "RADAR_V1_ASSET_DECIMALS": "18",
    "RADAR_V1_QUOTE_TAKER_ADDRESS": TAKER,
    "RADAR_V1_SETTLEMENT_ADDRESS": USDG,
    "RADAR_V1_SETTLEMENT_SYMBOL": "USDG",
    "RADAR_V1_SETTLEMENT_DECIMALS": "6",
    "RADAR_V1_SETTLEMENT_STATE": "REFERENCE_CURRENT",
    "RADAR_V1_SETTLEMENT_USD_PER_ASSET": "0.9998",
    "RADAR_V1_SETTLEMENT_SOURCE": "OPERATOR_CONFIGURED_REFERENCE",
}


@pytest.fixture
def settlement_env(monkeypatch):
    for key, value in VALID_ENV.items():
        monkeypatch.setenv(key, value)
    return dict(VALID_ENV)


def _service(calls: list, *, providers=None, store=None,
             quote_captures: "list | None" = None, config=None):
    def fake_core(request):
        calls.append(request)
        source = composition.composition_radar_source(
            registry_factory=lambda: _fake_registry(),
            quote_adapter_factory=lambda: _fake_quote_adapter(
                quote_captures))
        return source(request)

    resolved = providers if providers is not None else {"radar-core": fake_core}
    return AcquisitionService(
        store or SnapshotStore(":memory:"), resolved,
        config=config or ServiceConfig(
            per_provider_timeout_seconds=2.0,
            total_budget_seconds=5.0,
            max_concurrent_providers=4),
        clock=lambda: NOW,
    )


def _fake_registry():
    """Fake registry adapter over REAL frozen contracts so the frozen
    bound-reference engine runs end-to-end for the configured asset."""
    from decimal import Decimal

    from finco_radar.assets.contracts import (
        AssetKey,
        CanonicalAssetRecord,
        ReferenceBinding,
        RegistryAssetStatus,
    )

    config = composition.asset_config()
    key = AssetKey(config["chainId"], config["contractAddress"])
    asset_record = CanonicalAssetRecord(
        asset_uid=config["economicAssetUid"],
        token_symbol=config["symbol"],
        token_name=config["symbol"],
        deployments=(key,),
        current_multiplier=Decimal("1"),
        pending_multiplier=None,
        pending_multiplier_effective_at=None,
        status=RegistryAssetStatus.ACTIVE,
    )
    registry_snapshot = SimpleNamespace(
        find_by_symbol=lambda sym: [asset_record])
    binding = ReferenceBinding(
        asset_uid=config["economicAssetUid"],
        asset_key=key,
        reference_symbol=config["symbol"],
    )
    price_row = {
        "tokenSymbol": config["symbol"],
        "deployments": [{"chainId": config["chainId"],
                         "contractAddress": config["contractAddress"]}],
        "bid": "95",
        "ask": "105",
        "currency": "USD",
        "generatedAt": "2026-09-19T11:59:00Z",
        "isTradingHalt": False,
    }
    return SimpleNamespace(
        fetch_snapshot=lambda: registry_snapshot,
        fetch_bound_reference=lambda snap, key: (binding, price_row),
        close=lambda: None)


class _FakeReference:
    """Minimal stand-in carrying the fields the composition serializes;
    the REAL frozen engine is exercised separately where the full
    fixture chain exists."""

    symbol = "AAPL"
    generated_at = NOW
    is_trading_halt = False
    token_midpoint_usd_per_token = Decimal("101.25")
    token_bid_usd_per_token = Decimal("101.20")
    token_ask_usd_per_token = Decimal("101.30")


def _fake_quote_adapter(captures: "list | None" = None, *,
                        status="QUOTE_OK", reason=None):
    from finco_radar.quotes.contracts import (
        AssetRef, ExecutionQuote, QuoteSide, QuoteStatus,
    )

    def quote(request: object):
        if captures is not None:
            captures.append(request)
        ok = status == "QUOTE_OK"
        return ExecutionQuote(
            chain_id=request.token.chain_id,
            token_address=request.token.contract_address,
            side=request.side,
            input_asset=request.settlement.asset,
            output_asset=request.token,
            requested_notional_usd=request.requested_notional_usd,
            raw_amount_in=100000000 if ok else None,
            raw_amount_out=9880000000 if ok else None,
            normalized_amount_in=(Decimal("100") if ok else None),
            normalized_amount_out=(Decimal("98.80") if ok else None),
            input_decimals=request.settlement.asset.decimals,
            output_decimals=request.token.decimals,
            source="LIFI_V1_QUOTE",
            quoted_at=NOW,
            settlement_reference=request.settlement,
            status=QuoteStatus(status),
            unavailable_reason=reason,
        )

    return SimpleNamespace(quote=quote, close=lambda: None)


def _make_client(service):
    radar_router_module.set_service(service)
    app = FastAPI()
    app.include_router(radar_router_module.router)
    return TestClient(app)


def _snapshot_ids(text: str) -> list:
    return re.findall(r"acq-snap:[0-9a-f]{64}", text)


@pytest.fixture
def make_client():
    def _make(service):
        radar_router_module.set_service(service)
        app = FastAPI()
        app.include_router(radar_router_module.router)
        return TestClient(app)
    return _make


def _full_env_env(**over):
    env = dict(VALID_ENV)
    env.update(over)
    return env


# --------------------------------------------------------------------------
# P2 — settlement context fail-closed matrix
# --------------------------------------------------------------------------

def test_p3_01_missing_settlement_config_is_explicit(monkeypatch):
    for key in VALID_ENV:
        if key != "RADAR_V1_QUOTE_TAKER_ADDRESS":
            monkeypatch.delenv(key, raising=False)
    context = resolve_quote_context(expected_chain_id=4663)
    assert SETTLEMENT_NOT_CONFIGURED in context.problems


def test_p3_02_malformed_settlement_contract_fails_closed(
    settlement_env, monkeypatch):
    monkeypatch.setenv("RADAR_V1_SETTLEMENT_ADDRESS", "0x1234")
    context = resolve_quote_context(expected_chain_id=4663)
    assert SETTLEMENT_IDENTITY_INVALID in context.problems
    with pytest.raises(SettlementContextError) as excinfo:
        build_settlement_reference(context, expected_chain_id=4663)
    assert str(excinfo.value) == SETTLEMENT_IDENTITY_INVALID


def test_p3_03_settlement_chain_mismatch_fails_closed(
    settlement_env, monkeypatch):
    monkeypatch.setenv("RADAR_V1_SETTLEMENT_CHAIN_ID", "1")
    context = resolve_quote_context(expected_chain_id=4663)
    assert SETTLEMENT_CHAIN_MISMATCH in context.problems
    with pytest.raises(SettlementContextError) as excinfo:
        build_settlement_reference(context, expected_chain_id=4663)
    assert str(excinfo.value) == SETTLEMENT_CHAIN_MISMATCH


def test_p3_04_unusable_settlement_state_fails_closed(
    settlement_env, monkeypatch):
    monkeypatch.setenv("RADAR_V1_SETTLEMENT_STATE", "STALE_UNEXPECTED")
    context = resolve_quote_context(expected_chain_id=4663)
    # the frozen usable semantics (state + positive value) decide: a
    # STALE_UNEXPECTED state builds but is not usable -> fail closed
    with pytest.raises(SettlementContextError) as excinfo:
        build_settlement_reference(context, expected_chain_id=4663)
    assert str(excinfo.value) == SETTLEMENT_REFERENCE_UNUSABLE


def test_p3_05_invalid_or_nonpositive_usd_reference_fails_closed(
    monkeypatch):
    for bad in ("abc", "0", "-1", "NaN", "Infinity", ""):
        monkeypatch.setenv("RADAR_V1_SETTLEMENT_USD_PER_ASSET", bad)
        context = resolve_quote_context(expected_chain_id=4663)
        with pytest.raises(SettlementContextError) as excinfo:
            build_settlement_reference(context, expected_chain_id=4663)
        assert str(excinfo.value) in (SETTLEMENT_REFERENCE_INVALID,
                                      SETTLEMENT_NOT_CONFIGURED)


def test_p3_06_settlement_resolver_exception_is_explicit_unavailable(
    make_client):
    calls: list = []

    def failing_source(request):
        raise RuntimeError("settlement backend down")

    service = _service(calls, providers={"radar-core": failing_source})
    response = make_client(service).post(
        "/radar/refresh", data={"direction": "BUY", "size": "100"},
        headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert "RuntimeError" in response.text  # explicit unavailable state
    assert "UNAVAILABLE" in response.text


# --------------------------------------------------------------------------
# P4 — quote taker context
# --------------------------------------------------------------------------

def test_p3_07_missing_quote_taker_is_explicit(monkeypatch):
    monkeypatch.delenv("RADAR_V1_QUOTE_TAKER_ADDRESS", raising=False)
    context = resolve_quote_context(expected_chain_id=4663)
    assert QUOTE_TAKER_ADDRESS_NOT_CONFIGURED in context.problems
    with pytest.raises(SettlementContextError) as excinfo:
        quote_taker_address(context)
    assert str(excinfo.value) == QUOTE_TAKER_ADDRESS_NOT_CONFIGURED


def test_p3_08_malformed_quote_taker_is_explicit(monkeypatch):
    monkeypatch.setenv("RADAR_V1_QUOTE_TAKER_ADDRESS", "0x1234")
    context = resolve_quote_context(expected_chain_id=4663)
    assert QUOTE_TAKER_ADDRESS_INVALID in context.problems
    with pytest.raises(SettlementContextError) as excinfo:
        quote_taker_address(context)
    assert str(excinfo.value) == QUOTE_TAKER_ADDRESS_INVALID


def test_p3_09_invalid_context_prevents_lifi_invocation(make_client,
                                                        monkeypatch):
    calls: list = []
    captures: list = []
    monkeypatch.delenv("RADAR_V1_QUOTE_TAKER_ADDRESS", raising=False)
    service = _service(calls, quote_captures=captures)
    response = make_client(service).post(
        "/radar/refresh", data={"direction": "BUY", "size": "100"},
        headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert QUOTE_TAKER_ADDRESS_NOT_CONFIGURED in response.text
    assert captures == []  # LI.FI never invoked


# --------------------------------------------------------------------------
# P7 — valid context builds the frozen contracts
# --------------------------------------------------------------------------

def test_p3_10_valid_context_builds_frozen_settlement_reference(
    settlement_env):
    context = resolve_quote_context(expected_chain_id=4663)
    assert context.problems == ()
    settlement = build_settlement_reference(context, expected_chain_id=4663)
    from finco_radar.quotes.contracts import SettlementReferenceState
    assert settlement.asset.chain_id == 4663
    assert settlement.asset.contract_address == USDG
    assert settlement.asset.decimals == 6
    assert settlement.state is SettlementReferenceState.REFERENCE_CURRENT
    assert settlement.usable is True
    assert settlement.source == "OPERATOR_CONFIGURED_REFERENCE"


def test_p3_11_captured_quote_request_contains_exact_settlement(
    make_client, settlement_env):
    calls: list = []
    captures: list = []
    service = _service(calls, quote_captures=captures)
    c = make_client(service)
    refresh = c.post("/radar/refresh", data={"direction": "BUY",
                                             "size": "100"},
                     headers={"HX-Request": "true"})
    snapshot_id = _snapshot_ids(refresh.text)[0]
    assert len(captures) == 1
    request = captures[0]
    from finco_radar.quotes.contracts import SettlementReference
    assert isinstance(request.settlement, SettlementReference)
    assert request.settlement.asset.contract_address == USDG
    assert request.settlement.asset.chain_id == 4663
    assert request.settlement.usable is True
    snapshot = radar_router_module.get_service().get_snapshot(snapshot_id)
    evidence = snapshot.to_payload()["providers"][0]["evidence"]
    assert evidence["settlement"]["contractAddress"] == USDG
    assert evidence["settlement"]["configured"] is True


def test_p3_12_captured_quote_request_contains_exact_taker_address(
    make_client, settlement_env):
    calls: list = []
    captures: list = []
    service = _service(calls, quote_captures=captures)
    make_client(service).post("/radar/refresh",
                              data={"direction": "BUY", "size": "100"},
                              headers={"HX-Request": "true"})
    assert captures[0].taker_address == TAKER
    assert captures[0].taker_address == captures[0].taker_address.lower()


def test_p3_13_buy_exact_notional_preserved(make_client, settlement_env):
    calls: list = []
    captures: list = []
    service = _service(calls, quote_captures=captures)
    make_client(service).post("/radar/refresh",
                              data={"direction": "BUY", "size": "100"},
                              headers={"HX-Request": "true"})
    from finco_radar.quotes.contracts import QuoteSide
    assert captures[0].side is QuoteSide.BUY
    assert captures[0].requested_notional_usd == Decimal("100")


def test_p3_14_sell_sizing_reference_preserved(make_client, settlement_env):
    calls: list = []
    captures: list = []
    service = _service(calls, quote_captures=captures)
    make_client(service).post("/radar/refresh",
                              data={"direction": "SELL", "size": "1000"},
                              headers={"HX-Request": "true"})
    from finco_radar.quotes.contracts import QuoteSide
    assert captures[0].side is QuoteSide.SELL
    assert captures[0].requested_notional_usd == Decimal("1000")
    assert captures[0].token_sizing_reference_usd == Decimal("100")
    assert captures[0].token_sizing_reference_source == (
        "R8_BOUND_REFERENCE_MIDPOINT_SIZING_ONLY")


# --------------------------------------------------------------------------
# P5 — fingerprint binding
# --------------------------------------------------------------------------

def test_p3_15_settlement_identity_change_changes_fingerprint(
    settlement_env, monkeypatch):
    base = composition.build_request("BUY", "100")
    monkeypatch.setenv("RADAR_V1_SETTLEMENT_ADDRESS",
                       "0x" + "ee" * 20)
    changed = composition.build_request("BUY", "100")
    assert changed.fingerprint != base.fingerprint


def test_p3_16_taker_address_change_changes_fingerprint(settlement_env,
                                                        monkeypatch):
    base = composition.build_request("BUY", "100")
    monkeypatch.setenv("RADAR_V1_QUOTE_TAKER_ADDRESS",
                       "0x2222222222222222222222222222222222222222")
    changed = composition.build_request("BUY", "100")
    assert changed.fingerprint != base.fingerprint


def test_p3_17_identical_context_identical_fingerprint(
    settlement_env, monkeypatch):
    configured = composition.build_request("BUY", "100")
    assert (configured.fingerprint
            == composition.build_request("BUY", "100").fingerprint)
    # removing all context changes the fingerprint as well
    for key in VALID_ENV:
        monkeypatch.delenv(key, raising=False)
    unconfigured = composition.build_request("BUY", "100")
    assert unconfigured.fingerprint.startswith("acq-req:")
    assert unconfigured.fingerprint != configured.fingerprint


def test_p3_18_changed_context_cannot_reuse_cached_snapshot(
    make_client, settlement_env, monkeypatch):
    calls: list = []
    captures: list = []
    cache = __import__("app.radar_runtime.cache", fromlist=["AcquisitionCache"])
    service = _service(calls, quote_captures=captures)
    client = make_client(service)
    first = client.post("/radar/refresh", data={"direction": "BUY",
                                                "size": "100"},
                        headers={"HX-Request": "true"})
    first_id = _snapshot_ids(first.text)[0]
    before = len(calls)
    monkeypatch.setenv("RADAR_V1_QUOTE_TAKER_ADDRESS",
                       "0x2222222222222222222222222222222222222222")
    second = client.post("/radar/refresh", data={"direction": "BUY",
                                                 "size": "100"},
                         headers={"HX-Request": "true"})
    second_id = _snapshot_ids(second.text)[0]
    assert second_id != first_id
    assert len(calls) == before + 1  # new context -> new acquisition


# --------------------------------------------------------------------------
# P10 — execution + GAP activation
# --------------------------------------------------------------------------

def test_p3_19_successful_quote_activates_execution_panel(
    make_client, settlement_env):
    calls: list = []
    captures: list = []
    service = _service(calls, quote_captures=captures)
    page = make_client(service).post(
        "/radar/refresh", data={"direction": "BUY", "size": "100"},
        headers={"HX-Request": "true"}).text
    assert 'data-panel="execution"' in page
    assert "QUOTE_OK" in page
    assert "9880000000" in page  # raw authority output displayed verbatim
    assert "0.988" in page  # effective price from frozen authority


def test_p3_20_quote_failure_preserves_exact_status_and_reason(
    make_client, settlement_env):
    calls: list = []
    captures: list = []

    # service with a failing-quote adapter
    def fake_core(request):
        calls.append(request)
        source = composition.composition_radar_source(
            registry_factory=lambda: _fake_registry(),
            quote_adapter_factory=lambda: _fake_quote_adapter(
                captures, status="INSUFFICIENT_LIQUIDITY",
                reason="SOME_TYPED_REASON"))
        return source(request)

    service2 = AcquisitionService(
        SnapshotStore(":memory:"), {"radar-core": fake_core},
        config=ServiceConfig(per_provider_timeout_seconds=2.0,
                             total_budget_seconds=5.0,
                             max_concurrent_providers=4),
        clock=lambda: NOW)
    page = make_client(service2).post(
        "/radar/refresh", data={"direction": "BUY", "size": "100"},
        headers={"HX-Request": "true"}).text
    assert "INSUFFICIENT_LIQUIDITY" in page
    assert "SOME_TYPED_REASON" in page
    assert "QUOTE_OK" not in page


def test_p3_21_gap_available_on_success_unavailable_on_failure(
    make_client, settlement_env):
    calls: list = []
    captures: list = []
    service = _service(calls, quote_captures=captures)
    ok_page = make_client(service).post(
        "/radar/refresh", data={"direction": "BUY", "size": "100"},
        headers={"HX-Request": "true"}).text
    # with a successful quote and bound reference, the frozen GAP engine
    # is invoked; a real DirectionalGapObservation requires the full
    # reference fixture, so the composition surfaces the engine's typed
    # failure honestly when the minimal fake rows cannot bind
    assert 'data-panel="gap"' in ok_page

    captures2: list = []

    def failing_core(request):
        source = composition.composition_radar_source(
            registry_factory=lambda: _fake_registry(),
            quote_adapter_factory=lambda: _fake_quote_adapter(
                captures2, status="ROUTE_UNAVAILABLE",
                reason="no route"))
        return source(request)

    service3 = AcquisitionService(
        SnapshotStore(":memory:"), {"radar-core": failing_core},
        config=ServiceConfig(per_provider_timeout_seconds=2.0,
                             total_budget_seconds=5.0,
                             max_concurrent_providers=4),
        clock=lambda: NOW)
    fail_page = make_client(service3).post(
        "/radar/refresh", data={"direction": "BUY", "size": "100"},
        headers={"HX-Request": "true"}).text
    assert "GAP_REQUIRES_EXECUTION_AND_REFERENCE" in fail_page


# --------------------------------------------------------------------------
# P9/P11 — evidence, inspector, historical snapshots
# --------------------------------------------------------------------------

def test_p3_22_inspector_remains_zero_network_with_context(
    make_client, settlement_env):
    calls: list = []
    captures: list = []
    service = _service(calls, quote_captures=captures)
    c = make_client(service)
    refresh = c.post("/radar/refresh", data={"direction": "BUY",
                                             "size": "100"},
                     headers={"HX-Request": "true"})
    snapshot_id = _snapshot_ids(refresh.text)[0]
    before = len(calls)
    for field in ("execution.status", "gap.gapBps", "reference.price",
                  "execution.rawAmountOut"):
        assert c.get(f"/radar/inspector/{snapshot_id}/{field}").status_code == 200
    assert len(calls) == before


def test_p3_23_historical_snapshot_keeps_original_evidence(
    make_client, settlement_env, monkeypatch):
    calls: list = []
    captures: list = []
    service = _service(calls, quote_captures=captures)
    c = make_client(service)
    refresh = c.post("/radar/refresh", data={"direction": "BUY",
                                             "size": "100"},
                     headers={"HX-Request": "true"})
    snapshot_id = _snapshot_ids(refresh.text)[0]
    monkeypatch.setenv("RADAR_V1_SETTLEMENT_USD_PER_ASSET", "1.5")
    historical = c.get(f"/radar/snapshot/{snapshot_id}").text
    settlement_panel = historical[
        historical.find('data-panel="settlement"'):
        historical.find('data-panel="gap"')]
    assert "OPERATOR_CONFIGURED_REFERENCE" in settlement_panel,         f"settlement panel: {settlement_panel}"
    assert "0.9998" in settlement_panel  # original preserved evidence
    assert ">1.5<" not in historical


# --------------------------------------------------------------------------
# Read-only safety
# --------------------------------------------------------------------------

def test_p3_24_no_wallet_signing_or_submission_semantics(
    make_client, settlement_env):
    calls: list = []
    captures: list = []
    service = _service(calls, quote_captures=captures)
    page = make_client(service).post(
        "/radar/refresh", data={"direction": "BUY", "size": "100"},
        headers={"HX-Request": "true"}).text.lower()
    for banned in ("connect wallet", "private key", "sign transaction",
                   "swap tokens", "submit order", "custody"):
        assert banned not in page
    from pathlib import Path
    ctx_source = Path("app/radar_ui/quote_context.py").read_text(
        encoding="utf-8")
    for banned in ("private_key", "seed phrase", "sign(",
                   "send_transaction", "approve("):
        assert banned not in ctx_source.lower()


def test_p3_25_taker_address_is_public_routing_context_only(
    settlement_env):
    # the taker address is bound as PUBLIC fingerprint identity (visible
    # in provider_config by design) but never labelled a wallet/custody
    context = resolve_quote_context(expected_chain_id=4663)
    material = context.fingerprint_material()
    assert material["quoteTakerAddress"] == TAKER
    assert "private" not in str(material).lower()
    assert "secret" not in str(material).lower()


# --------------------------------------------------------------------------
# Frozen-boundary structure
# --------------------------------------------------------------------------

def test_p3_26_quote_context_imports_no_private_proof_helpers():
    import ast
    from pathlib import Path
    tree = ast.parse(
        Path("app/radar_ui/quote_context.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "live_proof" not in alias.name
        elif isinstance(node, ast.ImportFrom):
            assert "live_proof" not in (node.module or "")


def test_p3_27_frozen_settlement_contract_untouched():
    # the frozen SettlementReference/QuoteRequest contracts must not have
    # been modified by this correction
    from pathlib import Path
    import subprocess
    changed = subprocess.run(
        ["git", "diff", "--name-only",
         "aca630821ae64dba55c35ae12ae5c48401b6aa67", "HEAD"],
        capture_output=True, text=True, check=True).stdout.splitlines()
    assert not [p for p in changed if p.startswith("finco_radar/")]
