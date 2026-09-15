"""Source-waterfall construction funding allocation."""

from __future__ import annotations

from domain.construction.config import FundingSourceCaps
from domain.construction.result import ConstructionMonthlyEntry


def allocate_source_waterfall(
    monthly_uses_keur: tuple[float, ...],
    funding_caps: FundingSourceCaps,
    *,
    tolerance_keur: float = 0.01,
) -> tuple[ConstructionMonthlyEntry, ...]:
    """Allocate monthly uses through equity, SHL, junior, then senior debt."""

    if any(value < 0 for value in monthly_uses_keur):
        raise ValueError("monthly construction uses cannot be negative")

    caps = (
        funding_caps.equity_shares_keur,
        funding_caps.shl_keur,
        funding_caps.junior_keur,
        funding_caps.senior_debt_keur,
    )
    if any(cap < 0 for cap in caps):
        raise ValueError("funding source caps cannot be negative")

    total_uses = sum(monthly_uses_keur)
    if funding_caps.total_keur + tolerance_keur < total_uses:
        raise ValueError(
            f"Funding source caps {funding_caps.total_keur:.3f} kEUR do not cover "
            f"construction uses {total_uses:.3f} kEUR"
        )

    entries: list[ConstructionMonthlyEntry] = []
    previous_cumulative = [0.0, 0.0, 0.0, 0.0]
    cumulative_uses = 0.0

    for idx, monthly_uses in enumerate(monthly_uses_keur, start=1):
        cumulative_uses += monthly_uses
        remaining = cumulative_uses
        cumulative = []
        for cap in caps:
            source_cumulative = min(cap, max(0.0, remaining))
            cumulative.append(source_cumulative)
            remaining -= source_cumulative

        monthly_draws = [
            max(0.0, current - previous)
            for current, previous in zip(cumulative, previous_cumulative)
        ]
        monthly_funding = sum(monthly_draws)
        if abs(monthly_funding - monthly_uses) > tolerance_keur:
            raise ValueError(
                f"Month {idx} funding {monthly_funding:.3f} kEUR does not match "
                f"uses {monthly_uses:.3f} kEUR"
            )

        entries.append(
            ConstructionMonthlyEntry(
                month_index=idx,
                monthly_uses_keur=monthly_uses,
                cumulative_uses_keur=cumulative_uses,
                equity_draw_keur=monthly_draws[0],
                shl_draw_keur=monthly_draws[1],
                junior_draw_keur=monthly_draws[2],
                senior_draw_keur=monthly_draws[3],
                cumulative_equity_keur=cumulative[0],
                cumulative_shl_keur=cumulative[1],
                cumulative_junior_keur=cumulative[2],
                cumulative_senior_keur=cumulative[3],
            )
        )
        previous_cumulative = cumulative

    return tuple(entries)


__all__ = ["allocate_source_waterfall"]
