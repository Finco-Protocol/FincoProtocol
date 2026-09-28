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
    """Declares what to validate, against which registry authority, at what tolerance."""
    name: str
    registry_key: str
    tolerance_policy: str
    vertical: str
    assertion: str
    notes: str = ""


@dataclass
class CheckResult:
    """Outcome of one named validation check."""
    name: str
    passed: bool
    actual: Any
    expected: Any
    tolerance: float | None = None
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

    def summary(self) -> dict[str, Any]:
        return {
            "vertical": self.vertical,
            "project_type": self.project_type,
            "passed": self.passed,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "failed_names": [c.name for c in self.failed_checks()],
        }
