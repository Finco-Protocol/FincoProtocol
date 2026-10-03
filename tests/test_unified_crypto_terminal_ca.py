"""Unified Crypto Terminal Correction A — yield access boundary, provenance,
bounded limits, single request clock, truthful meta."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_unified_crypto_terminal_v1 import (
    _patch_agent_a, _seed_venue_store)


@pytest.fixture()
def api_client(monkeypatch, tmp_path):
    _seed_venue_store(tmp_path / "venues.db")
    monkeypatch.setenv("FINCO_VENUE_DB_PATH", str(tmp_path / "venues.db"))
    from finco_yield.history import YieldHistoryStore
    from finco_yield.observation import ImmutableObservationRecord
    from finco_yield.registry import load_bundled_registry

    now = datetime.now(timezone.utc)
    store = YieldHistoryStore(tmp_path / "yield_history.jsonl")
    opp = load_bundled_registry().all()[0]
    for i in range(6):
        store.append(ImmutableObservationRecord(
            opportunity_uid=opp.uid,
            observed_at=now - timedelta(hours=0.2) if i == 5
            else now - timedelta(hours=(6 - i) * 24),
            source_authority="NATIVE_ENRICHED", source_uri="https://test",
            adapter_version="test",
            payload={"apy_total": "0.0440" if i == 5 else "0.0400",
                     "tvl_usd": "5000000"}))
    monkeypatch.setenv("FINCO_YIELD_HISTORY_PATH", str(store.path))
    monkeypatch.delenv("FINCO_TOKEN_GATING_ENABLED", raising=False)
    from app.protocol.entitlement_evaluator import Decision
    _patch_agent_a(monkeypatch, {"crypto.api": (Decision.ALLOW,
                                                "CRYPTO_API_ACTIVATED")})
    from app.api.v1.router import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def _activated_api(monkeypatch):
    """API app with crypto.api ACTIVATED (Agent-A patched)."""
    from app.protocol.entitlement_evaluator import Decision
    _patch_agent_a(monkeypatch, {"crypto.api": (Decision.ALLOW,
                                                "CRYPTO_API_ACTIVATED")})
    from app.api.v1.router import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def _deny_yield_history(monkeypatch):
    from finco_yield import access as access_mod
    from app.protocol.entitlement_evaluator import Decision, ResourceAccessDecision

    async def fake(resource_key, wallet):
        from finco_yield.access import YieldResource
        print("FAKE evaluate:", resource_key)
        if resource_key == YieldResource.HISTORY.value:
            return ResourceAccessDecision(
                resource_key=resource_key, decision=Decision.DENY,
                reason_code="BALANCE_BELOW_THRESHOLD", access_mode=None,
                wallet_address=None, chain_id=None, token_address=None,
                entitlement_state=None, observed_balance=None,
                minimum_balance=None, observed_at=None)
        return ResourceAccessDecision(
            resource_key=resource_key, decision=Decision.ALLOW,
            reason_code="ENTITLED", access_mode="FINCO_HOLDER",
            wallet_address=None, chain_id=None, token_address=None,
            entitlement_state="ACTIVE", observed_balance=None,
            minimum_balance=None, observed_at=None)

    monkeypatch.setattr(access_mod, "evaluate_resource_access", fake)


# ── yield premium access boundary ────────────────────────────────────────────

def test_yield_history_denied_returns_basic_without_protected_build(
        api_client, monkeypatch):
    """crypto.api ALLOW + yield.history DENY -> 200 BASIC pool detail, the
    protected history intelligence is never built (spy on the shared read
    boundary), and no protected field leaks."""
    _deny_yield_history(monkeypatch)

    import app.crypto_terminal.yield_read as yield_read_mod
    calls = []

    def _spy(store, uid, *, as_of):
        calls.append(uid)
        raise AssertionError("build_intelligence must not run when denied")

    monkeypatch.setattr(yield_read_mod, "build_intelligence", _spy)

    from finco_yield.registry import load_bundled_registry
    uid = load_bundled_registry().all()[0].uid
    response = api_client.get(f"/api/v1/crypto/yield/{uid}")
    body = response.json()
    data = body["data"]
    assert data["canonical_id"] == uid
    assert "current_apy" in data and "tvl_usd" in data
    assert data["history_intelligence_included"] is False
    assert not data.get("intel")            # protected intelligence absent
    assert data.get("market") is None       # protected market view absent
    assert calls == [], "protected history builder must not be invoked when denied"
    assert body["access"]["history"]["allowed"] is False
    assert body["access"]["history"]["reason"] == "BALANCE_BELOW_THRESHOLD"


def test_yield_history_allowed_builds_full_detail(api_client):
    from finco_yield.registry import load_bundled_registry
    uid = load_bundled_registry().all()[0].uid
    response = api_client.get(f"/api/v1/crypto/yield/{uid}")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["history_intelligence_included"] is True
    assert data.get("intel", {}).get("status") == "AVAILABLE"
    assert data.get("market") is not None
    assert response.json()["access"]["history"]["allowed"] is True


def test_yield_history_inactive_preserves_ungated_detail(api_client, monkeypatch):
    """yield.history INACTIVE -> access_allowed=True: existing ungated Yield
    behaviour fully preserved (merged #180 semantics, unchanged)."""
    from finco_yield import access as access_mod
    from app.protocol.entitlement_evaluator import Decision, ResourceAccessDecision

    async def inactive(resource_key, wallet):
        from finco_yield.access import YieldResource
        if resource_key == YieldResource.HISTORY.value:
            return ResourceAccessDecision(
                resource_key=resource_key, decision=Decision.INACTIVE,
                reason_code="TOKEN_ENTITLEMENT_FEATURE_INACTIVE",
                access_mode=None, wallet_address=None, chain_id=None,
                token_address=None, entitlement_state=None,
                observed_balance=None, minimum_balance=None, observed_at=None)
        return ResourceAccessDecision(
            resource_key=resource_key, decision=Decision.ALLOW,
            reason_code="ENTITLED", access_mode="FINCO_HOLDER",
            wallet_address=None, chain_id=None, token_address=None,
            entitlement_state="ACTIVE", observed_balance=None,
            minimum_balance=None, observed_at=None)

    monkeypatch.setattr(access_mod, "evaluate_resource_access", inactive)
    from finco_yield.registry import load_bundled_registry
    uid = load_bundled_registry().all()[0].uid
    response = api_client.get(f"/api/v1/crypto/yield/{uid}")
    assert response.status_code == 200
    body = response.json()
    assert body["access"]["history"]["allowed"] is True
    assert "intel" in body["data"]


# ── provenance: fixture vs source-observed ───────────────────────────────────

def test_yield_api_marks_reference_fixture_provenance(api_client):
    landing = api_client.get("/api/v1/crypto/yield")
    assert landing.status_code == 200
    summary = landing.json()["data"]["summary"]
    assert summary["provenance"]["source_status_origin"] == "REFERENCE_FIXTURE"
    for row in landing.json()["data"]["pools"]:
        assert row["data_origin"] == "REFERENCE_FIXTURE"
    detail = api_client.get(
        f"/api/v1/crypto/yield/{landing.json()['data']['pools'][0]['canonical_id']}")
    data = detail.json()["data"]
    assert data["data_origin"] == "REFERENCE_FIXTURE"
    assert data["origin"] == "REFERENCE"
    assert data["provenance"]["source_status_origin"] == "REFERENCE_FIXTURE"


def test_yield_api_distinguishes_source_observed_snapshot(api_client, monkeypatch):
    import dataclasses
    from finco_yield.snapshot import ORIGIN_SNAPSHOT, RegistrySourceStatus
    import app.crypto_terminal.yield_read as yread

    real_snapshot = yread.market_snapshot

    def with_snapshot(*, now=None, include_market=True):
        view = real_snapshot(now=now, include_market=include_market)
        patched = [dataclasses.replace(o, data_origin="SOURCE_OBSERVED")
                   for o in view["registry"].all()]
        from finco_yield.registry import YieldRegistry
        view["registry"] = YieldRegistry(patched)
        view["source_status"] = RegistrySourceStatus(
            ORIGIN_SNAPSHOT, None, view["as_of"].isoformat(),
            len(patched), 0, 0)
        return view

    monkeypatch.setattr(yread, "market_snapshot", with_snapshot)
    landing = api_client.get("/api/v1/crypto/yield")
    provenance = landing.json()["data"]["summary"]["provenance"]
    assert provenance["source_status_origin"] == "SNAPSHOT"
    rows = landing.json()["data"]["pools"]
    assert rows and all(row["data_origin"] == "SOURCE_OBSERVED" for row in rows)


# ── bounded limit ────────────────────────────────────────────────────────────

def test_tokenized_api_limit_is_bounded(tmp_path, monkeypatch):
    db = _seed_venue_store(tmp_path / "venues.db")
    monkeypatch.setenv("FINCO_VENUE_DB_PATH", str(db))
    from app.protocol.entitlement_evaluator import Decision
    _patch_agent_a(monkeypatch, {"crypto.api": (Decision.ALLOW,
                                                "CRYPTO_API_ACTIVATED")})
    from app.api.v1.router import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)
    ok = client.get("/api/v1/crypto/tokenized?limit=1")
    assert ok.status_code == 200
    assert ok.json()["data"]["showing"] <= 1
    for bad in ("0", "-1", "61", "100000"):
        response = client.get(f"/api/v1/crypto/tokenized?limit={bad}")
        assert response.status_code == 422, bad


