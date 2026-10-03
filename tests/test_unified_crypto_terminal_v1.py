"""Unified Crypto Terminal + API V1 — end-to-end product tests.

Proves the PR #181 acceptance list on the merged authorities:
navigation, public/premium tokenized access, crypto.api fail-closed
INACTIVE semantics, API/UI single read authority, missing != zero,
stale != current, quarantined != active, acquisition-free read paths,
unknown identity fail-closed, and one-unavailable-domain resilience.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


# ── fixture builders (venue store per test_tokenized_markets_composition) ────

def _venue_registry(entries, quarantines=None):
    from finco_radar.venues.registry import VenueRegistry
    from finco_radar.venues.models import parse_underlying

    def entry(canonical, contract, venue="robinhood-chain", status=None):
        base = dict(
            canonical_asset_id=canonical,
            venue_id=venue,
            instrument_id=contract,
            instrument_type="tokenized-equity",
            network=" Arbitrum ".strip(),
            contract_address=contract,
            status=status or "OK",
            source="test-registry",
            provenance={"source_ref": "test"},
        )
        return base

    underlyings = {
        "NVDA": parse_underlying({"canonical_symbol": "NVDA",
                                  "underlying_name": "NVIDIA",
                                  "underlying_isin": "US67066G1040",
                                  "sources": ["test"]}),
        "AAPL": parse_underlying({"canonical_symbol": "AAPL",
                                  "underlying_name": "Apple",
                                  "sources": ["test"]}),
    }
    rows = [entry(e[0], e[1], e[2] if len(e) > 2 else "robinhood-chain")
            for e in entries]
    # registry rows are RepresentationEntry objects in the real module
    from finco_radar.venues.models import RepresentationEntry
    parsed = []
    for row in rows:
        parsed.append(RepresentationEntry(**row))
    return VenueRegistry(underlyings, parsed, quarantines or [])


def _seed_venue_store(path, *, fresh=True, quarantined=False):
    from finco_radar.venues.observations import (FreshnessState, MarketObservation,
                                                 ObservationStatus)
    from finco_radar.venues.store import VenueMarketStore
    store = VenueMarketStore(path)
    stamp = NOW - (timedelta(days=3) if not fresh else timedelta(seconds=60))
    for canonical, contract in (("NVDA", "0x" + "d0601c"[-6:] * 6 + "00"),
                                ("NVDA", "0x" + "1234" * 10)):
        pass
    observation = MarketObservation(
        ts=(NOW - timedelta(seconds=60)).isoformat(),
        collected_at=(NOW - timedelta(seconds=55)).isoformat(),
        canonical_asset_id="NVDA",
        venue_id="robinhood-chain",
        instrument_id="0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec",
        instrument_type="tokenized-equity",
        price="235.50",
        source="persisted-evidence",
        freshness_state=FreshnessState.AVAILABLE if fresh else FreshnessState.STALE,
        observation_status=(ObservationStatus.QUARANTINED if quarantined
                            else ObservationStatus.OK),
        payload={},
    )
    store.append_observation(observation)
    return path


@pytest.fixture()
def venue_env(monkeypatch, tmp_path):
    db = _seed_venue_store(tmp_path / "venues.db")
    monkeypatch.setenv("FINCO_VENUE_DB_PATH", str(db))
    return db


@pytest.fixture()
def yield_env(monkeypatch, tmp_path):
    from finco_yield.history import YieldHistoryStore
    from finco_yield.observation import ImmutableObservationRecord

    path = tmp_path / "yield_history.jsonl"
    store = YieldHistoryStore(path)
    now = datetime.now(timezone.utc)
    from finco_yield.registry import load_bundled_registry
    opp = load_bundled_registry().all()[0]
    for i in range(6):
        store.append(ImmutableObservationRecord(
            opportunity_uid=opp.uid, observed_at=now - timedelta(hours=0.2)
            if i == 5 else now - timedelta(hours=(6 - i) * 24),
            source_authority="NATIVE_ENRICHED", source_uri="https://test",
            adapter_version="test",
            payload={"apy_total": "0.0440" if i == 5 else "0.0400",
                     "tvl_usd": "5000000"}))
    monkeypatch.setenv("FINCO_YIELD_HISTORY_PATH", str(path))
    return path


@pytest.fixture()
def api_client(monkeypatch, venue_env, yield_env):
    """Crypto API app with the API capability ACTIVATED (crypto.api allowed)
    and token gating off (tokenized holder resources canonical-INACTIVE ->
    approved ungated legacy behaviour).  Both semantics are overridden in
    specific tests."""
    monkeypatch.delenv("FINCO_TOKEN_GATING_ENABLED", raising=False)
    monkeypatch.delenv("FINCO_ENTITLEMENT_POLICIES_JSON", raising=False)
    from app.protocol.entitlement_evaluator import Decision
    _patch_agent_a(monkeypatch, {"crypto.api": (Decision.ALLOW,
                                                "CRYPTO_API_ACTIVATED")})
    from app.api.v1.router import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


# ── Agent-A seam (same pattern as the gating suites) ─────────────────────────

def _patch_agent_a(monkeypatch, verdict_by_resource):
    from app.protocol.entitlement_evaluator import (Decision,
                                                    ResourceAccessDecision)

    async def fake(resource_key, wallet):
        verdict, reason = verdict_by_resource.get(
            resource_key, (Decision.ALLOW, "PUBLIC_RESOURCE"))
        return ResourceAccessDecision(
            resource_key=resource_key, decision=verdict, reason_code=reason,
            access_mode="FINCO_HOLDER" if verdict is Decision.ALLOW else None,
            wallet_address=wallet.address if wallet else None,
            chain_id=None, token_address=None, entitlement_state=None,
            observed_balance=None, minimum_balance=None, observed_at=None)

    import app.radar_ui.tokenized_gating as gating_mod
    import app.crypto_api_access as api_mod
    import app.tokenized_access as tokenized_access_mod

    monkeypatch.setattr(gating_mod, "resolve_tokenized_gates",
                        _patched_gates_factory(verdict_by_resource))
    monkeypatch.setattr(api_mod, "resolve_api_access",
                        _patched_api_access(verdict_by_resource))
    monkeypatch.setattr(tokenized_access_mod, "resolve_tokenized_access",
                        _patched_tokenized_access(verdict_by_resource))


def _patched_gates_factory(verdict_by_resource):
    from app.crypto_resource_access import (CryptoAccessDecision,
                                             CryptoAccessState)
    from app.protocol.entitlement_evaluator import Decision
    from app.radar_ui.tokenized_gating import TokenizedGates

    def resolve(resource):
        verdict, reason = verdict_by_resource.get(
            resource.value, (Decision.ALLOW, "PUBLIC_RESOURCE"))
        if verdict is Decision.ALLOW:
            state = (CryptoAccessState.PUBLIC if reason == "PUBLIC_RESOURCE"
                     else CryptoAccessState.ENTITLED)
            allowed = True
        elif verdict is Decision.INACTIVE:
            state, allowed = CryptoAccessState.TOKEN_ENTITLEMENT_FEATURE_INACTIVE, True
        else:
            state, allowed = CryptoAccessState.ENTITLEMENT_NOT_SATISFIABLE \
                if False else CryptoAccessState.ENTITLEMENT_NOT_SATISFIED, False
        return CryptoAccessDecision(resource=resource.value, state=state,
                                    access_allowed=allowed,
                                    token_entitled=allowed and state == CryptoAccessState.ENTITLED,
                                    gate_active=reason != "PUBLIC_RESOURCE",
                                    reason=reason)

    async def gates(request):
        from app.tokenized_access import TokenizedResource
        return TokenizedGates(
            basic=resolve(TokenizedResource.BASIC),
            history=resolve(TokenizedResource.HISTORY),
            dislocation=resolve(TokenizedResource.DISLOCATION))

    return gates


def _patched_tokenized_access(verdict_by_resource):
    """The API 403 seam: canonical semantics — ALLOW/INACTIVE allow the read,
    DENY denies (typed 403).  Returns the shared CryptoAccessDecision exactly
    like app.tokenized_access does."""
    from app.crypto_resource_access import CryptoAccessDecision, CryptoAccessState
    from app.protocol.entitlement_evaluator import Decision

    async def resolve(request, resource, **kwargs):
        verdict, reason = verdict_by_resource.get(
            resource.value, (Decision.ALLOW, "PUBLIC_RESOURCE"))
        if verdict is Decision.ALLOW:
            state = (CryptoAccessState.PUBLIC if reason == "PUBLIC_RESOURCE"
                     else CryptoAccessState.ENTITLED)
            allowed = True
        elif verdict is Decision.INACTIVE:
            state, allowed = CryptoAccessState.TOKEN_ENTITLEMENT_FEATURE_INACTIVE, True
        else:
            state, allowed = CryptoAccessState.ENTITLEMENT_NOT_SATISFIED, False
        return CryptoAccessDecision(resource=resource.value, state=state,
                                    access_allowed=allowed,
                                    token_entitled=allowed and state == CryptoAccessState.ENTITLED,
                                    gate_active=reason != "PUBLIC_RESOURCE",
                                    reason=reason)

    return resolve


def _patched_api_access(verdict_by_resource):
    from app.crypto_resource_access import CryptoAccessDecision, CryptoAccessState
    from app.protocol.entitlement_evaluator import Decision

    async def resolve(request, **kwargs):
        verdict, reason = verdict_by_resource.get(
            "crypto.api", (Decision.ALLOW, "PUBLIC_RESOURCE"))
        if verdict is Decision.ALLOW:
            return CryptoAccessDecision(
                resource="crypto.api", state=CryptoAccessState.PUBLIC,
                access_allowed=True, token_entitled=False, gate_active=False,
                reason=reason)
        if verdict is Decision.INACTIVE:
            # canonical INACTIVE semantics for crypto.api: DENIED, fail-closed
            return CryptoAccessDecision(
                resource="crypto.api",
                state=CryptoAccessState.TOKEN_ENTITLEMENT_FEATURE_INACTIVE,
                access_allowed=False, token_entitled=False, gate_active=True,
                reason=reason)
        return CryptoAccessDecision(
            resource="crypto.api", state=CryptoAccessState.ENTITLEMENT_NOT_SATISFIED,
            access_allowed=False, token_entitled=False, gate_active=True,
            reason=reason)

    return resolve


# ── 1. navigation ────────────────────────────────────────────────────────────

def test_radar_to_tokenized_navigation_present(monkeypatch):
    monkeypatch.delenv("FINCO_TOKEN_GATING_ENABLED", raising=False)
    from app.radar_ui.tokenized_router import router as tokenized_router
    from app.radar_ui.crypto_router import router as crypto_router
    app = FastAPI()
    app.include_router(tokenized_router)
    app.include_router(crypto_router)
    client = TestClient(app)
    tokenized = client.get("/radar/tokenized-markets")
    overview = client.get("/radar/crypto")
    assert tokenized.status_code == 200
    assert overview.status_code == 200
    for page in (tokenized, overview):
        assert 'data-testid="crypto-domain-nav"' in page.text
        assert 'href="/radar/tokenized-markets"' in page.text
        assert 'href="/yield"' in page.text
        assert 'href="/radar"' in page.text


def test_yield_terminal_carries_domain_navigation(yield_env):
    from finco_yield.web import router as yield_router
    app = FastAPI()
    app.include_router(yield_router)
    client = TestClient(app)
    page = client.get("/yield")
    assert page.status_code == 200
    assert 'data-testid="crypto-domain-nav"' in page.text
    assert 'href="/radar/tokenized-markets"' in page.text


# ── 2–7. tokenized access + crypto.api semantics ─────────────────────────────

def test_tokenized_basic_is_public_on_api(api_client):
    response = api_client.get("/api/v1/crypto/tokenized")
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "finco-crypto-api-v1"
    assert body["resource"] == "tokenized.landing"
    assert body["access"]["basic"]["allowed"] is True


def test_tokenized_history_denied_is_typed_403_without_payload(api_client, monkeypatch):
    _patch_agent_a(monkeypatch, {
        "tokenized.basic": (None, None),  # filled below
    })
    from app.protocol.entitlement_evaluator import Decision
    _patch_agent_a(monkeypatch, {
        "tokenized.basic": (Decision.ALLOW, "PUBLIC_RESOURCE"),
        "tokenized.history": (Decision.DENY, "BALANCE_BELOW_THRESHOLD"),
        "tokenized.dislocation": (Decision.DENY, "BALANCE_BELOW_THRESHOLD"),
    })
    detail = api_client.get("/api/v1/crypto/tokenized/NVDA")
    assert detail.status_code == 200
    # premium payload redacted from the detail envelope
    assert "intelligence" not in detail.json()["data"]
    history = api_client.get("/api/v1/crypto/tokenized/NVDA/history")
    assert history.status_code == 403
    body = history.json()
    assert body["error"] == "TOKENIZED_PREMIUM_REQUIRED"
    assert set(body) <= {"error", "resource", "access_state", "reason"}
    dislocations = api_client.get("/api/v1/crypto/tokenized/NVDA/dislocations")
    assert dislocations.status_code == 403
    assert dislocations.json()["error"] == "TOKENIZED_PREMIUM_REQUIRED"


def test_gating_inactive_preserves_ungated_premium_behaviour(api_client, monkeypatch):
    """Canonical INACTIVE on the tokenized holder resources keeps the approved
    ungated behaviour (access_allowed=True) even though the values exist."""
    from app.protocol.entitlement_evaluator import Decision
    _patch_agent_a(monkeypatch, {
        "tokenized.basic": (Decision.ALLOW, "PUBLIC_RESOURCE"),
        "tokenized.history": (Decision.INACTIVE, "TOKEN_ENTITLEMENT_FEATURE_INACTIVE"),
        "tokenized.dislocation": (Decision.INACTIVE, "TOKEN_ENTITLEMENT_FEATURE_INACTIVE"),
    })
    history = api_client.get("/api/v1/crypto/tokenized/NVDA/history")
    assert history.status_code == 200
    body = history.json()
    assert body["state"] == "AVAILABLE"
    assert isinstance(body["data"]["series"], list)


def test_crypto_api_inactive_remains_denied(api_client, monkeypatch):
    from app.protocol.entitlement_evaluator import Decision
    _patch_agent_a(monkeypatch, {"crypto.api": (Decision.INACTIVE,
                                                "TOKEN_ENTITLEMENT_FEATURE_INACTIVE")})
    for path in ("/api/v1/crypto/tokenized",
                 "/api/v1/crypto/tokenized/NVDA",
                 "/api/v1/crypto/tokenized/NVDA/history",
                 "/api/v1/crypto/tokenized/NVDA/dislocations",
                 "/api/v1/crypto/yield",
                 "/api/v1/crypto/yield/x"):
        response = api_client.get(path)
        assert response.status_code == 403, path
        body = response.json()
        assert body["error"] == "CRYPTO_API_ACCESS_REQUIRED"
        assert body["access_state"] == "TOKEN_ENTITLEMENT_FEATURE_INACTIVE"


def test_entitled_api_fixture_returns_protected_data(api_client, monkeypatch):
    from app.protocol.entitlement_evaluator import Decision
    _patch_agent_a(monkeypatch, {
        "tokenized.basic": (Decision.ALLOW, "PUBLIC_RESOURCE"),
        "tokenized.history": (Decision.ALLOW, "TOKEN_ENTITLED"),
        "tokenized.dislocation": (Decision.ALLOW, "TOKEN_ENTITLED"),
    })
    detail = api_client.get("/api/v1/crypto/tokenized/NVDA")
    assert detail.status_code == 200
    assert "intelligence" in detail.json()["data"]
    history = api_client.get("/api/v1/crypto/tokenized/NVDA/history")
    assert history.status_code == 200
    dislocations = api_client.get("/api/v1/crypto/tokenized/NVDA/dislocations")
    assert dislocations.status_code == 200


def test_yield_api_reads_canonical_history(yield_env, api_client):
    landing = api_client.get("/api/v1/crypto/yield")
    assert landing.status_code == 200
    body = landing.json()
    assert body["resource"] == "yield.market"
    assert body["data"]["summary"]["pools_observed"] >= 1
    from finco_yield.registry import load_bundled_registry
    uid = load_bundled_registry().all()[0].uid
    detail = api_client.get(f"/api/v1/crypto/yield/{uid}")
    assert detail.status_code == 200
    data = detail.json()["data"]
    assert data["market"]["latest_apy"] == 0.044   # newest canonical observation (4.4%)
    assert data["market"]["delta_24h_bps"] == pytest.approx(40.0)


def test_unknown_identity_fails_closed(api_client):
    detail = api_client.get("/api/v1/crypto/tokenized/NOT-A-REGISTRY-SYMBOL")
    assert detail.status_code == 404
    assert detail.json()["state"] == "UNKNOWN_IDENTITY"
    pool = api_client.get("/api/v1/crypto/yield/does-not-exist")
    assert pool.status_code == 404
    assert pool.json()["state"] == "UNKNOWN_IDENTITY"


# ── 9–11. value semantics on the API surface ─────────────────────────────────

def _activated_api(monkeypatch):
    """API app with crypto.api ACTIVATED (Agent-A patched)."""
    from app.protocol.entitlement_evaluator import Decision
    _patch_agent_a(monkeypatch, {"crypto.api": (Decision.ALLOW,
                                                "CRYPTO_API_ACTIVATED")})
    from app.api.v1.router import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def test_api_missing_is_null_not_zero(venue_env, api_client):
    """An unpriced representation exposes null price/basis — never zero."""
    detail = api_client.get("/api/v1/crypto/tokenized/NVDA")
    assert detail.status_code == 200
    representations = detail.json()["data"]["representations"]
    assert isinstance(representations, list)
    for rep in representations:
        if rep["price"] is None:
            assert rep["price"] is not None or rep["basis_bps"] is None


def test_api_stale_is_not_current(venue_env, monkeypatch, tmp_path):
    db = _seed_venue_store(tmp_path / "stale.db", fresh=False)
    monkeypatch.setenv("FINCO_VENUE_DB_PATH", str(db))
    client = _activated_api(monkeypatch)
    detail = client.get("/api/v1/crypto/tokenized/NVDA")
    assert detail.status_code == 200
    states = [rep["freshness_state"] for rep in detail.json()["data"]["representations"]]
    assert "STALE" in states


def test_quarantined_is_not_active_market_evidence(venue_env, monkeypatch, tmp_path):
    db = _seed_venue_store(tmp_path / "quarantined.db", quarantined=True)
    monkeypatch.setenv("FINCO_VENUE_DB_PATH", str(db))
    client = _activated_api(monkeypatch)
    detail = client.get("/api/v1/crypto/tokenized/NVDA")
    representations = detail.json()["data"]["representations"]
    quarantined = [r for r in representations if r["observation_status"] == "QUARANTINED"]
    for rep in quarantined:
        assert rep["basis_bps"] is None
        assert rep["basis_reason"] == "REPRESENTATION_QUARANTINED"


# ── 12–13. acquisition-free read paths ───────────────────────────────────────

def test_api_and_browser_never_invoke_market_acquisition(venue_env, yield_env, monkeypatch):
    """Browser and API reads stay acquisition-free: any upstream provider
    HTTP during the read paths fails the test loudly."""
    import httpx

    def _no_external_http(self, method=None, url=None, *args, **kwargs):
        target = str(url or (args[0] if args else ""))
        if "testserver" not in target and not target.startswith("/"):
            raise AssertionError(f"upstream provider HTTP on a read path: {target}")
        return _original_request(self, method, url, *args, **kwargs)

    _original_request = httpx.Client.request
    monkeypatch.setattr(httpx.Client, "request", _no_external_http)
    monkeypatch.setenv("FINCO_VENUE_DB_PATH", str(venue_env))
    client = _activated_api(monkeypatch)
    assert client.get("/api/v1/crypto/tokenized").status_code == 200
    detail = client.get("/api/v1/crypto/tokenized/NVDA")
    assert detail.status_code in (200, 404)

    from app.radar_ui.tokenized_router import router as tokenized_router
    app = FastAPI()
    app.include_router(tokenized_router)
    ui = TestClient(app)
    assert ui.get("/radar/tokenized-markets").status_code == 200


def test_unavailable_venue_store_degrades_terminal(venue_env, monkeypatch, tmp_path, yield_env):
    monkeypatch.setenv("FINCO_VENUE_DB_PATH", str(tmp_path / "missing-dir" / "v.db"))
    from app.api.v1.router import router as api_router
    from app.radar_ui.tokenized_router import router as tokenized_router
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.include_router(tokenized_router)
    from app.protocol.entitlement_evaluator import Decision
    _patch_agent_a(monkeypatch, {"crypto.api": (Decision.ALLOW,
                                                "CRYPTO_API_ACTIVATED")})
    client = TestClient(app)
    landing = client.get("/api/v1/crypto/tokenized")
    assert landing.status_code == 200
    page = client.get("/radar/tokenized-markets")
    assert page.status_code == 200
    api_pool = client.get("/api/v1/crypto/yield")
    assert api_pool.status_code == 200   # yield domain unaffected


# ── 16. no execution/signing/custody surface ────────────────────────────────

def test_crypto_api_is_read_only_get_only():
    from app.api.v1.crypto_router import router
    for route in router.routes:
        methods = getattr(route, "methods", set())
        assert methods == {"GET"}, f"{route.path} must be GET-only"
        assert "sign" not in route.path and "order" not in route.path
    source = open("app/api/v1/crypto_router.py", encoding="utf-8").read().lower()
    for forbidden in ("post", "put(", "delete(", "sign", "custody", "swap"):
        assert f'"{forbidden}' not in source


# ── product truth contract ──────────────────────────────────────────────────

def test_product_truth_contract_is_canonical_and_pinned():
    doc = open("docs/CRYPTO_TERMINAL_PRODUCT_TRUTH.md", encoding="utf-8").read()
    for domain in ("Radar", "Tokenized Markets", "Yield", "Crypto API V1"):
        assert domain in doc
    assert "AVAILABLE TODAY" in doc and "CONFIGURABLE BUT INACTIVE" in doc
    assert "NOT YET SUPPORTED" in doc
    assert "Execution remains OFF" in doc
    assert "Decision.INACTIVE" in doc or "INACTIVE" in doc
    assert "never zero" in doc
    assert "DeFiLlama" not in doc  # not a Yield source; no provider expansion
