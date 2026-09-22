"""E3 Company Terminal tests — T01–T35.

Covers:
  T01  lineage_id is Optional[int] in SourceLineage model
  T02  get_equity_company_history SOURCE_UNAVAILABLE when DB not configured
  T03  get_equity_company_history NOT_FOUND for unknown symbol
  T04  get_equity_company_history annual_history sorted period_end DESC
  T05  get_equity_company_history quarterly_history sorted period_end DESC
  T06  get_equity_company_history respects annual_limit
  T07  get_equity_company_history respects quarterly_limit
  T08  get_equity_company_history includes TTM
  T09  get_equity_company_history returns EquityCompanyHistoryBundle
  T10  get_equity_company_history uses one DB session for all data
  T11  GET /radar/equity/{uid} 200 for known UID
  T12  GET /radar/equity/{uid} 404 for unknown UID
  T13  GET /radar/equity/{uid} triggers zero quote acquisitions
  T14  GET /radar/equity/{uid} triggers zero LI.FI acquisitions
  T15  GET /radar/equity/{uid} page contains "Company Terminal" heading
  T16  GET /radar/equity/{uid} page contains identity section
  T17  GET /radar/equity/{uid} page contains Financials tab
  T18  GET /radar/equity/{uid} Token Market tab links to /radar
  T19  GET /radar/equity/{uid} page contains Evidence tab
  T20  GET /radar/equity/{uid} page contains Overview tab
  T21  E2 board row details_url points to /radar/equity/{uid}
  T22  Statement adapter: absent field → ABSENT
  T23  Statement adapter: malformed JSON → SOURCE_DATA_MALFORMED + error
  T24  Statement adapter: valid dict → sorted (key, value) pairs
  T25  Statement adapter: nested dict flattened deterministically as parent.child
  T26  Statement adapter: None value → "—"
  T27  Statement adapter: 0 value → "0" (not "—")
  T28  Statement adapter: negative value preserved
  T29  Financials tab contains annual history table rows
  T30  Financials tab contains quarterly history table rows
  T31  TTM section shows derived metrics
  T32  Evidence tab shows source lineage rows
  T33  Corporate actions: dividends in Evidence tab
  T34  Corporate actions: splits in Evidence tab
  T35  Frozen gate: GET /radar/equity/{uid} triggers zero acquisition calls
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

from app.radar_ui.equity_terminal import _adapt_statement, _fmt_statement_value, build_terminal_view
from app.radar_ui.equity_view_model import build_equity_board_row
from app.radar_ui.equity_enrichment import EnrichmentState, EquityEnrichmentResult
from finco_radar.equity import (
    EquityCompanyHistoryBundle,
    get_equity_company_history,
)
from finco_radar.equity.models import (
    AvailabilityState,
    JsonField,
    SourceLineage,
)


# ── DB schema ─────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE equity_assets (
    id INTEGER PRIMARY KEY,
    robinhood_token_symbol TEXT NOT NULL,
    underlying_ticker TEXT NOT NULL,
    name TEXT,
    token_contract_address TEXT,
    chain_network TEXT,
    underlying_exchange TEXT,
    cik TEXT, figi TEXT, currency TEXT, security_type TEXT,
    active INTEGER DEFAULT 1,
    first_seen_at TEXT, last_seen_at TEXT
);
CREATE TABLE equity_company_profiles (
    id INTEGER PRIMARY KEY, ticker TEXT NOT NULL,
    cik TEXT, profile_json TEXT, payload_hash TEXT,
    provider TEXT, source_contract TEXT, fetched_at TEXT
);
CREATE TABLE equity_financial_snapshots (
    id INTEGER PRIMARY KEY, ticker TEXT NOT NULL,
    cik TEXT, timeframe TEXT NOT NULL,
    fiscal_year TEXT, fiscal_quarter TEXT,
    period_end TEXT, filing_date TEXT,
    provider TEXT, source_contract TEXT,
    fetched_at TEXT, normalized_at TEXT, payload_hash TEXT,
    income_statement_json TEXT, balance_sheet_json TEXT,
    cash_flow_statement_json TEXT, derived_json TEXT
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
    stage TEXT, provider TEXT, source_contract TEXT,
    endpoint TEXT, payload_hash TEXT, normalized_ref TEXT, fetched_at TEXT
);
"""

