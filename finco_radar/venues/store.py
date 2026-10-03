"""Append-only SQLite store for normalized cross-venue market observations.

Immutability contract:
  - rows are keyed by the deterministic content digest;
  - INSERT-only: the same canonical observation deduplicates (no-op), a
    changed evidence value becomes a NEW row;
  - there is no UPDATE/DELETE path for historical evidence;
  - missing numerics persist as NULL (never 0); decimal strings round-trip
    exactly.

Clock semantics: ``ts`` is the source evidence timestamp, ``collected_at``
the FINCO collection instant.  They are stored and queried separately and
never substituted for one another.

Default location follows the existing Radar SQLite convention
(``data/`` beside the package, overridable via FINCO_VENUE_DB_PATH).
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from finco_radar.venues.models import InstrumentIdentity
from finco_radar.venues.observations import (
    FreshnessState,
    MarketObservation,
    ObservationStatus,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_observations (
    digest              TEXT PRIMARY KEY,
    ts                  TEXT,
    collected_at        TEXT NOT NULL,
    canonical_asset_id  TEXT NOT NULL,
    venue_id            TEXT NOT NULL,
    instrument_id       TEXT NOT NULL,
    instrument_type     TEXT NOT NULL,
    price               TEXT,
    reference_price     TEXT,
    basis_bps           TEXT,
    volume_24h          TEXT,
    open_interest       TEXT,
    funding_rate        TEXT,
    source              TEXT NOT NULL,
    freshness_state     TEXT NOT NULL,
    observation_status  TEXT NOT NULL,
    payload             TEXT NOT NULL
)
"""

# Ordering-clock expression indexes: the generic latest reads order by
# COALESCE(ts, collected_at) (ts is nullable), which a plain (…, ts) index
# cannot serve.  Benchmark (1.55M rows) showed ~1s latest reads without
# these; with them, raw indexed reads remain sufficient — no rollups.
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_market_obs_asset_ts "
    "ON market_observations (canonical_asset_id, ts)",
    "CREATE INDEX IF NOT EXISTS idx_market_obs_venue_ts "
    "ON market_observations (venue_id, ts)",
    "CREATE INDEX IF NOT EXISTS idx_market_obs_instrument_ts "
    "ON market_observations (instrument_id, ts)",
    "CREATE INDEX IF NOT EXISTS idx_market_obs_instrument_order "
    "ON market_observations (instrument_id, "
    "COALESCE(ts, collected_at) DESC, collected_at DESC, digest DESC)",
    "CREATE INDEX IF NOT EXISTS idx_market_obs_asset_order "
    "ON market_observations (canonical_asset_id, "
    "COALESCE(ts, collected_at) DESC, collected_at DESC, digest DESC)",
    "CREATE INDEX IF NOT EXISTS idx_market_obs_venue_instrument_order "
    "ON market_observations (venue_id, instrument_id, "
    "COALESCE(ts, collected_at) DESC, collected_at DESC, digest DESC)",
)

_COLUMNS = ("digest, ts, collected_at, canonical_asset_id, venue_id, "
            "instrument_id, instrument_type, price, reference_price, "
            "basis_bps, volume_24h, open_interest, funding_rate, source, "
            "freshness_state, observation_status, payload")

# Generic "latest collected usable observation" ordering: an explicitly
# derived internal clock (COALESCE(ts, collected_at)) used ONLY for
# ordering — provenance returned to callers still exposes ts=None when the
# source had no source timestamp.
_ORDER = "ORDER BY COALESCE(ts, collected_at) DESC, collected_at DESC, digest DESC"


def default_db_path() -> str:
    return os.getenv(
        "FINCO_VENUE_DB_PATH",
        str(Path(__file__).resolve().parents[1] / "data" / "venues_market_observations.db"))


def _as_str(value) -> str:
    return str(value.value) if hasattr(value, "value") else str(value)


