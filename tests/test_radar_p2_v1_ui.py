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
                                              "size": "100"},
                           headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert len(calls) == 1


def test_ui_06_response_binds_exactly_one_snapshot_id(make_client):
    calls: list = []
    c = make_client(_build_service(calls))
    response = c.post("/radar/refresh", data={"direction": "BUY",
                                              "size": "100"},
                           headers={"HX-Request": "true"})
    ids = _snapshot_ids(response.text)
    assert len(ids) >= 1
    assert len(set(ids)) == 1


def test_ui_07_all_panels_carry_the_same_snapshot_id(make_client):
    calls: list = []
    c = make_client(_build_service(calls))
    response = c.post("/radar/refresh", data={"direction": "BUY",
                                              "size": "100"},
                           headers={"HX-Request": "true"})
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
                                           "size": "1000"},
                           headers={"HX-Request": "true"}).text
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
                                              "size": "100"},
                           headers={"HX-Request": "true"})
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
                                              "size": "100"},
                           headers={"HX-Request": "true"})
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
                                              "size": "100"},
                           headers={"HX-Request": "true"})
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


# ==========================================================================
# Correction A — browser + snapshot binding closure (A1-A6)
# ==========================================================================

from types import SimpleNamespace


def test_ca2_01_before_refresh_no_snapshot_authority_claimed(make_client):
    page = make_client(_build_service([])).get("/radar").text
    assert "Configured target asset" in page
    assert 'data-panel="identity"' not in page
    assert "acq-snap:" not in page


def test_ca2_02_identity_panel_bound_to_refresh_snapshot(make_client):
    calls: list = []
    c = make_client(_build_service(calls))
    response = c.post("/radar/refresh", data={"direction": "BUY",
                                              "size": "100"},
                      headers={"HX-Request": "true"})
    snapshot_id = _snapshot_ids(response.text)[0]
    assert 'data-panel="identity"' in response.text
    identity_ids = re.findall(
        r'(<section class="panel panel-identity"[^>]*data-snapshot-id=")'
        r"(acq-snap:[0-9a-f]{64})", response.text)
    assert identity_ids and identity_ids[0][1] == snapshot_id
    assert "AAPL" in response.text  # uid from the snapshot evidence


def test_ca2_03_historical_identity_survives_config_change(make_client):
    calls: list = []
    store = SnapshotStore(":memory:")
    service = _build_service(calls, store=store)
    c = make_client(service)
    response = c.post("/radar/refresh", data={"direction": "BUY",
                                              "size": "100"},
                      headers={"HX-Request": "true"})
    snapshot_id = _snapshot_ids(response.text)[0]
    original_address = composition.asset_config()["contractAddress"]

    # environment configuration changes after the snapshot exists
    import os
    os.environ["RADAR_V1_ASSET_ADDRESS"] = "0x" + "bb" * 20
    try:
        historical = c.get(f"/radar/snapshot/{snapshot_id}").text
        assert original_address in historical  # persisted identity wins
        assert ("0x" + "bb" * 20) not in historical
    finally:
        os.environ.pop("RADAR_V1_ASSET_ADDRESS", None)


def test_ca3_04_reference_identity_mismatch_fails_closed():
    def fake_registry(uid, address, chain_id=4663):
        key = SimpleNamespace(chain_id=chain_id, contract_address=address)
        asset_record = SimpleNamespace(
            asset_uid=uid, token_symbol="AAPL",
            deployment_for_chain=lambda c: key if c == chain_id else None)
        registry_snapshot = SimpleNamespace(
            find_by_symbol=lambda sym: [asset_record])
        return SimpleNamespace(
            fetch_snapshot=lambda: registry_snapshot,
            fetch_bound_reference=lambda snap, key: ({}, {}))

    source = composition.composition_radar_source(
        registry_factory=lambda: fake_registry(
            "AAPL", "0x" + "bb" * 20))  # wrong contract
    request_obj = composition.build_request("BUY", "100")
    result = source(request_obj)
    reference = result["evidence"]["reference"]
    assert reference["available"] is False
    assert reference["reason"] == "REFERENCE_IDENTITY_MISMATCH"
    # execution/gap must not regain availability from a mismatched reference
    assert result["evidence"]["execution"]["available"] is False
    assert result["evidence"]["gap"]["available"] is False


def test_ca3_05_reference_uid_mismatch_fails_closed():
    source = composition.composition_radar_source(
        registry_factory=lambda: _fake_registry_uid(
            "MSFT", composition.asset_config()["contractAddress"]))
    request_obj = composition.build_request("BUY", "100")
    result = source(request_obj)
    assert (result["evidence"]["reference"]["reason"]
            == "REFERENCE_IDENTITY_MISMATCH")


