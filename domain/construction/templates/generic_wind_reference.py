"""Synthetic construction-funding template for Generic Wind Reference."""

from __future__ import annotations

from datetime import date

from domain.construction.config import CapexProfileType, ConstructionConfig, FundingSourceCaps

GENERIC_WIND_MONTHLY_USES_KEUR = tuple([2150.0] * 20)


def build_generic_wind_reference_construction_config() -> ConstructionConfig:
    """Return a round-number, jurisdiction-neutral wind construction template."""
    fractions = tuple(1.0 / 20.0 for _ in GENERIC_WIND_MONTHLY_USES_KEUR)
    return ConstructionConfig(
        project_code="REF-WIND-B",
        construction_start_date=date(2027, 1, 1),
        cod_date=date(2028, 9, 1),
        construction_months=20,
        total_uses_keur=43_000.0,
        profile_type=CapexProfileType.CUSTOM,
        monthly_uses_keur=GENERIC_WIND_MONTHLY_USES_KEUR,
        funding_caps=FundingSourceCaps(
            equity_shares_keur=4_000.0,
            shl_keur=9_000.0,
            junior_keur=0.0,
            senior_debt_keur=30_000.0,
        ),
        shl_interest_rate=0.06,
        shl_investment_date=date(2027, 1, 1),
        shl_day_count_denominator=365.0,
        senior_interest_rate=0.05,
        senior_interest_period_fractions=fractions,
        senior_idc_target_keur=None,
        senior_idc_notes="Synthetic public reference; no external calibration target.",
    )


__all__ = ["GENERIC_WIND_MONTHLY_USES_KEUR", "build_generic_wind_reference_construction_config"]
