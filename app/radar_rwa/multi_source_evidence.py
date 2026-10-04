"""Three independent evidence roles per reviewed Stock Token: MARKET, OFFICIAL_REFERENCE, ORACLE.

MARKET != OFFICIAL_REFERENCE != ORACLE.  Each leg owns its own state, value, source timestamp, collected_at, typed
reason and provenance.  No leg is ever derived from, substituted by, or made current by another leg; a failing leg
never erases the others.  Persistence is append-only, per role (see ``SourceEvidenceStore``).

The legs are built from existing authorities, never re-fetched:
  MARKET             <- ``RLiveResult.onchain``  (Uniswap V3 TWAP x Chainlink USDG/USD, existing R-LIVE authority)
  OFFICIAL_REFERENCE <- ``RLiveResult.authority.underlying`` (existing Robinhood bound reference; NOT duplicated)
  ORACLE             <- ``stock_token_oracle.read_stock_token_oracle`` (per-asset Chainlink Stock Token feed)
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

from finco_radar.authority.contracts import AuthorityState
from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID

from .stock_token_oracle import ORACLE_SOURCE_AUTHORITY, ORACLE_UNIT, OracleObservation

SCHEMA = "FINCO_SOURCE_EVIDENCE_V1"
MARKET_SOURCE_AUTHORITY = "UNISWAP_V3_TWAP_CHAINLINK_USDG_USD"
REFERENCE_SOURCE_AUTHORITY = "ROBINHOOD_STOCK_TOKEN_BOUND_PRICE"
VALUE_UNIT = "USD_PER_STOCK_TOKEN"


class EvidenceRole(str, Enum):
    MARKET = "MARKET"
    OFFICIAL_REFERENCE = "OFFICIAL_REFERENCE"
    ORACLE = "ORACLE"


@dataclass(frozen=True)
class EvidenceLeg:
    canonical_id: str
    role: EvidenceRole
    source_authority: str
    source_instrument: str | None
    state: str                           # AVAILABLE | STALE | UNAVAILABLE | IDENTITY_UNAVAILABLE
    value: Decimal | None
    unit: str
    source_timestamp: datetime | None
    reason: str | None
    evidence: Mapping[str, Any] = field(default_factory=dict)

    @property
    def symbol(self) -> str:             # presentation only, after exact identity is established
        return APPROVED_BY_CANONICAL_ID[self.canonical_id].symbol

    def digest(self) -> str:
        """Content digest over what the SOURCE said. collected_at is excluded so identical evidence dedupes."""
        body = {
            "schema": SCHEMA, "canonical_id": self.canonical_id, "role": self.role.value,
            "source_authority": self.source_authority, "source_instrument": self.source_instrument,
            "value": None if self.value is None else format(self.value, "f"),
            "source_timestamp": self.source_timestamp.isoformat() if self.source_timestamp else None,
            "state": self.state, "reason": self.reason,
        }
        return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _state(value: Any) -> str:
    return str(getattr(value, "value", value))


def market_leg(canonical_id: str, onchain: Any) -> EvidenceLeg:
    """MARKET leg from the existing on-chain observation, independent of the Robinhood reference."""
    policy = APPROVED_BY_CANONICAL_ID[canonical_id]
    evidence = dict(getattr(onchain, "evidence", None) or {})
    return EvidenceLeg(
        canonical_id, EvidenceRole.MARKET, MARKET_SOURCE_AUTHORITY,
        str(evidence.get("pool") or policy.pool.pool_address),
        _state(onchain.state), onchain.price_usd_per_token, VALUE_UNIT, onchain.observed_at,
        onchain.reason, evidence)


def reference_leg(canonical_id: str, underlying: Any | None) -> EvidenceLeg:
    """OFFICIAL_REFERENCE leg from the existing Robinhood bound reference (reused, never re-fetched)."""
    if underlying is None:
        return EvidenceLeg(canonical_id, EvidenceRole.OFFICIAL_REFERENCE, REFERENCE_SOURCE_AUTHORITY,
                           canonical_id, "UNAVAILABLE", None, VALUE_UNIT, None, "REFERENCE_EVIDENCE_UNAVAILABLE")
    return EvidenceLeg(
        canonical_id, EvidenceRole.OFFICIAL_REFERENCE, str(underlying.source or REFERENCE_SOURCE_AUTHORITY),
        canonical_id, _state(underlying.state), underlying.price_usd_per_token, VALUE_UNIT,
        underlying.observed_at, underlying.reason, dict(getattr(underlying, "evidence", None) or {}))


def oracle_leg(canonical_id: str, observation: OracleObservation) -> EvidenceLeg:
    return EvidenceLeg(
        canonical_id, EvidenceRole.ORACLE, ORACLE_SOURCE_AUTHORITY, observation.feed_proxy,
        _state(observation.state), observation.value, ORACLE_UNIT, observation.source_timestamp,
        observation.reason, dict(observation.evidence))


# ── append-only per-role persistence ─────────────────────────────────────────────────────────────
def default_db_path() -> str:
    explicit = os.getenv("FINCO_SOURCE_EVIDENCE_DB_PATH", "").strip()
    if explicit:
        return explicit
    venue = os.getenv("FINCO_VENUE_DB_PATH", "").strip()
    if venue:
        return str(Path(venue).with_name("source_evidence.db"))
    return str(Path(__file__).resolve().parents[2] / "data" / "source_evidence.db")


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS source_evidence (
    seq                 INTEGER PRIMARY KEY AUTOINCREMENT,
    digest              TEXT NOT NULL,
    canonical_id        TEXT NOT NULL,
    canonical_asset_id  TEXT NOT NULL,
    evidence_role       TEXT NOT NULL,
    source_authority    TEXT NOT NULL,
    source_instrument   TEXT,
    value               TEXT,
    unit                TEXT NOT NULL,
    source_timestamp    TEXT,
    collected_at        TEXT NOT NULL,
    state               TEXT NOT NULL,
    reason              TEXT,
    payload             TEXT NOT NULL
)"""
_INDEX_SQL = ("CREATE INDEX IF NOT EXISTS idx_source_evidence_latest ON source_evidence "
              "(canonical_id, evidence_role, seq DESC)")