# ── single request evaluation clock ──────────────────────────────────────────

def test_single_request_as_of_across_envelope_and_reads(
        api_client, tmp_path, monkeypatch):
    db = _seed_venue_store(tmp_path / "venues.db")
    monkeypatch.setenv("FINCO_VENUE_DB_PATH", str(db))
    import app.crypto_terminal.tokenized_read as tread
    import app.crypto_terminal.yield_read as yread

    captured = {}
    real_market = yread.market_snapshot

    def spy_market(*, now=None, include_market=True):
        captured["yield"] = now
        return real_market(now=now, include_market=include_market)

    monkeypatch.setattr(yread, "market_snapshot", spy_market)
    body = api_client.get("/api/v1/crypto/yield").json()
    assert captured["yield"].isoformat() == body["as_of"]

    real_landing = tread.landing_rows

    def spy_landing(*, gates, limit=None, now=None):
        captured["tokenized"] = now
        return real_landing(gates=gates, limit=limit, now=now)

    monkeypatch.setattr(tread, "landing_rows", spy_landing)
    body = api_client.get("/api/v1/crypto/tokenized").json()
    assert captured["tokenized"].isoformat() == body["as_of"]


# ── truthful meta ────────────────────────────────────────────────────────────

def test_meta_declares_crypto_api_configurable_but_inactive(api_client):
    meta = api_client.get("/api/v1/meta")
    assert meta.status_code == 200
    body = meta.json()
    assert body["crypto_api"]["state"] == "CONFIGURABLE_BUT_INACTIVE"
    assert body["crypto_api"]["activation_authority"] == "crypto.api"
    for capability in ("crypto.tokenized.read", "crypto.tokenized.history.read",
                       "crypto.tokenized.dislocation.read", "crypto.yield.read"):
        assert capability in body["capabilities"]


