"""P1.3 Institutional Validation & Reconciliation Pack — typed validation framework.

Provides machine-readable, traceable validation contracts for all four live
FINCO Model verticals (Solar, Wind, Data Center, EV Charging).

USAGE
-----
    from app.model_validation import ValidationMetric, CheckResult, ValidationResult
    from app.model_validation.runner import run_vertical_validation

    result = run_vertical_validation("solar")
    assert result.passed, result.fail_count

The module is read-only with respect to financial logic: it consumes
production engine output and asserts toleranced equality; it never modifies
inputs or re-implements financial formulas.

SCOPE
-----
P1.3 validation covers:
  - Absolute KPI pinning (all four verticals)
  - XLSX workbook reconciliation sheet audit
  - Balance sheet component identity
  - Debt roll-forward per-period
  - Cash waterfall identity
  - Cross-surface reconciliation (runtime KPI == XLSX)
  - G2C waterfall gate structure
  - XIRR date-axis convention proof

VALIDATION CATEGORIES
---------------------
kpi_pinning          — runtime KPI vs. published reference value
xlsx_reconciliation  — XLSX Returns/Reconciliation sheet vs. runtime
statements           — balance sheet, P&L, cash flow identity
debt                 — debt roll-forward per-period
waterfall            — cash waterfall identity
returns              — IRR/XIRR convention proof
identity             — run identity, snapshot, engine version
g2c                  — G2C gate structure and component coverage

GAP TYPES
---------
FAIL           — a real product reconciliation failure (not a test failure)
NOT_AVAILABLE  — the quantity cannot be computed for this vertical/scenario
NOT_SUPPORTED  — the surface is not wired up for this vertical
NOT_APPLICABLE — the check is architecturally not relevant for this vertical

FROZEN NAMESPACES
-----------------
financial_engine/**  = ZERO DIFF
finco_core/**        = ZERO DIFF
finco_radar/**       = ZERO DIFF
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ValidationMetric:
    """Declares what to validate, against which registry authority, at what tolerance.

    Fields
    ------
    name              Human-readable check label.
    registry_key      P1.1 registry key for the economic quantity being checked.
    tolerance_policy  Named key in TOLERANCES dict.
    vertical          Target vertical ('solar', 'wind', 'data_center', 'ev_charging').
    category          Validation category ('kpi_pinning', 'xlsx_reconciliation', etc.).
    extractor_key     Key in BUNDLE_EXTRACTORS for runtime value extraction.
    expected_value    Typed float — the reference value to check against (None = XLSX/gap only).
    expected_state    Expected string state for XLSX or gap checks ('PASS', 'NOT_AVAILABLE', etc.).
    assertion         Human-readable description of the assertion (documentation only).
    notes             Additional context.
    """
    name: str
    registry_key: str
    tolerance_policy: str
    vertical: str
    category: str
    extractor_key: str
    expected_value: float | None = None
    expected_state: str = ""
    assertion: str = ""
    notes: str = ""


@dataclass(frozen=True)
class ValidationGap:
    """A known product gap surfaced in the validation result.

    These are real product limitations — not validation framework failures.
    A ValidationResult may PASS while containing ValidationGap entries that
    document honest, unresolved product deficiencies for institutional review.
    """
    name: str
    vertical: str
    category: str
    gap_type: str  # "FAIL" | "NOT_AVAILABLE" | "NOT_SUPPORTED" | "NOT_APPLICABLE"
    description: str
    registry_key: str = ""
    notes: str = ""


@dataclass
class CheckResult:
    """Outcome of one named validation check."""
    name: str
    passed: bool
    actual: Any
    expected: Any
    tolerance: float | None = None
    tolerance_policy: str = ""
    notes: str = ""

    def __repr__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"CheckResult({status!r}, {self.name!r}, actual={self.actual!r})"


@dataclass
class ValidationResult:
    """Aggregated outcome for one vertical's validation run."""
    vertical: str
    project_type: str
    checks: list[CheckResult] = field(default_factory=list)
    gaps: list[ValidationGap] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]

    def gaps_by_type(self, gap_type: str) -> list[ValidationGap]:
        return [g for g in self.gaps if g.gap_type == gap_type]

    def summary(self) -> dict[str, Any]:
        return {
            "vertical": self.vertical,
            "project_type": self.project_type,
            "passed": self.passed,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "failed_names": [c.name for c in self.failed_checks()],
            "gap_count": len(self.gaps),
            "gaps": [
                {
                    "name": g.name,
                    "gap_type": g.gap_type,
                    "category": g.category,
                    "registry_key": g.registry_key,
                }
                for g in self.gaps
            ],
        }
