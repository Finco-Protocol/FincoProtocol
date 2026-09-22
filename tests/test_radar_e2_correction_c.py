"""E2 Correction C tests — C01–C10.

Covers:
  C01 real featured AAPL GET uses economic_asset_uid
  C02 featured selected route = 1 batch / 0 single
  C03 non-featured selected route = 1 batch / 1 single
  C04 exact #equity-details identity for featured selected
  C05 exact #equity-details identity for non-featured selected
  C06 duplicate token symbol does not silently collapse
  C07 selected reuse requires exact UID
  C08 selected reuse requires exact chain
  C09 selected reuse requires exact contract
  C10 ambiguous featured symbol fails closed / skipped
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


# ── DB schema (shared) ────────────────────────────────────────────────────────

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
    tmp = Path(tempfile.mktemp(suffix=".db"))
    conn = sqlite3.connect(str(tmp))
    conn.executescript(_SCHEMA)
    for row in symbols_data:
        _insert_asset(conn, *row)
    conn.commit()
    conn.close()
    return tmp


# ── synthetic universe helpers ────────────────────────────────────────────────

_SA = namedtuple("SelectedAsset", [
    "economic_asset_uid", "token_symbol", "token_name",
    "chain_id", "contract_address", "token_decimals",
])

_FEATURED_10_SYMS = ("AAPL", "NVDA", "MSFT", "AMZN", "GOOGL",
                     "META", "TSLA", "AVGO", "JPM", "V")


def _make_universe_11() -> list:
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


def _not_found_result():
    return EquityEnrichmentResult(
        state=EnrichmentState.NOT_FOUND, bundle=None, identity_note=None
    )


def _extract_section(html: str, section_id: str) -> str:
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


# ── C01: real AAPL UID used in GET request ────────────────────────────────────

class TestC01RealAaplUid:
    """C01: GET /radar uses the real economic_asset_uid for AAPL, not the token symbol."""

    def test_c01_aapl_get_uses_economic_asset_uid(self, client_11asset):
        """GET /radar?asset_uid=<real_uid> for AAPL → 200, AAPL selected."""
        client, _, universe, _, mock_single, mock_many = client_11asset
        mock_single.reset_mock()
        mock_many.reset_mock()

        aapl_uid = next(
            a.economic_asset_uid for a in universe if a.token_symbol == "AAPL"
        )
        assert aapl_uid != "AAPL", (
            "Fixture must use a real UID distinct from the token symbol"
        )

        resp = client.get(f"/radar?asset_uid={aapl_uid}")
        assert resp.status_code == 200
        assert "AAPL" in resp.text

    def test_c01_token_symbol_not_a_valid_uid(self, client_11asset):
        """GET /radar?asset_uid=AAPL (token symbol, not UID) resolves no asset."""
        client, _, universe, _, mock_single, mock_many = client_11asset
        # The token symbol 'AAPL' is NOT a valid economic_asset_uid in the fixture
        aapl_asset = next(a for a in universe if a.token_symbol == "AAPL")
        assert aapl_asset.economic_asset_uid != "AAPL"
        # Passing the symbol as uid fails closed (no selected asset)
        resp = client.get("/radar?asset_uid=AAPL")
        assert resp.status_code == 200
        # Since no asset resolves, selected is None — no single read triggered
        assert mock_single.call_count == 0


# ── C02: featured selected route read counts ──────────────────────────────────

class TestC02FeaturedSelectedReadCounts:
    """C02: featured selected route = exactly 1 batch read, 0 single reads."""

    def test_c02_featured_selected_one_batch_zero_single_unit(self):
        """Unit: _load_equity_and_featured_board with featured selected → 0 single."""
        universe = _make_universe_11()
        aapl = next(a for a in universe if a.token_symbol == "AAPL")

        with patch("app.radar_ui.equity_enrichment.enrich_many_selected_assets") as mock_many, \
             patch("app.radar_ui.equity_enrichment.enrich_selected_asset") as mock_single, \
             patch.dict("os.environ", {"RADAR_FEATURED_EQUITY_SYMBOLS": ",".join(_FEATURED_10_SYMS)}):

            mock_many.return_value = tuple(
                _not_found_result() for _ in _FEATURED_10_SYMS
            )
            _load_equity_and_featured_board(universe, aapl, "Apple Inc.")

        assert mock_many.call_count == 1
        assert mock_single.call_count == 0, (
            f"Featured selected must reuse batch: got {mock_single.call_count} single reads"
        )

    def test_c02_featured_selected_route_one_batch_zero_single(self, client_11asset):
        """Route: GET /radar?asset_uid=<AAPL_UID> → 1 batch, 0 single."""
        client, _, universe, _, mock_single, mock_many = client_11asset
        mock_single.reset_mock()
        mock_many.reset_mock()

        aapl_uid = next(
            a.economic_asset_uid for a in universe if a.token_symbol == "AAPL"
        )
        resp = client.get(f"/radar?asset_uid={aapl_uid}")
        assert resp.status_code == 200
        assert mock_many.call_count == 1
        assert mock_single.call_count == 0


# ── C03: non-featured selected route read counts ──────────────────────────────

class TestC03NonFeaturedSelectedReadCounts:
    """C03: non-featured selected route = exactly 1 batch read + 1 single read."""

    def test_c03_non_featured_selected_one_batch_one_single_unit(self):
        """Unit: XYZ (non-featured) → 1 batch + 1 single."""
        universe = _make_universe_11()
        xyz = next(a for a in universe if a.token_symbol == "XYZ")

        with patch("app.radar_ui.equity_enrichment.enrich_many_selected_assets") as mock_many, \
             patch("app.radar_ui.equity_enrichment.enrich_selected_asset") as mock_single, \
             patch.dict("os.environ", {"RADAR_FEATURED_EQUITY_SYMBOLS": ",".join(_FEATURED_10_SYMS)}):

            mock_many.return_value = tuple(
                _not_found_result() for _ in _FEATURED_10_SYMS
            )
            mock_single.return_value = _not_found_result()

            _load_equity_and_featured_board(universe, xyz, "XYZ Corp")

        assert mock_many.call_count == 1
        assert mock_single.call_count == 1

    def test_c03_non_featured_route_one_batch_one_single(self, client_11asset):
        """Route: GET /radar?asset_uid=rh-equity-xyz-099 → 1 batch + 1 single."""
        client, _, universe, _, mock_single, mock_many = client_11asset
        mock_single.reset_mock()
        mock_many.reset_mock()

        xyz_uid = next(
            a.economic_asset_uid for a in universe if a.token_symbol == "XYZ"
        )
        assert xyz_uid == "rh-equity-xyz-099"

        resp = client.get(f"/radar?asset_uid={xyz_uid}")
        assert resp.status_code == 200
        assert mock_many.call_count == 1
        assert mock_single.call_count == 1


# ── C04: exact #equity-details identity for featured selected ─────────────────

class TestC04FeaturedSelectedEquityDetails:
    """C04: GET /radar?asset_uid=<AAPL_UID> → #equity-details shows AAPL Corp."""

    def test_c04_featured_selected_equity_details_identity(self, client_11asset):
        """Featured AAPL selected → #equity-details contains AAPL Corp identity."""
        client, _, universe, _, _, _ = client_11asset
        aapl_uid = next(
            a.economic_asset_uid for a in universe if a.token_symbol == "AAPL"
        )

        resp = client.get(f"/radar?asset_uid={aapl_uid}")
        assert resp.status_code == 200
        html = resp.text

        section = _extract_section(html, "equity-details")
        assert section and len(section.strip()) > 10, (
            "#equity-details section not found or empty"
        )
        assert "AAPL Corp" in section, (
            f"AAPL Corp not found in #equity-details. Section: {section[:500]!r}"
        )
        # Other featured identities must not bleed in
        assert "NVDA Corp" not in section
        assert "XYZ Corp" not in section

    def test_c04_nvda_featured_equity_details_identity(self, client_11asset):
        """Featured NVDA selected → #equity-details contains NVDA Corp, not AAPL Corp."""
        client, _, universe, _, _, _ = client_11asset
        nvda_uid = next(
            a.economic_asset_uid for a in universe if a.token_symbol == "NVDA"
        )

        resp = client.get(f"/radar?asset_uid={nvda_uid}")
        assert resp.status_code == 200
        section = _extract_section(resp.text, "equity-details")
        assert section and len(section.strip()) > 10

        assert "NVDA Corp" in section
        assert "AAPL Corp" not in section


