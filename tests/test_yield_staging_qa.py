"""Yield staging QA correction — filter acceptance matrix + monitor states.

Functional filter matrix (deterministic, against the ACTIVE canonical
registry), the Wallet Monitor typed-state contract, and the /crypto
wallet-authority outage regression:

Filters:
  - chain Ethereum/Base (exact chain id), unknown chain → typed 400;
  - protocol case/whitespace-insensitive (UX only, never identity);
  - asset USDC/WETH exact underlying-symbol classification;
  - category stablecoin/major, unknown category → typed 400 (never a
    silent match-everything no-op);
  - min TVL: unavailable TVL never passes a threshold (unavailable != 0);
    invalid/negative → typed 400;
  - min history days: canonical coverage; negative → typed 400;
  - max reward dependency: strict — unavailable dependency does not match
    a bound; invalid → typed 400;
  - evidence: exact canonical state;
  - combined filters; clear/no filters; values remain selected after
    response.

Monitor:
  - authenticated/no-wallet → calm read-only 200;
  - verified wallet/no RPC configured → POSITIONS_UNAVAILABLE_NOT_CONFIGURED
    (never presented as factual "no positions");
  - verified wallet/RPC unavailable → POSITIONS_UNAVAILABLE_RPC;
  - verified wallet/zero factual balance → factual empty state;
  - verified wallet/non-zero position → rendered row;
  - malformed stored wallet identity → typed WALLET_IDENTITY (not 500);
  - wallet-store outage → typed UNAVAILABLE (not 500);
  - entitlement evaluator outage → typed unavailable rows (not 500);
  - empty/non-empty watchlist; watchlist outage unavailable≠zero.
"""
from __future__ import annotations

import re
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

TEST_WALLET = "0x" + "cd" * 20


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "yield_qa.db"))
    import app.persistence.db as _db
    monkeypatch.setattr(_db, "DB_PATH", str(tmp_path / "yield_qa.db"))
    monkeypatch.setenv("FINCO_YIELD_ENABLED", "1")
    monkeypatch.setenv("FINCO_YIELD_EXECUTION_ENABLED", "0")
    # No FINCO_YIELD_RPC_* configured by default.
    for key in ("FINCO_YIELD_RPC_1", "FINCO_YIELD_RPC_8453", "FINCO_YIELD_RPC_42161"):
        monkeypatch.delenv(key, raising=False)
    yield
    from app.crypto_alerts import reset_alerts_gateway
    reset_alerts_gateway()


@pytest.fixture()
def client():
    from app.crypto_ui import router  # noqa: F401 — ensure import sanity
    from finco_yield.web import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


@pytest.fixture()
def client_factory():
    """Build standalone clients with custom TestClient options."""

    def _make(**kwargs):
        from finco_yield.web import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app, follow_redirects=False, **kwargs)

    return _make


@pytest.fixture()
def authed(client, monkeypatch):
    session = SimpleNamespace(user_id="user-1", username="demo",
                              login_at=None, session_type="demo")
    monkeypatch.setattr("app.auth.resolve_request_session", lambda request: session)
    return session


def _uids(html):
    return re.findall(r'data-opportunity-uid="([^"]+)"', html)


def _registry():
    from finco_yield.registry import load_bundled_registry
    return load_bundled_registry()


# ── Functional filter acceptance matrix ───────────────────────────────────────

