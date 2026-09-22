"""E1 equity fundamentals read authority — T1 through T21.

All tests use a synthetic in-process SQLite DB with the exact production
schema.  No production data.  No network calls.  No Robinhood API calls.

T1  — token identity: NVDA resolves to NVDA; case-insensitive; unknown fails.
T2  — missing != zero: revenues=0.0 is distinct from free_cash_flow=None.
T3  — latest TTM: multiple TTM rows; latest period_end is chosen.
T4  — same-period payload revisions: newest version deterministically selected.
T5  — annual and quarterly: latest per timeframe; no cross-contamination.
T6  — profile revision: latest fetched_at profile selected.
T7  — partial coverage: TTM absent → bundle is PARTIAL; no fake TTM.
T8  — dividends/splits: chronological order; genuine 0.0 preserved.
T9  — lineage: payload_hash linkage preserved.
T10 — inactive asset: direct lookup returns active=False; list excludes it.
T11 — read-only enforcement: INSERT through repo raises; missing path not created.
T12 — deterministic bundle: two identical reads produce equivalent results.
T13 — malformed JSON: parse error isolated to section; record still returned.
T14 — no market authority leakage: bundle contains no price/quote/liquidity fields.
T15 — WAL snapshot mode: immutable=1 URI; no WAL/SHM files created.
T16 — live mode: mode=ro only URI; standard WAL open.
T17 — atomic bundle read: all fields from one read_session.
T18 — missing schema table → EquityDBReadError → SOURCE_UNAVAILABLE.
T19 — dividend frequency is Optional[int], not string.
T20 — derived_source metadata preserved: absent/malformed distinction.
T21 — canonical token symbol: bundle uses DB form, not request casing.
"""
from __future__ import annotations

import dataclasses
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Optional

import pytest

from finco_radar.equity.config import (
    EquityDBModeError,
    EquityDBNotConfiguredError,
    EquityDBNotFoundError,
    resolve_db_mode,
    resolve_db_path,
)
from finco_radar.equity.models import AvailabilityState, EquityFundamentalsBundle
from finco_radar.equity.repository import (
    EquityFundamentalsRepository,
    EquityDBReadError,
    open_db,
)
from finco_radar.equity.service import get_equity_fundamentals


# ── schema ────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE equity_assets (
    robinhood_token_symbol TEXT PRIMARY KEY,
    underlying_ticker TEXT NOT NULL,
    name TEXT,
    token_contract_address TEXT,
    chain_network TEXT,
    underlying_exchange TEXT,
    cik TEXT,
    figi TEXT,
    currency TEXT,
    security_type TEXT,
    active INTEGER,
    first_seen_at TEXT,
    last_seen_at TEXT
);

CREATE TABLE equity_company_profiles (
    ticker TEXT,
    cik TEXT,
    profile_json TEXT,
    payload_hash TEXT,
    provider TEXT,
    source_contract TEXT,
    fetched_at TEXT,
    PRIMARY KEY (ticker, payload_hash)
);

CREATE TABLE equity_financial_snapshots (
    ticker TEXT,
    cik TEXT,
    timeframe TEXT,
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
    derived_json TEXT,
    PRIMARY KEY (ticker, timeframe, period_end, payload_hash)
);

