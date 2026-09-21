"""Persistence repository for the FINCO Equity fundamentals database."""
from __future__ import annotations

import json
import sqlite3
from typing import Iterable, Optional, Sequence

from .db import payload_hash, utcnow
from .domain import CompanyProfile, Dividend, EquityAsset, EquitySnapshot, Split
from .domain import (PROVIDER_MASSIVE, SOURCE_CONTRACT_MASSIVE_LEGACY,
                     derive_fundamentals)


# -- equity_assets -----------------------------------------------------------

def upsert_asset(conn: sqlite3.Connection, asset: EquityAsset) -> None:
    now = utcnow()
    conn.execute(
        """
        INSERT INTO equity_assets (
            robinhood_token_symbol, underlying_ticker, name,
            token_contract_address, chain_network, underlying_exchange,
            cik, figi, currency, security_type, active,
            first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(robinhood_token_symbol) DO UPDATE SET
            underlying_ticker=excluded.underlying_ticker,
            name=COALESCE(excluded.name, name),
            token_contract_address=COALESCE(excluded.token_contract_address, token_contract_address),
            chain_network=COALESCE(excluded.chain_network, chain_network),
            cik=COALESCE(excluded.cik, cik),
            figi=COALESCE(excluded.figi, figi),
            currency=COALESCE(excluded.currency, currency),
            security_type=COALESCE(excluded.security_type, security_type),
            active=excluded.active,
            last_seen_at=excluded.last_seen_at
        """,
        (
            asset.robinhood_token_symbol, asset.underlying_ticker, asset.name,
            asset.token_contract_address, asset.chain_network, asset.underlying_exchange,
            asset.cik, asset.figi, asset.currency, asset.security_type,
            1 if asset.active else 0, now, now,
        ),
    )


def mark_disappeared_inactive(conn: sqlite3.Connection, seen_symbols: Sequence[str]) -> int:
    """Assets present in DB but absent from the live registry -> active=0."""
    rows = conn.execute(
        "SELECT robinhood_token_symbol FROM equity_assets WHERE active = 1"
    ).fetchall()
    seen = set(seen_symbols)
    disappeared = 0
    for row in rows:
        symbol = row["robinhood_token_symbol"]
        if symbol not in seen:
            conn.execute(
                "UPDATE equity_assets SET active = 0, last_seen_at = ? "
                "WHERE robinhood_token_symbol = ?",
                (utcnow(), symbol),
            )
            disappeared += 1
    return disappeared


def active_tickers(conn: sqlite3.Connection) -> list[str]:
    return [
        r["underlying_ticker"]
        for r in conn.execute(
            "SELECT underlying_ticker FROM equity_assets "
            "WHERE active = 1 ORDER BY robinhood_token_symbol"
        )
    ]


# -- profiles ----------------------------------------------------------------

def profile_freshness(conn: sqlite3.Connection, ticker: str) -> Optional[str]:
    row = conn.execute(
        "SELECT MAX(fetched_at) AS f FROM equity_company_profiles WHERE ticker = ?",
        (ticker,),
    ).fetchone()
    return row["f"] if row else None


