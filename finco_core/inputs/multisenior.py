"""Explicit F3 activation contract; legacy ProjectInputs retains its exact shape."""
from __future__ import annotations

from dataclasses import dataclass, fields

from finco_core.inputs._models import ProjectInputs
from finco_core.inputs.financing_instruments import (
    CommitmentAuthority, FinancingCollection, FinancingError, InstrumentType,
    MaturityAuthority, RateMode, RepaymentMode,
)

AUTHORITY = "F3_TWO_SENIOR_EXPLICIT_COMMITMENTS_V1"


def validate_effective_collection(collection: FinancingCollection) -> None:
    if not isinstance(collection, FinancingCollection):
        raise FinancingError("F3_EFFECTIVE_COLLECTION_REQUIRED")
    if len(collection.instruments) != 2 or len(collection.active()) != 2:
        raise FinancingError("F3_EXACTLY_TWO_SENIORS_REQUIRED")
    if collection.providers:
        raise FinancingError("F3_PROVIDER_ECONOMICS_UNSUPPORTED")
    for instrument in collection.instruments:
        if instrument.instrument_type is not InstrumentType.SENIOR_TERM_LOAN:
            raise FinancingError("F3_EFFECTIVE_INSTRUMENT_UNSUPPORTED", instrument.instrument_id)
        if instrument.commitment_authority is not CommitmentAuthority.EXPLICIT or instrument.commitment_keur <= 0:
            raise FinancingError("F3_EXPLICIT_POSITIVE_COMMITMENT_REQUIRED", instrument.instrument_id)
        if instrument.seniority_rank != 1 or instrument.funding_source_ref is not None:
            raise FinancingError("F3_PARI_PASSU_SENIOR_ONLY", instrument.instrument_id)
        if instrument.interest.mode is not RateMode.FIXED or instrument.interest.pik:
            raise FinancingError("F3_FIXED_CASH_INTEREST_ONLY", instrument.instrument_id)
        repayment = instrument.repayment
        if repayment.mode not in (RepaymentMode.LEVEL_PRINCIPAL, RepaymentMode.BULLET):
            raise FinancingError("F3_REPAYMENT_UNSUPPORTED", instrument.instrument_id)
        if repayment.maturity_authority is not MaturityAuthority.EXPLICIT_DATE:
            raise FinancingError("F3_EXPLICIT_CALENDAR_MATURITY_REQUIRED", instrument.instrument_id)
        if not instrument.drawdowns or abs(sum(d.amount_keur for d in instrument.drawdowns) - instrument.commitment_keur) > 1e-9:
            raise FinancingError("F3_FULL_EXPLICIT_DRAWS_REQUIRED", instrument.instrument_id)
        kinds = set()
        for fee in instrument.fees:
            if (fee.kind, fee.basis) not in (("UPFRONT", "COMMITMENT"), ("COMMITMENT", "UNDRAWN")):
                raise FinancingError("F3_FEE_UNSUPPORTED", instrument.instrument_id)
            if fee.kind in kinds:
                raise FinancingError("F3_DUPLICATE_EFFECTIVE_FEE", instrument.instrument_id)
            kinds.add(fee.kind)


@dataclass(frozen=True, kw_only=True)
class MultiSeniorProjectInputs(ProjectInputs):
    """Only activated inputs gain these fields; no legacy default, migration or hash drift."""

    financing_collection: FinancingCollection
    financing_activation_authority: str = AUTHORITY

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.financing_activation_authority != AUTHORITY:
            raise FinancingError("F3_ACTIVATION_AUTHORITY_UNSUPPORTED")
        validate_effective_collection(self.financing_collection)


def activate_collection(pi: ProjectInputs, collection: FinancingCollection) -> MultiSeniorProjectInputs:
    values = {field.name: getattr(pi, field.name) for field in fields(ProjectInputs)}
    return MultiSeniorProjectInputs(**values, financing_collection=collection)


def deactivate_collection(pi: ProjectInputs) -> ProjectInputs:
    return ProjectInputs(**{field.name: getattr(pi, field.name) for field in fields(ProjectInputs)})
