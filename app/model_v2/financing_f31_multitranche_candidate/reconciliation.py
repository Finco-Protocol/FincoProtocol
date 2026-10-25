"""Candidate multi-tranche source/use reconciliation — released rules, pure.

Mirrors the released F3 reconciliation rules
(``financial_engine/financing/multisenior.run_multisenior_financing``):
aggregate senior = sum of contractual commitments; the gearing cap is a
constraint (never a resizing authority); contractual dated senior draws fund
uses first and the equity allocator fills the residual; a period whose dated
draws exceed its funded uses fails closed; optional canonical-CFADS
shortfall check on contractual service.

``total_project_uses_keur`` / ``period_uses_keur`` are SUPPLIED canonical
authority outputs — the candidate never recomputes project uses.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import fsum
from typing import Optional, Sequence

from finco_core.inputs.financing_instruments import FinancingError

from app.model_v2.financing_f31_multitranche_candidate.schedules import (
    CandidateFacilitySchedule,
    TOLERANCE_KEUR,
)


@dataclass(frozen=True)
class EquityDrawRow:
    """Per-construction-period equity fill after contractual senior draws."""

    period_position: int
    period_uses_keur: float
    senior_draw_keur: float
    share_capital_draw_keur: float
    share_premium_draw_keur: float
    other_committed_equity_draw_keur: float
    additional_equity_draw_keur: float
    residual_keur: float


@dataclass(frozen=True)
class MultitrancheReconciliation:
    aggregate_senior_commitment_keur: float
    total_project_uses_keur: float
    gearing_capacity_keur: float
    per_period: tuple[EquityDrawRow, ...]
    sources_uses_residual_keur: float
    additional_equity_keur: float


def _equity_fill(residual: float, *, share_capital: float, share_premium: float,
                 other_equity: float, additional_equity: float) -> tuple[float, float, float, float, float]:
    """Released funding order: share capital -> premium -> other -> additional.

    A negative residual after the full equity stack fails closed (the uses
    cannot be funded by the declared sources).
    """
    share_capital_used = min(share_capital, max(0.0, residual))
    residual -= share_capital_used
    share_premium_used = min(share_premium, max(0.0, residual))
    residual -= share_premium_used
    other_used = min(other_equity, max(0.0, residual))
    residual -= other_used
    additional_used = min(additional_equity, max(0.0, residual))
    residual -= additional_used
    return share_capital_used, share_premium_used, other_used, additional_used, residual


def reconcile_multitranche_sources_uses(
    facilities: Sequence[CandidateFacilitySchedule],
    *,
    total_project_uses_keur: float,
    period_uses_keur: Sequence[float],
    gearing_ratio: float,
    share_capital_keur: float,
    share_premium_keur: float,
    other_equity_keur: float,
    additional_equity_keur: Optional[float] = None,
    cfads_by_period: Optional[dict[int, float]] = None,
) -> MultitrancheReconciliation:
    """Reconcile N tranches against the canonical uses. Fail closed on any
    released rule violation; never resize commitments."""
    if not facilities:
        raise FinancingError("F3_MULTITRANCHE_COUNT_UNSUPPORTED", "no facilities")
    if additional_equity_keur is None:
        raise FinancingError(
            "F3_MULTITRANCHE_ADDITIONAL_EQUITY_REQUIRED",
            "the residual equity output of the canonical stack must be "
            "supplied (candidate never sizes equity)")
    senior_total = fsum(f.commitment_keur for f in facilities)
    gearing_capacity = total_project_uses_keur * gearing_ratio
    if senior_total > gearing_capacity + TOLERANCE_KEUR:
        raise FinancingError(
            "F3_AGGREGATE_GEARING_CAP_EXCEEDED",
            f"aggregate senior {senior_total} > gearing capacity "
            f"{gearing_capacity}")
    draws_by_period = _draws_by_construction_period(facilities, len(period_uses_keur))
    if abs(fsum(period_uses_keur) - total_project_uses_keur) > TOLERANCE_KEUR:
        raise FinancingError(
            "F3_CONSTRUCTION_USES_DO_NOT_RECONCILE",
            f"period uses {fsum(period_uses_keur)} != total uses "
            f"{total_project_uses_keur}")
    rows = []
    cumulative_residual = 0.0
    for position, uses in enumerate(period_uses_keur):
        drawn = draws_by_period[position]
        if drawn > uses + TOLERANCE_KEUR:
            raise FinancingError(
                "F3_PERIOD_OVERFUNDING",
                f"dated senior draws {drawn} exceed that period's funded "
                f"uses {uses}")
        residual = uses - drawn
        share_capital_used, share_premium_used, other_used, additional_used, leftover = \
            _equity_fill(
                residual, share_capital=share_capital_keur,
                share_premium=share_premium_keur, other_equity=other_equity_keur,
                additional_equity=additional_equity_keur)
        cumulative_residual += leftover
        rows.append(EquityDrawRow(
            period_position=position, period_uses_keur=uses,
            senior_draw_keur=drawn, share_capital_draw_keur=share_capital_used,
            share_premium_draw_keur=share_premium_used,
            other_committed_equity_draw_keur=other_used,
            additional_equity_draw_keur=additional_used,
            residual_keur=leftover))
    if abs(cumulative_residual) > TOLERANCE_KEUR:
        raise FinancingError(
            "F3_SOURCES_USES_UNRECONCILED",
            f"equity stack leaves residual {cumulative_residual}")
    if cfads_by_period is not None:
        _check_contractual_service_shortfall(facilities, cfads_by_period)
    return MultitrancheReconciliation(
        aggregate_senior_commitment_keur=senior_total,
        total_project_uses_keur=total_project_uses_keur,
        gearing_capacity_keur=gearing_capacity,
        per_period=tuple(rows),
        sources_uses_residual_keur=cumulative_residual,
        additional_equity_keur=additional_equity_keur)


def _draws_by_construction_period(
        facilities: Sequence[CandidateFacilitySchedule],
        period_count: int) -> tuple[float, ...]:
    """Sum of dated draws across tranches per construction period."""
    return tuple(
        fsum(f.construction_draws_keur[position] for f in facilities)
        for position in range(period_count))


def _check_contractual_service_shortfall(
        facilities: Sequence[CandidateFacilitySchedule],
        cfads_by_period: dict[int, float]) -> None:
    """Released rule: contractual service is never resized by available cash."""
    for facility in facilities:
        for idx, service in zip(facility.period_indices,
                                facility.debt_service_keur):
            if service > cfads_by_period.get(idx, 0.0) + TOLERANCE_KEUR:
                raise FinancingError(
                    "F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL", str(idx))
