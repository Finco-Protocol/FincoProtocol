"""financial_engine.shl.maturity_authority — OD-R final-state SHL maturity authority contract.

The cash-sweep shareholder-loan maturity predicate (``closing > tolerance + 1e-9`` at the
contractual maturity period, ``SHL_MATURITY_RESIDUAL_FAILS_CLOSED``) is unchanged. This module
only decides WHEN a breach of that predicate is a financial rejection.

Canonical interpretation (default, deployed): every evaluation is authoritative, so a breach in
any SHL schedule raises immediately.

OD-R (Financial Owner decision "Final-State SHL Maturity Authority"): the predicate is
authoritative only on the final converged financing state —

* the final DSCR-only capacity pass and the final funded pass (or the strict re-solve that
  replaced it) of the returned converged G2A evaluation,
* the same passes of the construction-IDC final idempotence verification G2A,
* the final waterfall SHL schedule,

and only once every existing convergence / idempotence validation has succeeded. Breaches in
provisional G2A, construction-IDC or initial-DSRA fixed-point iterations are recorded as
diagnostics.

Authority is carried explicitly:

``ShlMaturityContext``      passed by a fixed-point owner to ``run_senior_debt_model`` and on to
                            ``compute_shareholder_loan_schedules``. ``None`` (the default
                            everywhere) is the canonical fail-closed behaviour.
``G2aShlMaturityEvidence``  one G2A invocation's per-pass evidence, returned to the owner that
                            knows whether that invocation is provisional or final.
``OdrAttempt``              one complete engine evaluation opened by the OD-R policy owner (the
                            initial-DSRA fixed point). Only that owner opens it, with
                            ``odr_attempt``; it is context-local (never process-global), refuses
                            nesting, and is absent in every other Run, thread and worker process,
                            where the canonical behaviour therefore applies.

No numerical value is changed by this contract: a provisional evaluation computes exactly the
schedule a canonical evaluation computes and differs only in not raising this one exception.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum
from typing import Iterator

SHL_MATURITY_ERROR_CODE = "SHL_MATURITY_RESIDUAL_FAILS_CLOSED"

# Release-closed policy selector values (``GenericFinancingPolicy.shl_maturity_authority``).
SHL_MATURITY_POLICY_CANONICAL = "CANONICAL_EVERY_EVALUATION"
SHL_MATURITY_POLICY_OD_R = "OD_R_FINAL_STATE_SHL_MATURITY_V1"
SHL_MATURITY_POLICIES = (SHL_MATURITY_POLICY_CANONICAL, SHL_MATURITY_POLICY_OD_R)


class ShlMaturityAuthority(str, Enum):
    AUTHORITATIVE = "AUTHORITATIVE"
    PROVISIONAL = "PROVISIONAL"


@dataclass(frozen=True)
class ShlMaturityShortfall:
    """One breach of the unchanged cash-sweep maturity predicate (kEUR, exact float)."""

    closing_keur: float
    period_index: int
    tolerance_keur: float


def shl_maturity_residual_error(
    shortfall: ShlMaturityShortfall, *, evidence: str = "",
) -> ValueError:
    """The canonical maturity exception; ``evidence`` is appended only by OD-R final checks."""
    return ValueError(
        f"{SHL_MATURITY_ERROR_CODE}: "
        f"closing balance {shortfall.closing_keur:.12f} kEUR remains at maturity "
        f"period_index={shortfall.period_index}" + evidence
    )


class ShlMaturityLedger:
    """Append-only record of the breaches observed by ONE provisional evaluation."""

    __slots__ = ("_shortfalls",)

    def __init__(self) -> None:
        self._shortfalls: list[ShlMaturityShortfall] = []

    def record(self, shortfall: ShlMaturityShortfall) -> None:
        if not isinstance(shortfall, ShlMaturityShortfall):
            raise TypeError("ShlMaturityLedger records ShlMaturityShortfall only")
        self._shortfalls.append(shortfall)

    @property
    def shortfalls(self) -> tuple[ShlMaturityShortfall, ...]:
        return tuple(self._shortfalls)

    def first(self) -> ShlMaturityShortfall | None:
        """The breach the canonical evaluation would have raised (first in calculation order)."""
        return self._shortfalls[0] if self._shortfalls else None


@dataclass(frozen=True)
class ShlMaturityContext:
    """Explicit authority of one SHL evaluation. PROVISIONAL must name where breaches go."""

    authority: ShlMaturityAuthority
    ledger: ShlMaturityLedger | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.authority, ShlMaturityAuthority):
            raise TypeError("ShlMaturityContext.authority must be ShlMaturityAuthority")
        if self.authority is ShlMaturityAuthority.PROVISIONAL and not isinstance(
            self.ledger, ShlMaturityLedger
        ):
            raise ValueError("a PROVISIONAL SHL maturity context requires a ShlMaturityLedger")

    @property
    def provisional(self) -> bool:
        return self.authority is ShlMaturityAuthority.PROVISIONAL

    @classmethod
    def provisional_pass(cls) -> "ShlMaturityContext":
        return cls(ShlMaturityAuthority.PROVISIONAL, ShlMaturityLedger())


class G2aShlMaturityEvidence:
    """Per-pass maturity evidence of one G2A (derived-SHL / Senior) invocation.

    Filled by ``run_project_financing_model``; classified by the owner that knows whether the
    invocation is provisional (construction seed / superseded outer iteration / non-final DSRA
    attempt) or final (returned converged G2A / idempotence verification G2A).
    """

    __slots__ = ("provisional_passes", "final_passes", "converged")

    def __init__(self) -> None:
        # (pass site, G2A iteration, first breach) for every pass of a non-converging iteration
        self.provisional_passes: list[tuple[str, int, ShlMaturityShortfall | None]] = []
        # (pass site, first breach or None) for the converging iteration, in calculation order
        self.final_passes: list[tuple[str, ShlMaturityShortfall | None]] = []
        self.converged = False

    def record_iteration(
        self, iteration: int, passes: "list[tuple[str, ShlMaturityContext]]", *, final: bool,
    ) -> None:
        if self.converged:
            raise RuntimeError("OD_R_G2A_EVIDENCE_ALREADY_FINAL")
        # The funded pass that a strict re-solve replaced is not the returned state.
        strict = any(site == "STRICT" for site, _ in passes)
        for site, ctx in passes:
            if final and not (strict and site == "FUNDED"):
                self.final_passes.append((site, ctx.ledger.first()))
            else:
                self.provisional_passes.append((site, iteration, ctx.ledger.first()))
        self.converged = final


WATERFALL_FINAL_CHECK = "WATERFALL.FINAL_SHL_SCHEDULE"


@dataclass(frozen=True)
class OdrFinalCheck:
    name: str
    shortfall: ShlMaturityShortfall | None

    @property
    def passed(self) -> bool:
        return self.shortfall is None


class OdrAttempt:
    """Maturity evidence of ONE complete engine evaluation under OD-R."""

    def __init__(self) -> None:
        self.provisional_violations: list[tuple[str, ShlMaturityShortfall]] = []
        self.final_checks: list[OdrFinalCheck] = []

    def absorb_g2a(self, evidence: G2aShlMaturityEvidence, *, final: bool, role: str) -> None:
        if not isinstance(evidence, G2aShlMaturityEvidence):
            raise TypeError("OdrAttempt absorbs G2aShlMaturityEvidence only")
        for site, iteration, shortfall in evidence.provisional_passes:
            if shortfall is not None:
                self.provisional_violations.append((f"{role}.ITER{iteration}.{site}", shortfall))
        if final:
            if not evidence.converged:
                # Final authority exists only for a G2A that converged and recorded its passes.
                # (A converged G2A without any SHL evaluation has no final pass to check.)
                raise RuntimeError(f"OD_R_FINAL_G2A_EVIDENCE_INCOMPLETE: {role}")
            for site, shortfall in evidence.final_passes:
                self.final_checks.append(OdrFinalCheck(f"{role}.FINAL_{site}", shortfall))
        else:
            for site, shortfall in evidence.final_passes:
                if shortfall is not None:
                    self.provisional_violations.append((f"{role}.CONVERGED.{site}", shortfall))

    def record_final_waterfall(self, shortfall: ShlMaturityShortfall | None) -> None:
        """The final waterfall SHL schedule's check (contractual SHL schedule of this evaluation)."""
        if shortfall is not None and not isinstance(shortfall, ShlMaturityShortfall):
            raise TypeError("record_final_waterfall takes ShlMaturityShortfall or None")
        self.final_checks.append(OdrFinalCheck(WATERFALL_FINAL_CHECK, shortfall))

    def demote(self, role: str) -> None:
        """This whole evaluation was superseded (non-final DSRA iteration): all of it is provisional."""
        for check in self.final_checks:
            if check.shortfall is not None:
                self.provisional_violations.append((f"{role}.{check.name}", check.shortfall))
        self.final_checks = []

    def first_final_failure(self) -> OdrFinalCheck | None:
        return next((c for c in self.final_checks if not c.passed), None)

    def final_failure_error(self) -> ValueError | None:
        failure = self.first_final_failure()
        if failure is None:
            return None
        return shl_maturity_residual_error(
            failure.shortfall,
            evidence=(
                f"; od_r_final_check={failure.name}"
                f"; od_r_failed_final_checks={sum(not c.passed for c in self.final_checks)}"
                f"; od_r_provisional_violations={len(self.provisional_violations)}"
            ),
        )


