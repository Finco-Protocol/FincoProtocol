"""SHL construction period engine — multi-period draw schedule (Fix 3 architecture).

This module provides the canonical multi-period construction engine. Typed PR-9
construction financing invokes it through the explicit financing handoff;
legacy single-period construction remains in production.py::compute_shl_schedule.

FULL_PRINCIPAL_AT_FC_COMPOUND_COUNTERFACTUAL diagnostic functions are
provided for testing and comparison only — they assume all SHL principal
exists at financial close and are NOT used in production calculations.

SIMPLE multi-period semantics (Fix 2 closeout)
-----------------------------------------------
SIMPLE interest must NOT compound: accumulated PIK from prior periods must
never enter the interest basis of a subsequent period.

  cash_principal_balance[t] = cash_principal_balance[t-1] + draw[t]
  interest[t] = cash_principal_balance[t] * annual_rate * dcf[t]
  accumulated_pik[t] = accumulated_pik[t-1] + interest[t]
  closing_total_shl[t] = cash_principal_balance[t] + accumulated_pik[t]

The cash-principal balance is tracked separately and exposed via
ShlConstructionPeriodResult.cash_principal_balance_keur.

COMPOUND_PERIODIC multi-period semantics
-----------------------------------------
Prior closing total (including accumulated PIK) enters the next period's
interest basis:

  balance_for_interest[t] = prior_closing_total_shl[t-1] + draw[t]
  interest[t] = balance_for_interest[t] * ((1+rate)^dcf[t] - 1)
  closing_total_shl[t] = balance_for_interest[t] + interest[t]
"""
from __future__ import annotations

from dataclasses import dataclass
from finco_core.inputs._models import ShlConstructionInterestMethod


@dataclass(frozen=True)
class ShlConstructionPeriodInput:
    """One construction draw period for the multi-period engine."""
    draw_keur: float
    day_count_fraction: float
    period_index: int = 0


@dataclass(frozen=True)
class ShlConstructionPeriodResult:
    """Result for one construction draw period.

    Invariants (hold for BOTH SIMPLE and COMPOUND_PERIODIC):
      opening_balance_keur      = total SHL liability at start of period before current draw
                                  (includes prior accumulated PIK for COMPOUND; cash-only for SIMPLE
                                  since PIK from prior periods does not re-enter the SIMPLE basis)
      cash_principal_balance_keur = cumulative cash principal drawn (excludes PIK, both methods)
      pik_interest_keur         = interest accrued this period
      closing_balance_keur      = opening_balance_keur + draw_keur + pik_interest_keur  (identity)
      interest_basis_keur       = basis used to compute pik_interest_keur:
                                    SIMPLE:   cash_principal_balance_keur (post-draw)
                                    COMPOUND: opening_balance_keur + draw_keur
    """
    period_index: int
    opening_balance_keur: float
    draw_keur: float
    pik_interest_keur: float
    closing_balance_keur: float
    cash_principal_balance_keur: float = 0.0
    interest_basis_keur: float = 0.0


@dataclass(frozen=True)
class ShlConstructionScheduleResult:
    """Result of compute_shl_construction_schedule."""
    periods: tuple[ShlConstructionPeriodResult, ...]
    total_pik_keur: float
    opening_operating_shl_balance_keur: float
    method: ShlConstructionInterestMethod
    interest_rate: float


