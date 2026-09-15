"""Synthetic construction-funding template for Generic Solar Reference."""

from __future__ import annotations

from datetime import date

from domain.construction.config import CapexProfileType, ConstructionConfig, FundingSourceCaps

GENERIC_SOLAR_REFERENCE_MONTHLY_USES_KEUR = tuple([2750.0] * 12)


def build_generic_solar_reference_construction_config() -> ConstructionConfig:
    """Return a round-number, jurisdiction-neutral solar construction template."""
    fractions = tuple(1.0 / 12.0 for _ in GENERIC_SOLAR_REFERENCE_MONTHLY_USES_KEUR)
    return ConstructionConfig(
        project_code="REF-SOLAR-A",
        construction_start_date=date(2027, 1, 1),
        cod_date=date(2028, 1, 1),
        construction_months=12,
        total_uses_keur=33_000.0,
        profile_type=CapexProfileType.CUSTOM,
        monthly_uses_keur=GENERIC_SOLAR_REFERENCE_MONTHLY_USES_KEUR,
        funding_caps=FundingSourceCaps(
            equity_shares_keur=3_000.0,
            shl_keur=6_000.0,
            junior_keur=0.0,
            senior_debt_keur=24_000.0,
        ),
        shl_interest_rate=0.06,
        shl_investment_date=date(2027, 1, 1),
        shl_day_count_denominator=365.0,
        senior_interest_rate=0.05,
        senior_interest_period_fractions=fractions,
        senior_idc_target_keur=None,
        senior_idc_notes="Synthetic public reference; no external calibration target.",
    )


__all__ = ["GENERIC_SOLAR_REFERENCE_MONTHLY_USES_KEUR", "build_generic_solar_reference_construction_config"]