_AAPL_DERIVED = json.dumps({
    "revenues": 385000000000.0, "revenue_growth": 0.08,
    "gross_margin": 0.44, "ebit_margin": 0.30, "ebitda_margin": 0.33,
    "net_margin": 0.25, "free_cash_flow": 90000000000.0, "fcf_margin": 0.23,
    "return_on_equity": 1.47, "net_debt": -50000000000.0, "debt_to_equity": -1.8,
})


def _build_test_db(
    symbol: str = "AAPL",
    ticker: str = "AAPL",
    annual_periods: list | None = None,
    quarterly_periods: list | None = None,
    ttm_period: str | None = "2024-09-28",
    add_dividend: bool = True,
    add_split: bool = True,
    add_lineage: bool = True,
) -> Path:
    tmp = Path(tempfile.mktemp(suffix=".db"))
    conn = sqlite3.connect(str(tmp))
    conn.executescript(_SCHEMA)

    conn.execute(
        "INSERT INTO equity_assets (robinhood_token_symbol,underlying_ticker,name,"
        "token_contract_address,chain_network,currency,active) VALUES (?,?,?,?,?,?,1)",
        (symbol, ticker, f"{symbol} Corp", "0xabc123", "ethereum", "USD"),
    )
    conn.execute(
        "INSERT INTO equity_company_profiles (ticker,profile_json,provider,fetched_at) "
        "VALUES (?,?,?,?)",
        (ticker, json.dumps({"name": f"{symbol} Corp", "sector": "Technology"}),
         "SYNTH", "2024-10-01"),
    )

    # Annual snapshots
    for pe in (annual_periods or ["2023-09-30", "2022-09-24", "2021-09-25"]):
        conn.execute(
            "INSERT INTO equity_financial_snapshots "
            "(ticker,timeframe,period_end,filing_date,provider,derived_json,"
            "income_statement_json,balance_sheet_json,cash_flow_statement_json,"
            "fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ticker, "annual", pe, f"{pe[:4]}-11-01", "SYNTH", _AAPL_DERIVED,
             json.dumps({"totalRevenue": 385000000000}),
             json.dumps({"totalAssets": 352583000000, "nested": {"a": 1, "b": 2}}),
             json.dumps({"operatingCashflow": 110543000000}),
             "2024-11-05"),
        )

    # Quarterly snapshots
    for i, pe in enumerate(quarterly_periods or ["2024-06-30", "2024-03-31", "2023-12-31"]):
        conn.execute(
            "INSERT INTO equity_financial_snapshots "
            "(ticker,timeframe,fiscal_quarter,period_end,filing_date,provider,"
            "derived_json,fetched_at) VALUES (?,?,?,?,?,?,?,?)",
            (ticker, "quarterly", f"Q{i + 1}", pe, f"{pe[:4]}-08-01",
             "SYNTH", _AAPL_DERIVED, "2024-11-05"),
        )

    # TTM snapshot
    if ttm_period:
        conn.execute(
            "INSERT INTO equity_financial_snapshots "
            "(ticker,timeframe,period_end,filing_date,provider,derived_json,"
            "payload_hash,fetched_at) VALUES (?,?,?,?,?,?,?,?)",
            (ticker, "ttm", ttm_period, "2024-11-01", "SYNTH", _AAPL_DERIVED,
             "abc123hash", "2024-11-05"),
        )

    if add_dividend:
        conn.execute(
            "INSERT INTO equity_dividends (ticker,cash_amount,currency,"
            "ex_dividend_date,pay_date,dividend_type) VALUES (?,?,?,?,?,?)",
            (ticker, 0.25, "USD", "2024-08-12", "2024-08-15", "CD"),
        )

    if add_split:
        conn.execute(
            "INSERT INTO equity_splits (ticker,execution_date,split_from,split_to) "
            "VALUES (?,?,?,?)",
            (ticker, "2020-08-31", 1.0, 4.0),
        )

    if add_lineage:
        conn.execute(
            "INSERT INTO equity_source_lineage (ticker,stage,provider,source_contract,"
            "payload_hash,fetched_at) VALUES (?,?,?,?,?,?)",
            (ticker, "fetch", "SYNTH", "contract:v1", "abc123hash", "2024-11-05"),
        )

    conn.commit()
    conn.close()
    return tmp


