"""FINCO Yield watchlist foundation (crypto utility V0, Agent C).

The smallest durable watchlist: save / remove / list canonical Yield
opportunities, bound to the EXISTING authenticated user model
(``SessionData.user_id``, the same identifier the wallet-verification
store binds wallets to).  This is watchlist state for future
``yield.alerts`` use — NOT an alert-delivery platform.

Canonical identity rule:
  a watchlist item references a Yield opportunity by its canonical uid
  (``yld_`` + sha-256 of the canonical identity JSON — see
  ``finco_yield.identity``).  Saving resolves the uid through THE one
  bundled Yield registry (``load_bundled_registry``); an unknown uid is a
  typed error.  Display fields (name/ticker/protocol labels) are copied
  from the registry for convenience only and are NEVER identity: no
  ticker, name, symbol, fuzzy or free-text matching exists anywhere in
  this module.

Persistence follows the existing lazy-table convention used by the
wallet-verification store (``app.protocol.wallet_auth``): a narrow
idempotent table in the main application database (``FINCO_DB_PATH``),
``user_id`` keyed exactly like every other per-user table.  Duplicates are
deterministic via the primary key: saving an already-saved item is an
idempotent no-op reporting ``created=False``.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .registry import RegistryError, load_bundled_registry

WATCHLIST_SCHEMA_VERSION = "finco-yield-watchlist-v0"

_UID_PATTERN = re.compile(r"^yld_[0-9a-f]{32}$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS yield_watchlist (
    user_id           TEXT NOT NULL,
    opportunity_uid   TEXT NOT NULL,
    chain_id          INTEGER NOT NULL,
    protocol          TEXT NOT NULL,
    product_type      TEXT NOT NULL,
    contract_address  TEXT NOT NULL,
    display_name      TEXT,
    saved_at          TEXT NOT NULL,
    PRIMARY KEY (user_id, opportunity_uid)
)
"""

_CREATE_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_yield_watchlist_user "
    "ON yield_watchlist(user_id, saved_at DESC)"
)


class WatchlistError(ValueError):
    """Typed watchlist failure. ``REASON`` is a stable uppercase code and is
    always part of the message (assertable, loggable, API-safe)."""

    def __init__(self, reason: str, detail: str | None = None) -> None:
        self.REASON = reason
        message = reason if detail is None else f"{reason}: {detail}"
        super().__init__(message)


class WatchlistOpportunityUnknown(WatchlistError):
    def __init__(self, detail: str = "YIELD_OPPORTUNITY_UID_UNKNOWN") -> None:
        super().__init__("YIELD_OPPORTUNITY_UID_UNKNOWN", detail)


def _db_path() -> str:
    import os
    return os.getenv("FINCO_DB_PATH",
                     str(Path(__file__).resolve().parents[1] / "data" / "finco_runs.db"))


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute(_SCHEMA)
    conn.execute(_CREATE_INDEX)
    conn.commit()
    return conn


def _utc_iso(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("WATCHLIST_CLOCK_MUST_BE_AWARE")
    return value.astimezone(timezone.utc).isoformat()


def _validate_uid(opportunity_uid: str) -> str:
    if not isinstance(opportunity_uid, str) or not _UID_PATTERN.match(opportunity_uid):
        raise WatchlistError(
            "YIELD_OPPORTUNITY_UID_MALFORMED",
            "watchlist identity must be the canonical yld_<32-hex> opportunity uid",
        )
    return opportunity_uid


def save_watchlist_item(user_id: str, opportunity_uid: str, *,
                        now: datetime | None = None) -> dict:
    """Save ONE canonical Yield opportunity for ONE user. Idempotent.

    The uid must resolve in the bundled canonical registry — identity is
    never taken from display text.  Returns a typed result with
    ``created`` False for a deterministic duplicate save.
    """
    if not user_id or not str(user_id).strip():
        raise WatchlistError("WATCHLIST_USER_REQUIRED")
    uid = _validate_uid(opportunity_uid)
    try:
        opportunity = load_bundled_registry().resolve(uid)
    except RegistryError as exc:
        raise WatchlistOpportunityUnknown() from exc

    stamp = _utc_iso(now)
    conn = _connect()
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO yield_watchlist (user_id, opportunity_uid, chain_id, "
                "protocol, product_type, contract_address, display_name, saved_at) "
                "VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(user_id, opportunity_uid) DO NOTHING",
                (str(user_id), opportunity.uid, opportunity.chain_id,
                 opportunity.protocol, opportunity.product_type,
                 opportunity.contract_address, opportunity.name, stamp),
            )
            created = cursor.rowcount == 1
    finally:
        conn.close()
    return {
        "user_id": str(user_id),
        "opportunity_uid": opportunity.uid,
        "chain_id": opportunity.chain_id,
        "protocol": opportunity.protocol,
        "product_type": opportunity.product_type,
        "contract_address": opportunity.contract_address,
        "display_name": opportunity.name,
        "saved_at": stamp,
        "created": created,
    }


def remove_watchlist_item(user_id: str, opportunity_uid: str) -> bool:
    """Remove ONE saved opportunity. Returns True when a row was removed."""
    if not user_id or not str(user_id).strip():
        raise WatchlistError("WATCHLIST_USER_REQUIRED")
    uid = _validate_uid(opportunity_uid)
    conn = _connect()
    try:
        with conn:
            cursor = conn.execute(
                "DELETE FROM yield_watchlist WHERE user_id=? AND opportunity_uid=?",
                (str(user_id), uid),
            )
        return cursor.rowcount == 1
    finally:
        conn.close()


def list_watchlist_items(user_id: str) -> list[dict]:
    """List the user's saved opportunities, newest first. Canonical uids."""
    if not user_id or not str(user_id).strip():
        raise WatchlistError("WATCHLIST_USER_REQUIRED")
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT opportunity_uid, chain_id, protocol, product_type, "
            "contract_address, display_name, saved_at "
            "FROM yield_watchlist WHERE user_id=? ORDER BY saved_at DESC",
            (str(user_id),),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "opportunity_uid": row["opportunity_uid"],
            "chain_id": row["chain_id"],
            "protocol": row["protocol"],
            "product_type": row["product_type"],
            "contract_address": row["contract_address"],
            "display_name": row["display_name"],
            "saved_at": row["saved_at"],
        }
        for row in rows
    ]


def watchlist_contains(user_id: str, opportunity_uid: str) -> bool:
    uid = _validate_uid(opportunity_uid)
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM yield_watchlist WHERE user_id=? AND opportunity_uid=?",
            (str(user_id), uid),
        ).fetchone()
    finally:
        conn.close()
    return row is not None