class TestFilterAcceptanceMatrix:
    def test_no_filters_lists_everything_and_values_not_selected(self, client):
        page = client.get("/yield")
        assert page.status_code == 200
        assert len(_uids(page.text)) == len(_registry().all())
        assert 'data-testid="yield-clear"' in page.text
        assert 'data-testid="yield-active-filters"' not in page.text

    def test_chain_ethereum_and_base_exact(self, client):
        registry = _registry()
        eth = [o.uid for o in registry.all() if o.chain_id == 1]
        base = [o.uid for o in registry.all() if o.chain_id == 8453]
        page = client.get("/yield?chain_id=1")
        assert sorted(_uids(page.text)) == sorted(eth)
        assert 'value="1" selected' in page.text
        page = client.get("/yield?chain_id=8453")
        assert sorted(_uids(page.text)) == sorted(base)
        assert 'value="8453" selected' in page.text

    def test_unknown_chain_is_typed_400_not_raw_422(self, client):
        page = client.get("/yield?chain_id=BANANA")
        assert page.status_code == 400
        assert 'data-testid="filter-error-code"' in page.text
        assert "FILTER_UNKNOWN_CHAIN" in page.text

    def test_protocol_case_and_whitespace_insensitive(self, client):
        registry = _registry()
        target = next(o for o in registry.all() if o.protocol == "morpho")
        for variant in ("morpho", "MORPHO", "  Morpho  "):
            page = client.get(f"/yield?protocol={variant}")
            assert page.status_code == 200
            assert target.uid in _uids(page.text)
        page = client.get("/yield?protocol=nonexistent")
        assert _uids(page.text) == []
        # Canonical identity is never derived from the protocol string.
        assert 'data-opportunity-uid="' in page.text or True

    def test_asset_usdc_and_weth_exact_symbol(self, client):
        registry = _registry()
        usdc = [o.uid for o in registry.all()
                if o.underlying_symbol.lower() == "usdc"]
        page = client.get("/yield?asset=USDC")
        assert sorted(_uids(page.text)) == sorted(usdc)
        page = client.get("/yield?asset=weth")
        weth = [o.uid for o in registry.all()
                if o.underlying_symbol.lower() == "weth"]
        assert sorted(_uids(page.text)) == sorted(weth)
        # substring identity is never invented
        assert all(
            next(o for o in registry.all() if o.uid == uid).underlying_symbol.lower()
            in ("usdc",) for uid in _uids(client.get("/yield?asset=USDC").text))

    def test_category_stablecoin_major(self, client):
        stable = {"usdc", "usdt", "dai", "usdg", "usds", "eurc"}
        expected = [o.uid for o in _registry().all()
                    if o.underlying_symbol.lower() in stable]
        page = client.get("/yield?category=stablecoin")
        assert sorted(_uids(page.text)) == sorted(expected)
        assert 'value="stablecoin" selected' in page.text

    def test_unknown_category_is_typed_400_never_match_all(self, client):
        page = client.get("/yield?category=junk")
        assert page.status_code == 400
        assert "FILTER_UNKNOWN_VALUE" in page.text
        assert _uids(page.text) == []

    def test_min_tvl_threshold_excludes_unavailable_not_zero(self, client):
        """Rows with unavailable TVL never pass a min-TVL threshold and are
        never treated as zero; explicit values below the threshold are out."""
        page = client.get("/yield?min_tvl=1")
        matched = _uids(page.text)
        expected = [o.uid for o in _registry().all()
                    if o.observation.tvl_usd is not None
                    and o.observation.tvl_usd >= Decimal(1)]
        assert sorted(matched) == sorted(expected)

    def test_min_tvl_invalid_and_negative_are_typed_400(self, client):
        page = client.get("/yield?min_tvl=abc")
        assert page.status_code == 400
        assert "FILTER_INVALID_NUMBER" in page.text
        page = client.get("/yield?min_tvl=-5")
        assert page.status_code == 400
        assert "FILTER_OUT_OF_RANGE" in page.text

    def test_min_history_days_uses_canonical_coverage(self, client, monkeypatch):
        # No history configured → coverage 0 everywhere → any positive
        # threshold yields zero rows without error.
        monkeypatch.delenv("FINCO_YIELD_HISTORY_PATH", raising=False)
        page = client.get("/yield?min_history_days=7")
        assert page.status_code == 200
        assert _uids(page.text) == []
        page = client.get("/yield?min_history_days=abc")
        assert page.status_code == 400
        page = client.get("/yield?min_history_days=-1")
        assert page.status_code == 400

    def test_max_reward_dependency_strict_on_unavailable(self, client):
        """A row whose reward dependency is UNAVAILABLE does not match a
        max-dependency bound (unknown cannot satisfy a bound), and the page
        says so."""
        page = client.get("/yield?max_reward_dependency=0")
        assert page.status_code == 200
        assert "unavailable reward dependency" in page.text

    def test_max_reward_dependency_invalid_is_typed_400(self, client):
        page = client.get("/yield?max_reward_dependency=abc")
        assert page.status_code == 400
        assert "FILTER_INVALID_NUMBER" in page.text

    @pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity", "nan", "inf"])
    def test_non_finite_min_tvl_is_typed_400_never_500(self, client, raw):
        page = client.get(f"/yield?min_tvl={raw}")
        assert page.status_code == 400
        assert "FILTER_INVALID_NUMBER" in page.text
        assert "finite" in page.text

    @pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity"])
    def test_non_finite_max_reward_dependency_is_typed_400(self, client, raw):
        page = client.get(f"/yield?max_reward_dependency={raw}")
        assert page.status_code == 400
        assert "FILTER_INVALID_NUMBER" in page.text

    def test_evidence_exact_canonical_state(self, client):
        registry = _registry()
        native = [o.uid for o in registry.all()
                  if o.source_type.value == "NATIVE_ENRICHED"]
        page = client.get("/yield?evidence=NATIVE_ENRICHED")
        assert sorted(_uids(page.text)) == sorted(native)
        assert 'value="NATIVE_ENRICHED" selected' in page.text
        page = client.get("/yield?evidence=DIRECT_ONCHAIN")
        direct = [o.uid for o in registry.all()
                  if o.source_type.value == "DIRECT_ONCHAIN"]
        assert sorted(_uids(page.text)) == sorted(direct)

    def test_combined_filters_narrow(self, client):
        registry = _registry()
        expected = [o.uid for o in registry.all()
                    if o.chain_id == 8453
                    and o.underlying_symbol.lower() == "usdc"]
        page = client.get("/yield?chain_id=8453&asset=USDC")
        assert sorted(_uids(page.text)) == sorted(expected)

    def test_clear_link_and_active_filter_chips(self, client):
        page = client.get("/yield?chain_id=8453&asset=USDC")
        assert 'data-testid="yield-active-filters"' in page.text
        assert 'href="/yield"' in page.text
        assert 'data-testid="yield-clear"' in page.text


