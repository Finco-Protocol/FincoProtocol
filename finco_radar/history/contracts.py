"""Typed immutable history and change contracts for R5 snapshots."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from finco_radar.assets.contracts import AssetKey
from finco_radar.quotes.contracts import QuoteSide
from finco_radar.signals.contracts import SignalPolicy, SignalSnapshot


class HistoryStatus(str, Enum):
    HISTORY_OK = "HISTORY_OK"
    HISTORY_IDENTITY_MISMATCH = "HISTORY_IDENTITY_MISMATCH"
    HISTORY_POLICY_MISMATCH = "HISTORY_POLICY_MISMATCH"
    HISTORY_TIME_ORDER_INVALID = "HISTORY_TIME_ORDER_INVALID"
    HISTORY_EVIDENCE_INVALID = "HISTORY_EVIDENCE_INVALID"


class HistoryError(ValueError):
    def __init__(self, message: str, status: HistoryStatus) -> None:
        super().__init__(message)
        self.status = status


class SignalChangeKind(str, Enum):
    SIGNAL_APPEARED = "SIGNAL_APPEARED"
    SIGNAL_CLEARED = "SIGNAL_CLEARED"
    DIRECTION_CHANGED = "DIRECTION_CHANGED"
    SIZE_STATE_CHANGED = "SIZE_STATE_CHANGED"
    LIQUIDITY_CONTEXT_CHANGED = "LIQUIDITY_CONTEXT_CHANGED"
    MAGNITUDE_CHANGED = "MAGNITUDE_CHANGED"
    UNCHANGED = "UNCHANGED"


@dataclass(frozen=True)
class HistoryEntry:
    asset_uid: str
    canonical_key: AssetKey
    symbol: str
    observed_at: datetime
    signal_snapshot: SignalSnapshot
    snapshot_digest: str
    policy: SignalPolicy

    def to_evidence_dict(self) -> dict[str, Any]:
        return {"assetUid": self.asset_uid, "canonicalKey": self.canonical_key.canonical_id,
                "symbol": self.symbol, "observedAt": self.observed_at.isoformat(),
                "snapshotDigest": self.snapshot_digest, "policy": self.policy.to_evidence_dict()}


@dataclass(frozen=True)
class SignalChange:
    kind: SignalChangeKind
    side: QuoteSide | None
    details: dict[str, Any]

    def to_evidence_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "side": self.side.value if self.side else None, "details": self.details}
