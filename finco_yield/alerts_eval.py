"""Deterministic watchlist alert evaluation for Yield Alerts V1.

``evaluate_watchlist_alerts`` is the single deterministic callable a later
scheduler/refresh path invokes.  No scheduler, queue, cron, email, push or
chat infrastructure lives here.

Pipeline:
    canonical history/observation rows
    → deterministic change detection (detect_changes)
    → watched-opportunity filter (WatchlistStore)
    → typed alert events
    → per-user persistence (PerUserAlertStore, deduped)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from .alerts_types import detect_changes, DetectionContext

__all__ = ["evaluate_watchlist_alerts", "alerts_for_detection"]


def _row_field(row: dict, field: str):
    """Read one observed value from a history row, honouring missing != zero.

    History rows may carry the observation fields at top level or inside a
    ``payload`` mapping.  A truly absent key is missing; an explicitly
    stored ``None`` is also missing (never zero).  An explicit ``0`` is
    valid observed data.
    """
    if field in row:
        return row[field]
    payload = row.get("payload")
    if isinstance(payload, dict) and field in payload:
        return payload[field]
    return None  # missing


def alerts_for_detection(ctx: DetectionContext, *,
                         detected_at: datetime | None = None) -> tuple:
    """Derive typed alert events from one detection context.

    Order-stable: APY / TVL / reward component / freshness / support state,
    in the canonical TRACKED_FIELDS order.
    """
    from .alerts_detect import events_from_changes

    return events_from_changes(ctx, detected_at=detected_at)


def evaluate_watchlist_alerts(
    *,
    user_id: str,
    history_rows: Iterable[dict],
    watchlist: WatchlistStore,
    alert_store: PerUserAlertStore,
    detected_at: datetime | None = None,
) -> list[dict]:
    """Evaluate deterministic watchlist alerts for one user.

    For every watched canonical opportunity with at least two history
    observations, diff the last two observations in canonical history order
    and persist the resulting typed alert events (deduped).

    - Non-watched opportunities never produce alerts for this user.
    - Unwatching stops future alerts; stored alerts are retained.
    - Missing != zero: absent/None fields never diff against an explicit 0.
    - A single-observation opportunity produces no change alerts.

    Returns the freshly created alert records (empty list when deduped).
    """
    detected_at = detected_at or datetime.now(timezone.utc)
    watched = watchlist.watched_uids(user_id)

    # Group history rows per opportunity in canonical (append) order.
    by_uid: dict[str, list[dict]] = {}
    for row in history_rows:
        uid = row.get("opportunity_uid")
        if uid in watched:
            by_uid.setdefault(uid, []).append(row)

    created: list[dict] = []
    for uid in sorted(by_uid):
        rows = by_uid[uid]
        if len(rows) < 2:
            continue  # need a previous and a current observation
        previous, current = rows[-2], rows[-1]
        ctx = DetectionContext(
            opportunity_uid=uid,
            previous=previous,
            current=current,
            previous_hash=previous.get("observation_hash", ""),
            current_hash=current.get("observation_hash", ""),
        )
        sensor = detect_changes(ctx)
        if not sensor.changes:
            continue
        events = alerts_for_detection(sensor, detected_at=detected_at)
        created_records = alert_store.create_from_events(user_id, events)
        created.extend(created_records)
    return created
