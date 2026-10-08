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


def pre_scenario_base_equivalent(
    cursor: Any,
    *,
    draft_snapshot_json: str,
    project_id: str,
    user_id: str,
    scenario: Any,
    last_runtime_scenario_id: Optional[str],
    last_hash: Optional[str],
) -> bool:
    """Narrow Base compatibility rule for runs committed before scenarios existed.

    The canonical identity defines ``scenario_id=None`` as the Base Case. A Base
    run committed before the Base scenario row existed therefore carries a
    composite hash computed under that None convention, while the explicit Base
    row hashes with its own id. Presentation/freshness may treat the two as the
    same state ONLY when ALL hold, positively proven:

      * ``scenario`` is the canonical Base Case,
      * the Base Case has no economic overrides,
      * the run recorded no scenario id (pre-scenario),
      * recomputing the identity under the None convention reproduces the
        run's original composite hash exactly.

    Pure freshness decision: nothing about the run's provenance is rewritten.
    No non-Base scenario can ever satisfy this. Any error fails closed (False).
    """
    try:
        if (scenario is None or not getattr(scenario, "is_base_case", False)
                or getattr(scenario, "overrides", None)
                or last_runtime_scenario_id or not last_hash):
            return False
        from app.workbook.registry import WORKBOOK
        from app.workbook.workbook_identity import assemble_transactional

        legacy = assemble_transactional(
            draft_snapshot_json=draft_snapshot_json,
            project_id=project_id, user_id=user_id,
            active_scenario_id=None, active_scenario_name=None,
            cursor=cursor, workbook_version=WORKBOOK.version,
        )
        return legacy.composite_hash == last_hash
    except Exception:
        return False


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
        if stale and current_composite_hash and _base_equivalence_holds(ws, last_hash):
            return RuntimeFreshness(
                True, False, RuntimeAuthorityState.CURRENT,
                current_composite_hash, last_hash, "pre_scenario_base_equivalence",
            )
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


def _base_equivalence_holds(ws: Any, last_hash: str) -> bool:
    """Evaluate :func:`pre_scenario_base_equivalent` for a persisted workspace."""
    try:
        if getattr(ws, "last_runtime_scenario_id", None):
            return False
        scenario_id = getattr(ws, "active_scenario_id", None)
        user_id = getattr(ws, "user_id", None)
        project_id = getattr(ws, "project_id", None)
        if not (scenario_id and user_id and project_id):
            return False
        import json

        from app.persistence.db import get_cursor
        from app.persistence.scenarios_repository import get_scenario

        scenario = get_scenario(scenario_id, user_id)
        with get_cursor() as cur:
            return pre_scenario_base_equivalent(
                cur,
                draft_snapshot_json=json.dumps(getattr(ws, "draft_snapshot", None) or {}),
                project_id=project_id, user_id=user_id, scenario=scenario,
                last_runtime_scenario_id=None, last_hash=last_hash,
            )
    except Exception:
        return False