CREATE TABLE equity_dividends (
    ticker TEXT,
    external_id TEXT PRIMARY KEY,
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

CREATE TABLE equity_splits (
    ticker TEXT,
    external_id TEXT PRIMARY KEY,
    execution_date TEXT,
    split_from REAL,
    split_to REAL,
    first_seen_at TEXT
);

CREATE TABLE equity_source_lineage (
    lineage_id TEXT PRIMARY KEY,
    ticker TEXT,
    stage TEXT,
    provider TEXT,
    source_contract TEXT,
    endpoint TEXT,
    payload_hash TEXT,
    raw_payload_json TEXT,
    normalized_ref TEXT,
    fetched_at TEXT
);

CREATE TABLE equity_ingestion_runs (
    run_key TEXT PRIMARY KEY,
    stage TEXT,
    ticker TEXT,
    status TEXT,
    attempts INTEGER,
    detail TEXT,
    updated_at TEXT
);
"""


def _make_db(rows_fn=None) -> Path:
    """Create a fresh temporary DB with the exact production schema."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    path = Path(f.name)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_DDL)
        if rows_fn is not None:
            rows_fn(conn)
        conn.commit()
    finally:
        conn.close()
    return path


def _make_wal_db(rows_fn=None) -> Path:
    """Create a fresh temporary DB in genuine WAL journal mode with the production schema.

    Asserts that PRAGMA journal_mode=WAL was actually applied (returns 'wal').
    """
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    path = Path(f.name)
    conn = sqlite3.connect(str(path))
    try:
        result = conn.execute("PRAGMA journal_mode=WAL").fetchone()
        assert result[0] == "wal", f"Expected WAL journal mode, got: {result[0]!r}"
        conn.executescript(_DDL)
        if rows_fn is not None:
            rows_fn(conn)
        conn.commit()
    finally:
        conn.close()
    return path


def _nvda_asset(conn, active=1):
    conn.execute(
        """INSERT INTO equity_assets VALUES
        (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "NVDA", "NVDA", "NVIDIA Corporation",
            "0xabcdef1234567890abcdef1234567890abcdef12", "ethereum",
            "NASDAQ", "1045810", "BBG000BBJQV0", "USD", "common_stock",
            active, "2023-01-01T00:00:00", "2026-09-01T00:00:00",
        ),
    )


def _insert_snapshot(
    conn, ticker, timeframe, period_end, payload_hash,
    filing_date="2024-02-15", normalized_at="2024-03-01T00:00:00",
    fetched_at="2024-03-02T00:00:00",
    income_json=None, balance_json=None, cashflow_json=None, derived_json=None,
):
    conn.execute(
        """INSERT INTO equity_financial_snapshots
        (ticker, cik, timeframe, fiscal_year, fiscal_quarter, period_end,
         filing_date, provider, source_contract, fetched_at, normalized_at,
         payload_hash, income_statement_json, balance_sheet_json,
         cash_flow_statement_json, derived_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            ticker, None, timeframe, "2023", None, period_end,
            filing_date, "MASSIVE", "LEGACY_MASSIVE_VX",
            fetched_at, normalized_at, payload_hash,
            income_json, balance_json, cashflow_json, derived_json,
        ),
    )


# ══════════════════════════════════════════════════════════════════════════════
# T1 — token identity
# ══════════════════════════════════════════════════════════════════════════════

class TestT1TokenIdentity:
    def test_nvda_resolves_to_underlying_nvda(self):
        path = _make_db(_nvda_asset)
        repo = EquityFundamentalsRepository(path)
        asset = repo.get_asset("NVDA")
        assert asset is not None
        assert asset.underlying_ticker == "NVDA"
        assert asset.robinhood_token_symbol == "NVDA"

    def test_asset_metadata_exposed(self):
        path = _make_db(_nvda_asset)
        repo = EquityFundamentalsRepository(path)
        asset = repo.get_asset("NVDA")
        assert asset.name == "NVIDIA Corporation"
        assert asset.chain_network == "ethereum"
        assert asset.underlying_exchange == "NASDAQ"
        assert asset.cik == "1045810"
        assert asset.figi == "BBG000BBJQV0"
        assert asset.currency == "USD"
        assert asset.security_type == "common_stock"
        assert asset.active is True

    def test_case_insensitive_lookup_lower(self):
        path = _make_db(_nvda_asset)
        repo = EquityFundamentalsRepository(path)
        assert repo.get_asset("nvda") is not None

    def test_case_insensitive_lookup_mixed(self):
        path = _make_db(_nvda_asset)
        repo = EquityFundamentalsRepository(path)
        assert repo.get_asset("Nvda") is not None

    def test_unknown_token_returns_none(self):
        path = _make_db(_nvda_asset)
        repo = EquityFundamentalsRepository(path)
        assert repo.get_asset("UNKNOWN_TOKEN_XYZ") is None

    def test_unknown_token_bundle_is_not_found(self):
        path = _make_db(_nvda_asset)
        bundle = get_equity_fundamentals("UNKNOWN_TOKEN_XYZ", db_path=path)
        assert bundle.availability == AvailabilityState.NOT_FOUND
        assert bundle.asset is None


# ══════════════════════════════════════════════════════════════════════════════
# T2 — MISSING != ZERO
# ══════════════════════════════════════════════════════════════════════════════

class TestT2MissingNotZero:
    """revenues=0.0 must be distinct from free_cash_flow=absent."""

    def test_zero_revenue_distinct_from_missing_fcf(self):
        derived_data = {"revenues": 0.0}  # free_cash_flow key intentionally absent

        def seed(conn):
            _nvda_asset(conn)
            _insert_snapshot(
                conn, "NVDA", "ttm", "2024-03-31", "hash-t2",
                derived_json=json.dumps(derived_data),
            )

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        snap = repo.get_latest_snapshot("NVDA", "ttm")
        assert snap is not None
        assert snap.derived is not None
        assert snap.derived.revenues == 0.0, "revenues=0.0 must NOT be None"
        assert snap.derived.free_cash_flow is None, (
            "free_cash_flow absent from JSON must be None, not 0.0"
        )

    def test_zero_and_null_in_income_statement(self):
        income_data = {"revenue": 0.0, "net_income": None, "gross_profit": 100000.0}

        def seed(conn):
            _nvda_asset(conn)
            _insert_snapshot(
                conn, "NVDA", "annual", "2024-12-31", "hash-t2b",
                income_json=json.dumps(income_data),
            )

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        snap = repo.get_latest_snapshot("NVDA", "annual")
        assert snap is not None
        d = snap.income_statement.value
        assert d["revenue"] == 0.0
        assert d["net_income"] is None
        assert d["gross_profit"] == 100000.0

    def test_derived_negative_number_preserved(self):
        derived_data = {"net_debt": -5000000.0}

        def seed(conn):
            _nvda_asset(conn)
            _insert_snapshot(
                conn, "NVDA", "ttm", "2024-03-31", "hash-t2c",
                derived_json=json.dumps(derived_data),
            )

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        snap = repo.get_latest_snapshot("NVDA", "ttm")
        assert snap.derived.net_debt == -5000000.0


# ══════════════════════════════════════════════════════════════════════════════
# T3 — latest TTM
# ══════════════════════════════════════════════════════════════════════════════

class TestT3LatestTTM:
    def test_latest_period_end_chosen(self):
        def seed(conn):
            _nvda_asset(conn)
            _insert_snapshot(conn, "NVDA", "ttm", "2023-09-30", "hash-old")
            _insert_snapshot(conn, "NVDA", "ttm", "2024-03-31", "hash-new")
            _insert_snapshot(conn, "NVDA", "ttm", "2023-12-31", "hash-mid")

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        snap = repo.get_latest_snapshot("NVDA", "ttm")
        assert snap is not None
        assert snap.period_end == "2024-03-31", (
            f"Expected latest period 2024-03-31, got {snap.period_end}"
        )

    def test_history_returns_multiple_periods_in_order(self):
        def seed(conn):
            _nvda_asset(conn)
            for period in ["2024-03-31", "2023-12-31", "2023-09-30"]:
                _insert_snapshot(conn, "NVDA", "ttm", period, f"hash-{period}")

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        history = repo.get_financial_history("NVDA", "ttm")
        periods = [s.period_end for s in history]
        assert periods == sorted(periods, reverse=True), (
            "History must be returned period_end DESC"
        )
        assert periods[0] == "2024-03-31"


# ══════════════════════════════════════════════════════════════════════════════
# T4 — same-period payload revisions
# ══════════════════════════════════════════════════════════════════════════════

class TestT4SamePeriodRevisions:
    """Two rows for the same period → newest version selected deterministically."""

    def test_latest_fetched_version_selected(self):
        def seed(conn):
            _nvda_asset(conn)
            # Older version fetched first
            _insert_snapshot(
                conn, "NVDA", "ttm", "2024-03-31", "hash-v1",
                filing_date="2024-05-01",
                normalized_at="2024-05-10T00:00:00",
                fetched_at="2024-05-11T00:00:00",
                derived_json=json.dumps({"revenues": 100.0}),
            )
            # Newer version fetched later
            _insert_snapshot(
                conn, "NVDA", "ttm", "2024-03-31", "hash-v2",
                filing_date="2024-05-01",
                normalized_at="2024-05-15T00:00:00",
                fetched_at="2024-05-16T00:00:00",
                derived_json=json.dumps({"revenues": 999.0}),
            )

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        snap = repo.get_latest_snapshot("NVDA", "ttm")
        assert snap is not None
        assert snap.payload_hash == "hash-v2", (
            "Newer version (hash-v2) must be selected over older (hash-v1)"
        )
        assert snap.derived.revenues == 999.0

    def test_history_deduplicates_same_period(self):
        """History must return ONE row per period (latest version)."""

        def seed(conn):
            _nvda_asset(conn)
            _insert_snapshot(
                conn, "NVDA", "ttm", "2024-03-31", "hash-old-v",
                fetched_at="2024-05-01T00:00:00",
                derived_json=json.dumps({"revenues": 1.0}),
            )
            _insert_snapshot(
                conn, "NVDA", "ttm", "2024-03-31", "hash-new-v",
                fetched_at="2024-06-01T00:00:00",
                derived_json=json.dumps({"revenues": 2.0}),
            )
            _insert_snapshot(conn, "NVDA", "ttm", "2023-12-31", "hash-prev-p")

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        history = repo.get_financial_history("NVDA", "ttm")
        periods = [s.period_end for s in history]
        assert len(periods) == len(set(periods)), "Duplicate periods in history"
        march_row = next(s for s in history if s.period_end == "2024-03-31")
        assert march_row.payload_hash == "hash-new-v"
        assert march_row.derived.revenues == 2.0

    def test_payload_hash_asc_is_stable_tiebreak(self):
        """When fetched_at also ties, payload_hash ASC is the deterministic winner."""

        def seed(conn):
            _nvda_asset(conn)
            for h in ("hash-zz", "hash-aa"):
                _insert_snapshot(
                    conn, "NVDA", "annual", "2024-12-31", h,
                    filing_date="2025-02-01",
                    normalized_at="2025-02-10T00:00:00",
                    fetched_at="2025-02-10T00:00:00",
                )

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        snap = repo.get_latest_snapshot("NVDA", "annual")
        assert snap.payload_hash == "hash-aa", (
            "payload_hash ASC tie-break: 'hash-aa' < 'hash-zz'"
        )


# ══════════════════════════════════════════════════════════════════════════════
# T5 — annual and quarterly
# ══════════════════════════════════════════════════════════════════════════════

class TestT5AnnualAndQuarterly:
    def test_annual_returns_latest_annual(self):
        def seed(conn):
            _nvda_asset(conn)
            _insert_snapshot(conn, "NVDA", "annual", "2024-12-31", "hash-a24")
            _insert_snapshot(conn, "NVDA", "annual", "2023-12-31", "hash-a23")
            _insert_snapshot(conn, "NVDA", "quarterly", "2024-03-31", "hash-q1")

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        snap = repo.get_latest_snapshot("NVDA", "annual")
        assert snap.period_end == "2024-12-31"
        assert snap.timeframe == "annual"

    def test_quarterly_returns_latest_quarterly(self):
        def seed(conn):
            _nvda_asset(conn)
            _insert_snapshot(conn, "NVDA", "annual", "2024-12-31", "hash-a24")
            _insert_snapshot(conn, "NVDA", "quarterly", "2024-09-30", "hash-q3")
            _insert_snapshot(conn, "NVDA", "quarterly", "2024-06-30", "hash-q2")

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        snap = repo.get_latest_snapshot("NVDA", "quarterly")
        assert snap.period_end == "2024-09-30"
        assert snap.timeframe == "quarterly"

    def test_no_cross_timeframe_contamination(self):
        """Annual query must not return quarterly rows."""

        def seed(conn):
            _nvda_asset(conn)
            _insert_snapshot(conn, "NVDA", "quarterly", "2025-03-31", "hash-q-future")
            _insert_snapshot(conn, "NVDA", "annual", "2024-12-31", "hash-a24")

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        annual = repo.get_latest_snapshot("NVDA", "annual")
        quarterly = repo.get_latest_snapshot("NVDA", "quarterly")
        assert annual.timeframe == "annual"
        assert annual.period_end == "2024-12-31"
        assert quarterly.timeframe == "quarterly"
        assert quarterly.period_end == "2025-03-31"


# ══════════════════════════════════════════════════════════════════════════════
# T6 — profile revision
# ══════════════════════════════════════════════════════════════════════════════

class TestT6ProfileRevision:
    def test_latest_fetched_profile_selected(self):
        def seed(conn):
            _nvda_asset(conn)
            conn.execute(
                "INSERT INTO equity_company_profiles VALUES (?,?,?,?,?,?,?)",
                ("NVDA", "1045810",
                 json.dumps({"name": "NVIDIA v1"}), "phash-old",
                 "MASSIVE", "LEGACY_MASSIVE_VX", "2024-01-01T00:00:00"),
            )
            conn.execute(
                "INSERT INTO equity_company_profiles VALUES (?,?,?,?,?,?,?)",
                ("NVDA", "1045810",
                 json.dumps({"name": "NVIDIA v2"}), "phash-new",
                 "MASSIVE", "LEGACY_MASSIVE_VX", "2025-01-01T00:00:00"),
            )

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        profile = repo.get_latest_profile("NVDA")
        assert profile is not None
        assert profile.payload_hash == "phash-new"
        assert profile.profile.value["name"] == "NVIDIA v2"

    def test_profile_fetched_at_exposed(self):
        def seed(conn):
            _nvda_asset(conn)
            conn.execute(
                "INSERT INTO equity_company_profiles VALUES (?,?,?,?,?,?,?)",
                ("NVDA", None, json.dumps({"name": "NVIDIA"}), "ph1",
                 "MASSIVE", "LEGACY_MASSIVE_VX", "2025-06-01T12:00:00"),
            )

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        profile = repo.get_latest_profile("NVDA")
        assert profile.fetched_at == "2025-06-01T12:00:00"


# ══════════════════════════════════════════════════════════════════════════════
# T7 — partial coverage
# ══════════════════════════════════════════════════════════════════════════════

class TestT7PartialCoverage:
    def test_no_ttm_bundle_is_partial(self):
        def seed(conn):
            _nvda_asset(conn)
            conn.execute(
                "INSERT INTO equity_company_profiles VALUES (?,?,?,?,?,?,?)",
                ("NVDA", None, json.dumps({"name": "NVIDIA"}), "ph1",
                 "MASSIVE", "LEGACY_MASSIVE_VX", "2025-01-01T00:00:00"),
            )
            # Annual exists but no TTM
            _insert_snapshot(conn, "NVDA", "annual", "2024-12-31", "hash-ann")

        path = _make_db(seed)
        bundle = get_equity_fundamentals("NVDA", db_path=path)
        assert bundle.availability == AvailabilityState.PARTIAL
        assert bundle.latest_ttm is None, "No fake TTM should be manufactured"
        assert bundle.latest_annual is not None
        assert bundle.latest_annual.period_end == "2024-12-31"

    def test_no_snapshots_bundle_is_partial(self):
        def seed(conn):
            _nvda_asset(conn)
            conn.execute(
                "INSERT INTO equity_company_profiles VALUES (?,?,?,?,?,?,?)",
                ("NVDA", None, json.dumps({"name": "NVIDIA"}), "ph1",
                 "MASSIVE", "LEGACY_MASSIVE_VX", "2025-01-01T00:00:00"),
            )

        path = _make_db(seed)
        bundle = get_equity_fundamentals("NVDA", db_path=path)
        assert bundle.availability == AvailabilityState.PARTIAL
        assert bundle.latest_ttm is None
        assert bundle.latest_quarterly is None
        assert bundle.latest_annual is None

    def test_full_data_is_available(self):
        def seed(conn):
            _nvda_asset(conn)
            conn.execute(
                "INSERT INTO equity_company_profiles VALUES (?,?,?,?,?,?,?)",
                ("NVDA", None, json.dumps({"name": "NVIDIA"}), "ph1",
                 "MASSIVE", "LEGACY_MASSIVE_VX", "2025-01-01T00:00:00"),
            )
            _insert_snapshot(conn, "NVDA", "ttm", "2024-09-30", "hash-ttm")

        path = _make_db(seed)
        bundle = get_equity_fundamentals("NVDA", db_path=path)
        assert bundle.availability == AvailabilityState.AVAILABLE

    def test_asset_only_no_data_is_not_available(self):
        path = _make_db(_nvda_asset)
        bundle = get_equity_fundamentals("NVDA", db_path=path)
        assert bundle.availability == AvailabilityState.NOT_AVAILABLE


# ══════════════════════════════════════════════════════════════════════════════
# T8 — dividends and splits
# ══════════════════════════════════════════════════════════════════════════════

class TestT8DividendsAndSplits:
    def _seed_divs_splits(self, conn):
        _nvda_asset(conn)
        # Two dividend records; newest pay_date first
        conn.execute(
            "INSERT INTO equity_dividends VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("NVDA", "div-001", 0.10, "USD",
             "2024-09-01", "2024-09-15", "2024-09-16", "2024-10-01",
             4, "CASH", "2024-09-02T00:00:00"),
        )
        conn.execute(
            "INSERT INTO equity_dividends VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("NVDA", "div-002", 0.0, "USD",
             "2024-06-01", "2024-06-15", "2024-06-16", "2024-07-01",
             4, "CASH", "2024-06-02T00:00:00"),
        )
        # Split record
        conn.execute(
            "INSERT INTO equity_splits VALUES (?,?,?,?,?,?)",
            ("NVDA", "split-001", "2021-07-20", 1.0, 4.0, "2021-07-21T00:00:00"),
        )

    def test_dividends_returned_newest_first(self):
        path = _make_db(self._seed_divs_splits)
        repo = EquityFundamentalsRepository(path)
        divs = repo.get_dividends("NVDA")
        assert divs[0].external_id == "div-001", "Newest dividend first"
        assert divs[1].external_id == "div-002"

    def test_zero_cash_amount_preserved(self):
        path = _make_db(self._seed_divs_splits)
        repo = EquityFundamentalsRepository(path)
        divs = repo.get_dividends("NVDA")
        zero_div = next(d for d in divs if d.external_id == "div-002")
        assert zero_div.cash_amount == 0.0, "cash_amount=0.0 must NOT be None"

    def test_splits_typed_correctly(self):
        path = _make_db(self._seed_divs_splits)
        repo = EquityFundamentalsRepository(path)
        splits = repo.get_splits("NVDA")
        assert len(splits) == 1
        s = splits[0]
        assert s.split_from == 1.0
        assert s.split_to == 4.0
        assert s.execution_date == "2021-07-20"


