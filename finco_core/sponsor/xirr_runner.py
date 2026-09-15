"""Phase 7B — Deterministic XIRR helper for sponsor-level IRR computation.

Wraps the core XIRR solver and tracks convergence metadata.
No scipy dependency. Deterministic. No hidden state.

reference-compatible: 365-day year fraction, requires sign change in cashflows.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from finco_core.sponsor.xirr import xirr as _core_xirr
from finco_core.sponsor.xirr import xirr_bisection as _core_bisection

__all__ = ["SponsorXirrResult", "xirr_with_convergence"]


@dataclass(frozen=True)
class SponsorXirrResult:
    """XIRR result with convergence metadata.

    Attributes
    ----------
    rate : float | None
        XIRR rate (decimal, e.g. 0.12 for 12.0%), or None if no solution.
    converged : bool
        True if solver converged within tolerance.
    iterations : int
        Number of iterations used. 0 if not attempted.
    tolerance : float
        Convergence tolerance used (relative rate change).
    method : str
        Solver used: "newton_raphson" or "bisection".
    """
    rate: float | None
    converged: bool = False
    iterations: int = 0
    tolerance: float = 1e-7
    method: str = "newton_raphson"

    @property
    def rate_percent(self) -> float | None:
        """Rate expressed as percentage."""
        if self.rate is None:
            return None
        return self.rate * 100.0


def xirr_with_convergence(
    cash_flows: Sequence[float],
    dates: Sequence[date],
    guess: float = 0.10,
    tolerance: float = 1e-7,
    max_iterations: int = 200,
) -> SponsorXirrResult:
    """Compute XIRR with convergence metadata.

    Wraps the Newton-Raphson XIRR from finco_core.sponsor.xirr with iteration
    tracking. Falls back to bisection if Newton-Raphson fails to converge.

    Parameters
    ----------
    cash_flows : Sequence[float]
        Ordered cash flows (negative = contribution, positive = distribution).
        Must contain at least one positive and one negative value.
    dates : Sequence[date]
        Corresponding dates in ascending order.
    guess : float
        Initial rate guess (default 0.10 = 10%).
    tolerance : float
        Convergence tolerance on relative rate change (default 1e-7).
    max_iterations : int
        Maximum iterations before declaring non-convergence (default 200).

    Returns
    -------
    SponsorXirrResult
        rate (or None), converged flag, iteration count, tolerance, method.

    Notes
    -----
    - Uses reference-compatible 365-day year fractions.
    - Returns None rate if no sign change in cashflows.
    - Deterministic: same inputs always produce identical results.
    """
    # Quick validation
    if not cash_flows or len(cash_flows) < 2:
        return SponsorXirrResult(rate=None, converged=False, iterations=0,
                                  tolerance=tolerance, method="newton_raphson")
    if len(cash_flows) != len(dates):
        raise ValueError("cash_flows and dates must have the same length")

    has_positive = any(cf > 0 for cf in cash_flows)
    has_negative = any(cf < 0 for cf in cash_flows)
    if not (has_positive and has_negative):
        return SponsorXirrResult(rate=None, converged=False, iterations=0,
                                  tolerance=tolerance, method="newton_raphson")

    # Try Newton-Raphson with iteration tracking
    rate, iterations = _xirr_newton_tracked(
        list(cash_flows), list(dates), guess=guess,
        tolerance=tolerance, max_iterations=max_iterations,
    )

    if rate is not None:
        return SponsorXirrResult(
            rate=rate, converged=True, iterations=iterations,
            tolerance=tolerance, method="newton_raphson",
        )

    # Fallback to bisection (more robust, slower)
    rate = _core_bisection(
        list(cash_flows), list(dates),
        tolerance=tolerance, max_iterations=max_iterations * 5,
    )

    if rate is not None:
        return SponsorXirrResult(
            rate=rate, converged=True, iterations=0,  # bisection doesn't track iterations
            tolerance=tolerance, method="bisection",
        )

    return SponsorXirrResult(
        rate=None, converged=False, iterations=0,
        tolerance=tolerance, method="bisection",
    )


def _xirr_newton_tracked(
    cash_flows: list[float],
    dates: list[date],
    guess: float,
    tolerance: float,
    max_iterations: int,
) -> tuple[float | None, int]:
    """Newton-Raphson XIRR with iteration counting.

    Returns (rate, iterations) where iterations is the count of iterations
    performed. rate is None if convergence failed.
    """
    d0 = dates[0]
    year_fractions = [(d - d0).days / 365.0 for d in dates]

    rate = guess

    for iteration in range(1, max_iterations + 1):
        npv = sum(
            cf / (1 + rate) ** t
            for cf, t in zip(cash_flows, year_fractions)
        )
        d_npv = sum(
            -t * cf / (1 + rate) ** (t + 1)
            for cf, t in zip(cash_flows, year_fractions)
        )

        if abs(d_npv) < 1e-15:
            return None, iteration

        new_rate = rate - npv / d_npv

        if abs(new_rate - rate) < tolerance:
            return new_rate, iteration

        if new_rate < -0.99 or new_rate > 100:
            return None, iteration

        rate = new_rate

    return None, max_iterations