def upsert_profile(
    conn: sqlite3.Connection, profile: CompanyProfile, raw: object
) -> None:
    p_hash = payload_hash(raw)
    conn.execute(
        """
        INSERT OR IGNORE INTO equity_company_profiles
            (ticker, cik, profile_json, payload_hash, provider, source_contract, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            profile.ticker, profile.cik, json.dumps(profile.__dict__, default=str),
            p_hash, PROVIDER_MASSIVE, SOURCE_CONTRACT_MASSIVE_LEGACY, utcnow(),
        ),
    )
    _lineage(conn, profile.ticker, "profiles", p_hash)


# -- financial snapshots -----------------------------------------------------

def upsert_snapshots(
    conn: sqlite3.Connection, snapshots: Iterable[EquitySnapshot], raw: object
) -> int:
    p_hash = payload_hash(raw)
    inserted = 0
    for snapshot in snapshots:
        derived = derive_fundamentals(snapshot)
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO equity_financial_snapshots (
                ticker, cik, timeframe, fiscal_year, fiscal_quarter, period_end,
                filing_date, provider, source_contract, fetched_at, normalized_at,
                payload_hash, income_statement_json, balance_sheet_json,
                cash_flow_statement_json, derived_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.ticker, snapshot.cik, snapshot.timeframe,
                snapshot.fiscal_year or "", snapshot.fiscal_quarter or "",
                snapshot.period_end or "",
                snapshot.filing_date, PROVIDER_MASSIVE, SOURCE_CONTRACT_MASSIVE_LEGACY,
                utcnow(), utcnow(), p_hash,
                json.dumps(snapshot.income_statement),
                json.dumps(snapshot.balance_sheet),
                json.dumps(snapshot.cash_flow_statement),
                json.dumps(derived),
            ),
        )
        inserted += cursor.rowcount or 0
    if inserted:
        first = next(iter(snapshots), None)
        _lineage(conn, first.ticker if first else None, "financials", p_hash)
    return inserted


def has_snapshots(conn: sqlite3.Connection, ticker: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM equity_financial_snapshots WHERE ticker = ? LIMIT 1",
        (ticker,),
    ).fetchone()
    return row is not None


# -- dividends / splits ------------------------------------------------------

def upsert_dividends(conn: sqlite3.Connection, dividends: Iterable[Dividend]) -> int:
    inserted = 0
    now = utcnow()
    for div in dividends:
        external_id = payload_hash(
            {
                "ticker": div.ticker, "ex": div.ex_dividend_date, "pay": div.pay_date,
                "amount": div.cash_amount, "type": div.dividend_type,
            }
        )
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO equity_dividends (
                ticker, external_id, cash_amount, currency, declaration_date,
                ex_dividend_date, record_date, pay_date, frequency, dividend_type,
                first_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                div.ticker, external_id, div.cash_amount, div.currency,
                div.declaration_date, div.ex_dividend_date, div.record_date,
                div.pay_date, div.frequency, div.dividend_type, now,
            ),
        )
        inserted += cursor.rowcount or 0
    return inserted


def upsert_splits(
    conn: sqlite3.Connection, splits: Iterable[Split], raw: object
) -> int:
    p_hash = payload_hash(raw)
    inserted = 0
    now = utcnow()
    for split in splits:
        external_id = payload_hash(
            {"ticker": split.ticker, "date": split.execution_date,
             "from": split.split_from, "to": split.split_to}
        )
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO equity_splits (
                ticker, external_id, execution_date, split_from, split_to, first_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (split.ticker, external_id, split.execution_date,
             split.split_from, split.split_to, now),
        )
        inserted += cursor.rowcount or 0
    if inserted:
        _lineage(conn, splits[0].ticker if isinstance(splits, list) and splits else None,
                 "splits", p_hash)
    return inserted


# -- lineage & checkpoints ---------------------------------------------------

def _lineage(
    conn: sqlite3.Connection,
    ticker: Optional[str],
    stage: str,
    p_hash: str,
    endpoint: str = "",
    raw: object = None,
    normalized_ref: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO equity_source_lineage (
            ticker, stage, provider, source_contract, endpoint, payload_hash,
            raw_payload_json, normalized_ref, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ticker, stage, PROVIDER_MASSIVE, SOURCE_CONTRACT_MASSIVE_LEGACY,
            endpoint, p_hash,
            json.dumps(raw, default=str) if raw is not None else None,
            normalized_ref, utcnow(),
        ),
    )


def lineage_rows(conn: sqlite3.Connection, stage: Optional[str] = None) -> list:
    if stage:
        return conn.execute(
            "SELECT * FROM equity_source_lineage WHERE stage = ? ORDER BY fetched_at",
            (stage,),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM equity_source_lineage ORDER BY fetched_at"
    ).fetchall()


def checkpoint_get(conn: sqlite3.Connection, run_key: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM equity_ingestion_runs WHERE run_key = ?", (run_key,)
    ).fetchone()


def checkpoint_set(
    conn: sqlite3.Connection, run_key: str, stage: str, ticker: Optional[str],
    status: str, detail: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO equity_ingestion_runs (run_key, stage, ticker, status, attempts, detail, updated_at)
        VALUES (?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(run_key) DO UPDATE SET
            status=excluded.status, attempts=attempts + 1,
            detail=excluded.detail, updated_at=excluded.updated_at
        """,
        (run_key, stage, ticker, status, detail, utcnow()),
    )


def stage_stats(conn: sqlite3.Connection, stage: str) -> dict:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM equity_ingestion_runs WHERE stage = ? "
        "GROUP BY status",
        (stage,),
    ).fetchall()
    return {r["status"]: r["n"] for r in rows}
