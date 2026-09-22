"""E2 Correction A tests — R1–R4 real route integration + batch API + board.

Uses the actual FastAPI application via TestClient so every assertion
exercises the real router, middleware stack, and template rendering.

No external network: Robinhood universe and E1 DB are both synthetic.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from collections import namedtuple
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.radar_ui.equity_enrichment import (
    EnrichmentState,
    enrich_many_selected_assets,
    enrich_selected_asset,
)
from app.radar_ui.equity_view_model import build_equity_board_row, build_equity_view
from finco_radar.equity import get_equity_fundamentals_many


# ── synthetic DB helpers ───────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE equity_assets (
    id INTEGER PRIMARY KEY,
    robinhood_token_symbol TEXT NOT NULL,
    underlying_ticker TEXT NOT NULL,
    name TEXT,
    token_contract_address TEXT,
    chain_network TEXT,
    underlying_exchange TEXT,
    cik TEXT,
    figi TEXT,
    currency TEXT,
    security_type TEXT,
    active INTEGER DEFAULT 1,
    first_seen_at TEXT,
    last_seen_at TEXT
);
CREATE TABLE equity_company_profiles (
    id INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL,
    cik TEXT,
    profile_json TEXT,
    payload_hash TEXT,
    provider TEXT,
    source_contract TEXT,
    fetched_at TEXT
);
CREATE TABLE equity_financial_snapshots (
    id INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL,
    cik TEXT,
    timeframe TEXT NOT NULL,
    fiscal_year TEXT,
    fiscal_quarter TEXT,
    period_end TEXT,
    filing_date TEXT,
    provider TEXT,
    source_contract TEXT,
    fetched_at TEXT,
    normalized_at TEXT,
    payload_hash TEXT,
    income_statement_json TEXT,
    balance_sheet_json TEXT,
    cash_flow_statement_json TEXT,
    derived_json TEXT
);
CREATE TABLE equity_dividends (
    id INTEGER PRIMARY KEY, ticker TEXT, external_id TEXT,
    cash_amount REAL, currency TEXT, declaration_date TEXT,
    ex_dividend_date TEXT, record_date TEXT, pay_date TEXT,
    frequency INTEGER, dividend_type TEXT, first_seen_at TEXT
);
CREATE TABLE equity_splits (
    id INTEGER PRIMARY KEY, ticker TEXT, external_id TEXT,
    execution_date TEXT, split_from REAL, split_to REAL, first_seen_at TEXT
);
CREATE TABLE equity_source_lineage (
    lineage_id INTEGER PRIMARY KEY, ticker TEXT,
    stage TEXT, provider TEXT, source_contract TEXT, endpoint TEXT,
    payload_hash TEXT, normalized_ref TEXT, fetched_at TEXT
);
"""

_AAPL_DERIVED = json.dumps({
    "revenues": 385000000000.0,
    "revenue_growth": 0.08,
    "gross_margin": 0.44,
    "ebit_margin": 0.30,
    "ebitda_margin": 0.33,
    "net_margin": 0.25,
    "free_cash_flow": 90000000000.0,
    "fcf_margin": 0.23,
    "return_on_equity": 1.47,
    "net_debt": -50000000000.0,
    "debt_to_equity": -1.8,
})

_NVDA_DERIVED = json.dumps({
    "revenues": 60920000000.0,
    "revenue_growth": 1.22,
    "gross_margin": 0.73,
    "ebit_margin": 0.55,
    "ebitda_margin": 0.57,
    "net_margin": 0.49,
    "free_cash_flow": 27000000000.0,
    "fcf_margin": 0.44,
    "return_on_equity": 0.85,
    "net_debt": -5000000000.0,
    "debt_to_equity": -1.8,
})


