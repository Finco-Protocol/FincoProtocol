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


def shl_horizon_notice(pis: Any) -> Optional[dict]:
    """Return a notice dict when the SHL maturity period is not on the period grid for the current horizon, else None."""
    try:
        project = pis.to_projectinputs()
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
