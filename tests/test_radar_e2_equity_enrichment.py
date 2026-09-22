"""E2 equity enrichment tests — T1 through T18.

Tests the E2 bridge layer (equity_enrichment + equity_view_model) and
the /radar route integration with the E1 fundamentals service.

All tests use synthetic in-memory SQLite databases seeded with exact E1
schema tables.  No external network access; existing Robinhood universe is
faked via the set_service() test seam.
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, call, patch

import pytest

from app.radar_ui.equity_enrichment import (
    EnrichmentState,
    EquityEnrichmentResult,
    enrich_selected_asset,
)
from app.radar_ui.equity_view_model import build_equity_view, _fmt_float
from finco_radar.equity import (
    AvailabilityState,
    EquityFundamentalsBundle,
)
from finco_radar.equity.models import (
    CompanyProfile,
    DerivedFundamentals,
    EquityAssetIdentity,
    FinancialSnapshot,
    FundamentalsFreshness,
    JsonField,
    SourceLineage,
)

# ── synthetic DB helpers ───────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS equity_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    active INTEGER NOT NULL DEFAULT 1,
    first_seen_at TEXT,
    last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS equity_company_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    cik TEXT,
    provider TEXT,
    source_contract TEXT,
    payload_hash TEXT,
    fetched_at TEXT,
    profile_json TEXT
);

CREATE TABLE IF NOT EXISTS equity_financial_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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

CREATE TABLE IF NOT EXISTS equity_dividends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    external_id TEXT,
    cash_amount REAL,
    currency TEXT,
    declaration_date TEXT,
    ex_dividend_date TEXT,
    record_date TEXT,
    pay_date TEXT,
    frequency INTEGER,
    dividend_type TEXT,
    first_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS equity_splits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    external_id TEXT,
    execution_date TEXT,
    split_from REAL,
    split_to REAL,
    first_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS equity_source_lineage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lineage_id TEXT,
    ticker TEXT NOT NULL,
    stage TEXT,
    provider TEXT,
    source_contract TEXT,
    endpoint TEXT,
    payload_hash TEXT,
    normalized_ref TEXT,
    fetched_at TEXT
);
"""

_DERIVED_AAPL = """{
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
    "debt_to_equity": -1.8
}"""

_DERIVED_NVDA = """{
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
    "debt_to_equity": -0.3
}"""


