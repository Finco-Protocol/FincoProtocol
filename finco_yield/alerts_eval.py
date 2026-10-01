"""Deterministic checkpoint-based alert evaluation for Yield Alerts V1 (Agent A).

``evaluate_watchlist_alerts`` is the single deterministic callable a later
scheduler/refresh path invokes.  No scheduler, queue, cron, email, push or
chat infrastructure lives here.

Authorities (canonical only, no parallel stores):

    watched set        ``finco_yield.watchlist.list_watchlist_items``
    observations       canonical ``YieldHistoryStore.for_opportunity``
    freshness          canonical ``finco_yield.freshness.evaluate_freshness``
                       (CURRENT / STALE / INVALID / FUTURE_TIMESTAMP —
                       ``AVAILABLE`` is not a freshness state)
    support state      canonical registry ``resolve(uid).support_state``
    persistence        SQLite ``yield_alerts`` + ``yield_alert_state``

Pipeline per watched opportunity:

    watch lifecycle check (canonical ``saved_at`` vs checkpoint stamp)
    → first evaluation / re-watch: baseline at latest observation, NO alerts
    → every UNSEEN observation transition processed in canonical order;
      each transition is one ATOMIC unit (alert inserts + checkpoint
      advance commit together — a checkpoint can never advance past
      unpersisted alerts; persistence failures fail closed and retries
      re-derive the same deterministic alert_ids)
    → freshness re-evaluated canonically at evaluation time even when no
      new observation arrived (degradation works without new evidence)
    → registry support state compared EVEN WITHOUT new history
    → typed alerts persisted (deterministic alert_id, deduped)

Recovery semantics: FRESHNESS_RECOVERED and NEW_OBSERVATION require a
canonical DEGRADED state (STALE / INVALID / FUTURE_TIMESTAMP) followed by
CURRENT evidence on a NEW observation hash.  UNKNOWN or absent freshness
recovering to CURRENT is handled conservatively (checkpoint update only,
no recovery claim).  Routine CURRENT → CURRENT observations are silent.

Missing vs zero (V1 contract): MISSING (``None``/absent) observation
fields are never numerically interpreted as zero — no delta or economic
magnitude is ever computed from a missing value, and persisted alerts
keep previous/current verbatim.  A MISSING ↔ explicit-``0`` transition is
still a descriptive availability-state change and emits the field-change
alert with the true values (previous ``None``, current ``0``).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .alerts_store import commit_alert_state, get_checkpoint
from .alerts_types import (
    ALERT_TYPE_LABELS,
    STATE_ONLY_ALERT_TYPES,
    AlertType,
    deterministic_alert_id,
)

_STATE_ONLY_TYPES = STATE_ONLY_ALERT_TYPES

__all__ = ["evaluate_watchlist_alerts"]

# Economic observation fields tracked for change detection, in canonical
# alert order.  Freshness and support state are appended after these.
_TRACKED_FIELDS: tuple[str, ...] = ("apy_total", "tvl_usd", "apy_rewards")

_FIELD_ALERT_TYPE: dict[str, AlertType] = {
    "apy_total": AlertType.APY_CHANGED,
    "tvl_usd": AlertType.TVL_CHANGED,
    "apy_rewards": AlertType.REWARD_COMPONENT_CHANGED,
}

# Canonical freshness states that constitute degradation from CURRENT.
_DEGRADED_STATES = frozenset({"STALE", "INVALID", "FUTURE_TIMESTAMP"})

# Recovery claims are allowed only from these canonical degraded states.
# UNKNOWN or an absent checkpoint state never yields a recovery claim.
_RECOVERY_PREREQUISITES = _DEGRADED_STATES


# ── Row / value helpers ───────────────────────────────────────────────────────

def _row_field(row: dict, field: str):
    """Read one observed value from a history row.

    Rows may carry observation fields at top level or inside ``payload``.
    A truly absent key is MISSING; an explicitly stored ``None`` is also
    MISSING.  An explicit ``0`` is valid observed data.  MISSING values
    are never numerically interpreted — see the module contract above.
    """
    if field in row:
        return row[field]
    payload = row.get("payload")
    if isinstance(payload, dict) and field in payload:
        return payload[field]
    return None  # MISSING


def _scalar_key(value) -> str | None:
    """Canonical comparison key.  Numeric strings (canonical JSONL round-trip
    of Decimal) compare equal to the numbers they denote.  None → None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        if value.is_finite():
            return str(value.normalize())
        return str(value)
    if isinstance(value, (int, float)):
        return str(Decimal(str(value)).normalize())
    if isinstance(value, str):
        try:
            return str(Decimal(value).normalize())
        except InvalidOperation:
            return value
    return str(value)


