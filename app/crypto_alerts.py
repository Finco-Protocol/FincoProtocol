"""FINCO crypto alerts consumption boundary (utility UX V1, Agent C).

UI/API consumption contract for the future in-app alert engine
(unread count / alert list / mark read / mark all read).  This module is
the BOUNDARY ONLY — it is NOT an alert scheduler, delivery platform, or
notification service.  The real alerts backend is built separately; Agent
D connects it here via :func:`set_alerts_gateway`.

Until a real gateway is installed the default gateway is an honest typed
placeholder: ``available=False``, reason ``ALERTS_INTEGRATION_PENDING``.
Nothing fabricates alerts, unread counts, or delivery claims — and
``/yield/monitor`` remains the Wallet Monitor, never a relabelled alerts
surface.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

ALERTS_SCHEMA_VERSION = "finco-crypto-alerts-boundary-v0"

ALERTS_INTEGRATION_PENDING = "ALERTS_INTEGRATION_PENDING"


@dataclass(frozen=True)
class AlertsSnapshot:
    """Typed alerts state for presentation. ``available`` is False until a
    real gateway is connected; ``unread_count`` is None when unknown."""

    available: bool
    reason: str | None
    unread_count: Optional[int]
    items: tuple[dict, ...]

    def public_dict(self) -> dict:
        return {
            "schema_version": ALERTS_SCHEMA_VERSION,
            "available": self.available,
            "reason": self.reason,
            "unread_count": self.unread_count,
            "items": list(self.items),
        }


class AlertsGateway(Protocol):
    """Interface the real alerts backend implements (Agent A / Agent D)."""

    def snapshot(self, user_id: str) -> AlertsSnapshot: ...

    def mark_read(self, user_id: str, alert_id: str) -> bool: ...

    def mark_all_read(self, user_id: str) -> int: ...


class IntegrationPendingGateway:
    """Honest placeholder: no alert engine is shipped yet."""

    def snapshot(self, user_id: str) -> AlertsSnapshot:
        return AlertsSnapshot(available=False, reason=ALERTS_INTEGRATION_PENDING,
                              unread_count=None, items=())

    def mark_read(self, user_id: str, alert_id: str) -> bool:
        return False

    def mark_all_read(self, user_id: str) -> int:
        return 0


_GATEWAY: AlertsGateway = IntegrationPendingGateway()


def get_alerts_gateway() -> AlertsGateway:
    """The installed alerts gateway (integration-pending placeholder by default)."""
    return _GATEWAY


def set_alerts_gateway(gateway: AlertsGateway) -> None:
    """Install a real alerts gateway (integration point — not used in prod yet)."""
    global _GATEWAY
    _GATEWAY = gateway


def reset_alerts_gateway() -> None:
    """Restore the integration-pending placeholder (test housekeeping)."""
    global _GATEWAY
    _GATEWAY = IntegrationPendingGateway()
