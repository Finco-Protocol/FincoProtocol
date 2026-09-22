"""E1 equity fundamentals read authority — T1 through T14.

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
    EquityDBNotConfiguredError,
    EquityDBNotFoundError,
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
    frequency TEXT,
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
             "quarterly", "CASH", "2024-09-02T00:00:00"),
        )
        conn.execute(
            "INSERT INTO equity_dividends VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("NVDA", "div-002", 0.0, "USD",
             "2024-06-01", "2024-06-15", "2024-06-16", "2024-07-01",
             "quarterly", "CASH", "2024-06-02T00:00:00"),
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