# ══════════════════════════════════════════════════════════════════════════════
# T9 — lineage
# ══════════════════════════════════════════════════════════════════════════════

class TestT9Lineage:
    def test_lineage_linked_by_payload_hash(self):
        target_hash = "hash-ttm-lineage"

        def seed(conn):
            _nvda_asset(conn)
            _insert_snapshot(
                conn, "NVDA", "ttm", "2024-03-31", target_hash,
            )
            conn.execute(
                """INSERT INTO equity_source_lineage
                (lineage_id, ticker, stage, provider, source_contract,
                 endpoint, payload_hash, raw_payload_json, normalized_ref, fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    "lin-001", "NVDA", "normalize", "MASSIVE",
                    "LEGACY_MASSIVE_VX", "/api/v2/fundamentals",
                    target_hash, None, "norm-ref-001",
                    "2024-03-02T00:00:00",
                ),
            )

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        lineage = repo.get_lineage("NVDA", payload_hash=target_hash)
        assert len(lineage) == 1
        lin = lineage[0]
        assert lin.payload_hash == target_hash
        assert lin.provider == "MASSIVE"
        assert lin.source_contract == "LEGACY_MASSIVE_VX"
        assert lin.normalized_ref == "norm-ref-001"

    def test_lineage_in_bundle(self):
        target_hash = "hash-bundle-lin"

        def seed(conn):
            _nvda_asset(conn)
            _insert_snapshot(
                conn, "NVDA", "ttm", "2024-03-31", target_hash,
            )
            conn.execute(
                """INSERT INTO equity_source_lineage
                (lineage_id, ticker, stage, provider, source_contract,
                 endpoint, payload_hash, raw_payload_json, normalized_ref, fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    "lin-002", "NVDA", "fetch", "MASSIVE",
                    "LEGACY_MASSIVE_VX", "/api/v2/income",
                    target_hash, None, None, "2024-03-02T00:00:00",
                ),
            )

        path = _make_db(seed)
        bundle = get_equity_fundamentals("NVDA", db_path=path)
        assert len(bundle.source_lineage_summary) >= 1
        lin = bundle.source_lineage_summary[0]
        assert lin.payload_hash == target_hash


