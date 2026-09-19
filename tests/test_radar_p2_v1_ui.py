"""Post-R12 P2 — narrow Radar v1 UI + Evidence Inspector tests.

Deterministic and offline: the suite injects fake providers into the
canonical P1 acquisition service through the documented composition seam
and exercises the real router + templates.

Core invariant under test: one refresh -> ONE acquisition -> ONE
snapshot_id; every panel and the Evidence Inspector reference that exact
snapshot with zero further provider/network calls.
"""
from __future__ import annotations

import ast
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.radar_runtime.contracts import RuntimeContractError
from app.radar_runtime.service import AcquisitionService, ServiceConfig
from app.radar_runtime.snapshot_store import SnapshotStore
from app.radar_ui import composition, view_model
from app.radar_ui import router as radar_router_module

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
SECRET = "SUPER-SECRET-TOKEN"


def _fake_core(calls: list, *, evidence=None, observed_at="2026-09-19T12:00:00+00:00"):
    def provider(request):
        calls.append(request)
        payload = evidence or {
            "asset": {"symbol": "AAPL", "chainId": request.chain_id,
                      "contractAddress": request.contract_address,
                      "economicAssetUid": "AAPL"},
            "observedAt": observed_at,
            "reference": {"available": True, "price": "101.25",
                          "bid": "101.20", "ask": "101.30",
                          "source": "FROZEN::BoundReferencePrice",
                          "observedAt": "2026-09-19T11:59:00+00:00"},
            "execution": {"available": True, "side": request.direction,
                          "notionalUsd": request.notional_usd,
                          "status": "QUOTE_OK", "rawAmountIn": "100000000",
                          "rawAmountOut": "9880000000",
                          "effectivePrice": "101.30",
                          "source": "LIFI_V1_QUOTE",
                          "quotedAt": "2026-09-19T12:00:00+00:00"},
            "gap": {"available": True, "side": request.direction,
                    "gapBps": "-42.5", "gapToMidBps": "-12.5",
                    "source": "FROZEN::DirectionalGapObservation",
                    "quotedAt": "2026-09-19T12:00:00+00:00"},
        }
        return {"evidence": payload, "observedAt": observed_at}
    return provider


def _build_service(calls: list, *, providers=None, config=None, store=None):
    resolved = providers if providers is not None else {
        "radar-core": _fake_core(calls)}
    return AcquisitionService(
        store or SnapshotStore(":memory:"), resolved,
        config=config or ServiceConfig(
            per_provider_timeout_seconds=2.0,
            total_budget_seconds=5.0,
            max_concurrent_providers=4),
        clock=lambda: NOW,
    )


@pytest.fixture
def make_client():
    def _make(service):
        radar_router_module.set_service(service)
        app = FastAPI()
        app.include_router(radar_router_module.router)
        return TestClient(app)
    return _make


def _snapshot_ids(html: str) -> list:
    return re.findall(r"acq-snap:[0-9a-f]{64}", html)


# --------------------------------------------------------------------------
# Page, identity, controls
# --------------------------------------------------------------------------

def test_ui_01_radar_page_renders(make_client):
    c = make_client(_build_service([]))
    response = c.get("/radar")
    assert response.status_code == 200
    assert "FINCO" in response.text and "RADAR" in response.text.upper()
    assert "READ-ONLY" in response.text


def test_ui_02_canonical_asset_identity_visible(make_client):
    c = make_client(_build_service([]))
    page = c.get("/radar").text
    assert "AAPL" in page
    assert "4663" in page
    assert composition.asset_config()["contractAddress"] in page


def test_ui_03_buy_sell_controls_exist(make_client):
    page = make_client(_build_service([])).get("/radar").text
    assert 'name="direction"' in page
    assert 'value="BUY"' in page and 'value="SELL"' in page


def test_ui_04_only_reviewed_sizes_supported(make_client):
    page = make_client(_build_service([])).get("/radar").text
    assert 'value="100"' in page and 'value="1000"' in page
    assert 'type="number"' not in page  # no arbitrary size input
    with pytest.raises(RuntimeContractError):
        composition.build_request("BUY", "250")
    with pytest.raises(RuntimeContractError):
        composition.build_request("HOLD", "100")


# --------------------------------------------------------------------------
# P7 — one refresh -> ONE acquisition -> ONE snapshot_id
# --------------------------------------------------------------------------

def test_ui_05_one_refresh_exactly_one_acquisition(make_client):
    calls: list = []
    c = make_client(_build_service(calls))
    response = c.post("/radar/refresh", data={"direction": "BUY",
                                              "size": "100"})
    assert response.status_code == 200
    assert len(calls) == 1