def _fake_registry_uid(uid, address):
    key = SimpleNamespace(chain_id=4663, contract_address=address)
    asset_record = SimpleNamespace(
        asset_uid=uid, token_symbol="AAPL",
        deployment_for_chain=lambda c: key if c == 4663 else None)
    registry_snapshot = SimpleNamespace(
        find_by_symbol=lambda sym: [asset_record])
    return SimpleNamespace(
        fetch_snapshot=lambda: registry_snapshot,
        fetch_bound_reference=lambda snap, key: ({}, {}))


def test_ca3_06_exact_identity_binding_passes_helper():
    from app.radar_ui.composition import bind_reference_identity
    key = SimpleNamespace(chain_id=4663,
                          contract_address="0xAAAAAAAAAAAAAAAAAAAAAAAA"
                                           "AAAAAAAAAAAAAAAAAA")
    asset_record = SimpleNamespace(asset_uid="AAPL")
    # exact UID + chain + contract (case-insensitive EVM address semantics)
    bind_reference_identity(asset_record, key,
                            economic_asset_uid="AAPL", chain_id=4663,
                            contract_address="0xaaaaaaaaaaaaaaaaaaaaaaaa"
                                             "aaaaaaaaaaaaaaaaaa")
    with pytest.raises(composition.ReferenceIdentityMismatch):
        bind_reference_identity(asset_record, key,
                                economic_asset_uid="MSFT", chain_id=4663,
                                contract_address=key.contract_address)
    with pytest.raises(composition.ReferenceIdentityMismatch):
        bind_reference_identity(asset_record, key,
                                economic_asset_uid="AAPL", chain_id=1,
                                contract_address=key.contract_address)


def test_ca3_07_snapshot_evidence_identity_is_bound_identity():
    # through the service: the preserved evidence identity equals the
    # requested canonical identity (never a mixture)
    calls: list = []
    service = _build_service(calls)
    snapshot = service.acquire(composition.build_request("BUY", "100"))
    payload = snapshot.to_payload()
    evidence = payload["providers"][0]["evidence"]
    assert evidence["asset"]["economicAssetUid"] == "AAPL"
    assert evidence["asset"]["chainId"] == payload["chainId"]
    assert evidence["asset"]["contractAddress"] == payload["contractAddress"]


def test_ca4_08_every_rendered_inspector_link_resolves(make_client):
    calls: list = []
    c = make_client(_build_service(calls))
    refresh = c.post("/radar/refresh", data={"direction": "BUY",
                                             "size": "100"},
                     headers={"HX-Request": "true"})
    snapshot_id = _snapshot_ids(refresh.text)[0]
    links = re.findall(
        r'href="(/radar/inspector/([^"]+)/([^"]+))"', refresh.text)
    assert links, "panel fragment must render inspector links"
    fields = {field for _, _, field in links}
    assert "reference.source" in fields  # A4: previously broken link
    for href, snapshot_id_in_link, field in links:
        assert snapshot_id_in_link == snapshot_id
        response = c.get(href)
        assert response.status_code == 200
        assert "UNKNOWN_FIELD" not in response.text, field
        assert snapshot_id in response.text
    assert len(calls) == 1  # following links never reacquires


def test_ca5_09_field_specific_authority_timestamps(make_client):
    calls: list = []
    evidence = {
        "reference": {"available": True, "price": "101.25",
                      "observedAt": "2026-09-19T11:59:00+00:00"},
        "execution": {"available": True, "side": "BUY",
                      "status": "QUOTE_OK",
                      "quotedAt": "2026-09-19T11:58:00+00:00"},
        "gap": {"available": True, "gapBps": "-42.5",
                "quotedAt": "2026-09-19T11:57:00+00:00"},
    }
    service = _build_service(
        calls, providers={"radar-core": _fake_core(
            calls, evidence=evidence,
            observed_at="2026-09-19T12:00:00+00:00")})
    c = make_client(service)
    refresh = c.post("/radar/refresh", data={"direction": "BUY",
                                             "size": "100"},
                     headers={"HX-Request": "true"})
    snapshot_id = _snapshot_ids(refresh.text)[0]
    expected = {"reference.price": "2026-09-19T11:59",
                "execution.status": "2026-09-19T11:58",
                "gap.gapBps": "2026-09-19T11:57"}
    for field, timestamp in expected.items():
        inspector = c.get(f"/radar/inspector/{snapshot_id}/{field}").text
        assert timestamp in inspector, field
    # the provider-wrapper observation time stays a SEPARATE lineage row
    gap_inspector = c.get(f"/radar/inspector/{snapshot_id}/gap.gapBps").text
    assert "12:00" in gap_inspector
    assert "Acquisition/provider observation time" in gap_inspector