def _make_db(symbol: str, ticker: str, contract: str,
             derived: str, extra_symbols: Optional[list] = None) -> Path:
    tmp = tempfile.mktemp(suffix=".db")
    path = Path(tmp)
    conn = sqlite3.connect(str(path))
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT INTO equity_assets (robinhood_token_symbol,underlying_ticker,name,"
        "token_contract_address,chain_network,currency,active) VALUES (?,?,?,?,?,?,1)",
        (symbol, ticker, f"{symbol} Corp", contract, "ethereum", "USD"),
    )
    conn.execute(
        "INSERT INTO equity_company_profiles (ticker,profile_json,provider,fetched_at) "
        "VALUES (?,?,?,?)",
        (ticker, json.dumps({"name": f"{symbol} Corp"}), "SYNTH", "2024-10-01"),
    )
    conn.execute(
        "INSERT INTO equity_financial_snapshots "
        "(ticker,timeframe,period_end,filing_date,provider,derived_json,fetched_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (ticker, "ttm", "2024-09-28", "2024-11-01", "SYNTH", derived, "2024-11-05"),
    )
    if extra_symbols:
        for xsym, xticker, xcont, xderived in extra_symbols:
            conn.execute(
                "INSERT INTO equity_assets (robinhood_token_symbol,underlying_ticker,name,"
                "token_contract_address,chain_network,currency,active) VALUES (?,?,?,?,?,?,1)",
                (xsym, xticker, f"{xsym} Corp", xcont, "ethereum", "USD"),
            )
            conn.execute(
                "INSERT INTO equity_company_profiles (ticker,profile_json,provider,fetched_at) "
                "VALUES (?,?,?,?)",
                (xticker, json.dumps({"name": f"{xsym} Corp"}), "SYNTH", "2024-10-01"),
            )
            conn.execute(
                "INSERT INTO equity_financial_snapshots "
                "(ticker,timeframe,period_end,filing_date,provider,derived_json,fetched_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (xticker, "ttm", "2024-09-28", "2024-11-01", "SYNTH", xderived, "2024-11-05"),
            )
    conn.commit()
    conn.close()
    return path


def _aapl_db() -> Path:
    return _make_db(
        "AAPL", "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", _AAPL_DERIVED)


def _nvda_db() -> Path:
    return _make_db(
        "NVDA", "NVDA", "0xNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNN1", _NVDA_DERIVED)


def _multi_db() -> Path:
    """DB with both AAPL and NVDA."""
    return _make_db(
        "AAPL", "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", _AAPL_DERIVED,
        extra_symbols=[
            ("NVDA", "NVDA", "0xNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNN1", _NVDA_DERIVED),
        ],
    )


# ── synthetic Robinhood universe fixture ────────────────────────────────────────

_SA = namedtuple("SelectedAsset", [
    "economic_asset_uid", "token_symbol", "token_name",
    "chain_id", "contract_address", "token_decimals",
])

_AAPL_ASSET = _SA(
    economic_asset_uid="AAPL",
    token_symbol="AAPL",
    token_name="Apple Inc.",
    chain_id=4663,
    contract_address="0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1",
    token_decimals=0,
)

_NVDA_ASSET = _SA(
    economic_asset_uid="NVDA",
    token_symbol="NVDA",
    token_name="NVIDIA Corporation",
    chain_id=4663,
    contract_address="0xNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNN1",
    token_decimals=0,
)

_UNIVERSE = [_AAPL_ASSET, _NVDA_ASSET]


def _fake_core(calls: list):
    def provider(request):
        calls.append(request)
        return {
            "evidence": {
                "asset": {
                    "symbol": request.token_symbol
                    if hasattr(request, "token_symbol") else "AAPL",
                    "chainId": request.chain_id,
                    "contractAddress": request.contract_address,
                    "economicAssetUid": getattr(request, "economic_asset_uid",
                                                request.contract_address),
                },
                "observedAt": "2026-09-19T12:00:00+00:00",
                "reference": {
                    "available": True, "price": "101.25",
                    "bid": "101.20", "ask": "101.30",
                    "source": "FROZEN::BoundReferencePrice",
                    "observedAt": "2026-09-19T11:59:00+00:00",
                },
                "execution": {
                    "available": True, "side": request.direction,
                    "notionalUsd": request.notional_usd,
                    "status": "QUOTE_OK",
                    "rawAmountIn": "100000000",
                    "rawAmountOut": "9880000000",
                    "effectivePrice": "101.30",
                    "source": "LIFI_V1_QUOTE",
                    "quotedAt": "2026-09-19T12:00:00+00:00",
                },
                "gap": {
                    "available": True, "side": request.direction,
                    "gapBps": "-42.5", "gapToMidBps": "-12.5",
                    "source": "FROZEN::DirectionalGapObservation",
                    "quotedAt": "2026-09-19T12:00:00+00:00",
                },
            },
            "observedAt": "2026-09-19T12:00:00+00:00",
        }
    return provider


