"""FINCO Crypto alerts consumption boundary.

The presentation contract remains deliberately smaller than the Yield Alerts
domain. Production resolves the concrete Yield gateway lazily; tests and
other bounded consumers may still inject a gateway explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

ALERTS_SCHEMA_VERSION = "finco-crypto-alerts-boundary-v0"
ALERTS_INTEGRATION_PENDING = "ALERTS_INTEGRATION_PENDING"


@dataclass(frozen=True)
class AlertsSnapshot:
    """Typed alerts state for presentation."""

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


def auth_required_snapshot() -> AlertsSnapshot:
    """Anonymous identity never reaches the user-scoped alert backend."""
    return AlertsSnapshot(
        available=False,
        reason="ALERTS_AUTH_REQUIRED",
        unread_count=None,
        items=(),
    )


class AlertsGateway(Protocol):
    """Presentation interface implemented by the Yield Alerts adapter."""

    def snapshot(self, user_id: str) -> AlertsSnapshot: ...

    def mark_read(self, user_id: str, alert_id: str) -> bool: ...

    def mark_all_read(self, user_id: str) -> int: ...


class IntegrationPendingGateway:
    """Explicit placeholder retained for bounded tests/fallbacks."""

    def snapshot(self, user_id: str) -> AlertsSnapshot:
        return AlertsSnapshot(
            available=False,
            reason=ALERTS_INTEGRATION_PENDING,
            unread_count=None,
            items=(),
        )

    def mark_read(self, user_id: str, alert_id: str) -> bool:
        return False

    def mark_all_read(self, user_id: str) -> int:
        return 0


# None means production has not resolved the concrete adapter yet. Resolution
# is lazy to avoid import cycles: YieldAlertsGateway imports AlertsSnapshot.
_GATEWAY: AlertsGateway | None = None


def get_alerts_gateway() -> AlertsGateway:
    global _GATEWAY
    if _GATEWAY is None:
        from app.yield_alerts_gateway import YieldAlertsGateway
        _GATEWAY = YieldAlertsGateway()
    return _GATEWAY


def set_alerts_gateway(gateway: AlertsGateway) -> None:
    """Install an explicit gateway (primarily an integration/test seam)."""
    global _GATEWAY
    _GATEWAY = gateway


def reset_alerts_gateway(*, pending: bool = True) -> None:
    """Reset the seam for tests or bounded integration checks.

    The historical C-suite contract expects a reset to restore its explicit
    pending placeholder. Production never needs this helper: module startup
    begins with ``_GATEWAY = None`` and lazily resolves the real Yield gateway.
    Pass ``pending=False`` when a test intentionally wants production-style
    lazy resolution.
    """
    global _GATEWAY
    _GATEWAY = IntegrationPendingGateway() if pending else None