# ── Correction B: clock completion + fail-soft access authority ──────────────

def test_tokenized_history_envelope_uses_request_clock(tmp_path, monkeypatch):
    db = _seed_venue_store(tmp_path / "venues.db")
    monkeypatch.setenv("FINCO_VENUE_DB_PATH", str(db))
    client = _activated_api(monkeypatch)
    body = client.get("/api/v1/crypto/tokenized/NVDA/history").json()
    captured = {}

    # Re-request with a spy on the shared read to capture the request clock.
    import app.crypto_terminal.tokenized_read as tread
    real_detail = tread.detail

    def spy(canonical_asset_id, *, gates, now=None):
        captured["as_of"] = now
        return real_detail(canonical_asset_id, gates=gates, now=now)

    monkeypatch.setattr(tread, "detail", spy)
    body = client.get("/api/v1/crypto/tokenized/NVDA/history").json()
    assert captured["as_of"] is not None
    assert body["as_of"] == captured["as_of"].isoformat(), (
        "history envelope must use the SAME captured request clock as the read")


def test_tokenized_dislocation_envelope_uses_request_clock(tmp_path, monkeypatch):
    db = _seed_venue_store(tmp_path / "venues.db")
    monkeypatch.setenv("FINCO_VENUE_DB_PATH", str(db))
    client = _activated_api(monkeypatch)
    client.get("/api/v1/crypto/tokenized/NVDA/dislocations")
    import app.crypto_terminal.tokenized_read as tread
    captured = {}
    real_detail = tread.detail

    def spy(canonical_asset_id, *, gates, now=None):
        captured["as_of"] = now
        return real_detail(canonical_asset_id, gates=gates, now=now)

    monkeypatch.setattr(tread, "detail", spy)
    body = client.get("/api/v1/crypto/tokenized/NVDA/dislocations").json()
    assert captured["as_of"] is not None
    assert body["as_of"] == captured["as_of"].isoformat(), (
        "dislocation envelope must use the SAME captured request clock as the read")


