"""Shareholder-loan terms and the exact one-period SHL step.

The period arithmetic reproduces the released canonical SHL engine
(``financial_engine.shl.engine.compute_shl_period``: period-start draw
convention, ``(opening + draw) * rate * fraction``, PIK capitalised into the
balance) in exact Decimal. The accrual fraction is SUPPLIED per period; no
day-count convention is chosen here. An SHL is sponsor debt: never legal
equity and never a distribution.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.model_v2.financing_wf07_candidate.contracts import (
    ClaimClass, Decision, InterestMode, InterestTreatment, Phase, Wf07Error,
    dec, enum, ident, index, unique,
)


@dataclass(frozen=True)
class ShlDraw:
    period_index: int
    amount: Decimal
    evidence_id: str

    def __post_init__(self):
        index(self.period_index, "ShlDraw.period_index")
        dec(self.amount, "ShlDraw.amount", positive=True)
        ident(self.evidence_id, "ShlDraw.evidence_id")


@dataclass(frozen=True)
class ShlPrincipal:
    """Explicitly scheduled principal repayment (no sweep, no inferred bullet)."""

    period_index: int
    amount: Decimal

    def __post_init__(self):
        index(self.period_index, "ShlPrincipal.period_index")
        dec(self.amount, "ShlPrincipal.amount", positive=True)


@dataclass(frozen=True)
class ShlTerms:
    shl_id: str
    commitment: Decimal
    annual_rate: Decimal
    construction_mode: InterestMode
    operating_mode: InterestMode
    draws: tuple
    principal: tuple = ()
    #: Tax deductibility of SHL interest is a Financial Owner decision.
    tax_deductibility: Decision = Decision.OPEN
    claim_class: ClaimClass = ClaimClass.SPONSOR_DEBT

    def __post_init__(self):
        ident(self.shl_id, "ShlTerms.shl_id")
        dec(self.commitment, "ShlTerms.commitment", positive=True)
        dec(self.annual_rate, "ShlTerms.annual_rate", nonnegative=True)
        enum(self.construction_mode, InterestMode, "construction_mode")
        enum(self.operating_mode, InterestMode, "operating_mode")
        if self.tax_deductibility is not Decision.OPEN:
            raise Wf07Error("WF07_DECISION_NOT_OPEN", "SHL tax deductibility is an OPEN owner decision")
        if self.claim_class is not ClaimClass.SPONSOR_DEBT:
            raise Wf07Error("WF07_SHL_CLAIM_CLASS", "a shareholder loan is sponsor debt, not equity or a distribution")
        if not isinstance(self.draws, tuple) or not all(isinstance(d, ShlDraw) for d in self.draws):
            raise Wf07Error("WF07_VALUE", "ShlTerms.draws must be a tuple of ShlDraw")
        if not isinstance(self.principal, tuple) or not all(isinstance(p, ShlPrincipal) for p in self.principal):
            raise Wf07Error("WF07_VALUE", "ShlTerms.principal must be a tuple of ShlPrincipal")
        unique([d.period_index for d in self.draws], f"{self.shl_id} draw period")
        unique([d.evidence_id for d in self.draws], f"{self.shl_id} draw evidence")
        unique([p.period_index for p in self.principal], f"{self.shl_id} principal period")
        if sum((d.amount for d in self.draws), Decimal(0)) > self.commitment:
            raise Wf07Error("WF07_SHL_COMMITMENT_EXCEEDED", self.shl_id)

    def draw_in(self, period_index: int) -> Decimal:
        return sum((d.amount for d in self.draws if d.period_index == period_index), Decimal(0))

    def principal_in(self, period_index: int) -> Decimal:
        return sum((p.amount for p in self.principal if p.period_index == period_index), Decimal(0))


@dataclass(frozen=True)
class ShlDue:
    shl_id: str
    period_index: int
    phase: Phase
    opening: Decimal
    draw: Decimal
    accrued_interest: Decimal
    cash_interest: Decimal
    pik_interest: Decimal
    treatment: InterestTreatment
    principal_due: Decimal


@dataclass(frozen=True)
class ShlRow:
    """Settled SHL period. Identity: closing = opening + draw + pik - principal_paid."""

    shl_id: str
    period_index: int
    phase: Phase
    opening: Decimal
    draw: Decimal
    accrued_interest: Decimal
    cash_interest_paid: Decimal
    pik_interest: Decimal
    treatment: InterestTreatment
    principal_paid: Decimal
    closing: Decimal
    claim_class: ClaimClass = ClaimClass.SPONSOR_DEBT


def shl_due(terms: ShlTerms, opening: Decimal, period_index: int, phase: Phase,
            accrual_fraction: Decimal) -> ShlDue:
    draw = terms.draw_in(period_index)
    accrued = (opening + draw) * terms.annual_rate * accrual_fraction
    mode = terms.construction_mode if phase is Phase.CONSTRUCTION else terms.operating_mode
    cash = accrued if mode is InterestMode.CASH else Decimal(0)
    pik = accrued if mode is InterestMode.PIK else Decimal(0)
    treatment = (InterestTreatment.CAPITALIZED if phase is Phase.CONSTRUCTION
                 else InterestTreatment.OPERATING_EXPENSE_CANDIDATE)
    principal = terms.principal_in(period_index)
    if phase is Phase.CONSTRUCTION and principal > 0:
        raise Wf07Error("WF07_SHL_PRINCIPAL_IN_CONSTRUCTION", terms.shl_id)
    if principal > opening + draw + pik:
        raise Wf07Error("WF07_SHL_PRINCIPAL_EXCEEDS_BALANCE", f"{terms.shl_id} period {period_index}")
    return ShlDue(terms.shl_id, period_index, phase, opening, draw, accrued, cash, pik,
                  treatment, principal)


def settle(due: ShlDue, cash_interest_paid: Decimal, principal_paid: Decimal) -> ShlRow:
    """Settle in full only; a partial payment has no approved treatment (deferral,
    capitalisation or default are OPEN) and is rejected by the caller beforehand."""
    if cash_interest_paid != due.cash_interest or principal_paid != due.principal_due:
        raise Wf07Error("WF07_SHL_PARTIAL_SETTLEMENT_UNSUPPORTED", due.shl_id)
    closing = due.opening + due.draw + due.pik_interest - principal_paid
    return ShlRow(due.shl_id, due.period_index, due.phase, due.opening, due.draw,
                  due.accrued_interest, cash_interest_paid, due.pik_interest, due.treatment,
                  principal_paid, closing)