class SourceEvidenceStore:
    """Append-only. Exact duplicate of the LATEST row of the same (asset, role) is a no-op; any change appends.

    Rows are never updated or deleted, roles never overwrite each other, and nothing is interpolated.
    """

    def __init__(self, path: str | Path | None = None):
        self.path = str(path or default_db_path())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_SCHEMA_SQL)
            conn.execute(_INDEX_SQL)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def append(self, leg: EvidenceLeg, *, collected_at: datetime) -> bool:
        """True when a new row was appended, False when identical to the latest row of this asset+role."""
        if collected_at.tzinfo is None or collected_at.utcoffset() is None:
            raise ValueError("EVIDENCE_COLLECTION_CLOCK_MUST_BE_AWARE")
        digest = leg.digest()
        conn = self._connect()
        try:
            with conn:
                latest = conn.execute(
                    "SELECT digest FROM source_evidence WHERE canonical_id=? AND evidence_role=? "
                    "ORDER BY seq DESC LIMIT 1", (leg.canonical_id, leg.role.value)).fetchone()
                if latest is not None and latest["digest"] == digest:
                    return False
                conn.execute(
                    "INSERT INTO source_evidence (digest, canonical_id, canonical_asset_id, evidence_role, "
                    "source_authority, source_instrument, value, unit, source_timestamp, collected_at, state, "
                    "reason, payload) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (digest, leg.canonical_id, leg.symbol, leg.role.value, leg.source_authority,
                     leg.source_instrument, None if leg.value is None else format(leg.value, "f"), leg.unit,
                     leg.source_timestamp.isoformat() if leg.source_timestamp else None,
                     collected_at.astimezone(timezone.utc).isoformat(), leg.state, leg.reason,
                     json.dumps(dict(leg.evidence), sort_keys=True, default=str)))
                return True
        finally:
            conn.close()

    def latest(self, canonical_id: str, role: EvidenceRole) -> dict | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM source_evidence WHERE canonical_id=? AND evidence_role=? "
                "ORDER BY seq DESC LIMIT 1", (canonical_id, role.value)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def history(self, canonical_id: str, role: EvidenceRole, *, limit: int = 100) -> list[dict]:
        if not 1 <= limit <= 1000:
            raise ValueError("EVIDENCE_HISTORY_LIMIT_INVALID")
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM source_evidence WHERE canonical_id=? AND evidence_role=? "
                "ORDER BY seq DESC LIMIT ?", (canonical_id, role.value, limit)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def count(self) -> int:
        conn = self._connect()
        try:
            return int(conn.execute("SELECT COUNT(*) FROM source_evidence").fetchone()[0])
        finally:
            conn.close()