@dataclass(frozen=True)
class OdrMaturityEvidence:
    """Bounded, deterministic OD-R decision-path evidence attached to an accepted result."""

    authority: str
    provisional_violation_count: int
    max_provisional_shortfall_keur: float
    final_checks_performed: tuple[str, ...]
    final_waterfall_check: str
    superseded_attempts: int

    def to_metadata(self) -> dict:
        return {
            "shl_maturity_authority": self.authority,
            "shl_maturity_provisional_violations": self.provisional_violation_count,
            "shl_maturity_max_provisional_shortfall_keur": self.max_provisional_shortfall_keur,
            "shl_maturity_final_checks": list(self.final_checks_performed),
            "shl_maturity_final_waterfall_check": self.final_waterfall_check,
            "shl_maturity_superseded_dsra_attempts": self.superseded_attempts,
        }


def summarize(final: OdrAttempt, superseded: "list[OdrAttempt]") -> OdrMaturityEvidence:
    if final.first_final_failure() is not None:
        raise RuntimeError("OD_R_EVIDENCE_REQUESTED_FOR_REJECTED_STATE")
    waterfall = (
        "PASSED" if any(c.name == WATERFALL_FINAL_CHECK for c in final.final_checks)
        else "NOT_APPLICABLE_NO_SHL"
    )
    provisional = [s for a in superseded for _, s in a.provisional_violations]
    provisional += [s for _, s in final.provisional_violations]
    return OdrMaturityEvidence(
        authority=SHL_MATURITY_POLICY_OD_R,
        provisional_violation_count=len(provisional),
        max_provisional_shortfall_keur=max((s.closing_keur for s in provisional), default=0.0),
        final_checks_performed=tuple(c.name for c in final.final_checks),
        final_waterfall_check=waterfall,
        superseded_attempts=len(superseded),
    )


