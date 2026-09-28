"""B2.3 Usage/Metering — extension hooks and interfaces.

Provides hook interfaces for future MCP tool call integration and
Trust Pack premium access metering. No MCP integration is wired in V1.

Usage recording hooks are invoked AFTER the access/entitlement decision.
They never affect financial math, verification truth, or evidence validity.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol, runtime_checkable


@runtime_checkable
class UsageHook(Protocol):
    """Callback interface for post-access usage recording.

    Implementations must be non-blocking and must not raise exceptions
    that propagate to the caller. They must not call financial engine code
    or Verify/authority code.
    """

    def on_feature_accessed(
        self,
        *,
        session,
        feature_key: str,
        quantity: int = 1,
        unit: str = "request",
        idempotency_key: str | None = None,
        occurred_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Called after a successful access/entitlement decision."""
        ...


class RecorderUsageHook:
    """Wires a UsageRecorder to the UsageHook interface.

    Swallow all exceptions — usage recording must never block the caller.
    """

    def __init__(self, recorder) -> None:
        self._recorder = recorder

    def on_feature_accessed(
        self,
        *,
        session,
        feature_key: str,
        quantity: int = 1,
        unit: str = "request",
        idempotency_key: str | None = None,
        occurred_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> None:
        try:
            self._recorder.record(
                session=session,
                feature_key=feature_key,
                quantity=quantity,
                unit=unit,
                idempotency_key=idempotency_key,
                occurred_at=occurred_at,
                metadata=metadata or {},
            )
        except Exception:
            pass


class McpToolCallHookInterface:
    """Placeholder hook for future MCP tool call metering.

    Not integrated in V1. Callers import this interface and wire it in
    once the MCP branch is ready. The feature_key is FEATURE_MCP_TOOL_CALL.
    """

    _hook: UsageHook | None = None

    @classmethod
    def register(cls, hook: UsageHook) -> None:
        cls._hook = hook

    @classmethod
    def record_tool_call(
        cls,
        *,
        session,
        tool_name: str,
        idempotency_key: str | None = None,
    ) -> None:
        if cls._hook is None:
            return
        from app.usage.contracts import FEATURE_MCP_TOOL_CALL
        cls._hook.on_feature_accessed(
            session=session,
            feature_key=FEATURE_MCP_TOOL_CALL,
            quantity=1,
            unit="tool_call",
            idempotency_key=idempotency_key,
            metadata={"feature_variant": tool_name[:64] if tool_name else ""},
        )


class TrustPackAccessHookInterface:
    """Placeholder hook for future Trust Pack premium access metering.

    Not integrated in V1. Callers import this interface once Trust Pack
    premium access is approved. The feature_key is FEATURE_TRUST_PACK_ACCESS.

    B2.2 entitlement determines whether access is allowed. This hook records
    usage AFTER the access decision. It never determines whether access is
    granted.
    """

    _hook: UsageHook | None = None

    @classmethod
    def register(cls, hook: UsageHook) -> None:
        cls._hook = hook

    @classmethod
    def record_access(
        cls,
        *,
        session,
        idempotency_key: str | None = None,
    ) -> None:
        if cls._hook is None:
            return
        from app.usage.contracts import FEATURE_TRUST_PACK_ACCESS
        cls._hook.on_feature_accessed(
            session=session,
            feature_key=FEATURE_TRUST_PACK_ACCESS,
            quantity=1,
            unit="access",
            idempotency_key=idempotency_key,
        )