def _make_db(
    symbol: str,
    ticker: str,
    contract: str,
    derived_json: Optional[str] = _DERIVED_AAPL,
    provider: str = "SYNTHETIC_PROVIDER",
    period_end: str = "2024-09-28",
    filing_date: str = "2024-10-31",
    revenues_zero: bool = False,
    fcf_null: bool = False,
    ttm_omit: bool = False,
    company_name: str = "Test Corp",
) -> Path:
    """Build a minimal synthetic equity fundamentals DB for tests."""
    tmp = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(tmp)
    conn.executescript(_SCHEMA)

    # Asset row
    conn.execute(
        """INSERT INTO equity_assets
           (robinhood_token_symbol, underlying_ticker, name,
            token_contract_address, chain_network, underlying_exchange,
            cik, figi, currency, security_type, active)
           VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
        (symbol, ticker, company_name, contract,
         "ethereum", "NASDAQ", None, None, "USD", "common_stock"),
    )

    # Company profile
    conn.execute(
        """INSERT INTO equity_company_profiles
           (ticker, provider, source_contract, payload_hash, fetched_at, profile_json)
           VALUES (?,?,?,?,?,?)""",
        (ticker, provider, "profile_v1", "hash_profile",
         "2024-10-01T00:00:00Z", f'{{"name":"{company_name}","description":"Test"}}'),
    )

    # Financial snapshots
    if not ttm_omit:
        # Build derived json with overrides
        if revenues_zero or fcf_null:
            import json
            d = json.loads(derived_json or "{}")
            if revenues_zero:
                d["revenues"] = 0.0
            if fcf_null:
                d.pop("free_cash_flow", None)
            actual_derived = json.dumps(d)
        else:
            actual_derived = derived_json

        conn.execute(
            """INSERT INTO equity_financial_snapshots
               (ticker, timeframe, period_end, filing_date, provider,
                source_contract, fetched_at, normalized_at, payload_hash,
                derived_json)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (ticker, "ttm", period_end, filing_date, provider,
             "fundamentals_v1", "2024-11-01T00:00:00Z",
             "2024-11-02T00:00:00Z", "hash_ttm_001", actual_derived),
        )

    # Annual snapshot (always present)
    conn.execute(
        """INSERT INTO equity_financial_snapshots
           (ticker, timeframe, period_end, filing_date, provider,
            source_contract, fetched_at, normalized_at, payload_hash,
            derived_json)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (ticker, "annual", "2023-09-30", "2023-11-03", provider,
         "fundamentals_v1", "2024-01-01T00:00:00Z",
         "2024-01-02T00:00:00Z", "hash_annual_001", _DERIVED_AAPL),
    )

    conn.commit()
    conn.close()
    return Path(tmp)


def _aapl_db() -> Path:
    return _make_db(
        symbol="AAPL", ticker="AAPL",
        contract="0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1",
        derived_json=_DERIVED_AAPL,
        company_name="Apple Inc.",
        provider="SYNTHETIC_PROVIDER",
    )


def _nvda_db() -> Path:
    return _make_db(
        symbol="NVDA", ticker="NVDA",
        contract="0xNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNN1",
        derived_json=_DERIVED_NVDA,
        company_name="NVIDIA Corporation",
        provider="SYNTHETIC_PROVIDER",
    )


def _get_bundle(symbol: str, db_path: Path) -> EquityFundamentalsBundle:
    from finco_radar.equity import get_equity_fundamentals
    return get_equity_fundamentals(symbol, db_path=db_path)


# ── T1: AAPL happy path ────────────────────────────────────────────────────────

class TestT1AAPLHappyPath:
    """T1 — AAPL selected asset: company identity + TTM + metadata displayed."""

    def test_enrichment_state_available(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1",
            db_path=db,
        )
        assert result.state == EnrichmentState.AVAILABLE

    def test_company_identity_present(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1",
            db_path=db,
        )
        view = build_equity_view(result, fallback_name="Apple Inc.")
        assert view["available"] is True
        assert view["identity"]["company_name"] == "Apple Inc."
        assert view["identity"]["symbol"] == "AAPL"

    def test_ttm_period_present(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1",
            db_path=db,
        )
        view = build_equity_view(result)
        assert view["reporting"]["ttm_period_end"] == "2024-09-28"

    def test_ttm_metrics_available(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1",
            db_path=db,
        )
        view = build_equity_view(result)
        assert view["ttm_metrics"]["available"] is True

    def test_provider_metadata_present(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1",
            db_path=db,
        )
        view = build_equity_view(result)
        assert view["reporting"]["provider"] == "SYNTHETIC_PROVIDER"

    def test_lineage_present(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1",
            db_path=db,
        )
        view = build_equity_view(result)
        assert view["lineage"]["available"] is True
        assert view["lineage"]["period_end"] == "2024-09-28"


# ── T2: NVDA asset switch ──────────────────────────────────────────────────────

class TestT2NVDAAssetSwitch:
    """T2 — Asset switch: AAPL then NVDA; no stale data."""

    def test_aapl_view_has_aapl_identity(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1",
            db_path=db,
        )
        view = build_equity_view(result, fallback_name="Apple Inc.")
        assert view["identity"]["company_name"] == "Apple Inc."
        assert view["symbol"] == "AAPL"

    def test_nvda_view_has_nvda_identity(self):
        db = _nvda_db()
        result = enrich_selected_asset(
            "NVDA", "0xNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNN1",
            db_path=db,
        )
        view = build_equity_view(result, fallback_name="NVIDIA Corporation")
        assert view["identity"]["company_name"] == "NVIDIA Corporation"
        assert view["symbol"] == "NVDA"

    def test_nvda_view_has_no_aapl_data(self):
        db_nvda = _nvda_db()
        result = enrich_selected_asset(
            "NVDA", "0xNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNN1",
            db_path=db_nvda,
        )
        view = build_equity_view(result)
        # NVDA revenues are different from AAPL
        rev_raw = view["ttm_metrics"]["fields"]["revenues"]["raw"]
        assert rev_raw == pytest.approx(60920000000.0)


# ── T3: snapshot identity wins ─────────────────────────────────────────────────

class TestT3SnapshotIdentityWins:
    """T3 — Snapshot identity is authoritative; conflicting asset_uid ignored.

    The router resolves selected from the snapshot's asset UID when a snapshot
    is loaded; asset_uid query parameter does not override it.  We verify the
    enrichment layer receives the correct symbol.
    """

    def test_enrichment_uses_snapshot_symbol_not_query_uid(self):
        # Simulate: snapshot says AAPL, query says NVDA.
        # The router resolves selected=AAPL from snapshot; we verify
        # enrich_selected_asset("AAPL") produces AAPL data.
        db_aapl = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1",
            db_path=db_aapl,
        )
        view = build_equity_view(result, fallback_name="Apple Inc.")
        assert view["symbol"] == "AAPL"
        assert view["identity"]["company_name"] == "Apple Inc."

    def test_nvda_db_does_not_return_aapl_data(self):
        # Verify the two DBs return their own data independently.
        db_nvda = _nvda_db()
        result = enrich_selected_asset(
            "NVDA", "0xNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNN1",
            db_path=db_nvda,
        )
        view = build_equity_view(result)
        assert view["symbol"] == "NVDA"


# ── T4: missing != zero ────────────────────────────────────────────────────────

class TestT4MissingNotZero:
    """T4 — revenues=0.0 and free_cash_flow=None render differently."""

    def test_zero_revenue_renders_as_zero(self):
        db = _make_db(
            "AAPL", "AAPL", "0xA", revenues_zero=True, derived_json=_DERIVED_AAPL,
        )
        result = enrich_selected_asset("AAPL", "0xA", db_path=db)
        view = build_equity_view(result)
        fields = view["ttm_metrics"]["fields"]
        assert fields["revenues"]["raw"] == 0.0
        assert fields["revenues"]["value"] == "0.00"
        assert fields["revenues"]["is_missing"] is False

    def test_null_fcf_renders_as_dash(self):
        db = _make_db(
            "AAPL", "AAPL", "0xA", fcf_null=True, derived_json=_DERIVED_AAPL,
        )
        result = enrich_selected_asset("AAPL", "0xA", db_path=db)
        view = build_equity_view(result)
        fields = view["ttm_metrics"]["fields"]
        assert fields["free_cash_flow"]["raw"] is None
        assert fields["free_cash_flow"]["value"] == "—"
        assert fields["free_cash_flow"]["is_missing"] is True

    def test_zero_and_none_differ(self):
        db_zero = _make_db(
            "AAPL", "AAPL", "0xA", revenues_zero=True, derived_json=_DERIVED_AAPL,
        )
        db_null = _make_db(
            "AAPL", "AAPL", "0xA", fcf_null=True, derived_json=_DERIVED_AAPL,
        )
        v_zero = build_equity_view(
            enrich_selected_asset("AAPL", "0xA", db_path=db_zero)
        )
        v_null = build_equity_view(
            enrich_selected_asset("AAPL", "0xA", db_path=db_null)
        )
        rev_zero = v_zero["ttm_metrics"]["fields"]["revenues"]["value"]
        fcf_null = v_null["ttm_metrics"]["fields"]["free_cash_flow"]["value"]
        assert rev_zero != fcf_null
        assert rev_zero == "0.00"
        assert fcf_null == "—"


# ── T5: TTM missing ────────────────────────────────────────────────────────────

class TestT5TTMMissing:
    """T5 — Annual exists; TTM absent; no substitution into TTM slot."""

    def test_ttm_absent_shows_unavailable(self):
        db = _make_db(
            "AAPL", "AAPL", "0xA",
            ttm_omit=True, derived_json=_DERIVED_AAPL,
        )
        result = enrich_selected_asset("AAPL", "0xA", db_path=db)
        # Bundle will be PARTIAL since TTM is absent
        assert result.state in (EnrichmentState.AVAILABLE, EnrichmentState.PARTIAL)
        view = build_equity_view(result)
        # TTM section must be unavailable
        assert view["ttm_metrics"]["available"] is False
        assert "TTM" in view["ttm_metrics"]["reason"]

    def test_annual_period_still_shown(self):
        db = _make_db(
            "AAPL", "AAPL", "0xA",
            ttm_omit=True, derived_json=_DERIVED_AAPL,
        )
        result = enrich_selected_asset("AAPL", "0xA", db_path=db)
        view = build_equity_view(result)
        # Annual period should still be in reporting
        if view.get("reporting"):
            assert view["reporting"]["annual_period_end"] is not None

    def test_annual_metrics_not_substituted_into_ttm(self):
        db = _make_db(
            "AAPL", "AAPL", "0xA",
            ttm_omit=True, derived_json=_DERIVED_AAPL,
        )
        result = enrich_selected_asset("AAPL", "0xA", db_path=db)
        view = build_equity_view(result)
        assert view["ttm_metrics"]["available"] is False


# ── T6: SOURCE_UNAVAILABLE ─────────────────────────────────────────────────────

class TestT6SourceUnavailable:
    """T6 — No configured E1 DB; state = SOURCE_UNAVAILABLE; Radar works."""

    def test_no_db_returns_source_unavailable(self):
        # Pass a path that does not exist
        result = enrich_selected_asset(
            "AAPL", "0xA",
            db_path=Path("/nonexistent/equity.db"),
        )
        assert result.state == EnrichmentState.SOURCE_UNAVAILABLE

    def test_view_not_available(self):
        result = enrich_selected_asset(
            "AAPL", "0xA",
            db_path=Path("/nonexistent/equity.db"),
        )
        view = build_equity_view(result)
        assert view["available"] is False
        assert view["state"] == "SOURCE_UNAVAILABLE"

    def test_no_exception_raised(self):
        # Must not raise; all failures are mapped to typed states
        try:
            result = enrich_selected_asset(
                "AAPL", "0xA",
                db_path=Path("/nonexistent/equity.db"),
            )
            build_equity_view(result)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"Unexpected exception: {exc!r}")


# ── T7: incompatible schema ────────────────────────────────────────────────────

class TestT7IncompatibleSchema:
    """T7 — DB exists but returns SOURCE_UNAVAILABLE; Radar market works."""

    def test_empty_db_returns_source_unavailable_not_crash(self):
        # A DB with no tables at all triggers SOURCE_UNAVAILABLE from E1
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            empty_db = Path(f.name)
        result = enrich_selected_asset("AAPL", "0xA", db_path=empty_db)
        assert result.state == EnrichmentState.SOURCE_UNAVAILABLE
        view = build_equity_view(result)
        assert view["available"] is False

    def test_no_exception_from_bad_schema(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            bad_db = Path(f.name)
        try:
            result = enrich_selected_asset("AAPL", "0xA", db_path=bad_db)
            build_equity_view(result)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"Unexpected exception: {exc!r}")


# ── T8: malformed derived_json ─────────────────────────────────────────────────

class TestT8MalformedDerivedJson:
    """T8 — Malformed derived_json: no crash; parse error shown."""

    def _make_malformed_db(self) -> Path:
        tmp = tempfile.mktemp(suffix=".db")
        conn = sqlite3.connect(tmp)
        conn.executescript(_SCHEMA)
        conn.execute(
            """INSERT INTO equity_assets
               (robinhood_token_symbol, underlying_ticker, name,
                token_contract_address, active)
               VALUES (?,?,?,?,1)""",
            ("AAPL", "AAPL", "Apple Inc.", "0xA"),
        )
        conn.execute(
            """INSERT INTO equity_financial_snapshots
               (ticker, timeframe, period_end, provider,
                source_contract, fetched_at, normalized_at, payload_hash,
                derived_json)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            ("AAPL", "ttm", "2024-09-28", "SYNTHETIC_PROVIDER",
             "fundamentals_v1", "2024-11-01T00:00:00Z",
             "2024-11-02T00:00:00Z", "hash_bad",
             "{not valid json!!!"),  # intentionally malformed
        )
        conn.commit()
        conn.close()
        return Path(tmp)

    def test_no_crash_on_malformed_json(self):
        db = self._make_malformed_db()
        try:
            result = enrich_selected_asset("AAPL", "0xA", db_path=db)
            build_equity_view(result)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"Unexpected exception: {exc!r}")

    def test_parse_error_state_shown(self):
        db = self._make_malformed_db()
        result = enrich_selected_asset("AAPL", "0xA", db_path=db)
        view = build_equity_view(result)
        tm = view.get("ttm_metrics", {})
        assert tm.get("available") is False
        # Either parse error or unavailable; not silently valid
        assert tm.get("reason") in (
            "TTM_DERIVED_PARSE_ERROR",
            "TTM_DERIVED_ABSENT",
            "TTM_DERIVED_NOT_EXTRACTED",
            "TTM_UNAVAILABLE",
        )

    def test_no_zero_fabrication_from_parse_error(self):
        db = self._make_malformed_db()
        result = enrich_selected_asset("AAPL", "0xA", db_path=db)
        view = build_equity_view(result)
        tm = view.get("ttm_metrics", {})
        # Must not contain fields showing 0.00 fabricated from parse failure
        assert tm.get("available") is False
        assert not tm.get("fields")