# ══════════════════════════════════════════════════════════════════════════════
# T10 — inactive asset
# ══════════════════════════════════════════════════════════════════════════════

class TestT10InactiveAsset:
    def test_direct_lookup_returns_inactive_asset(self):
        def seed(conn):
            _nvda_asset(conn, active=0)

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        asset = repo.get_asset("NVDA")
        assert asset is not None, "Inactive asset must NOT be hidden on direct lookup"
        assert asset.active is False

    def test_active_listing_excludes_inactive(self):
        def seed(conn):
            _nvda_asset(conn, active=0)
            conn.execute(
                "INSERT INTO equity_assets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("AAPL", "AAPL", "Apple Inc.", None, None, "NASDAQ",
                 None, None, "USD", "common_stock", 1,
                 "2023-01-01T00:00:00", "2026-09-01T00:00:00"),
            )

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        active = repo.list_active_assets()
        symbols = [a.robinhood_token_symbol for a in active]
        assert "NVDA" not in symbols, "Inactive NVDA must be excluded from list"
        assert "AAPL" in symbols, "Active AAPL must be in list"


# ══════════════════════════════════════════════════════════════════════════════
# T11 — read-only enforcement
# ══════════════════════════════════════════════════════════════════════════════

class TestT11ReadOnly:
    def test_insert_through_open_db_raises(self):
        path = _make_db(_nvda_asset)
        with open_db(path) as conn:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute(
                    "INSERT INTO equity_assets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("TEST", "TEST", None, None, None, None,
                     None, None, None, None, 1, None, None),
                )

    def test_create_table_through_open_db_raises(self):
        path = _make_db(_nvda_asset)
        with open_db(path) as conn:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute("CREATE TABLE new_table (id INTEGER)")

    def test_missing_path_is_not_created(self):
        missing = Path(tempfile.mkdtemp()) / "does_not_exist.db"
        assert not missing.exists()
        with pytest.raises(EquityDBReadError):
            with open_db(missing):
                pass
        assert not missing.exists(), "Missing DB must NOT be auto-created"

    def test_missing_path_bundle_is_source_unavailable(self):
        missing = Path(tempfile.mkdtemp()) / "absent.db"
        bundle = get_equity_fundamentals("NVDA", db_path=missing)
        assert bundle.availability == AvailabilityState.SOURCE_UNAVAILABLE


# ══════════════════════════════════════════════════════════════════════════════
# T12 — deterministic bundle
# ══════════════════════════════════════════════════════════════════════════════

class TestT12Deterministic:
    def test_two_reads_produce_equivalent_bundles(self):
        def seed(conn):
            _nvda_asset(conn)
            conn.execute(
                "INSERT INTO equity_company_profiles VALUES (?,?,?,?,?,?,?)",
                ("NVDA", None, json.dumps({"name": "NVIDIA"}), "ph1",
                 "MASSIVE", "LEGACY_MASSIVE_VX", "2025-01-01T00:00:00"),
            )
            _insert_snapshot(conn, "NVDA", "ttm", "2024-09-30", "hash-ttm")

        path = _make_db(seed)
        b1 = get_equity_fundamentals("NVDA", db_path=path)
        b2 = get_equity_fundamentals("NVDA", db_path=path)
        assert b1 == b2, "Bundle must be deterministic across identical reads"

    def test_no_network_calls(self):
        """Smoke test: get_equity_fundamentals completes without network access."""
        import socket
        original_getaddrinfo = socket.getaddrinfo

        def no_network(*args, **kwargs):
            raise AssertionError("Network call attempted inside get_equity_fundamentals")

        path = _make_db(_nvda_asset)
        socket.getaddrinfo = no_network
        try:
            bundle = get_equity_fundamentals("NVDA", db_path=path)
        finally:
            socket.getaddrinfo = original_getaddrinfo
        assert bundle is not None


# ══════════════════════════════════════════════════════════════════════════════
# T13 — malformed JSON
# ══════════════════════════════════════════════════════════════════════════════

class TestT13MalformedJSON:
    def test_malformed_income_statement_does_not_crash(self):
        def seed(conn):
            _nvda_asset(conn)
            _insert_snapshot(
                conn, "NVDA", "ttm", "2024-03-31", "hash-bad-json",
                income_json="{not valid json!!!",
                balance_json=json.dumps({"total_assets": 50000000.0}),
            )

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        snap = repo.get_latest_snapshot("NVDA", "ttm")
        assert snap is not None, "Record must remain available despite malformed JSON"
        assert snap.income_statement.parse_error is not None, (
            "parse_error must be set for malformed income_statement_json"
        )
        assert snap.income_statement.value is None, (
            "value must be None (not {}) for malformed JSON"
        )
        assert not snap.income_statement.absent, (
            "absent must be False: field was present but malformed"
        )
        assert snap.balance_sheet.is_available, "Valid balance sheet must still parse"
        assert snap.balance_sheet.value["total_assets"] == 50000000.0

    def test_malformed_derived_json_does_not_return_empty_dict(self):
        def seed(conn):
            _nvda_asset(conn)
            _insert_snapshot(
                conn, "NVDA", "ttm", "2024-03-31", "hash-bad-derived",
                derived_json="[1, 2, 3]",  # valid JSON but wrong type (list)
            )

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        snap = repo.get_latest_snapshot("NVDA", "ttm")
        assert snap.derived is None, (
            "Non-object derived_json must yield derived=None, not an empty dict"
        )
        assert snap.income_statement.absent, (
            "Absent income_statement_json must be absent=True"
        )

    def test_malformed_json_bundle_still_returned(self):
        def seed(conn):
            _nvda_asset(conn)
            _insert_snapshot(
                conn, "NVDA", "ttm", "2024-03-31", "hash-malformed",
                income_json="INVALID",
            )

        path = _make_db(seed)
        bundle = get_equity_fundamentals("NVDA", db_path=path)
        assert bundle.latest_ttm is not None
        assert bundle.latest_ttm.income_statement.parse_error is not None

    def test_malformed_profile_json_does_not_crash(self):
        def seed(conn):
            _nvda_asset(conn)
            conn.execute(
                "INSERT INTO equity_company_profiles VALUES (?,?,?,?,?,?,?)",
                ("NVDA", None, "{bad json", "ph-bad",
                 "MASSIVE", "LEGACY_MASSIVE_VX", "2025-01-01T00:00:00"),
            )

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        profile = repo.get_latest_profile("NVDA")
        assert profile is not None
        assert profile.profile.parse_error is not None
        assert profile.profile.value is None