def compute_shl_construction_schedule(
    opening_balance_keur: float,
    periods: tuple[ShlConstructionPeriodInput, ...],
    annual_rate: float,
    method: ShlConstructionInterestMethod,
) -> ShlConstructionScheduleResult:
    """Multi-period SHL construction engine for Fix 3 architecture.

    SIMPLE: interest basis = cash principal draws only (no PIK compounding).
      interest[t] = cash_principal_balance[t] * rate * dcf[t]
      PIK does NOT re-enter the interest basis in subsequent periods.

    COMPOUND_PERIODIC: prior closing total (including PIK) enters next period.
      interest[t] = (prior_closing + draw[t]) * ((1+rate)^dcf[t] - 1)

    Production single-draw boundary:
      For a single-period draw at financial close with dcf covering the full
      construction period, SIMPLE = P*r*t and COMPOUND = P*((1+r)^t - 1),
      matching compute_shl_construction_pik_keur in this module and the
      production.py single-draw path. No project-specific calibration constants are embedded in this implementation.
    """
    results: list[ShlConstructionPeriodResult] = []

    if method == ShlConstructionInterestMethod.SIMPLE:
        # SIMPLE: track cash principal balance and accumulated PIK separately.
        # Interest basis = cash principal only; PIK never re-enters the basis.
        # opening_balance is the total liability (cash + prior accumulated PIK).
        cash_principal = opening_balance_keur
        accumulated_pik = 0.0
        for p in periods:
            # opening_balance = total liability before this draw (cash + prior PIK)
            opening_total = cash_principal + accumulated_pik
            cash_principal = cash_principal + p.draw_keur
            interest_basis = cash_principal  # SIMPLE: basis = post-draw cash principal
            if p.day_count_fraction == 0.0 or interest_basis == 0.0:
                interest = 0.0
            else:
                interest = interest_basis * annual_rate * p.day_count_fraction
            accumulated_pik = accumulated_pik + interest
            closing_total = opening_total + p.draw_keur + interest  # identity
            results.append(ShlConstructionPeriodResult(
                period_index=p.period_index,
                opening_balance_keur=opening_total,
                draw_keur=p.draw_keur,
                pik_interest_keur=interest,
                closing_balance_keur=closing_total,
                cash_principal_balance_keur=cash_principal,
                interest_basis_keur=interest_basis,
            ))
        total_pik = sum(r.pik_interest_keur for r in results)
        final_closing = results[-1].closing_balance_keur if results else opening_balance_keur
        return ShlConstructionScheduleResult(
            periods=tuple(results),
            total_pik_keur=total_pik,
            opening_operating_shl_balance_keur=final_closing,
            method=method,
            interest_rate=annual_rate,
        )
    elif method == ShlConstructionInterestMethod.COMPOUND_PERIODIC:
        # COMPOUND_PERIODIC: prior closing total (including PIK) is the next
        # period's opening balance for interest accrual.
        balance = opening_balance_keur
        cash_principal = opening_balance_keur
        for p in periods:
            opening_total = balance
            cash_principal = cash_principal + p.draw_keur
            interest_basis = opening_total + p.draw_keur  # COMPOUND: basis = opening + draw
            if p.day_count_fraction == 0.0 or interest_basis == 0.0:
                interest = 0.0
            else:
                interest = interest_basis * (
                    (1.0 + annual_rate) ** p.day_count_fraction - 1.0
                )
            closing = opening_total + p.draw_keur + interest  # identity
            results.append(ShlConstructionPeriodResult(
                period_index=p.period_index,
                opening_balance_keur=opening_total,
                draw_keur=p.draw_keur,
                pik_interest_keur=interest,
                closing_balance_keur=closing,
                cash_principal_balance_keur=cash_principal,
                interest_basis_keur=interest_basis,
            ))
            balance = closing
        total_pik = sum(r.pik_interest_keur for r in results)
        return ShlConstructionScheduleResult(
            periods=tuple(results),
            total_pik_keur=total_pik,
            opening_operating_shl_balance_keur=balance,
            method=method,
            interest_rate=annual_rate,
        )
    else:
        raise ValueError(
            f"compute_shl_construction_schedule: unsupported construction_interest_method {method!r}. "
            f"Supported: SIMPLE, COMPOUND_PERIODIC."
        )


def build_shl_construction_draw_schedule(
    shl_cash_principal_keur: float,
    construction_periods: tuple[ShlConstructionPeriodInput, ...],
    policy: "SponsorFundingTimingPolicy",
) -> tuple[ShlConstructionPeriodInput, ...]:
    """Build SHL draw schedule per policy.

    PRO_RATA_CONSTRUCTION: draw proportional to each period's day_count_fraction / total_dcf
    ALL_AT_FC: full principal in first period, zero thereafter.

    Total draws always sum to shl_cash_principal_keur.
    """
    from finco_core.inputs._models import SponsorFundingTimingPolicy as Policy
    if policy == Policy.ALL_AT_FC:
        return tuple(
            ShlConstructionPeriodInput(
                draw_keur=shl_cash_principal_keur if i == 0 else 0.0,
                day_count_fraction=p.day_count_fraction,
                period_index=p.period_index,
            )
            for i, p in enumerate(construction_periods)
        )
    elif policy == Policy.PRO_RATA_CONSTRUCTION:
        total_dcf = sum(p.day_count_fraction for p in construction_periods)
        if total_dcf == 0.0:
            return tuple(
                ShlConstructionPeriodInput(draw_keur=0.0, day_count_fraction=p.day_count_fraction, period_index=p.period_index)
                for p in construction_periods
            )
        return tuple(
            ShlConstructionPeriodInput(
                draw_keur=shl_cash_principal_keur * p.day_count_fraction / total_dcf,
                day_count_fraction=p.day_count_fraction,
                period_index=p.period_index,
            )
            for p in construction_periods
        )
    else:
        raise ValueError(
            f"build_shl_construction_draw_schedule: unsupported SponsorFundingTimingPolicy {policy!r}. "
            f"Supported: PRO_RATA_CONSTRUCTION, ALL_AT_FC."
        )