_ATTEMPT: ContextVar[OdrAttempt | None] = ContextVar("finco_od_r_attempt", default=None)


def current_attempt() -> OdrAttempt | None:
    """The OD-R evaluation open in this context, or None (canonical behaviour)."""
    return _ATTEMPT.get()


@contextmanager
def odr_attempt(attempt: OdrAttempt) -> Iterator[OdrAttempt]:
    """Open one OD-R engine evaluation. Exceptions keep canonical precedence for final breaches.

    A breach at a final check is recorded rather than raised because the owner may only learn
    afterwards that the evaluation is the final one. If any exception then escapes the
    evaluation, the canonical engine would already have raised the earlier final breach, so the
    maturity error is raised (chained) instead; otherwise the exception propagates unchanged.
    """
    if not isinstance(attempt, OdrAttempt):
        raise TypeError("odr_attempt requires an OdrAttempt")
    if _ATTEMPT.get() is not None:
        raise RuntimeError("OD_R_ATTEMPT_NESTING_REFUSED")
    token = _ATTEMPT.set(attempt)
    try:
        yield attempt
    except Exception as exc:
        error = attempt.final_failure_error()
        if error is None:
            raise
        raise error from exc
    finally:
        _ATTEMPT.reset(token)


__all__ = [
    "SHL_MATURITY_ERROR_CODE", "SHL_MATURITY_POLICY_CANONICAL", "SHL_MATURITY_POLICY_OD_R",
    "SHL_MATURITY_POLICIES", "ShlMaturityAuthority", "ShlMaturityShortfall",
    "ShlMaturityLedger", "ShlMaturityContext", "shl_maturity_residual_error",
    "G2aShlMaturityEvidence", "WATERFALL_FINAL_CHECK", "OdrFinalCheck", "OdrAttempt", "OdrMaturityEvidence",
    "summarize", "current_attempt", "odr_attempt",
]