# ══════════════════════════════════════════════════════════════════════════════
# T14 — no market authority leakage
# ══════════════════════════════════════════════════════════════════════════════

_MARKET_FIELD_PATTERNS = {
    "price", "quote", "ohlcv", "ohlc", "open", "high", "low", "close",
    "volume", "spread", "liquidity", "bid", "ask", "execution",
    "token_price", "live_price", "market_price", "last_price",
}


def _field_names_of(cls) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


class TestT14NoMarketAuthorityLeakage:
    def test_bundle_has_no_price_fields(self):
        bundle_fields = _field_names_of(EquityFundamentalsBundle)
        overlap = bundle_fields & _MARKET_FIELD_PATTERNS
        assert not overlap, (
            f"EquityFundamentalsBundle must not contain market-price fields: {overlap}"
        )

    def test_asset_identity_has_no_price_fields(self):
        from finco_radar.equity.models import EquityAssetIdentity
        overlap = _field_names_of(EquityAssetIdentity) & _MARKET_FIELD_PATTERNS
        assert not overlap

    def test_financial_snapshot_has_no_price_fields(self):
        from finco_radar.equity.models import FinancialSnapshot
        overlap = _field_names_of(FinancialSnapshot) & _MARKET_FIELD_PATTERNS
        assert not overlap

    def test_derived_fundamentals_has_no_price_fields(self):
        from finco_radar.equity.models import DerivedFundamentals
        overlap = _field_names_of(DerivedFundamentals) & _MARKET_FIELD_PATTERNS
        assert not overlap

    def test_freshness_has_no_price_fields(self):
        from finco_radar.equity.models import FundamentalsFreshness
        overlap = _field_names_of(FundamentalsFreshness) & _MARKET_FIELD_PATTERNS
        assert not overlap

    def test_service_imports_no_market_modules(self):
        """service.py must not import from Radar market-price modules."""
        import importlib, ast
        import finco_radar.equity.service as svc_mod
        src = Path(svc_mod.__file__).read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in getattr(node, "names", []):
                    assert "quote" not in alias.name.lower(), (
                        f"service.py imports quote module: {alias.name}"
                    )
                    assert "gap" not in alias.name.lower()
                    assert "liquidity" not in alias.name.lower()


# ══════════════════════════════════════════════════════════════════════════════
# Config resolver tests
# ══════════════════════════════════════════════════════════════════════════════

class TestConfig:
    def test_not_configured_raises(self, monkeypatch):
        monkeypatch.delenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", raising=False)
        with pytest.raises(EquityDBNotConfiguredError):
            resolve_db_path()

    def test_configured_missing_file_raises(self, monkeypatch, tmp_path):
        missing = tmp_path / "no_such.db"
        monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", str(missing))
        with pytest.raises(EquityDBNotFoundError):
            resolve_db_path()

    def test_configured_valid_file_returns_path(self, monkeypatch):
        path = _make_db()
        monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", str(path))
        resolved = resolve_db_path()
        assert resolved == path

    def test_source_unavailable_when_env_not_set(self, monkeypatch):
        monkeypatch.delenv("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", raising=False)
        bundle = get_equity_fundamentals("NVDA")
        assert bundle.availability == AvailabilityState.SOURCE_UNAVAILABLE

    def test_mode_defaults_to_snapshot(self, monkeypatch):
        monkeypatch.delenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", raising=False)
        assert resolve_db_mode() == "snapshot"

    def test_mode_live_accepted(self, monkeypatch):
        monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "live")
        assert resolve_db_mode() == "live"

    def test_mode_snapshot_accepted(self, monkeypatch):
        monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "snapshot")
        assert resolve_db_mode() == "snapshot"

    def test_mode_invalid_raises(self, monkeypatch):
        monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "realtime")
        with pytest.raises(EquityDBModeError):
            resolve_db_mode()

    def test_mode_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "SNAPSHOT")
        assert resolve_db_mode() == "snapshot"


# ══════════════════════════════════════════════════════════════════════════════
# E1-F05 — strict mode validation: every public DB-mode entry point
# ══════════════════════════════════════════════════════════════════════════════

class TestF05ModeValidation:
    """No public path may silently downgrade an invalid mode to live behaviour."""

    def test_validate_db_mode_snapshot(self):
        from finco_radar.equity.config import validate_db_mode
        assert validate_db_mode("snapshot") == "snapshot"

    def test_validate_db_mode_live(self):
        from finco_radar.equity.config import validate_db_mode
        assert validate_db_mode("live") == "live"

    def test_validate_db_mode_normalizes_uppercase(self):
        from finco_radar.equity.config import validate_db_mode
        assert validate_db_mode("SNAPSHOT") == "snapshot"
        assert validate_db_mode("LIVE") == "live"

    def test_validate_db_mode_invalid_raises(self):
        from finco_radar.equity.config import validate_db_mode
        with pytest.raises(EquityDBModeError):
            validate_db_mode("realtime")

    def test_validate_db_mode_empty_raises(self):
        from finco_radar.equity.config import validate_db_mode
        with pytest.raises(EquityDBModeError):
            validate_db_mode("")

    def test_validate_db_mode_unknown_raises(self):
        from finco_radar.equity.config import validate_db_mode
        for bad in ("ro", "rw", "readonly", "wal", "immutable", "auto"):
            with pytest.raises(EquityDBModeError, match="invalid"):
                validate_db_mode(bad)

    def test_service_direct_db_mode_invalid_raises(self):
        """get_equity_fundamentals(db_mode='realtime') raises EquityDBModeError
        immediately — does NOT return SOURCE_UNAVAILABLE."""
        path = _make_db(_nvda_asset)
        with pytest.raises(EquityDBModeError):
            get_equity_fundamentals("NVDA", db_path=path, db_mode="realtime")

    def test_service_direct_db_mode_invalid_is_not_source_unavailable(self):
        """EquityDBModeError must NOT be swallowed as SOURCE_UNAVAILABLE."""
        path = _make_db(_nvda_asset)
        try:
            result = get_equity_fundamentals("NVDA", db_path=path, db_mode="bad")
            assert False, (
                f"Expected EquityDBModeError, but got bundle with "
                f"availability={result.availability}"
            )
        except EquityDBModeError:
            pass  # correct

    def test_repository_invalid_mode_raises_on_construction(self):
        """EquityFundamentalsRepository(path, mode='invalid') raises immediately."""
        path = _make_db(_nvda_asset)
        with pytest.raises(EquityDBModeError):
            EquityFundamentalsRepository(path, mode="realtime")

    def test_repository_valid_modes_accepted(self):
        path = _make_db(_nvda_asset)
        for valid_mode in ("snapshot", "live", "SNAPSHOT", "LIVE"):
            repo = EquityFundamentalsRepository(path, mode=valid_mode)
            assert repo._mode in ("snapshot", "live")


