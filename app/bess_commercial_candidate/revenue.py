"""Revenue classification and lender-facing presentation (WF-08A, release-closed).

Every revenue line is declared as exactly one of CONTRACTED, CONTRACTED_UNSECURED or MERCHANT. The
three classes are presented as SEPARATE categories and are never netted into one figure. How a class
would enter a future lender cash-flow / DSCR analysis is recorded as a typed presentation mapping whose
DSCR eligibility and haircut are OPEN Financial Owner decisions: this module never assigns an eligibility,
a haircut or a discount, and it does not touch the released CFADS, debt-sizing or DSCR engines.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.bess_commercial_candidate.contracts import (
    exact_arithmetic,
    BessCommercialError, Decision, RevenueClass, Service, enum_member, ident, opt_dec, opt_ident,
    require_release, tuple_of, unique,
)

_CONTRACTED = (RevenueClass.CONTRACTED, RevenueClass.CONTRACTED_UNSECURED)


@dataclass(frozen=True)
class RevenueLine:
    """One declared revenue line. ``amount_keur`` None = MISSING; ``Decimal(0)`` = reported zero.

    ``claim_id`` links the line to exactly one dispatch-allocation claim, so the physical energy or
    reserved capacity behind it is accounted for once.
    """

    line_id: str
    period_id: str
    service: Service
    classification: RevenueClass
    amount_keur: Optional[Decimal]
    claim_id: str
    contract_ref: Optional[str] = None

    def __post_init__(self):
        ident(self.line_id, "line_id")
        ident(self.period_id, "period_id")
        ident(self.claim_id, "claim_id")
        enum_member(self.service, Service, "service")
        enum_member(self.classification, RevenueClass, "revenue classification")
        opt_dec(self.amount_keur, "amount_keur", nonnegative=True)
        opt_ident(self.contract_ref, "contract_ref")
        if self.classification in _CONTRACTED and self.contract_ref is None:
            raise BessCommercialError(
                f"BESS_COMMERCIAL_CLASSIFICATION: {self.classification.value} requires a contract_ref")
        if self.classification is RevenueClass.MERCHANT and self.contract_ref is not None:
            raise BessCommercialError(
                "BESS_COMMERCIAL_CLASSIFICATION: MERCHANT revenue cannot carry a contract_ref")


@dataclass(frozen=True)
class LenderTreatment:
    """How one class would be PRESENTED to a future lender analysis (no policy applied)."""

    classification: RevenueClass
    presentation_bucket: str
    dscr_eligibility: Decision
    haircut: Decision
    netted_with_other_classes: bool = False


#: Presentation mapping. Eligibility and haircut are OPEN for every class — nothing is decided here.
LENDER_TREATMENT = {
    RevenueClass.CONTRACTED: LenderTreatment(RevenueClass.CONTRACTED, "CONTRACTED", Decision.OPEN, Decision.OPEN),
    RevenueClass.CONTRACTED_UNSECURED: LenderTreatment(
        RevenueClass.CONTRACTED_UNSECURED, "CONTRACTED_UNSECURED_SEPARATE_CATEGORY", Decision.OPEN, Decision.OPEN),
    RevenueClass.MERCHANT: LenderTreatment(RevenueClass.MERCHANT, "MERCHANT", Decision.OPEN, Decision.OPEN),
}


@dataclass(frozen=True)
class Bucket:
    amount_keur: Optional[Decimal]     # None when any contributing line is MISSING
    line_count: int                    # 0 = no line declared (distinct from a reported zero)
    unavailable_line_ids: tuple


@dataclass(frozen=True)
class PeriodPresentation:
    period_id: str
    contracted: Bucket
    contracted_unsecured: Bucket
    merchant: Bucket


@dataclass(frozen=True)
class LenderPresentation:
    periods: tuple
    treatment: tuple
    released_cfads_engine_modified: bool = False
    released_debt_sizing_modified: bool = False
    released_dscr_engine_modified: bool = False


def _bucket(lines) -> Bucket:
    missing = tuple(line.line_id for line in lines if line.amount_keur is None)
    total = None if missing else sum((line.amount_keur for line in lines), Decimal(0))
    return Bucket(total, len(lines), missing)


@exact_arithmetic
def present_for_lender(lines) -> LenderPresentation:
    """Group lines by period and class. Classes are reported separately and never netted."""
    require_release()
    lines = tuple_of(lines, "lines")
    for line in lines:
        if not isinstance(line, RevenueLine):
            raise BessCommercialError("BESS_COMMERCIAL_SCHEMA: RevenueLine required")
    unique([line.line_id for line in lines], "revenue line_id")
    unique([line.claim_id for line in lines], "claim_id (one allocation claim backs one revenue line)")
    periods = []
    for period_id in sorted({line.period_id for line in lines}):
        mine = [line for line in lines if line.period_id == period_id]
        by = {cls: [line for line in mine if line.classification is cls] for cls in RevenueClass}
        periods.append(PeriodPresentation(period_id, _bucket(by[RevenueClass.CONTRACTED]),
                                          _bucket(by[RevenueClass.CONTRACTED_UNSECURED]),
                                          _bucket(by[RevenueClass.MERCHANT])))
    return LenderPresentation(tuple(periods), tuple(LENDER_TREATMENT[c] for c in RevenueClass))


@exact_arithmetic
def stack_by_service(lines) -> dict:
    """Per (period, service, class) totals so stacked services stay visibly separate."""
    require_release()
    lines = tuple_of(lines, "lines")
    unique([line.line_id for line in lines], "revenue line_id")
    out: dict = {}
    for line in lines:
        key = (line.period_id, line.service.value, line.classification.value)
        previous = out.get(key, Decimal(0))
        out[key] = None if previous is None or line.amount_keur is None else previous + line.amount_keur
    return out


@exact_arithmetic
def link_to_allocation(lines, claims) -> None:
    """Every revenue line must be backed by exactly one allocation claim of the SAME service.

    A claim backing two revenue lines, an unknown claim, or a service mismatch fails closed, so
    a physical MWh or reserved MW cannot be monetised twice.
    """
    require_release()
    by_id = {}
    for claim in tuple_of(claims, "claims"):
        by_id[claim.claim_id] = claim
    used = set()
    for line in tuple_of(lines, "lines"):
        claim = by_id.get(line.claim_id)
        if claim is None:
            raise BessCommercialError(
                f"BESS_COMMERCIAL_ALLOCATION: revenue line {line.line_id!r} references unknown claim {line.claim_id!r}")
        if claim.service is not line.service:
            raise BessCommercialError(
                f"BESS_COMMERCIAL_ALLOCATION: revenue line {line.line_id!r} service {line.service.value} "
                f"differs from claim service {claim.service.value}")
        if line.claim_id in used:
            raise BessCommercialError(
                f"BESS_COMMERCIAL_DOUBLE_COUNT: claim {line.claim_id!r} backs more than one revenue line")
        used.add(line.claim_id)
