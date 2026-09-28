"""Append-only B1.3 intelligence history, scoped to exact UID and deployment.

R5 uses canonical JSON plus SHA-256 for deterministic evidence identity.  This
store follows that convention and the existing Radar SQLite snapshot ledger;
it is not a replacement for either authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from threading import RLock

from finco_radar.assets.contracts import AssetKey, normalize_asset_uid
from finco_radar.authority.cross_chain import CrossChainIdentityBinding
from finco_radar.authority.contracts import AuthoritySnapshot, AuthorityState
from finco_radar.authority.r_live_onchain import OnchainReferenceObservation


DEFAULT_DB_PATH = str(Path(__file__).resolve().parents[1] / "data" / "radar_bnb_intelligence.db")


def make_history_point(binding: CrossChainIdentityBinding, intelligence: dict, observed_at: str) -> dict | None:
    """Only an available premium earns a numeric history point."""
    if binding.economic_asset_uid is None or binding.external_asset_key is None:
        return None
    premium = intelligence["reference_premium"]
    if premium["state"] != "AVAILABLE" or premium["value_bps"] is None:
        return None
    gap = intelligence["execution_gap"]
    execution = intelligence["execution"]
    gap_available = gap["state"] == "AVAILABLE"
    return {
        "economic_asset_uid": binding.economic_asset_uid,
        "asset_key": binding.external_asset_key.canonical_id,
        "identity_source": binding.authority_source,
        "identity_observed_at": binding.observed_at.isoformat() if binding.observed_at else None,
        "observed_at": observed_at,
        "state": premium["state"],
        "robinhood_basis": intelligence["robinhood_basis"],
        "independent_token_reference": intelligence["independent_token_reference"],
        "reference_premium_bps": premium["value_bps"],
        "premium_sources": premium["sources"],
        "premium_evidence_at": premium["observed_at"],
        "execution_price_usd_per_token": execution["effective_price_usd_per_token"] if gap_available else None,
        "execution_source": execution["provider"] if gap_available else None,
        "execution_observed_at": execution["observed_at"] if gap_available else None,
        "execution_impact_bps": gap["execution_impact_bps"] if gap_available else None,
        "total_execution_gap_bps": gap["effective_gap_bps"] if gap_available else None,
        "execution_state": gap["state"],
    }


def make_r_live_history_point(snapshot: AuthoritySnapshot,
                              observation: OnchainReferenceObservation) -> dict | None:
    """Use the existing B1.3 digest/append-only history for exact R-LIVE evidence."""
    if (observation.state is not AuthorityState.AVAILABLE
            or snapshot.premium.state is not AuthorityState.AVAILABLE
            or snapshot.premium.value_bps is None
            or snapshot.economic_asset_uid != observation.registry_asset_uid
            or snapshot.canonical_token != observation.asset_key):
        return None
    assert observation.observed_at is not None
    return {
        "economic_asset_uid": snapshot.economic_asset_uid,
        "asset_key": snapshot.canonical_token.canonical_id,
        "identity_source": snapshot.registry_source,
        "identity_observed_at": snapshot.registry_observed_at.isoformat() if snapshot.registry_observed_at else None,
        "observed_at": observation.observed_at.isoformat(),
        "state": snapshot.premium.state.value,
        "robinhood_basis": {
            "price_usd_per_token": str(snapshot.underlying.price_usd_per_token),
            "source": snapshot.underlying.source,
            "observed_at": snapshot.underlying.observed_at.isoformat() if snapshot.underlying.observed_at else None,
        },
        "independent_token_reference": observation.to_evidence_dict(),
        "reference_premium_bps": str(snapshot.premium.value_bps),
        "premium_sources": list(snapshot.premium.sources),
        "premium_evidence_at": [value.isoformat() for value in snapshot.premium.observed_at],
        "execution_state": snapshot.execution.state.value,
    }


def _canonical(point: dict) -> str:
    return json.dumps(point, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _r_live_source_identity(point: dict) -> str:
    """Retrieval time is not a new source observation of the same evidence."""
    stable = json.loads(_canonical(point))
    stable["independent_token_reference"]["evidence"].pop("retrievedAt", None)
    return _canonical(stable)


class BnbIntelligenceHistoryStore:
    """Dedicated durable, append-only ledger; no update/delete operations."""

    def __init__(self, path: str | None = None, *, allowed_chain_id: int = 56) -> None:
        if allowed_chain_id not in (56, 4663):
            raise ValueError("history chain must be BNB or Robinhood")
        self.allowed_chain_id = allowed_chain_id
        location = path or os.getenv("RADAR_BNB_INTELLIGENCE_DB_PATH", DEFAULT_DB_PATH)
        if location != ":memory:":
            Path(location).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(location, timeout=30, isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS bnb_intelligence_history (
                digest TEXT PRIMARY KEY,
                economic_asset_uid TEXT NOT NULL,
                asset_key TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_bnb_intelligence_identity_time
                ON bnb_intelligence_history(economic_asset_uid, asset_key, observed_at);
        """)
        self._lock = RLock()

    def put(self, point: dict) -> str:
        payload = _canonical(point)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        uid = normalize_asset_uid(point["economic_asset_uid"])
        key = point["asset_key"]
        observed_at = datetime.fromisoformat(point["observed_at"])
        if (not isinstance(key, str) or not key.startswith(f"{self.allowed_chain_id}:")
                or point["state"] != "AVAILABLE" or point["reference_premium_bps"] is None):
            raise ValueError("history requires available exact premium evidence")
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("history observation must be timezone-aware")
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO bnb_intelligence_history VALUES (?, ?, ?, ?, ?)",
                    (digest, uid, key, point["observed_at"], payload),
                )
            except sqlite3.IntegrityError:
                existing = self._conn.execute(
                    "SELECT payload FROM bnb_intelligence_history WHERE digest = ?", (digest,),
                ).fetchone()
                if existing is None or existing["payload"] != payload:
                    raise ValueError("history digest conflicts with existing evidence") from None
        return digest

    def put_r_live(self, point: dict) -> str:
        """Append once per exact source/basis evidence, even after a later retrieval."""
        if self.allowed_chain_id != 4663:
            raise ValueError("R_LIVE_REQUIRES_ROBINHOOD_HISTORY")
        identity = _r_live_source_identity(point)
        uid = normalize_asset_uid(point["economic_asset_uid"])
        key = point["asset_key"]
        with self._lock:
            # Serialize the read/append across independent collector processes.
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                rows = self._conn.execute(
                    "SELECT digest, payload FROM bnb_intelligence_history "
                    "WHERE economic_asset_uid = ? AND asset_key = ? AND observed_at = ?",
                    (uid, key, point["observed_at"]),
                ).fetchall()
                for row in rows:
                    if hashlib.sha256(row["payload"].encode("utf-8")).hexdigest() != row["digest"]:
                        raise ValueError("history digest does not reconstruct")
                    existing = json.loads(row["payload"])
                    if ("independent_token_reference" in existing
                            and _r_live_source_identity(existing) == identity):
                        self._conn.execute("COMMIT")
                        return row["digest"]
                digest = self.put(point)
                self._conn.execute("COMMIT")
                return digest
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def read(self, uid: str, key: AssetKey, *, limit: int = 30) -> list[dict]:
        if key.chain_id != self.allowed_chain_id or not 1 <= limit <= 100:
            raise ValueError("exact chain key and bounded limit required")
        with self._lock:
            rows = self._conn.execute(
                "SELECT digest, payload FROM bnb_intelligence_history "
                "WHERE economic_asset_uid = ? AND asset_key = ? "
                "ORDER BY observed_at DESC, digest DESC LIMIT ?",
                (normalize_asset_uid(uid), key.canonical_id, limit),
            ).fetchall()
        result = []
        for row in rows:
            if hashlib.sha256(row["payload"].encode("utf-8")).hexdigest() != row["digest"]:
                raise ValueError("history digest does not reconstruct")
            result.append(json.loads(row["payload"]))
        return result

    def close(self) -> None:
        with self._lock:
            self._conn.close()