# ══════════════════════════════════════════════════════════════════════════════
# T15 — genuine checkpointed WAL snapshot
# ══════════════════════════════════════════════════════════════════════════════

class TestT15WALSnapshotMode:
    def test_make_wal_db_produces_genuine_wal_mode(self):
        """_make_wal_db must produce a DB whose journal_mode is 'wal'."""
        path = _make_wal_db()
        conn = sqlite3.connect(str(path))
        try:
            result = conn.execute("PRAGMA journal_mode").fetchone()
            assert result[0] == "wal", f"Expected WAL journal mode, got: {result[0]!r}"
        finally:
            conn.close()

    def test_snapshot_mode_uri_contains_immutable(self):
        from finco_radar.equity.repository import _build_uri
        uri = _build_uri(Path("/tmp/test.db"), "snapshot")
        assert "immutable=1" in uri
        assert "mode=ro" in uri

    def test_checkpointed_wal_snapshot_reads_correctly(self):
        """E1 snapshot mode reads a genuinely checkpointed WAL database."""
        path = _make_wal_db(_nvda_asset)

        # Complete WAL checkpoint: merge all WAL frames into the main DB file
        conn = sqlite3.connect(str(path))
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()

        repo = EquityFundamentalsRepository(path, mode="snapshot")
        asset = repo.get_asset("NVDA")
        assert asset is not None
        assert asset.underlying_ticker == "NVDA"
        assert asset.robinhood_token_symbol == "NVDA"

    def test_snapshot_mode_no_wal_shm_creation_after_checkpoint(self):
        """Snapshot reader must not create or grow WAL/SHM sidecar files.

        After a checkpoint and full writer close, opening with immutable=1
        must leave the DB directory unchanged.
        """
        path = _make_wal_db(_nvda_asset)

        # Checkpoint and close all writer connections
        conn = sqlite3.connect(str(path))
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()

        wal_path = Path(str(path) + "-wal")
        shm_path = Path(str(path) + "-shm")

        # Capture pre-read sidecar state
        wal_size_before = wal_path.stat().st_size if wal_path.exists() else None
        shm_existed_before = shm_path.exists()

        # E1 snapshot read (immutable=1 — must not touch WAL/SHM)
        repo = EquityFundamentalsRepository(path, mode="snapshot")
        asset = repo.get_asset("NVDA")
        assert asset is not None

        # Verify no new sidecar growth or creation
        wal_size_after = wal_path.stat().st_size if wal_path.exists() else None
        shm_after = shm_path.exists()

        if wal_size_before is None:
            assert wal_size_after in (None, 0), (
                "Snapshot reader must not create WAL sidecar file"
            )
        else:
            assert (wal_size_after or 0) <= wal_size_before, (
                "Snapshot reader must not grow WAL file"
            )
        if not shm_existed_before:
            assert not shm_after, "Snapshot reader must not create SHM sidecar file"

    def test_snapshot_mode_nonwritable_directory(self):
        """Snapshot mode (immutable=1) works even when the DB directory is not writable.

        This proves immutable=1 bypasses WAL/SHM which would require write
        permission on the source directory.  Skipped when running as root.
        """
        import os
        if os.getuid() == 0:
            pytest.skip("Root ignores filesystem permissions; cannot test read-only directory")

        tmpdir = Path(tempfile.mkdtemp())
        db_path = tmpdir / "snapshot_ro.db"

        # Seed with WAL mode and checkpoint while dir is still writable
        seed_conn = sqlite3.connect(str(db_path))
        try:
            seed_conn.execute("PRAGMA journal_mode=WAL")
            seed_conn.executescript(_DDL)
            _nvda_asset(seed_conn)
            seed_conn.commit()
            seed_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            seed_conn.close()

        # Make directory non-writable (live mode would fail here; snapshot must succeed)
        os.chmod(tmpdir, 0o555)
        try:
            repo = EquityFundamentalsRepository(db_path, mode="snapshot")
            asset = repo.get_asset("NVDA")
            assert asset is not None, "Snapshot mode must work in non-writable directory"
            assert asset.underlying_ticker == "NVDA"
        finally:
            os.chmod(tmpdir, 0o755)

    def test_default_mode_is_snapshot(self):
        path = _make_wal_db(_nvda_asset)
        repo = EquityFundamentalsRepository(path)  # default: "snapshot"
        asset = repo.get_asset("NVDA")
        assert asset is not None


# ══════════════════════════════════════════════════════════════════════════════
# T16 — genuine live WAL reader
# ══════════════════════════════════════════════════════════════════════════════

class TestT16LiveMode:
    def test_live_mode_uri_no_immutable(self):
        from finco_radar.equity.repository import _build_uri
        uri = _build_uri(Path("/tmp/test.db"), "live")
        assert "immutable" not in uri
        assert "mode=ro" in uri

    def test_live_wal_reads_current_data(self):
        """E1 live mode reads a genuine WAL database."""
        path = _make_wal_db(_nvda_asset)
        repo = EquityFundamentalsRepository(path, mode="live")
        asset = repo.get_asset("NVDA")
        assert asset is not None
        assert asset.underlying_ticker == "NVDA"

    def test_live_mode_sees_writer_committed_revision(self):
        """After a writer commits a new revision, a new E1 live-mode session sees it.

        Proof sequence:
          1. Old E1 session reads OLD_TTM (period 2024-03-31).
          2. Writer commits NEW_TTM (period 2024-06-30, newer → selected by tie-break).
          3. New E1 session reads NEW_TTM.
        """
        OLD_TTM_HASH = "old-ttm-live-t16"
        NEW_TTM_HASH = "new-ttm-live-t16"

        def seed(conn):
            _nvda_asset(conn)
            _insert_snapshot(conn, "NVDA", "ttm", "2024-03-31", OLD_TTM_HASH)

        path = _make_wal_db(seed)
        repo = EquityFundamentalsRepository(path, mode="live")

        # Old E1 session: reads initial state
        with repo.read_session() as old_session:
            old_ttm = old_session.get_latest_snapshot("NVDA", "ttm")
        assert old_ttm is not None
        assert old_ttm.payload_hash == OLD_TTM_HASH

        # Writer commits new revision with a newer period_end (wins tie-break)
        writer_conn = sqlite3.connect(str(path))
        try:
            _insert_snapshot(writer_conn, "NVDA", "ttm", "2024-06-30", NEW_TTM_HASH)
            writer_conn.commit()
        finally:
            writer_conn.close()

        # New E1 session: must see the newly committed revision
        with repo.read_session() as new_session:
            new_ttm = new_session.get_latest_snapshot("NVDA", "ttm")
        assert new_ttm is not None
        assert new_ttm.payload_hash == NEW_TTM_HASH, (
            f"New E1 session must see writer-committed revision; "
            f"got {new_ttm.payload_hash}"
        )

    def test_live_mode_bundle_reads_correctly(self):
        def seed(conn):
            _nvda_asset(conn)
            conn.execute(
                "INSERT INTO equity_company_profiles VALUES (?,?,?,?,?,?,?)",
                ("NVDA", None, json.dumps({"name": "NVIDIA"}), "ph1",
                 "MASSIVE", "LEGACY_MASSIVE_VX", "2025-01-01T00:00:00"),
            )
            _insert_snapshot(conn, "NVDA", "ttm", "2024-09-30", "hash-ttm-t16")

        path = _make_wal_db(seed)
        bundle = get_equity_fundamentals("NVDA", db_path=path, db_mode="live")
        assert bundle.availability == AvailabilityState.AVAILABLE
        assert bundle.latest_ttm is not None

    def test_db_mode_override_in_service(self):
        path = _make_wal_db(_nvda_asset)
        bundle = get_equity_fundamentals("NVDA", db_path=path, db_mode="snapshot")
        assert bundle.availability == AvailabilityState.NOT_AVAILABLE