def test_ca5_10_missing_field_timestamp_shows_unavailable(make_client):
    calls: list = []
    evidence = {"reference": {"available": True, "price": "101.25"}}
    service = _build_service(
        calls, providers={"radar-core": _fake_core(calls, evidence=evidence,
                                                   observed_at="2026-09-19"
                                                           "T12:00:00+00:00")})
    c = make_client(service)
    refresh = c.post("/radar/refresh", data={"direction": "BUY",
                                             "size": "100"},
                     headers={"HX-Request": "true"})
    snapshot_id = _snapshot_ids(refresh.text)[0]
    inspector = c.get(f"/radar/inspector/{snapshot_id}/reference.price").text
    # reference.observedAt absent -> explicit UNAVAILABLE, never the
    # provider-wrapper time substituted in
    assert "UNAVAILABLE" in inspector


def test_ca6_11_execution_unavailable_reason_fidelity(make_client):
    calls: list = []
    evidence = {
        "reference": {"available": True, "price": "101.25",
                      "observedAt": "2026-09-19T11:59:00+00:00"},
        "execution": {"available": False, "side": "BUY",
                      "notionalUsd": "100",
                      "status": "INSUFFICIENT_LIQUIDITY",
                      "unavailableReason": "SOME_TYPED_REASON",
                      "source": "LIFI_V1_QUOTE",
                      "quotedAt": "2026-09-19T11:58:00+00:00"},
        "gap": {"available": False,
                "reason": "GAP_REQUIRES_EXECUTION_AND_REFERENCE"},
    }
    service = _build_service(
        calls, providers={"radar-core": _fake_core(calls, evidence=evidence)})
    c = make_client(service)
    page = c.post("/radar/refresh", data={"direction": "BUY",
                                          "size": "100"},
                  headers={"HX-Request": "true"}).text
    assert "INSUFFICIENT_LIQUIDITY" in page   # exact frozen status
    assert "SOME_TYPED_REASON" in page        # exact frozen reason
    assert "NOT_PROVIDED_BY_ACQUISITION" not in page
    snapshot_id = _snapshot_ids(page)[0]
    inspector = c.get(f"/radar/inspector/{snapshot_id}/execution.status").text
    assert "INSUFFICIENT_LIQUIDITY" in inspector
    assert "SOME_TYPED_REASON" in inspector


# ==========================================================================
# Correction B — final UI contract closure (B1-B5)
# ==========================================================================

def test_cb_license_01_htmx_version_and_0bsd_metadata():
    js = Path("static/radar/vendor/htmx.min.js").read_text(encoding="utf-8")
    assert "1.9.12" in js  # vendored version identity
    license_path = Path("static/radar/vendor/htmx.min.js.LICENSE")
    assert license_path.exists()
    license_text = license_path.read_text(encoding="utf-8")
    assert "htmx.org v1.9.12" in license_text
    assert "SPDX-License-Identifier: 0BSD" in license_text
    assert "0BSD" in license_text
    assert "BSD 2-Clause" not in license_text  # incorrect claim removed


def _inspector_stages(inspector_html: str) -> dict:
    stages: dict = {}
    parts = inspector_html.split('<div class="inspector-stage ')
    for part in parts[1:]:
        stage_name = part.split('"', 1)[0]
        stages[stage_name] = part
    return stages


def _unavailable_execution_snapshot(make_client, calls: list) -> str:
    evidence = {
        "reference": {"available": True, "price": "101.25",
                      "observedAt": "2026-09-19T11:59:00+00:00"},
        "execution": {"available": False, "side": "BUY",
                      "notionalUsd": "100",
                      "status": "INSUFFICIENT_LIQUIDITY",
                      "unavailableReason": "SOME_TYPED_REASON",
                      "source": "LIFI_V1_QUOTE",
                      "quotedAt": "2026-09-19T11:58:00+00:00"},
        "gap": {"available": False,
                "reason": "GAP_REQUIRES_EXECUTION_AND_REFERENCE"},
    }
    service = _build_service(
        calls, providers={"radar-core": _fake_core(calls, evidence=evidence)})
    c = make_client(service)
    page = c.post("/radar/refresh", data={"direction": "BUY",
                                          "size": "100"},
                  headers={"HX-Request": "true"}).text
    return _snapshot_ids(page)[0], c


def test_cb_number_02_execution_status_in_stage_number_not_unavailable(
    make_client):
    calls: list = []
    snapshot_id, c = _unavailable_execution_snapshot(make_client, calls)
    inspector = c.get(
        f"/radar/inspector/{snapshot_id}/execution.status").text
    stages = _inspector_stages(inspector)
    assert "INSUFFICIENT_LIQUIDITY" in stages["stage-number"]
    # UNAVAILABLE must not replace the known frozen status in NUMBER
    assert '<p class="state-unavailable">UNAVAILABLE</p>' not in stages[
        "stage-number"]
    assert "UNAVAILABLE" not in stages["stage-number"]


