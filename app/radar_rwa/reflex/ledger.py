"""Append-only experiment evidence with exact event and authority identity binding."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from threading import RLock

from finco_radar.assets.contracts import normalize_asset_uid


LEDGER_SCHEMA_VERSION = "RWA_REFLEX_LEDGER_V2"
OUTCOME_SOURCE_CONTRACT = "FINCO_AUTHORITY_SNAPSHOT_V1"


def _canonical(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(payload: dict[str, object]) -> tuple[str, str]:
    canonical = _canonical(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest(), canonical


def _aware_iso(value: str, name: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


@dataclass(frozen=True)
class ReflexOutcomeObservation:
    observed_at: datetime
    economic_asset_uid: str
    asset_key: str
    registry_source: str
    registry_observed_at: datetime | None
    authority_state: str
    market_session: str
    reference_premium_bps: Decimal | None
    effective_gap_bps: Decimal | None
    liquidity_usd: Decimal | None
    depth_1pct_usd: Decimal | None
    source_contract: str = OUTCOME_SOURCE_CONTRACT

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("outcome observed_at must be timezone-aware")
        if self.registry_observed_at is not None and (
            self.registry_observed_at.tzinfo is None or self.registry_observed_at.utcoffset() is None
        ):
            raise ValueError("registry_observed_at must be timezone-aware")
        object.__setattr__(self, "economic_asset_uid", normalize_asset_uid(self.economic_asset_uid))
        if not self.asset_key.strip() or not self.registry_source.strip():
            raise ValueError("outcome requires canonical asset key and registry source")
        if self.source_contract != OUTCOME_SOURCE_CONTRACT:
            raise ValueError("RWA_REFLEX_OUTCOME_SOURCE_SPOOF_REJECTED")
        for name in ("reference_premium_bps", "effective_gap_bps", "liquidity_usd", "depth_1pct_usd"):
            value = getattr(self, name)
            if value is not None and not value.is_finite():
                raise ValueError(f"{name} must be finite when present")
        for name in ("liquidity_usd", "depth_1pct_usd"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be nonnegative when present")

    def to_payload(self) -> dict[str, object]:
        return {
            "observed_at": self.observed_at.isoformat(),
            "economic_asset_uid": self.economic_asset_uid,
            "asset_key": self.asset_key,
            "registry_source": self.registry_source,
            "registry_observed_at": self.registry_observed_at.isoformat() if self.registry_observed_at else None,
            "authority_state": self.authority_state,
            "market_session": self.market_session,
            "reference_premium_bps": str(self.reference_premium_bps) if self.reference_premium_bps is not None else None,
            "effective_gap_bps": str(self.effective_gap_bps) if self.effective_gap_bps is not None else None,
            "liquidity_usd": str(self.liquidity_usd) if self.liquidity_usd is not None else None,
            "depth_1pct_usd": str(self.depth_1pct_usd) if self.depth_1pct_usd is not None else None,
            "source_contract": self.source_contract,
        }


class ReflexExperimentLedger:
    """Dedicated immutable ledger; canonical Radar history is never written."""

    def __init__(self, path: str = ":memory:") -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS reflex_predictions (
                digest TEXT PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                input_fingerprint TEXT NOT NULL,
                economic_asset_uid TEXT NOT NULL,
                asset_key TEXT NOT NULL,
                registry_source TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_reflex_prediction_identity_time
                ON reflex_predictions(economic_asset_uid, asset_key, observed_at);
            CREATE TABLE IF NOT EXISTS reflex_outcomes (
                digest TEXT PRIMARY KEY,
                prediction_digest TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                horizon_seconds INTEGER NOT NULL,
                payload TEXT NOT NULL,
                FOREIGN KEY(prediction_digest) REFERENCES reflex_predictions(digest)
            );
            CREATE INDEX IF NOT EXISTS idx_reflex_outcome_prediction_time
                ON reflex_outcomes(prediction_digest, observed_at);
        """)
        self._lock = RLock()

    def put_prediction(self, experiment: dict[str, object]) -> str:
        if experiment.get("experimental") is not True:
            raise ValueError("prediction requires experimental Reflex payload")
        state = experiment.get("reflex_state")
        interpretation = experiment.get("interpretation")
        event = experiment.get("event")
        if not isinstance(state, dict) or not isinstance(interpretation, dict) or not isinstance(event, dict):
            raise ValueError("prediction requires Reflex state, interpretation and event")
        uid_raw = state.get("economic_asset_uid")
        token = state.get("canonical_token")
        provenance = state.get("provenance")
        observed_at_raw = state.get("observed_at")
        fingerprint = interpretation.get("input_fingerprint")
        event_id = event.get("event_id")
        if not isinstance(uid_raw, str) or not isinstance(token, dict) or not isinstance(provenance, dict):
            raise ValueError("prediction requires canonical identity provenance")
        asset_key = token.get("canonical_id")
        registry_source = provenance.get("registry_source")
        if not all(isinstance(v, str) and v for v in (asset_key, registry_source, event_id)):
            raise ValueError("prediction requires asset key, registry source and event id")
        if event.get("economic_asset_uid") != uid_raw or event.get("asset_key") != asset_key or event.get("registry_source") != registry_source:
            raise ValueError("prediction event identity mismatch")
        if not isinstance(observed_at_raw, str):
            raise ValueError("prediction requires observation time")
        _aware_iso(observed_at_raw, "prediction observed_at")
        if not isinstance(fingerprint, str) or len(fingerprint) != 64:
            raise ValueError("prediction requires input fingerprint")

        payload = dict(experiment)
        payload["ledger_schema_version"] = LEDGER_SCHEMA_VERSION
        digest, canonical = _digest(payload)
        uid = normalize_asset_uid(uid_raw)
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO reflex_predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (digest, event_id, fingerprint, uid, asset_key, registry_source, observed_at_raw, canonical),
                )
            except sqlite3.IntegrityError:
                row = self._conn.execute("SELECT digest, payload FROM reflex_predictions WHERE event_id = ?", (event_id,)).fetchone()
                if row is not None and row["digest"] == digest and row["payload"] == canonical:
                    return digest
                raise ValueError("RWA_REFLEX_EVENT_DUPLICATE") from None
        return digest

    def prediction_identity(self, prediction_digest: str) -> dict[str, str] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT economic_asset_uid, asset_key, registry_source, observed_at FROM reflex_predictions WHERE digest = ?",
                (prediction_digest,),
            ).fetchone()
        return None if row is None else dict(row)

    def put_outcome(self, prediction_digest: str, outcome: ReflexOutcomeObservation) -> str:
        with self._lock:
            prediction = self._conn.execute(
                "SELECT economic_asset_uid, asset_key, registry_source, observed_at FROM reflex_predictions WHERE digest = ?",
                (prediction_digest,),
            ).fetchone()
            if prediction is None:
                raise ValueError("outcome requires an existing prediction")
            if (normalize_asset_uid(prediction["economic_asset_uid"]) != outcome.economic_asset_uid
                    or prediction["asset_key"] != outcome.asset_key
                    or prediction["registry_source"] != outcome.registry_source):
                raise ValueError("RWA_REFLEX_OUTCOME_CROSS_ASSET_REJECTED")
            if outcome.source_contract != OUTCOME_SOURCE_CONTRACT:
                raise ValueError("RWA_REFLEX_OUTCOME_SOURCE_SPOOF_REJECTED")
            predicted_at = _aware_iso(prediction["observed_at"], "prediction observed_at")
            horizon_seconds = int((outcome.observed_at - predicted_at).total_seconds())
            if horizon_seconds <= 0:
                raise ValueError("outcome must occur after prediction")
            payload = {
                "ledger_schema_version": LEDGER_SCHEMA_VERSION,
                "prediction_digest": prediction_digest,
                "horizon_seconds": horizon_seconds,
                **outcome.to_payload(),
            }
            digest, canonical = _digest(payload)
            try:
                self._conn.execute(
                    "INSERT INTO reflex_outcomes VALUES (?, ?, ?, ?, ?)",
                    (digest, prediction_digest, outcome.observed_at.isoformat(), horizon_seconds, canonical),
                )
            except sqlite3.IntegrityError:
                row = self._conn.execute("SELECT payload FROM reflex_outcomes WHERE digest = ?", (digest,)).fetchone()
                if row is None or row["payload"] != canonical:
                    raise ValueError("outcome digest conflict") from None
        return digest

    def read_prediction(self, digest: str) -> dict[str, object] | None:
        with self._lock:
            row = self._conn.execute("SELECT payload FROM reflex_predictions WHERE digest = ?", (digest,)).fetchone()
        if row is None:
            return None
        if hashlib.sha256(row["payload"].encode("utf-8")).hexdigest() != digest:
            raise ValueError("prediction digest does not reconstruct")
        return json.loads(row["payload"])

    def read_outcomes(self, prediction_digest: str) -> list[dict[str, object]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT digest, payload FROM reflex_outcomes WHERE prediction_digest = ? ORDER BY observed_at ASC, digest ASC",
                (prediction_digest,),
            ).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            if hashlib.sha256(row["payload"].encode("utf-8")).hexdigest() != row["digest"]:
                raise ValueError("outcome digest does not reconstruct")
            result.append(json.loads(row["payload"]))
        return result

    def close(self) -> None:
        with self._lock:
            self._conn.close()