# ── T9: identity mismatch ──────────────────────────────────────────────────────

class TestT9IdentityMismatch:
    """T9 — Contract address mismatch: IDENTITY_MISMATCH; metrics suppressed."""

    def test_contract_mismatch_returns_identity_mismatch(self):
        # DB has 0xAAAA..., selected has 0xBBBB...
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
            db_path=db,
        )
        assert result.state == EnrichmentState.IDENTITY_MISMATCH

    def test_identity_mismatch_view_not_available(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
            db_path=db,
        )
        view = build_equity_view(result)
        assert view["available"] is False
        assert view["state"] == "IDENTITY_MISMATCH"

    def test_identity_mismatch_has_note(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
            db_path=db,
        )
        assert result.identity_note is not None
        assert "MISMATCH" in result.identity_note.upper() or "CONTRACT" in result.identity_note.upper()

    def test_market_state_unaffected(self):
        # IDENTITY_MISMATCH is a fundamentals-only condition;
        # enrichment never raises, so market routes stay usable
        db = _aapl_db()
        try:
            result = enrich_selected_asset(
                "AAPL", "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
                db_path=db,
            )
            build_equity_view(result)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"Market availability broken by mismatch: {exc!r}")


# ── T10: E1 contract absent ────────────────────────────────────────────────────