# ── matrix (pure; no I/O) ────────────────────────────────────────────────────────────────────────
def _age(now: datetime, ts: datetime | None) -> int | None:
    if ts is None:
        return None
    seconds = (now - ts).total_seconds()
    return int(seconds) if seconds >= 0 else None


def _leg_cell(leg: EvidenceLeg | None, now: datetime) -> dict:
    if leg is None:
        return {"state": "UNAVAILABLE", "value": None, "source_timestamp": None, "age_seconds": None,
                "reason": "EVIDENCE_LEG_NOT_COLLECTED", "source_authority": None, "source_instrument": None}
    return {
        "state": leg.state, "value": None if leg.value is None else format(leg.value, "f"),
        "source_timestamp": leg.source_timestamp.isoformat() if leg.source_timestamp else None,
        "age_seconds": _age(now, leg.source_timestamp), "reason": leg.reason,
        "source_authority": leg.source_authority, "source_instrument": leg.source_instrument,
    }


def _comparison(a: EvidenceLeg | None, b: EvidenceLeg | None) -> dict:
    """Basis of a vs b (bps) ONLY when both legs are AVAILABLE with values; otherwise typed non-comparable."""
    if a is None or b is None:
        return {"basis_bps": None, "time_skew_seconds": None, "reason": "LEG_NOT_COLLECTED"}
    if a.state != "AVAILABLE" or b.state != "AVAILABLE":
        return {"basis_bps": None, "time_skew_seconds": None, "reason": "LEG_NOT_AVAILABLE"}
    if a.value is None or b.value is None or b.value <= 0:
        return {"basis_bps": None, "time_skew_seconds": None, "reason": "LEG_VALUE_MISSING"}
    skew = None
    if a.source_timestamp and b.source_timestamp:
        skew = int(abs((a.source_timestamp - b.source_timestamp).total_seconds()))
    return {"basis_bps": format(((a.value / b.value) - 1) * 10000, "f"), "time_skew_seconds": skew, "reason": None}


def build_matrix(legs_by_asset: Mapping[str, Mapping[EvidenceRole, EvidenceLeg]], *, now: datetime,
                 oracle_coverage: Mapping[str, str] | None = None) -> list[dict]:
    """One row for EVERY reviewed asset (a missing asset is never omitted), three independent cells each."""
    rows = []
    for canonical_id in sorted(APPROVED_BY_CANONICAL_ID, key=lambda c: APPROVED_BY_CANONICAL_ID[c].symbol):
        policy = APPROVED_BY_CANONICAL_ID[canonical_id]
        legs = legs_by_asset.get(canonical_id, {})
        market, reference, oracle = (legs.get(EvidenceRole.MARKET), legs.get(EvidenceRole.OFFICIAL_REFERENCE),
                                     legs.get(EvidenceRole.ORACLE))
        rows.append({
            "symbol": policy.symbol, "canonical_id": canonical_id,
            "oracle_binding": (oracle_coverage or {}).get(canonical_id),
            "MARKET": _leg_cell(market, now),
            "OFFICIAL_REFERENCE": _leg_cell(reference, now),
            "ORACLE": _leg_cell(oracle, now),
            "comparisons": {
                "market_vs_reference": _comparison(market, reference),
                "oracle_vs_reference": _comparison(oracle, reference),
                "market_vs_oracle": _comparison(market, oracle),
            },
        })
    return rows


