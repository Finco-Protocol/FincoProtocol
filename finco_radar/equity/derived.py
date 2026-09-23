"""Canonical derived metrics for the equity fundamentals authority layer.

UNIT CONTRACT (from the normalization pipeline that writes equity_fundamentals.db;
  verified against DB sample 2026-09-23 — sample confirms contract, does not
  define it universally):

  revenues, free_cash_flow, net_debt
    - raw base-currency absolute values (e.g. not thousands/millions)
    - normalization contract: absolute base-currency unit
    - sample: AAPL TTM 2026-06-27 = 466,823,000,000

  margin/return fields (gross_margin, ebit_margin, ebitda_margin,
                        net_margin, fcf_margin, return_on_equity)
    - source fractions: 0.4865 == 48.65%
    - sample: AAPL gross_margin TTM = 0.4865291…

  revenue_growth (DerivedFundamentals.revenue_growth)
    - NULL in the source DB for LEGACY_MASSIVE_VX / current MASSIVE snapshots
      (confirmed 2026-09-23); must be derived — see below.
    - Other future providers may populate it directly; derivation here is
      scoped to the quarterly-history fallback path only.

REVENUE GROWTH DERIVATION:
  Canonical definition: TTM revenue / prior-comparable TTM revenue - 1

  Algorithm (fail-closed — returns None on any validation failure):
    1. Require 8 or more snapshots; use first 8 only.
    2. All 8 must have timeframe == "quarterly".
    3. All 8 must share the same ticker.
    4. All 8 must have period_end; period_ends must be strictly descending.
    5. Adjacent quarter pairs must be plausibly consecutive: 60–120 days.
    6. Each current[i] vs prior[i] gap must be in [330, 400] days (all 4 pairs).
    7. When fiscal_quarter is present on both sides of a pair, they must match.
    8. All 8 revenue values must be non-None (MISSING != ZERO invariant).
    9. prior TTM sum must be positive (no division by zero or negative base).

  Returns None on any failure — never fabricates or approximates.
  No interpolation; no cross-currency comparison; no mismatched fiscal basis.

AUTHORITY BOUNDARY:
  This module performs deterministic arithmetic on proven source data only.
  No market prices, no Robinhood API calls, no network I/O.
  Do NOT derive financial metrics inside Jinja templates or JavaScript.

PERFORMANCE NOTE:
  The quarterly_history sequence is fetched within the same SQLite read
  session as the rest of the bundle — same DB snapshot, no network fanout.
  This is not a bulk batch query but is not a network N+1 either.
"""
from __future__ import annotations

from datetime import date
from typing import Optional, Sequence


def compute_ttm_revenue_growth(
    quarterly_history: Sequence,
) -> Optional[float]:
    """YoY TTM revenue growth from 8 comparable quarterly snapshots.

    quarterly_history must be sorted period_end DESC (latest first),
    as returned by EquityFundamentalsRepository.get_financial_history.

    Returns a fraction: 0.145 == +14.5%.  Returns None when any
    comparability check fails (see module docstring for the full list).

    MISSING != ZERO: a None revenue fails the whole computation.
    A 0.0 revenue propagates into the sum (genuine zero is not missing).
    """
    if len(quarterly_history) < 8:
        return None

    current_quarters = quarterly_history[:4]
    prior_quarters = quarterly_history[4:8]
    all_eight = list(current_quarters) + list(prior_quarters)

    # All 8 must be quarterly snapshots
    for snap in all_eight:
        if getattr(snap, "timeframe", None) != "quarterly":
            return None

    # All 8 must share the same ticker
    tickers = {getattr(snap, "ticker", None) for snap in all_eight}
    if len(tickers) != 1 or next(iter(tickers)) is None:
        return None

    # Parse and validate period_ends: all present, strictly descending
    try:
        dates = []
        for snap in all_eight:
            pe = getattr(snap, "period_end", None)
            if not pe:
                return None
            dates.append(date.fromisoformat(pe[:10]))
    except (TypeError, ValueError):
        return None

    for i in range(len(dates) - 1):
        if dates[i] <= dates[i + 1]:
            return None

    # Adjacent quarterly continuity: each pair should be 60–120 days apart
    for i in range(len(dates) - 1):
        gap = (dates[i] - dates[i + 1]).days
        if not (60 <= gap <= 120):
            return None

    # Pairwise year-over-year gap: all 4 pairs must be in [330, 400] days
    for i in range(4):
        gap = (dates[i] - dates[4 + i]).days
        if not (330 <= gap <= 400):
            return None

    # Fiscal quarter pairwise match when metadata is present on both sides
    for i in range(4):
        fq_curr = getattr(current_quarters[i], "fiscal_quarter", None)
        fq_prior = getattr(prior_quarters[i], "fiscal_quarter", None)
        if fq_curr and fq_prior and fq_curr != fq_prior:
            return None

    # Revenue extraction — all 8 must be non-None
    current_revenues: list[Optional[float]] = []
    prior_revenues: list[Optional[float]] = []

    for snap in current_quarters:
        rev = snap.derived.revenues if snap.derived is not None else None
        current_revenues.append(rev)

    for snap in prior_quarters:
        rev = snap.derived.revenues if snap.derived is not None else None
        prior_revenues.append(rev)

    if any(r is None for r in current_revenues + prior_revenues):
        return None

    current_sum: float = sum(current_revenues)  # type: ignore[arg-type]
    prior_sum: float = sum(prior_revenues)       # type: ignore[arg-type]

    if prior_sum <= 0:
        return None

    return (current_sum / prior_sum) - 1
