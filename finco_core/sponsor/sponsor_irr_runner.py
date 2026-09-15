"""Phase 7B — Sponsor IRR & MOIC runner.

Deterministic sponsor-level IRR and MOIC computation from immutable
SponsorCashflowResult outputs. No mutation. No side effects. No hidden state.

The runner accepts an optional fc_date (financial close date) to convert
semiannual period indices to dates for XIRR. If not provided, dates are
derived from the period index assuming 6-month semiannual periods.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from finco_core.sponsor.sponsor_cashflow_result import (
    SponsorCashflowResult,
    SponsorCashflowPeriodResult,
)
from finco_core.sponsor.sponsor_irr_result import (
    SponsorIrrResult,
    SponsorMoicResult,
)
from finco_core.sponsor.xirr_runner import xirr_with_convergence, SponsorXirrResult

__all__ = [
    "SponsorIrrRunnerInputs",
    "SponsorMoicRunnerInputs",
    "run_sponsor_irr",
    "run_sponsor_moic",
]


# ── Runner inputs ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SponsorIrrRunnerInputs:
    """Inputs for sponsor IRR runner.

    Attributes
    ----------
    sponsor_result : SponsorCashflowResult
        The immutable sponsor cashflow result to compute IRR from.
        Must have at least one negative (contribution) and one positive
        (distribution) cashflow for IRR to exist.
    fc_date : date, optional
        Financial close date (date of first equity injection).
        Used to convert period indices to dates for XIRR.
        If None, dates are derived as: fc_date + period_index * 6 months.
    metadata : tuple[tuple[str, Any], ...], optional
        Additional metadata to attach to the result.
    notes : tuple[str, ...], optional
        Additional notes to attach to the result.
    """
    sponsor_result: SponsorCashflowResult
    fc_date: date | None = None
    metadata: tuple[tuple[str, Any], ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class SponsorMoicRunnerInputs:
    """Inputs for sponsor MOIC runner.

    Attributes
    ----------
    sponsor_result : SponsorCashflowResult
        The immutable sponsor cashflow result to compute MOIC from.
    metadata : tuple[tuple[str, Any], ...], optional
        Additional metadata to attach to the result.
    notes : tuple[str, ...], optional
        Additional notes to attach to the result.
    """
    sponsor_result: SponsorCashflowResult
    metadata: tuple[tuple[str, Any], ...] = ()
    notes: tuple[str, ...] = ()


# ── Pure-function runners ─────────────────────────────────────────────────────

def run_sponsor_irr(inputs: SponsorIrrRunnerInputs) -> SponsorIrrResult:
    """Compute sponsor IRR from immutable sponsor cashflow result.

    Deterministic: same inputs always produce identical outputs.
    No mutation of the input SponsorCashflowResult.

    Parameters
    ----------
    inputs : SponsorIrrRunnerInputs
        Bundled inputs including the sponsor result and optional fc_date.

    Returns
    -------
    SponsorIrrResult
        Immutable IRR result with convergence metadata.

    XIRR logic
    ----------
    Cash flows are constructed as net_cashflow_keur per period:
      - negative values = contributions (equity injected)
      - positive values = distributions (returns to sponsor)
    Dates are derived from fc_date + period_index * 6 months (semiannual).
    If fc_date is None, the first period is treated as date 0 (year fraction 0).

    The XIRR solver requires at least one positive and one negative cashflow.
    If this condition is not met, gross_sponsor_irr is None and converged is False.
    """
    result = inputs.sponsor_result

    # ── Build cashflows and dates (single-path) ─────────────────────────────
    cash_flows: list[float] = []
    dates: list[date] = []

    if inputs.fc_date is not None:
        base_date = inputs.fc_date
    else:
        base_date = date(2000, 1, 1)  # dummy base when fc_date not supplied

    for period in result.period_results:
        cash_flows.append(period.net_cashflow_keur)
        # Semiannual period_index → 183 days (≈ 6 months)
        period_date = base_date + timedelta(days=period.period_index * 183)
        dates.append(period_date)

    # ── Compute XIRR ─────────────────────────────────────────────────────────
    xirr_result = xirr_with_convergence(
        cash_flows=cash_flows,
        dates=dates,
        guess=0.10,
        tolerance=1e-7,
        max_iterations=200,
    )

    # ── Build IRR result ──────────────────────────────────────────────────────
    notes_parts: list[str] = []

    if not xirr_result.converged:
        notes_parts.append(
            "XIRR did not converge: check cashflow sign pattern "
            "(requires at least one positive and one negative)"
        )
    elif xirr_result.method == "bisection":
        notes_parts.append("XIRR solved via bisection fallback (Newton-Raphson did not converge)")

    # Check if there are actual contributions and distributions
    has_contribution = any(p.equity_injected_keur > 0 for p in result.period_results)
    has_distribution = any(p.distribution_received_keur > 0 for p in result.period_results)

    if not has_contribution:
        notes_parts.append("no equity injections found in sponsor result")
    if not has_distribution:
        notes_parts.append("no distributions found in sponsor result")

    notes_parts.append(
        f"IRR computed over {result.period_count} semiannual periods; "
        f"total equity injected = {result.total_equity_injected_keur:.2f} kEUR; "
        f"total distributions = {result.total_distributions_received_keur:.2f} kEUR"
    )

    metadata = (
        ("investor_id", result.investor_id),
        ("entity_code", result.entity_code),
        ("period_count", result.period_count),
        ("total_equity_injected_keur", result.total_equity_injected_keur),
        ("total_distributions_received_keur", result.total_distributions_received_keur),
        ("total_wht_keur", result.total_wht_keur),
        ("fc_date", str(inputs.fc_date) if inputs.fc_date else None),
        ("xirr_method", xirr_result.method),
        ("run_type", "sponsor_irr"),
        ("phase", "7B"),
        *inputs.metadata,
    )

    return SponsorIrrResult(
        investor_id=result.investor_id,
        gross_sponsor_irr=xirr_result.rate,
        net_sponsor_irr_placeholder=None,
        xirr_converged=xirr_result.converged,
        xirr_iterations=xirr_result.iterations,
        xirr_tolerance=xirr_result.tolerance,
        metadata=metadata,
        notes=tuple(notes_parts) if notes_parts else ("sponsor IRR result",),
    )


def run_sponsor_moic(inputs: SponsorMoicRunnerInputs) -> SponsorMoicResult:
    """Compute sponsor MOIC from immutable sponsor cashflow result.

    Deterministic: same inputs always produce identical outputs.
    No mutation of the input SponsorCashflowResult.

    MOIC = total_distributions_received / total_equity_injected

    Parameters
    ----------
    inputs : SponsorMoicRunnerInputs
        Bundled inputs including the sponsor result.

    Returns
    -------
    SponsorMoicResult
        Immutable MOIC result.
    """
    result = inputs.sponsor_result

    total_injected = result.total_equity_injected_keur
    total_distributions = result.total_distributions_received_keur

    gross_moic: float | None = None
    notes_parts: list[str] = []

    if total_injected > 0:
        gross_moic = total_distributions / total_injected
        notes_parts.append(
            f"gross MOIC = {gross_moic:.4f}x "
            f"(distributions={total_distributions:.2f} kEUR / injections={total_injected:.2f} kEUR)"
        )
    else:
        notes_parts.append(
            "MOIC not meaningful: no equity injections in sponsor result"
        )

    metadata = (
        ("investor_id", result.investor_id),
        ("entity_code", result.entity_code),
        ("total_equity_injected_keur", total_injected),
        ("total_distributions_received_keur", total_distributions),
        ("total_wht_keur", result.total_wht_keur),
        ("run_type", "sponsor_moic"),
        ("phase", "7B"),
        *inputs.metadata,
    )

    return SponsorMoicResult(
        investor_id=result.investor_id,
        gross_sponsor_moic=gross_moic,
        total_equity_injected_keur=total_injected,
        total_distributions_received_keur=total_distributions,
        net_multiple_placeholder=None,
        metadata=metadata,
        notes=tuple(notes_parts) if notes_parts else ("sponsor MOIC result",),
    )


# ── Date helpers ─────────────────────────────────────────────────────────────

def _add_months(base: date, months: int) -> date:
    """Add months to a date (approximate, using 30-day months).

    Excel XIRR uses 365-day years, so we use 30-day months for simplicity.
    For more precise date arithmetic, use dateutil.relativedelta.
    """
    total_days = months * 30
    return base + timedelta(days=total_days)