"""STAB-1A — Run / materialization integration for persisted OPEX custom sub-lines.

This module sits between the persistence layer (``app.persistence.opex_sub_lines``)
and the model layer (``finco_core.inputs.OpexItem``). Its single public function,
``apply_user_sub_lines_to_opex``, is the canonical wire-up that the /run route
calls in the user-created path — the **OPEX fold at the run boundary**.

Design
------
OPEX custom sub-lines are **additive**: each active sub-line becomes a new
``OpexItem`` appended to the existing opex tuple. This mirrors how the ViewModel
renders them (custom lines alongside factory lines), and is correct because:

1. B.09 "Fees" has no BOUND registry field and no base ``OpexItem`` in
   user-created projects — sub-lines create new costs where there were none.
2. B.01–B.08, B.10–B.12 groups may also carry custom sub-lines as genuinely
   additional costs on top of the base group total (not a decomposition of it).
3. The contingency ``OpexItem`` (``percentage_of_opex > 0``) is computed by the
   engine as a percentage of the sum of fixed items — appending new sub-line items
   automatically increases the contingency base, preserving that invariant without
   any special handling here.

Scenario overrides
------------------
If the active scenario carries an ``_opex_sub_line_overrides`` key in its
``overrides_json``, the map ``{sub_line_id: amount_keur}`` is used to REPLACE
the default sub-line amount for that run (override semantics mirror CAPEX).

Factory / template-seeded projects
-----------------------------------
Generic Wind Reference, Generic Solar Reference, Generic Solar, Generic Wind have no persisted sub-lines —
``apply_user_sub_lines_to_opex`` returns the input opex tuple unchanged.

Each sub-line becomes one ``OpexItem``:
  - ``name`` = ``sub_line.business_code``  (e.g. ``B.09.U001``; unique per project)
  - ``y1_amount_keur`` = effective amount (possibly overridden by scenario)
  - ``annual_inflation`` = ``sub_line.inflation_pct / 100``
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional, Sequence

from app.persistence.opex_sub_lines import (
    OpexSubLine,
    get_active_sub_lines_for_project,
)

logger = logging.getLogger(__name__)

# Reserved key in ``scenario.overrides_json`` for per-sub-line amount overrides.
_RESERVED_SUB_LINE_OVERRIDES_KEY = "_opex_sub_line_overrides"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_sub_line_overrides(
    scenario_overrides: Optional[Mapping[str, Any]],
) -> dict:
    """Extract the per-scenario OPEX sub-line override map.

    Returns:
        A ``{sub_line_id: amount_keur}`` dict. Empty when the scenario is the
        Base case (no overrides) or the reserved key is missing / malformed.
    """
    if not scenario_overrides:
        return {}
    raw = scenario_overrides.get(_RESERVED_SUB_LINE_OVERRIDES_KEY)
    if isinstance(raw, dict):
        return dict(raw)
    if raw is not None:
        logger.warning(
            "scenario_overrides[%r] is not a dict (%s); "
            "ignoring OPEX sub-line override map",
            _RESERVED_SUB_LINE_OVERRIDES_KEY,
            type(raw).__name__,
        )
    return {}


def _load_active_sub_lines(project_id: str) -> tuple[OpexSubLine, ...]:
    """Load active OPEX sub-lines for a project (is_active=1 only)."""
    rows = get_active_sub_lines_for_project(project_id)
    return tuple(rows)


def _resolve_effective_amount(
    base_amount: float,
    sub_line_id: str,
    overrides: dict,
) -> float:
    """Return the scenario-effective amount for one sub-line.

    Override REPLACES the base amount (not a delta), mirroring CAPEX semantics.
    """
    if sub_line_id in overrides:
        return float(overrides[sub_line_id])
    return float(base_amount)


# ---------------------------------------------------------------------------
# Core fold
# ---------------------------------------------------------------------------

def fold_sub_lines_into_opex(
    opex: Sequence,
    user_sub_lines: Sequence[OpexSubLine],
    *,
    scenario_overrides: dict | None = None,
) -> tuple:
    """Append active OPEX custom sub-lines as new OpexItems.

    Args:
        opex: the existing ``tuple[OpexItem, ...]`` from ``ProjectInputs``.
        user_sub_lines: active ``OpexSubLine`` records for the project.
        scenario_overrides: ``{sub_line_id: amount_keur}`` override map, or None.

    Returns:
        A new tuple with the original items plus one ``OpexItem`` per active
        custom sub-line.  If ``user_sub_lines`` is empty, returns ``opex``
        unchanged (same object — no allocation).
    """
    if not user_sub_lines:
        return tuple(opex)

    overrides = scenario_overrides or {}

    from finco_core.inputs import OpexItem

    new_items: list = list(opex)
    for sub in user_sub_lines:
        if not sub.is_active:
            continue
        effective_amount = _resolve_effective_amount(
            sub.amount_keur, sub.sub_line_id, overrides,
        )
        new_items.append(
            OpexItem(
                name=sub.business_code,
                y1_amount_keur=effective_amount,
                annual_inflation=sub.inflation_pct / 100.0,
            )
        )

    return tuple(new_items)


# ---------------------------------------------------------------------------
# Public entry point for run_service
# ---------------------------------------------------------------------------

def apply_user_sub_lines_to_opex(
    opex: Any,
    *,
    project_id: str,
    scenario_overrides: Optional[Mapping[str, Any]] = None,
) -> Any:
    """Fold persisted OPEX custom sub-lines into a ProjectInputs.opex tuple.

    This is the **explicit Run/materialization boundary** for STAB-1A.
    ``_execute_user_created_path`` in ``run_service.py`` calls this helper
    AFTER ``ProjectInputs`` is built from the snapshot, AFTER the CAPEX fold,
    and BEFORE the engine runs.

    Args:
        opex: the ``tuple[OpexItem, ...]`` from the current ``ProjectInputs``.
        project_id: the ``projects.project_id`` of the user project.
        scenario_overrides: the active scenario's ``overrides_json`` dict (or
            None for the Base case).  The reserved key
            ``_opex_sub_line_overrides`` carries ``{sub_line_id: amount_keur}``.

    Returns:
        A new tuple with sub-line items appended, or the original tuple
        unchanged if there are no active custom sub-lines.

    Design rules:
        - Factory / template-seeded projects (no persisted sub-lines) return
          opex unchanged — Generic Wind Reference/Generic Solar Reference parity preserved by construction.
        - Each sub-line → one ``OpexItem(name=business_code, y1=effective, inf=pct/100)``.
        - Fold is additive: existing items are untouched; sub-lines are appended.
        - The engine's contingency item (``percentage_of_opex > 0``) automatically
          picks up the new items because it sums ALL fixed items.
        - This function does NOT touch the formula path, Excel export, or UI.
    """
    if not project_id:
        return opex

    user_sub_lines = _load_active_sub_lines(project_id)
    if not user_sub_lines:
        return opex

    sub_line_overrides = _extract_sub_line_overrides(scenario_overrides)

    result = fold_sub_lines_into_opex(
        opex,
        user_sub_lines,
        scenario_overrides=sub_line_overrides,
    )

    if sub_line_overrides:
        active_uuids = {sub.sub_line_id for sub in user_sub_lines}
        for stale_uuid in set(sub_line_overrides) - active_uuids:
            logger.warning(
                "STAB-1A: scenario override for opex sub_line_id %s "
                "does not match any active sub-line; ignoring.",
                stale_uuid,
            )

    return result