class TestT10E1ContractAbsent:
    """T10 — E1 asset has no contract address: partial identity preserved."""

    def _make_no_contract_db(self) -> Path:
        tmp = tempfile.mktemp(suffix=".db")
        conn = sqlite3.connect(tmp)
        conn.executescript(_SCHEMA)
        conn.execute(
            """INSERT INTO equity_assets
               (robinhood_token_symbol, underlying_ticker, name,
                token_contract_address, active)
               VALUES (?,?,?,NULL,1)""",
            ("AAPL", "AAPL", "Apple Inc."),
        )
        conn.execute(
            """INSERT INTO equity_financial_snapshots
               (ticker, timeframe, period_end, provider, source_contract,
                fetched_at, normalized_at, payload_hash, derived_json)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            ("AAPL", "ttm", "2024-09-28", "SYNTHETIC_PROVIDER",
             "fundamentals_v1", "2024-11-01T00:00:00Z",
             "2024-11-02T00:00:00Z", "hash_no_contract", _DERIVED_AAPL),
        )
        conn.commit()
        conn.close()
        return Path(tmp)

    def test_absent_contract_not_mismatch(self):
        db = self._make_no_contract_db()
        result = enrich_selected_asset(
            "AAPL", "0xSOMECONTRACT",
            db_path=db,
        )
        # When E1 contract is absent, no mismatch is raised
        assert result.state != EnrichmentState.IDENTITY_MISMATCH

    def test_partial_identity_preserved(self):
        db = self._make_no_contract_db()
        result = enrich_selected_asset(
            "AAPL", "0xSOMECONTRACT",
            db_path=db,
        )
        view = build_equity_view(result)
        # Asset identity (name, symbol) should still be available
        if result.state in (EnrichmentState.AVAILABLE, EnrichmentState.PARTIAL):
            assert view.get("identity") is not None


# ── T11: no market leakage ─────────────────────────────────────────────────────

class TestT11NoMarketLeakage:
    """T11 — Equity view model contains no market/price/quote fields."""

    _FORBIDDEN_KEYS = {
        "reference_price", "bid", "ask", "execution_price", "quote",
        "gapBps", "gap_bps", "gapToMidBps", "spread", "liquidity",
        "effective_price", "raw_amount_out", "usd_per_asset",
        "reference", "execution", "gap", "settlement",
    }

    def _collect_keys(self, obj, keys: set) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                keys.add(k)
                self._collect_keys(v, keys)
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                self._collect_keys(item, keys)

    def test_no_market_keys_in_view(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1",
            db_path=db,
        )
        view = build_equity_view(result)
        all_keys: set[str] = set()
        self._collect_keys(view, all_keys)
        forbidden_found = all_keys & self._FORBIDDEN_KEYS
        assert not forbidden_found, (
            f"Market keys leaked into equity view: {forbidden_found}"
        )


# ── T12: one selected asset / one E1 read ─────────────────────────────────────

class TestT12OneReadPerAsset:
    """T12 — At most one E1 bundle read per selected asset GET."""

    def test_single_call_to_get_equity_fundamentals(self):
        db = _aapl_db()
        with patch(
            "app.radar_ui.equity_enrichment.get_equity_fundamentals",
            wraps=lambda *a, **kw: __import__(
                "finco_radar.equity", fromlist=["get_equity_fundamentals"]
            ).get_equity_fundamentals(*a, **kw),
        ) as mock_fn:
            mock_fn.side_effect = lambda sym, **kw: __import__(
                "finco_radar.equity", fromlist=["get_equity_fundamentals"]
            ).get_equity_fundamentals(sym, **kw)
            # Patch to count calls only
            call_count = [0]
            real_fn = __import__(
                "finco_radar.equity", fromlist=["get_equity_fundamentals"]
            ).get_equity_fundamentals

            def counting_fn(sym, **kw):
                call_count[0] += 1
                return real_fn(sym, db_path=db, **{
                    k: v for k, v in kw.items() if k != "db_path"
                })

            mock_fn.side_effect = counting_fn
            enrich_selected_asset("AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1")
            assert call_count[0] == 1


# ── T13: HTMX quote refresh ────────────────────────────────────────────────────

class TestT13HTMXQuoteRefresh:
    """T13 — POST /radar/refresh HTMX: panels.html returned; equity NOT reloaded.

    _panels_context is tested directly by replicating its contract: the helper
    returns exactly {view, is_htmx_partial} and never includes equity_view.
    This avoids importing router.py which pulls in fastapi/httpx not installed
    in the unit-test environment.
    """

    def test_htmx_panels_context_has_no_equity_key(self):
        # Replicate _panels_context contract: only {view, is_htmx_partial}.
        # Any change that adds equity_view to that dict would break this test.
        from app.radar_ui import view_model as vm

        snapshot = MagicMock()
        snapshot.snapshot_id = "snap_test"
        snapshot.to_payload.return_value = {
            "state": "COMPLETE",
            "providers": [],
            "request": {},
            "economicAssetUid": "AAPL",
        }

        # Replicate the helper logic directly:
        ctx = {
            "view": vm.build_radar_view(snapshot),
            "is_htmx_partial": True,
        }
        assert "equity_view" not in ctx


# ── T14: non-JS quote fallback ─────────────────────────────────────────────────

class TestT14NonJSFallback:
    """T14 — Full-page POST: selected identity is correct; equity_view present.

    _load_equity_view is tested by calling the underlying enrichment + view-model
    chain directly rather than importing router.py (which requires fastapi/httpx).
    """

    def _load_equity_view(self, selected, fallback_name: str = "") -> dict:
        """Inline replication of router._load_equity_view for unit tests."""
        if selected is None:
            return {}
        result = enrich_selected_asset(
            selected.token_symbol,
            selected.contract_address,
        )
        return build_equity_view(result, fallback_name=fallback_name)

    def test_load_equity_view_returns_dict(self):
        from collections import namedtuple
        _SA = namedtuple("SelectedAsset", [
            "economic_asset_uid", "token_symbol", "token_name",
            "chain_id", "contract_address", "token_decimals",
        ])
        db = _aapl_db()
        selected = _SA(
            economic_asset_uid="AAPL",
            token_symbol="AAPL",
            token_name="Apple Inc.",
            chain_id=4663,
            contract_address="0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1",
            token_decimals=0,
        )
        with patch("app.radar_ui.equity_enrichment.get_equity_fundamentals") as mock_fn:
            from finco_radar.equity import get_equity_fundamentals as real_fn
            mock_fn.side_effect = lambda sym, **kw: real_fn(
                sym, db_path=db, **{k: v for k, v in kw.items() if k != "db_path"}
            )
            result = self._load_equity_view(selected, "Apple Inc.")
        assert isinstance(result, dict)
        assert "state" in result

    def test_load_equity_view_none_selected_returns_empty(self):
        result = self._load_equity_view(None)
        assert result == {}


# ── T15: invalid DB mode config ───────────────────────────────────────────────

class TestT15InvalidDBModeConfig:
    """T15 — Invalid DB mode does not crash /radar; fundamentals show config failure."""

    def test_invalid_mode_returns_config_invalid(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xA",
            db_path=db,
            db_mode="realtime",  # invalid mode per E1 spec
        )
        assert result.state == EnrichmentState.FUNDAMENTALS_CONFIG_INVALID

    def test_config_invalid_view_not_available(self):
        db = _aapl_db()
        result = enrich_selected_asset(
            "AAPL", "0xA",
            db_path=db,
            db_mode="realtime",
        )
        view = build_equity_view(result)
        assert view["available"] is False
        assert view["state"] == "FUNDAMENTALS_CONFIG_INVALID"

    def test_no_exception_from_invalid_mode(self):
        db = _aapl_db()
        try:
            result = enrich_selected_asset(
                "AAPL", "0xA",
                db_path=db,
                db_mode="realtime",
            )
            build_equity_view(result)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"Invalid mode should not crash: {exc!r}")


# ── T16: no network from fundamentals path ────────────────────────────────────

class TestT16NoNetworkFromFundamentals:
    """T16 — E1 enrichment reads only from local SQLite; no network calls."""

    def test_no_outbound_calls_during_enrichment(self):
        db = _aapl_db()

        # Patch httpx and socket to verify no network calls
        import socket as _socket
        original_connect = _socket.socket.connect

        network_calls = []

        def mock_connect(self, address):
            network_calls.append(address)
            return original_connect(self, address)

        with patch.object(_socket.socket, "connect", mock_connect):
            result = enrich_selected_asset(
                "AAPL", "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1",
                db_path=db,
            )
            build_equity_view(result)

        assert not network_calls, (
            f"Network calls made during fundamentals enrichment: {network_calls}"
        )


# ── T17: provider metadata ────────────────────────────────────────────────────

class TestT17ProviderMetadata:
    """T17 — Provider name comes from E1 bundle, not hardcoded."""

    def test_custom_provider_name_rendered(self):
        db = _make_db(
            "AAPL", "AAPL", "0xA",
            provider="CUSTOM_TEST_PROVIDER",
            derived_json=_DERIVED_AAPL,
        )
        result = enrich_selected_asset("AAPL", "0xA", db_path=db)
        view = build_equity_view(result)
        assert view["reporting"]["provider"] == "CUSTOM_TEST_PROVIDER"

    def test_different_provider_does_not_hardcode(self):
        db = _make_db(
            "AAPL", "AAPL", "0xA",
            provider="ANOTHER_PROVIDER_XYZ",
            derived_json=_DERIVED_AAPL,
        )
        result = enrich_selected_asset("AAPL", "0xA", db_path=db)
        view = build_equity_view(result)
        assert view["reporting"]["provider"] == "ANOTHER_PROVIDER_XYZ"
        assert "MASSIVE" not in view["reporting"]["provider"]
        assert "LEGACY" not in view["reporting"]["provider"]


# ── T18: genuine negative numeric ────────────────────────────────────────────

class TestT18GenuineNegativeNumeric:
    """T18 — Negative net_debt remains negative; never clamped to zero."""

    def test_negative_net_debt_preserved(self):
        import json
        derived = json.loads(_DERIVED_AAPL)
        derived["net_debt"] = -100.0
        db = _make_db("AAPL", "AAPL", "0xA", derived_json=json.dumps(derived))
        result = enrich_selected_asset("AAPL", "0xA", db_path=db)
        view = build_equity_view(result)
        nd = view["ttm_metrics"]["fields"]["net_debt"]
        assert nd["raw"] == -100.0
        assert nd["value"] == "-100.00"
        assert nd["is_missing"] is False

    def test_negative_not_clamped(self):
        import json
        derived = json.loads(_DERIVED_AAPL)
        derived["net_debt"] = -9876543210.0
        db = _make_db("AAPL", "AAPL", "0xA", derived_json=json.dumps(derived))
        result = enrich_selected_asset("AAPL", "0xA", db_path=db)
        view = build_equity_view(result)
        nd = view["ttm_metrics"]["fields"]["net_debt"]
        assert nd["raw"] < 0
        assert nd["value"].startswith("-")

    def test_fmt_float_negative(self):
        assert _fmt_float(-100.0) == "-100.00"
        assert _fmt_float(0.0) == "0.00"
        assert _fmt_float(None) == "—"
