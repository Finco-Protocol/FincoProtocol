"""P1.3 — vertical validation runner.

Executes the live production engine for each vertical and evaluates the
ValidationMetric contracts from contracts.py against engine output.
Returns a machine-readable ValidationResult.

AUTHORITY: production engine via run_project() — clean G2C path only.
NO re-implementation of financial formulas here.
"""
from __future__ import annotations

import math
from typing import Any

from app.model_validation import CheckResult, ValidationResult
from app.model_validation.tolerances import TOLERANCES


VERTICAL_PROJECT_TYPES: dict[str, str] = {
    "solar": "Generic Solar Reference",
    "wind": "Generic Wind Reference",
    "data_center": "Generic Data Center Reference",
    "ev_charging": "Generic EV Charging Reference",
}


def _check(
    name: str,
    actual: Any,
    expected: Any,
    *,
    abs_tol: float | None = None,
    rel_tol: float | None = None,
    notes: str = "",
) -> CheckResult:
    if actual is None:
        return CheckResult(name=name, passed=False, actual=None, expected=expected,
                           notes=f"actual is None; {notes}")
    try:
        a = float(actual)
        e = float(expected)
        if abs_tol is not None:
            passed = abs(a - e) <= abs_tol
        elif rel_tol is not None:
            passed = math.isclose(a, e, rel_tol=rel_tol)
        else:
            passed = math.isclose(a, e, rel_tol=1e-6)
        return CheckResult(name=name, passed=passed, actual=a, expected=e,
                           tolerance=abs_tol or rel_tol, notes=notes)
    except (TypeError, ValueError) as exc:
        return CheckResult(name=name, passed=False, actual=actual, expected=expected,
                           notes=f"comparison error: {exc}")


def run_vertical_validation(vertical: str) -> ValidationResult:
    """Execute all P1.3 KPI checks for one vertical.

    Calls run_project() once, reads KPIs and sponsor_schedule, and
    evaluates each check against the published reference values.
    """
    project_type = VERTICAL_PROJECT_TYPES[vertical]
    from app.api.project_runner import run_project
    result = run_project(project_type, "Base")
    kpis = result["kpis"]
    sponsor = result.get("sponsor_schedule") or {}
    sponsor_summary = sponsor.get("summary") or {}

    checks: list[CheckResult] = []
    tol_irr = TOLERANCES["irr_abs"]
    tol_xirr = TOLERANCES["xirr_abs"]
    tol_rel = TOLERANCES["money_keur_rel"]

    if vertical == "solar":
        checks += [
            _check("project_irr", kpis.get("project_irr"), 0.11557, abs_tol=tol_irr),
            _check("equity_irr", kpis.get("equity_irr"), 0.50468, abs_tol=tol_irr),
            _check("total_sponsor_xirr",
                   sponsor_summary.get("total_sponsor_xirr"), 0.17896, abs_tol=tol_xirr),
            _check("senior_debt_keur", kpis.get("senior_debt_keur"), 24_750.0, rel_tol=tol_rel),
            _check("total_capex_keur", kpis.get("total_capex_keur"), 33_000.0, rel_tol=tol_rel),
        ]

    elif vertical == "wind":
        checks += [
            _check("project_irr", kpis.get("project_irr"), 0.13722, abs_tol=tol_irr),
            _check("equity_irr", kpis.get("equity_irr"), 0.74595, abs_tol=tol_irr),
            _check("total_sponsor_xirr",
                   sponsor_summary.get("total_sponsor_xirr"), 0.20794, abs_tol=tol_xirr),
            _check("senior_debt_keur", kpis.get("senior_debt_keur"), 32_250.0, rel_tol=tol_rel),
            _check("total_capex_keur", kpis.get("total_capex_keur"), 43_000.0, rel_tol=tol_rel),
        ]

    elif vertical == "data_center":
        checks += [
            _check("project_irr", kpis.get("project_irr"), 0.02293, abs_tol=0.005),
            _check("total_capex_keur", kpis.get("total_capex_keur"), 200_000.0, rel_tol=tol_rel),
            _check("senior_debt_keur", kpis.get("senior_debt_keur"), 80_436.5, abs_tol=500.0),
        ]

    elif vertical == "ev_charging":
        checks += [
            _check("project_irr", kpis.get("project_irr"), 0.14679, abs_tol=0.005),
            _check("equity_irr", kpis.get("equity_irr"), 0.39541, abs_tol=0.005),
            _check("total_capex_keur", kpis.get("total_capex_keur"), 9_000.0, rel_tol=tol_rel),
            _check("senior_debt_keur", kpis.get("senior_debt_keur"), 5_850.0, rel_tol=tol_rel),
        ]
    else:
        raise ValueError(f"Unknown vertical: {vertical!r}")

    return ValidationResult(vertical=vertical, project_type=project_type, checks=checks)
