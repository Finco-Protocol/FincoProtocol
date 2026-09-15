"""Depreciation — financial vs tax reference schedules.

The public repository uses synthetic, jurisdiction-neutral reference lives.
They are modelling assumptions rather than statements of any country's tax law.
"""
from dataclasses import dataclass
from typing import Sequence

from finco_core.engine.period_engine import PeriodMeta


@dataclass(frozen=True)
class DepreciationParams:
    """Odvojeni parametri za financijsku i poreznu amortizaciju."""
    # Financijska amortizacija (za investitora / banku)
    financial_life_years: int  # 30 za solar, 25 za wind
    financial_method: str = "straight_line"  # straight_line | declining_balance
    financial_residual_pct: float = 0.0

    # Tax depreciation may differ from financial depreciation.
    tax_life_years: int = 20  # synthetic reference default
    tax_method: str = "straight_line"
    tax_residual_pct: float = 0.0

    @staticmethod
    def create_solar_generic() -> "DepreciationParams":
        """Solar synthetic reference — 30y financial, 20y tax."""
        return DepreciationParams(
            financial_life_years=30,
            tax_life_years=20,
        )

    @staticmethod
    def create_wind_generic() -> "DepreciationParams":
        """Wind synthetic reference — 25y financial, 20y tax."""
        return DepreciationParams(
            financial_life_years=25,
            tax_life_years=20,
        )

    @staticmethod
    def create_bess_generic() -> "DepreciationParams":
        """Storage synthetic reference — 15y financial, 10y tax."""
        return DepreciationParams(
            financial_life_years=15,
            tax_life_years=10,
        )


def financial_depreciation_schedule(
    capex_keur: float,
    params: DepreciationParams,
    horizon_years: int,
) -> list[float]:
    """Annual financial depreciation in kEUR (straight-line)."""
    if params.financial_life_years <= 0:
        return [0.0] * horizon_years

    if params.financial_method == "straight_line":
        annual = capex_keur / params.financial_life_years
        return [
            annual if y <= params.financial_life_years else 0.0
            for y in range(1, horizon_years + 1)
        ]
    elif params.financial_method == "declining_balance":
        rate = 1.0 / params.financial_life_years * 2  # Double declining
        balance = capex_keur
        schedule = []
        for y in range(1, horizon_years + 1):
            if y <= params.financial_life_years:
                dep = balance * rate
                balance -= dep
                schedule.append(dep)
            else:
                schedule.append(0.0)
        return schedule
    else:
        raise ValueError(f"Unknown method: {params.financial_method}")


def tax_depreciation_schedule(
    capex_keur: float,
    params: DepreciationParams,
    horizon_years: int,
) -> list[float]:
    """Annual synthetic tax depreciation in kEUR."""
    if params.tax_life_years <= 0:
        return [0.0] * horizon_years

    if params.tax_method == "straight_line":
        annual = capex_keur / params.tax_life_years
        return [
            annual if y <= params.tax_life_years else 0.0
            for y in range(1, horizon_years + 1)
        ]
    elif params.tax_method == "declining_balance":
        rate = 1.0 / params.tax_life_years * 2  # Double declining
        balance = capex_keur
        schedule = []
        for y in range(1, horizon_years + 1):
            if y <= params.tax_life_years:
                dep = balance * rate
                balance -= dep
                schedule.append(dep)
            else:
                schedule.append(0.0)
        return schedule
    else:
        raise ValueError(f"Unknown method: {params.tax_method}")


def semi_annual_depreciation(
    annual_schedule: list[float],
    periods: Sequence[PeriodMeta],
) -> dict[int, float]:
    """Convert an annual schedule into semi-annual model periods.

    Args:
        annual_schedule: Annual schedule (index 0 = Y1)
        periods: Sequence of PeriodMeta

    Returns:
        Dict mapping period_index → depreciation in kEUR
    """
    result = {}
    for p in periods:
        if not p.is_operation:
            result[p.index] = 0.0
        else:
            year_dep = (
                annual_schedule[p.year_index - 1]
                if p.year_index <= len(annual_schedule)
                else 0.0
            )
            result[p.index] = year_dep / 2  # Split 50/50 H1/H2
    return result


def financial_depreciation_period(
    capex_keur: float,
    params: DepreciationParams,
    periods: Sequence[PeriodMeta],
) -> dict[int, float]:
    """Financial depreciation schedule po periodu (kEUR)."""
    annual = financial_depreciation_schedule(capex_keur, params, len(periods))
    return semi_annual_depreciation(annual, periods)


def tax_depreciation_period(
    capex_keur: float,
    params: DepreciationParams,
    periods: Sequence[PeriodMeta],
) -> dict[int, float]:
    """Tax depreciation schedule po periodu (kEUR)."""
    annual = tax_depreciation_schedule(capex_keur, params, len(periods))
    return semi_annual_depreciation(annual, periods)