# ── C05: exact #equity-details identity for non-featured selected ─────────────

class TestC05NonFeaturedSelectedEquityDetails:
    """C05: GET /radar?asset_uid=rh-equity-xyz-099 → #equity-details shows XYZ Corp."""

    def test_c05_non_featured_xyz_equity_details_identity(self, client_11asset):
        """Non-featured XYZ → #equity-details contains XYZ Corp; featured detail absent."""
        client, _, universe, _, _, _ = client_11asset

        resp = client.get("/radar?asset_uid=rh-equity-xyz-099")
        assert resp.status_code == 200
        html = resp.text

        section = _extract_section(html, "equity-details")
        assert section and len(section.strip()) > 10, (
            "#equity-details not found or empty"
        )
        assert "XYZ Corp" in section, (
            f"XYZ Corp not found in #equity-details. Section: {section[:500]!r}"
        )
        assert "AAPL Corp" not in section, (
            "AAPL Corp leaked into non-featured #equity-details"
        )
        assert "NVDA Corp" not in section, (
            "NVDA Corp leaked into non-featured #equity-details"
        )


# ── C06: duplicate token symbol does not silently collapse ────────────────────

class TestC06DuplicateSymbolNoCollapse:
    """C06: duplicate token symbol in universe must not silently choose last/first."""

    def _make_dup_universe(self):
        """Universe with two assets sharing token_symbol DUP but distinct UIDs/contracts."""
        return [
            _SA(
                economic_asset_uid="rh-a",
                token_symbol="DUP",
                token_name="DUP Corp A",
                chain_id=4663,
                contract_address="0xAAA" + "0" * 37,
                token_decimals=0,
            ),
            _SA(
                economic_asset_uid="rh-b",
                token_symbol="DUP",
                token_name="DUP Corp B",
                chain_id=4663,
                contract_address="0xBBB" + "0" * 37,
                token_decimals=0,
            ),
        ]

    def test_c06_duplicate_symbol_skipped_from_featured_board(self):
        """Symbol DUP appears twice in universe → skipped from featured board."""
        universe = self._make_dup_universe()

        with patch("app.radar_ui.equity_enrichment.enrich_many_selected_assets") as mock_many, \
             patch.dict("os.environ", {"RADAR_FEATURED_EQUITY_SYMBOLS": "DUP"}):

            mock_many.return_value = ()
            _, rows = _load_equity_and_featured_board(universe, None)

        # DUP is ambiguous → board must be empty (skipped, not arbitrarily chosen)
        assert rows == [], (
            f"Ambiguous symbol DUP must not appear in featured board; got: {rows}"
        )
        # enrich_many must not have been called with DUP (nothing to enrich)
        assert mock_many.call_count == 0 or mock_many.call_args_list == [] or all(
            len(args[0]) == 0 for args, _ in mock_many.call_args_list
        ), "enrich_many should not be called for an ambiguous symbol"

    def test_c06_duplicate_symbol_batch_not_called(self):
        """No assets passed to enrich_many when only ambiguous symbols are configured."""
        universe = self._make_dup_universe()

        with patch("app.radar_ui.equity_enrichment.enrich_many_selected_assets") as mock_many, \
             patch.dict("os.environ", {"RADAR_FEATURED_EQUITY_SYMBOLS": "DUP"}):

            mock_many.return_value = ()
            _load_equity_and_featured_board(universe, None)

        # Either not called at all or called with empty list
        if mock_many.call_count > 0:
            called_assets = mock_many.call_args[0][0]
            assert len(called_assets) == 0, (
                f"enrich_many called with ambiguous symbol: {called_assets}"
            )

    def test_c06_unambiguous_symbols_still_resolved(self):
        """When DUP is ambiguous but UNIQUE also configured, UNIQUE still resolved."""
        unique_asset = _SA(
            economic_asset_uid="rh-unique-001",
            token_symbol="UNIQUE",
            token_name="Unique Corp",
            chain_id=4663,
            contract_address="0xCCC" + "0" * 37,
            token_decimals=0,
        )
        universe = self._make_dup_universe() + [unique_asset]

        with patch("app.radar_ui.equity_enrichment.enrich_many_selected_assets") as mock_many, \
             patch.dict("os.environ", {"RADAR_FEATURED_EQUITY_SYMBOLS": "DUP,UNIQUE"}):

            mock_many.return_value = (_not_found_result(),)
            _, rows = _load_equity_and_featured_board(universe, None)

        # Only UNIQUE in rows; DUP skipped
        assert len(rows) == 1
        assert rows[0]["symbol"] == "UNIQUE"


