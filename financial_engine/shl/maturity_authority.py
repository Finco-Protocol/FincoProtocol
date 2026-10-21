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
diagnostics. A failed validation always keeps its own error: final authority was never
established for that evaluation.

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
FINAL_EVIDENCE_MISSING = "ODR_FINAL_EVIDENCE_MISSING"
FINAL_EVIDENCE_DUPLICATE = "ODR_FINAL_EVIDENCE_DUPLICATE"
FINAL_EVIDENCE_CONTRADICTORY = "ODR_FINAL_EVIDENCE_CONTRADICTORY"
FINAL_EVIDENCE_UNBOUND = "ODR_FINAL_EVIDENCE_UNBOUND"
FINALIZATION_REPEATED = "ODR_FINALIZATION_REPEATED"
CONSTRUCTION_G2A_ROLES = ("CONSTRUCTION_RETURNED_G2A", "CONSTRUCTION_VERIFICATION_G2A")
TOP_LEVEL_G2A_ROLES = ("G2A",)


class OdrFinalizationError(RuntimeError):
    """The returned evaluation lacks complete, unambiguous final evidence: never an accepted result."""


@dataclass(frozen=True)
class OdrFinalCheck:
    name: str
    shortfall: ShlMaturityShortfall | None

    @property
    def passed(self) -> bool:
        return self.shortfall is None


@dataclass(frozen=True)
class OdrFinalRequirements:
    """Which final checks the RETURNED financial state requires, derived from that state alone (never from evidence)."""

    g2a_roles: tuple[str, ...]
    waterfall_required: bool
    reason: str


def required_final_checks(result) -> OdrFinalRequirements:
    """Applicability from the actual final financing state.

    * SHL liability exists when the final financing derives a positive SHL cash principal or the final SHL schedule
      carries any positive drawdown / opening / closing balance (a very small positive amount is still a liability).
    * Deferred G2A final passes exist only for the canonical derived-SHL/Senior fixed point (exact
      ``ProjectFinancingResult``) whose final model evaluated an SHL schedule: construction-IDC results need the returned
      and the verification G2A, other results the top-level G2A. Junior / multi-senior financing never defers: its SHL
      maturity check is the canonical immediate check on every evaluation.
    """
    from financial_engine.financing.contracts import ProjectFinancingResult

    financing = result.financing_result
    model = financing.project_model_result
    schedule = getattr(model, "shareholder_loan", None)
    balances = () if schedule is None else (
        tuple(schedule.shl_drawdown_keur) + tuple(schedule.shl_opening_keur) + tuple(schedule.shl_closing_keur))
    liability = financing.derived_shl_cash_principal_keur > 0.0 or any(value > 0.0 for value in balances)
    if type(financing) is not ProjectFinancingResult:
        return OdrFinalRequirements((), liability, f"{type(financing).__name__}: canonical immediate SHL check")
    if schedule is None:
        return OdrFinalRequirements((), liability, "no SHL schedule in the final model")
    roles = CONSTRUCTION_G2A_ROLES if financing.construction_financing is not None else TOP_LEVEL_G2A_ROLES
    return OdrFinalRequirements(roles, liability, "derived-SHL/Senior fixed point")


class _BoundEvidence:
    """Final evidence registered against exactly one evaluated financing state (identity of its final model result)."""

    __slots__ = ("state", "g2a", "waterfall")

    def __init__(self, state) -> None:
        self.state = state                      # strong reference: the identity cannot be recycled during the attempt
        self.g2a: dict[str, list[tuple[str, ShlMaturityShortfall | None]]] = {}
        self.waterfall: list[ShlMaturityShortfall | None] = []


