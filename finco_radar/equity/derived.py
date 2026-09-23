"""Canonical derived metrics for the equity fundamentals authority layer.

UNIT CONTRACT (proven from equity_fundamentals.db, 2026-09-23):
  revenues, free_cash_flow, net_debt
    - raw base-currency absolute values (e.g. USD, not thousands/millions)
    - 466_823_000_000 == USD 466.8 billion
    - confirmed: AAPL TTM 2026-06-27 = 466,823,000,000
                 AAPL annual 2025-09-27 = 416,161,000,000

  margin/return fields (gross_margin, ebit_margin, ebitda_margin,
                        net_margin, fcf_margin, return_on_equity)
    - source fractions: 0.4865 == 48.65%
    - confirmed: AAPL gross_margin TTM = 0.4865291… → 48.65%

  revenue_growth (DerivedFundamentals.revenue_growth)
    - UNIVERSALLY NULL in the current DB snapshot (confirmed 2026-09-23)
    - Must be derived from comparable quarterly snapshots — see below.

REVENUE GROWTH DERIVATION:
  Canonical definition: TTM revenue / prior-comparable TTM revenue - 1

  Algorithm (fail-closed):
    1. Require exactly 8 or more quarterly snapshots sorted period_end DESC.
    2. Split into current_4 = quarters[0:4] and prior_4 = quarters[4:8].
    3. Period-gap check: period_end(current_4[0]) - period_end(prior_4[0])
       must be in [330, 400] days to confirm quarterly comparability.
    4. All 8 revenues must be non-None (MISSING != ZERO invariant).
    5. prior_sum must be > 0 (no division by zero or negative base).
    6. Result: (current_sum / prior_sum) - 1   (fraction, not percent)

  Returns None on any failure — never fabricates or approximates.
  No interpolation; no cross-currency comparison; no mismatched fiscal basis.

AUTHORITY BOUNDARY:
  This module performs deterministic arithmetic on proven source data only.
  No market prices, no Robinhood API calls, no network I/O.
  Do NOT derive financial metrics inside Jinja templates or JavaScript.
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

    Returns a fraction: 0.145 == +14.5%.  Returns None when:
    - fewer than 8 snapshots
    - period gap between the two 4-quarter groups is outside [330, 400] days
    - any revenue value in either group is None
    - prior_sum is zero or negative (comparison not valid)

    MISSING != ZERO: a None revenue fails the whole computation.
    A 0.0 revenue propagates into the sum (genuine zero is not missing).
    """
    if len(quarterly_history) < 8:
        return None

    current_quarters = quarterly_history[:4]
    prior_quarters = quarterly_history[4:8]

    # Period-gap check: confirm the two groups are ~1 year apart
    try:
        current_end_str = current_quarters[0].period_end
        prior_end_str = prior_quarters[0].period_end
        if not current_end_str or not prior_end_str:
            return None
        current_end = date.fromisoformat(current_end_str[:10])
        prior_end = date.fromisoformat(prior_end_str[:10])
        gap_days = (current_end - prior_end).days
        if not (330 <= gap_days <= 400):
            return None
    except (TypeError, ValueError, AttributeError):
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