def _values_differ(previous, current) -> bool:
    """Deterministic inequality.

    MISSING (None) is never CONVERTED to zero for comparison.  None vs an
    explicit 0 (either direction) is a genuine availability-state change;
    None vs None and 0 vs 0 are not changes.
    """
    return _scalar_key(previous) != _scalar_key(current)


def _row_observed_at(row: dict) -> datetime | None:
    raw = row.get("observed_at")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _source_ref_from_row(row: dict):
    """Reconstruct the canonical SourceReference from a history row."""
    from .schema import EvidenceConfidence, SourceReference

    raw_type = row.get("source_authority")
    if raw_type is None:
        return None
    try:
        source_type = EvidenceConfidence(str(raw_type))
    except ValueError:
        return None
    observed_at = _row_observed_at(row)
    if observed_at is None:
        return None
    return SourceReference(
        source_type=source_type,
        uri=str(row.get("source_uri", "")),
        observed_at=observed_at,
        block_number=row.get("block_number"),
        adapter_version=str(row.get("adapter_version", "y0.1")),
    )


def _row_freshness_state(row: dict, *, now: datetime, policy=None) -> str:
    """Canonical freshness state of one observation's evidence at ``now``."""
    from .freshness import evaluate_freshness

    source = _source_ref_from_row(row)
    if source is None:
        return "UNKNOWN"
    return evaluate_freshness(source, now=now, policy=policy).state


def _support_state(registry, opportunity_uid: str) -> str | None:
    """Canonical support state from THE registry (display fields ignored)."""
    from .registry import RegistryError, YieldSupportState

    try:
        opportunity = registry.resolve(opportunity_uid)
    except RegistryError:
        return None
    state = opportunity.support_state
    return state.value if isinstance(state, YieldSupportState) else str(state)


def _make_alert(
    *, user_id: str, opportunity_uid: str, alert_type: AlertType,
    field: str | None, previous, current,
    previous_hash: str, current_hash: str, detected_at: str,
    state_from: str | None = None, state_to: str | None = None,
) -> dict[str, Any]:
    state_only = alert_type in _STATE_ONLY_TYPES
    return {
        "alert_id": deterministic_alert_id(
            user_id=user_id,
            opportunity_uid=opportunity_uid,
            alert_type=alert_type.value,
            field=field,
            previous_observation_hash=previous_hash,
            current_observation_hash=current_hash,
            state_from=state_from if state_only else None,
            state_to=state_to if state_only else None,
        ),
        "opportunity_uid": opportunity_uid,
        "alert_type": alert_type.value,
        "label": ALERT_TYPE_LABELS[alert_type],
        "field": field,
        "previous": previous,
        "current": current,
        "previous_observation_hash": previous_hash,
        "current_observation_hash": current_hash,
        "detected_at": detected_at,
    }


# ── History sequencing ────────────────────────────────────────────────────────

def _canon_history(history_store, opportunity_uid: str) -> list[dict]:
    """Canonical observations in append order, hash-bearing only."""
    rows = history_store.for_opportunity(opportunity_uid)
    return [row for row in rows if row.get("observation_hash")]


def _unseen_after(history: list[dict], checkpoint_hash: str) -> list[dict] | None:
    """Rows strictly after the checkpoint hash, in canonical order.

    Returns None when the checkpoint hash is unknown to the history
    (e.g. pruned) — the caller then re-baselines instead of guessing.
    """
    for index, row in enumerate(history):
        if row["observation_hash"] == checkpoint_hash:
            return history[index + 1:]
    return None


# ── Evaluation ────────────────────────────────────────────────────────────────

def evaluate_watchlist_alerts(
    *,
    user_id: str,
    history_store,
    registry,
    now: datetime | None = None,
    freshness_policy=None,
) -> list[dict[str, Any]]:
    """Deterministic checkpoint-based alert evaluation for ONE user.

    - Watches exactly the canonical ``finco_yield.watchlist`` items.
    - First evaluation AND every re-watch (new watch lifecycle, detected
      via the canonical ``saved_at`` stamp) baseline at the latest
      observation and produce NO alerts — the unwatched period is never
      replayed.
    - Later evaluations process EVERY unseen observation transition in
      canonical order; each transition commits its alert inserts and the
      checkpoint advance in ONE transaction (fail closed, retry-safe).
    - Freshness degrades canonically at ``now`` even with no new
      observation; registry support state is compared independently of
      history.  Recovery and NEW_OBSERVATION require a canonical degraded
      state followed by CURRENT evidence on a NEW observation hash.

    Persistence failures propagate (fail closed): nothing is committed
    and the checkpoint does not move.
    """
    from .watchlist import list_watchlist_items

    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("evaluation clock must be timezone-aware")
    now = now.astimezone(timezone.utc)
    detected_at = now.isoformat()

    watched = [
        (item["opportunity_uid"], item.get("saved_at"))
        for item in list_watchlist_items(user_id)
    ]

    created: list[dict[str, Any]] = []
    for opportunity_uid, watch_saved_at in watched:
        history = _canon_history(history_store, opportunity_uid)
        if not history:
            continue
        created.extend(_evaluate_one(
            user_id=user_id,
            opportunity_uid=opportunity_uid,
            history=history,
            registry=registry,
            watch_saved_at=watch_saved_at,
            now=now,
            freshness_policy=freshness_policy,
            detected_at=detected_at,
        ))
    return created