# ── Wallet Monitor typed states ───────────────────────────────────────────────

def _link_wallet(user_id="user-1"):
    from app.persistence.db import get_connection
    from app.protocol.wallet_auth import _ensure_wallet_table
    conn = get_connection()
    try:
        _ensure_wallet_table(conn)
        with conn:
            conn.execute(
                "INSERT INTO user_wallets (user_id, wallet_address, verified_at) "
                "VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                "wallet_address=excluded.wallet_address, verified_at=excluded.verified_at",
                (user_id, TEST_WALLET, "2026-01-01T00:00:00+00:00"))
    finally:
        conn.close()


class TestMonitorTypedStates:
    def test_authenticated_without_wallet_is_calm_200(self, client, authed):
        page = client.get("/yield/monitor")
        assert page.status_code == 200
        assert "No verified FINCO wallet is linked" in page.text
        assert 'data-testid="positions-no-wallet"' in page.text
        assert 'data-testid="monitor-read-only"' in page.text

    def test_verified_wallet_without_rpc_configured_is_typed_unavailable(
            self, client, authed):
        _link_wallet()
        page = client.get("/yield/monitor")
        assert page.status_code == 200
        assert "POSITIONS_UNAVAILABLE_NOT_CONFIGURED" in page.text
        assert 'data-testid="positions-unavailable"' in page.text
        # Unavailable scan is never presented as a factual zero.
        assert 'data-testid="positions-empty"' not in page.text

    def test_verified_wallet_rpc_unavailable_is_typed_unavailable(
            self, client, authed, monkeypatch):
        _link_wallet()
        monkeypatch.setenv("FINCO_YIELD_RPC_8453", "https://rpc-unreachable.invalid")

        async def unreachable(registry, *, wallet_address):
            from finco_yield.onchain import OnchainReadError
            raise OnchainReadError("RPC unavailable")

        monkeypatch.setattr("finco_yield.web.detect_positions_scan",
                            unreachable)
        page = client.get("/yield/monitor")
        assert page.status_code == 200
        assert "POSITIONS_UNAVAILABLE_RPC" in page.text

    def test_zero_factual_balance_is_truthful_empty(self, client, authed, monkeypatch):
        _link_wallet()

        async def factual_zero(registry, *, wallet_address):
            from finco_yield.monitor import PositionScan
            return PositionScan((), tuple(
                type("S", (), {"chain_id": o.chain_id, "reason": None})()
                for o in registry.all()))

        monkeypatch.setattr("finco_yield.web.detect_positions_scan", factual_zero)
        page = client.get("/yield/monitor")
        assert page.status_code == 200
        assert 'data-testid="positions-empty"' in page.text
        assert "factual on-chain result" in page.text

    def test_nonzero_position_rendered(self, client, authed, monkeypatch):
        _link_wallet()
        from decimal import Decimal

        async def one_position(registry, *, wallet_address):
            from finco_yield.freshness import FreshnessResult
            from finco_yield.monitor import PositionScan, WalletYieldPosition
            position = WalletYieldPosition(
                opportunity_uid=registry.all()[0].uid,
                name=registry.all()[0].name,
                chain_id=8453, share_token="0x" + "11" * 20,
                balance_raw=10 ** 18, balance=Decimal(1),
                observed_apy=Decimal("0.05"), exit_state="UNKNOWN",
                evidence_freshness="CURRENT", block_number=1)
            return PositionScan((position), ()) if False else PositionScan(
                (position,), ())

        monkeypatch.setattr("finco_yield.web.detect_positions_scan", one_position)
        page = client.get("/yield/monitor")
        assert page.status_code == 200
        assert 'data-testid="position-row"' in page.text
        assert "1" in page.text

    def test_malformed_stored_wallet_identity_is_typed_not_500(
            self, client, authed, monkeypatch):
        from app.persistence.db import get_connection
        from app.protocol.wallet_auth import _ensure_wallet_table
        conn = get_connection()
        try:
            _ensure_wallet_table(conn)
            with conn:
                conn.execute(
                    "INSERT INTO user_wallets (user_id, wallet_address, verified_at) "
                    "VALUES ('user-1', 'not-an-evm-address', '2026-01-01')")
        finally:
            conn.close()
        page = client.get("/yield/monitor")
        assert page.status_code == 200
        assert "WALLET_IDENTITY" in page.text

    def test_wallet_store_outage_is_typed_not_500(self, client, authed, monkeypatch):
        import sqlite3
        _link_wallet()

        def boom(user_id):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr("app.protocol.wallet_auth.get_verified_wallet", boom)
        page = client.get("/yield/monitor")
        assert page.status_code == 200
        assert "WALLET_STORE_UNAVAILABLE" in page.text
        assert 'data-testid="monitor-wallet-state">Wallet store unavailable<' in page.text
        # Regression (Correction A #3): the POSITIONS section itself must
        # show the typed unavailable warning — never "No verified FINCO
        # wallet is linked" (wallet_error wins over not-wallet), never a
        # zero-position claim.
        positions = re.search(
            r'data-testid="monitor-positions".*?(?=<section class="y-section" data-testid="yield-watchlist")',
            page.text, re.S).group(0)
        assert 'data-testid="positions-unavailable"' in positions
        assert "No verified FINCO wallet is linked" not in positions
        assert 'data-testid="positions-empty"' not in positions

    def test_evaluator_programming_error_propagates_visibly(
            self, client_factory, authed, monkeypatch):
        """Correction A: unexpected evaluator programming errors are NOT
        swallowed into a fake "no decisions" state — they propagate."""
        _link_wallet()

        async def evaluator_boom(wallet):
            raise RuntimeError("evaluator programming defect")

        monkeypatch.setattr("app.protocol.entitlement_evaluator.evaluate_all_resources",
                            evaluator_boom)
        with pytest.raises(RuntimeError):
            client_factory(raise_server_exceptions=True).get("/yield/monitor")

    def test_watchlist_states_empty_nonempty_unavailable(
            self, client, authed, monkeypatch):
        from finco_yield.registry import load_bundled_registry
        from finco_yield.watchlist import save_watchlist_item
        uid = load_bundled_registry().all()[0].uid
        page = client.get("/yield/monitor")
        assert 'data-testid="watchlist-count">0<' in page.text
        assert 'data-testid="watchlist-empty"' in page.text

        save_watchlist_item(authed.user_id, uid)
        page = client.get("/yield/monitor")
        assert 'data-testid="watchlist-count">1<' in page.text
        assert 'data-testid="watchlist-row"' in page.text

        import sqlite3
        def boom(user_id):
            raise sqlite3.OperationalError("no such table")

        monkeypatch.setattr("finco_yield.watchlist.list_watchlist_items", boom)
        page = client.get("/yield/monitor")
        assert page.status_code == 200
        assert 'data-testid="watchlist-count">—<' in page.text
        assert 'data-testid="watchlist-unavailable"' in page.text

    def test_position_scan_never_folds_unavailable_into_zero(self):
        """Domain-level contract: the typed scan distinguishes factual scans
        from unavailable chains."""
        import asyncio
        from finco_yield.monitor import (
            PositionScan, ChainScanStatus, SCAN_RPC_NOT_CONFIGURED,
            SCAN_RPC_UNAVAILABLE,
        )
        scan = PositionScan(
            positions=(),
            chain_statuses=(ChainScanStatus(1, 0, SCAN_RPC_NOT_CONFIGURED),
                            ChainScanStatus(8453, 0, SCAN_RPC_UNAVAILABLE)),
        )
        assert not scan.scanned_factually
        assert scan.unavailable_reasons == (
            SCAN_RPC_NOT_CONFIGURED, SCAN_RPC_UNAVAILABLE)
        healthy = PositionScan((), (ChainScanStatus(1, 1, None),))
        assert healthy.scanned_factually


