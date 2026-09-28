"""P1.3 — vertical validation runner.

Executes the live production engine for each vertical using
_build_export_bundle() as the SINGLE canonical run source.

Both runtime KPI checks (P1_3_RUNNER_CONSUMES_TYPED_CONTRACT) and
XLSX reconciliation checks use the same bundle object, guaranteeing
same-run identity (P1_3_SAME_CANONICAL_RUN_RECONCILIATION).

ARCHITECTURE
------------
1. _build_export_bundle(project_key) is called once per vertical.
2. BUNDLE_EXTRACTORS maps extractor_key → callable(bundle) → value.
3. run_vertical_validation() iterates ALL_CONTRACTS[vertical]; the runner
   reads extractor_key and expected_value from each ValidationMetric — no
   duplicate hardcoded expectations.
4. Known product gaps (pre-existing failures/NOT_AVAILABLE states) are
   collected from VERTICAL_GAPS and surfaced as ValidationGap objects in
   the returned ValidationResult.

AUTHORITY: production engine via _build_export_bundle() — clean G2C path only.
NO re-implementation of financial formulas here.
"""
from __future__ import annotations

import math
from typing import Any, Callable

from app.model_validation import CheckResult, ValidationGap, ValidationResult
from app.model_validation.contracts import ALL_CONTRACTS
from app.model_validation.tolerances import TOLERANCES


VERTICAL_PROJECT_TYPES: dict[str, str] = {
    "solar": "Generic Solar Reference",
    "wind": "Generic Wind Reference",
    "data_center": "Generic Data Center Reference",
    "ev_charging": "Generic EV Charging Reference",
}

# Maps extractor_key → callable(bundle) → scalar value
# All keys must correspond to registry_key entries in P1.1 (total_capex, initial_senior_debt, etc.)
BUNDLE_EXTRACTORS: dict[str, Callable] = {
    "project_irr": lambda b: b.runtime_result.project_irr,
    "equity_irr": lambda b: b.runtime_result.equity_irr,
    "total_sponsor_xirr": lambda b: b.runtime_result.sponsor_irr,
    "senior_debt_keur": lambda b: b.senior_debt_keur_authority,
    "total_capex_keur": lambda b: b.project_inputs.capex.total_capex,
}

# Tolerance policies that use relative comparison (rel_tol); all others use abs_tol
_REL_POLICIES: frozenset[str] = frozenset({"money_keur_rel", "xlsx_vs_runtime_rel"})

# Known pre-existing product gaps — surfaced in ValidationResult.gaps, not hidden
VERTICAL_GAPS: dict[str, list[ValidationGap]] = {
    "ev_charging": [
        ValidationGap(
            name="EV Sources=Uses reconciliation FAIL",
            vertical="ev_charging",
            category="xlsx_reconciliation",
            gap_type="FAIL",
            description=(
                "EV Charging workbook Sources vs Uses reconciliation check reports FAIL. "
                "Pre-existing limitation: EV-specific capital structure Sources & Uses "
                "reconciliation is not yet fully implemented in the workbook builder."
            ),
            registry_key="initial_senior_debt",
            notes="Carry to P1.4 for resolution.",
        ),
        ValidationGap(
            name="EV CAPEX line items sum vs context total FAIL",
            vertical="ev_charging",
            category="xlsx_reconciliation",
            gap_type="FAIL",
            description=(
                "EV Charging workbook CAPEX line items sum vs context total reports FAIL. "
                "Pre-existing limitation: CAPEX detail reconciliation not implemented for EV vertical."
            ),
            registry_key="total_capex",
            notes="Carry to P1.4 for resolution.",
        ),
    ],
    "data_center": [
        ValidationGap(
            name="DC Equity IRR NOT_AVAILABLE (distressed reference)",
            vertical="data_center",
            category="kpi_pinning",
            gap_type="NOT_AVAILABLE",
            description=(
                "Data Center distressed reference: equity_irr=None (sub-bankable by design, "
                "no positive equity return on 55% Y1 occupancy scenario). "
                "Returns sheet Equity IRR vs runtime = NOT_AVAILABLE."
            ),
            registry_key="equity_irr",
            notes=(
                "DC_A3_ECONOMICS_DISTRESSED_DOCUMENTED: synthetic distressed reference. "
                "Equity IRR is only computable when equity distributions > 0."
            ),
        ),
        ValidationGap(
            name="DC Total Sponsor XIRR NOT_AVAILABLE (distressed reference)",
            vertical="data_center",
            category="kpi_pinning",
            gap_type="NOT_AVAILABLE",
            description=(
                "Data Center distressed reference: sponsor_irr=None. "
                "Returns sheet Total Sponsor XIRR vs runtime = NOT_AVAILABLE."
            ),
            registry_key="total_sponsor_xirr",
        ),
    ],
}