def test_cb_reason_03_typed_reason_preserved_in_gap_stage(make_client):
    calls: list = []
    snapshot_id, c = _unavailable_execution_snapshot(make_client, calls)
    inspector = c.get(
        f"/radar/inspector/{snapshot_id}/execution.status").text
    stages = _inspector_stages(inspector)
    assert "SOME_TYPED_REASON" in stages["stage-gaps"]
    assert "SECTION_UNAVAILABLE" in stages["stage-gaps"]
    # the reason belongs to the gap stage, not the NUMBER stage
    assert "SOME_TYPED_REASON" not in stages["stage-number"]


def test_cb_links_04_every_inspector_link_full_interaction_contract(
    make_client):
    calls: list = []
    c = make_client(_build_service(calls))
    page = c.post("/radar/refresh", data={"direction": "BUY",
                                          "size": "100"},
                  headers={"HX-Request": "true"}).text
    snapshot_id = _snapshot_ids(page)[0]
    anchors = re.findall(
        r'<a class="inspector-link" ([^>]*)>(.*?)</a>', page)
    assert anchors, "panels must render inspector links"
    fields = set()
    for attrs, _text in anchors:
        def attr(name):
            match = re.search(name + r'="([^"]+)"', attrs)
            assert match is not None, f"{name} missing on {attrs}"
            return match.group(1)
        href = attr("href")
        hx_get = attr("hx-get")
        assert href == hx_get
        assert attr("hx-target") == "#radar-inspector"
        assert attr("hx-swap") == "innerHTML"
        assert snapshot_id in href
        field = href.rsplit("/", 1)[1]
        fields.add(field)
        response = c.get(href)
        assert response.status_code == 200
        assert "UNKNOWN_FIELD" not in response.text
        assert snapshot_id in response.text
        assert len(calls) == 1  # following links never reacquires
    assert "reference.source" in fields
    # the macro guarantees the contract on every link; no bare links remain
    bare = re.findall(r'<a class="inspector-link" href="[^"]*"(?![^>]*hx-get)',
                      page)
    assert not bare


# ── Correction A regression tests ────────────────────────────────────────────


def test_correction_a_notional_100_rendered_without_k_suffix(make_client):
    """$100 is presented as '$100', never '$100k'."""
    calls: list = []
    c = make_client(_build_service(calls))
    # Controls page must show $100 not $100k
    page = c.get("/radar").text
    assert "$100" in page
    assert "$100k" not in page
    # Post-refresh panels must also show $100 not $100k
    resp = c.post("/radar/refresh", data={"direction": "BUY", "size": "100"},
                  headers={"HX-Request": "true"})
    assert "$100" in resp.text
    assert "$100k" not in resp.text


def test_correction_a_notional_1000_rendered_as_1000_with_comma(make_client):
    """$1000 is presented as '$1,000', never '$1000k' or '$1,000k'."""
    calls: list = []
    c = make_client(_build_service(calls))
    # Controls page must show $1,000 not $1000k / $1,000k
    page = c.get("/radar").text
    assert "$1,000" in page
    assert "$1000k" not in page
    assert "$1,000k" not in page
    # Post-refresh panels must also show $1,000 not $1000k
    resp = c.post("/radar/refresh", data={"direction": "BUY", "size": "1000"},
                  headers={"HX-Request": "true"})
    assert "$1,000" in resp.text
    assert "$1000k" not in resp.text
    assert "$1,000k" not in resp.text


def test_correction_b_gap_label_is_directional_not_model_market(make_client):
    """Summary row must show 'Directional GAP', not 'Model / Market GAP'."""
    calls: list = []
    c = make_client(_build_service(calls))
    resp = c.post("/radar/refresh", data={"direction": "BUY", "size": "100"},
                  headers={"HX-Request": "true"})
    assert "Directional GAP" in resp.text
    assert "Model / Market GAP" not in resp.text


def test_correction_c_no_unsupported_liquidity_claim_in_idle_state(make_client):
    """Empty-state copy must not advertise 'Liquidity' as a rendered panel."""
    page = make_client(_build_service([])).get("/radar").text
    # Confirm the idle-state panel is present and does not mention Liquidity
    assert "panel-idle" in page
    assert "Liquidity" not in page


def test_correction_f_read_only_boundary_intact(make_client):
    """READ-ONLY state chip present; no wallet connect / sign / submit controls."""
    page = make_client(_build_service([])).get("/radar").text
    assert "READ-ONLY" in page
    # The READ-ONLY disclaimer explicitly says "no wallet, no signing…" — that
    # text is correct authority copy. What must be absent is any interactive
    # control that would enable those actions.
    for forbidden_control in (
        "connect wallet", "sign transaction", "submit transaction",
        "send transaction", "approve transaction",
    ):
        assert forbidden_control not in page.lower(), (
            f"Forbidden control phrase '{forbidden_control}' found on Radar page"
        )