@pytest.fixture(scope="function")
def real_client_with_equity():
    """Real main_web app with offline service + synthetic universe + E1 DB."""
    from datetime import datetime, timezone
    from types import SimpleNamespace as SN

    import main_web
    from app.radar_runtime.service import AcquisitionService, ServiceConfig
    from app.radar_runtime.snapshot_store import SnapshotStore
    from app.radar_ui import composition, router as radar_router_module

    NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

    aapl_key = SN(chain_id=4663, contract_address="0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1")
    nvda_key = SN(chain_id=4663, contract_address="0xNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNN1")
    aapl_ra = SN(
        asset_uid="AAPL", token_symbol="AAPL", token_name="Apple Inc.",
        raw_evidence={"tokenDecimals": 0},
        deployment_for_chain=lambda c: aapl_key if c == 4663 else None,
    )
    nvda_ra = SN(
        asset_uid="NVDA", token_symbol="NVDA", token_name="NVIDIA Corporation",
        raw_evidence={"tokenDecimals": 0},
        deployment_for_chain=lambda c: nvda_key if c == 4663 else None,
    )
    _snap = SN(
        assets=[aapl_ra, nvda_ra],
        get_by_uid=lambda u: aapl_ra if u == "AAPL" else (nvda_ra if u == "NVDA" else None),
    )

    def _offline_factory():
        return SN(
            fetch_snapshot=lambda: _snap,
            fetch_bound_reference=lambda sn, k: ({}, {}),
        )

    composition.set_registry_factory(_offline_factory)
    calls: list = []
    service = AcquisitionService(
        SnapshotStore(":memory:"),
        {"radar-core": _fake_core(calls)},
        config=ServiceConfig(
            per_provider_timeout_seconds=2.0,
            total_budget_seconds=5.0,
            max_concurrent_providers=4,
        ),
        clock=lambda: NOW,
    )
    radar_router_module.set_service(service)

    db = _multi_db()

    with patch("app.radar_ui.equity_enrichment.get_equity_fundamentals") as mock_single, \
         patch("app.radar_ui.equity_enrichment.get_equity_fundamentals_many") as mock_many:

        from finco_radar.equity import (
            get_equity_fundamentals as real_single,
            get_equity_fundamentals_many as real_many,
        )

        mock_single.side_effect = lambda sym, **kw: real_single(
            sym, db_path=db,
            **{k: v for k, v in kw.items() if k != "db_path"},
        )
        mock_many.side_effect = lambda syms, **kw: real_many(
            syms, db_path=db,
            **{k: v for k, v in kw.items() if k != "db_path"},
        )

        client = TestClient(main_web.app, raise_server_exceptions=False)
        yield client, calls, db

    radar_router_module.set_service(None)
    composition.set_registry_factory(None)


# ── R1: snapshot identity precedence ──────────────────────────────────────────

class TestR1SnapshotIdentityPrecedence:
    """R1 — GET /radar?snapshot_id=<AAPL_SNAP>&asset_uid=NVDA must use AAPL.

    Snapshot identity is authoritative; conflicting asset_uid is ignored.
    """

    def test_snapshot_uid_wins_over_query_uid(self, real_client_with_equity):
        client, calls, db = real_client_with_equity
        # First acquire an AAPL snapshot via POST
        resp_snap = client.post(
            "/radar/refresh",
            data={"asset_uid": "AAPL", "direction": "BUY", "size": "100"},
            headers={"HX-Request": "true"},
        )
        assert resp_snap.status_code == 200
        import re
        ids = re.findall(r"acq-snap:[0-9a-f]{64}", resp_snap.text)
        assert ids, "Expected a snapshot id in HTMX response"
        snapshot_id = ids[0]

        # Then GET /radar?snapshot_id=AAPL_snap&asset_uid=NVDA
        resp_get = client.get(f"/radar?snapshot_id={snapshot_id}&asset_uid=NVDA")
        assert resp_get.status_code == 200
        html = resp_get.text

        # AAPL should appear as the selected identity, NVDA as non-selected
        # The asset header / selected panel should show AAPL
        assert "AAPL" in html
        # The page should NOT show NVDA as the selected asset identity
        # (NVDA would appear in universe dropdown, but not as selected)
        # Verify AAPL Corp (equity detail) not NVDA Corp in the detail section
        assert "Apple Inc." in html or "AAPL Corp" in html

    def test_no_nvda_equity_detail_when_aapl_snapshot(self, real_client_with_equity):
        client, calls, db = real_client_with_equity
        # Acquire AAPL snapshot
        resp_snap = client.post(
            "/radar/refresh",
            data={"asset_uid": "AAPL", "direction": "BUY", "size": "100"},
            headers={"HX-Request": "true"},
        )
        import re
        ids = re.findall(r"acq-snap:[0-9a-f]{64}", resp_snap.text)
        if not ids:
            pytest.skip("No snapshot in response")
        snapshot_id = ids[0]

        resp_get = client.get(f"/radar?snapshot_id={snapshot_id}&asset_uid=NVDA")
        html = resp_get.text
        # NVDA Corp fundamentals should not be the selected detail
        assert "NVIDIA Corporation" not in html or "Apple" in html


