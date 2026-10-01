"""Typed alerts contracts for Yield Alerts V1 (Agent A).

Alerts are descriptive only.  There is no BUY/SELL/ENTER/EXIT/BEST/SAFE/
UNSAFE vocabulary anywhere in this module, and none may be added.

Freshness states use canonical ``evaluate_freshness`` semantics
(CURRENT / STALE / INVALID / FUTURE_TIMESTAMP) — ``AVAILABLE`` is not a
freshness state.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

ALERTS_SCHEMA_VERSION = "YIELD_ALERTS_V1"

# Tracked economic observation fields (canonical payload keys).
TRACKED_ECONOMIC_FIELDS: tuple[str, ...] = (
    "apy_total",
    "tvl_usd",
    "apy_rewards",
)


class AlertType(str, Enum):
    APY_CHANGED = "APY_CHANGED"
    TVL_CHANGED = "TVL_CHANGED"
    REWARD_COMPONENT_CHANGED = "REWARD_COMPONENT_CHANGED"
    FRESHNESS_DEGRADED = "FRESHNESS_DEGRADED"
    FRESHNESS_RECOVERED = "FRESHNESS_RECOVERED"
    SUPPORT_STATE_CHANGED = "SUPPORT_STATE_CHANGED"
    NEW_OBSERVATION = "NEW_OBSERVATION"


ALERT_TYPE_LABELS: dict[AlertType, str] = {
    AlertType.APY_CHANGED: "APY changed",
    AlertType.TVL_CHANGED: "TVL changed",
    AlertType.REWARD_COMPONENT_CHANGED: "Reward component changed",
    AlertType.FRESHNESS_DEGRADED: "Evidence freshness degraded",
    AlertType.FRESHNESS_RECOVERED: "Evidence freshness recovered",
    AlertType.SUPPORT_STATE_CHANGED: "Support state changed",
    AlertType.NEW_OBSERVATION: "Fresh evidence arrived after a stale period",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class YieldAlertEvent:
    """One typed, descriptive alert event (pre-persistence)."""

    opportunity_uid: str
    alert_type: AlertType
    label: str
    field: str | None
    previous: object
    current: object
    previous_observation_hash: str
    current_observation_hash: str
    detected_at: str  # ISO-8601 UTC


def deterministic_alert_id(
    *, user_id: str, opportunity_uid: str, alert_type: str,
    field: str | None, previous_observation_hash: str,
    current_observation_hash: str,
) -> str:
    """Deterministic alert ID from canonical identity fields.

    Same logical transition → same alert_id → exactly one persisted record.
    Different transition → different alert_id.
    """
    payload = json.dumps({
        "schema": ALERTS_SCHEMA_VERSION,
        "user_id": user_id,
        "opportunity_uid": opportunity_uid,
        "alert_type": alert_type,
        "field": field or "",
        "previous_observation_hash": previous_observation_hash,
        "current_observation_hash": current_observation_hash,
    }, sort_keys=True, separators=(",", ":"))
    return "yalt_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:40]