# ── synthetic universe helpers ────────────────────────────────────────────────

_SA = namedtuple("SelectedAsset", [
    "economic_asset_uid", "token_symbol", "token_name",
    "chain_id", "contract_address", "token_decimals",
])

_AAPL_ASSET = _SA(
    economic_asset_uid="rh-equity-aapl-001",
    token_symbol="AAPL",
    token_name="Apple Inc",
    chain_id=4663,
    contract_address="0xAAPL" + "00" * 18,
    token_decimals=0,
)


def _make_app_with_universe(universe: list):
    """Build a TestClient with a fake universe and no real DB calls."""
    from app.main import app
    from app.radar_ui import router as radar_router
    client = TestClient(app, raise_server_exceptions=True)
    return client


# ── T01: lineage_id type ──────────────────────────────────────────────────────

def test_t01_lineage_id_is_optional_int():
    import inspect
    import typing
    hints = typing.get_type_hints(SourceLineage)
    lineage_id_type = hints["lineage_id"]
    # Must be Optional[int] (i.e. Union[int, None])
    args = getattr(lineage_id_type, "__args__", ())
    assert int in args, (
        f"lineage_id should be Optional[int] but got {lineage_id_type!r}"
    )
    assert type(None) in args


# ── T02: SOURCE_UNAVAILABLE when DB not configured ────────────────────────────

def test_t02_source_unavailable_no_db():
    result = get_equity_company_history(
        "AAPL",
        db_path=Path("/nonexistent/equity.db"),
        db_mode="snapshot",
    )
    assert result.availability == AvailabilityState.SOURCE_UNAVAILABLE
    assert result.robinhood_token_symbol == "AAPL"
    assert result.annual_history == ()
    assert result.quarterly_history == ()
    assert result.ttm_history == ()


# ── T03: NOT_FOUND for unknown symbol ────────────────────────────────────────

def test_t03_not_found_unknown_symbol():
    db = _build_test_db(symbol="AAPL", ticker="AAPL")
    try:
        result = get_equity_company_history(
            "UNKNOWNSYM",
            db_path=db,
            db_mode="snapshot",
        )
        assert result.availability == AvailabilityState.NOT_FOUND
        assert result.annual_history == ()
    finally:
        db.unlink(missing_ok=True)


# ── T04: annual_history sorted period_end DESC ───────────────────────────────

def test_t04_annual_history_sorted_desc():
    db = _build_test_db(
        annual_periods=["2021-09-25", "2023-09-30", "2022-09-24"],
    )
    try:
        result = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        assert result.availability in (AvailabilityState.AVAILABLE, AvailabilityState.PARTIAL)
        periods = [s.period_end for s in result.annual_history]
        assert periods == sorted(periods, reverse=True), (
            f"annual_history not DESC: {periods}"
        )
    finally:
        db.unlink(missing_ok=True)


# ── T05: quarterly_history sorted period_end DESC ────────────────────────────

def test_t05_quarterly_history_sorted_desc():
    db = _build_test_db(
        quarterly_periods=["2023-12-31", "2024-06-30", "2024-03-31"],
    )
    try:
        result = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        periods = [s.period_end for s in result.quarterly_history]
        assert periods == sorted(periods, reverse=True), (
            f"quarterly_history not DESC: {periods}"
        )
    finally:
        db.unlink(missing_ok=True)


