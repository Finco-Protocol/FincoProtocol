"""Equivalent common-equity mapping; all allocations use the existing core runner."""
import math

from finco_core.sponsor.sponsor_waterfall_tier import SponsorShare, SponsorWaterfallTier, TierType
from finco_core.sponsor.waterfall_runner import WaterfallRunnerInputs, run_waterfall

from .contracts import CASH_TOLERANCE_KEUR, InvestorAgreement


def to_existing_inputs(agreement: InvestorAgreement) -> WaterfallRunnerInputs:
    reasons = agreement.unsupported_reasons()
    if reasons:
        raise ValueError("Unsupported candidate agreement: " + "; ".join(reasons))
    dates = agreement.evidence.period_dates
    # Projection only: no new allocation, preference accrual or return calculation.
    cumulative = tuple(sum(c.amount_keur for c in agreement.contributions if c.cash_date <= d) for d in dates)
    tier = SponsorWaterfallTier(
        tier_index=0, tier_type=TierType.RESIDUAL,
        sponsor_shares=tuple(SponsorShare(i.investor_id, i.ownership_fraction) for i in agreement.investors),
        description="Explicit common-equity candidate agreement",
    )
    return WaterfallRunnerInputs(
        tiers=(tier,), available_cash_by_period=agreement.evidence.net_equity_cash_keur,
        pref_result=None, cumulative_invested_by_period=cumulative, num_periods=len(dates),
    )


def validate_candidate_result(agreement: InvestorAgreement, result) -> None:
    """Check the delegated result against its exact input; no residual repair."""
    to_existing_inputs(agreement)  # Reject unsupported rights, including synthetic result validation.
    cash = agreement.evidence.net_equity_cash_keur
    expected_ids = {i.investor_id for i in agreement.investors}
    if len(result.period_results) != len(cash):
        raise ValueError("candidate result period mismatch")
    for index, (available, period) in enumerate(zip(cash, result.period_results)):
        if (period.period_index != index or abs(period.available_cash_keur - available) > CASH_TOLERANCE_KEUR
                or len(period.tier_entries) != 1):
            raise ValueError("candidate result input mismatch")
        tier = period.tier_entries[0]
        allocations = tier.allocated_per_sponsor_keur
        if (tier.tier_type != TierType.RESIDUAL or len(allocations) != len(expected_ids)
                or {i for i, _ in allocations} != expected_ids):
            raise ValueError("candidate allocation identity/tier mismatch")
        values = (period.total_allocated_keur, period.total_remaining_cash_keur,
                  period.available_cash_keur, tier.allocated_amount_keur, *(v for _, v in allocations))
        if any(not math.isfinite(v) or v < 0 for v in values):
            raise ValueError("candidate allocations must be finite and nonnegative")
        distributed = math.fsum(v for _, v in allocations)
        if (distributed > available + CASH_TOLERANCE_KEUR
                or abs(distributed - available) > CASH_TOLERANCE_KEUR
                or abs(period.total_allocated_keur - distributed) > CASH_TOLERANCE_KEUR
                or abs(period.total_remaining_cash_keur) > CASH_TOLERANCE_KEUR):
            raise ValueError("candidate cash conservation failed; retained cash is not authorized")


def evaluate_candidate(agreement: InvestorAgreement):
    """Offline evaluation only; no production callers, persistence or activation hook."""
    result = run_waterfall(to_existing_inputs(agreement))
    validate_candidate_result(agreement, result)
    return result