def _check(
    name: str,
    actual: Any,
    expected: Any,
    *,
    abs_tol: float | None = None,
    rel_tol: float | None = None,
    tolerance_policy: str = "",
    notes: str = "",
) -> CheckResult:
    if actual is None:
        return CheckResult(
            name=name, passed=False, actual=None, expected=expected,
            tolerance_policy=tolerance_policy,
            notes=f"actual is None; {notes}",
        )
    try:
        a = float(actual)
        e = float(expected)
        if abs_tol is not None:
            passed = abs(a - e) <= abs_tol
        elif rel_tol is not None:
            passed = math.isclose(a, e, rel_tol=rel_tol)
        else:
            passed = math.isclose(a, e, rel_tol=1e-6)
        return CheckResult(
            name=name, passed=passed, actual=a, expected=e,
            tolerance=abs_tol if abs_tol is not None else rel_tol,
            tolerance_policy=tolerance_policy,
            notes=notes,
        )
    except (TypeError, ValueError) as exc:
        return CheckResult(
            name=name, passed=False, actual=actual, expected=expected,
            tolerance_policy=tolerance_policy,
            notes=f"comparison error: {exc}",
        )


def run_vertical_validation(vertical: str) -> ValidationResult:
    """Execute all P1.3 KPI checks for one vertical.

    Uses _build_export_bundle() as the SINGLE canonical run source.
    Iterates ALL_CONTRACTS[vertical] — no duplicate hardcoded expectations.
    Known product gaps are surfaced in ValidationResult.gaps.

    Markers satisfied:
      P1_3_RUNNER_CONSUMES_TYPED_CONTRACT
      P1_3_SAME_CANONICAL_RUN_RECONCILIATION
    """
    if vertical not in VERTICAL_PROJECT_TYPES:
        raise ValueError(f"Unknown vertical: {vertical!r}")

    project_type = VERTICAL_PROJECT_TYPES[vertical]
    project_key = project_type.lower().replace(" ", "_")

    from app.export.institutional_workbook import _build_export_bundle
    bundle = _build_export_bundle(project_key)

    checks: list[CheckResult] = []
    contract = ALL_CONTRACTS.get(vertical, ())

    for metric in contract:
        if metric.expected_value is None:
            continue  # XLSX-only or gap-only metric; skip KPI numeric check

        extractor = BUNDLE_EXTRACTORS.get(metric.extractor_key)
        if extractor is None:
            checks.append(CheckResult(
                name=metric.name,
                passed=False,
                actual=None,
                expected=metric.expected_value,
                tolerance_policy=metric.tolerance_policy,
                notes=f"No BUNDLE_EXTRACTORS entry for extractor_key={metric.extractor_key!r}",
            ))
            continue

        actual_value = extractor(bundle)
        policy = metric.tolerance_policy
        pol_val = TOLERANCES.get(policy)
        abs_tol: float | None = None
        rel_tol: float | None = None

        if pol_val is not None:
            if policy in _REL_POLICIES:
                rel_tol = pol_val
            else:
                abs_tol = pol_val

        checks.append(_check(
            metric.name,
            actual_value,
            metric.expected_value,
            abs_tol=abs_tol,
            rel_tol=rel_tol,
            tolerance_policy=policy,
            notes=metric.notes,
        ))

    gaps = list(VERTICAL_GAPS.get(vertical, []))

    return ValidationResult(
        vertical=vertical,
        project_type=project_type,
        checks=checks,
        gaps=gaps,
    )