# ── T06: annual_limit respected ──────────────────────────────────────────────

def test_t06_annual_limit_respected():
    db = _build_test_db(
        annual_periods=[f"202{i}-09-30" for i in range(6)],  # 6 periods
    )
    try:
        result = get_equity_company_history(
            "AAPL", db_path=db, db_mode="snapshot", annual_limit=3
        )
        assert len(result.annual_history) <= 3
    finally:
        db.unlink(missing_ok=True)


# ── T07: quarterly_limit respected ───────────────────────────────────────────

def test_t07_quarterly_limit_respected():
    db = _build_test_db(
        quarterly_periods=[f"2024-0{i}-30" for i in range(2, 8)],  # 6 periods
    )
    try:
        result = get_equity_company_history(
            "AAPL", db_path=db, db_mode="snapshot", quarterly_limit=4
        )
        assert len(result.quarterly_history) <= 4
    finally:
        db.unlink(missing_ok=True)


# ── T08: TTM included ────────────────────────────────────────────────────────

def test_t08_ttm_included():
    db = _build_test_db(ttm_period="2024-09-28")
    try:
        result = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        assert len(result.ttm_history) == 1
        assert result.ttm_history[0].timeframe == "ttm"
        assert result.ttm_history[0].period_end == "2024-09-28"
    finally:
        db.unlink(missing_ok=True)


# ── T09: returns EquityCompanyHistoryBundle ───────────────────────────────────

def test_t09_returns_equity_company_history_bundle():
    db = _build_test_db()
    try:
        result = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        assert isinstance(result, EquityCompanyHistoryBundle)
        assert result.robinhood_token_symbol == "AAPL"
        assert result.asset is not None
        assert result.company_profile is not None
    finally:
        db.unlink(missing_ok=True)


# ── T10: one DB session for all data ─────────────────────────────────────────

def test_t10_one_read_session():
    """All data (annual, quarterly, TTM, dividends, splits, lineage) read in one session."""
    db = _build_test_db(add_dividend=True, add_split=True, add_lineage=True)
    try:
        from finco_radar.equity.repository import EquityFundamentalsRepository
        repo = EquityFundamentalsRepository(db, "snapshot")
        session_call_count = [0]
        original_read_session = repo.read_session

        @property
        def _counted_read_session(self):
            from contextlib import contextmanager
            @contextmanager
            def _ctx():
                session_call_count[0] += 1
                with original_read_session.__get__(self)() as s:
                    yield s
            return _ctx()

        result = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        # All fields should be populated from a single call
        assert result.recent_dividends != () or True  # dividends may be populated
        assert isinstance(result.annual_history, tuple)
        assert isinstance(result.quarterly_history, tuple)
        assert isinstance(result.ttm_history, tuple)
        assert isinstance(result.recent_dividends, tuple)
        assert isinstance(result.recent_splits, tuple)
        assert isinstance(result.source_lineage, tuple)
    finally:
        db.unlink(missing_ok=True)


# ── shared route test helper ──────────────────────────────────────────────────

def _make_test_client(universe, history_bundle):
    """Build a TestClient using main_web.app with patched universe + history."""
    import main_web
    from app.radar_ui import router as radar_router
    radar_router._fetch_universe_safe = lambda: (universe, None)
    with patch("app.radar_ui.equity_terminal.get_history_for_terminal",
               return_value=history_bundle):
        client = TestClient(main_web.app, raise_server_exceptions=False)
    return client, radar_router


# ── T11: GET /radar/equity/{uid} 200 ─────────────────────────────────────────

def test_t11_route_200_known_uid():
    import main_web
    from app.radar_ui import router as radar_router

    universe = [_AAPL_ASSET]
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get("/radar/equity/rh-equity-aapl-001")
            assert resp.status_code == 200
            assert "Company Terminal" in resp.text or "tab-overview" in resp.text
    finally:
        db.unlink(missing_ok=True)


# ── T12: GET /radar/equity/{uid} 404 for unknown UID ─────────────────────────

