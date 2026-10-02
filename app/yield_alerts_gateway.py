"""Concrete FINCO Yield Alerts -> Crypto UX integration boundary.

This module is deliberately narrow.  Alert economics, checkpointing and
persistence remain owned by ``finco_yield.alerts_*``; this adapter only maps
that domain snapshot into the presentation contract and exposes an explicit
manual refresh action over the canonical Yield history/registry authorities.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3

from app.crypto_alerts import AlertsSnapshot

_HISTORY_ENV = "FINCO_YIELD_HISTORY_PATH"


@dataclass(frozen=True)
class AlertsRefreshResult:
    """Typed result of one explicit, authenticated alert evaluation."""

    available: bool
    reason: str | None
    created_count: int | None
    snapshot: AlertsSnapshot

    def public_dict(self) -> dict:
        return {
            "state": "REFRESHED" if self.available else "UNAVAILABLE",
            "reason": self.reason,
            "created_count": self.created_count,
            "alerts": self.snapshot.public_dict(),
        }


@dataclass(frozen=True)
class AlertsEvaluationOutcome:
    """Typed result of one user's canonical evaluation (no snapshot)."""

    available: bool
    reason: str | None
    created_count: int | None


class YieldAlertsGateway:
    """Presentation adapter over Agent A's canonical alert backend."""

    @staticmethod
    def _map_item(alert: dict, registry) -> dict:
        item = {
            "alert_id": alert["alert_id"],
            "alert_type": alert.get("alert_type"),
            "opportunity_uid": alert.get("opportunity_uid"),
            "label": alert.get("label"),
            "field": alert.get("field"),
            "previous": alert.get("previous"),
            "current": alert.get("current"),
            "detected_at": alert.get("detected_at"),
            "read": bool(alert.get("read")),
        }
        uid = item["opportunity_uid"]
        if uid:
            try:
                # Exact canonical UID resolution only.  Never ticker/name/fuzzy lookup.
                item["opportunity_display"] = registry.resolve(uid).name
            except Exception:
                # A stale persisted alert may outlive a registry entry.  Identity remains
                # the canonical UID; display enrichment is optional and non-authoritative.
                pass
        return item

    def snapshot(self, user_id: str) -> AlertsSnapshot:
        from finco_yield.alerts_core import alerts_snapshot
        from finco_yield.registry import load_bundled_registry

        try:
            raw = alerts_snapshot(user_id)
            registry = load_bundled_registry()
            items = tuple(self._map_item(alert, registry) for alert in raw["alerts"])
            return AlertsSnapshot(
                available=True,
                reason=None,
                unread_count=int(raw["unread_count"]),
                items=items,
            )
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
            return AlertsSnapshot(
                available=False,
                reason="ALERTS_BACKEND_UNAVAILABLE",
                unread_count=None,
                items=(),
            )

    def mark_read(self, user_id: str, alert_id: str) -> bool:
        from finco_yield.alerts_core import mark_read
        return mark_read(user_id, alert_id)

    def mark_all_read(self, user_id: str) -> int:
        from finco_yield.alerts_core import mark_all_read
        return mark_all_read(user_id)

    @staticmethod
    def _history_store():
        """Return the canonical configured history store or a typed reason.

        Missing/unreadable/malformed history is unavailable, never equivalent
        to a valid empty history file.
        """
        from finco_yield.history import YieldHistoryStore

        raw_path = (os.getenv(_HISTORY_ENV) or "").strip()
        if not raw_path:
            return None, "YIELD_HISTORY_UNAVAILABLE"
        path = Path(raw_path)
        try:
            if not path.is_file():
                return None, "YIELD_HISTORY_UNAVAILABLE"
            store = YieldHistoryStore(path)
            rows = store.read_all()
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            return None, "YIELD_HISTORY_UNAVAILABLE"

        # A valid empty file is valid zero evidence.  Structurally malformed rows
        # are unavailable rather than silently treated as no observations.
        for row in rows:
            if not isinstance(row, dict):
                return None, "YIELD_HISTORY_UNAVAILABLE"
            if "opportunity_uid" not in row or "observation_hash" not in row:
                return None, "YIELD_HISTORY_UNAVAILABLE"
        return store, None

    @classmethod
    def resolve_inputs(cls):
        """Canonical evaluation inputs: ``(history_store, registry, reason)``.

        One resolution used by manual Refresh AND background evaluation, so the
        two paths can never disagree about what "unavailable" means.  ``reason``
        is a typed code when either input is unavailable.
        """
        from finco_yield.registry import load_bundled_registry

        history_store, history_reason = cls._history_store()
        if history_store is None:
            return None, None, history_reason
        try:
            registry = load_bundled_registry()
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None, None, "YIELD_REGISTRY_UNAVAILABLE"
        return history_store, registry, None

    @classmethod
    def evaluate_user(cls, user_id: str, *, history_store=None, registry=None,
                      now=None) -> "AlertsEvaluationOutcome":
        """Evaluate ONE user's canonical watchlist once (THE shared core).

        Manual Refresh and the background runner both call this function; the
        transition logic stays in ``finco_yield.alerts_eval``.  Inputs are
        resolved here unless the caller already resolved them once for a batch.
        ``now`` is passed through to the canonical evaluator (None = its clock).
        """
        from finco_yield.alerts_core import evaluate_watchlist_alerts

        if history_store is None or registry is None:
            history_store, registry, reason = cls.resolve_inputs()
            if reason is not None:
                return AlertsEvaluationOutcome(False, reason, None)
        try:
            created = evaluate_watchlist_alerts(
                user_id=user_id,
                history_store=history_store,
                registry=registry,
                now=now,
            )
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
            return AlertsEvaluationOutcome(False, "ALERT_EVALUATION_UNAVAILABLE", None)
        return AlertsEvaluationOutcome(True, None, len(created))

    def refresh(self, user_id: str) -> AlertsRefreshResult:
        """Evaluate watched opportunities once against canonical authorities."""
        outcome = self.evaluate_user(user_id)
        return AlertsRefreshResult(
            available=outcome.available,
            reason=outcome.reason,
            created_count=outcome.created_count,
            snapshot=self.snapshot(user_id),
        )
