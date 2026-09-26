"""SQLite persistence for the FINCO Equity fundamentals database.

Follows the repo's `app/persistence/db.py` conventions: lightweight SQLite,
WAL mode, idempotent schema creation, row_factory=sqlite3.Row.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.getenv(
    "FINCO_EQUITY_DB_PATH", os.path.join(DATA_DIR, "equity_fundamentals.db")
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def payload_hash(raw: object) -> str:
    serialized = json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    _init_schema(conn)
    return conn


@contextmanager
def connect(db_path: str | None = None):
    conn = get_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS equity_assets (
            robinhood_token_symbol TEXT PRIMARY KEY,
            underlying_ticker      TEXT NOT NULL,
            name                   TEXT,
            token_contract_address TEXT,
            chain_network          TEXT,
            underlying_exchange    TEXT,
            cik                    TEXT,
            figi                   TEXT,
            currency               TEXT,
            security_type          TEXT,
            active                 INTEGER NOT NULL DEFAULT 1,
            first_seen_at          TEXT NOT NULL,
            last_seen_at           TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS equity_company_profiles (
            ticker       TEXT NOT NULL,
            cik          TEXT,
            profile_json TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            provider     TEXT NOT NULL,
            source_contract TEXT NOT NULL,
            fetched_at   TEXT NOT NULL,
            PRIMARY KEY (ticker, payload_hash)
        );

        CREATE TABLE IF NOT EXISTS equity_financial_snapshots (
            ticker         TEXT NOT NULL,
            cik            TEXT,
            timeframe      TEXT NOT NULL,
            fiscal_year    TEXT,
            fiscal_quarter TEXT,
            period_end     TEXT,
            filing_date    TEXT,
            provider       TEXT NOT NULL,
            source_contract TEXT NOT NULL,
            fetched_at     TEXT NOT NULL,
            normalized_at  TEXT NOT NULL,
            payload_hash   TEXT NOT NULL,
            income_statement_json  TEXT NOT NULL DEFAULT '{}',
            balance_sheet_json      TEXT NOT NULL DEFAULT '{}',
            cash_flow_statement_json TEXT NOT NULL DEFAULT '{}',
            derived_json   TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (ticker, timeframe, period_end, fiscal_year, fiscal_quarter, payload_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_eqfin_ticker
            ON equity_financial_snapshots(ticker, timeframe, period_end);

        CREATE TABLE IF NOT EXISTS equity_dividends (
            ticker          TEXT NOT NULL,
            external_id     TEXT NOT NULL,
            cash_amount     REAL,
            currency        TEXT,
            declaration_date TEXT,
            ex_dividend_date TEXT,
            record_date     TEXT,
            pay_date        TEXT,
            frequency       INTEGER,
            dividend_type   TEXT,
            first_seen_at   TEXT NOT NULL,
            PRIMARY KEY (ticker, external_id)
        );

        CREATE TABLE IF NOT EXISTS equity_splits (
            ticker         TEXT NOT NULL,
            external_id    TEXT NOT NULL,
            execution_date TEXT,
            split_from     REAL,
            split_to       REAL,
            first_seen_at  TEXT NOT NULL,
            PRIMARY KEY (ticker, external_id)
        );

        CREATE TABLE IF NOT EXISTS equity_source_lineage (
            lineage_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker         TEXT,
            stage          TEXT NOT NULL,
            provider       TEXT NOT NULL,
            source_contract TEXT NOT NULL,
            endpoint       TEXT NOT NULL,
            payload_hash   TEXT NOT NULL,
            raw_payload_json TEXT,      -- optional raw blob (scrubbed of secrets)
            normalized_ref  TEXT,       -- reference to canonical rows (e.g. snapshot PK)
            fetched_at     TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_lineage_ticker
            ON equity_source_lineage(ticker, stage, fetched_at);

        CREATE TABLE IF NOT EXISTS equity_ingestion_runs (
            run_key      TEXT PRIMARY KEY,   -- '{stage}:{ticker}'
            stage        TEXT NOT NULL,
            ticker       TEXT,
            status       TEXT NOT NULL,      -- pending | done | failed | skipped
            attempts     INTEGER NOT NULL DEFAULT 0,
            detail       TEXT,
            updated_at   TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_runs_stage ON equity_ingestion_runs(stage, status);
        """
    )