class OdrAttempt:
    """Maturity evidence of ONE complete engine evaluation under OD-R.

    Final checks are bound to the evaluated financing state they validate. ``finalize`` accepts only the checks bound to
    the state actually returned; checks bound to any other state (superseded U2 / G2A evaluations) are diagnostics.
    """

    def __init__(self) -> None:
        self.provisional_violations: list[tuple[str, ShlMaturityShortfall]] = []
        self.final_checks: list[OdrFinalCheck] = []
        self._bound: list[_BoundEvidence] = []
        self._finalized = False

    def _evidence_for(self, state) -> _BoundEvidence:
        if state is None:
            raise OdrFinalizationError(f"{FINAL_EVIDENCE_UNBOUND}: final evidence must name its evaluated state")
        if self._finalized:
            raise OdrFinalizationError(f"{FINALIZATION_REPEATED}: evidence after finalization")
        for entry in self._bound:
            if entry.state is state:
                return entry
        entry = _BoundEvidence(state)
        self._bound.append(entry)
        return entry

    def absorb_g2a(self, evidence: G2aShlMaturityEvidence, *, final: bool, role: str, state=None) -> None:
        if not isinstance(evidence, G2aShlMaturityEvidence):
            raise TypeError("OdrAttempt absorbs G2aShlMaturityEvidence only")
        for site, iteration, shortfall in evidence.provisional_passes:
            if shortfall is not None:
                self.provisional_violations.append((f"{role}.ITER{iteration}.{site}", shortfall))
        if final:
            if not evidence.converged:
                # Final authority exists only for a G2A that converged and recorded its passes.
                raise RuntimeError(f"OD_R_FINAL_G2A_EVIDENCE_INCOMPLETE: {role}")
            entry = self._evidence_for(state)
            if role in entry.g2a:
                raise OdrFinalizationError(f"{FINAL_EVIDENCE_DUPLICATE}: {role} registered twice for one state")
            entry.g2a[role] = list(evidence.final_passes)
        else:
            for site, shortfall in evidence.final_passes:
                if shortfall is not None:
                    self.provisional_violations.append((f"{role}.CONVERGED.{site}", shortfall))

    def record_final_waterfall(self, shortfall: ShlMaturityShortfall | None, *, state=None) -> None:
        """The waterfall SHL schedule check computed for the financing state ``state`` (its final model result)."""
        if shortfall is not None and not isinstance(shortfall, ShlMaturityShortfall):
            raise TypeError("record_final_waterfall takes ShlMaturityShortfall or None")
        self._evidence_for(state).waterfall.append(shortfall)

    def demote(self, role: str) -> None:
        """This whole evaluation was superseded (non-final DSRA iteration): all of it is provisional."""
        for entry in self._bound:
            for g2a_role, passes in entry.g2a.items():
                for site, shortfall in passes:
                    if shortfall is not None:
                        self.provisional_violations.append((f"{role}.{g2a_role}.FINAL_{site}", shortfall))
            for shortfall in entry.waterfall:
                if shortfall is not None:
                    self.provisional_violations.append((f"{role}.{WATERFALL_FINAL_CHECK}", shortfall))
        self._bound = []
        self.final_checks = []

    def finalize(self, result) -> OdrFinalRequirements:
        """Decide the returned evaluation exactly once, before it can be returned.

        Economic breaches at required final checks raise the canonical maturity error; otherwise missing, contradictory
        or unbound final evidence raises ``OdrFinalizationError``. Absence of evidence never establishes inapplicability.
        """
        if self._finalized:
            raise OdrFinalizationError(f"{FINALIZATION_REPEATED}: an evaluation is finalized once")
        self._finalized = True
        requirements = required_final_checks(result)
        state = result.financing_result.project_model_result
        returned = None
        for entry in self._bound:
            if entry.state is state:
                returned = entry
                continue
            # Evidence of another (superseded) financing evaluation within this attempt is diagnostic only.
            for g2a_role, passes in entry.g2a.items():
                for site, shortfall in passes:
                    if shortfall is not None:
                        self.provisional_violations.append((f"SUPERSEDED.{g2a_role}.FINAL_{site}", shortfall))
            for shortfall in entry.waterfall:
                if shortfall is not None:
                    self.provisional_violations.append((f"SUPERSEDED.{WATERFALL_FINAL_CHECK}", shortfall))
        returned = returned or _BoundEvidence(state)
        checks: list[OdrFinalCheck] = []
        missing: list[str] = []
        # A registered G2A that evaluated SHL passes for a state that needs none contradicts the final state; a converged
        # G2A without any SHL pass (no SHL in its model) is consistent with an inapplicable check.
        contradictory = sorted(role for role, passes in returned.g2a.items()
                               if passes and role not in requirements.g2a_roles)
        for role in requirements.g2a_roles:
            passes = returned.g2a.get(role)
            if passes is None:
                missing.append(f"{role}.FINAL_CAPACITY")
                missing.append(f"{role}.FINAL_FUNDED_OR_STRICT")
                continue
            sites = [site for site, _ in passes]
            if sites.count("CAPACITY") != 1:
                (missing if "CAPACITY" not in sites else contradictory).append(f"{role}.FINAL_CAPACITY")
            funded = [site for site in sites if site in ("FUNDED", "STRICT")]
            if len(funded) != 1:
                (missing if not funded else contradictory).append(f"{role}.FINAL_FUNDED_OR_STRICT")
            checks += [OdrFinalCheck(f"{role}.FINAL_{site}", shortfall) for site, shortfall in passes]
        if requirements.waterfall_required:
            if not returned.waterfall:
                missing.append(WATERFALL_FINAL_CHECK)
            # Repeated evaluations of the same returned state must all pass; any breach is decisive.
            checks += [OdrFinalCheck(WATERFALL_FINAL_CHECK, shortfall) for shortfall in returned.waterfall]
        elif returned.waterfall:
            contradictory.append(f"{WATERFALL_FINAL_CHECK} recorded for a state without SHL liability")
        self.final_checks = checks
        error = self.final_failure_error()
        if error is not None:
            raise error
        if contradictory:
            raise OdrFinalizationError(f"{FINAL_EVIDENCE_CONTRADICTORY}: {', '.join(contradictory)}")
        if missing:
            raise OdrFinalizationError(
                f"{FINAL_EVIDENCE_MISSING}: {', '.join(missing)} (required by the returned state: {requirements.reason}; "
                f"shl_liability={requirements.waterfall_required})")
        return requirements

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