def test_yield_access_authority_failure_fails_closed_not_500(api_client, monkeypatch):
    """crypto.api ALLOW + Yield HISTORY authority RAISING -> 200 basic pool
    detail, no protected build, typed authority-unavailable access state."""
    from finco_yield import access as access_mod
    from finco_yield.registry import load_bundled_registry

    async def broken(resource_key, wallet):
        raise RuntimeError("entitlement store unavailable")

    monkeypatch.setattr(access_mod, "evaluate_resource_access", broken)

    import app.crypto_terminal.yield_read as yield_read_mod
    build_calls = []

    def _spy(store, uid, *, as_of):
        build_calls.append(uid)
        raise AssertionError("build_intelligence must not run when the access "
                             "authority is unavailable")

    monkeypatch.setattr(yield_read_mod, "build_intelligence", _spy)

    uid = load_bundled_registry().all()[0].uid
    response = api_client.get(f"/api/v1/crypto/yield/{uid}")
    assert response.status_code == 200, "authority failure must not 500"
    body = response.json()
    data = body["data"]
    assert data["history_intelligence_included"] is False
    assert not data.get("intel")
    assert data.get("market") is None
    assert build_calls == []
    access = body["access"]["history"]
    assert access["allowed"] is False
    assert access["state"] == "ENTITLEMENT_AUTHORITY_UNAVAILABLE"
    assert access["reason"] == "ACCESS_AUTHORITY_ERROR"


def test_product_truth_acquisition_claims_are_precise():
    doc = open("docs/CRYPTO_TERMINAL_PRODUCT_TRUTH.md", encoding="utf-8").read()
    # Tokenized provider-free guarantee stays explicit...
    assert "Tokenized Markets" in doc and "acquisition-free" in doc
    # ...while the Treasury FRED-cache refresh is accurately described.
    assert "bounded local FRED cache" in doc
    # No universal "all reads are acquisition-free" overclaim remains.
    assert "Browser and API reads are acquisition-free" not in doc


# ── Correction B: A40 synchronous-handler contract ───────────────────────────

def test_crypto_api_handlers_are_plain_def():
    """Every Crypto API handler must be a plain synchronous def (API V1 A40
    concurrency contract): FastAPI dispatches them to the worker threadpool;
    the async entitlement adapters are bridged via _run_async only."""
    import asyncio
    import inspect
    from app.api.v1.crypto_router import router
    endpoints = [r for r in router.routes if hasattr(r, "endpoint")]
    assert len(endpoints) == 6
    for route in endpoints:
        assert not asyncio.iscoroutinefunction(route.endpoint), (
            f"Handler {route.endpoint.__name__!r} must be a plain def")
        assert route.methods == {"GET"}
    source = open("app/api/v1/crypto_router.py", encoding="utf-8").read()
    assert "async def" not in source
    assert "asyncio.to_thread" not in source, (
        "sync read models are called directly from the worker-thread handler")
    assert "_run_async" in source, "async adapter bridge must stay centralized"
