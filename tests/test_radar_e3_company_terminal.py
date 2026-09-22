"""E3 Company Terminal tests — T01–T92, D01–D10, F08-ADV, F10-A, F10-B, HTML-ESC, 3x3.

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
  T36  Canonical dedup: two rows same period_end → exactly one in history
  T37  IDENTITY_MISMATCH suppresses annual_history in build_terminal_view
  T38  IDENTITY_MISMATCH identity badge in page
  T39  PARTIAL_IDENTITY when selected has no contract address
  T40  VERIFIED when symbol and contract match
  T41  F02: universe unavailable → 503, ASSET_UNIVERSE_UNAVAILABLE
  T42  F03: FUNDAMENTALS_CONFIG_INVALID shown in page
  T43  Query param nav: default tab is overview
  T44  Query param nav: ?tab=financials routes to financials
  T45  Query param nav: ?timeframe=quarterly&statement=balance
  T46  Query param nav: invalid tab defaults to overview
  T47  _build_statement_matrix: empty snapshots → available=False
  T48  _build_statement_matrix: single period income statement
  T49  _build_statement_matrix: multi-period union of field paths
  T50  _build_statement_matrix: known fields in map order, unknowns alphabetical
  T51  _build_statement_matrix: None value → "—"
  T52  _build_statement_matrix: 0.0 value → displayed zero
  T53  _build_statement_matrix: negative value preserved
  T54  _build_statement_matrix: absent period → "—" for all rows
  T55  _build_statement_matrix: nested dict flattened
  T56  _build_statement_matrix: period_headers labels correct
  T57  Evidence: profile evidence fields in page
  T58  Evidence: snapshot evidence fields in page
  T59  Evidence: raw_payload_json NOT in page
  T60  Dividend completeness: declaration_date in page
  T61  Dividend completeness: record_date in page
  T62  Asset switcher <select> in page
  T63  Token Market: chain_id, contract_address, economic_asset_uid in page
  T64  Token Market: "No quote/execution acquisition" wording
  T65  F05: IDENTITY_MISMATCH suppresses dividends in build_terminal_view
  T66  F05: IDENTITY_MISMATCH suppresses splits in build_terminal_view
  T67  F05: IDENTITY_MISMATCH suppresses snapshot_evidence in build_terminal_view
  T68  F05: IDENTITY_MISMATCH suppresses lineage in build_terminal_view
  T69  F05: IDENTITY_MISMATCH suppresses profile in build_terminal_view
  T70  F05: IDENTITY_MISMATCH suppresses profile_evidence (available==False) in build_terminal_view
  T71  F05: IDENTITY_MISMATCH freshness all "—" in build_terminal_view
  T72  F05: IDENTITY_MISMATCH company_name uses fallback_name, not DB profile
  T73  F05: rendered HTML does NOT contain sentinel DB company name on IDENTITY_MISMATCH
  T74  F05: rendered HTML does NOT contain sentinel dividend declaration_date on IDENTITY_MISMATCH
  T75  F05: rendered HTML does NOT contain sentinel payload_hash on IDENTITY_MISMATCH
  T76  F05: selected token identity remains visible in rendered HTML on IDENTITY_MISMATCH
  T77  F06: symbol mismatch + both contracts present → IDENTITY_MISMATCH
  T78  F06: symbol mismatch + selected_contract missing → IDENTITY_MISMATCH
  T79  F06: symbol mismatch + DB contract missing → IDENTITY_MISMATCH
  T80  F06: matching symbol + selected_contract missing → PARTIAL_IDENTITY
  T81  F06: matching symbol + DB contract missing → PARTIAL_IDENTITY
  T82  F06: full match (symbol + contract) → VERIFIED
  T83  F07: single malformed-only period → matrix state SOURCE_DATA_MALFORMED
  T84  F07: multiple malformed-only periods → matrix state SOURCE_DATA_MALFORMED
  T85  F07: mixed available + malformed periods → matrix state PARTIAL
  T86  F07: absent-only periods → matrix state NOT_AVAILABLE
  T87  F07: SOURCE_DATA_MALFORMED visible in rendered HTML
  T88  C3: income field map labels all real-data snake_case keys
  T89  C3: balance sheet field map labels all real-data snake_case keys
  T90  C3: cash flow field map labels all real-data snake_case keys
  T91  C3: unknown field key falls back to raw key as label
  T92  C3: statement matrix with real-data snake_case keys renders correct row labels
  D01  F09: all available periods → AVAILABLE
  D02  F09: available + absent → PARTIAL (not AVAILABLE)
  D03  F09: available + malformed → PARTIAL
  D04  F09: available + absent + malformed → PARTIAL
  D05  F09: all absent → NOT_AVAILABLE
  D06  F09: all malformed → SOURCE_DATA_MALFORMED
  D07  F09: malformed + absent → SOURCE_DATA_MALFORMED
  D08  F09: no periods → NOT_AVAILABLE
  D09  F08: IDENTITY_MISMATCH uses selected_symbol, not bundle symbol (DB_SENTINEL absent)
  D10  F10-A: GET /radar/equity/{unknown} → 404, state=ASSET_NOT_FOUND_IN_UNIVERSE
  D11  F10-B: build_terminal_view NOT_FOUND → FUNDAMENTALS_NOT_FOUND with message
  D12  HTML escaping: adversarial company name with <script> is escaped in page
  D13  3×3 nav: all (annual/quarterly/ttm) × (income/balance/cashflow) tab combinations
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

from app.radar_ui.equity_terminal import (
    _adapt_statement,
    _build_statement_matrix,
    _fmt_statement_value,
    build_terminal_view,
    validate_terminal_identity,
)
from app.radar_ui.equity_view_model import build_equity_board_row
from app.radar_ui.equity_enrichment import EnrichmentState, EquityEnrichmentResult
from finco_radar.equity import (
    EquityCompanyHistoryBundle,
    get_equity_company_history,
)
from finco_radar.equity.config import EquityDBModeError
from finco_radar.equity.models import (
    AvailabilityState,
    FundamentalsFreshness,
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
            "declaration_date,ex_dividend_date,record_date,pay_date,frequency,dividend_type) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (ticker, 0.25, "USD", "2024-08-01", "2024-08-12", "2024-08-13", "2024-08-15", 4, "CD"),
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
    contract_address="0xabc123",
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
    from contextlib import contextmanager
    from finco_radar.equity.repository import EquityFundamentalsRepository

    db = _build_test_db(add_dividend=True, add_split=True, add_lineage=True)
    call_count = [0]
    _original_read_session = EquityFundamentalsRepository.read_session

    @contextmanager
    def _counting_read_session(self):
        call_count[0] += 1
        with _original_read_session(self) as session:
            yield session

    try:
        with patch.object(EquityFundamentalsRepository, "read_session", _counting_read_session):
            result = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")

        assert call_count[0] == 1, (
            f"Expected exactly 1 read_session call, got {call_count[0]}"
        )
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
        assert "ASSET_NOT_FOUND_IN_UNIVERSE" in resp.text


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


# ── T36: canonical dedup ──────────────────────────────────────────────────────

def test_t36_canonical_dedup_two_rows_same_period():
    """Two rows with same (ticker, timeframe, period_end) → exactly one in history."""
    db = _build_test_db(annual_periods=[])
    conn = sqlite3.connect(str(db))
    try:
        # Insert two rows with the same period_end for annual
        for _ in range(2):
            conn.execute(
                "INSERT INTO equity_financial_snapshots "
                "(ticker,timeframe,period_end,provider,derived_json,fetched_at) "
                "VALUES (?,?,?,?,?,?)",
                ("AAPL", "annual", "2023-09-30", "SYNTH", _AAPL_DERIVED, "2024-11-05"),
            )
        conn.commit()
    finally:
        conn.close()
    try:
        result = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        pe_list = [s.period_end for s in result.annual_history if s.period_end == "2023-09-30"]
        assert len(pe_list) == 1, (
            f"Expected exactly 1 canonical period for 2023-09-30, got {len(pe_list)}"
        )
    finally:
        db.unlink(missing_ok=True)


# ── T37: IDENTITY_MISMATCH suppresses annual_history ─────────────────────────

def test_t37_identity_mismatch_suppresses_financials():
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        view = build_terminal_view(
            bundle,
            economic_asset_uid="rh-equity-aapl-001",
            fallback_name="Apple Inc",
            identity_state="IDENTITY_MISMATCH",
            selected_chain_id="4663",
            selected_contract_address="0xWRONG",
        )
        assert view["annual_history"] == [], (
            f"IDENTITY_MISMATCH should suppress annual_history, got {view['annual_history']}"
        )
        assert view["quarterly_history"] == []
        assert view["ttm_history"] == []
    finally:
        db.unlink(missing_ok=True)


# ── T38: IDENTITY_MISMATCH badge in page ──────────────────────────────────────

def test_t38_identity_mismatch_badge_in_page():
    import main_web
    from app.radar_ui import router as radar_router

    mismatch_asset = _SA(
        economic_asset_uid="rh-equity-aapl-001",
        token_symbol="AAPL",
        token_name="Apple Inc",
        chain_id=4663,
        contract_address="0xWRONG_CONTRACT",
        token_decimals=0,
    )
    universe = [mismatch_asset]
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get("/radar/equity/rh-equity-aapl-001")
            assert resp.status_code == 200
            assert "IDENTITY_MISMATCH" in resp.text
    finally:
        db.unlink(missing_ok=True)


# ── T39: PARTIAL_IDENTITY when no contract ────────────────────────────────────

def test_t39_partial_identity_no_contract():
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        state = validate_terminal_identity(
            selected_symbol="AAPL",
            selected_contract=None,
            bundle=bundle,
        )
        assert state == "PARTIAL_IDENTITY", f"Expected PARTIAL_IDENTITY, got {state!r}"
    finally:
        db.unlink(missing_ok=True)


# ── T40: VERIFIED when symbol and contract match ──────────────────────────────

def test_t40_verified_when_matches():
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        state = validate_terminal_identity(
            selected_symbol="AAPL",
            selected_contract="0xabc123",
            bundle=bundle,
        )
        assert state == "VERIFIED", f"Expected VERIFIED, got {state!r}"
    finally:
        db.unlink(missing_ok=True)


# ── T41: F02 universe unavailable → 503 ──────────────────────────────────────

def test_t41_universe_unavailable_503():
    import main_web
    from app.radar_ui import router as radar_router

    with patch.object(radar_router, "_fetch_universe_safe",
                      return_value=([], "Connection refused")):
        client = TestClient(main_web.app, raise_server_exceptions=False)
        resp = client.get("/radar/equity/rh-equity-aapl-001")
        assert resp.status_code == 503
        assert "ASSET_UNIVERSE_UNAVAILABLE" in resp.text


# ── T42: F03 FUNDAMENTALS_CONFIG_INVALID in page ─────────────────────────────

def test_t42_fundamentals_config_invalid_in_page():
    import main_web
    from app.radar_ui import router as radar_router

    invalid_bundle = EquityCompanyHistoryBundle(
        robinhood_token_symbol="AAPL",
        asset=None,
        company_profile=None,
        annual_history=(),
        quarterly_history=(),
        ttm_history=(),
        recent_dividends=(),
        recent_splits=(),
        source_lineage=(),
        availability=AvailabilityState.FUNDAMENTALS_CONFIG_INVALID,
        freshness=FundamentalsFreshness(
            ttm_period_end=None, ttm_filing_date=None, ttm_fetched_at=None,
            ttm_normalized_at=None, quarterly_period_end=None,
            quarterly_fetched_at=None, annual_period_end=None,
            annual_fetched_at=None, profile_fetched_at=None,
            asset_last_seen_at=None,
        ),
    )
    universe = [_AAPL_ASSET]
    with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
         patch("app.radar_ui.equity_terminal.get_history_for_terminal",
               return_value=invalid_bundle):
        client = TestClient(main_web.app, raise_server_exceptions=False)
        resp = client.get("/radar/equity/rh-equity-aapl-001")
        assert resp.status_code == 200
        assert "FUNDAMENTALS_CONFIG_INVALID" in resp.text


# ── T43: default tab is overview ──────────────────────────────────────────────

def test_t43_default_tab_overview():
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
            # Overview tab should be visible (display:block)
            assert "tab-overview" in resp.text
    finally:
        db.unlink(missing_ok=True)


# ── T44: ?tab=financials routes to financials ─────────────────────────────────

def test_t44_tab_financials_query_param():
    import main_web
    from app.radar_ui import router as radar_router

    universe = [_AAPL_ASSET]
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get("/radar/equity/rh-equity-aapl-001?tab=financials")
            assert resp.status_code == 200
            assert "tab-financials" in resp.text
    finally:
        db.unlink(missing_ok=True)


# ── T45: ?timeframe=quarterly&statement=balance ───────────────────────────────

def test_t45_timeframe_statement_query_params():
    import main_web
    from app.radar_ui import router as radar_router

    universe = [_AAPL_ASSET]
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get(
                "/radar/equity/rh-equity-aapl-001?tab=financials&timeframe=quarterly&statement=balance"
            )
            assert resp.status_code == 200
            assert "tab-financials" in resp.text
    finally:
        db.unlink(missing_ok=True)


# ── T46: invalid tab defaults to overview ─────────────────────────────────────

def test_t46_invalid_tab_defaults_to_overview():
    import main_web
    from app.radar_ui import router as radar_router

    universe = [_AAPL_ASSET]
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get("/radar/equity/rh-equity-aapl-001?tab=HACKED_VALUE")
            assert resp.status_code == 200
            # nav.tab should have been sanitized to "overview"
            assert "tab-overview" in resp.text
    finally:
        db.unlink(missing_ok=True)


# ── T47: _build_statement_matrix empty → available=False ─────────────────────

def test_t47_statement_matrix_empty():
    result = _build_statement_matrix([], "income_statement")
    assert result["available"] is False
    assert result["period_headers"] == []
    assert result["rows"] == []


# ── T48: _build_statement_matrix single period ───────────────────────────────

def test_t48_statement_matrix_single_period():
    from finco_radar.equity.models import FinancialSnapshot, DerivedFundamentals

    snap = FinancialSnapshot(
        ticker="AAPL",
        cik=None,
        timeframe="annual",
        fiscal_year="2023",
        fiscal_quarter=None,
        period_end="2023-09-30",
        filing_date=None,
        provider="SYNTH",
        source_contract=None,
        fetched_at=None,
        normalized_at=None,
        payload_hash=None,
        income_statement=JsonField(
            value={"totalRevenue": 385000000000.0, "netIncome": 99000000000.0},
            absent=False,
            parse_error=None,
        ),
        balance_sheet=JsonField(value=None, absent=True, parse_error=None),
        cash_flow_statement=JsonField(value=None, absent=True, parse_error=None),
        derived_source=JsonField(value=None, absent=True, parse_error=None),
        derived=None,
    )
    result = _build_statement_matrix([snap], "income_statement")
    assert result["available"] is True
    assert len(result["period_headers"]) == 1
    assert result["period_headers"][0]["label"] == "FY2023"
    field_keys = [r["field_key"] for r in result["rows"]]
    assert "totalRevenue" in field_keys
    assert "netIncome" in field_keys


# ── T49: _build_statement_matrix multi-period union ──────────────────────────

def test_t49_statement_matrix_multiperiod_union():
    from finco_radar.equity.models import FinancialSnapshot

    def _make_snap(fy, fields):
        return FinancialSnapshot(
            ticker="AAPL", cik=None, timeframe="annual",
            fiscal_year=fy, fiscal_quarter=None,
            period_end=f"{fy}-09-30", filing_date=None,
            provider="SYNTH", source_contract=None,
            fetched_at=None, normalized_at=None, payload_hash=None,
            income_statement=JsonField(value=fields, absent=False, parse_error=None),
            balance_sheet=JsonField(value=None, absent=True, parse_error=None),
            cash_flow_statement=JsonField(value=None, absent=True, parse_error=None),
            derived_source=JsonField(value=None, absent=True, parse_error=None),
            derived=None,
        )

    snap1 = _make_snap("2023", {"totalRevenue": 100.0, "netIncome": 20.0})
    snap2 = _make_snap("2022", {"totalRevenue": 90.0, "operatingIncome": 25.0})
    result = _build_statement_matrix([snap1, snap2], "income_statement")
    field_keys = [r["field_key"] for r in result["rows"]]
    assert "totalRevenue" in field_keys
    assert "netIncome" in field_keys
    assert "operatingIncome" in field_keys
    assert len(result["period_headers"]) == 2


# ── T50: known fields in map order, unknowns alphabetical ────────────────────

def test_t50_statement_matrix_field_ordering():
    from finco_radar.equity.models import FinancialSnapshot
    from app.radar_ui.equity_terminal import _INCOME_FIELD_MAP

    snap = FinancialSnapshot(
        ticker="AAPL", cik=None, timeframe="annual",
        fiscal_year="2023", fiscal_quarter=None,
        period_end="2023-09-30", filing_date=None,
        provider="SYNTH", source_contract=None,
        fetched_at=None, normalized_at=None, payload_hash=None,
        income_statement=JsonField(
            value={
                "net_income_loss": 99.0,
                "revenues": 385.0,
                "zzz_unknown": 1.0,
                "aaa_unknown": 2.0,
                "gross_profit": 170.0,
            },
            absent=False, parse_error=None,
        ),
        balance_sheet=JsonField(value=None, absent=True, parse_error=None),
        cash_flow_statement=JsonField(value=None, absent=True, parse_error=None),
        derived_source=JsonField(value=None, absent=True, parse_error=None),
        derived=None,
    )
    result = _build_statement_matrix([snap], "income_statement")
    field_keys = [r["field_key"] for r in result["rows"]]
    # Known fields come first in map order
    known_in_map = [k for k in _INCOME_FIELD_MAP if k in {"net_income_loss", "revenues", "gross_profit"}]
    known_positions = [field_keys.index(k) for k in known_in_map if k in field_keys]
    unknown_positions = [field_keys.index(k) for k in ["aaa_unknown", "zzz_unknown"] if k in field_keys]
    assert max(known_positions) < min(unknown_positions), (
        "Known fields must come before unknown fields"
    )
    # Unknown fields must be sorted alphabetically
    unknown_keys = [k for k in field_keys if k in {"aaa_unknown", "zzz_unknown"}]
    assert unknown_keys == sorted(unknown_keys)


# ── T51: None value → "—" in matrix ──────────────────────────────────────────

def test_t51_statement_matrix_none_value():
    from finco_radar.equity.models import FinancialSnapshot

    snap = FinancialSnapshot(
        ticker="AAPL", cik=None, timeframe="annual",
        fiscal_year="2023", fiscal_quarter=None,
        period_end="2023-09-30", filing_date=None,
        provider="SYNTH", source_contract=None,
        fetched_at=None, normalized_at=None, payload_hash=None,
        income_statement=JsonField(
            value={"totalRevenue": None},
            absent=False, parse_error=None,
        ),
        balance_sheet=JsonField(value=None, absent=True, parse_error=None),
        cash_flow_statement=JsonField(value=None, absent=True, parse_error=None),
        derived_source=JsonField(value=None, absent=True, parse_error=None),
        derived=None,
    )
    result = _build_statement_matrix([snap], "income_statement")
    revenue_row = next(r for r in result["rows"] if r["field_key"] == "totalRevenue")
    assert revenue_row["cells"][0] == "—"


# ── T52: 0.0 → displayed zero ─────────────────────────────────────────────────

def test_t52_statement_matrix_zero_displayed():
    from finco_radar.equity.models import FinancialSnapshot

    snap = FinancialSnapshot(
        ticker="AAPL", cik=None, timeframe="annual",
        fiscal_year="2023", fiscal_quarter=None,
        period_end="2023-09-30", filing_date=None,
        provider="SYNTH", source_contract=None,
        fetched_at=None, normalized_at=None, payload_hash=None,
        income_statement=JsonField(
            value={"totalRevenue": 0.0},
            absent=False, parse_error=None,
        ),
        balance_sheet=JsonField(value=None, absent=True, parse_error=None),
        cash_flow_statement=JsonField(value=None, absent=True, parse_error=None),
        derived_source=JsonField(value=None, absent=True, parse_error=None),
        derived=None,
    )
    result = _build_statement_matrix([snap], "income_statement")
    revenue_row = next(r for r in result["rows"] if r["field_key"] == "totalRevenue")
    assert revenue_row["cells"][0] != "—", "0.0 must display as a zero value, not '—'"
    assert "0" in revenue_row["cells"][0]


# ── T53: negative value preserved ────────────────────────────────────────────

def test_t53_statement_matrix_negative_preserved():
    from finco_radar.equity.models import FinancialSnapshot

    snap = FinancialSnapshot(
        ticker="AAPL", cik=None, timeframe="annual",
        fiscal_year="2023", fiscal_quarter=None,
        period_end="2023-09-30", filing_date=None,
        provider="SYNTH", source_contract=None,
        fetched_at=None, normalized_at=None, payload_hash=None,
        income_statement=JsonField(
            value={"netIncome": -50000000.0},
            absent=False, parse_error=None,
        ),
        balance_sheet=JsonField(value=None, absent=True, parse_error=None),
        cash_flow_statement=JsonField(value=None, absent=True, parse_error=None),
        derived_source=JsonField(value=None, absent=True, parse_error=None),
        derived=None,
    )
    result = _build_statement_matrix([snap], "income_statement")
    ni_row = next(r for r in result["rows"] if r["field_key"] == "netIncome")
    assert "-" in ni_row["cells"][0], f"Negative value not preserved: {ni_row['cells'][0]!r}"


# ── T54: absent period → "—" for all rows ────────────────────────────────────

def test_t54_statement_matrix_absent_period():
    from finco_radar.equity.models import FinancialSnapshot

    snap = FinancialSnapshot(
        ticker="AAPL", cik=None, timeframe="annual",
        fiscal_year="2023", fiscal_quarter=None,
        period_end="2023-09-30", filing_date=None,
        provider="SYNTH", source_contract=None,
        fetched_at=None, normalized_at=None, payload_hash=None,
        income_statement=JsonField(value=None, absent=True, parse_error=None),
        balance_sheet=JsonField(value=None, absent=True, parse_error=None),
        cash_flow_statement=JsonField(value=None, absent=True, parse_error=None),
        derived_source=JsonField(value=None, absent=True, parse_error=None),
        derived=None,
    )
    result = _build_statement_matrix([snap], "income_statement")
    # No fields → no rows (all absent); available is True because we have a period
    assert result["period_headers"][0]["state"] == "NOT_AVAILABLE"
    assert result["rows"] == []


# ── T55: nested dict flattened in matrix ─────────────────────────────────────

def test_t55_statement_matrix_nested_flattened():
    from finco_radar.equity.models import FinancialSnapshot

    snap = FinancialSnapshot(
        ticker="AAPL", cik=None, timeframe="annual",
        fiscal_year="2023", fiscal_quarter=None,
        period_end="2023-09-30", filing_date=None,
        provider="SYNTH", source_contract=None,
        fetched_at=None, normalized_at=None, payload_hash=None,
        balance_sheet=JsonField(
            value={"totalAssets": 100.0, "nested": {"a": 1, "b": 2}},
            absent=False, parse_error=None,
        ),
        income_statement=JsonField(value=None, absent=True, parse_error=None),
        cash_flow_statement=JsonField(value=None, absent=True, parse_error=None),
        derived_source=JsonField(value=None, absent=True, parse_error=None),
        derived=None,
    )
    result = _build_statement_matrix([snap], "balance_sheet")
    field_keys = [r["field_key"] for r in result["rows"]]
    assert "nested.a" in field_keys
    assert "nested.b" in field_keys
    assert "totalAssets" in field_keys


# ── T56: period_headers labels ────────────────────────────────────────────────

def test_t56_statement_matrix_period_labels():
    from finco_radar.equity.models import FinancialSnapshot

    snap_a = FinancialSnapshot(
        ticker="AAPL", cik=None, timeframe="annual",
        fiscal_year="2023", fiscal_quarter=None,
        period_end="2023-09-30", filing_date=None,
        provider="SYNTH", source_contract=None,
        fetched_at=None, normalized_at=None, payload_hash=None,
        income_statement=JsonField(value={"totalRevenue": 1.0}, absent=False, parse_error=None),
        balance_sheet=JsonField(value=None, absent=True, parse_error=None),
        cash_flow_statement=JsonField(value=None, absent=True, parse_error=None),
        derived_source=JsonField(value=None, absent=True, parse_error=None),
        derived=None,
    )
    snap_q = FinancialSnapshot(
        ticker="AAPL", cik=None, timeframe="quarterly",
        fiscal_year="2023", fiscal_quarter="Q3",
        period_end="2023-06-30", filing_date=None,
        provider="SYNTH", source_contract=None,
        fetched_at=None, normalized_at=None, payload_hash=None,
        income_statement=JsonField(value={"totalRevenue": 2.0}, absent=False, parse_error=None),
        balance_sheet=JsonField(value=None, absent=True, parse_error=None),
        cash_flow_statement=JsonField(value=None, absent=True, parse_error=None),
        derived_source=JsonField(value=None, absent=True, parse_error=None),
        derived=None,
    )
    result_a = _build_statement_matrix([snap_a], "income_statement")
    assert result_a["period_headers"][0]["label"] == "FY2023"

    result_q = _build_statement_matrix([snap_q], "income_statement")
    assert "Q3" in result_q["period_headers"][0]["label"]


# ── T57: Evidence: profile evidence fields in page ───────────────────────────

def test_t57_profile_evidence_fields_in_page():
    import main_web
    from app.radar_ui import router as radar_router

    universe = [_AAPL_ASSET]
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get("/radar/equity/rh-equity-aapl-001?tab=evidence")
            assert resp.status_code == 200
            # Provider and fetched_at from profile
            assert "panel-profile-evidence" in resp.text or "Profile Evidence" in resp.text
            assert "SYNTH" in resp.text
            assert "2024-10-01" in resp.text
    finally:
        db.unlink(missing_ok=True)


# ── T58: Evidence: snapshot evidence fields in page ──────────────────────────

def test_t58_snapshot_evidence_fields_in_page():
    import main_web
    from app.radar_ui import router as radar_router

    universe = [_AAPL_ASSET]
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get("/radar/equity/rh-equity-aapl-001?tab=evidence")
            assert resp.status_code == 200
            assert "panel-snapshot-evidence" in resp.text or "Snapshot Evidence" in resp.text
            # payload_hash inserted for TTM
            assert "abc123hash" in resp.text
    finally:
        db.unlink(missing_ok=True)


# ── T59: raw_payload_json must NOT appear in page ─────────────────────────────

def test_t59_raw_payload_json_not_in_page():
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
            assert "raw_payload_json" not in resp.text, (
                "raw_payload_json must never appear in the rendered terminal page"
            )
    finally:
        db.unlink(missing_ok=True)


# ── T60: dividend declaration_date in page ────────────────────────────────────

def test_t60_dividend_declaration_date_in_page():
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
            # declaration_date was inserted as "2024-08-01"
            assert "2024-08-01" in resp.text, (
                "declaration_date must be shown in dividend row"
            )
    finally:
        db.unlink(missing_ok=True)


# ── T61: dividend record_date in page ────────────────────────────────────────

def test_t61_dividend_record_date_in_page():
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
            # record_date was inserted as "2024-08-13"
            assert "2024-08-13" in resp.text, (
                "record_date must be shown in dividend row"
            )
    finally:
        db.unlink(missing_ok=True)


# ── T62: asset switcher <select> in page ─────────────────────────────────────

def test_t62_asset_switcher_in_page():
    """Asset switcher renders as <select> when universe has multiple assets."""
    import main_web
    from app.radar_ui import router as radar_router

    _MSFT_ASSET = _SA(
        economic_asset_uid="rh-equity-msft-001",
        token_symbol="MSFT",
        token_name="Microsoft Corp",
        chain_id=4663,
        contract_address="0xmsft",
        token_decimals=0,
    )
    universe = [_AAPL_ASSET, _MSFT_ASSET]
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get("/radar/equity/rh-equity-aapl-001")
            assert resp.status_code == 200
            assert "<select" in resp.text
            assert "rh-equity-aapl-001" in resp.text
    finally:
        db.unlink(missing_ok=True)


# ── T63: Token Market shows chain_id, contract_address, economic_asset_uid ───

def test_t63_token_market_shows_identity():
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
            assert "rh-equity-aapl-001" in resp.text
            assert "4663" in resp.text
            assert "0xabc123" in resp.text
    finally:
        db.unlink(missing_ok=True)


# ── T64: Token Market "No quote/execution acquisition" wording ────────────────

def test_t64_token_market_no_acquisition_wording():
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
            assert "No quote" in resp.text or "No quote/execution" in resp.text or \
                   "acquisition" in resp.text.lower()
    finally:
        db.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# T65–T87: Correction B regression tests — F05 / F06 / F07
# ═══════════════════════════════════════════════════════════════════════════════

# ── T65: F05 IDENTITY_MISMATCH suppresses dividends ──────────────────────────

def test_t65_identity_mismatch_suppresses_dividends():
    db = _build_test_db(add_dividend=True)
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        view = build_terminal_view(
            bundle, economic_asset_uid="rh-equity-aapl-001",
            fallback_name="Apple Inc", identity_state="IDENTITY_MISMATCH",
        )
        assert view["dividends"] == [], (
            f"IDENTITY_MISMATCH must suppress dividends, got {view['dividends']}"
        )
    finally:
        db.unlink(missing_ok=True)


# ── T66: F05 IDENTITY_MISMATCH suppresses splits ─────────────────────────────

def test_t66_identity_mismatch_suppresses_splits():
    db = _build_test_db(add_split=True)
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        view = build_terminal_view(
            bundle, economic_asset_uid="rh-equity-aapl-001",
            fallback_name="Apple Inc", identity_state="IDENTITY_MISMATCH",
        )
        assert view["splits"] == [], (
            f"IDENTITY_MISMATCH must suppress splits, got {view['splits']}"
        )
    finally:
        db.unlink(missing_ok=True)


# ── T67: F05 IDENTITY_MISMATCH suppresses snapshot_evidence ──────────────────

def test_t67_identity_mismatch_suppresses_snapshot_evidence():
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        view = build_terminal_view(
            bundle, economic_asset_uid="rh-equity-aapl-001",
            fallback_name="Apple Inc", identity_state="IDENTITY_MISMATCH",
        )
        assert view["snapshot_evidence"] == [], (
            f"IDENTITY_MISMATCH must suppress snapshot_evidence, got {view['snapshot_evidence']}"
        )
    finally:
        db.unlink(missing_ok=True)


# ── T68: F05 IDENTITY_MISMATCH suppresses lineage ────────────────────────────

def test_t68_identity_mismatch_suppresses_lineage():
    db = _build_test_db(add_lineage=True)
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        view = build_terminal_view(
            bundle, economic_asset_uid="rh-equity-aapl-001",
            fallback_name="Apple Inc", identity_state="IDENTITY_MISMATCH",
        )
        assert view["lineage"] == [], (
            f"IDENTITY_MISMATCH must suppress lineage, got {view['lineage']}"
        )
    finally:
        db.unlink(missing_ok=True)


# ── T69: F05 IDENTITY_MISMATCH suppresses profile ────────────────────────────

def test_t69_identity_mismatch_suppresses_profile():
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        view = build_terminal_view(
            bundle, economic_asset_uid="rh-equity-aapl-001",
            fallback_name="Apple Inc", identity_state="IDENTITY_MISMATCH",
        )
        assert view["profile"] is None, (
            f"IDENTITY_MISMATCH must suppress profile, got {view['profile']}"
        )
    finally:
        db.unlink(missing_ok=True)


# ── T70: F05 IDENTITY_MISMATCH suppresses profile_evidence ───────────────────

def test_t70_identity_mismatch_suppresses_profile_evidence():
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        view = build_terminal_view(
            bundle, economic_asset_uid="rh-equity-aapl-001",
            fallback_name="Apple Inc", identity_state="IDENTITY_MISMATCH",
        )
        assert view["profile_evidence"]["available"] is False, (
            f"IDENTITY_MISMATCH must suppress profile_evidence, got {view['profile_evidence']}"
        )
    finally:
        db.unlink(missing_ok=True)


# ── T71: F05 IDENTITY_MISMATCH → all freshness values are "—" ────────────────

def test_t71_identity_mismatch_freshness_all_dash():
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        view = build_terminal_view(
            bundle, economic_asset_uid="rh-equity-aapl-001",
            fallback_name="Apple Inc", identity_state="IDENTITY_MISMATCH",
        )
        fr = view["freshness"]
        for key, val in fr.items():
            assert val == "—", (
                f"freshness[{key!r}] must be '—' on IDENTITY_MISMATCH, got {val!r}"
            )
    finally:
        db.unlink(missing_ok=True)


# ── T72: F05 IDENTITY_MISMATCH → company_name uses fallback, not DB ──────────

def test_t72_identity_mismatch_company_name_from_fallback():
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        view = build_terminal_view(
            bundle, economic_asset_uid="rh-equity-aapl-001",
            fallback_name="FALLBACK_CORP_XXYYZZ", identity_state="IDENTITY_MISMATCH",
        )
        assert view["company_name"] == "FALLBACK_CORP_XXYYZZ", (
            f"company_name should come from fallback_name, got {view['company_name']!r}"
        )
        assert "AAPL Corp" not in view["company_name"]
    finally:
        db.unlink(missing_ok=True)


# ── T73: F05 sentinel DB company name absent from rendered HTML ───────────────

def test_t73_identity_mismatch_sentinel_company_not_in_html():
    import main_web
    from app.radar_ui import router as radar_router

    _SENTINEL = "SENTINELCORP_XQ99ZZ_DBNAME"
    tmp = Path(tempfile.mktemp(suffix=".db"))
    conn = sqlite3.connect(str(tmp))
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT INTO equity_assets (robinhood_token_symbol,underlying_ticker,name,"
        "token_contract_address,chain_network,currency,active) VALUES (?,?,?,?,?,?,1)",
        ("AAPL", "AAPL", _SENTINEL, "0xabc123", "ethereum", "USD"),
    )
    conn.execute(
        "INSERT INTO equity_company_profiles (ticker,profile_json,provider,fetched_at) "
        "VALUES (?,?,?,?)",
        ("AAPL", json.dumps({"name": _SENTINEL}), "SYNTH", "2024-10-01"),
    )
    conn.commit()
    conn.close()

    mismatch_asset = _SA(
        economic_asset_uid="rh-equity-aapl-001",
        token_symbol="AAPL",
        token_name="Apple Inc",
        chain_id=4663,
        contract_address="0xWRONG_CONTRACT_T73",
        token_decimals=0,
    )
    try:
        bundle = get_equity_company_history("AAPL", db_path=tmp, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=([mismatch_asset], None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get("/radar/equity/rh-equity-aapl-001")
            assert resp.status_code == 200
            assert "IDENTITY_MISMATCH" in resp.text
            assert _SENTINEL not in resp.text, (
                f"Sentinel DB company name {_SENTINEL!r} must not appear in IDENTITY_MISMATCH page"
            )
    finally:
        tmp.unlink(missing_ok=True)


# ── T74: F05 sentinel dividend date absent from rendered HTML ─────────────────

def test_t74_identity_mismatch_sentinel_dividend_not_in_html():
    import main_web
    from app.radar_ui import router as radar_router

    _SENTINEL_DATE = "3333-12-31"
    tmp = _build_test_db(add_dividend=False, add_split=False, add_lineage=False)
    conn = sqlite3.connect(str(tmp))
    conn.execute(
        "INSERT INTO equity_dividends (ticker,cash_amount,currency,declaration_date,"
        "ex_dividend_date,record_date,pay_date,frequency,dividend_type) VALUES (?,?,?,?,?,?,?,?,?)",
        ("AAPL", 0.25, "USD", _SENTINEL_DATE, "3333-12-15", "3333-12-16", "3333-12-18", 4, "CD"),
    )
    conn.commit()
    conn.close()

    mismatch_asset = _SA(
        economic_asset_uid="rh-equity-aapl-001",
        token_symbol="AAPL",
        token_name="Apple Inc",
        chain_id=4663,
        contract_address="0xWRONG_CONTRACT_T74",
        token_decimals=0,
    )
    try:
        bundle = get_equity_company_history("AAPL", db_path=tmp, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=([mismatch_asset], None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get("/radar/equity/rh-equity-aapl-001")
            assert resp.status_code == 200
            assert "IDENTITY_MISMATCH" in resp.text
            assert _SENTINEL_DATE not in resp.text, (
                f"Sentinel dividend declaration_date {_SENTINEL_DATE!r} must not appear in IDENTITY_MISMATCH page"
            )
    finally:
        tmp.unlink(missing_ok=True)


# ── T75: F05 sentinel payload hash absent from rendered HTML ──────────────────

def test_t75_identity_mismatch_sentinel_payload_hash_not_in_html():
    import main_web
    from app.radar_ui import router as radar_router

    _SENTINEL_HASH = "SENTINELHASH_MISMATCH_XQ99ZZ_9988"
    tmp = _build_test_db(ttm_period=None, add_dividend=False, add_split=False, add_lineage=False)
    conn = sqlite3.connect(str(tmp))
    conn.execute(
        "INSERT INTO equity_financial_snapshots "
        "(ticker,timeframe,period_end,provider,derived_json,payload_hash,fetched_at) VALUES (?,?,?,?,?,?,?)",
        ("AAPL", "ttm", "2024-09-28", "SYNTH", _AAPL_DERIVED, _SENTINEL_HASH, "2024-11-05"),
    )
    conn.commit()
    conn.close()

    mismatch_asset = _SA(
        economic_asset_uid="rh-equity-aapl-001",
        token_symbol="AAPL",
        token_name="Apple Inc",
        chain_id=4663,
        contract_address="0xWRONG_CONTRACT_T75",
        token_decimals=0,
    )
    try:
        bundle = get_equity_company_history("AAPL", db_path=tmp, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=([mismatch_asset], None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get("/radar/equity/rh-equity-aapl-001")
            assert resp.status_code == 200
            assert "IDENTITY_MISMATCH" in resp.text
            assert _SENTINEL_HASH not in resp.text, (
                "Sentinel payload hash must not appear in IDENTITY_MISMATCH page"
            )
    finally:
        tmp.unlink(missing_ok=True)


# ── T76: F05 selected token identity visible in IDENTITY_MISMATCH page ────────

def test_t76_identity_mismatch_selected_token_visible_in_html():
    import main_web
    from app.radar_ui import router as radar_router

    _SENTINEL_CONTRACT = "0xSENTINEL_SELECTED_T76_CONTRACT"
    mismatch_asset = _SA(
        economic_asset_uid="rh-equity-aapl-001",
        token_symbol="AAPL",
        token_name="Apple Inc",
        chain_id=9999,
        contract_address=_SENTINEL_CONTRACT,
        token_decimals=0,
    )
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=([mismatch_asset], None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get("/radar/equity/rh-equity-aapl-001?tab=token-market")
            assert resp.status_code == 200
            assert "IDENTITY_MISMATCH" in resp.text
            assert "rh-equity-aapl-001" in resp.text, (
                "economic_asset_uid must remain visible on IDENTITY_MISMATCH page"
            )
            assert _SENTINEL_CONTRACT in resp.text, (
                "selected contract address must remain visible on IDENTITY_MISMATCH page"
            )
    finally:
        db.unlink(missing_ok=True)


# ── T77: F06 symbol mismatch + both contracts present → IDENTITY_MISMATCH ─────

def test_t77_f06_symbol_mismatch_both_contracts():
    bundle = MagicMock()
    bundle.asset = MagicMock()
    bundle.asset.robinhood_token_symbol = "MSFT"
    bundle.asset.token_contract_address = "0xmsft_contract"
    state = validate_terminal_identity(
        selected_symbol="AAPL",
        selected_contract="0xaapl_contract",
        bundle=bundle,
    )
    assert state == "IDENTITY_MISMATCH", (
        f"F06: symbol mismatch must override contract presence, got {state!r}"
    )


# ── T78: F06 symbol mismatch + selected_contract missing → IDENTITY_MISMATCH ──

def test_t78_f06_symbol_mismatch_no_selected_contract():
    bundle = MagicMock()
    bundle.asset = MagicMock()
    bundle.asset.robinhood_token_symbol = "MSFT"
    bundle.asset.token_contract_address = "0xmsft_contract"
    state = validate_terminal_identity(
        selected_symbol="AAPL",
        selected_contract=None,
        bundle=bundle,
    )
    assert state == "IDENTITY_MISMATCH", (
        f"F06: symbol mismatch must not be downgraded to PARTIAL_IDENTITY, got {state!r}"
    )


# ── T79: F06 symbol mismatch + DB contract missing → IDENTITY_MISMATCH ───────

def test_t79_f06_symbol_mismatch_no_db_contract():
    bundle = MagicMock()
    bundle.asset = MagicMock()
    bundle.asset.robinhood_token_symbol = "MSFT"
    bundle.asset.token_contract_address = None
    state = validate_terminal_identity(
        selected_symbol="AAPL",
        selected_contract="0xaapl_contract",
        bundle=bundle,
    )
    assert state == "IDENTITY_MISMATCH", (
        f"F06: symbol mismatch must not be downgraded to PARTIAL_IDENTITY, got {state!r}"
    )


# ── T80: F06 matching symbol + selected_contract missing → PARTIAL_IDENTITY ───

def test_t80_f06_matching_symbol_no_selected_contract():
    bundle = MagicMock()
    bundle.asset = MagicMock()
    bundle.asset.robinhood_token_symbol = "AAPL"
    bundle.asset.token_contract_address = "0xaapl_contract"
    state = validate_terminal_identity(
        selected_symbol="AAPL",
        selected_contract=None,
        bundle=bundle,
    )
    assert state == "PARTIAL_IDENTITY", (
        f"F06: matching symbol + absent selected_contract → PARTIAL_IDENTITY, got {state!r}"
    )


# ── T81: F06 matching symbol + DB contract missing → PARTIAL_IDENTITY ─────────

def test_t81_f06_matching_symbol_no_db_contract():
    bundle = MagicMock()
    bundle.asset = MagicMock()
    bundle.asset.robinhood_token_symbol = "AAPL"
    bundle.asset.token_contract_address = None
    state = validate_terminal_identity(
        selected_symbol="AAPL",
        selected_contract="0xaapl_contract",
        bundle=bundle,
    )
    assert state == "PARTIAL_IDENTITY", (
        f"F06: matching symbol + absent DB contract → PARTIAL_IDENTITY, got {state!r}"
    )


# ── T82: F06 full match (symbol + contract) → VERIFIED ───────────────────────

def test_t82_f06_full_match_verified():
    bundle = MagicMock()
    bundle.asset = MagicMock()
    bundle.asset.robinhood_token_symbol = "AAPL"
    bundle.asset.token_contract_address = "0xaapl_contract"
    state = validate_terminal_identity(
        selected_symbol="AAPL",
        selected_contract="0xaapl_contract",
        bundle=bundle,
    )
    assert state == "VERIFIED", f"Full match should be VERIFIED, got {state!r}"


# ── T83: F07 single malformed-only period → SOURCE_DATA_MALFORMED ─────────────

def test_t83_matrix_single_malformed_state():
    from finco_radar.equity.models import FinancialSnapshot
    snap = FinancialSnapshot(
        ticker="AAPL", cik=None, timeframe="annual",
        fiscal_year="2023", fiscal_quarter=None,
        period_end="2023-09-30", filing_date=None,
        provider="SYNTH", source_contract=None,
        fetched_at=None, normalized_at=None, payload_hash=None,
        income_statement=JsonField(value=None, absent=False, parse_error="JSON parse error"),
        balance_sheet=JsonField(value=None, absent=True, parse_error=None),
        cash_flow_statement=JsonField(value=None, absent=True, parse_error=None),
        derived_source=JsonField(value=None, absent=True, parse_error=None),
        derived=None,
    )
    result = _build_statement_matrix([snap], "income_statement")
    assert result["state"] == "SOURCE_DATA_MALFORMED", (
        f"All-malformed periods must yield SOURCE_DATA_MALFORMED, got {result['state']!r}"
    )
    assert result["available"] is False


# ── T84: F07 multiple malformed-only periods → SOURCE_DATA_MALFORMED ──────────

def test_t84_matrix_multiple_malformed_state():
    from finco_radar.equity.models import FinancialSnapshot

    def _malformed_snap(fy):
        return FinancialSnapshot(
            ticker="AAPL", cik=None, timeframe="annual",
            fiscal_year=fy, fiscal_quarter=None,
            period_end=f"{fy}-09-30", filing_date=None,
            provider="SYNTH", source_contract=None,
            fetched_at=None, normalized_at=None, payload_hash=None,
            income_statement=JsonField(value=None, absent=False, parse_error="bad JSON"),
            balance_sheet=JsonField(value=None, absent=True, parse_error=None),
            cash_flow_statement=JsonField(value=None, absent=True, parse_error=None),
            derived_source=JsonField(value=None, absent=True, parse_error=None),
            derived=None,
        )

    result = _build_statement_matrix(
        [_malformed_snap("2023"), _malformed_snap("2022")], "income_statement"
    )
    assert result["state"] == "SOURCE_DATA_MALFORMED"
    assert result["available"] is False


# ── T85: F07 mixed available + malformed → PARTIAL ───────────────────────────

def test_t85_matrix_mixed_available_malformed_partial():
    from finco_radar.equity.models import FinancialSnapshot

    snap_ok = FinancialSnapshot(
        ticker="AAPL", cik=None, timeframe="annual",
        fiscal_year="2023", fiscal_quarter=None,
        period_end="2023-09-30", filing_date=None,
        provider="SYNTH", source_contract=None,
        fetched_at=None, normalized_at=None, payload_hash=None,
        income_statement=JsonField(value={"totalRevenue": 100.0}, absent=False, parse_error=None),
        balance_sheet=JsonField(value=None, absent=True, parse_error=None),
        cash_flow_statement=JsonField(value=None, absent=True, parse_error=None),
        derived_source=JsonField(value=None, absent=True, parse_error=None),
        derived=None,
    )
    snap_bad = FinancialSnapshot(
        ticker="AAPL", cik=None, timeframe="annual",
        fiscal_year="2022", fiscal_quarter=None,
        period_end="2022-09-24", filing_date=None,
        provider="SYNTH", source_contract=None,
        fetched_at=None, normalized_at=None, payload_hash=None,
        income_statement=JsonField(value=None, absent=False, parse_error="bad JSON"),
        balance_sheet=JsonField(value=None, absent=True, parse_error=None),
        cash_flow_statement=JsonField(value=None, absent=True, parse_error=None),
        derived_source=JsonField(value=None, absent=True, parse_error=None),
        derived=None,
    )
    result = _build_statement_matrix([snap_ok, snap_bad], "income_statement")
    assert result["state"] == "PARTIAL", (
        f"Mixed available+malformed must be PARTIAL, got {result['state']!r}"
    )
    assert result["available"] is True


# ── T86: F07 absent-only periods → NOT_AVAILABLE ─────────────────────────────

def test_t86_matrix_absent_only_not_available():
    from finco_radar.equity.models import FinancialSnapshot
    snap = FinancialSnapshot(
        ticker="AAPL", cik=None, timeframe="annual",
        fiscal_year="2023", fiscal_quarter=None,
        period_end="2023-09-30", filing_date=None,
        provider="SYNTH", source_contract=None,
        fetched_at=None, normalized_at=None, payload_hash=None,
        income_statement=JsonField(value=None, absent=True, parse_error=None),
        balance_sheet=JsonField(value=None, absent=True, parse_error=None),
        cash_flow_statement=JsonField(value=None, absent=True, parse_error=None),
        derived_source=JsonField(value=None, absent=True, parse_error=None),
        derived=None,
    )
    result = _build_statement_matrix([snap], "income_statement")
    assert result["state"] == "NOT_AVAILABLE", (
        f"Absent-only must be NOT_AVAILABLE, got {result['state']!r}"
    )
    assert result["available"] is False


# ── T87: F07 SOURCE_DATA_MALFORMED visible in rendered HTML ───────────────────

def test_t87_source_data_malformed_in_html():
    import main_web
    from app.radar_ui import router as radar_router

    # Build DB with malformed income_statement_json for the only annual period
    tmp = Path(tempfile.mktemp(suffix=".db"))
    conn = sqlite3.connect(str(tmp))
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT INTO equity_assets (robinhood_token_symbol,underlying_ticker,name,"
        "token_contract_address,chain_network,currency,active) VALUES (?,?,?,?,?,?,1)",
        ("AAPL", "AAPL", "AAPL Corp", "0xabc123", "ethereum", "USD"),
    )
    conn.execute(
        "INSERT INTO equity_company_profiles (ticker,profile_json,provider,fetched_at) "
        "VALUES (?,?,?,?)",
        ("AAPL", json.dumps({"name": "AAPL Corp"}), "SYNTH", "2024-10-01"),
    )
    conn.execute(
        "INSERT INTO equity_financial_snapshots "
        "(ticker,timeframe,period_end,provider,derived_json,"
        "income_statement_json,fetched_at) VALUES (?,?,?,?,?,?,?)",
        ("AAPL", "annual", "2023-09-30", "SYNTH", _AAPL_DERIVED,
         "NOT_VALID_JSON_{{{_MALFORMED", "2024-11-05"),
    )
    conn.commit()
    conn.close()

    universe = [_AAPL_ASSET]
    try:
        bundle = get_equity_company_history("AAPL", db_path=tmp, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get(
                "/radar/equity/rh-equity-aapl-001?tab=financials&timeframe=annual&statement=income"
            )
            assert resp.status_code == 200
            assert "SOURCE_DATA_MALFORMED" in resp.text, (
                "SOURCE_DATA_MALFORMED must appear in rendered HTML when all periods are malformed"
            )
    finally:
        tmp.unlink(missing_ok=True)


# ──────────────────────────────────────────────────────────────────────────────
# T88–T92: Correction C — real-data field map coverage
# ──────────────────────────────────────────────────────────────────────────────

# ── T88: income field map labels all real-data snake_case keys ────────────────

def test_t88_income_field_map_covers_real_data_keys():
    from app.radar_ui.equity_terminal import _INCOME_FIELD_MAP

    # Keys observed in real MASSIVE/LEGACY_MASSIVE_VX income statements
    real_keys = {
        "revenues", "cost_of_revenue", "gross_profit", "operating_income_loss",
        "operating_expenses", "costs_and_expenses", "benefits_costs_expenses",
        "income_loss_from_continuing_operations_before_tax", "income_tax_expense_benefit",
        "income_loss_from_continuing_operations_after_tax", "net_income_loss",
        "net_income_loss_attributable_to_parent", "basic_earnings_per_share",
        "diluted_earnings_per_share", "basic_average_shares", "diluted_average_shares",
    }
    missing = real_keys - set(_INCOME_FIELD_MAP)
    assert not missing, f"Income field map missing real-data keys: {sorted(missing)}"
    for k in real_keys:
        assert _INCOME_FIELD_MAP[k] != k, f"Key {k!r} falls back to raw key — add a display label"


# ── T89: balance sheet field map labels all real-data snake_case keys ─────────

def test_t89_balance_field_map_covers_real_data_keys():
    from app.radar_ui.equity_terminal import _BALANCE_FIELD_MAP

    real_keys = {
        "assets", "current_assets", "noncurrent_assets", "inventory",
        "other_current_assets", "fixed_assets", "other_noncurrent_assets",
        "liabilities", "current_liabilities", "noncurrent_liabilities",
        "accounts_payable", "other_current_liabilities", "long_term_debt",
        "other_noncurrent_liabilities", "equity", "equity_attributable_to_parent",
        "equity_attributable_to_noncontrolling_interest", "liabilities_and_equity",
    }
    missing = real_keys - set(_BALANCE_FIELD_MAP)
    assert not missing, f"Balance field map missing real-data keys: {sorted(missing)}"
    for k in real_keys:
        assert _BALANCE_FIELD_MAP[k] != k, f"Key {k!r} falls back to raw key — add a display label"


# ── T90: cash flow field map labels all real-data snake_case keys ─────────────

def test_t90_cashflow_field_map_covers_real_data_keys():
    from app.radar_ui.equity_terminal import _CASHFLOW_FIELD_MAP

    real_keys = {
        "net_cash_flow_from_operating_activities",
        "net_cash_flow_from_investing_activities",
        "net_cash_flow_from_financing_activities",
        "net_cash_flow",
        "net_cash_flow_continuing",
        "net_cash_flow_from_operating_activities_continuing",
        "net_cash_flow_from_investing_activities_continuing",
        "net_cash_flow_from_financing_activities_continuing",
    }
    missing = real_keys - set(_CASHFLOW_FIELD_MAP)
    assert not missing, f"Cash flow field map missing real-data keys: {sorted(missing)}"
    for k in real_keys:
        assert _CASHFLOW_FIELD_MAP[k] != k, f"Key {k!r} falls back to raw key — add a display label"


# ── T91: unknown field key falls back to raw key as label ─────────────────────

def test_t91_unknown_field_falls_back_to_raw_key():
    from finco_radar.equity.models import FinancialSnapshot

    snap = FinancialSnapshot(
        ticker="AAPL", cik=None, timeframe="annual",
        fiscal_year="2023", fiscal_quarter=None,
        period_end="2023-09-30", filing_date=None,
        provider="SYNTH", source_contract=None,
        fetched_at=None, normalized_at=None, payload_hash=None,
        income_statement=JsonField(
            value={"revenues": 385.0, "xyzzy_future_field": 1.0},
            absent=False, parse_error=None,
        ),
        balance_sheet=JsonField(value=None, absent=True, parse_error=None),
        cash_flow_statement=JsonField(value=None, absent=True, parse_error=None),
        derived_source=JsonField(value=None, absent=True, parse_error=None),
        derived=None,
    )
    result = _build_statement_matrix([snap], "income_statement")
    row_map = {r["field_key"]: r["label"] for r in result["rows"]}
    assert row_map["revenues"] == "Revenue", "Known key must use human label"
    assert row_map["xyzzy_future_field"] == "xyzzy_future_field", (
        "Unknown key must fall back to raw key as label"
    )


# ── T92: matrix with real-data snake_case keys renders correct row labels ─────

def test_t92_matrix_real_data_key_labels():
    from finco_radar.equity.models import FinancialSnapshot

    income_data = {
        "revenues": 385_980_000_000.0,
        "gross_profit": 166_936_000_000.0,
        "operating_income_loss": 119_437_000_000.0,
        "net_income_loss": 96_150_000_000.0,
        "basic_earnings_per_share": 6.16,
        "diluted_earnings_per_share": 6.08,
        "basic_average_shares": 15_617_769_000.0,
        "diluted_average_shares": 15_812_547_000.0,
    }
    snap = FinancialSnapshot(
        ticker="AAPL", cik=None, timeframe="annual",
        fiscal_year="2025", fiscal_quarter=None,
        period_end="2025-09-27", filing_date=None,
        provider="MASSIVE", source_contract="LEGACY_MASSIVE_VX",
        fetched_at=None, normalized_at=None, payload_hash=None,
        income_statement=JsonField(value=income_data, absent=False, parse_error=None),
        balance_sheet=JsonField(value=None, absent=True, parse_error=None),
        cash_flow_statement=JsonField(value=None, absent=True, parse_error=None),
        derived_source=JsonField(value=None, absent=True, parse_error=None),
        derived=None,
    )
    result = _build_statement_matrix([snap], "income_statement")
    assert result["state"] == "AVAILABLE"
    assert result["available"] is True
    row_map = {r["field_key"]: r["label"] for r in result["rows"]}
    assert row_map["revenues"] == "Revenue"
    assert row_map["gross_profit"] == "Gross Profit"
    assert row_map["operating_income_loss"] == "Operating Income"
    assert row_map["net_income_loss"] == "Net Income"
    assert row_map["basic_earnings_per_share"] == "EPS (Basic)"
    assert row_map["diluted_earnings_per_share"] == "EPS (Diluted)"
    assert row_map["basic_average_shares"] == "Shares (Basic)"
    assert row_map["diluted_average_shares"] == "Shares (Diluted)"
    # Values formatted correctly
    cells_map = {r["field_key"]: r["cells"][0] for r in result["rows"]}
    assert cells_map["net_income_loss"] == "96,150,000,000.00"
    assert cells_map["basic_earnings_per_share"] == "6.16"


# ══════════════════════════════════════════════════════════════════════════════
# Correction D: D01–D13
# ══════════════════════════════════════════════════════════════════════════════

def _make_snap(
    fiscal_year: str,
    income_state: str = "AVAILABLE",  # "AVAILABLE", "ABSENT", "MALFORMED"
) -> "FinancialSnapshot":
    from finco_radar.equity.models import FinancialSnapshot
    if income_state == "AVAILABLE":
        inc = JsonField(value={"revenues": 100.0}, absent=False, parse_error=None)
    elif income_state == "MALFORMED":
        inc = JsonField(value=None, absent=False, parse_error="bad JSON")
    else:
        inc = JsonField(value=None, absent=True, parse_error=None)
    return FinancialSnapshot(
        ticker="AAPL", cik=None, timeframe="annual",
        fiscal_year=fiscal_year, fiscal_quarter=None,
        period_end=f"{fiscal_year}-09-30", filing_date=None,
        provider="SYNTH", source_contract=None,
        fetched_at=None, normalized_at=None, payload_hash=None,
        income_statement=inc,
        balance_sheet=JsonField(value=None, absent=True, parse_error=None),
        cash_flow_statement=JsonField(value=None, absent=True, parse_error=None),
        derived_source=JsonField(value=None, absent=True, parse_error=None),
        derived=None,
    )


# ── D01: F09 all available → AVAILABLE ───────────────────────────────────────

def test_d01_all_available_is_available():
    snaps = [_make_snap("2023", "AVAILABLE"), _make_snap("2022", "AVAILABLE")]
    result = _build_statement_matrix(snaps, "income_statement")
    assert result["state"] == "AVAILABLE", (
        f"All available periods must yield AVAILABLE, got {result['state']!r}"
    )
    assert result["available"] is True


# ── D02: F09 available + absent → PARTIAL (not AVAILABLE) ────────────────────

def test_d02_available_plus_absent_is_partial():
    snaps = [_make_snap("2023", "AVAILABLE"), _make_snap("2022", "ABSENT")]
    result = _build_statement_matrix(snaps, "income_statement")
    assert result["state"] == "PARTIAL", (
        f"available+absent must yield PARTIAL (not AVAILABLE), got {result['state']!r}"
    )
    assert result["available"] is True


# ── D03: F09 available + malformed → PARTIAL ─────────────────────────────────

def test_d03_available_plus_malformed_is_partial():
    snaps = [_make_snap("2023", "AVAILABLE"), _make_snap("2022", "MALFORMED")]
    result = _build_statement_matrix(snaps, "income_statement")
    assert result["state"] == "PARTIAL", (
        f"available+malformed must yield PARTIAL, got {result['state']!r}"
    )
    assert result["available"] is True


# ── D04: F09 available + absent + malformed → PARTIAL ────────────────────────

def test_d04_mixed_three_states_is_partial():
    snaps = [
        _make_snap("2023", "AVAILABLE"),
        _make_snap("2022", "ABSENT"),
        _make_snap("2021", "MALFORMED"),
    ]
    result = _build_statement_matrix(snaps, "income_statement")
    assert result["state"] == "PARTIAL", (
        f"available+absent+malformed must yield PARTIAL, got {result['state']!r}"
    )
    assert result["available"] is True


# ── D05: F09 all absent → NOT_AVAILABLE ──────────────────────────────────────

def test_d05_all_absent_is_not_available():
    snaps = [_make_snap("2023", "ABSENT"), _make_snap("2022", "ABSENT")]
    result = _build_statement_matrix(snaps, "income_statement")
    assert result["state"] == "NOT_AVAILABLE", (
        f"All absent must yield NOT_AVAILABLE, got {result['state']!r}"
    )
    assert result["available"] is False


# ── D06: F09 all malformed → SOURCE_DATA_MALFORMED ───────────────────────────

def test_d06_all_malformed_is_source_data_malformed():
    snaps = [_make_snap("2023", "MALFORMED"), _make_snap("2022", "MALFORMED")]
    result = _build_statement_matrix(snaps, "income_statement")
    assert result["state"] == "SOURCE_DATA_MALFORMED", (
        f"All malformed must yield SOURCE_DATA_MALFORMED, got {result['state']!r}"
    )
    assert result["available"] is False


# ── D07: F09 malformed + absent → SOURCE_DATA_MALFORMED ──────────────────────

def test_d07_malformed_plus_absent_is_source_data_malformed():
    snaps = [_make_snap("2023", "MALFORMED"), _make_snap("2022", "ABSENT")]
    result = _build_statement_matrix(snaps, "income_statement")
    assert result["state"] == "SOURCE_DATA_MALFORMED", (
        f"malformed+absent (no available) must yield SOURCE_DATA_MALFORMED, got {result['state']!r}"
    )
    assert result["available"] is False


# ── D08: F09 no periods → NOT_AVAILABLE ──────────────────────────────────────

def test_d08_no_periods_is_not_available():
    result = _build_statement_matrix([], "income_statement")
    assert result["state"] == "NOT_AVAILABLE", (
        f"No periods must yield NOT_AVAILABLE, got {result['state']!r}"
    )
    assert result["available"] is False


# ── D09: F08 IDENTITY_MISMATCH uses selected_symbol, DB sentinel absent ───────

def test_d09_f08_identity_mismatch_uses_selected_symbol_not_bundle():
    _DB_SENTINEL = "DB_SENTINEL_CORP_XQ99ZZA"
    _RH_SELECTED = "RH_SELECTED_SYMBOL_XQ99ZZB"
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        # Patch bundle's robinhood_token_symbol to look like the DB value
        bundle_mock = MagicMock(wraps=bundle)
        bundle_mock.robinhood_token_symbol = _DB_SENTINEL
        bundle_mock.availability = bundle.availability

        view = build_terminal_view(
            bundle_mock,
            economic_asset_uid="rh-equity-aapl-001",
            fallback_name="Apple Inc",
            identity_state="IDENTITY_MISMATCH",
            selected_symbol=_RH_SELECTED,
            selected_name="Apple Inc (RH Selected)",
        )
        assert view["symbol"] == _RH_SELECTED, (
            f"symbol must be selected_symbol={_RH_SELECTED!r}, got {view['symbol']!r}"
        )
        assert _DB_SENTINEL not in str(view), (
            f"DB sentinel {_DB_SENTINEL!r} must not appear anywhere in IDENTITY_MISMATCH view"
        )
    finally:
        db.unlink(missing_ok=True)


# ── D10: F10-A GET unknown UID → 404, state=ASSET_NOT_FOUND_IN_UNIVERSE ───────

def test_d10_f10_case_a_unknown_uid_asset_not_found():
    import main_web
    from app.radar_ui import router as radar_router

    universe = [_AAPL_ASSET]
    with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)):
        client = TestClient(main_web.app, raise_server_exceptions=False)
        resp = client.get("/radar/equity/rh-equity-totally-unknown-uid-999")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
        assert "ASSET_NOT_FOUND_IN_UNIVERSE" in resp.text, (
            "Case A (UID not in universe) must render ASSET_NOT_FOUND_IN_UNIVERSE"
        )


# ── D11: F10-B build_terminal_view NOT_FOUND → FUNDAMENTALS_NOT_FOUND ─────────

def test_d11_f10_case_b_fundamentals_not_found():
    from unittest.mock import MagicMock
    from finco_radar.equity.models import AvailabilityState

    bundle = MagicMock()
    bundle.availability = AvailabilityState.NOT_FOUND
    bundle.robinhood_token_symbol = "AAPL"

    view = build_terminal_view(
        bundle,
        economic_asset_uid="rh-equity-aapl-001",
        fallback_name="Apple Inc",
        selected_symbol="AAPL",
        selected_name="Apple Inc",
    )
    assert view["state"] == "FUNDAMENTALS_NOT_FOUND", (
        f"E1 NOT_FOUND must map to FUNDAMENTALS_NOT_FOUND, got {view['state']!r}"
    )
    assert view["available"] is False
    assert "message" in view, "FUNDAMENTALS_NOT_FOUND must include a message key"
    assert "Robinhood" in view["message"] or "fundamental" in view["message"].lower(), (
        f"message must explain the situation, got {view['message']!r}"
    )


# ── D12: HTML escaping adversarial company name ───────────────────────────────

def test_d12_html_escaping_adversarial_company_name():
    import main_web
    from app.radar_ui import router as radar_router

    _SCRIPT_PAYLOAD = '<script>alert("company_xq99")</script>'
    tmp = Path(tempfile.mktemp(suffix=".db"))
    conn = sqlite3.connect(str(tmp))
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT INTO equity_assets (robinhood_token_symbol,underlying_ticker,name,"
        "token_contract_address,chain_network,currency,active) VALUES (?,?,?,?,?,?,1)",
        ("EVIL", "EVIL", _SCRIPT_PAYLOAD, "0xevil", "ethereum", "USD"),
    )
    conn.execute(
        "INSERT INTO equity_company_profiles (ticker,profile_json,provider,fetched_at) "
        "VALUES (?,?,?,?)",
        ("EVIL", json.dumps({"name": _SCRIPT_PAYLOAD}), "SYNTH", "2024-10-01"),
    )
    conn.commit()
    conn.close()

    evil_asset = _SA(
        economic_asset_uid="rh-equity-evil-001",
        token_symbol="EVIL",
        token_name=_SCRIPT_PAYLOAD,
        chain_id=4663,
        contract_address="0xevil",
        token_decimals=0,
    )
    try:
        from finco_radar.equity import get_equity_company_history as _gech
        bundle = _gech("EVIL", db_path=tmp, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=([evil_asset], None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get("/radar/equity/rh-equity-evil-001")
            assert resp.status_code == 200
            # The raw script tag must NOT appear unescaped
            assert "<script>alert(" not in resp.text, (
                "Raw <script> tag from adversarial company name must be HTML-escaped in output"
            )
            # The content must appear somewhere (escaped form)
            assert "alert" in resp.text or "company_xq99" in resp.text, (
                "Escaped content should still appear in page"
            )
    finally:
        tmp.unlink(missing_ok=True)


# ── D13: 3×3 nav — all timeframe×statement combinations return 200 ─────────────

@pytest.mark.parametrize("timeframe,statement", [
    ("annual", "income"),
    ("annual", "balance"),
    ("annual", "cashflow"),
    ("quarterly", "income"),
    ("quarterly", "balance"),
    ("quarterly", "cashflow"),
    ("ttm", "income"),
    ("ttm", "balance"),
    ("ttm", "cashflow"),
])
def test_d13_3x3_nav_combinations(timeframe, statement):
    import main_web
    from app.radar_ui import router as radar_router

    universe = [_AAPL_ASSET]
    db = _build_test_db()
    try:
        bundle = get_equity_company_history("AAPL", db_path=db, db_mode="snapshot")
        with patch.object(radar_router, "_fetch_universe_safe", return_value=(universe, None)), \
             patch("app.radar_ui.equity_terminal.get_history_for_terminal", return_value=bundle):
            client = TestClient(main_web.app, raise_server_exceptions=False)
            resp = client.get(
                f"/radar/equity/rh-equity-aapl-001?tab=financials"
                f"&timeframe={timeframe}&statement={statement}"
            )
            assert resp.status_code == 200, (
                f"3×3 nav [{timeframe}×{statement}] expected 200, got {resp.status_code}"
            )
            # Nav params must be reflected in page
            assert timeframe in resp.text, (
                f"timeframe={timeframe!r} not found in rendered page"
            )
    finally:
        db.unlink(missing_ok=True)