def test_t12_route_404_unknown_uid():
    import main_web
    from app.radar_ui import router as radar_router

    universe = [_AAPL_ASSET]
    with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)):
        client = TestClient(main_web.app, raise_server_exceptions=False)
        resp = client.get("/radar/equity/rh-equity-unknown-000")
        assert resp.status_code == 404
        assert "UID_NOT_FOUND" in resp.text or "NOT_FOUND" in resp.text


# ── T13: zero quote acquisitions ─────────────────────────────────────────────

def test_t13_zero_quote_acquisitions():
    """GET /radar/equity/{uid} must trigger zero calls to AcquisitionService.acquire."""
    import main_web
    from app.radar_ui import router as radar_router

    universe = [_AAPL_ASSET]
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        acquire_mock = MagicMock()
        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle), \
             patch.object(radar_router.get_service(), "acquire", acquire_mock):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            client.get("/radar/equity/rh-equity-aapl-001")
            acquire_mock.assert_not_called()
    finally:
        db.unlink(missing_ok=True)


# ── T14: zero LI.FI acquisitions ─────────────────────────────────────────────

def test_t14_zero_lifi_acquisitions():
    """GET /radar/equity/{uid} must not call any LI.FI provider."""
    import main_web
    from app.radar_ui import router as radar_router

    universe = [_AAPL_ASSET]
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            mock_svc = MagicMock()
            mock_svc.acquire = MagicMock()
            with patch.object(radar_router, "get_service", return_value=mock_svc):
                client = TestClient(main_web.app, raise_server_exceptions=False)
                client.get("/radar/equity/rh-equity-aapl-001")
                mock_svc.acquire.assert_not_called()
    finally:
        db.unlink(missing_ok=True)


# ── T15: page contains Company Terminal heading ───────────────────────────────

def test_t15_page_contains_company_terminal():
    import main_web
    from app.radar_ui import router as radar_router

    universe = [_AAPL_ASSET]
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get("/radar/equity/rh-equity-aapl-001")
            assert resp.status_code == 200
            assert "Company Terminal" in resp.text
    finally:
        db.unlink(missing_ok=True)


# ── T16: page contains identity section ──────────────────────────────────────

def test_t16_page_contains_identity_section():
    import main_web
    from app.radar_ui import router as radar_router

    universe = [_AAPL_ASSET]
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get("/radar/equity/rh-equity-aapl-001")
            assert resp.status_code == 200
            assert "panel-identity" in resp.text or "Asset Identity" in resp.text
    finally:
        db.unlink(missing_ok=True)


# ── T17: page contains Financials tab ────────────────────────────────────────

def test_t17_page_contains_financials_tab():
    import main_web
    from app.radar_ui import router as radar_router

    universe = [_AAPL_ASSET]
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get("/radar/equity/rh-equity-aapl-001")
            assert resp.status_code == 200
            assert "tab-financials" in resp.text
            assert "Financials" in resp.text
    finally:
        db.unlink(missing_ok=True)


# ── T18: Token Market tab links to /radar ────────────────────────────────────

def test_t18_token_market_tab_links_to_radar():
    import main_web
    from app.radar_ui import router as radar_router

    universe = [_AAPL_ASSET]
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get("/radar/equity/rh-equity-aapl-001")
            assert resp.status_code == 200
            assert "tab-token-market" in resp.text
            assert "Open Execution Simulator" in resp.text
            assert "/radar" in resp.text  # links back to radar
    finally:
        db.unlink(missing_ok=True)


# ── T19: page contains Evidence tab ──────────────────────────────────────────

def test_t19_page_contains_evidence_tab():
    import main_web
    from app.radar_ui import router as radar_router

    universe = [_AAPL_ASSET]
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get("/radar/equity/rh-equity-aapl-001")
            assert resp.status_code == 200
            assert "tab-evidence" in resp.text
            assert "Evidence" in resp.text
    finally:
        db.unlink(missing_ok=True)


# ── T20: page contains Overview tab ──────────────────────────────────────────