def _evaluate_one(
    *, user_id: str, opportunity_uid: str, history: list[dict],
    registry, watch_saved_at: str | None,
    now: datetime, freshness_policy, detected_at: str,
) -> list[dict[str, Any]]:
    checkpoint = get_checkpoint(user_id, opportunity_uid)
    latest = history[-1]

    # Unknown checkpoint hash (pruned history) or a NEW watch lifecycle
    # (canonical saved_at stamp changed → the entry was removed and
    # re-added): fresh baseline at the latest observation, NO replay.
    new_lifecycle = (
        checkpoint is not None
        and checkpoint.get("watch_saved_at") != watch_saved_at
    )
    if checkpoint is None or new_lifecycle or _unseen_after(
            history, checkpoint["last_processed_observation_hash"]) is None:
        commit_alert_state(
            user_id, opportunity_uid, [],
            last_processed_observation_hash=latest["observation_hash"],
            last_freshness_state=_row_freshness_state(
                latest, now=now, policy=freshness_policy),
            last_support_state=_support_state(registry, opportunity_uid),
            watch_saved_at=watch_saved_at,
        )
        return []

    alerts: list[dict[str, Any]] = []
    unseen = _unseen_after(history, checkpoint["last_processed_observation_hash"]) or []
    previous = _row_at(history, checkpoint["last_processed_observation_hash"])
    fresh_state = checkpoint.get("last_freshness_state")
    support_state = checkpoint.get("last_support_state")

    for current in unseen:
        transition_alerts = _transition_alerts(
            user_id=user_id,
            opportunity_uid=opportunity_uid,
            previous=previous,
            current=current,
            previous_hash=previous["observation_hash"],
            checkpoint_freshness=fresh_state,
            checkpoint_support=support_state,
            registry=registry,
            now=now,
            freshness_policy=freshness_policy,
            detected_at=detected_at,
        )
        # Resolve the post-transition state, then commit alerts + checkpoint
        # as ONE atomic unit: the checkpoint never advances past alerts
        # that are not durably persisted.
        fresh_state = _row_freshness_state(
            current, now=now, policy=freshness_policy)
        support_state = _support_state(registry, opportunity_uid)
        alerts.extend(commit_alert_state(
            user_id, opportunity_uid, transition_alerts,
            last_processed_observation_hash=current["observation_hash"],
            last_freshness_state=fresh_state,
            last_support_state=support_state,
            watch_saved_at=watch_saved_at,
        ))
        previous = current

    # ── State-only phase (no new observation required) ──────────────────────
    alerts.extend(_state_only_alerts(
        user_id=user_id,
        opportunity_uid=opportunity_uid,
        latest=previous,
        fresh_state=fresh_state,
        support_state=support_state,
        registry=registry,
        watch_saved_at=watch_saved_at,
        now=now,
        freshness_policy=freshness_policy,
        detected_at=detected_at,
    ))
    return alerts


def _row_at(history: list[dict], observation_hash: str) -> dict:
    for row in history:
        if row["observation_hash"] == observation_hash:
            return row
    return history[0]


