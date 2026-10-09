"""Typed contracts for the Model Quality evaluator (pure data, strict validation)."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

ADVISORY_LABEL = "MODEL QUALITY / LENDER READINESS ADVISORY"
NOT_CLAIMS = ("Not bank approval", "Not certification", "Not verification")
SCHEMA_VERSION = "model-quality-q1-1"

_ID_RE = re.compile(r"^QM-[A-Z]{2,5}-\d{3}$")


class CheckStatus(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNAVAILABLE = "UNAVAILABLE"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class CheckClass(str, Enum):
    """What kind of statement a check makes.  An advisory range is never a binding covenant."""

    MATHEMATICAL_INTEGRITY = "MATHEMATICAL_INTEGRITY"   # an identity the model must satisfy
    CONTRACTUAL_COVENANT = "CONTRACTUAL_COVENANT"       # a project-supplied threshold
    ADVISORY_RISK = "ADVISORY_RISK"                     # screening observation, not a covenant
    EVIDENCE_AVAILABILITY = "EVIDENCE_AVAILABILITY"     # is the evidence present and well-formed


class Category(str, Enum):
    ACCOUNTING_INTEGRITY = "ACCOUNTING_INTEGRITY"
    SOURCES_USES = "SOURCES_USES"
    SENIOR_DEBT = "SENIOR_DEBT"
    CASH_LIQUIDITY = "CASH_LIQUIDITY"
    COVENANTS = "COVENANTS"
    CAPEX_CONSTRUCTION = "CAPEX_CONSTRUCTION"
    REVENUE = "REVENUE"
    TERMINAL_LIABILITY = "TERMINAL_LIABILITY"
    PROVENANCE_FRESHNESS = "PROVENANCE_FRESHNESS"


SEVERITY_WEIGHT = {Severity.CRITICAL: 8, Severity.HIGH: 4, Severity.MEDIUM: 2, Severity.LOW: 1}


def _finite_or_none(name: str, value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"QM_NON_FINITE_VALUE: {name}={value!r}")
    return float(value)


@dataclass(frozen=True)
class QualityCheck:
    check_id: str
    category: Category
    check_class: CheckClass
    title: str
    description: str
    status: CheckStatus
    severity: Severity
    measured_value: Optional[float]
    measured_unit: str
    threshold_value: Optional[float]
    threshold_authority: str
    evidence_source: str
    reason_code: Optional[str]
    related_assumption_ids: tuple[str, ...]
    related_output_keys: tuple[str, ...]
    navigation_target: str
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.check_id, str) or not _ID_RE.match(self.check_id):
            raise ValueError(f"QM_INVALID_CHECK_ID: {self.check_id!r}")
        for name, kind in (("category", Category), ("check_class", CheckClass),
                           ("status", CheckStatus), ("severity", Severity)):
            if not isinstance(getattr(self, name), kind):
                raise ValueError(f"QM_INVALID_ENUM: {name}={getattr(self, name)!r}")
        object.__setattr__(self, "measured_value", _finite_or_none("measured_value", self.measured_value))
        object.__setattr__(self, "threshold_value", _finite_or_none("threshold_value", self.threshold_value))
        if self.status is CheckStatus.UNAVAILABLE and not self.reason_code:
            raise ValueError("QM_UNAVAILABLE_NEEDS_REASON")
        if not isinstance(self.related_assumption_ids, tuple) or not isinstance(self.related_output_keys, tuple):
            raise ValueError("QM_RELATED_REFERENCES_MUST_BE_TUPLES")

    @property
    def evaluated(self) -> bool:
        return self.status in (CheckStatus.PASS, CheckStatus.WARNING, CheckStatus.FAIL)

    @property
    def weight(self) -> int:
        return SEVERITY_WEIGHT[self.severity]

    @property
    def blocking(self) -> bool:
        """A failed identity or a failed CRITICAL check blocks, whatever the advisory score is."""
        return self.status is CheckStatus.FAIL and (
            self.check_class is CheckClass.MATHEMATICAL_INTEGRITY or self.severity is Severity.CRITICAL)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "category": self.category.value,
            "check_class": self.check_class.value,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "severity": self.severity.value,
            "measured_value": self.measured_value,
            "measured_unit": self.measured_unit,
            "threshold_value": self.threshold_value,
            "threshold_authority": self.threshold_authority,
            "evidence_source": self.evidence_source,
            "reason_code": self.reason_code,
            "related_assumption_ids": list(self.related_assumption_ids),
            "related_output_keys": list(self.related_output_keys),
            "navigation_target": self.navigation_target,
            "detail": self.detail,
            "blocking": self.blocking,
        }


@dataclass(frozen=True)
class ScoreSummary:
    registered: int
    applicable: int
    evaluated: int
    passed: int
    warnings: int
    failed: int
    not_applicable: int
    unavailable: int
    coverage_count: Optional[float]      # evaluated / applicable
    coverage_weighted: Optional[float]   # severity-weighted
    min_coverage: float
    score: Optional[float]               # None = UNAVAILABLE (never an invented zero)
    score_status: str                    # PUBLISHED | UNAVAILABLE_INSUFFICIENT_EVIDENCE | UNAVAILABLE_NO_RUN
    blocked: bool
    blocked_score_cap: float
    severity_breakdown: dict[str, dict[str, int]]
    readiness_label: str

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass(frozen=True)
class QualityReport:
    label: str
    not_claims: tuple[str, ...]
    schema_version: str
    freshness: Optional[str]
    score_is_current: bool
    run_identity: dict[str, Any]
    checks: tuple[QualityCheck, ...]
    summary: ScoreSummary
    top_issues: tuple[str, ...]          # check_ids, most material first
    evidence_gaps: tuple[str, ...]       # UNAVAILABLE check_ids, most material first
    blocking_findings: tuple[str, ...]

    def check(self, check_id: str) -> QualityCheck:
        for c in self.checks:
            if c.check_id == check_id:
                return c
        raise KeyError(check_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "not_claims": list(self.not_claims),
            "schema_version": self.schema_version,
            "freshness": self.freshness,
            "score_is_current": self.score_is_current,
            "run_identity": dict(self.run_identity),
            "summary": self.summary.to_dict(),
            "top_issues": list(self.top_issues),
            "evidence_gaps": list(self.evidence_gaps),
            "blocking_findings": list(self.blocking_findings),
            "checks": [c.to_dict() for c in self.checks],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