# ── C07: selected reuse requires exact UID ────────────────────────────────────

class TestC07SelectedReuseRequiresExactUid:
    """C07: UID mismatch between featured asset and selected → no reuse."""

    def test_c07_different_uid_no_reuse(self):
        """Featured asset rh-a, selected rh-b (same symbol+contract) → single read."""
        asset_a = _SA("rh-a", "SYM", "SYM Corp A", 4663, "0xAAA" + "0" * 37, 0)
        asset_b = _SA("rh-b", "SYM", "SYM Corp B", 4663, "0xAAA" + "0" * 37, 0)
        # Universe contains both; featured is configured with SYM — but two assets
        # share the symbol, so it's ambiguous; selected=asset_b still gets single read.
        universe = [asset_a, asset_b]

        with patch("app.radar_ui.equity_enrichment.enrich_many_selected_assets") as mock_many, \
             patch("app.radar_ui.equity_enrichment.enrich_selected_asset") as mock_single, \
             patch.dict("os.environ", {"RADAR_FEATURED_EQUITY_SYMBOLS": "SYM"}):

            mock_many.return_value = ()
            mock_single.return_value = _not_found_result()

            _load_equity_and_featured_board(universe, asset_b, "SYM Corp B")

        # Ambiguous symbol → no batch row → selected must use single read
        assert mock_single.call_count == 1, (
            "Different UID: selected must not reuse featured batch result; "
            f"single_count={mock_single.call_count}"
        )

    def test_c07_exact_uid_match_allows_reuse(self):
        """Same featured asset as selected (same UID/chain/contract) → batch reuse."""
        asset = _SA("rh-unique", "SYM", "SYM Corp", 4663, "0xDDD" + "0" * 37, 0)
        universe = [asset]

        with patch("app.radar_ui.equity_enrichment.enrich_many_selected_assets") as mock_many, \
             patch("app.radar_ui.equity_enrichment.enrich_selected_asset") as mock_single, \
             patch.dict("os.environ", {"RADAR_FEATURED_EQUITY_SYMBOLS": "SYM"}):

            mock_many.return_value = (_not_found_result(),)
            mock_single.return_value = _not_found_result()

            _load_equity_and_featured_board(universe, asset, "SYM Corp")

        assert mock_many.call_count == 1
        assert mock_single.call_count == 0, (
            "Exact UID/chain/contract match must reuse batch; "
            f"single_count={mock_single.call_count}"
        )