def summarize(final: OdrAttempt, superseded: "list[OdrAttempt]",
              requirements: OdrFinalRequirements) -> OdrMaturityEvidence:
    """Evidence of a FINALIZED, accepted evaluation. The waterfall label follows the established applicability."""
    if not final._finalized or final.first_final_failure() is not None:
        raise RuntimeError("OD_R_EVIDENCE_REQUESTED_FOR_UNFINALIZED_OR_REJECTED_STATE")
    provisional = [s for a in superseded for _, s in a.provisional_violations]
    provisional += [s for _, s in final.provisional_violations]
    return OdrMaturityEvidence(
        authority=SHL_MATURITY_POLICY_OD_R,
        provisional_violation_count=len(provisional),
        max_provisional_shortfall_keur=max((s.closing_keur for s in provisional), default=0.0),
        final_checks_performed=tuple(c.name for c in final.final_checks),
        final_waterfall_check="PASSED" if requirements.waterfall_required else "NOT_APPLICABLE_NO_SHL",
        superseded_attempts=len(superseded),
    )


_ATTEMPT: ContextVar[OdrAttempt | None] = ContextVar("finco_od_r_attempt", default=None)


def current_attempt() -> OdrAttempt | None:
    """The OD-R evaluation open in this context, or None (canonical behaviour)."""
    return _ATTEMPT.get()


@contextmanager
def odr_attempt(attempt: OdrAttempt) -> Iterator[OdrAttempt]:
    """Open one OD-R engine evaluation.

    Final authority exists only for an evaluation that completed every required convergence,
    funding and idempotence validation (and, at the policy owner, the initial-DSRA fixed point).
    An evaluation that raised never established that authority, so any exception escaping it
    propagates unchanged; recorded breaches are never substituted for it. Final breaches are
    enforced only by the owner, on the returned evaluation, before the result is returned.
    """
    if not isinstance(attempt, OdrAttempt):
        raise TypeError("odr_attempt requires an OdrAttempt")
    if _ATTEMPT.get() is not None:
        raise RuntimeError("OD_R_ATTEMPT_NESTING_REFUSED")
    token = _ATTEMPT.set(attempt)
    try:
        yield attempt
    finally:
        _ATTEMPT.reset(token)


__all__ = [
    "SHL_MATURITY_ERROR_CODE", "SHL_MATURITY_POLICY_CANONICAL", "SHL_MATURITY_POLICY_OD_R",
    "SHL_MATURITY_POLICIES", "ShlMaturityAuthority", "ShlMaturityShortfall",
    "ShlMaturityLedger", "ShlMaturityContext", "shl_maturity_residual_error",
    "G2aShlMaturityEvidence", "WATERFALL_FINAL_CHECK", "OdrFinalCheck", "OdrFinalRequirements",
    "OdrFinalizationError", "required_final_checks", "OdrAttempt", "OdrMaturityEvidence",
    "summarize", "current_attempt", "odr_attempt",
]