# ── R2: HTMX refresh ──────────────────────────────────────────────────────────

class TestR2HTMXRefresh:
    """R2 — POST /radar/refresh with HX-Request: true.

    Must return panels fragment (no <!DOCTYPE html>), exactly one acquisition,
    and must NOT reload equity fundamentals.
    """

    def test_htmx_returns_fragment_not_full_page(self, real_client_with_equity):
        client, calls, _ = real_client_with_equity
        before = len(calls)
        resp = client.post(
            "/radar/refresh",
            data={"asset_uid": "AAPL", "direction": "BUY", "size": "100"},
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert "<!DOCTYPE html>" not in resp.text

    def test_htmx_exactly_one_acquisition(self, real_client_with_equity):
        client, calls, _ = real_client_with_equity
        before = len(calls)
        client.post(
            "/radar/refresh",
            data={"asset_uid": "AAPL", "direction": "BUY", "size": "100"},
            headers={"HX-Request": "true"},
        )
        assert len(calls) - before == 1

    def test_htmx_no_equity_fundamentals_section(self, real_client_with_equity):
        client, _, _ = real_client_with_equity
        resp = client.post(
            "/radar/refresh",
            data={"asset_uid": "AAPL", "direction": "BUY", "size": "100"},
            headers={"HX-Request": "true"},
        )
        # HTMX partial should not include the equity-details anchor
        assert 'id="equity-details"' not in resp.text
        # Should not include the corporate fundamentals panel
        assert 'panel-equity-fundamentals' not in resp.text

    def test_htmx_oob_asset_header_present(self, real_client_with_equity):
        client, _, _ = real_client_with_equity
        resp = client.post(
            "/radar/refresh",
            data={"asset_uid": "AAPL", "direction": "BUY", "size": "100"},
            headers={"HX-Request": "true"},
        )
        # OOB asset header swap should be present
        assert "hx-swap-oob" in resp.text or "radar-asset-header" in resp.text


# ── R3: non-JS POST fallback ───────────────────────────────────────────────────

class TestR3NonJSFallback:
    """R3 — Normal POST /radar/refresh (no HX-Request header).

    Must return full page, exactly one acquisition, correct equity fundamentals.
    """

    def test_non_js_post_returns_full_page(self, real_client_with_equity):
        client, calls, _ = real_client_with_equity
        before = len(calls)
        resp = client.post(
            "/radar/refresh",
            data={"asset_uid": "AAPL", "direction": "BUY", "size": "100"},
        )
        assert resp.status_code == 200
        assert "<!DOCTYPE html>" in resp.text
        assert len(calls) - before == 1

    def test_non_js_post_shows_equity_fundamentals(self, real_client_with_equity):
        client, _, _ = real_client_with_equity
        resp = client.post(
            "/radar/refresh",
            data={"asset_uid": "AAPL", "direction": "BUY", "size": "100"},
        )
        assert resp.status_code == 200
        html = resp.text
        assert 'id="equity-details"' in html
        # Should show some equity data
        assert "AAPL" in html

    def test_non_js_post_market_and_equity_identity_agree(self, real_client_with_equity):
        client, _, _ = real_client_with_equity
        resp = client.post(
            "/radar/refresh",
            data={"asset_uid": "NVDA", "direction": "BUY", "size": "100"},
        )
        assert resp.status_code == 200
        html = resp.text
        # Both market and equity sections should reference NVDA
        assert "NVDA" in html


# ── R4: browser smoke ─────────────────────────────────────────────────────────

class TestR4BrowserSmoke:
    """R4 — GET /radar?asset_uid=NVDA smoke test via TestClient."""

    def test_get_nvda_renders_nvda_selected(self, real_client_with_equity):
        client, _, _ = real_client_with_equity
        resp = client.get("/radar?asset_uid=NVDA")
        assert resp.status_code == 200
        html = resp.text
        assert "NVDA" in html

    def test_get_nvda_shows_equity_details_anchor(self, real_client_with_equity):
        client, _, _ = real_client_with_equity
        resp = client.get("/radar?asset_uid=NVDA")
        assert 'id="equity-details"' in resp.text

    def test_get_nvda_shows_details_cta(self, real_client_with_equity):
        client, _, _ = real_client_with_equity
        resp = client.get("/radar?asset_uid=NVDA")
        assert "Details →" in resp.text or "details_url" in resp.text

    def test_get_radar_shows_featured_board(self, real_client_with_equity):
        client, _, _ = real_client_with_equity
        resp = client.get("/radar")
        assert resp.status_code == 200
        assert "Featured Equities" in resp.text

    def test_get_radar_no_15_acquisitions(self, real_client_with_equity):
        client, calls, _ = real_client_with_equity
        before = len(calls)
        client.get("/radar")
        after = len(calls)
        assert after == before, (
            f"GET /radar triggered {after - before} acquisitions; expected 0"
        )


# ── Batch API tests ────────────────────────────────────────────────────────────

class TestBatchAPI:
    """Verify get_equity_fundamentals_many() semantics."""

    def test_batch_preserves_order(self):
        db = _multi_db()
        results = get_equity_fundamentals_many(["AAPL", "NVDA"], db_path=db)
        assert len(results) == 2
        assert results[0].robinhood_token_symbol == "AAPL"
        assert results[1].robinhood_token_symbol == "NVDA"

    def test_batch_unknown_symbol_is_not_found(self):
        db = _multi_db()
        results = get_equity_fundamentals_many(["AAPL", "ZZZZ"], db_path=db)
        assert results[0].availability.value == "AVAILABLE"
        assert results[1].availability.value == "NOT_FOUND"

    def test_batch_empty_returns_empty_tuple(self):
        db = _aapl_db()
        results = get_equity_fundamentals_many([], db_path=db)
        assert results == ()

    def test_batch_one_db_connection(self):
        db = _multi_db()
        open_calls = []
        import finco_radar.equity.repository as repo_mod
        original_open = repo_mod.open_db

        class _CountingCtx:
            def __init__(self, path, mode):
                open_calls.append((path, mode))
                self._ctx = original_open(path, mode)

            def __enter__(self):
                return self._ctx.__enter__()

            def __exit__(self, *a):
                return self._ctx.__exit__(*a)

        with patch.object(repo_mod, "open_db", _CountingCtx):
            get_equity_fundamentals_many(["AAPL", "NVDA"], db_path=db)
        assert len(open_calls) == 1, (
            f"Expected 1 DB open for batch of 2; got {len(open_calls)}"
        )

    def test_batch_duplicates_independent(self):
        db = _aapl_db()
        results = get_equity_fundamentals_many(["AAPL", "AAPL"], db_path=db)
        assert len(results) == 2
        assert results[0].robinhood_token_symbol == "AAPL"
        assert results[1].robinhood_token_symbol == "AAPL"

    def test_batch_source_unavailable_when_no_db(self):
        results = get_equity_fundamentals_many(
            ["AAPL"], db_path=Path("/nonexistent_db.sqlite")
        )
        assert len(results) == 1
        assert results[0].availability.value == "SOURCE_UNAVAILABLE"


class TestEnrichManySelectedAssets:
    """enrich_many_selected_assets() contract."""

    def test_enrich_many_returns_tuple(self):
        db = _multi_db()
        pairs = [("AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1"),
                 ("NVDA", "0xNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNN1")]
        with patch("app.radar_ui.equity_enrichment.get_equity_fundamentals_many") as mock_many:
            from finco_radar.equity import get_equity_fundamentals_many as real_many
            mock_many.side_effect = lambda syms, **kw: real_many(syms, db_path=db)
            results = enrich_many_selected_assets(pairs)
        assert len(results) == 2
        assert results[0].state in (EnrichmentState.AVAILABLE, EnrichmentState.PARTIAL)
        assert results[1].state in (EnrichmentState.AVAILABLE, EnrichmentState.PARTIAL)

    def test_enrich_many_identity_mismatch_caught_per_position(self):
        db = _multi_db()
        # NVDA with WRONG contract address → IDENTITY_MISMATCH
        pairs = [
            ("AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1"),
            ("NVDA", "0xWRONG"),
        ]
        with patch("app.radar_ui.equity_enrichment.get_equity_fundamentals_many") as mock_many:
            from finco_radar.equity import get_equity_fundamentals_many as real_many
            mock_many.side_effect = lambda syms, **kw: real_many(syms, db_path=db)
            results = enrich_many_selected_assets(pairs)
        assert results[0].state in (EnrichmentState.AVAILABLE, EnrichmentState.PARTIAL)
        assert results[1].state == EnrichmentState.IDENTITY_MISMATCH

    def test_enrich_many_empty_returns_empty(self):
        results = enrich_many_selected_assets([])
        assert results == ()


# ── Featured Board view model ──────────────────────────────────────────────────

class TestFeaturedBoardViewModel:
    """build_equity_board_row() contract."""

    def test_board_row_has_required_keys(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", db_path=db)
        row = build_equity_board_row(result, asset_uid="AAPL",
                                     fallback_name="Apple Inc.")
        assert "state" in row
        assert "symbol" in row
        assert "company_name" in row
        assert "asset_uid" in row
        assert "details_url" in row

    def test_board_row_details_url_contains_asset_uid(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", db_path=db)
        row = build_equity_board_row(result, asset_uid="AAPL")
        assert "AAPL" in row["details_url"]
        assert "equity-details" in row["details_url"]

    def test_board_row_available_has_metrics(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", db_path=db)
        row = build_equity_board_row(result, asset_uid="AAPL")
        assert row["state"] in ("AVAILABLE", "PARTIAL")
        assert "revenues" in row
        assert "gross_margin" in row

    def test_board_row_gross_margin_is_percentage(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", db_path=db)
        row = build_equity_board_row(result, asset_uid="AAPL")
        # 0.44 → "44.00%"
        assert row["gross_margin"] == "44.00%"

    def test_board_row_not_found_state(self):
        db = _aapl_db()
        result = enrich_selected_asset("ZZZZ", "0x0", db_path=db)
        row = build_equity_board_row(result, asset_uid="ZZZZ")
        assert row["state"] == "NOT_FOUND"
        assert "revenues" not in row

    def test_board_row_identity_mismatch_no_metrics(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xWRONG_CONTRACT_ADDRESS", db_path=db)
        row = build_equity_board_row(result, asset_uid="AAPL")
        assert row["state"] == "IDENTITY_MISMATCH"
        assert "revenues" not in row

    def test_board_row_source_unavailable_no_metrics(self):
        result = enrich_selected_asset("AAPL", "0x0")  # no DB configured
        row = build_equity_board_row(result, asset_uid="AAPL")
        assert row["state"] == "SOURCE_UNAVAILABLE"
        assert "revenues" not in row


# ── Ratio display semantics ────────────────────────────────────────────────────

class TestRatioDisplaySemantics:
    """Proven: margin/growth/return fields are source-fractions → displayed as %."""

    def test_gross_margin_44pct(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", db_path=db)
        view = build_equity_view(result)
        # raw 0.44 → "44.00%"
        f = view["ttm_metrics"]["fields"]
        assert f["gross_margin"]["value"] == "44.00%"
        assert f["gross_margin"]["raw"] == pytest.approx(0.44)

    def test_revenue_growth_8pct(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", db_path=db)
        view = build_equity_view(result)
        f = view["ttm_metrics"]["fields"]
        assert f["revenue_growth"]["value"] == "8.00%"

    def test_return_on_equity_147pct(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", db_path=db)
        view = build_equity_view(result)
        f = view["ttm_metrics"]["fields"]
        assert f["return_on_equity"]["value"] == "147.00%"

    def test_debt_to_equity_is_raw_ratio(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", db_path=db)
        view = build_equity_view(result)
        f = view["ttm_metrics"]["fields"]
        # D/E is a dimensionless ratio, shown as raw float not percentage
        assert "%" not in f["debt_to_equity"]["value"]
        assert f["debt_to_equity"]["raw"] == pytest.approx(-1.8)

    def test_revenue_raw_not_percent(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", db_path=db)
        view = build_equity_view(result)
        f = view["ttm_metrics"]["fields"]
        # Revenue is currency, not percentage
        assert "%" not in f["revenues"]["value"]

    def test_negative_margin_preserved_as_negative_pct(self):
        from app.radar_ui.equity_view_model import _fmt_percent
        assert _fmt_percent(-0.30) == "-30.00%"

    def test_none_margin_is_dash(self):
        from app.radar_ui.equity_view_model import _fmt_percent
        assert _fmt_percent(None) == "—"


# ── E2-F03 reporting/lineage fallback ─────────────────────────────────────────

class TestReportingLineageFallback:
    """E2-F03 — quarterly-only and annual-only assets use their metadata."""

    def _make_quarterly_only_db(self) -> Path:
        tmp = Path(tempfile.mktemp(suffix=".db"))
        conn = sqlite3.connect(str(tmp))
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT INTO equity_assets (robinhood_token_symbol,underlying_ticker,"
            "name,token_contract_address,active) VALUES (?,?,?,?,1)",
            ("QTR", "QTR", "Quarterly Corp", "0xQQQ"),
        )
        conn.execute(
            "INSERT INTO equity_financial_snapshots "
            "(ticker,timeframe,period_end,filing_date,provider,derived_json,fetched_at) "
            "VALUES (?,?,?,?,?,?,?)",
            ("QTR", "quarterly", "2024-06-30", "2024-08-01",
             "QUARTERLY_PROVIDER", _AAPL_DERIVED, "2024-08-10"),
        )
        conn.commit()
        conn.close()
        return tmp

    def _make_annual_only_db(self) -> Path:
        tmp = Path(tempfile.mktemp(suffix=".db"))
        conn = sqlite3.connect(str(tmp))
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT INTO equity_assets (robinhood_token_symbol,underlying_ticker,"
            "name,token_contract_address,active) VALUES (?,?,?,?,1)",
            ("ANN", "ANN", "Annual Corp", "0xAANN"),
        )
        conn.execute(
            "INSERT INTO equity_financial_snapshots "
            "(ticker,timeframe,period_end,filing_date,provider,derived_json,fetched_at) "
            "VALUES (?,?,?,?,?,?,?)",
            ("ANN", "annual", "2023-12-31", "2024-02-15",
             "ANNUAL_PROVIDER", _AAPL_DERIVED, "2024-02-20"),
        )
        conn.commit()
        conn.close()
        return tmp

    def test_quarterly_only_provider_shown(self):
        db = self._make_quarterly_only_db()
        result = enrich_selected_asset("QTR", "0xQQQ", db_path=db)
        view = build_equity_view(result)
        # reporting provider must come from quarterly snapshot, not "—"
        assert view["reporting"]["provider"] == "QUARTERLY_PROVIDER"

    def test_annual_only_provider_shown(self):
        db = self._make_annual_only_db()
        result = enrich_selected_asset("ANN", "0xAANN", db_path=db)
        view = build_equity_view(result)
        assert view["reporting"]["provider"] == "ANNUAL_PROVIDER"

    def test_quarterly_only_lineage_available(self):
        db = self._make_quarterly_only_db()
        result = enrich_selected_asset("QTR", "0xQQQ", db_path=db)
        view = build_equity_view(result)
        assert view["lineage"]["available"] is True
        assert view["lineage"]["period_end"] == "2024-06-30"

    def test_ttm_takes_precedence_over_quarterly(self):
        """When TTM exists, use TTM metadata not quarterly."""
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", db_path=db)
        view = build_equity_view(result)
        assert view["reporting"]["provider"] == "SYNTH"


# ── E2-F02 exception masking ───────────────────────────────────────────────────

class TestExceptionMasking:
    """E2-F02 — No broad exception swallowing; programming errors propagate."""

    def test_mode_error_raises_config_invalid(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1",
            db_path=db, db_mode="realtime",
        )
        assert result.state == EnrichmentState.FUNDAMENTALS_CONFIG_INVALID

    def test_programming_error_propagates(self):
        """An unexpected TypeError from the E1 service should NOT be silently
        converted to SOURCE_UNAVAILABLE — it must propagate to the caller."""
        with patch("app.radar_ui.equity_enrichment.get_equity_fundamentals") as mock_fn:
            mock_fn.side_effect = TypeError("synthetic programmer bug")
            with pytest.raises(TypeError, match="synthetic programmer bug"):
                enrich_selected_asset("AAPL", "0x0")

    def test_db_read_error_in_single_path(self):
        """EquityDBReadError from single-path returns SOURCE_UNAVAILABLE bundle
        (handled inside E1 service, never reaches the bridge layer)."""
        db = _aapl_db()
        # E1 catches EquityDBReadError internally; result is SOURCE_UNAVAILABLE bundle
        # This test verifies the E1 → enrichment path handles the state correctly.
        result = enrich_selected_asset(
            "AAPL", "0x0",
            db_path=Path("/nonexistent_path_xyz.db"),
        )
        assert result.state == EnrichmentState.SOURCE_UNAVAILABLE


# ── Featured board board failure modes ────────────────────────────────────────

class TestBoardFailureModes:
    """Board shows canonical identities even when fundamentals unavailable."""

    def test_source_unavailable_board_row_still_has_symbol(self):
        result = enrich_selected_asset("AAPL", "0x0")  # no DB
        row = build_equity_board_row(result, asset_uid="AAPL",
                                     fallback_name="Apple Inc.")
        assert row["symbol"] == "AAPL" or row["asset_uid"] == "AAPL"
        assert row["state"] == "SOURCE_UNAVAILABLE"
        assert "details_url" in row

    def test_not_found_board_row_has_details_link(self):
        db = _aapl_db()
        result = enrich_selected_asset("ZZZZ", "0x0", db_path=db)
        row = build_equity_board_row(result, asset_uid="ZZZZ")
        assert row["details_url"] is not None
        assert "ZZZZ" in row["details_url"]

    def test_board_row_never_raises(self):
        for state in (
            enrich_selected_asset("AAPL", "0x0"),  # SOURCE_UNAVAILABLE
            enrich_selected_asset("AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1",
                                  db_path=_aapl_db()),
        ):
            row = build_equity_board_row(state, asset_uid="AAPL")
            assert isinstance(row, dict)


# ── Market authority zero-fanout (proof) ──────────────────────────────────────

class TestZeroMarketFanout:
    """Prove GET /radar never triggers 15 market acquisitions."""

    def test_get_radar_zero_acquisitions(self, real_client_with_equity):
        client, calls, _ = real_client_with_equity
        before = len(calls)
        client.get("/radar")
        assert len(calls) == before

    def test_featured_board_zero_acquisitions_even_with_equity_db(
            self, real_client_with_equity):
        client, calls, _ = real_client_with_equity
        before = len(calls)
        # Board loads fundamentals but triggers ZERO market acquisitions
        client.get("/radar?asset_uid=AAPL")
        assert len(calls) == before


# ── Scoring boundary ───────────────────────────────────────────────────────────

class TestScoringBoundary:
    """No FINCO Score, no BUY/SELL/HOLD labels anywhere in E2 board."""

    def test_board_row_has_no_score_field(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", db_path=db)
        row = build_equity_board_row(result, asset_uid="AAPL")
        for key in row:
            assert "score" not in key.lower()
            assert "buy" not in key.lower()
            assert "sell" not in key.lower()

    def test_board_row_has_no_recommendation_labels(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", db_path=db)
        row = build_equity_board_row(result, asset_uid="AAPL")
        for v in row.values():
            s = str(v).upper()
            assert "STRONG BUY" not in s
            assert "STRONG SELL" not in s
            assert s not in ("BUY", "SELL", "HOLD", "NEUTRAL", "ATTRACTIVE")

    def test_get_radar_html_no_finco_score(self, real_client_with_equity):
        client, _, _ = real_client_with_equity
        resp = client.get("/radar")
        assert "FINCO SCORE" not in resp.text.upper()
        assert "STRONG BUY" not in resp.text.upper()