def _transition_alerts(
    *, user_id: str, opportunity_uid: str,
    previous: dict, current: dict,
    previous_hash: str, checkpoint_freshness: str | None,
    checkpoint_support: str | None,
    registry, now: datetime, freshness_policy, detected_at: str,
) -> list[dict[str, Any]]:
    """Typed alerts for ONE observation transition (prev hash → curr hash)."""
    current_hash = current["observation_hash"]
    alerts: list[dict[str, Any]] = []

    # Economic observation fields, canonical order.
    for field in _TRACKED_FIELDS:
        previous_value = _row_field(previous, field)
        current_value = _row_field(current, field)
        if _values_differ(previous_value, current_value):
            alerts.append(_make_alert(
                user_id=user_id, opportunity_uid=opportunity_uid,
                alert_type=_FIELD_ALERT_TYPE[field], field=field,
                previous=previous_value, current=current_value,
                previous_hash=previous_hash, current_hash=current_hash,
                detected_at=detected_at,
            ))

    # Freshness transition, canonical evaluate_freshness at evaluation time.
    current_fresh = _row_freshness_state(
        current, now=now, policy=freshness_policy)
    if checkpoint_freshness is not None and current_fresh != checkpoint_freshness:
        if current_fresh in _DEGRADED_STATES:
            alerts.append(_make_alert(
                user_id=user_id, opportunity_uid=opportunity_uid,
                alert_type=AlertType.FRESHNESS_DEGRADED,
                field="freshness_state",
                previous=checkpoint_freshness, current=current_fresh,
                previous_hash=previous_hash, current_hash=current_hash,
                detected_at=detected_at,
                state_from=checkpoint_freshness, state_to=current_fresh,
            ))
        elif (current_fresh == "CURRENT"
                and checkpoint_freshness in _RECOVERY_PREREQUISITES
                and current_hash != previous_hash):
            # Recovery claim requires: canonical DEGRADED → CURRENT on a
            # NEW observation.  UNKNOWN/None → CURRENT never claims it.
            alerts.append(_make_alert(
                user_id=user_id, opportunity_uid=opportunity_uid,
                alert_type=AlertType.FRESHNESS_RECOVERED,
                field="freshness_state",
                previous=checkpoint_freshness, current=current_fresh,
                previous_hash=previous_hash, current_hash=current_hash,
                detected_at=detected_at,
                state_from=checkpoint_freshness, state_to=current_fresh,
            ))
            alerts.append(_make_alert(
                user_id=user_id, opportunity_uid=opportunity_uid,
                alert_type=AlertType.NEW_OBSERVATION,
                field=None, previous=None, current=None,
                previous_hash=previous_hash, current_hash=current_hash,
                detected_at=detected_at,
            ))

    # Support state, resolved through THE canonical registry.
    if checkpoint_support is not None:
        current_support = _support_state(registry, opportunity_uid)
        if current_support is not None and current_support != checkpoint_support:
            alerts.append(_make_alert(
                user_id=user_id, opportunity_uid=opportunity_uid,
                alert_type=AlertType.SUPPORT_STATE_CHANGED,
                field="support_state",
                previous=checkpoint_support, current=current_support,
                previous_hash=previous_hash, current_hash=current_hash,
                detected_at=detected_at,
                state_from=checkpoint_support, state_to=current_support,
            ))

    return alerts


def _state_only_alerts(
    *, user_id: str, opportunity_uid: str, latest: dict,
    fresh_state: str | None, support_state: str | None,
    registry, watch_saved_at: str | None,
    now: datetime, freshness_policy, detected_at: str,
) -> list[dict[str, Any]]:
    """Registry/evaluator state changes while economic evidence stands still.

    Canonical freshness is re-evaluated at ``now`` and the canonical
    registry support state is resolved — both INDEPENDENTLY of whether a
    new observation arrived.  Alerts + the state-only checkpoint update
    commit as one atomic unit (persisted BEFORE the checkpoint advances).

    Without a new observation no recovery claim is possible: only
    degradation alerts here; a CURRENT reading without new evidence just
    updates the checkpoint conservatively.
    """
    alerts: list[dict[str, Any]] = []
    new_fresh = fresh_state
    new_support = support_state

    current_fresh = _row_freshness_state(
        latest, now=now, policy=freshness_policy)
    if fresh_state is not None and current_fresh != fresh_state:
        if current_fresh in _DEGRADED_STATES:
            alerts.append(_make_alert(
                user_id=user_id, opportunity_uid=opportunity_uid,
                alert_type=AlertType.FRESHNESS_DEGRADED,
                field="freshness_state",
                previous=fresh_state, current=current_fresh,
                previous_hash=latest["observation_hash"],
                current_hash=latest["observation_hash"],
                detected_at=detected_at,
                state_from=fresh_state, state_to=current_fresh,
            ))
        new_fresh = current_fresh  # degraded or conservative recovery

    current_support = _support_state(registry, opportunity_uid)
    if (support_state is not None and current_support is not None
            and current_support != support_state):
        alerts.append(_make_alert(
            user_id=user_id, opportunity_uid=opportunity_uid,
            alert_type=AlertType.SUPPORT_STATE_CHANGED,
            field="support_state",
            previous=support_state, current=current_support,
            previous_hash=latest["observation_hash"],
            current_hash=latest["observation_hash"],
            detected_at=detected_at,
            state_from=support_state, state_to=current_support,
        ))
        new_support = current_support

    if alerts or new_fresh != fresh_state or new_support != support_state:
        commit_alert_state(
            user_id, opportunity_uid, alerts,
            last_processed_observation_hash=latest["observation_hash"],
            last_freshness_state=new_fresh,
            last_support_state=new_support,
            watch_saved_at=watch_saved_at,
        )
    return alerts
