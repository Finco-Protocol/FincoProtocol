"""Canonical serialization, validation and deterministic R5 change detection."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from finco_radar.signals.contracts import GapDirection, SignalSnapshot, SizePersistenceState
from .contracts import HistoryEntry, HistoryError, HistoryStatus, SignalChange, SignalChangeKind


def canonical_snapshot_json(snapshot: SignalSnapshot) -> str:
    return json.dumps(snapshot.to_evidence_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_history_entry(snapshot: SignalSnapshot) -> HistoryEntry:
    payload = canonical_snapshot_json(snapshot).encode("utf-8")
    return HistoryEntry(snapshot.asset_uid, snapshot.canonical_key, snapshot.symbol,
                        snapshot.observed_at, snapshot, hashlib.sha256(payload).hexdigest(), snapshot.policy)


def validate_history_series(entries: tuple[HistoryEntry, ...]) -> None:
    if not entries:
        return
    first = entries[0]
    previous = None
    for entry in entries:
        snapshot = entry.signal_snapshot
        if (entry.asset_uid != snapshot.asset_uid or
                entry.canonical_key != snapshot.canonical_key or
                entry.symbol != snapshot.symbol or
                entry.observed_at != snapshot.observed_at or
                entry.policy != snapshot.policy):
            raise HistoryError(
                "history entry metadata does not match its embedded snapshot",
                HistoryStatus.HISTORY_EVIDENCE_INVALID,
            )
        if entry.observed_at.tzinfo is None:
            raise HistoryError("history timestamps must be timezone-aware", HistoryStatus.HISTORY_TIME_ORDER_INVALID)
        if entry.asset_uid != first.asset_uid or entry.canonical_key != first.canonical_key:
            raise HistoryError("history canonical identity mismatch", HistoryStatus.HISTORY_IDENTITY_MISMATCH)
        if entry.policy != first.policy:
            raise HistoryError("history policy mismatch", HistoryStatus.HISTORY_POLICY_MISMATCH)
        if previous is not None and entry.observed_at <= previous:
            raise HistoryError("history timestamps must strictly increase", HistoryStatus.HISTORY_TIME_ORDER_INVALID)
        if build_history_entry(entry.signal_snapshot).snapshot_digest != entry.snapshot_digest:
            raise HistoryError("snapshot digest does not reconstruct", HistoryStatus.HISTORY_EVIDENCE_INVALID)
        previous = entry.observed_at


def _material(snapshot: SignalSnapshot, assessment) -> bool:
    return (snapshot.signals_active and
            assessment.size_persistence_state is not SizePersistenceState.NO_MATERIAL_DISLOCATION)


def _direction(assessment) -> GapDirection | None:
    values = [d for d in (assessment.small_gap_direction, assessment.large_gap_direction)
              if d is not GapDirection.WITHIN_THRESHOLD]
    return values[-1] if values and all(d is values[0] for d in values) else None


def compare_signal_snapshots(previous: SignalSnapshot, current: SignalSnapshot) -> tuple[SignalChange, ...]:
    if previous.asset_uid != current.asset_uid or previous.canonical_key != current.canonical_key:
        raise HistoryError("snapshot identity mismatch", HistoryStatus.HISTORY_IDENTITY_MISMATCH)
    if previous.policy != current.policy:
        raise HistoryError("snapshot policy mismatch", HistoryStatus.HISTORY_POLICY_MISMATCH)
    if (previous.observed_at.tzinfo is None or current.observed_at.tzinfo is None or
            current.observed_at <= previous.observed_at):
        raise HistoryError("comparison timestamps must be aware and strictly increasing",
                           HistoryStatus.HISTORY_TIME_ORDER_INVALID)
    changes: list[SignalChange] = []
    authority_changed = (
        previous.signals_active != current.signals_active or
        previous.authority_state is not current.authority_state or
        previous.suppression_reasons != current.suppression_reasons
    )
    if authority_changed:
        changes.append(SignalChange(
            SignalChangeKind.AUTHORITY_STATE_CHANGED,
            None,
            {
                "signalsActiveBefore": previous.signals_active,
                "signalsActiveAfter": current.signals_active,
                "authorityStateBefore": previous.authority_state.value,
                "authorityStateAfter": current.authority_state.value,
                "suppressionReasonsBefore": [r.value for r in previous.suppression_reasons],
                "suppressionReasonsAfter": [r.value for r in current.suppression_reasons],
            },
        ))
    for before, after in ((previous.buy_assessment, current.buy_assessment),
                          (previous.sell_assessment, current.sell_assessment)):
        bm, am = _material(previous, before), _material(current, after)
        comparable = previous.signals_active and current.signals_active
        if current.signals_active and not bm and am:
            changes.append(SignalChange(SignalChangeKind.SIGNAL_APPEARED, after.side, {}))
        elif comparable and bm and not am:
            changes.append(SignalChange(SignalChangeKind.SIGNAL_CLEARED, after.side, {}))
        if comparable and bm and am and _direction(before) is not None and _direction(after) is not None and _direction(before) is not _direction(after):
            changes.append(SignalChange(SignalChangeKind.DIRECTION_CHANGED, after.side,
                                        {"before": _direction(before).value, "after": _direction(after).value}))
        if comparable and before.size_persistence_state is not after.size_persistence_state:
            changes.append(SignalChange(SignalChangeKind.SIZE_STATE_CHANGED, after.side,
                                        {"before": before.size_persistence_state.value, "after": after.size_persistence_state.value}))
        if comparable and (before.adverse_size_impact != after.adverse_size_impact or
                before.route_changed != after.route_changed):
            changes.append(SignalChange(SignalChangeKind.LIQUIDITY_CONTEXT_CHANGED, after.side,
                                        {"adverseSizeImpactBefore": before.adverse_size_impact,
                                         "adverseSizeImpactAfter": after.adverse_size_impact,
                                         "routeChangedBefore": before.route_changed,
                                         "routeChangedAfter": after.route_changed}))
        small_delta = after.small_gap_bps - before.small_gap_bps
        large_delta = after.large_gap_bps - before.large_gap_bps
        threshold = current.policy.material_history_change_bps
        if comparable and (abs(small_delta) >= threshold or abs(large_delta) >= threshold):
            changes.append(SignalChange(SignalChangeKind.MAGNITUDE_CHANGED, after.side,
                                        {"smallGapDeltaBps": str(small_delta), "largeGapDeltaBps": str(large_delta)}))
    if (previous.signals_active and current.signals_active and
            (previous.spread_small_state is not current.spread_small_state or
             previous.spread_large_state is not current.spread_large_state)):
        changes.append(SignalChange(SignalChangeKind.LIQUIDITY_CONTEXT_CHANGED, None,
                                    {"spreadSmallBefore": previous.spread_small_state.value,
                                     "spreadSmallAfter": current.spread_small_state.value,
                                     "spreadLargeBefore": previous.spread_large_state.value,
                                     "spreadLargeAfter": current.spread_large_state.value}))
    return tuple(changes) if changes else (SignalChange(SignalChangeKind.UNCHANGED, None, {}),)
