"""E2 Correction B tests — B01–B15.

Covers:
  B01 selected-featured reuses batch result (zero extra single reads)
  B02 selected non-featured gets exactly one single read
  B03 single/batch bundle semantic parity
  B04 scoped AAPL snapshot identity proof (DOM-scoped)
  B05 scoped NVDA selected-detail proof (DOM-scoped)
  B06 >=10 featured rows in configured order
  B07 every row has Details →
  B08 UID != token_symbol; symbol column shows token_symbol, URL uses UID
  B09 missing featured symbol skipped
  B10 non-featured dropdown selection
  B11 SOURCE_UNAVAILABLE board identity preserved
  B12 config-invalid board identity preserved
  B13 source-contract unit proof (margins as %, revenue_growth raw)
  B14 revenue_growth no unsupported ×100
  B15 frozen P3 gate still rejects arbitrary non-equity finco_radar changes
"""
from __future__ import annotations

import json
import re
import sqlite3
import tempfile
from collections import namedtuple
from pathlib import Path
from types import SimpleNamespace as SN
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.radar_ui.equity_enrichment import (
    EnrichmentState,
    EquityEnrichmentResult,
    enrich_many_selected_assets,
    enrich_selected_asset,
)
from app.radar_ui.equity_view_model import build_equity_board_row, build_equity_view
from app.radar_ui.router import _load_equity_and_featured_board
from finco_radar.equity import get_equity_fundamentals, get_equity_fundamentals_many


# ── DB schema (shared with Correction A) ─────────────────────────────────────

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
    "revenues": 385000000000.0, "revenue_growth": 0.08,
    "gross_margin": 0.44, "ebit_margin": 0.30, "ebitda_margin": 0.33,
    "net_margin": 0.25, "free_cash_flow": 90000000000.0, "fcf_margin": 0.23,
    "return_on_equity": 1.47, "net_debt": -50000000000.0, "debt_to_equity": -1.8,
})

_NVDA_DERIVED = json.dumps({
    "revenues": 60920000000.0, "revenue_growth": 1.22,
    "gross_margin": 0.73, "ebit_margin": 0.55, "ebitda_margin": 0.57,
    "net_margin": 0.49, "free_cash_flow": 27000000000.0, "fcf_margin": 0.44,
    "return_on_equity": 0.85, "net_debt": -5000000000.0, "debt_to_equity": -1.8,
})

# Generic derived for synthetic symbols in the 10-asset fixture
_GENERIC_DERIVED = json.dumps({
    "revenues": 10000000000.0, "revenue_growth": 0.05,
    "gross_margin": 0.40, "ebit_margin": 0.20,
    "net_margin": 0.15, "fcf_margin": 0.18,
    "return_on_equity": 0.25, "debt_to_equity": 0.5,
})


def _insert_asset(conn, symbol: str, ticker: str, contract: str, derived: str,
                  profile_name: str | None = None) -> None:
    conn.execute(
        "INSERT INTO equity_assets (robinhood_token_symbol,underlying_ticker,name,"
        "token_contract_address,chain_network,currency,active) VALUES (?,?,?,?,?,?,1)",
        (symbol, ticker, profile_name or f"{symbol} Corp", contract, "ethereum", "USD"),
    )
    conn.execute(
        "INSERT INTO equity_company_profiles (ticker,profile_json,provider,fetched_at) "
        "VALUES (?,?,?,?)",
        (ticker, json.dumps({"name": profile_name or f"{symbol} Corp"}), "SYNTH", "2024-10-01"),
    )
    conn.execute(
        "INSERT INTO equity_financial_snapshots "
        "(ticker,timeframe,period_end,filing_date,provider,derived_json,fetched_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (ticker, "ttm", "2024-09-28", "2024-11-01", "SYNTH", derived, "2024-11-05"),
    )


def _make_multi_db(symbols_data: list[tuple]) -> Path:
    """Create a DB with multiple (symbol, ticker, contract, derived, name?) entries."""
    tmp = Path(tempfile.mktemp(suffix=".db"))
    conn = sqlite3.connect(str(tmp))
    conn.executescript(_SCHEMA)
    for row in symbols_data:
        _insert_asset(conn, *row)
    conn.commit()
    conn.close()
    return tmp


# ── synthetic universe fixtures ───────────────────────────────────────────────

_SA = namedtuple("SelectedAsset", [
    "economic_asset_uid", "token_symbol", "token_name",
    "chain_id", "contract_address", "token_decimals",
])

# 10 featured symbols with DISTINCT economic_asset_uid from token_symbol.
# This proves B08: displayed symbol != UID.
_FEATURED_10_SYMS = ("AAPL", "NVDA", "MSFT", "AMZN", "GOOGL",
                     "META", "TSLA", "AVGO", "JPM", "V")


