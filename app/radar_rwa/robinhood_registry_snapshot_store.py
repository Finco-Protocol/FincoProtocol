"""Durable retained Robinhood RegistrySnapshot evidence for R-LIVE continuity.

This module is storage only. It never chooses authority, refreshes timestamps,
or derives identity. Canonical selection remains in
finco_radar.authority.engine.select_robinhood_registry.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.registry import RegistrySnapshot


_SCHEMA_VERSION = "ROBINHOOD_REGISTRY_SNAPSHOT_V1"
_TABLE = "robinhood_registry_snapshot"


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class RobinhoodRegistrySnapshotStore:
    """Single-row durable retention of the latest source-proven official snapshot."""

    def __init__(self, path: str) -> None:
        if not isinstance(path, str) or not path.strip() or path == ":memory:":
            raise ValueError("durable registry snapshot path required")
        self.path = Path(path)

    @staticmethod
    def _envelope(snapshot: RegistrySnapshot) -> dict[str, Any]:
        if snapshot.source != RobinhoodAssetRegistryAdapter.source_name:
            raise ValueError("retained registry source must be official Robinhood")
        if snapshot.observed_at.tzinfo is None or snapshot.observed_at.utcoffset() is None:
            raise ValueError("retained registry observed_at must be timezone-aware")

        rows: list[dict[str, Any]] = []
        for asset in snapshot.assets:
            if not isinstance(asset.raw_evidence, Mapping) or not asset.raw_evidence:
                raise ValueError("retained registry requires original official asset rows")
            try:
                row = json.loads(json.dumps(dict(asset.raw_evidence)))
            except (TypeError, ValueError) as exc:
                raise ValueError("retained official asset row is not JSON serializable") from exc
            if not isinstance(row, dict):
                raise ValueError("retained official asset row must be an object")
            rows.append(row)

        reconstructed = RobinhoodAssetRegistryAdapter.parse_snapshot(
            {"assets": rows},
            observed_at=snapshot.observed_at,
        )
        if reconstructed != snapshot:
            raise ValueError("retained official rows do not reconstruct the canonical snapshot")

        return {
            "schema_version": _SCHEMA_VERSION,
            "source": snapshot.source,
            "observed_at": snapshot.observed_at.isoformat(),
            "assets": rows,
        }

    def put(self, snapshot: RegistrySnapshot) -> str:
        envelope = self._envelope(snapshot)
        payload = _canonical(envelope)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=10) as conn:
            conn.execute(
                f"""CREATE TABLE IF NOT EXISTS {_TABLE} (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    payload TEXT NOT NULL,
                    digest TEXT NOT NULL
                )"""
            )
            conn.execute(
                f"""INSERT INTO {_TABLE}(singleton, payload, digest)
                    VALUES (1, ?, ?)
                    ON CONFLICT(singleton) DO UPDATE SET
                        payload=excluded.payload,
                        digest=excluded.digest""",
                (payload, digest),
            )
            conn.commit()
        return digest

    def load_latest(self) -> RegistrySnapshot | None:
        """Return verified retained evidence or None; reading never restamps it."""
        if not self.path.is_file():
            return None
        try:
            with sqlite3.connect(
                self.path.resolve().as_uri() + "?mode=ro",
                uri=True,
                timeout=5,
            ) as conn:
                row = conn.execute(
                    f"SELECT payload, digest FROM {_TABLE} WHERE singleton = 1"
                ).fetchone()
            if row is None:
                return None
            payload, digest = row
            if not isinstance(payload, str) or not isinstance(digest, str):
                return None
            if hashlib.sha256(payload.encode("utf-8")).hexdigest() != digest:
                return None
            envelope = json.loads(payload)
            if not isinstance(envelope, dict):
                return None
            if envelope.get("schema_version") != _SCHEMA_VERSION:
                return None
            if envelope.get("source") != RobinhoodAssetRegistryAdapter.source_name:
                return None
            observed_raw = envelope.get("observed_at")
            if not isinstance(observed_raw, str):
                return None
            observed_at = datetime.fromisoformat(observed_raw)
            if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                return None
            rows = envelope.get("assets")
            if not isinstance(rows, list) or not rows:
                return None
            return RobinhoodAssetRegistryAdapter.parse_snapshot(
                {"assets": rows},
                observed_at=observed_at,
            )
        except (OSError, sqlite3.Error, json.JSONDecodeError, TypeError, ValueError):
            return None