def test_ui_06_response_binds_exactly_one_snapshot_id(make_client):
    calls: list = []
    c = make_client(_build_service(calls))
    response = c.post("/radar/refresh", data={"direction": "BUY",
                                              "size": "100"})
    ids = _snapshot_ids(response.text)
    assert len(ids) >= 1
    assert len(set(ids)) == 1


def test_ui_07_all_panels_carry_the_same_snapshot_id(make_client):
    calls: list = []
    c = make_client(_build_service(calls))
    response = c.post("/radar/refresh", data={"direction": "BUY",
                                              "size": "100"})
    panel_ids = re.findall(r'data-snapshot-id="(acq-snap:[0-9a-f]{64})"',
                           response.text)
    panels = re.findall(r'data-panel="([a-z-]+)"', response.text)
    assert len(panel_ids) == len(panels) and len(set(panel_ids)) == 1


# --------------------------------------------------------------------------
# Evidence Inspector — same snapshot, zero network
# --------------------------------------------------------------------------

def test_ui_08_inspector_reads_exact_same_snapshot(make_client):
    calls: list = []
    c = make_client(_build_service(calls))
    refresh = c.post("/radar/refresh", data={"direction": "BUY",
                                             "size": "100"})
    snapshot_id = _snapshot_ids(refresh.text)[0]
    inspector = c.get(f"/radar/inspector/{snapshot_id}/gap.gapBps")
    assert inspector.status_code == 200
    assert snapshot_id in inspector.text
    assert "NUMBER" in inspector.text and "VERIFICATION" in inspector.text
    assert "-42.5" in inspector.text


def test_ui_09_inspector_performs_zero_provider_or_network_calls(make_client):
    calls: list = []
    c = make_client(_build_service(calls))
    refresh = c.post("/radar/refresh", data={"direction": "BUY",
                                             "size": "100"})
    snapshot_id = _snapshot_ids(refresh.text)[0]
    before = len(calls)
    for field in ("reference.price", "execution.status", "gap.gapBps",
                  "snapshot.state"):
        assert c.get(f"/radar/inspector/{snapshot_id}/{field}").status_code == 200
        assert c.get(f"/radar/snapshot/{snapshot_id}").status_code == 200
    assert len(calls) == before, "inspector/read endpoints must never acquire"


def test_ui_10_changing_snapshot_id_changes_displayed_evidence(make_client):
    calls: list = []
    c = make_client(_build_service(calls))
    small = c.post("/radar/refresh", data={"direction": "BUY",
                                           "size": "100"}).text
    large = c.post("/radar/refresh", data={"direction": "SELL",
                                           "size": "1000"}).text
    small_id, large_id = _snapshot_ids(small)[0], _snapshot_ids(large)[0]
    assert small_id != large_id
    small_inspector = c.get(
        f"/radar/inspector/{small_id}/execution.rawAmountOut").text
    large_inspector = c.get(
        f"/radar/inspector/{large_id}/execution.rawAmountOut").text
    assert '"notionalUsd": "100"' in small_inspector
    assert '"notionalUsd": "1000"' in large_inspector
    assert small_id in small_inspector and large_id not in small_inspector


# --------------------------------------------------------------------------
# P8 — presentation authority: values verbatim, never recomputed
# --------------------------------------------------------------------------

def test_ui_11_reference_values_consumed_verbatim_not_recomputed(make_client):
    calls: list = []
    c = make_client(_build_service(calls))
    page = c.post("/radar/refresh", data={"direction": "BUY",
                                          "size": "100"}).text
    assert "101.25" in page and "101.20" in page and "101.30" in page


def test_ui_12_gap_consumed_from_authority_not_locally_derived(make_client):
    calls: list = []
    c = make_client(_build_service(calls))
    page = c.post("/radar/refresh", data={"direction": "BUY",
                                          "size": "100"}).text
    assert "-42.5" in page and "-12.5" in page
    assert "consumed, not recomputed" in page


# --------------------------------------------------------------------------
# P9 — partial / unavailable / per-provider failure states
# --------------------------------------------------------------------------

def test_ui_13_partial_snapshot_renders_cleanly(make_client):
    calls: list = []

    def slow(request):
        import time
        time.sleep(5)
        return {"evidence": {}}

    service = _build_service(
        calls,
        providers={"radar-core": _fake_core(calls),
                   "aux": slow},
        config=ServiceConfig(per_provider_timeout_seconds=0.15,
                             total_budget_seconds=5.0,
                             max_concurrent_providers=4))
    c = make_client(service)
    composition.set_configured_sources(("aux",))
    try:
        response = c.post("/radar/refresh", data={"direction": "BUY",
                                                  "size": "100"})
    finally:
        composition.set_configured_sources(())
    assert response.status_code == 200
    assert "PARTIAL" in response.text
    assert "TIMEOUT" in response.text
    assert "101.25" in response.text  # successful evidence preserved