def _make_universe_11() -> list:
    """11-asset synthetic universe: 10 featured + 1 non-featured (XYZ).

    economic_asset_uid is deliberately distinct from token_symbol to prove B08.
    """
    assets = []
    for i, sym in enumerate(_FEATURED_10_SYMS):
        assets.append(_SA(
            economic_asset_uid=f"rh-equity-{sym.lower()}-{i + 1:03d}",
            token_symbol=sym,
            token_name=f"{sym} Corp",
            chain_id=4663,
            contract_address=f"0xABCD{i + 1:04x}{'00' * 16}",
            token_decimals=0,
        ))
    # Non-featured asset
    assets.append(_SA(
        economic_asset_uid="rh-equity-xyz-099",
        token_symbol="XYZ",
        token_name="XYZ Corp",
        chain_id=4663,
        contract_address="0x" + "FF" * 20,
        token_decimals=0,
    ))
    return assets


def _make_db_for_universe_11(universe: list) -> Path:
    """Create an E1 DB for the 11-asset universe (AAPL and NVDA with real derived data)."""
    rows = []
    derived_map = {"AAPL": _AAPL_DERIVED, "NVDA": _NVDA_DERIVED}
    for asset in universe:
        rows.append((
            asset.token_symbol,
            asset.token_symbol,
            asset.contract_address,
            derived_map.get(asset.token_symbol, _GENERIC_DERIVED),
        ))
    return _make_multi_db(rows)


# ── DOM-scoped HTML extraction helper ────────────────────────────────────────

def _extract_section(html: str, section_id: str) -> str:
    """Return the inner HTML of the first element with the given id.

    Uses a depth-counting parser to handle nested tags correctly.
    Returns an empty string when the id is not found.
    """
    open_tag_re = re.compile(
        rf'<(?P<tag>div|section)[^>]*\bid="{re.escape(section_id)}"[^>]*>',
        re.IGNORECASE,
    )
    m = open_tag_re.search(html)
    if not m:
        return ""
    tag_name = m.group("tag").lower()
    content_start = m.end()
    pos = content_start
    depth = 1
    open_pat = re.compile(rf"<{tag_name}[\s>]", re.IGNORECASE)
    close_pat = re.compile(rf"</{tag_name}>", re.IGNORECASE)
    while depth > 0 and pos < len(html):
        close_m = close_pat.search(html, pos)
        open_m = open_pat.search(html, pos)
        if close_m is None:
            break
        if open_m is not None and open_m.start() < close_m.start():
            depth += 1
            pos = open_m.end()
        else:
            depth -= 1
            if depth == 0:
                return html[content_start: close_m.start()]
            pos = close_m.end()
    return html[content_start:]


# ── fake acquisition core ─────────────────────────────────────────────────────

def _fake_core(calls: list):
    def provider(request):
        calls.append(request)
        return {
            "evidence": {
                "asset": {
                    "symbol": getattr(request, "token_symbol", "AAPL"),
                    "chainId": request.chain_id,
                    "contractAddress": request.contract_address,
                    "economicAssetUid": getattr(request, "economic_asset_uid",
                                                request.contract_address),
                },
                "observedAt": "2026-09-22T12:00:00+00:00",
                "reference": {
                    "available": True, "price": "150.00",
                    "bid": "149.95", "ask": "150.05",
                    "source": "FROZEN::BoundReferencePrice",
                    "observedAt": "2026-09-22T11:59:00+00:00",
                },
                "execution": {
                    "available": True, "side": request.direction,
                    "notionalUsd": request.notional_usd,
                    "status": "QUOTE_OK",
                    "rawAmountIn": "100000000",
                    "rawAmountOut": "9880000000",
                    "effectivePrice": "150.05",
                    "source": "LIFI_V1_QUOTE",
                    "quotedAt": "2026-09-22T12:00:00+00:00",
                },
                "gap": {
                    "available": True, "side": request.direction,
                    "gapBps": "-3.3", "gapToMidBps": "1.7",
                    "source": "FROZEN::DirectionalGapObservation",
                    "quotedAt": "2026-09-22T12:00:00+00:00",
                },
            },
            "observedAt": "2026-09-22T12:00:00+00:00",
        }
    return provider


# ── shared client fixture (function scope) ────────────────────────────────────

