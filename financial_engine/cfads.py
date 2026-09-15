"""financial_engine.cfads — Canonical CFADS calculation.

Phase 2B definition::

    CFADS = EBITDA + financing_income - cash_tax_paid

This is the pre-debt-service, pre-DSRA CFADS.  Debt service, DSRA movements,
and distributions are out of Phase 2B scope.

Pure function.  No imports from app, finco_core or any framework.

``calculate_canonical_cfads`` is the **single authoritative location** for the
CFADS formula.  ``run_tax_cfads_model`` must call this function and must not
re-derive CFADS inline.

Safeguards
----------
* Period count must match between ``periods`` and ``period_results``.
* Period indices must match (same set, same order).
* No duplicate period indices allowed in either sequence.
* Exactly one result per model period.
"""
from __future__ import annotations

from dataclasses import dataclass

from financial_engine.tax.models import PeriodCashTaxResult


@dataclass(frozen=True)
class PeriodCfadsResult:
    """Canonical CFADS for one model period."""
    period_index: int
    ebitda_keur: float
    cash_tax_keur: float
    cfads_keur: float
    financing_income_keur: float = 0.0


def calculate_canonical_cfads(
    periods: tuple,                      # tuple[OperatingPeriodResult]
    period_results: tuple[PeriodCashTaxResult, ...],
) -> tuple[PeriodCfadsResult, ...]:
    """Calculate CFADS = EBITDA − cash_tax_paid for every model period.

    Parameters
    ----------
    periods:
        OperatingPeriodResult tuple from the Phase 2A orchestrator.
    period_results:
        PeriodCashTaxResult tuple from ``calculate_tax()``.

    Returns
    -------
    ``tuple[PeriodCfadsResult]`` — one entry per model period.

    Raises
    ------
    ValueError
        If period counts differ, indices differ, or duplicates are found.
    """
    if len(periods) != len(period_results):
        raise ValueError(
            f"calculate_canonical_cfads: period count mismatch — "
            f"{len(periods)} operating periods vs {len(period_results)} tax results"
        )

    p_indices = [p.period_index for p in periods]  # type: ignore[attr-defined]
    t_indices = [pr.period_index for pr in period_results]

    if len(set(p_indices)) != len(p_indices):
        raise ValueError("calculate_canonical_cfads: duplicate period indices in periods")
    if len(set(t_indices)) != len(t_indices):
        raise ValueError("calculate_canonical_cfads: duplicate period indices in period_results")
    if p_indices != t_indices:
        raise ValueError(
            f"calculate_canonical_cfads: period index mismatch — "
            f"periods={p_indices[:5]}… tax={t_indices[:5]}…"
        )

    results: list[PeriodCfadsResult] = []
    for p, pr in zip(periods, period_results):
        ebitda: float = p.ebitda_keur    # type: ignore[attr-defined]
        cash_tax: float = pr.cash_tax_keur
        fin_income: float = getattr(pr, "financing_income_keur", 0.0)
        results.append(PeriodCfadsResult(
            period_index=p.period_index,  # type: ignore[attr-defined]
            ebitda_keur=ebitda,
            cash_tax_keur=cash_tax,
            financing_income_keur=fin_income,
            cfads_keur=ebitda + fin_income - cash_tax,
        ))
    return tuple(results)
