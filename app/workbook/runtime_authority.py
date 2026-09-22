"""Canonical freshness authority for persisted Workbook V2 runtime evidence.

Freshness is a presentation/audit decision only.  It never runs the engine or
derives economics.  Modern workspaces compare the current composite workbook
identity with the identity committed by the last Run; legacy workspaces retain
the pre-composite scalar/dirty fallback.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class RuntimeAuthorityState(str, Enum):
    NOT_RUN = "NOT_RUN"
    CURRENT = "CURRENT"
    STALE = "STALE"


@dataclass(frozen=True)
class RuntimeFreshness:
    has_runtime: bool
    is_stale: bool
    state: RuntimeAuthorityState
    current_composite_hash: Optional[str]
    last_runtime_composite_hash: Optional[str]
    source: str


def resolve_runtime_freshness(
    ws: Any,
    *,
    current_composite_hash: Optional[str],
) -> RuntimeFreshness:
    """Resolve whether persisted Last Run evidence matches current inputs.

    A missing current hash on a modern row is fail-closed: Current cannot be
    proven, so the persisted result is classified STALE.
    """
    has_runtime = bool(
        getattr(ws, "last_runtime_snapshot_id", None)
        or (
            getattr(ws, "any_run_committed", False)
            and getattr(ws, "last_runtime_snapshot", None)
        )
    )
    last_hash = getattr(ws, "last_runtime_composite_hash", None) or None
    if not has_runtime:
        return RuntimeFreshness(
            False, False, RuntimeAuthorityState.NOT_RUN,
            current_composite_hash, last_hash, "no_runtime",
        )

    if last_hash:
        stale = not current_composite_hash or current_composite_hash != last_hash
        return RuntimeFreshness(
            True, stale,
            RuntimeAuthorityState.STALE if stale else RuntimeAuthorityState.CURRENT,
            current_composite_hash, last_hash,
            "composite_hash" if current_composite_hash else "identity_unresolved",
        )

    # Legacy rows predate run-bound composite identity.  Preserve their scalar
    # snapshot/dirty behavior without allowing it to affect the modern path.
    from app.persistence._helpers import snapshots_equal

    stale = bool(getattr(ws, "dirty", False)) or not snapshots_equal(
        getattr(ws, "draft_snapshot", None) or {},
        getattr(ws, "last_runtime_snapshot", None) or {},
    )
    return RuntimeFreshness(
        True, stale,
        RuntimeAuthorityState.STALE if stale else RuntimeAuthorityState.CURRENT,
        current_composite_hash, None, "legacy_scalar_fallback",
    )