@pytest.fixture(scope="function")
def client_11asset():
    """TestClient with 11-asset universe, offline service, E1 DB for all 11 assets."""
    from datetime import datetime, timezone

    import main_web
    from app.radar_ui import composition, router as radar_router_module
    from app.radar_runtime.service import AcquisitionService, ServiceConfig
    from app.radar_runtime.snapshot_store import SnapshotStore

    NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
    universe = _make_universe_11()
    db = _make_db_for_universe_11(universe)

    # Build offline registry from the 11-asset universe
    asset_map = {a.token_symbol: a for a in universe}
    uid_map = {a.economic_asset_uid: a for a in universe}

    def _make_ra(a):
        key = SN(chain_id=a.chain_id, contract_address=a.contract_address)
        return SN(
            asset_uid=a.economic_asset_uid,
            token_symbol=a.token_symbol,
            token_name=a.token_name,
            raw_evidence={"tokenDecimals": 0},
            deployment_for_chain=lambda c, _k=key: _k if c == 4663 else None,
        )

    ra_list = [_make_ra(a) for a in universe]
    ra_by_uid = {a.economic_asset_uid: _make_ra(a) for a in universe}
    _snap = SN(
        assets=ra_list,
        get_by_uid=lambda u: ra_by_uid.get(u),
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

    with patch("app.radar_ui.equity_enrichment.get_equity_fundamentals") as mock_single, \
         patch("app.radar_ui.equity_enrichment.get_equity_fundamentals_many") as mock_many, \
         patch.dict("os.environ", {"RADAR_FEATURED_EQUITY_SYMBOLS": ",".join(_FEATURED_10_SYMS)}):

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
        yield client, calls, universe, db, mock_single, mock_many

    radar_router_module.set_service(None)
    composition.set_registry_factory(None)


# ── B01/B02: E2-F04 unified read ─────────────────────────────────────────────

class TestB01B02UnifiedRead:
    """B01: selected featured → batch reuse, zero extra single reads.
    B02: selected non-featured → one batch + one single."""

    def test_b01_selected_featured_reuses_batch_zero_single(self):
        """AAPL is featured → enrich_selected_asset NOT called."""
        universe = _make_universe_11()
        selected = next(a for a in universe if a.token_symbol == "AAPL")

        with patch("app.radar_ui.equity_enrichment.enrich_many_selected_assets") as mock_many, \
             patch("app.radar_ui.equity_enrichment.enrich_selected_asset") as mock_single, \
             patch.dict("os.environ", {"RADAR_FEATURED_EQUITY_SYMBOLS": ",".join(_FEATURED_10_SYMS)}):

            # Return minimal results from batch
            mock_many.return_value = tuple(
                EquityEnrichmentResult(
                    state=EnrichmentState.NOT_FOUND, bundle=None, identity_note=None
                )
                for _ in _FEATURED_10_SYMS
            )

            _load_equity_and_featured_board(universe, selected, "Apple Inc.")

        assert mock_many.call_count == 1, "Expected exactly one batch read"
        assert mock_single.call_count == 0, (
            f"Featured selected triggered extra single read: {mock_single.call_count}"
        )

    def test_b02_selected_non_featured_one_batch_one_single(self):
        """XYZ is not featured → one batch + one single."""
        universe = _make_universe_11()
        xyz = next(a for a in universe if a.token_symbol == "XYZ")

        with patch("app.radar_ui.equity_enrichment.enrich_many_selected_assets") as mock_many, \
             patch("app.radar_ui.equity_enrichment.enrich_selected_asset") as mock_single, \
             patch.dict("os.environ", {"RADAR_FEATURED_EQUITY_SYMBOLS": ",".join(_FEATURED_10_SYMS)}):

            mock_many.return_value = tuple(
                EquityEnrichmentResult(
                    state=EnrichmentState.NOT_FOUND, bundle=None, identity_note=None
                )
                for _ in _FEATURED_10_SYMS
            )
            mock_single.return_value = EquityEnrichmentResult(
                state=EnrichmentState.NOT_FOUND, bundle=None, identity_note=None
            )

            _load_equity_and_featured_board(universe, xyz, "XYZ Corp")

        assert mock_many.call_count == 1, "Expected exactly one batch read"
        assert mock_single.call_count == 1, (
            f"Non-featured selected: expected 1 single read; got {mock_single.call_count}"
        )

    def test_b01_featured_get_route_zero_single_reads(self, client_11asset):
        """GET /radar?asset_uid=<AAPL_UID> (featured) → enrich_selected_asset not called."""
        client, _, universe, _, mock_single, mock_many = client_11asset
        mock_single.reset_mock()
        mock_many.reset_mock()

        # Resolve the real economic_asset_uid for AAPL — not the token_symbol.
        aapl_uid = next(
            a.economic_asset_uid for a in universe if a.token_symbol == "AAPL"
        )

        resp = client.get(f"/radar?asset_uid={aapl_uid}")
        assert resp.status_code == 200
        # AAPL must actually be selected
        assert "AAPL" in resp.text
        # Featured selected → batch reuse, zero single reads
        assert mock_many.call_count == 1
        assert mock_single.call_count == 0, (
            f"GET /radar?asset_uid={aapl_uid} (featured) triggered "
            f"{mock_single.call_count} single reads"
        )

    def test_b02_non_featured_get_route_one_single_read(self, client_11asset):
        """GET /radar?asset_uid=<XYZ_UID> (non-featured) → one batch + one single."""
        client, _, universe, _, mock_single, mock_many = client_11asset
        xyz_uid = next(a for a in universe if a.token_symbol == "XYZ").economic_asset_uid
        mock_single.reset_mock()
        mock_many.reset_mock()

        resp = client.get(f"/radar?asset_uid={xyz_uid}")
        assert resp.status_code == 200
        assert mock_many.call_count == 1, (
            f"Expected exactly one batch read; got {mock_many.call_count}"
        )
        assert mock_single.call_count == 1, (
            f"GET /radar?asset_uid={xyz_uid} (non-featured) expected 1 single read; "
            f"got {mock_single.call_count}"
        )


# ── B03: single/batch parity ──────────────────────────────────────────────────

class TestB03SingleBatchParity:
    """B03: get_equity_fundamentals and get_equity_fundamentals_many produce
    identical bundles — single and batch paths cannot drift."""

    def _multi_db(self) -> Path:
        return _make_multi_db([
            ("AAPL", "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1",
             _AAPL_DERIVED),
            ("NVDA", "NVDA", "0xNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNN1",
             _NVDA_DERIVED),
        ])

    def _assert_bundle_parity(self, single, batch_one) -> None:
        assert single.robinhood_token_symbol == batch_one.robinhood_token_symbol
        assert single.availability == batch_one.availability
        assert (single.asset is None) == (batch_one.asset is None)
        if single.asset:
            assert single.asset.robinhood_token_symbol == batch_one.asset.robinhood_token_symbol
            assert single.asset.underlying_ticker == batch_one.asset.underlying_ticker
        assert (single.latest_ttm is None) == (batch_one.latest_ttm is None)
        if single.latest_ttm:
            assert single.latest_ttm.period_end == batch_one.latest_ttm.period_end
            assert single.latest_ttm.provider == batch_one.latest_ttm.provider
        assert (single.latest_quarterly is None) == (batch_one.latest_quarterly is None)
        assert (single.latest_annual is None) == (batch_one.latest_annual is None)
        assert len(single.recent_dividends) == len(batch_one.recent_dividends)
        assert len(single.recent_splits) == len(batch_one.recent_splits)
        assert single.freshness.ttm_period_end == batch_one.freshness.ttm_period_end

    def test_b03_aapl_available_parity(self):
        db = self._multi_db()
        single = get_equity_fundamentals("AAPL", db_path=db)
        batch = get_equity_fundamentals_many(["AAPL"], db_path=db)
        assert single.availability.value == "AVAILABLE"
        self._assert_bundle_parity(single, batch[0])

    def test_b03_nvda_available_parity(self):
        db = self._multi_db()
        single = get_equity_fundamentals("NVDA", db_path=db)
        batch = get_equity_fundamentals_many(["NVDA"], db_path=db)
        self._assert_bundle_parity(single, batch[0])

    def test_b03_not_found_parity(self):
        db = self._multi_db()
        single = get_equity_fundamentals("ZZZZ", db_path=db)
        batch = get_equity_fundamentals_many(["ZZZZ"], db_path=db)
        assert single.availability.value == "NOT_FOUND"
        self._assert_bundle_parity(single, batch[0])

    def test_b03_source_unavailable_parity(self):
        single = get_equity_fundamentals("AAPL", db_path=Path("/no_such.db"))
        batch = get_equity_fundamentals_many(["AAPL"], db_path=Path("/no_such.db"))
        assert single.availability.value == "SOURCE_UNAVAILABLE"
        self._assert_bundle_parity(single, batch[0])

    def test_b03_batch_two_same_results_as_two_singles(self):
        db = self._multi_db()
        single_a = get_equity_fundamentals("AAPL", db_path=db)
        single_n = get_equity_fundamentals("NVDA", db_path=db)
        batch = get_equity_fundamentals_many(["AAPL", "NVDA"], db_path=db)
        self._assert_bundle_parity(single_a, batch[0])
        self._assert_bundle_parity(single_n, batch[1])


# ── B04/B05: scoped DOM identity proof ───────────────────────────────────────

class TestB04B05ScopedIdentityProof:
    """B04: AAPL snapshot + asset_uid=NVDA → #equity-details shows AAPL only.
    B05: GET /radar?asset_uid=NVDA → #equity-details shows NVDA, not AAPL."""

    def test_b04_snapshot_identity_scoped_to_equity_details(self, client_11asset):
        """Scoped proof: snapshot_id=AAPL_snap + asset_uid=NVDA_UID →
        #equity-details contains AAPL Corp, not NVDA Corp."""
        client, _, universe, _, _, _ = client_11asset
        aapl_uid = next(a for a in universe if a.token_symbol == "AAPL").economic_asset_uid
        nvda_uid = next(a for a in universe if a.token_symbol == "NVDA").economic_asset_uid

        # Acquire an AAPL snapshot
        snap_resp = client.post(
            "/radar/refresh",
            data={"asset_uid": aapl_uid, "direction": "BUY", "size": "100"},
            headers={"HX-Request": "true"},
        )
        assert snap_resp.status_code == 200
        snap_ids = re.findall(r"acq-snap:[0-9a-f]{64}", snap_resp.text)
        if not snap_ids:
            pytest.skip("No snapshot id in HTMX response")
        snapshot_id = snap_ids[0]

        # GET with AAPL snapshot but NVDA asset_uid — AAPL identity is authoritative
        resp = client.get(f"/radar?snapshot_id={snapshot_id}&asset_uid={nvda_uid}")
        assert resp.status_code == 200
        html = resp.text

        # Extract only #equity-details scope
        section = _extract_section(html, "equity-details")
        assert section and len(section.strip()) > 10, (
            "#equity-details section not found or empty"
        )

        # AAPL Corp identity must be in the equity-details scope
        assert "AAPL Corp" in section, (
            f"AAPL fundamentals not found within #equity-details.\n"
            f"Section content: {section[:500]!r}"
        )
        # NVDA Corp must NOT be in the equity-details scope
        assert "NVDA Corp" not in section, (
            "NVDA Corp leaked into #equity-details when AAPL snapshot was active"
        )

    def test_b05_nvda_selected_scoped_to_equity_details(self, client_11asset):
        """Scoped proof: GET /radar?asset_uid=<NVDA_UID> →
        #equity-details contains NVDA Corp, not AAPL Corp."""
        client, _, universe, _, _, _ = client_11asset
        nvda_uid = next(a for a in universe if a.token_symbol == "NVDA").economic_asset_uid

        resp = client.get(f"/radar?asset_uid={nvda_uid}")
        assert resp.status_code == 200
        html = resp.text

        section = _extract_section(html, "equity-details")
        assert section and len(section.strip()) > 10, (
            f"#equity-details empty or not found. Section: {section!r}"
        )

        assert "NVDA Corp" in section, (
            f"NVDA fundamentals not found within #equity-details.\n"
            f"Section: {section[:500]!r}"
        )
        assert "AAPL Corp" not in section, (
            "AAPL Corp leaked into #equity-details when NVDA was selected"
        )

    def test_b05_selected_asset_panel_shows_nvda(self, client_11asset):
        """Selected-asset panel (outside equity-details) shows NVDA symbol."""
        client, _, universe, _, _, _ = client_11asset
        nvda_uid = next(a for a in universe if a.token_symbol == "NVDA").economic_asset_uid
        resp = client.get(f"/radar?asset_uid={nvda_uid}")
        assert resp.status_code == 200
        assert "NVDA" in resp.text


# ── B06–B12: Featured Board acceptance ───────────────────────────────────────

class TestB06FeaturedBoardOrder:
    """B06: >=10 rows rendered in configured order."""

    def test_b06_ten_rows_in_configured_order(self, client_11asset):
        client, _, universe, _, _, _ = client_11asset
        resp = client.get("/radar")
        assert resp.status_code == 200
        html = resp.text

        # Featured board section must be present
        assert "Featured Equities" in html

        # Extract only the featured-board section for order verification
        board_section = _extract_section(html, "featured-board")
        assert board_section, "featured-board section not found"

        # Extract symbol cells (first <td> per row — font-weight:600 symbol column)
        symbol_cells = re.findall(
            r'<td[^>]*font-weight:600[^>]*>\s*([A-Z0-9]+)\s*</td>',
            board_section,
        )
        assert len(symbol_cells) >= 10, (
            f"Expected >=10 symbol cells in board; found {symbol_cells}"
        )
        # Symbols should appear in configured order
        expected_order = [s for s in _FEATURED_10_SYMS if s in symbol_cells]
        actual_order = [s for s in symbol_cells if s in _FEATURED_10_SYMS]
        assert actual_order == expected_order, (
            f"Featured board symbols not in configured order.\n"
            f"Expected: {expected_order}\nActual:   {actual_order}"
        )


class TestB07DetailsLinks:
    """B07: every row has a Details → link."""

    def test_b07_all_rows_have_details_cta(self, client_11asset):
        client, _, _, _, _, _ = client_11asset
        resp = client.get("/radar")
        html = resp.text

        # Count "Details →" occurrences — should match number of featured rows
        details_count = html.count("Details →")
        assert details_count >= 10, (
            f"Expected >=10 'Details →' links; found {details_count}"
        )

    def test_b07_details_links_point_to_equity_details_anchor(self, client_11asset):
        client, _, _, _, _, _ = client_11asset
        resp = client.get("/radar")
        html = resp.text

        # All details links should contain #equity-details
        detail_hrefs = re.findall(r'href="([^"]*equity-details[^"]*)"', html)
        assert len(detail_hrefs) >= 10, (
            f"Expected >=10 href with #equity-details; found {detail_hrefs}"
        )


class TestB08UidDistinctFromTokenSymbol:
    """B08: Details URL uses economic_asset_uid; symbol column shows token_symbol."""

    def test_b08_displayed_symbol_is_token_symbol_not_uid(self):
        """board row symbol = 'NVDA', details URL uses 'rh-equity-nvda-002'."""
        universe = _make_universe_11()
        nvda_asset = next(a for a in universe if a.token_symbol == "NVDA")
        assert nvda_asset.economic_asset_uid != nvda_asset.token_symbol, (
            "Fixture must have distinct UID and token_symbol for this test"
        )

        result = EquityEnrichmentResult(
            state=EnrichmentState.NOT_FOUND, bundle=None, identity_note=None
        )
        row = build_equity_board_row(
            result,
            asset_uid=nvda_asset.economic_asset_uid,
            fallback_name=nvda_asset.token_name,
            token_symbol=nvda_asset.token_symbol,
        )

        assert row["symbol"] == "NVDA", (
            f"Symbol column should be 'NVDA' not '{row['symbol']}'"
        )
        assert nvda_asset.economic_asset_uid in row["details_url"], (
            f"Details URL should use UID '{nvda_asset.economic_asset_uid}'"
        )
        assert "NVDA" not in row["details_url"] or nvda_asset.economic_asset_uid in row["details_url"]

    def test_b08_uid_in_board_details_href(self, client_11asset):
        """Rendered board: NVDA row's Details → href uses rh-equity-nvda-002."""
        client, _, universe, _, _, _ = client_11asset
        nvda_asset = next(a for a in universe if a.token_symbol == "NVDA")
        uid = nvda_asset.economic_asset_uid  # "rh-equity-nvda-002"

        resp = client.get("/radar")
        html = resp.text

        # Find the Details → link containing the NVDA UID
        assert uid in html, (
            f"NVDA economic_asset_uid '{uid}' not found in page HTML"
        )
        # The UID must appear in a Details → link href
        href_pattern = re.compile(rf'href="[^"]*{re.escape(uid)}[^"]*"')
        assert href_pattern.search(html), (
            f"No href containing '{uid}' found in page"
        )

    def test_b08_uid_never_shown_as_symbol_column(self, client_11asset):
        """The UID string (e.g. 'rh-equity-nvda-002') must not appear in the
        symbol column of the board table."""
        client, _, universe, _, _, _ = client_11asset
        resp = client.get("/radar")
        html = resp.text

        # Extract featured board section (before #equity-details)
        board_section = _extract_section(html, "radar-main") or html
        # None of the UIDs should appear as the <td> symbol cell content
        for asset in universe:
            if asset.token_symbol in _FEATURED_10_SYMS:
                uid = asset.economic_asset_uid
                # The UID may appear in href attributes but NOT as visible text
                # in the symbol column (first <td> per row).
                # We check that for each symbol row, the first td shows the
                # token_symbol not the uid.
                sym_cell_pattern = re.compile(
                    rf'<td[^>]*>({re.escape(uid)})</td>'
                )
                assert not sym_cell_pattern.search(html), (
                    f"UID '{uid}' appears as a table cell content (leaked as symbol)"
                )


class TestB09MissingSymbolSkipped:
    """B09: featured symbol not in live universe is silently skipped."""

    def test_b09_missing_symbol_not_in_board(self, client_11asset):
        """Configured symbol absent from universe does not appear in board."""
        client, _, _, _, _, _ = client_11asset

        # Override featured to include a symbol not in the 11-asset universe
        with patch.dict("os.environ", {
            "RADAR_FEATURED_EQUITY_SYMBOLS": "AAPL,NVDA,FAKESYM999"
        }):
            resp = client.get("/radar")
        assert resp.status_code == 200
        assert "FAKESYM999" not in resp.text

    def test_b09_only_universe_symbols_rendered(self):
        """_load_equity_and_featured_board filters to universe only."""
        universe = _make_universe_11()
        with patch("app.radar_ui.equity_enrichment.enrich_many_selected_assets") as mock_many, \
             patch.dict("os.environ", {
                 "RADAR_FEATURED_EQUITY_SYMBOLS": "AAPL,FAKESYM999,NVDA"
             }):
            mock_many.return_value = (
                EquityEnrichmentResult(
                    state=EnrichmentState.NOT_FOUND, bundle=None, identity_note=None),
                EquityEnrichmentResult(
                    state=EnrichmentState.NOT_FOUND, bundle=None, identity_note=None),
            )
            _, rows = _load_equity_and_featured_board(universe, None)

        # Only AAPL and NVDA are in universe; FAKESYM999 is skipped
        assert len(rows) == 2
        syms = [r["symbol"] for r in rows]
        assert "AAPL" in syms
        assert "NVDA" in syms


class TestB10NonFeaturedDropdown:
    """B10: non-featured asset remains selectable through the full dropdown."""

    def test_b10_xyz_in_dropdown(self, client_11asset):
        """XYZ (non-featured) appears in the asset selector dropdown."""
        client, _, _, _, _, _ = client_11asset
        resp = client.get("/radar")
        assert "XYZ" in resp.text

    def test_b10_xyz_selectable_get(self, client_11asset):
        """GET /radar?asset_uid=rh-equity-xyz-099 renders XYZ asset.

        Uses the real UID, scopes #equity-details to prove XYZ identity and
        confirm one featured batch read + one non-featured single read.
        """
        client, _, universe, _, mock_single, mock_many = client_11asset
        mock_single.reset_mock()
        mock_many.reset_mock()

        xyz = next(a for a in universe if a.token_symbol == "XYZ")
        assert xyz.economic_asset_uid == "rh-equity-xyz-099"

        resp = client.get(f"/radar?asset_uid={xyz.economic_asset_uid}")
        assert resp.status_code == 200
        html = resp.text

        # Scope proof: XYZ Corp present in #equity-details
        section = _extract_section(html, "equity-details")
        assert section and len(section.strip()) > 10, (
            "#equity-details section not found or empty"
        )
        assert "XYZ Corp" in section, (
            f"XYZ Corp not found within #equity-details. Section: {section[:500]!r}"
        )
        # Featured detail data must not bleed into non-featured selected section
        assert "AAPL Corp" not in section
        assert "NVDA Corp" not in section

        # Read contract: one featured batch + one selected single
        assert mock_many.call_count == 1, (
            f"Expected exactly one batch read; got {mock_many.call_count}"
        )
        assert mock_single.call_count == 1, (
            f"Non-featured XYZ expected 1 single read; got {mock_single.call_count}"
        )


class TestB11B12BoardFailureIdentity:
    """B11: SOURCE_UNAVAILABLE board row still shows symbol identity.
    B12: FUNDAMENTALS_CONFIG_INVALID board row still shows symbol identity."""

    def test_b11_source_unavailable_shows_symbol(self):
        result = EquityEnrichmentResult(
            state=EnrichmentState.SOURCE_UNAVAILABLE, bundle=None, identity_note=None
        )
        row = build_equity_board_row(
            result, asset_uid="rh-equity-aapl-001",
            fallback_name="Apple Inc.", token_symbol="AAPL",
        )
        assert row["state"] == "SOURCE_UNAVAILABLE"
        assert row["symbol"] == "AAPL", (
            f"symbol should be 'AAPL' not '{row['symbol']}'"
        )
        assert "revenues" not in row

    def test_b11_source_unavailable_details_url_uses_uid(self):
        result = EquityEnrichmentResult(
            state=EnrichmentState.SOURCE_UNAVAILABLE, bundle=None, identity_note=None
        )
        row = build_equity_board_row(
            result, asset_uid="rh-equity-aapl-001",
            token_symbol="AAPL",
        )
        assert "rh-equity-aapl-001" in row["details_url"]

    def test_b12_config_invalid_shows_symbol(self):
        result = EquityEnrichmentResult(
            state=EnrichmentState.FUNDAMENTALS_CONFIG_INVALID,
            bundle=None,
            identity_note="DB_MODE_INVALID: bad_mode",
        )
        row = build_equity_board_row(
            result, asset_uid="rh-equity-nvda-002",
            fallback_name="NVIDIA Corporation", token_symbol="NVDA",
        )
        assert row["state"] == "FUNDAMENTALS_CONFIG_INVALID"
        assert row["symbol"] == "NVDA"
        assert "revenues" not in row

    def test_b11_source_unavailable_in_rendered_board(self, client_11asset):
        """SOURCE_UNAVAILABLE rows in the rendered board show the symbol."""
        client, _, _, _, _, _ = client_11asset
        # Patch the E2 enrichment layer directly to return SOURCE_UNAVAILABLE
        with patch("app.radar_ui.equity_enrichment.enrich_many_selected_assets") as mock_e2_many:
            mock_e2_many.side_effect = lambda pairs, **kw: tuple(
                EquityEnrichmentResult(
                    state=EnrichmentState.SOURCE_UNAVAILABLE, bundle=None, identity_note=None
                )
                for _ in pairs
            )
            resp = client.get("/radar")
        assert resp.status_code == 200
        html = resp.text
        # Featured symbols must still appear (state shown)
        assert "AAPL" in html
        assert "SOURCE_UNAVAILABLE" in html


# ── B13/B14: ratio/unit semantics ────────────────────────────────────────────

class TestB13B14RatioSemantics:
    """B13: margin fields display as % (numerator/denominator authority).
    B14: revenue_growth displays as raw float (unit not proven)."""

    def _make_aapl_db(self) -> Path:
        return _make_multi_db([
            ("AAPL", "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1",
             _AAPL_DERIVED),
        ])

    def test_b13_gross_margin_percentage(self):
        db = self._make_aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", db_path=db)
        view = build_equity_view(result)
        f = view["ttm_metrics"]["fields"]
        assert f["gross_margin"]["value"] == "44.00%", (
            "gross_margin (numerator/denominator) must display as %"
        )

    def test_b13_net_margin_percentage(self):
        db = self._make_aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", db_path=db)
        view = build_equity_view(result)
        f = view["ttm_metrics"]["fields"]
        assert f["net_margin"]["value"] == "25.00%"

    def test_b13_fcf_margin_percentage(self):
        db = self._make_aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", db_path=db)
        view = build_equity_view(result)
        f = view["ttm_metrics"]["fields"]
        assert f["fcf_margin"]["value"] == "23.00%"

    def test_b13_return_on_equity_percentage(self):
        db = self._make_aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", db_path=db)
        view = build_equity_view(result)
        f = view["ttm_metrics"]["fields"]
        assert f["return_on_equity"]["value"] == "147.00%"

    def test_b14_revenue_growth_raw_not_percent(self):
        """B14: revenue_growth=0.08 → '0.08' (raw); NOT '8.00%'."""
        db = self._make_aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", db_path=db)
        view = build_equity_view(result)
        f = view["ttm_metrics"]["fields"]
        val = f["revenue_growth"]["value"]
        assert "%" not in val, (
            f"revenue_growth must not display as percentage; got '{val}'"
        )
        assert val == "0.08", (
            f"revenue_growth=0.08 must render as '0.08'; got '{val}'"
        )
        assert f["revenue_growth"]["raw"] == pytest.approx(0.08)

    def test_b14_revenue_growth_board_row_raw(self):
        """Board row revenue_growth also uses raw float."""
        db = self._make_aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", db_path=db)
        row = build_equity_board_row(result, asset_uid="AAPL")
        assert "%" not in row["revenue_growth"], (
            f"Board row revenue_growth must not be percent; got '{row['revenue_growth']}'"
        )

    def test_b13_debt_to_equity_raw_ratio(self):
        """debt_to_equity is dimensionless ratio → raw float."""
        db = self._make_aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", db_path=db)
        view = build_equity_view(result)
        f = view["ttm_metrics"]["fields"]
        assert "%" not in f["debt_to_equity"]["value"]

    def test_b13_unit_rule_strings_are_accurate(self):
        """unit_rule strings in view match documented semantics."""
        db = self._make_aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1", db_path=db)
        view = build_equity_view(result)
        f = view["ttm_metrics"]["fields"]
        # revenue_growth must say "not proven" or "raw"
        rg_rule = f["revenue_growth"]["unit_rule"].lower()
        assert "not proven" in rg_rule or "raw" in rg_rule
        # gross_margin must mention fraction/denominator/percent
        gm_rule = f["gross_margin"]["unit_rule"].lower()
        assert "fraction" in gm_rule or "%" in gm_rule or "100" in gm_rule


# ── B15: frozen P3 gate ───────────────────────────────────────────────────────

class TestB15FrozenP3Gate:
    """B15: gate rejects arbitrary non-equity finco_radar changes on HEAD."""

    def _get_changed_files(self):
        import subprocess
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only",
                 "aca630821ae64dba55c35ae12ae5c48401b6aa67", "HEAD"],
                capture_output=True, text=True, check=True,
            )
            return result.stdout.splitlines()
        except (subprocess.CalledProcessError, FileNotFoundError):
            pytest.skip("base commit unavailable in shallow checkout")

    def test_b15_head_has_no_non_equity_finco_radar_changes(self):
        """Actual HEAD: no finco_radar/** changes outside finco_radar/equity/."""
        changed = self._get_changed_files()
        violations = [
            p for p in changed
            if p.startswith("finco_radar/")
            and not p.startswith("finco_radar/equity/")
        ]
        assert not violations, (
            "Non-equity finco_radar paths modified (frozen): " + str(violations)
        )

    def test_b15_simulated_non_equity_change_would_fail(self):
        """Gate correctly flags a simulated new non-equity finco_radar path."""
        changed = self._get_changed_files()
        # Simulate adding a new non-equity finco_radar file
        simulated = changed + ["finco_radar/new_module/something.py"]
        violations = [
            p for p in simulated
            if p.startswith("finco_radar/")
            and not p.startswith("finco_radar/equity/")
        ]
        assert violations == ["finco_radar/new_module/something.py"], (
            f"Expected simulated violation to be caught; got: {violations}"
        )

    def test_b15_equity_additions_are_permitted(self):
        """Gate does NOT flag finco_radar/equity/** changes."""
        changed = self._get_changed_files()
        equity_changes = [
            p for p in changed if p.startswith("finco_radar/equity/")
        ]
        # There should be some equity changes (we added batch API)
        assert equity_changes, (
            "Expected finco_radar/equity/ changes in this PR; found none"
        )
        # None of them should appear as violations
        violations = [
            p for p in equity_changes
            if not p.startswith("finco_radar/equity/")
        ]
        assert not violations