def test_ui_14_unavailable_snapshot_renders_cleanly(make_client):
    def failing(request):
        return {"error": "provider down"}

    c = make_client(_build_service([], providers={"radar-core": failing}))
    response = c.post("/radar/refresh", data={"direction": "BUY",
                                              "size": "100"})
    assert response.status_code == 200
    assert "UNAVAILABLE" in response.text
    assert "PROVIDER_DECLARED_ERROR" in response.text


def test_ui_15_provider_timeout_renders_safely(make_client):
    def slow(request):
        import time
        time.sleep(5)
        return {"evidence": {}}

    service = _build_service(
        [], providers={"radar-core": slow},
        config=ServiceConfig(
            per_provider_timeout_seconds=0.15,
            total_budget_seconds=5.0,
            max_concurrent_providers=2))
    response = make_client(service).post("/radar/refresh",
                                         data={"direction": "BUY",
                                               "size": "100"})
    assert response.status_code == 200
    assert "TIMEOUT" in response.text
    assert "UNAVAILABLE" in response.text


def test_ui_16_invalid_provider_response_renders_safely(make_client):
    c = make_client(_build_service([], providers={"radar-core": lambda r: "bad"}))
    response = c.post("/radar/refresh", data={"direction": "BUY",
                                              "size": "100"})
    assert response.status_code == 200
    assert "INVALID_RESPONSE" in response.text


# --------------------------------------------------------------------------
# Read-only safety + secret hygiene
# --------------------------------------------------------------------------

def test_ui_17_provider_secrets_never_reach_html(make_client):
    def leaky(request):
        return {"error": f"Authorization: Bearer {SECRET}"}

    c = make_client(_build_service([], providers={"radar-core": leaky}))
    page = c.post("/radar/refresh", data={"direction": "BUY",
                                          "size": "100"}).text
    assert SECRET not in page
    assert "Bearer" not in page


def test_ui_18_provider_config_never_reaches_html(make_client):
    calls: list = []
    c = make_client(_build_service(calls))
    response = c.post("/radar/refresh", data={"direction": "BUY",
                                              "size": "100"})
    snapshot_id = _snapshot_ids(response.text)[0]
    inspector = c.get(f"/radar/inspector/{snapshot_id}/execution.status").text
    blob = response.text + inspector
    assert "providerConfig" not in blob
    assert "provider_config" not in blob


def test_ui_19_no_wallet_signing_or_trade_submission_exists(make_client):
    page = make_client(_build_service([])).get("/radar").text
    lowered = page.lower()
    for banned in ("connect wallet", "private key", "sign transaction",
                   "swap tokens", "token swap", "approve", "custody",
                   "submit order"):
        assert banned not in lowered, banned
    assert 'action="/radar/refresh"' in page or \
        'hx-post="/radar/refresh"' in page
    assert 'hx-post="/radar/refresh"' in page


# --------------------------------------------------------------------------
# Composition / frozen-boundary structure
# --------------------------------------------------------------------------

def test_ui_20_router_and_view_model_import_zero_frozen_authority():
    for module in ("app/radar_ui/router.py", "app/radar_ui/view_model.py"):
        tree = ast.parse(Path(module).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("finco_radar"), module
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("finco_radar"), module


def test_ui_20b_main_web_composition_includes_radar_router():
    source = Path("main_web.py").read_text(encoding="utf-8")
    assert "from app.radar_ui.router import router as _radar_router" in source
    assert "app.include_router(_radar_router)" in source


def test_ui_21_p1_runtime_surface_unchanged_by_ui_imports():
    # The UI consumes only the documented P1 public surface; it must not
    # reach into private P1 internals either.
    for module in ("app/radar_ui/router.py", "app/radar_ui/view_model.py"):
        tree = ast.parse(Path(module).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module_name = (node.module or "") if isinstance(
                    node, ast.ImportFrom) else ""
                for alias in (node.names if isinstance(node, ast.Import)
                              else []):
                    module_name = alias.name
                assert not module_name.startswith(
                    "app.radar_runtime.service._"), module_name


def test_ui_22_service_reuse_across_requests_keeps_persistence():
    calls: list = []
    store = SnapshotStore(":memory:")
    service = _build_service(calls, store=store)
    radar_router_module.set_service(service)
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(radar_router_module.router)
    c = TestClient(app)
    first = c.post("/radar/refresh", data={"direction": "BUY",
                                           "size": "100"})
    snapshot_id = _snapshot_ids(first.text)[0]
    # same request again -> cached snapshot reused, one snapshot only
    second = c.post("/radar/refresh", data={"direction": "BUY",
                                            "size": "100"})
    assert _snapshot_ids(second.text)[0] == snapshot_id
    assert len(calls) == 1
    assert store.get(snapshot_id) is not None