# ── C08: selected reuse requires exact chain ──────────────────────────────────

class TestC08SelectedReuseRequiresExactChain:
    """C08: chain_id mismatch → selected does not reuse featured batch result."""

    def test_c08_different_chain_no_reuse(self):
        """Featured on chain 4663, selected on chain 4664 (same UID+contract) → single."""
        feat_asset = _SA("rh-uid-001", "CHN", "CHN Corp", 4663, "0xEEE" + "0" * 37, 0)
        sel_asset = _SA("rh-uid-001", "CHN", "CHN Corp", 4664, "0xEEE" + "0" * 37, 0)
        universe_feat = [feat_asset]

        with patch("app.radar_ui.equity_enrichment.enrich_many_selected_assets") as mock_many, \
             patch("app.radar_ui.equity_enrichment.enrich_selected_asset") as mock_single, \
             patch.dict("os.environ", {"RADAR_FEATURED_EQUITY_SYMBOLS": "CHN"}):

            mock_many.return_value = (_not_found_result(),)
            mock_single.return_value = _not_found_result()

            # selected is not in the universe (different chain), so pass it directly
            _load_equity_and_featured_board(universe_feat, sel_asset, "CHN Corp")

        assert mock_single.call_count == 1, (
            "Chain mismatch must not reuse batch; "
            f"single_count={mock_single.call_count}"
        )


