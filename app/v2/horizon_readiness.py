"""SC-08: guided explanation when a shortened project horizon leaves the shareholder-loan (SHL) maturity after the last modelled period.

Presentation only. The engine's fail-closed rule (the SHL maturity period must exist on the model's period grid) is unchanged and still stops a Run;
this helper only reads the same resolved inputs the Run would use, names the affected terms and horizon, and states the smallest whole-year
horizon whose grid contains the maturity. It never moves the maturity, edits an input, or runs the model.
"""
from __future__ import annotations

from dataclasses import replace as _replace
from typing import Any, Optional


def _grid(project: Any):
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import _build_period_engine
    return list(_build_period_engine(from_project_inputs(project)).periods())


def _run_rederives_indices(project: Any, project_record: Any, actor_user_id: Optional[str]) -> bool:
    """True when the real Run would NOT use the stored SHL indices as they are: the project is a proven factory-generic Working Copy, so the
    two period indices are re-derived from the effective geometry at Run (ON-08 OD-1(A)), or it is such a project whose geometry another
    existing refusal explains, or eligibility cannot be verified. Same helper and same persisted facts as the Run; read-only, nothing is written."""
    from app.services import on08_shl_index_authority as on08
    key = on08.runtime_key_for(project_record)
    if key is None or not actor_user_id:
        return False
    reference, factory = on08.persisted_reference_facts(project_record)
    try:
        _inputs, outcome = on08.apply_generic_shl_index_authority(
            project, project_record=project_record, actor_user_id=actor_user_id, owner_user_id=getattr(project_record, "user_id", None),
            runtime_project_key=key, canonical_reference=reference, factory_reference_inputs=factory,
            grid_last_provider=on08.effective_grid_last_index)
    except on08.On08ShlIndexRefusal:
        return True            # eligible lineage but not derivable: say nothing rather than fabricate a minimum or an unconditional refusal
    return outcome.status != on08.NOT_ELIGIBLE


def shl_horizon_notice(pis: Any, *, project_record: Any = None, actor_user_id: Optional[str] = None) -> Optional[dict]:
    """Return a notice dict when the SHL maturity period is not on the period grid for the current horizon, else None.

    ``None`` is also returned for a project whose Run re-derives the stored indices (see ``_run_rederives_indices``): the stored factory
    maturity is then not what the Run uses, so no minimum horizon is claimed."""
    try:
        project = pis.to_projectinputs()
        if project_record is not None and _run_rederives_indices(project, project_record, actor_user_id):
            return None
        maturity = getattr(project.financing, "shl_maturity_period_index", None)
        if not isinstance(maturity, int):
            return None
        periods = _grid(project)
        if not periods or maturity in {p.index for p in periods}:
            return None
        horizon = int(project.info.horizon_years)
        last = periods[-1]
        minimum = None
        for candidate in range(horizon + 1, 61):
            trial = _replace(project, info=_replace(project.info, horizon_years=candidate))
            if maturity in {p.index for p in _grid(trial)}:
                minimum = candidate
                break
        return {
            "maturity_period": maturity,
            "last_period": last.index,
            "last_period_end": last.end_date.isoformat(),
            "horizon_years": horizon,
            "min_horizon_years": minimum,
            "horizon_field_id": "project_setup.technical.horizon_years",
        }
    except Exception:           # advisory only: when the grid cannot be derived, say nothing rather than guess
        return None
