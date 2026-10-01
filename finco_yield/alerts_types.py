"""Typed alert events and change-detection contracts for Yield Alerts V1.

Alerts are descriptive only.  There is no BUY/SELL/ENTER/EXIT/BEST/SAFE/
UNSAFE vocabulary anywhere in this module, and none may be added.

Missing != zero: ``None`` means missing/unavailable and never participates
in a change computation; an explicit ``0`` is valid observed data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

# Canonical observed fields (subset of the Yield observation contract that
# change detection covers).  Values are opaque: int/float/str/None.
TRACKED_FIELDS: tuple[str, ...] = (
    "apy_total",
    "tvl_usd",
    "apy_rewards",
    "freshness_state",
    "support_state",
)

FRESHNESS_STATE_FIELD = "freshness_state"
SUPPORT_STATE_FIELD = "support_state"


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
    AlertType.NEW_OBSERVATION: "New observation recorded",
}


@dataclass(frozen=True)
class FieldChange:
    """One deterministic field-level transition between two observations."""

    field: str
    previous: object  # prior value verbatim; None only when truly missing
    current: object   # new value verbatim; None only when truly missing


@dataclass(frozen=True)
class WatchedOpportunity:
    """One watchlist entry: an exact canonical opportunity UID."""

    user_id: str
    opportunity_uid: str  # exact yld_* canonical UID — never a ticker/label


@dataclass(frozen=True)
class ChangeSensorResult:
    """Deterministic diff between a previous and current observation."""

    opportunity_uid: str
    previous_observation_hash: str
    current_observation_hash: str
    changes: tuple[FieldChange, ...]
    degraded: bool
    recovered: bool


@dataclass(frozen=True)
class AlertEvent:
    """One typed, descriptive alert event (pre-persistence)."""

    opportunity_uid: str
    alert_type: AlertType
    label: str
    field: str | None
    previous: object
    current: object
    previous_observation_hash: str
    current_observation_hash: str
    detected_at: datetime

    @classmethod
    def from_change(cls, change: ChangeSensorResult, field_change: FieldChange,
                    alert_type: AlertType, detected_at: datetime) -> "AlertEvent":
        return cls(
            opportunity_uid=change.opportunity_uid,
            alert_type=alert_type,
            label=ALERT_TYPE_LABELS[alert_type],
            field=field_change.field,
            previous=field_change.previous,
            current=field_change.current,
            previous_observation_hash=change.previous_observation_hash,
            current_observation_hash=change.current_observation_hash,
            detected_at=detected_at,
        )


@dataclass(frozen=True)
class DetectionContext:
    """Inputs for one change-detection pass."""

    opportunity_uid: str
    previous: dict           # prior observation row (verbatim from history)
    current: dict            # current observation row (verbatim from history)
    previous_hash: str
    current_hash: str


def observed_value(row: dict, field: str):
    """Read one observed value, honouring missing != zero.

    Returns the raw stored value (which may legitimately be ``0``).  A truly
    missing field returns the ``MISSING`` sentinel via ``None`` only when the
    key is absent entirely — an explicit stored ``None`` is also missing.
    """
    if field not in row:
        return None
    return row[field]


def _is_missing(value) -> bool:
    """Missing means None/unavailable — an explicit 0 is valid data."""
    return value is None


def _values_differ(previous, current) -> bool:
    """Deterministic inequality that never treats missing as zero.

    - both missing (None)            -> not a change
    - one missing, other present     -> a change (including 0 <-> missing)
    - both present                   -> compare canonical representation
    """
    if _is_missing(previous) and _is_missing(current):
        return False
    if _is_missing(previous) != _is_missing(current):
        return True
    # Both present: canonical textual comparison so Decimal("0") == 0 and
    # "0" == 0 compare deterministically by string form of the value.
    return _canonical_scalar(previous) != _canonical_scalar(current)


def _canonical_scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return repr(value)
    if isinstance(value, float):
        if value == int(value) and abs(value) < 1e15:
            return repr(int(value))
        return repr(value)
    try:
        from decimal import Decimal

        if isinstance(value, Decimal):
            if value == value.to_integral_value():
                return str(int(value))
            return str(value)
    except (ImportError, AttributeError):
        pass
    return str(value)


def detect_changes(ctx: DetectionContext) -> ChangeSensorResult:
    """Deterministically diff two observations of the same opportunity.

    Freshness degrade/recover is derived from the freshness-state transition;
    all other tracked fields produce their specific changed alert.
    """
    changes: list[FieldChange] = []
    degraded = False
    recovered = False

    prev = ctx.previous
    curr = ctx.current

    for field in TRACKED_FIELDS:
        previous_value = observed_value(prev, field)
        current_value = observed_value(curr, field)
        if not _values_differ(previous_value, current_value):
            continue
        changes.append(FieldChange(field, previous_value, current_value))
        if field == FRESHNESS_STATE_FIELD:
            if current_value == "STALE" or (
                _is_missing(current_value) and not _is_missing(previous_value)
                and previous_value != "STALE"
            ):
                degraded = True
            elif previous_value == "STALE" and current_value == "AVAILABLE":
                recovered = True

    return ChangeSensorResult(
        opportunity_uid=ctx.opportunity_uid,
        previous_observation_hash=ctx.previous_hash,
        current_observation_hash=ctx.current_hash,
        changes=tuple(changes),
        degraded=degraded,
        recovered=recovered,
    )