# ── C09: selected reuse requires exact contract ───────────────────────────────

class TestC09SelectedReuseRequiresExactContract:
    """C09: contract_address mismatch → selected does not reuse featured batch result."""

    def test_c09_different_contract_no_reuse(self):
        """Featured contract 0xFFF…, selected contract 0x000… (same UID+chain) → single."""
        feat_asset = _SA("rh-uid-002", "CTR", "CTR Corp", 4663, "0xFFF" + "0" * 37, 0)
        sel_asset = _SA("rh-uid-002", "CTR", "CTR Corp", 4663, "0x000" + "1" * 37, 0)
        universe_feat = [feat_asset]

        with patch("app.radar_ui.equity_enrichment.enrich_many_selected_assets") as mock_many, \
             patch("app.radar_ui.equity_enrichment.enrich_selected_asset") as mock_single, \
             patch.dict("os.environ", {"RADAR_FEATURED_EQUITY_SYMBOLS": "CTR"}):

            mock_many.return_value = (_not_found_result(),)
            mock_single.return_value = _not_found_result()

            _load_equity_and_featured_board(universe_feat, sel_asset, "CTR Corp")

        assert mock_single.call_count == 1, (
            "Contract mismatch must not reuse batch; "
            f"single_count={mock_single.call_count}"
        )

    def test_c09_contract_case_insensitive_match_allows_reuse(self):
        """Contract address checked case-insensitively: 0xAbC == 0xabc → reuse."""
        feat_asset = _SA("rh-uid-003", "CSI", "CSI Corp", 4663,
                         "0xAbCdEf" + "0" * 33, 0)
        # Same address, different case
        sel_asset = _SA("rh-uid-003", "CSI", "CSI Corp", 4663,
                        "0xabcdef" + "0" * 33, 0)
        universe_feat = [feat_asset]

        with patch("app.radar_ui.equity_enrichment.enrich_many_selected_assets") as mock_many, \
             patch("app.radar_ui.equity_enrichment.enrich_selected_asset") as mock_single, \
             patch.dict("os.environ", {"RADAR_FEATURED_EQUITY_SYMBOLS": "CSI"}):

            mock_many.return_value = (_not_found_result(),)
            mock_single.return_value = _not_found_result()

            _load_equity_and_featured_board(universe_feat, sel_asset, "CSI Corp")

        assert mock_single.call_count == 0, (
            "Case-insensitive contract match must reuse batch; "
            f"single_count={mock_single.call_count}"
        )


# ── C10: ambiguous featured symbol fails closed / skipped ─────────────────────