_STATE_RANK = {"AVAILABLE": 0, "STALE": 1, "UNAVAILABLE": 2, "IDENTITY_UNAVAILABLE": 3}


def _worse(persisted: str, computed: str) -> str:
    """Degrade-only: effective status can match or fall below the persisted status, never rise above it."""
    return computed if _STATE_RANK.get(computed, 2) >= _STATE_RANK.get(persisted, 2) else persisted


def _parse_aware(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo and parsed.utcoffset() is not None else None


def evaluate_effective_state(
    role: EvidenceRole, *, canonical_id: str, persisted_state: str, persisted_reason: str | None,
    source_timestamp: datetime | None, payload: Mapping[str, Any], now: datetime, oracle_registry: Any | None = None,
) -> tuple[str, str | None]:
    """READ-TIME status of one persisted leg: (effective_state, effective_reason). Pure; writes nothing.

    collection-time AVAILABLE does not imply read-time AVAILABLE. The result may preserve or degrade the persisted state and
    NEVER upgrades it (a persisted STALE/UNAVAILABLE row stays so even if policy later changed). ``collected_at`` is never
    used as evidence time. Only EXISTING policy is reused; no new TTL exists here:
      MARKET             -> the R-LIVE snapshot re-evaluation contract (block / pool activity / USDG-USD quote limits)
      OFFICIAL_REFERENCE -> the R-LIVE authority ``max_reference_age_seconds`` via the authority engine's own age test
      ORACLE             -> the CURRENT reviewed registry binding's feed-specific heartbeat
    """
    if persisted_state != "AVAILABLE":
        # Never promote; an unreviewed oracle is still reported as unreviewed rather than as a stored value.
        if role is EvidenceRole.ORACLE and oracle_registry is not None \
                and oracle_registry.binding_for(canonical_id) is None:
            return "UNAVAILABLE", "ORACLE_FEED_NOT_REVIEWED"
        return persisted_state, persisted_reason

    if role is EvidenceRole.ORACLE:
        binding = oracle_registry.binding_for(canonical_id) if oracle_registry is not None else None
        if binding is None:
            return "UNAVAILABLE", "ORACLE_FEED_NOT_REVIEWED"
        if binding.heartbeat_seconds is None:
            return "UNAVAILABLE", "ORACLE_HEARTBEAT_NOT_REVIEWED"
        if source_timestamp is None:
            return "UNAVAILABLE", "ORACLE_SOURCE_TIMESTAMP_UNAVAILABLE"
        age = (now - source_timestamp).total_seconds()
        if age < 0 or age > binding.heartbeat_seconds:
            return "STALE", "ORACLE_HEARTBEAT_EXCEEDED"
        return "AVAILABLE", None

    if role is EvidenceRole.OFFICIAL_REFERENCE:
        if source_timestamp is None:
            return "UNAVAILABLE", "REFERENCE_SOURCE_TIMESTAMP_UNAVAILABLE"
        from finco_radar.authority.engine import _state as authority_age_state
        from .r_live_service import R_LIVE_AUTHORITY_POLICY
        state = authority_age_state(source_timestamp, now, R_LIVE_AUTHORITY_POLICY.max_reference_age_seconds)
        if state is AuthorityState.AVAILABLE:
            return "AVAILABLE", None
        return "STALE", "REFERENCE_STALE"

    # MARKET: reuse the existing snapshot re-evaluation (evidence timestamps only; never collected_at).
    from .r_live_snapshot_view import reevaluate_snapshot_row
    freshness = {
        "block_timestamp": payload.get("blockTimestamp") if isinstance(payload.get("blockTimestamp"), str) else None,
        "last_pool_activity_at": payload.get("lastPoolActivityAt"),
        "quote_updated_at": payload.get("quoteUpdatedAt"),
    }
    if freshness["block_timestamp"] is None and isinstance(payload.get("blockTimestamp"), (int, float)):
        freshness["block_timestamp"] = datetime.fromtimestamp(payload["blockTimestamp"], timezone.utc).isoformat()
    row = reevaluate_snapshot_row(
        {"canonical_id": canonical_id, "collected_at": None,
         "payload": {"canonical_id": canonical_id, "state": persisted_state, "data": {"freshness": freshness}}},
        now=now)
    state = str(row.get("state") or "UNAVAILABLE")
    return _worse(persisted_state, state), row.get("reason") if state != "AVAILABLE" else None


def read_latest_legs_readonly(canonical_id: str, *, path: str | Path | None = None,
                              now: datetime | None = None, oracle_registry: Any | None = None) -> dict:
    """Network-free, write-free read of the latest persisted leg per role for one exact reviewed asset.

    ``state`` is the EFFECTIVE status evaluated at read time by the server (no browser-clock authority);
    ``persisted_state`` is what the collector recorded and is never modified. Never creates the database, never calls a
    provider. Missing store/rows -> role reported as not collected.
    """
    if canonical_id not in APPROVED_BY_CANONICAL_ID:
        raise ValueError("EVIDENCE_EXACT_ASSETKEY_NOT_APPROVED")
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError("EVIDENCE_READ_CLOCK_MUST_BE_AWARE")
    if oracle_registry is None:
        from .stock_token_oracle_registry import load_registry
        try:
            oracle_registry = load_registry()
        except Exception:
            oracle_registry = None
    target = Path(path or default_db_path())
    out: dict[str, dict | None] = {role.value: None for role in EvidenceRole}
    if target.is_file():
        try:
            conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True, timeout=5.0)
            conn.row_factory = sqlite3.Row
            try:
                for role in EvidenceRole:
                    row = conn.execute(
                        "SELECT * FROM source_evidence WHERE canonical_id=? AND evidence_role=? "
                        "ORDER BY seq DESC LIMIT 1", (canonical_id, role.value)).fetchone()
                    if row is None:
                        continue
                    parsed = _parse_aware(row["source_timestamp"])
                    try:
                        payload = json.loads(row["payload"] or "{}")
                    except ValueError:
                        payload = {}
                    effective, reason = evaluate_effective_state(
                        role, canonical_id=canonical_id, persisted_state=row["state"], persisted_reason=row["reason"],
                        source_timestamp=parsed, payload=payload if isinstance(payload, dict) else {}, now=clock,
                        oracle_registry=oracle_registry)
                    heartbeat = None
                    if role is EvidenceRole.ORACLE and oracle_registry is not None:
                        binding = oracle_registry.binding_for(canonical_id)
                        heartbeat = binding.heartbeat_seconds if binding else None   # CURRENT reviewed policy
                    out[role.value] = {
                        "state": effective, "persisted_state": row["state"], "value": row["value"],
                        "unit": row["unit"], "reason": reason, "persisted_reason": row["reason"],
                        "source_timestamp": row["source_timestamp"], "collected_at": row["collected_at"],
                        "age_seconds": _age(clock, parsed) if parsed else None,
                        "source_authority": row["source_authority"], "source_instrument": row["source_instrument"],
                        "heartbeat_seconds": heartbeat,
                    }
                    if role is EvidenceRole.ORACLE:
                        # The recorded L2 guard facts, verbatim from the persisted evidence (never inferred): when no official
                        # sequencer feed is published the oracle is AVAILABLE with PINNED_BLOCK_FRESHNESS_ONLY, not sequencer
                        # assurance.
                        out[role.value].update({
                            "sequencer_authority_state": payload.get("sequencerAuthorityState"),
                            "sequencer_checked": payload.get("sequencerChecked"),
                            "l2_liveness_guard": payload.get("l2LivenessGuard"),
                            "sequencer_grace_protection": payload.get("sequencerGraceProtection"),
                        })
            finally:
                conn.close()
        except (sqlite3.Error, ValueError):
            out = {role.value: None for role in EvidenceRole}
    return {
        "canonical_id": canonical_id, "legs": out,
        "sequencer_authority": oracle_registry.sequencer_authority_state if oracle_registry is not None else None,
    }