class VenueMarketStore:
    """Append-only observation store (read/write API, no UI, no HTTP)."""

    def __init__(self, path: str | Path | None = None):
        self.path = str(path or default_db_path())
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _ensure_schema(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.execute(_SCHEMA)
            for index in _INDEXES:
                conn.execute(index)
            conn.commit()
        finally:
            conn.close()

    # ── write ─────────────────────────────────────────────────────────────
    def append_observation(self, observation: MarketObservation) -> tuple[str, bool]:
        """Append one observation.  Returns (digest, created).

        The same canonical content (same digest) is a deterministic no-op;
        changed evidence is a new row.  Historical rows are never mutated.
        """
        digest = observation.resolved_digest()
        conn = self._connect()
        try:
            exists = conn.execute(
                "SELECT 1 FROM market_observations WHERE digest=?",
                (digest,)).fetchone()
            if exists is not None:
                return digest, False
            payload = observation.payload
            conn.execute(
                f"INSERT INTO market_observations ({_COLUMNS}) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (digest,
                 observation.ts,
                 observation.collected_at,
                 observation.canonical_asset_id.upper(),
                 observation.venue_id,
                 observation.instrument_id,
                 observation.instrument_type,
                 observation.price,
                 observation.reference_price,
                 observation.basis_bps,
                 observation.volume_24h,
                 observation.open_interest,
                 observation.funding_rate,
                 observation.source,
                 _as_str(observation.freshness_state),
                 _as_str(observation.observation_status),
                 _as_str(payload) if isinstance(payload, str) else __import__("json").dumps(
                     payload, sort_keys=True, separators=(",", ":"))))
            conn.commit()
            return digest, True
        finally:
            conn.close()

    def append_many(
            self, observations) -> list[tuple[str, bool]]:
        return [self.append_observation(observation)
                for observation in observations]

    def append_many_batched(self, observations) -> list[tuple[str, bool]]:
        """Batch append over ONE connection/transaction (collector path).

        Dedupe uses the digest PRIMARY KEY via INSERT OR IGNORE inside the
        transaction — the historical digest universe is never pre-loaded
        into Python (O(batch), not O(total history)).  Rows immutable; no
        UPDATE path.
        """
        import json as _json
        created: list[tuple[str, bool]] = []
        conn = self._connect()
        try:
            for observation in observations:
                digest = observation.resolved_digest()
                payload = observation.payload
                cursor = conn.execute(
                    f"INSERT OR IGNORE INTO market_observations ({_COLUMNS}) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (digest,
                     observation.ts,
                     observation.collected_at,
                     observation.canonical_asset_id.upper(),
                     observation.venue_id,
                     observation.instrument_id,
                     observation.instrument_type,
                     observation.price,
                     observation.reference_price,
                     observation.basis_bps,
                     observation.volume_24h,
                     observation.open_interest,
                     observation.funding_rate,
                     observation.source,
                     _as_str(observation.freshness_state),
                     _as_str(observation.observation_status),
                     _as_str(payload) if isinstance(payload, str) else _json.dumps(
                         payload, sort_keys=True, separators=(",", ":"))))
                created.append((digest, cursor.rowcount > 0))
            conn.commit()
            return created
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── reads ─────────────────────────────────────────────────────────────
    @staticmethod
    def _to_observation(row: sqlite3.Row) -> MarketObservation:
        import json
        payload = json.loads(row["payload"]) if row["payload"] else {}
        return MarketObservation(
            ts=row["ts"],
            collected_at=row["collected_at"],
            canonical_asset_id=row["canonical_asset_id"],
            venue_id=row["venue_id"],
            instrument_id=row["instrument_id"],
            instrument_type=row["instrument_type"],
            price=row["price"],
            reference_price=row["reference_price"],
            basis_bps=row["basis_bps"],
            volume_24h=row["volume_24h"],
            open_interest=row["open_interest"],
            funding_rate=row["funding_rate"],
            source=row["source"],
            freshness_state=FreshnessState(row["freshness_state"]),
            observation_status=ObservationStatus(row["observation_status"]),
            payload=payload,
            digest=row["digest"],
        )

    def get_latest_for_instrument(
            self, instrument_id: str, *,
            venue_id: str | None = None) -> MarketObservation | None:
        query = ("SELECT * FROM market_observations WHERE instrument_id=? "
                 f"{_ORDER} LIMIT 1")
        param: tuple = (instrument_id,)
        if venue_id is not None:
            query = ("SELECT * FROM market_observations WHERE instrument_id=? "
                     "AND venue_id=? " + _ORDER + " LIMIT 1")
            param = (instrument_id, venue_id)
        conn = self._connect()
        try:
            row = conn.execute(query, param).fetchone()
        finally:
            conn.close()
        return self._to_observation(row) if row is not None else None

    def get_latest_for_underlying(
            self, canonical_asset_id: str, *,
            venue_id: str | None = None) -> MarketObservation | None:
        symbol = canonical_asset_id.upper()
        query = ("SELECT * FROM market_observations WHERE canonical_asset_id=? "
                 f"{_ORDER} LIMIT 1")
        param: tuple = (symbol,)
        if venue_id is not None:
            query = ("SELECT * FROM market_observations WHERE canonical_asset_id=? "
                     "AND venue_id=? " + _ORDER + " LIMIT 1")
            param = (symbol, venue_id)
        conn = self._connect()
        try:
            row = conn.execute(query, param).fetchone()
        finally:
            conn.close()
        return self._to_observation(row) if row is not None else None

    def get_window_for_instrument(
            self, instrument_id: str, *, since: datetime,
            until: datetime | None = None,
            venue_id: str | None = None) -> list[MarketObservation]:
        """SOURCE-EVIDENCE time window: rows without a provider source
        timestamp (ts IS NULL) are excluded — collected_at is never
        silently presented as provider evidence."""
        until = until or datetime.now(timezone.utc)
        query = ("SELECT * FROM market_observations WHERE instrument_id=? "
                 "AND ts IS NOT NULL AND ts>=? AND ts<=?")
        params: list = [instrument_id, since.isoformat(), until.isoformat()]
        if venue_id is not None:
            query += " AND venue_id=?"
            params.append(venue_id)
        query += " ORDER BY ts ASC, collected_at ASC, digest ASC"
        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()
        return [self._to_observation(row) for row in rows]

    def get_window_for_underlying(
            self, canonical_asset_id: str, *, since: datetime,
            until: datetime | None = None,
            venue_id: str | None = None) -> list[MarketObservation]:
        """SOURCE-EVIDENCE time window (ts IS NOT NULL) — see
        get_window_for_instrument for the provenance rule."""
        until = until or datetime.now(timezone.utc)
        query = ("SELECT * FROM market_observations WHERE canonical_asset_id=? "
                 "AND ts IS NOT NULL AND ts>=? AND ts<=?")
        params: list = [canonical_asset_id.upper(), since.isoformat(),
                        until.isoformat()]
        if venue_id is not None:
            query += " AND venue_id=?"
            params.append(venue_id)
        query += " ORDER BY ts ASC, collected_at ASC, digest ASC"
        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()
        return [self._to_observation(row) for row in rows]

    def get_latest_at_or_before_for_instrument(
            self, instrument_id: str, *, before: datetime,
            venue_id: str | None = None) -> MarketObservation | None:
        """Latest SOURCE-TIMESTAMPED row at or before a cutoff.

        collected_at never substitutes for missing provider time. This is
        the canonical baseline read used by 24h/7d Tokenized intelligence.
        """
        if before.tzinfo is None or before.utcoffset() is None:
            raise ValueError("before must be timezone-aware")
        query = (
            "SELECT * FROM market_observations WHERE instrument_id=? "
            "AND ts IS NOT NULL AND ts<=?"
        )
        params: list = [instrument_id, before.isoformat()]
        if venue_id is not None:
            query += " AND venue_id=?"
            params.append(venue_id)
        query += " ORDER BY ts DESC, collected_at DESC, digest DESC LIMIT 1"
        conn = self._connect()
        try:
            row = conn.execute(query, params).fetchone()
        finally:
            conn.close()
        return self._to_observation(row) if row is not None else None

    def list_latest_by_venue(self, venue_id: str) -> list[MarketObservation]:
        """Exactly ONE deterministic row per exact venue instrument, using
        the derived ordering clock with the digest as the final
        tie-breaker (timestamp ties cannot produce duplicate latest rows)."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT o.* FROM market_observations o "
                "JOIN (SELECT instrument_id, "
                "             MAX(COALESCE(ts, collected_at) || '|' || "
                "                 collected_at || '|' || digest) AS top "
                "      FROM market_observations WHERE venue_id=? "
                "      GROUP BY instrument_id) t "
                "ON o.instrument_id=t.instrument_id "
                " AND (COALESCE(o.ts, o.collected_at) || '|' || o.collected_at "
                "      || '|' || o.digest)=t.top "
                "WHERE o.venue_id=? "
                "ORDER BY o.canonical_asset_id ASC, o.instrument_id ASC",
                (venue_id, venue_id)).fetchall()
        finally:
            conn.close()
        return [self._to_observation(row) for row in rows]

    def count(self, *, venue_id: str | None = None) -> int:
        conn = self._connect()
        try:
            if venue_id is None:
                return conn.execute(
                    "SELECT COUNT(*) AS n FROM market_observations").fetchone()["n"]
            return conn.execute(
                "SELECT COUNT(*) AS n FROM market_observations WHERE venue_id=?",
                (venue_id,)).fetchone()["n"]
        finally:
            conn.close()


def make_identity(canonical_asset_id: str, venue_id: str,
                  instrument_id: str, instrument_type: str) -> InstrumentIdentity:
    return InstrumentIdentity(
        canonical_asset_id=canonical_asset_id, venue_id=venue_id,
        instrument_id=instrument_id, instrument_type=instrument_type)