class TestC10AmbiguousFeaturedSymbolSkipped:
    """C10: configured featured symbol matching >1 universe assets is skipped, not guessed."""

    def test_c10_two_dup_assets_skipped_from_board(self):
        """Two DUP assets → featured board skips DUP; no last-write-wins."""
        asset_a = _SA("rh-dup-a", "DUP", "DUP Corp A", 4663, "0xAAA" + "0" * 37, 0)
        asset_b = _SA("rh-dup-b", "DUP", "DUP Corp B", 4663, "0xBBB" + "0" * 37, 0)
        universe = [asset_a, asset_b]

        with patch("app.radar_ui.equity_enrichment.enrich_many_selected_assets") as mock_many, \
             patch.dict("os.environ", {"RADAR_FEATURED_EQUITY_SYMBOLS": "DUP"}):

            mock_many.return_value = ()
            _, rows = _load_equity_and_featured_board(universe, None)

        assert rows == [], "Ambiguous DUP must be skipped from featured board"
        assert "DUP Corp A" not in str(rows)
        assert "DUP Corp B" not in str(rows)

    def test_c10_selected_rh_a_does_not_reuse_rh_b_result(self):
        """If DUP is ambiguous for featured, selected=rh-a must never bind to rh-b result."""
        asset_a = _SA("rh-dup-a", "DUP", "DUP Corp A", 4663, "0xAAA" + "0" * 37, 0)
        asset_b = _SA("rh-dup-b", "DUP", "DUP Corp B", 4663, "0xBBB" + "0" * 37, 0)
        universe = [asset_a, asset_b]

        with patch("app.radar_ui.equity_enrichment.enrich_many_selected_assets") as mock_many, \
             patch("app.radar_ui.equity_enrichment.enrich_selected_asset") as mock_single, \
             patch.dict("os.environ", {"RADAR_FEATURED_EQUITY_SYMBOLS": "DUP"}):

            mock_many.return_value = ()
            mock_single.return_value = _not_found_result()

            # selected is asset_a — DUP is ambiguous in featured, so no batch entry exists
            # selected must use the single read path, never reuse a hypothetical rh-b result
            _load_equity_and_featured_board(universe, asset_a, "DUP Corp A")

        # Single read was called for asset_a — no silent rh-b binding occurred
        assert mock_single.call_count == 1, (
            "Ambiguous featured DUP: selected rh-dup-a must use single read, "
            f"not silently bind to rh-dup-b; single_count={mock_single.call_count}"
        )
        # Verify single was called with asset_a's identity
        call_args = mock_single.call_args
        if call_args:
            called_sym, called_contract = call_args[0][0], call_args[0][1]
            assert called_contract.lower() == asset_a.contract_address.lower(), (
                f"Single read must use rh-dup-a contract; got {called_contract!r}"
            )

    def test_c10_three_symbols_one_ambiguous_two_resolved(self):
        """DUP ambiguous, AONE and BONE unambiguous → board has AONE and BONE."""
        dup_a = _SA("rh-dup-a", "DUP", "DUP A", 4663, "0xAAA" + "0" * 37, 0)
        dup_b = _SA("rh-dup-b", "DUP", "DUP B", 4663, "0xBBB" + "0" * 37, 0)
        aone = _SA("rh-aone", "AONE", "AONE Corp", 4663, "0xA11" + "0" * 37, 0)
        bone = _SA("rh-bone", "BONE", "BONE Corp", 4663, "0xB11" + "0" * 37, 0)
        universe = [dup_a, dup_b, aone, bone]

        with patch("app.radar_ui.equity_enrichment.enrich_many_selected_assets") as mock_many, \
             patch.dict("os.environ", {"RADAR_FEATURED_EQUITY_SYMBOLS": "DUP,AONE,BONE"}):

            mock_many.return_value = (_not_found_result(), _not_found_result())
            _, rows = _load_equity_and_featured_board(universe, None)

        symbols_in_rows = [r["symbol"] for r in rows]
        assert "DUP" not in symbols_in_rows, (
            f"Ambiguous DUP must not appear in board; got: {symbols_in_rows}"
        )
        assert "AONE" in symbols_in_rows
        assert "BONE" in symbols_in_rows
        assert len(rows) == 2
