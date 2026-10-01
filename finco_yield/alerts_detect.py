"""Deterministic change detection for Yield Alerts V1 (Agent A).

Re-exports the detection primitives; the alert-type derivation from a
ChangeSensorResult lives here so the mapping from field transitions to
typed alert events is itself deterministic and testable.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .alerts_types import (
    AlertEvent,
    AlertType,
    ChangeSensorResult,
    DetectionContext,
    FieldChange,
)

# Field -> alert type for scalar value changes.
_FIELD_ALERT_TYPE: dict[str, AlertType] = {
    "apy_total": AlertType.APY_CHANGED,
    "tvl_usd": AlertType.TVL_CHANGED,
    "apy_rewards": AlertType.REWARD_COMPONENT_CHANGED,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def alert_type_for_change(change: FieldChange, sensor: ChangeSensorResult) -> AlertType | None:
    """Map one field transition to its typed alert."""
    if change.field == "freshness_state":
        if sensor.degraded:
            return AlertType.FRESHNESS_DEGRADED
        if sensor.recovered:
            return AlertType.FRESHNESS_RECOVERED
        return None
    if change.field == "support_state":
        return AlertType.SUPPORT_STATE_CHANGED
    return _FIELD_ALERT_TYPE.get(change.field)


def events_from_changes(
    sensor: ChangeSensorResult, *, detected_at: datetime | None = None
) -> tuple[AlertEvent, ...]:
    """Derive the typed alert events for one detection pass."""
    at = detected_at or utc_now()
    events: list[AlertEvent] = []
    for field_change in sensor.changes:
        alert_type = alert_type_for_change(field_change, sensor)
        if alert_type is None:
            continue
        events.append(
            AlertEvent.from_change(sensor, field_change, alert_type, at))
    if not events and not sensor.changes:
        # No field-level changes at all: the observation identity changed
        # (e.g. re-observation with identical values) — no alert.
        return ()
    return tuple(events)
