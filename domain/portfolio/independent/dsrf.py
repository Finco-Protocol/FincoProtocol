"""DSRF — Revolving Debt Service Reserve Facility (Phase 2).

DSRF is a revolving credit facility, NOT a cash-funded reserve account.
- Draws cover senior debt service shortfalls when CFADS is insufficient
- Commitment fee on undrawn portion (rate × period_year_fraction)
- Interest on drawn portion (EURIBOR + margin) × period_year_fraction
- Repayment reduces drawn amount from available cash before distributions
- enabled=False is byte-for-byte identical to dsrf=None

DSRA = cash reserve account (separate concept, not modified here)

Terminology: draw, repayment, drawn, undrawn, facility limit.
Do NOT use: top-up, release, balance, funded (those are DSRA concepts).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DSRFConfig:
    """Configuration for a revolving debt service reserve facility.

    DSRF is a committed revolving facility. It is NOT a cash reserve account.
    sizing_months selects facility size: 6, 9, or 12 months of average debt service.
    """
    enabled: bool = False
    # Sizing
    sizing_months: int = 6          # allowed values: 6, 9, 12
    sizing_basis: str = "average_debt_service"
    # Facility economics
    commitment_fee_rate_pa: float = 0.0   # e.g. 0.5% p.a. on undrawn amount
    margin_rate_pa: float = 0.0           # e.g. 2.0% p.a. on drawn amount
    euribor_rate_pa: float = 0.0           # e.g. 3.0% p.a. reference rate
    period_year_fraction: float = 0.5     # 0.5 for semiannual periods
    # Behavior
    repayment_priority: str = "before_distributions"
    allow_draw_for_debt_service_shortfall: bool = True

    def __post_init__(self):
        if self.enabled:
            if self.sizing_months not in (6, 9, 12):
                raise ValueError(
                    f"sizing_months must be one of 6, 9, 12; got {self.sizing_months}"
                )
            if self.commitment_fee_rate_pa < 0:
                raise ValueError(
                    f"commitment_fee_rate_pa must be >= 0, got {self.commitment_fee_rate_pa}"
                )
            if self.margin_rate_pa < 0:
                raise ValueError(
                    f"margin_rate_pa must be >= 0, got {self.margin_rate_pa}"
                )

            if self.period_year_fraction <= 0:
                raise ValueError(
                    f"period_year_fraction must be > 0, got {self.period_year_fraction}"
                )
            if self.sizing_basis != "average_debt_service":
                raise ValueError(
                    f"sizing_basis must be 'average_debt_service' for enabled DSRF; "
                    f"got {self.sizing_basis!r}"
                )
            if self.repayment_priority != "before_distributions":
                raise ValueError(
                    f"repayment_priority must be 'before_distributions' for enabled DSRF; "
                    f"got {self.repayment_priority!r}"
                )


@dataclass(frozen=True)
class DSRFPeriod:
    """DSRF result for a single semiannual period."""
    period: int
    spv_code: str
    # Facility
    facility_limit_keur: float
    # Start of period (before any draws)
    drawn_start_keur: float
    undrawn_start_keur: float   # = max(0, facility_limit - drawn_start)
    # Inputs
    scheduled_senior_ds_keur: float
    cfads_available_keur: float
    # DSRF activity
    debt_service_shortfall_keur: float   # shortfall before DSRF draw
    draw_keur: float                    # amount drawn this period
    # Fees (applied after draw)
    drawn_after_draw_keur: float         # drawn_start + draw
    commitment_fee_keur: float           # on undrawn after draw
    drawn_interest_keur: float          # on drawn_after_draw
    # Repayment
    repayment_keur: float               # repaid before distributions
    # End of period
    drawn_end_keur: float
    undrawn_end_keur: float              # = max(0, facility_limit - drawn_end)
    # Senior debt service actually paid (including DSRF draw)
    senior_ds_paid_keur: float
    # Cash available for distribution after all DSRF costs
    cash_available_for_distribution_keur: float


@dataclass(frozen=True)
class DSRFResult:
    """Aggregate DSRF results across all periods."""
    config: DSRFConfig
    periods: tuple[DSRFPeriod, ...]
    # Totals
    total_draw_keur: float = 0.0
    total_repayment_keur: float = 0.0
    total_commitment_fee_keur: float = 0.0
    total_drawn_interest_keur: float = 0.0
    total_debt_service_support_keur: float = 0.0
    # Facility
    facility_limit_keur: float = 0.0
    drawn_end_keur: float = 0.0   # drawn amount at end of last period

    @property
    def undrawn_end_keur(self) -> float:
        return max(0.0, self.facility_limit_keur - self.drawn_end_keur)


def calculate_average_debt_service(
    semiannual_debt_service_schedule: tuple[float, ...],
) -> float:
    """Calculate average semiannual senior debt service over the repayment period.

    Args:
        semiannual_debt_service_schedule: tuple of scheduled senior debt service per period (kEUR)

    Returns:
        Average senior debt service per semiannual period (kEUR)
    """
    if not semiannual_debt_service_schedule:
        return 0.0
    return sum(semiannual_debt_service_schedule) / len(semiannual_debt_service_schedule)


def calculate_facility_limit(
    average_period_debt_service_keur: float,
    sizing_months: int,
) -> float:
    """Calculate DSRF facility limit.


    Formula: facility_limit = average_period_DS × (sizing_months / 6)

    Examples:
        sizing_months=6  → 1.0 × average semiannual DS
        sizing_months=9  → 1.5 × average semiannual DS
        sizing_months=12 → 2.0 × average semiannual DS

    Raises:
        ValueError: if sizing_months is not 6, 9, or 12
    """
    if sizing_months not in (6, 9, 12):
        raise ValueError(
            f"sizing_months must be one of 6, 9, 12; got {sizing_months}"
        )
    if average_period_debt_service_keur < 0:
        raise ValueError(
            f"average_period_debt_service_keur must be >= 0, got {average_period_debt_service_keur}"
        )
    return average_period_debt_service_keur * (sizing_months / 6.0)


def calculate_period_dsrf(
    period: int,
    spv_code: str,
    cfads_available_keur: float,
    scheduled_senior_ds_keur: float,
    drawn_start_keur: float,
    facility_limit_keur: float,
    config: DSRFConfig,
) -> DSRFPeriod:
    """Calculate DSRF state for a single semiannual period.

    Draw happens BEFORE senior debt service is paid (to cover the shortfall).
    Fees and repayment consume cash after senior debt service is paid.

    This is a simplified semiannual convention, not daily accrual:
    - Commitment fee is charged on undrawn facility AFTER any period draw
    - Drawn interest is charged on drawn_after_draw
    - All rates are expressed as annual percentages; period charge = rate × period_year_fraction

    Returns:
        DSRFPeriod with all calculated values.
    """
    # Validate direct inputs (schedule-level function validates schedule length;
    # this guards against invalid direct calls)
    if scheduled_senior_ds_keur < 0:
        raise ValueError(
            f"scheduled_senior_ds_keur must be >= 0, got {scheduled_senior_ds_keur}"
        )
    if drawn_start_keur < 0:
        raise ValueError(
            f"drawn_start_keur must be >= 0, got {drawn_start_keur}"
        )
    if facility_limit_keur < 0:
        raise ValueError(
            f"facility_limit_keur must be >= 0, got {facility_limit_keur}"
        )

    if not config.enabled or facility_limit_keur <= 0:
        # No-op: return zero-activity period
        return DSRFPeriod(
            period=period, spv_code=spv_code,
            facility_limit_keur=0.0,
            drawn_start_keur=0.0, undrawn_start_keur=0.0,
            scheduled_senior_ds_keur=scheduled_senior_ds_keur,
            cfads_available_keur=cfads_available_keur,
            debt_service_shortfall_keur=0.0,
            draw_keur=0.0,
            drawn_after_draw_keur=0.0,
            commitment_fee_keur=0.0,
            drawn_interest_keur=0.0,
            repayment_keur=0.0,
            drawn_end_keur=0.0,
            undrawn_end_keur=0.0,
            senior_ds_paid_keur=min(scheduled_senior_ds_keur, cfads_available_keur),
            cash_available_for_distribution_keur=max(0.0, cfads_available_keur - scheduled_senior_ds_keur),
        )

    # Undrawn at start of period
    undrawn_start = max(0.0, facility_limit_keur - drawn_start_keur)

    # Shortfall before DSRF draw
    shortfall = max(0.0, scheduled_senior_ds_keur - cfads_available_keur)

    # Draw (only if shortfall exists and draw is allowed)
    if config.allow_draw_for_debt_service_shortfall and shortfall > 0:
        draw = min(shortfall, undrawn_start)
    else:
        draw = 0.0

    # Drawn amount after draw (before fees)
    drawn_after_draw = drawn_start_keur + draw

    # Senior debt service actually paid (CFADS + draw)
    senior_ds_paid = min(
        scheduled_senior_ds_keur,
        cfads_available_keur + draw,
    )

    # Undrawn after draw (used for commitment fee calculation)
    undrawn_after_draw = max(0.0, facility_limit_keur - drawn_after_draw)

    # Commitment fee on undrawn portion after draw
    commitment_fee = (
        undrawn_after_draw
        * config.commitment_fee_rate_pa
        * config.period_year_fraction
    )

    # Interest on drawn portion (EURIBOR + margin, floored at 0)
    # Negative EURIBOR is allowed but drawn interest cannot go negative
    effective_rate = max(0.0, config.margin_rate_pa + config.euribor_rate_pa)
    drawn_interest = (
        drawn_after_draw
        * effective_rate
        * config.period_year_fraction
    )

    # Cash after senior debt service is paid (CFADS - scheduled senior DS, floored at 0)
    cash_after_senior_ds = max(0.0, cfads_available_keur - scheduled_senior_ds_keur)

    # Cash after DSRF fees
    cash_after_fees = max(
        0.0,
        cash_after_senior_ds - commitment_fee - drawn_interest,
    )

    # Repayment (before distributions, capped by available cash and drawn amount)
    if config.repayment_priority == "before_distributions":
        repayment = min(cash_after_fees, drawn_after_draw)
    else:
        repayment = 0.0

    # Drawn amount at end of period
    drawn_end = max(0.0, drawn_after_draw - repayment)

    # Undrawn at end of period
    undrawn_end = max(0.0, facility_limit_keur - drawn_end)

    # Cash available for distribution (after fees and repayment)
    cash_for_dist = max(0.0, cash_after_fees - repayment)

    return DSRFPeriod(
        period=period, spv_code=spv_code,
        facility_limit_keur=facility_limit_keur,
        drawn_start_keur=drawn_start_keur,
        undrawn_start_keur=undrawn_start,
        scheduled_senior_ds_keur=scheduled_senior_ds_keur,
        cfads_available_keur=cfads_available_keur,
        debt_service_shortfall_keur=shortfall,
        draw_keur=draw,
        drawn_after_draw_keur=drawn_after_draw,
        commitment_fee_keur=commitment_fee,
        drawn_interest_keur=drawn_interest,
        repayment_keur=repayment,
        drawn_end_keur=drawn_end,
        undrawn_end_keur=undrawn_end,
        senior_ds_paid_keur=senior_ds_paid,
        cash_available_for_distribution_keur=cash_for_dist,
    )


def run_dsrf_facility_schedule(
    spv_code: str,
    semiannual_debt_service_schedule: tuple[float, ...],
    cfads_schedule: tuple[float, ...],
    config: DSRFConfig,
) -> DSRFResult:
    """Run DSRF facility across all semiannual periods.

    Args:
        spv_code: SPV identifier
        semiannual_debt_service_schedule: tuple of scheduled senior debt service per period (kEUR)
        cfads_schedule: tuple of CFADS per period (kEUR)
        config: DSRFConfig

    Returns:
        DSRFResult with per-period detail and aggregates.

    Note:
        enabled=False returns result with zero activity — byte-for-byte
        identical to passing dsrf=None once integrated.
    """
    if not config.enabled:
        return DSRFResult(
            config=config,
            periods=(),
            total_draw_keur=0.0,
            total_repayment_keur=0.0,
            total_commitment_fee_keur=0.0,
            total_drawn_interest_keur=0.0,
            total_debt_service_support_keur=0.0,
            facility_limit_keur=0.0,
            drawn_end_keur=0.0,
        )

    if len(semiannual_debt_service_schedule) != len(cfads_schedule):
        raise ValueError(
            f"schedule length mismatch: "
            f"debt_service_schedule has {len(semiannual_debt_service_schedule)} periods, "
            f"cfads_schedule has {len(cfads_schedule)} periods"
        )

    for i, ds in enumerate(semiannual_debt_service_schedule):
        if ds < 0:
            raise ValueError(
                f"scheduled senior debt service at period {i} is negative: {ds} kEUR"
            )

    avg_ds = calculate_average_debt_service(semiannual_debt_service_schedule)
    facility_limit = calculate_facility_limit(avg_ds, config.sizing_months)

    periods = []
    drawn_start = 0.0
    total_draw = 0.0
    total_repayment = 0.0
    total_commitment = 0.0
    total_interest = 0.0
    total_support = 0.0

    for i, (ds, cfads) in enumerate(zip(semiannual_debt_service_schedule, cfads_schedule)):
        p = calculate_period_dsrf(
            period=i,
            spv_code=spv_code,
            cfads_available_keur=cfads,
            scheduled_senior_ds_keur=ds,
            drawn_start_keur=drawn_start,
            facility_limit_keur=facility_limit,
            config=config,
        )
        periods.append(p)
        drawn_start = p.drawn_end_keur
        total_draw += p.draw_keur
        total_repayment += p.repayment_keur
        total_commitment += p.commitment_fee_keur
        total_interest += p.drawn_interest_keur
        total_support += p.draw_keur  # actual draw, not shortfall (shortfall may exceed undrawn)

    return DSRFResult(
        config=config,
        periods=tuple(periods),
        total_draw_keur=total_draw,
        total_repayment_keur=total_repayment,
        total_commitment_fee_keur=total_commitment,
        total_drawn_interest_keur=total_interest,
        total_debt_service_support_keur=total_support,
        facility_limit_keur=facility_limit,
        drawn_end_keur=drawn_start,
    )


__all__ = [
    "DSRFConfig",
    "DSRFPeriod",
    "DSRFResult",
    "calculate_average_debt_service",
    "calculate_facility_limit",
    "calculate_period_dsrf",
    "run_dsrf_facility_schedule",
]