"""Candidate N-tranche validation — released two-Senior rules, generalized.

Every per-instrument rule is the released two-Senior rule VERBATIM (same
stable ``FinancingError`` code, same semantics) so the generalization from
exactly-2 to N >= 2 is auditable rule-by-rule. Only the count rule is new.
Nothing here activates, persists or exposes anything.
"""
from __future__ import annotations

from finco_core.inputs.financing_instruments import (
    CommitmentAuthority,
    FinancingCollection,
    FinancingError,
    InstrumentType,
    MaturityAuthority,
    RateMode,
    RepaymentMode,
)

F31_MULTITRANCHE_CANDIDATE_AUTHORITY = "F31_MULTITRANCHE_CANDIDATE_V0"

# The candidate supports two or more pari-passu senior tranches. A single
# senior tranche remains the domain of the existing canonical/legacy
# financing authorities, so it is deliberately out of candidate scope.
MIN_TRANCHES = 2

_FEE_WHITELIST = frozenset({("UPFRONT", "COMMITMENT"), ("COMMITMENT", "UNDRAWN")})
_SUPPORTED_REPAYMENT = (RepaymentMode.LEVEL_PRINCIPAL, RepaymentMode.BULLET)


def validate_multitranche_collection(collection: FinancingCollection) -> None:
    """Validate an N-tranche (N >= 2) pari-passu senior proposal, fail closed.

    Rule-for-rule identical to the released two-Senior validator
    (finco_core.inputs.multisenior.validate_effective_collection) for every
    per-instrument check; the only new rule is the tranche count.
    """
    if not isinstance(collection, FinancingCollection):
        raise FinancingError("F3_EFFECTIVE_COLLECTION_REQUIRED")
    if len(collection.instruments) < MIN_TRANCHES:
        raise FinancingError(
            "F3_MULTITRANCHE_COUNT_UNSUPPORTED",
            f"{len(collection.instruments)} tranche(s); candidate requires "
            f">= {MIN_TRANCHES}",
        )
    if collection.providers:
        raise FinancingError("F3_PROVIDER_ECONOMICS_UNSUPPORTED")
    for instrument in collection.ordered():
        if instrument.instrument_type is not InstrumentType.SENIOR_TERM_LOAN:
            raise FinancingError(
                "F3_EFFECTIVE_INSTRUMENT_UNSUPPORTED", instrument.instrument_id)
        if (instrument.commitment_authority is not CommitmentAuthority.EXPLICIT
                or instrument.commitment_keur <= 0):
            raise FinancingError(
                "F3_EXPLICIT_POSITIVE_COMMITMENT_REQUIRED", instrument.instrument_id)
        if instrument.seniority_rank != 1 or instrument.funding_source_ref is not None:
            raise FinancingError(
                "F3_PARI_PASSU_SENIOR_ONLY", instrument.instrument_id)
        if instrument.interest.mode is not RateMode.FIXED or instrument.interest.pik:
            raise FinancingError(
                "F3_FIXED_CASH_INTEREST_ONLY", instrument.instrument_id)
        repayment = instrument.repayment
        if repayment.mode not in _SUPPORTED_REPAYMENT:
            raise FinancingError("F3_REPAYMENT_UNSUPPORTED", instrument.instrument_id)
        if repayment.maturity_authority is not MaturityAuthority.EXPLICIT_DATE:
            raise FinancingError(
                "F3_EXPLICIT_CALENDAR_MATURITY_REQUIRED", instrument.instrument_id)
        if (not instrument.drawdowns
                or abs(sum(d.amount_keur for d in instrument.drawdowns)
                       - instrument.commitment_keur) > 1e-9):
            raise FinancingError(
                "F3_FULL_EXPLICIT_DRAWS_REQUIRED", instrument.instrument_id)
        kinds = set()
        for fee in instrument.fees:
            if (fee.kind, fee.basis) not in _FEE_WHITELIST:
                raise FinancingError("F3_FEE_UNSUPPORTED", instrument.instrument_id)
            if fee.kind in kinds:
                raise FinancingError(
                    "F3_DUPLICATE_EFFECTIVE_FEE", instrument.instrument_id)
            kinds.add(fee.kind)
