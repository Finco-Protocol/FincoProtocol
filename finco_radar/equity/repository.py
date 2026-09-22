"""Read-only SQLite repository for equity fundamentals.

The database is opened with sqlite3 URI mode=ro so the OS-level file descriptor
is read-only.  PRAGMA query_only=ON is applied as defence-in-depth.

Mode selection (FINCO_EQUITY_FUNDAMENTALS_DB_MODE):
  snapshot — WAL-checkpointed standalone export.  Opens with mode=ro&immutable=1.
             No WAL/SHM creation; no source-directory write permission needed.
  live     — Live WAL DB updated by an ingestion process.  Opens with mode=ro only.
             Standard WAL/SHM semantics; source directory must be writable.

Never CREATEs, INSERTs, UPDATEs, DELETEs, or ALTERs the source DB.
Never creates an empty database if the path is wrong.

Snapshot selection tie-break rule (documented here and tested in T3/T4/T5):
  Primary:    period_end        DESC   (latest economic period)
  Secondary:  filing_date       DESC   (most-recently filed revision)
  Tertiary:   normalized_at     DESC   (most-recently normalised)
  Quaternary: fetched_at        DESC   (most-recently fetched)
  Quinary:    payload_hash      ASC    (deterministic stable tie-break)

For get_financial_history a window function partitions by (ticker, timeframe,
period_end) applying the same order; only the top-ranked row per period is
returned, then results are ordered by period_end DESC.

Company profile selection:
  Primary:    fetched_at        DESC
  Secondary:  payload_hash      ASC
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List, Optional
from urllib.parse import quote as _urlquote

from .config import validate_db_mode
from .models import (
    CompanyProfile,
    DerivedFundamentals,
    DividendRecord,
    EquityAssetIdentity,
    FinancialSnapshot,
    JsonField,
    SourceLineage,
    SplitRecord,
)


class EquityDBReadError(RuntimeError):
    """Raised when the DB file exists but cannot be opened or queried."""


# ── URI builder ───────────────────────────────────────────────────────────────

def _build_uri(path: Path, mode: str) -> str:
    """Build a SQLite URI for the given path and mode.

    snapshot → mode=ro&immutable=1 (bypasses WAL/SHM; safe for read-only dirs)
    live     → mode=ro             (standard WAL semantics)
    """
    encoded = _urlquote(str(path), safe="/:")
    if mode == "snapshot":
        return f"file:{encoded}?mode=ro&immutable=1"
    return f"file:{encoded}?mode=ro"


# ── JSON helpers ──────────────────────────────────────────────────────────────

def _parse_json_field(raw: Optional[str]) -> JsonField:
    """Parse a DB JSON column into a JsonField.

    Distinguishes absent (NULL/empty) from malformed (present but invalid).
    Never silently returns {} for malformed input.
    """
    if raw is None or not raw.strip():
        return JsonField(value=None, absent=True, parse_error=None)
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return JsonField(
                value=None,
                absent=False,
                parse_error=f"Expected JSON object, got {type(parsed).__name__}",
            )
        return JsonField(value=parsed, absent=False, parse_error=None)
    except json.JSONDecodeError as exc:
        return JsonField(value=None, absent=False, parse_error=str(exc))


def _get_float(d: Optional[dict], key: str) -> Optional[float]:
    """Extract an optional numeric value, preserving 0.0 as distinct from None."""
    if d is None or key not in d:
        return None
    v = d[key]
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _build_derived(raw_field: JsonField) -> Optional[DerivedFundamentals]:
    if not raw_field.is_available:
        return None
    d = raw_field.value
    return DerivedFundamentals(
        revenues=_get_float(d, "revenues"),
        revenue_growth=_get_float(d, "revenue_growth"),
        gross_margin=_get_float(d, "gross_margin"),
        ebit_margin=_get_float(d, "ebit_margin"),
        ebitda_margin=_get_float(d, "ebitda_margin"),
        net_margin=_get_float(d, "net_margin"),
        free_cash_flow=_get_float(d, "free_cash_flow"),
        fcf_margin=_get_float(d, "fcf_margin"),
        return_on_equity=_get_float(d, "return_on_equity"),
        net_debt=_get_float(d, "net_debt"),
        debt_to_equity=_get_float(d, "debt_to_equity"),
        source_field=raw_field,
    )


# ── row converters ────────────────────────────────────────────────────────────

_SNAPSHOT_COLS = (
    "ticker", "cik", "timeframe", "fiscal_year", "fiscal_quarter", "period_end",
    "filing_date", "provider", "source_contract", "fetched_at", "normalized_at",
    "payload_hash", "income_statement_json", "balance_sheet_json",
    "cash_flow_statement_json", "derived_json",
)


def _row_to_snapshot(row) -> FinancialSnapshot:
    d = dict(zip(_SNAPSHOT_COLS, row))
    income = _parse_json_field(d.get("income_statement_json"))
    balance = _parse_json_field(d.get("balance_sheet_json"))
    cashflow = _parse_json_field(d.get("cash_flow_statement_json"))
    derived_field = _parse_json_field(d.get("derived_json"))
    derived = _build_derived(derived_field)
    return FinancialSnapshot(
        ticker=d["ticker"],
        cik=d.get("cik"),
        timeframe=d["timeframe"],
        fiscal_year=d.get("fiscal_year"),
        fiscal_quarter=d.get("fiscal_quarter"),
        period_end=d.get("period_end"),
        filing_date=d.get("filing_date"),
        provider=d.get("provider"),
        source_contract=d.get("source_contract"),
        fetched_at=d.get("fetched_at"),
        normalized_at=d.get("normalized_at"),
        payload_hash=d.get("payload_hash"),
        income_statement=income,
        balance_sheet=balance,
        cash_flow_statement=cashflow,
        derived_source=derived_field,
        derived=derived,
    )


# ── connection context ────────────────────────────────────────────────────────

@contextmanager
def open_db(path: Path, mode: str = "snapshot") -> Iterator[sqlite3.Connection]:
    """Open the equity fundamentals DB in read-only mode.

    mode='snapshot' adds immutable=1 to bypass WAL/SHM (safe for read-only dirs).
    mode='live' opens with mode=ro only; WAL/SHM semantics apply.
    PRAGMA query_only=ON applied as defence-in-depth.
    Never creates the file if absent.
    Raises EquityDBModeError immediately for any unrecognised mode — does NOT
    silently fall through to live behaviour.
    """
    mode = validate_db_mode(mode)
    uri = _build_uri(path, mode)
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError as exc:
        raise EquityDBReadError(
            f"Cannot open equity fundamentals DB at {path}: {exc}"
        ) from exc
    try:
        conn.execute("PRAGMA query_only=ON")
        yield conn
    finally:
        conn.close()


# ── bound read session ────────────────────────────────────────────────────────

class BoundReadSession:
    """All repository reads for one bundle share this single connection.

    The connection is opened with BEGIN (deferred) so SQLite takes a WAL
    read snapshot at the first read; writer commits within this transaction
    are invisible until the transaction ends.  All OperationalError /
    DatabaseError from queries are wrapped as EquityDBReadError.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def _q(self, sql: str, params: tuple = ()) -> list:
        try:
            return self._conn.execute(sql, params).fetchall()
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as exc:
            raise EquityDBReadError(f"Query failed: {exc}") from exc

    def _q1(self, sql: str, params: tuple = ()) -> Optional[tuple]:
        try:
            return self._conn.execute(sql, params).fetchone()
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as exc:
            raise EquityDBReadError(f"Query failed: {exc}") from exc

    # ── asset identity ────────────────────────────────────────────────────────

    def get_asset(self, robinhood_token_symbol: str) -> Optional[EquityAssetIdentity]:
        row = self._q1(
            """
            SELECT robinhood_token_symbol, underlying_ticker, name,
                   token_contract_address, chain_network, underlying_exchange,
                   cik, figi, currency, security_type, active,
                   first_seen_at, last_seen_at
            FROM equity_assets
            WHERE UPPER(robinhood_token_symbol) = UPPER(?)
            """,
            (robinhood_token_symbol,),
        )
        if row is None:
            return None
        return EquityAssetIdentity(
            robinhood_token_symbol=row[0],
            underlying_ticker=row[1],
            name=row[2],
            token_contract_address=row[3],
            chain_network=row[4],
            underlying_exchange=row[5],
            cik=row[6],
            figi=row[7],
            currency=row[8],
            security_type=row[9],
            active=bool(row[10]),
            first_seen_at=row[11],
            last_seen_at=row[12],
        )

    def list_active_assets(self) -> List[EquityAssetIdentity]:
        rows = self._q(
            """
            SELECT robinhood_token_symbol, underlying_ticker, name,
                   token_contract_address, chain_network, underlying_exchange,
                   cik, figi, currency, security_type, active,
                   first_seen_at, last_seen_at
            FROM equity_assets
            WHERE active = 1
            ORDER BY robinhood_token_symbol ASC
            """
        )
        return [
            EquityAssetIdentity(
                robinhood_token_symbol=r[0],
                underlying_ticker=r[1],
                name=r[2],
                token_contract_address=r[3],
                chain_network=r[4],
                underlying_exchange=r[5],
                cik=r[6],
                figi=r[7],
                currency=r[8],
                security_type=r[9],
                active=bool(r[10]),
                first_seen_at=r[11],
                last_seen_at=r[12],
            )
            for r in rows
        ]

    # ── company profile ───────────────────────────────────────────────────────

    def get_latest_profile(self, ticker: str) -> Optional[CompanyProfile]:
        row = self._q1(
            """
            SELECT ticker, cik, profile_json, payload_hash,
                   provider, source_contract, fetched_at
            FROM equity_company_profiles
            WHERE ticker = ?
            ORDER BY fetched_at DESC, payload_hash ASC
            LIMIT 1
            """,
            (ticker,),
        )
        if row is None:
            return None
        return CompanyProfile(
            ticker=row[0],
            cik=row[1],
            provider=row[4],
            source_contract=row[5],
            payload_hash=row[3],
            fetched_at=row[6],
            profile=_parse_json_field(row[2]),
        )

    # ── financial snapshots ───────────────────────────────────────────────────

    def get_latest_snapshot(
        self, ticker: str, timeframe: str
    ) -> Optional[FinancialSnapshot]:
        row = self._q1(
            """
            SELECT ticker, cik, timeframe, fiscal_year, fiscal_quarter,
                   period_end, filing_date, provider, source_contract,
                   fetched_at, normalized_at, payload_hash,
                   income_statement_json, balance_sheet_json,
                   cash_flow_statement_json, derived_json
            FROM equity_financial_snapshots
            WHERE ticker = ? AND timeframe = ?
            ORDER BY period_end    DESC,
                     filing_date   DESC,
                     normalized_at DESC,
                     fetched_at    DESC,
                     payload_hash  ASC
            LIMIT 1
            """,
            (ticker, timeframe),
        )
        if row is None:
            return None
        return _row_to_snapshot(row)

    def get_financial_history(
        self,
        ticker: str,
        timeframe: str,
        limit: int = 20,
    ) -> List[FinancialSnapshot]:
        rows = self._q(
            """
            SELECT ticker, cik, timeframe, fiscal_year, fiscal_quarter,
                   period_end, filing_date, provider, source_contract,
                   fetched_at, normalized_at, payload_hash,
                   income_statement_json, balance_sheet_json,
                   cash_flow_statement_json, derived_json
            FROM (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY ticker, timeframe, period_end
                           ORDER BY filing_date   DESC,
                                    normalized_at DESC,
                                    fetched_at    DESC,
                                    payload_hash  ASC
                       ) AS rn
                FROM equity_financial_snapshots
                WHERE ticker = ? AND timeframe = ?
            )
            WHERE rn = 1
            ORDER BY period_end DESC
            LIMIT ?
            """,
            (ticker, timeframe, limit),
        )
        return [_row_to_snapshot(r) for r in rows]

    # ── corporate actions ─────────────────────────────────────────────────────

    def get_dividends(self, ticker: str, limit: int = 20) -> List[DividendRecord]:
        rows = self._q(
            """
            SELECT ticker, external_id, cash_amount, currency,
                   declaration_date, ex_dividend_date, record_date,
                   pay_date, frequency, dividend_type, first_seen_at
            FROM equity_dividends
            WHERE ticker = ?
            ORDER BY COALESCE(pay_date, ex_dividend_date, declaration_date) DESC,
                     external_id ASC
            LIMIT ?
            """,
            (ticker, limit),
        )
        return [
            DividendRecord(
                ticker=r[0], external_id=r[1], cash_amount=r[2],
                currency=r[3], declaration_date=r[4], ex_dividend_date=r[5],
                record_date=r[6], pay_date=r[7],
                frequency=int(r[8]) if r[8] is not None else None,
                dividend_type=r[9], first_seen_at=r[10],
            )
            for r in rows
        ]

    def get_splits(self, ticker: str, limit: int = 10) -> List[SplitRecord]:
        rows = self._q(
            """
            SELECT ticker, external_id, execution_date,
                   split_from, split_to, first_seen_at
            FROM equity_splits
            WHERE ticker = ?
            ORDER BY execution_date DESC, external_id ASC
            LIMIT ?
            """,
            (ticker, limit),
        )
        return [
            SplitRecord(
                ticker=r[0], external_id=r[1], execution_date=r[2],
                split_from=r[3], split_to=r[4], first_seen_at=r[5],
            )
            for r in rows
        ]

    # ── lineage ───────────────────────────────────────────────────────────────

    def get_lineage(
        self,
        ticker: str,
        payload_hash: Optional[str] = None,
        limit: int = 10,
    ) -> List[SourceLineage]:
        if payload_hash is not None:
            rows = self._q(
                """
                SELECT lineage_id, ticker, stage, provider, source_contract,
                       endpoint, payload_hash, normalized_ref, fetched_at
                FROM equity_source_lineage
                WHERE ticker = ? AND payload_hash = ?
                ORDER BY fetched_at DESC, lineage_id ASC
                LIMIT ?
                """,
                (ticker, payload_hash, limit),
            )
        else:
            rows = self._q(
                """
                SELECT lineage_id, ticker, stage, provider, source_contract,
                       endpoint, payload_hash, normalized_ref, fetched_at
                FROM equity_source_lineage
                WHERE ticker = ?
                ORDER BY fetched_at DESC, lineage_id ASC
                LIMIT ?
                """,
                (ticker, limit),
            )
        return [
            SourceLineage(
                lineage_id=r[0], ticker=r[1], stage=r[2], provider=r[3],
                source_contract=r[4], endpoint=r[5], payload_hash=r[6],
                normalized_ref=r[7], fetched_at=r[8],
            )
            for r in rows
        ]