# ══════════════════════════════════════════════════════════════════════════════
# T17 — mandatory concurrent atomic bundle snapshot
# ══════════════════════════════════════════════════════════════════════════════

class TestT17AtomicBundleRead:
    def test_concurrent_atomic_snapshot_no_mixed_reads(self):
        """Atomic bundle authority proof against a genuine WAL database.

        Deterministic sequence:
          1. Seed DB:   OLD_PROFILE (fetched 2025-01-01), OLD_TTM (period 2024-03-31)
          2. Open E1 read_session (live, WAL, BEGIN DEFERRED)
          3. First read establishes WAL snapshot — reads OLD_PROFILE
          4. Writer B commits: NEW_PROFILE (fetched 2026-01-01), NEW_TTM (period 2024-06-30)
          5. Reader in SAME session: must still see OLD_PROFILE and OLD_TTM
             (no mixing of old profile + new TTM or vice versa)
          6. Close reader session
          7. New E1 session: must see NEW_PROFILE and NEW_TTM
        """
        OLD_PROFILE_HASH = "old-profile-t17"
        NEW_PROFILE_HASH = "new-profile-t17"
        OLD_TTM_HASH = "old-ttm-t17"
        NEW_TTM_HASH = "new-ttm-t17"

        def seed(conn):
            _nvda_asset(conn)
            conn.execute(
                "INSERT INTO equity_company_profiles VALUES (?,?,?,?,?,?,?)",
                ("NVDA", None,
                 json.dumps({"name": "NVIDIA old"}), OLD_PROFILE_HASH,
                 "MASSIVE", "LEGACY_MASSIVE_VX", "2025-01-01T00:00:00"),
            )
            _insert_snapshot(
                conn, "NVDA", "ttm", "2024-03-31", OLD_TTM_HASH,
                derived_json=json.dumps({"revenues": 100.0}),
            )

        path = _make_wal_db(seed)
        repo = EquityFundamentalsRepository(path, mode="live")

        reader_profile_hash_during = None
        reader_ttm_hash_during = None

        with repo.read_session() as session:
            # Step 3: First read — establishes WAL read snapshot
            pre_write_profile = session.get_latest_profile("NVDA")
            assert pre_write_profile is not None
            assert pre_write_profile.payload_hash == OLD_PROFILE_HASH, (
                f"Pre-write: expected {OLD_PROFILE_HASH}, "
                f"got {pre_write_profile.payload_hash}"
            )

            # Step 4: Writer B commits NEW data on a separate connection
            writer_conn = sqlite3.connect(str(path))
            try:
                writer_conn.execute(
                    "INSERT INTO equity_company_profiles VALUES (?,?,?,?,?,?,?)",
                    ("NVDA", None,
                     json.dumps({"name": "NVIDIA new"}), NEW_PROFILE_HASH,
                     "MASSIVE", "LEGACY_MASSIVE_VX", "2026-01-01T00:00:00"),
                )
                _insert_snapshot(
                    writer_conn, "NVDA", "ttm", "2024-06-30", NEW_TTM_HASH,
                    derived_json=json.dumps({"revenues": 999.0}),
                )
                writer_conn.commit()
            finally:
                writer_conn.close()

            # Step 5: SAME reader session — must still see OLD snapshot
            post_write_profile = session.get_latest_profile("NVDA")
            post_write_ttm = session.get_latest_snapshot("NVDA", "ttm")

            reader_profile_hash_during = post_write_profile.payload_hash
            reader_ttm_hash_during = post_write_ttm.payload_hash

            assert reader_profile_hash_during == OLD_PROFILE_HASH, (
                f"ATOMIC VIOLATION: same-session profile changed after writer committed.\n"
                f"  Expected OLD: {OLD_PROFILE_HASH}\n"
                f"  Got: {reader_profile_hash_during}"
            )
            assert reader_ttm_hash_during == OLD_TTM_HASH, (
                f"ATOMIC VIOLATION: same-session TTM changed after writer committed.\n"
                f"  Expected OLD: {OLD_TTM_HASH}\n"
                f"  Got: {reader_ttm_hash_during}"
            )
        # Reader session closed

        # Step 7: New E1 session — must see NEW committed data
        with repo.read_session() as new_session:
            new_profile = new_session.get_latest_profile("NVDA")
            new_ttm = new_session.get_latest_snapshot("NVDA", "ttm")

        assert new_profile is not None
        assert new_profile.payload_hash == NEW_PROFILE_HASH, (
            f"New session must see NEW profile {NEW_PROFILE_HASH}; "
            f"got {new_profile.payload_hash}"
        )
        assert new_ttm is not None
        assert new_ttm.payload_hash == NEW_TTM_HASH, (
            f"New session must see NEW TTM {NEW_TTM_HASH}; "
            f"got {new_ttm.payload_hash}"
        )

    def test_read_session_basic_wal(self):
        """read_session context manager works on a WAL DB."""
        path = _make_wal_db(_nvda_asset)
        repo = EquityFundamentalsRepository(path, mode="live")
        with repo.read_session() as session:
            asset = session.get_asset("NVDA")
            profile = session.get_latest_profile("NVDA")
            ttm = session.get_latest_snapshot("NVDA", "ttm")
        assert asset is not None
        assert asset.underlying_ticker == "NVDA"
        assert profile is None
        assert ttm is None

    def test_full_bundle_atomic_via_read_session(self):
        """Service uses one read_session for the entire bundle."""
        def seed(conn):
            _nvda_asset(conn)
            conn.execute(
                "INSERT INTO equity_company_profiles VALUES (?,?,?,?,?,?,?)",
                ("NVDA", None, json.dumps({"name": "NVIDIA"}), "ph1",
                 "MASSIVE", "LEGACY_MASSIVE_VX", "2025-01-01T00:00:00"),
            )
            _insert_snapshot(conn, "NVDA", "ttm", "2024-09-30", "hash-t17-bundle")

        path = _make_wal_db(seed)
        bundle = get_equity_fundamentals("NVDA", db_path=path, db_mode="live")
        assert bundle.asset is not None
        assert bundle.company_profile is not None
        assert bundle.latest_ttm is not None
        assert bundle.availability == AvailabilityState.AVAILABLE

    def test_read_session_does_not_hold_write_lock(self):
        """After read_session closes, the DB is writable again."""
        path = _make_wal_db(_nvda_asset)
        repo = EquityFundamentalsRepository(path, mode="live")
        with repo.read_session() as session:
            _ = session.get_asset("NVDA")
        # Writable connection must succeed after reader closed
        conn = sqlite3.connect(str(path))
        try:
            conn.execute(
                "INSERT INTO equity_assets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("TEST3", "TEST3", None, None, None, None,
                 None, None, None, None, 1, None, None),
            )
            conn.commit()
        finally:
            conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# T18 — missing schema table → EquityDBReadError → SOURCE_UNAVAILABLE
# ══════════════════════════════════════════════════════════════════════════════

class TestT18MissingSchemaTable:
    def test_missing_table_raises_equity_db_read_error(self):
        """A DB missing equity_assets must raise EquityDBReadError (not crash)."""
        f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        f.close()
        path = Path(f.name)
        conn = sqlite3.connect(str(path))
        conn.execute("CREATE TABLE unrelated (id INTEGER)")
        conn.commit()
        conn.close()

        repo = EquityFundamentalsRepository(path)
        with pytest.raises(EquityDBReadError):
            repo.get_asset("NVDA")

    def test_missing_schema_bundle_is_source_unavailable(self):
        """Service wraps EquityDBReadError → SOURCE_UNAVAILABLE."""
        f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        f.close()
        path = Path(f.name)
        conn = sqlite3.connect(str(path))
        conn.execute("CREATE TABLE unrelated (id INTEGER)")
        conn.commit()
        conn.close()

        bundle = get_equity_fundamentals("NVDA", db_path=path)
        assert bundle.availability == AvailabilityState.SOURCE_UNAVAILABLE

    def test_empty_db_bundle_is_source_unavailable(self):
        """Completely empty SQLite file must yield SOURCE_UNAVAILABLE."""
        f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        f.close()
        path = Path(f.name)
        conn = sqlite3.connect(str(path))
        conn.commit()
        conn.close()

        bundle = get_equity_fundamentals("NVDA", db_path=path)
        assert bundle.availability == AvailabilityState.SOURCE_UNAVAILABLE


