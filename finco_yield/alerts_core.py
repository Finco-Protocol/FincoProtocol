"""FINCO Yield Alerts V1 — domain core (Agent A).

Deterministic, descriptive alert pipeline over canonical Yield evidence:

    canonical watchlist (``finco_yield.watchlist``)
    → canonical history (``YieldHistoryStore``)
    → checkpoint state (``yield_alert_state``)
    → canonical freshness (``evaluate_freshness``) + registry support state
    → typed alert event
    → per-user SQLite persistence (deterministic alert_id, deduped)

Identity remains exact ``yld_*`` canonical opportunity UIDs.  Alerts are
DESCRIPTIVE ONLY: they state that a value or evidence state changed.  They
are never BUY / SELL / ENTER / EXIT / BEST / SAFE / UNSAFE and never a
forecast.

Missing != zero: a ``None`` observation field is MISSING (no change can be
computed against it) while an explicit ``0`` is valid data and can change.
"""
from __future__ import annotations

from typing import Any

from .alerts_store import (
    create_alerts,
    get_checkpoint,
    list_alerts,
    mark_all_read,
    mark_read,
    remove_checkpoint,
    set_checkpoint,
    unread_count,
)
from .alerts_types import (
    ALERTS_SCHEMA_VERSION,
    ALERT_TYPE_LABELS,
    TRACKED_ECONOMIC_FIELDS,
    AlertType,
    YieldAlertEvent,
    deterministic_alert_id,
)
from .alerts_eval import evaluate_watchlist_alerts

__all__ = [
    "ALERTS_SCHEMA_VERSION",
    "ALERT_TYPE_LABELS",
    "TRACKED_ECONOMIC_FIELDS",
    "AlertType",
    "YieldAlertEvent",
    "alerts_snapshot",
    "create_alerts",
    "deterministic_alert_id",
    "evaluate_watchlist_alerts",
    "get_checkpoint",
    "list_alerts",
    "mark_all_read",
    "mark_read",
    "remove_checkpoint",
    "set_checkpoint",
    "unread_count",
]


def alerts_snapshot(user_id: str, *, unread_only: bool = False) -> dict[str, Any]:
    """Read-model snapshot for the presentation layer (Agent C seam).

    Descriptive only: the user's alerts (newest first) plus the unread
    count.  No ranking, no recommendation, no aggregation beyond counting.
    """
    alerts = list_alerts(user_id, unread_only=unread_only)
    return {
        "user_id": user_id,
        "alerts": alerts,
        "unread_count": unread_count(user_id),
    }
