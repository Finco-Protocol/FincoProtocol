"""Typed contracts for Run Integrity Checks (Opus H-4b).

Run Integrity Checks establish INTERNAL CONSISTENCY of a committed Last Run only.
They are not FINCO VERIFY, not market validation, not the Reference Regression Check
(machine key MODEL_VALIDATION), not a Signed Run, and not evidence that assumptions
are realistic. They never re-run the model and read no market data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

AUTHORITY = "RUN_INTEGRITY_CHECKS"
EVIDENCE_SCHEMA = "RUN_INTEGRITY_EVIDENCE_V1"
SCOPE_STATEMENT = (
    "Internal consistency of the committed Last Run only: it does not verify the asset, "
    "validate assumptions, check market data, replace the Reference Regression Check, "
    "or issue a Signed Run."
)

TOL_KEUR = 1e-6      # absolute tolerance on kEUR identities (evidence is full precision)
TOL_RATIO = 1e-9     # DSCR / ratio identities
TOL_XIRR = 1e-9      # XIRR recomputation


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNAVAILABLE = "UNAVAILABLE"


class OverallStatus(str, Enum):
    PASS = "PASS"              # every applicable check passed
    FAIL = "FAIL"              # at least one check failed
    INCOMPLETE = "INCOMPLETE"  # no failure, but at least one check could not be evaluated


@dataclass(frozen=True)
class IntegrityCheck:
    check_id: str
    title: str
    status: CheckStatus
    reason_code: str | None = None
    evaluated: int = 0                     # periods / items evaluated
    max_abs_deviation: float | None = None
    tolerance: float | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "title": self.title,
            "status": self.status.value,
            "reason_code": self.reason_code,
            "evaluated": self.evaluated,
            "max_abs_deviation": self.max_abs_deviation,
            "tolerance": self.tolerance,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class RunIntegrityReport:
    checks: tuple[IntegrityCheck, ...]
    evidence_digest: str | None = None
    authority: str = AUTHORITY
    scope: str = SCOPE_STATEMENT
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def overall(self) -> OverallStatus:
        statuses = {c.status for c in self.checks}
        if CheckStatus.FAIL in statuses:
            return OverallStatus.FAIL
        if CheckStatus.UNAVAILABLE in statuses or not statuses:
            return OverallStatus.INCOMPLETE
        return OverallStatus.PASS

    def counts(self) -> dict[str, int]:
        return {s.value: sum(1 for c in self.checks if c.status is s) for s in CheckStatus}

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "overall": self.overall.value,
            "counts": self.counts(),
            "scope": self.scope,
            "evidence_digest": self.evidence_digest,
            "checks": [c.to_dict() for c in self.checks],
            **self.extras,
        }