# ── repository ────────────────────────────────────────────────────────────────

class EquityFundamentalsRepository:
    """Read-only data-access boundary for equity_fundamentals.db."""

    def __init__(self, db_path: Path, mode: str = "snapshot") -> None:
        self._path = db_path
        self._mode = validate_db_mode(mode)  # raises EquityDBModeError on invalid

    @contextmanager
    def read_session(self) -> Iterator[BoundReadSession]:
        """Open one connection, begin a deferred transaction, yield a BoundReadSession.

        All queries within the session share a single WAL read snapshot.
        The transaction is always rolled back on exit (read-only; nothing to commit).
        Wraps open/connect failures as EquityDBReadError.
        """
        with open_db(self._path, self._mode) as conn:
            try:
                conn.execute("BEGIN DEFERRED")
            except (sqlite3.OperationalError, sqlite3.DatabaseError) as exc:
                raise EquityDBReadError(f"Cannot begin read transaction: {exc}") from exc
            try:
                yield BoundReadSession(conn)
            finally:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass

    # ── convenience pass-through methods (single-call use cases) ─────────────

    def get_asset(self, robinhood_token_symbol: str) -> Optional[EquityAssetIdentity]:
        with self.read_session() as s:
            return s.get_asset(robinhood_token_symbol)

    def list_active_assets(self) -> List[EquityAssetIdentity]:
        with self.read_session() as s:
            return s.list_active_assets()

    def get_latest_profile(self, ticker: str) -> Optional[CompanyProfile]:
        with self.read_session() as s:
            return s.get_latest_profile(ticker)

    def get_latest_snapshot(
        self, ticker: str, timeframe: str
    ) -> Optional[FinancialSnapshot]:
        with self.read_session() as s:
            return s.get_latest_snapshot(ticker, timeframe)

    def get_financial_history(
        self,
        ticker: str,
        timeframe: str,
        limit: int = 20,
    ) -> List[FinancialSnapshot]:
        with self.read_session() as s:
            return s.get_financial_history(ticker, timeframe, limit)

    def get_dividends(self, ticker: str, limit: int = 20) -> List[DividendRecord]:
        with self.read_session() as s:
            return s.get_dividends(ticker, limit)

    def get_splits(self, ticker: str, limit: int = 10) -> List[SplitRecord]:
        with self.read_session() as s:
            return s.get_splits(ticker, limit)

    def get_lineage(
        self,
        ticker: str,
        payload_hash: Optional[str] = None,
        limit: int = 10,
    ) -> List[SourceLineage]:
        with self.read_session() as s:
            return s.get_lineage(ticker, payload_hash=payload_hash, limit=limit)