# ══════════════════════════════════════════════════════════════════════════════
# T19 — dividend frequency is Optional[int], not string
# ══════════════════════════════════════════════════════════════════════════════

class TestT19DividendFrequencyInt:
    def test_frequency_is_int_when_present(self):
        def seed(conn):
            _nvda_asset(conn)
            conn.execute(
                "INSERT INTO equity_dividends VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("NVDA", "div-freq-1", 0.25, "USD",
                 "2024-01-01", "2024-01-15", "2024-01-16", "2024-02-01",
                 4, "CASH", "2024-01-02T00:00:00"),
            )

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        divs = repo.get_dividends("NVDA")
        assert len(divs) == 1
        assert divs[0].frequency == 4
        assert isinstance(divs[0].frequency, int), (
            f"frequency must be int, got {type(divs[0].frequency)}"
        )

    def test_frequency_is_none_when_null(self):
        def seed(conn):
            _nvda_asset(conn)
            conn.execute(
                "INSERT INTO equity_dividends VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("NVDA", "div-freq-null", 0.10, "USD",
                 "2024-01-01", "2024-01-15", "2024-01-16", "2024-02-01",
                 None, "CASH", "2024-01-02T00:00:00"),
            )

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        divs = repo.get_dividends("NVDA")
        assert divs[0].frequency is None

    def test_frequency_annual_is_1(self):
        def seed(conn):
            _nvda_asset(conn)
            conn.execute(
                "INSERT INTO equity_dividends VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("NVDA", "div-freq-annual", 1.00, "USD",
                 "2024-01-01", "2024-01-15", "2024-01-16", "2024-02-01",
                 1, "CASH", "2024-01-02T00:00:00"),
            )

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        divs = repo.get_dividends("NVDA")
        assert divs[0].frequency == 1
        assert isinstance(divs[0].frequency, int)

    def test_model_field_type_annotation(self):
        """DividendRecord.frequency must be annotated Optional[int], not Optional[str]."""
        import inspect
        from finco_radar.equity.models import DividendRecord
        hints = {}
        for f in dataclasses.fields(DividendRecord):
            hints[f.name] = f.type
        # The type annotation string must reflect int not str
        freq_type = hints.get("frequency", "")
        assert "str" not in str(freq_type), (
            f"DividendRecord.frequency must be Optional[int], got: {freq_type}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# T20 — derived_source metadata preserved: absent/malformed distinction
# ══════════════════════════════════════════════════════════════════════════════

class TestT20DerivedSourceMetadata:
    def test_derived_source_absent_when_null(self):
        def seed(conn):
            _nvda_asset(conn)
            _insert_snapshot(
                conn, "NVDA", "ttm", "2024-03-31", "hash-t20-null",
                derived_json=None,
            )

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        snap = repo.get_latest_snapshot("NVDA", "ttm")
        assert snap is not None
        assert snap.derived_source.absent is True
        assert snap.derived_source.parse_error is None
        assert snap.derived is None

    def test_derived_source_parse_error_when_malformed(self):
        def seed(conn):
            _nvda_asset(conn)
            _insert_snapshot(
                conn, "NVDA", "ttm", "2024-03-31", "hash-t20-bad",
                derived_json="{bad json!",
            )

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        snap = repo.get_latest_snapshot("NVDA", "ttm")
        assert snap is not None
        assert snap.derived_source.absent is False
        assert snap.derived_source.parse_error is not None
        assert snap.derived is None

    def test_derived_source_available_when_valid(self):
        def seed(conn):
            _nvda_asset(conn)
            _insert_snapshot(
                conn, "NVDA", "ttm", "2024-03-31", "hash-t20-ok",
                derived_json=json.dumps({"revenues": 1000.0}),
            )

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        snap = repo.get_latest_snapshot("NVDA", "ttm")
        assert snap is not None
        assert snap.derived_source.absent is False
        assert snap.derived_source.parse_error is None
        assert snap.derived_source.is_available is True
        assert snap.derived is not None
        assert snap.derived.revenues == 1000.0

    def test_derived_source_wrong_type_yields_parse_error(self):
        """A JSON array is valid JSON but not a dict → parse_error set."""
        def seed(conn):
            _nvda_asset(conn)
            _insert_snapshot(
                conn, "NVDA", "ttm", "2024-03-31", "hash-t20-arr",
                derived_json="[1, 2, 3]",
            )

        path = _make_db(seed)
        repo = EquityFundamentalsRepository(path)
        snap = repo.get_latest_snapshot("NVDA", "ttm")
        assert snap.derived_source.absent is False
        assert snap.derived_source.parse_error is not None
        assert snap.derived is None

    def test_derived_source_field_exists_on_model(self):
        """FinancialSnapshot must have derived_source: JsonField field."""
        from finco_radar.equity.models import FinancialSnapshot, JsonField
        field_names = {f.name for f in dataclasses.fields(FinancialSnapshot)}
        assert "derived_source" in field_names, (
            "FinancialSnapshot must have derived_source field"
        )
        field_map = {f.name: f for f in dataclasses.fields(FinancialSnapshot)}
        assert field_map["derived_source"].type in (
            "JsonField", JsonField,
        ) or "JsonField" in str(field_map["derived_source"].type)


# ══════════════════════════════════════════════════════════════════════════════
# T21 — canonical token symbol: bundle uses DB form, not request casing
# ══════════════════════════════════════════════════════════════════════════════

class TestT21CanonicalTokenSymbol:
    def test_lowercase_request_returns_db_canonical_symbol(self):
        path = _make_db(_nvda_asset)
        bundle = get_equity_fundamentals("nvda", db_path=path)
        assert bundle.robinhood_token_symbol == "NVDA", (
            "bundle.robinhood_token_symbol must be DB canonical form 'NVDA', not 'nvda'"
        )

    def test_mixed_case_request_returns_db_canonical_symbol(self):
        path = _make_db(_nvda_asset)
        bundle = get_equity_fundamentals("NvDa", db_path=path)
        assert bundle.robinhood_token_symbol == "NVDA"

    def test_exact_case_request_returns_db_canonical_symbol(self):
        path = _make_db(_nvda_asset)
        bundle = get_equity_fundamentals("NVDA", db_path=path)
        assert bundle.robinhood_token_symbol == "NVDA"

    def test_not_found_preserves_request_symbol(self):
        """For NOT_FOUND, the request symbol (any casing) is kept in the bundle."""
        path = _make_db(_nvda_asset)
        bundle = get_equity_fundamentals("unknown_token", db_path=path)
        assert bundle.availability == AvailabilityState.NOT_FOUND
        assert bundle.robinhood_token_symbol == "unknown_token"

    def test_canonical_symbol_matches_asset_field(self):
        """bundle.robinhood_token_symbol must equal bundle.asset.robinhood_token_symbol."""
        path = _make_db(_nvda_asset)
        bundle = get_equity_fundamentals("nvda", db_path=path)
        assert bundle.asset is not None
        assert bundle.robinhood_token_symbol == bundle.asset.robinhood_token_symbol