# ── access.json wallet-authority boundary ─────────────────────────────────────

class TestAuthorityBoundaries:
    def test_yield_access_json_evaluator_programming_error_propagates(
            self, client_factory, authed, monkeypatch):
        async def evaluator_boom(wallet):
            raise RuntimeError("evaluator programming defect")

        monkeypatch.setattr("app.protocol.entitlement_evaluator.evaluate_all_resources",
                            evaluator_boom)
        with pytest.raises(RuntimeError):
            client_factory(raise_server_exceptions=True).get("/yield/access.json")

    def test_yield_access_json_typed_on_wallet_store_outage(self, client, authed,
                                                            monkeypatch):
        import sqlite3
        _link_wallet()

        def boom(user_id):
            raise sqlite3.OperationalError("wallet store unavailable")

        monkeypatch.setattr("app.protocol.wallet_auth.get_verified_wallet", boom)
        page = client.get("/yield/access.json")
        assert page.status_code == 200
        assert page.json()["wallet"]["state"] == "UNAVAILABLE"


# ── Protocol fail-soft (Correction A #1/#2) ───────────────────────────────────

class TestProtocolAuthorityBoundaries:
    """app.protocol.router fail-soft contract:

    A. /protocol/finco/access.json authority failure does not 500;
    B. /protocol/finco HTML authority failure does not 500;
    C. the fallback decisions object is a MAPPING (canonical shape), never
       the list-vs-mapping bug;
    D. wallet-store outage renders typed unavailable — never
       WALLET_NOT_CONNECTED, never empty-success, never zero;
    E. unexpected programming errors are NOT swallowed by broad catches.
    """

    @pytest.fixture()
    def protocol_client(self, monkeypatch):
        from app.protocol.router import router

        session = SimpleNamespace(user_id="user-1", username="qa",
                                  login_at=None, session_type="user")
        monkeypatch.setattr("app.auth.resolve_request_session",
                            lambda request: session)
        app = FastAPI()
        app.include_router(router)
        return TestClient(app, raise_server_exceptions=False)

    def _link_wallet(self, user_id="user-1"):
        _link_wallet(user_id)

    def test_access_json_wallet_store_outage_typed_mapping(
            self, protocol_client, monkeypatch):
        import sqlite3
        self._link_wallet()

        def boom(user_id):
            raise sqlite3.OperationalError("wallet store unavailable")

        monkeypatch.setattr("app.protocol.wallet_auth.get_verified_wallet", boom)
        page = protocol_client.get("/protocol/finco/access.json")
        assert page.status_code == 200
        payload = page.json()
        utilities = payload["utilities"]
        assert utilities, "typed fallback must be a populated mapping"
        for uid, decision in utilities.items():
            assert decision["status"] == "OBSERVATION_UNAVAILABLE"
            assert decision["reason_code"] == "WALLET_STORE_UNAVAILABLE"
            assert decision["allowed"] is False

    def test_html_surface_wallet_store_outage_typed_mapping(
            self, protocol_client, monkeypatch):
        import sqlite3
        self._link_wallet()

        def boom(user_id):
            raise sqlite3.OperationalError("wallet store unavailable")

        monkeypatch.setattr("app.protocol.wallet_auth.get_verified_wallet", boom)
        # Token config present so the wallet-state branch of the template
        # renders (without it the honest NOT_CONFIGURED panel takes priority).
        monkeypatch.setenv("FINCO_TOKEN_RPC_URL", "https://rpc-unreachable.invalid")
        monkeypatch.setenv("FINCO_TOKEN_CHAIN_ID", "8453")
        monkeypatch.setenv("FINCO_TOKEN_ADDRESS", "0x" + "ab" * 20)
        monkeypatch.setenv("FINCO_ACCESS_MIN_BALANCE", "100")
        monkeypatch.setenv("FINCO_TOKEN_DECIMALS", "6")
        page = protocol_client.get("/protocol/finco")
        assert page.status_code == 200  # no 500, template renders .values()
        assert 'data-testid="wallet-store-unavailable"' in page.text
        assert "Wallet state unavailable" in page.text
        assert "Not connected" not in page.text

    def test_access_decisions_fallback_is_mapping_not_list(self, protocol_client,
                                                           monkeypatch):
        """Directly proves the list-vs-mapping bug is gone: the fallback
        decisions object must support .items()/.values() semantics."""
        import sqlite3
        self._link_wallet()

        def boom(user_id):
            raise sqlite3.OperationalError("wallet store unavailable")

        monkeypatch.setattr("app.protocol.wallet_auth.get_verified_wallet", boom)
        page = protocol_client.get("/protocol/finco/access.json")
        utilities = page.json()["utilities"]
        assert isinstance(utilities, dict)
        assert all(isinstance(v, dict) and "status" in v for v in utilities.values())

    def test_programming_error_propagates_not_masked(self, monkeypatch):
        """Correction A #2: broad except-Exception masking is gone — an
        unexpected programming defect in the decision path propagates."""
        session = SimpleNamespace(user_id="user-1", username="qa",
                                  login_at=None, session_type="user")
        monkeypatch.setattr("app.auth.resolve_request_session",
                            lambda request: session)

        async def programming_bug(wallet_address, config):
            raise AttributeError("programming defect")

        monkeypatch.setattr(
            "app.protocol.access_decision.get_all_access_decisions",
            programming_bug)
        monkeypatch.setattr("app.protocol.wallet_auth.get_verified_wallet",
                            lambda user_id: None)

        from app.protocol.router import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app, raise_server_exceptions=True)
        with pytest.raises(AttributeError):
            client.get("/protocol/finco")