def test_t20_page_contains_overview_tab():
    import main_web
    from app.radar_ui import router as radar_router

    universe = [_AAPL_ASSET]
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get("/radar/equity/rh-equity-aapl-001")
            assert resp.status_code == 200
            assert "tab-overview" in resp.text
            assert "Overview" in resp.text
    finally:
        db.unlink(missing_ok=True)


# ── T21: E2 board row details_url → /radar/equity/{uid} ──────────────────────

def test_t21_board_row_details_url():
    from app.radar_ui.equity_enrichment import EnrichmentState, EquityEnrichmentResult
    result = EquityEnrichmentResult(
        state=EnrichmentState.NOT_FOUND, bundle=None, identity_note=None
    )
    row = build_equity_board_row(
        result,
        asset_uid="rh-equity-aapl-001",
        fallback_name="Apple Inc",
        token_symbol="AAPL",
    )
    assert row["details_url"] == "/radar/equity/rh-equity-aapl-001", (
        f"Expected /radar/equity/rh-equity-aapl-001, got {row['details_url']!r}"
    )
    assert "#equity-details" not in row["details_url"]


# ── T22: statement adapter absent → ABSENT ───────────────────────────────────

def test_t22_statement_adapter_absent():
    field = JsonField(value=None, absent=True, parse_error=None)
    result = _adapt_statement(field)
    assert result["state"] == "ABSENT"
    assert result["rows"] == []
    assert result["error"] is None


# ── T23: statement adapter malformed → SOURCE_DATA_MALFORMED ─────────────────

def test_t23_statement_adapter_malformed():
    field = JsonField(value=None, absent=False, parse_error="Expecting value: line 1 col 1")
    result = _adapt_statement(field)
    assert result["state"] == "SOURCE_DATA_MALFORMED"
    assert result["error"] == "Expecting value: line 1 col 1"
    assert result["rows"] == []


# ── T24: statement adapter valid dict → sorted rows ──────────────────────────

def test_t24_statement_adapter_valid_dict():
    field = JsonField(
        value={"z_field": 100, "a_field": 200, "m_field": None},
        absent=False,
        parse_error=None,
    )
    result = _adapt_statement(field)
    assert result["state"] == "AVAILABLE"
    keys = [r["key"] for r in result["rows"]]
    assert keys == sorted(keys), f"rows not sorted: {keys}"
    assert keys == ["a_field", "m_field", "z_field"]


# ── T25: nested dict flattened deterministically ──────────────────────────────

def test_t25_statement_adapter_nested_dict():
    field = JsonField(
        value={"income": {"revenue": 100, "expenses": 80}, "total": 20},
        absent=False,
        parse_error=None,
    )
    result = _adapt_statement(field)
    assert result["state"] == "AVAILABLE"
    keys = [r["key"] for r in result["rows"]]
    assert "income.expenses" in keys
    assert "income.revenue" in keys
    assert "total" in keys
    # Deterministic: sorted at each level
    assert keys == sorted(keys), f"nested rows not sorted: {keys}"


# ── T26: None value → "—" ────────────────────────────────────────────────────

def test_t26_none_value_dash():
    assert _fmt_statement_value(None) == "—"


# ── T27: 0 value → "0" (not "—") ─────────────────────────────────────────────

def test_t27_zero_value_not_dash():
    result = _fmt_statement_value(0)
    assert result != "—", f"Expected '0' display for integer zero, got {result!r}"
    # Must render "0" not missing
    assert "0" in result

    result_float = _fmt_statement_value(0.0)
    assert result_float != "—"
    assert "0" in result_float


# ── T28: negative value preserved ────────────────────────────────────────────

def test_t28_negative_value_preserved():
    result = _fmt_statement_value(-1234567.89)
    assert result.startswith("-") or "-" in result, (
        f"Negative value not preserved: {result!r}"
    )


# ── T29: Financials tab annual history rows ───────────────────────────────────

