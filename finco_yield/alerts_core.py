"""FINCO Yield Alerts V1 — domain core (Agent A).

Deterministic, descriptive alert pipeline over canonical Yield evidence:

    canonical history/observation
    → deterministic change detection
    → watched canonical opportunity
    → typed alert event
    → per-user persistence

Identity remains exact ``yld_*`` canonical opportunity UIDs.  Alerts are
DESCRIPTIVE ONLY: they state that a value changed.  They are never BUY /
SELL / ENTER / EXIT / BEST / SAFE / UNSAFE and never a forecast.

Missing != zero: a ``None`` observation field is MISSING (no change can be
computed against it) while an explicit ``0`` is valid data and can change.
"""
from __future__ import annotations

from .alerts_types import (
    ALERT_TYPE_LABELS,
    AlertEvent,
    AlertType,
    ChangeSensorResult,
    FieldChange,
    WatchedOpportunity,
    detect_changes,
    observed_value,
)
from .alerts_store import (
    AlertRecord,
    PerUserAlertStore,
    WatchlistStore,
)
from .alerts_eval import evaluate_watchlist_alerts

__all__ = [
    "ALERT_TYPE_LABELS",
    "AlertEvent",
    "AlertRecord",
    "AlertType",
    "ChangeSensorResult",
    "DetectionContext",
    "FieldChange",
    "PerUserAlertStore",
    "WatchedOpportunity",
    "WatchlistStore",
    "detect_changes",
    "evaluate_watchlist_alerts",
    "observed_value",
]