def build_shl_construction_draw_schedule_from_uses(
    shl_cash_principal_keur: float,
    period_uses_keur: tuple[float, ...],
    period_senior_draws_keur: tuple[float, ...],
    period_junior_draws_keur: tuple[float, ...],
    period_other_sources_keur: tuple[float, ...],
    period_dcfs: tuple[float, ...],
    policy: "SponsorFundingTimingPolicy",
) -> tuple[ShlConstructionPeriodInput, ...]:
    """Build SHL draw schedule from actual construction funding needs.

    PRO_RATA_CONSTRUCTION: SHL drawn proportional to net Sponsor funding need per period.
        net_need[t] = uses[t] - senior[t] - junior[t] - other[t]
        shl_draw[t] = principal * net_need[t] / total_net_need
    ALL_AT_FC: Full principal at period 0, zero thereafter.

    Total draws sum to shl_cash_principal_keur under both policies.
    """
    from finco_core.inputs._models import SponsorFundingTimingPolicy as Policy
    if policy == Policy.ALL_AT_FC:
        return tuple(
            ShlConstructionPeriodInput(
                draw_keur=shl_cash_principal_keur if i == 0 else 0.0,
                day_count_fraction=dcf,
                period_index=i,
            )
            for i, dcf in enumerate(period_dcfs)
        )
    elif policy == Policy.PRO_RATA_CONSTRUCTION:
        net_needs = tuple(
            max(0.0, uses - senior - junior - other)
            for uses, senior, junior, other in zip(
                period_uses_keur, period_senior_draws_keur,
                period_junior_draws_keur, period_other_sources_keur
            )
        )
        total_need = sum(net_needs)
        if total_need == 0.0 and shl_cash_principal_keur > 0.0:
            raise ValueError(
                "build_shl_construction_draw_schedule_from_uses: total net Sponsor funding need is zero "
                "but shl_cash_principal_keur > 0. Schedule is internally inconsistent. "
                "Only PRO_RATA with zero net need when principal is also zero."
            )
        if total_need == 0.0:
            draws = tuple(0.0 for _ in period_dcfs)
        else:
            draws = tuple(shl_cash_principal_keur * need / total_need for need in net_needs)
        return tuple(
            ShlConstructionPeriodInput(draw_keur=d, day_count_fraction=dcf, period_index=i)
            for i, (d, dcf) in enumerate(zip(draws, period_dcfs))
        )
    else:
        raise ValueError(
            f"build_shl_construction_draw_schedule_from_uses: unsupported policy {policy!r}. "
            f"Supported: PRO_RATA_CONSTRUCTION, ALL_AT_FC."
        )


def compute_shl_construction_pik_keur(
    shl_cash_principal_keur: float,
    annual_rate: float,
    construction_day_count_fraction: float,
    method: ShlConstructionInterestMethod,
) -> float:
    """FULL_PRINCIPAL_AT_FC diagnostic: PIK under the assumption all SHL drawn at FC.

    SIMPLE: P * r * t
    COMPOUND_PERIODIC: P * ((1+r)^t - 1)

    This function assumes the FULL principal exists at financial close.
    It is valid for diagnostic method comparison but is NOT used in production calculations.
    Production uses compute_shl_schedule() in production.py.
    """
    if construction_day_count_fraction == 0.0 or shl_cash_principal_keur == 0.0:
        return 0.0
    if method == ShlConstructionInterestMethod.COMPOUND_PERIODIC:
        return shl_cash_principal_keur * (
            (1.0 + annual_rate) ** construction_day_count_fraction - 1.0
        )
    elif method == ShlConstructionInterestMethod.SIMPLE:
        return shl_cash_principal_keur * annual_rate * construction_day_count_fraction
    else:
        raise ValueError(
            f"compute_shl_construction_pik_keur: unsupported method {method!r}"
        )


def compute_full_principal_at_fc_compound_counterfactual(
    full_principal_keur: float,
    annual_rate: float,
    total_construction_dcf: float,
) -> float:
    """DIAGNOSTIC ONLY: full-at-FC compound formula P*((1+r)^T - 1).

    FULL_PRINCIPAL_AT_FC_COMPOUND_COUNTERFACTUAL: assumes entire SHL principal
    drawn at financial close. Not used in production. Valid only for comparison
    diagnostics; no project-specific comparison constants are embedded here.
    """
    if total_construction_dcf == 0.0 or full_principal_keur == 0.0:
        return 0.0
    return full_principal_keur * ((1.0 + annual_rate) ** total_construction_dcf - 1.0)
