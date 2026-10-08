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

# Name of the single aggregate OpexItem the input adapter emits when the working
# copy's Y1 OPEX total differs from the factory per-item sum (e.g. any capacity
# other than the reference). ``app.input_adapter`` is the authority for the name.
_AGGREGATE_Y1_OPEX_NAME = "User provided year 1 operating expense"

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


def _load_all_sub_lines(project_id: str) -> tuple[OpexSubLine, ...]:
    """All OPEX sub-lines of a project, active and inactive (read-only)."""
    from app.persistence.db import get_cursor
    from app.persistence.opex_sub_lines import list_sub_lines_for_project

    with get_cursor() as cur:
        return tuple(list_sub_lines_for_project(cur, project_id, include_inactive=True))


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

# Marker persisted in a committed Run's identity (``opex_fold``).  Its presence
# proves the Run used the seed-replacement fold below; a Run without it used the
# earlier fold and cannot be reproduced exactly from its identity alone.
OPEX_FOLD_SEMANTICS = "seed_replace_v1"


def _is_seeded(sub: OpexSubLine) -> bool:
    return (
        sub.source in {"reference_seed", "user_override"}
        and sub.replay_metadata.get("reference_seed") is True
    )


def opex_fold_provenance(all_rows: Sequence[OpexSubLine]) -> dict:
    """Typed, JSON-safe record of what the seeded rows replace at the Run boundary.

    Derived only from immutable reference-seed provenance (``canonical_key``),
    never from editable labels.  Computed from ALL rows, active and inactive.
    """
    seeded = [r for r in all_rows if _is_seeded(r)]
    return {
        "semantics": OPEX_FOLD_SEMANTICS,
        "replaced_canonical_keys": sorted({
            r.replay_metadata["canonical_key"]
            for r in seeded if r.replay_metadata.get("canonical_key")
        }),
        "replaces_aggregate": bool(seeded),
        # Order in which the Run appended active rows (float summation order).
        "active_order": [r.sub_line_id for r in all_rows if r.is_active],
    }


def fold_opex_with_provenance(
    opex: Sequence,
    active_rows: Sequence[OpexSubLine],
    provenance: Mapping[str, Any],
    *,
    scenario_overrides: Optional[Mapping[str, Any]] = None,
) -> tuple:
    """The single OPEX fold used by the Run and by canonical Last Run export.

    Base items named by a replaced ``canonical_key`` (and the adapter's aggregate
    item when seeded rows exist) are dropped; active rows are appended.
    """
    replaced = set(provenance.get("replaced_canonical_keys") or ())
    drop_aggregate = bool(provenance.get("replaces_aggregate"))
    base_opex = tuple(
        item for item in opex
        if getattr(item, "name", None) not in replaced
        and not (drop_aggregate and getattr(item, "name", None) == _AGGREGATE_Y1_OPEX_NAME)
    )
    return fold_sub_lines_into_opex(
        base_opex, active_rows, scenario_overrides=dict(scenario_overrides or {}),
    )


def project_has_seeded_opex_rows(project_id: str) -> bool:
    """True when the project carries reference-seeded OPEX rows (any state)."""
    return any(_is_seeded(r) for r in _load_all_sub_lines(project_id))


def run_predates_opex_seed_replacement(project_id: Optional[str], identity: Any) -> bool:
    """True when a committed Run used the superseded OPEX fold and its project is affected.

    A Run is *affected* only if its identity lacks the ``opex_fold`` marker AND
    the project has seeded OPEX rows (where the earlier fold added the seeded
    decomposition on top of its base).  Projects without seeded rows fold
    identically under both semantics and are never invalidated.  A lookup
    failure is treated as affected (currency cannot be proven).
    """
    if not isinstance(identity, Mapping) or identity.get("opex_fold"):
        return False
    if not project_id:
        return False
    try:
        return project_has_seeded_opex_rows(project_id)
    except Exception:
        logger.exception("OPEX fold semantics lookup failed; project_id=%s", project_id)
        return True


def _fold_user_sub_lines_to_opex(
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

    all_rows = _load_all_sub_lines(project_id)
    user_sub_lines = tuple(r for r in all_rows if r.is_active)

    # Reference seed rows are a detailed representation of canonical items,
    # not additive user costs.  Identity comes only from immutable replay
    # provenance; the editable display label is never an authority key.  The
    # replaced set is derived from ALL seeded rows (active AND inactive) so that
    # deactivating every seeded line of a category removes its cost for good.
    provenance = opex_fold_provenance(all_rows)
    if not user_sub_lines and not provenance["replaces_aggregate"]:
        return opex

    sub_line_overrides = _extract_sub_line_overrides(scenario_overrides)
    result = fold_opex_with_provenance(
        opex, user_sub_lines, provenance, scenario_overrides=sub_line_overrides,
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


def apply_user_sub_lines_to_opex(
    opex: Any,
    *,
    project_id: str,
    scenario_overrides: Optional[Mapping[str, Any]] = None,
) -> Any:
    """Fold custom OPEX sub-lines, then apply the typed B.13 percentage.

    The percentage is evaluated by the engine period-by-period over the other
    OPEX groups; no authority => reference contingency rule untouched.
    """
    from app.contingency_authority import apply_opex_contingency
    from app.services.capex_sub_lines_integration import _load_contingency_pct

    folded = _fold_user_sub_lines_to_opex(
        opex, project_id=project_id, scenario_overrides=scenario_overrides,
    )
    if not project_id:
        return folded
    pct, _source = _load_contingency_pct(project_id, scenario_overrides, "opex")
    if pct is None:
        return folded
    return apply_opex_contingency(folded, pct)