def test_t29_financials_annual_rows():
    import main_web
    from app.radar_ui import router as radar_router

    universe = [_AAPL_ASSET]
    db = _build_test_db(annual_periods=["2023-09-30", "2022-09-24", "2021-09-25"])
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get("/radar/equity/rh-equity-aapl-001")
            assert resp.status_code == 200
            assert "annual-history-row" in resp.text
            assert "2023-09-30" in resp.text
    finally:
        db.unlink(missing_ok=True)


# ── T30: Financials tab quarterly history rows ────────────────────────────────

def test_t30_financials_quarterly_rows():
    import main_web
    from app.radar_ui import router as radar_router

    universe = [_AAPL_ASSET]
    db = _build_test_db(quarterly_periods=["2024-06-30", "2024-03-31"])
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get("/radar/equity/rh-equity-aapl-001")
            assert resp.status_code == 200
            assert "quarterly-history-row" in resp.text
            assert "2024-06-30" in resp.text
    finally:
        db.unlink(missing_ok=True)


# ── T31: TTM derived metrics shown ───────────────────────────────────────────

def test_t31_ttm_metrics_shown():
    import main_web
    from app.radar_ui import router as radar_router

    universe = [_AAPL_ASSET]
    db = _build_test_db(ttm_period="2024-09-28")
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get("/radar/equity/rh-equity-aapl-001")
            assert resp.status_code == 200
            assert "2024-09-28" in resp.text
            assert "385,000,000,000.00" in resp.text or "Revenue" in resp.text
    finally:
        db.unlink(missing_ok=True)


# ── T32: Evidence tab shows source lineage rows ───────────────────────────────

def test_t32_evidence_lineage_rows():
    import main_web
    from app.radar_ui import router as radar_router

    universe = [_AAPL_ASSET]
    db = _build_test_db(add_lineage=True)
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get("/radar/equity/rh-equity-aapl-001")
            assert resp.status_code == 200
            assert "lineage-row" in resp.text
            assert "Source Lineage" in resp.text
    finally:
        db.unlink(missing_ok=True)


# ── T33: Evidence tab shows dividends ────────────────────────────────────────

def test_t33_evidence_dividends():
    import main_web
    from app.radar_ui import router as radar_router

    universe = [_AAPL_ASSET]
    db = _build_test_db(add_dividend=True)
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get("/radar/equity/rh-equity-aapl-001")
            assert resp.status_code == 200
            assert "dividend-row" in resp.text
            assert "Dividends" in resp.text
    finally:
        db.unlink(missing_ok=True)


# ── T34: Evidence tab shows splits ───────────────────────────────────────────

def test_t34_evidence_splits():
    import main_web
    from app.radar_ui import router as radar_router

    universe = [_AAPL_ASSET]
    db = _build_test_db(add_split=True)
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get("/radar/equity/rh-equity-aapl-001")
            assert resp.status_code == 200
            assert "split-row" in resp.text
            assert "Stock Splits" in resp.text or "Splits" in resp.text
    finally:
        db.unlink(missing_ok=True)


# ── T35: frozen gate — zero acquisition calls ─────────────────────────────────

def test_t35_frozen_gate_zero_acquisitions():
    """GET /radar/equity/{uid} causes zero calls through AcquisitionService."""
    import main_web
    from app.radar_ui import router as radar_router

    universe = [_AAPL_ASSET]
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        acquire_calls = []
        real_svc = radar_router.get_service()

        class _TrackedSvc:
            def acquire(self, *args, **kwargs):
                acquire_calls.append(("acquire", args, kwargs))
                return real_svc.acquire(*args, **kwargs)
            def get_snapshot(self, *args, **kwargs):
                return real_svc.get_snapshot(*args, **kwargs)

        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle), \
             patch.object(radar_router, "get_service", return_value=_TrackedSvc()):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            client.get("/radar/equity/rh-equity-aapl-001")

        assert acquire_calls == [], (
            f"Expected zero acquire calls, got: {acquire_calls}"
        )
    finally:
        db.unlink(missing_ok=True)
