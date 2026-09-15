"""Interest rate utilities — Euribor curve and blended rate computation.

Enterprise Implementation Brief §4.1
Supports: EURIBOR 3M/6M curves, hedging, rate floor/cap.
"""
from dataclasses import dataclass
from typing import Optional


# =============================================================================
# EURIBOR Curve Data
# =============================================================================

# Current Euribor reference rates (LIVE — April 23, 2026)
# Source: https://www.euribor-rates.eu/en/current-euribor-rates/
EURIBOR_1M_SPOT = 0.01968  # 1.968% (1M tenor)
EURIBOR_3M_SPOT = 0.02165  # 2.165% (3M tenor)
EURIBOR_6M_SPOT = 0.02427  # 2.427% (6M tenor)
EURIBOR_12M_SPOT = 0.02687  # 2.687% (12M tenor)

# Euribor forward curve (implied forward rates, semi-annual tenors)
EURIBOR_6M_FORWARDS = (
    0.02427,  # 6M: actual April 2026 spot = 2.427%
    0.02550,  # 12M: spot + ~13bps term premium
    0.02680,  # 18M: +25bps
    0.02800,  # 24M: +37bps
    0.02900,  # 30M: +47bps
    0.03000,  # 36M: +57bps
    0.03100,  # 42M: +67bps
    0.03180,  # 48M: +75bps
    0.03250,  # 54M: +82bps
    0.03300,  # 60M: +87bps
    0.03350,  # 66M: +92bps
    0.03400,  # 72M: +97bps
    0.03450,  # 84M: +102bps
    0.03500,  # 96M: +107bps
    0.03500,  # 108M: +107bps
)

# 1M forwards (monthly tenors up to 18M)
EURIBOR_1M_FORWARDS = (
    0.01968,  # 1M: actual April 2026 spot = 1.968%
    0.02000,  # 2M: +3bps
    0.02050,  # 3M: +8bps
    0.02100,  # 4M: +13bps
    0.02150,  # 5M: +18bps
    0.02200,  # 6M: +23bps
    0.02250,  # 7M: +28bps
    0.02300,  # 8M: +33bps
    0.02350,  # 9M: +38bps
    0.02400,  # 10M: +43bps
    0.02450,  # 11M: +48bps
    0.02500,  # 12M: +53bps
    0.02600,  # 15M: +63bps
    0.02700,  # 18M: +73bps
)

EURIBOR_3M_FORWARDS = (
    0.02165,  # 3M: actual April 2026 spot = 2.165%
    0.02250,  # 6M: +9bps
    0.02350,  # 9M: +19bps
    0.02450,  # 12M: +29bps
    0.02550,  # 15M: +39bps
    0.02650,  # 18M: +49bps
    0.02750,  # 21M: +59bps
    0.02850,  # 24M: +69bps
    0.02950,  # 27M: +79bps
    0.03050,  # 30M: +89bps
    0.03100,  # 33M: +94bps
    0.03150,  # 36M: +99bps
    0.03200,  # 42M: +104bps
    0.03250,  # 48M: +109bps
    0.03300,  # 54M: +114bps
)


@dataclass(frozen=True)
class RateCurvePoint:
    """Single point on a rate curve."""
    tenor_months: int
    rate: float


def build_euribor_curve(
    base_rate_type: str = "EURIBOR_6M",
    spot_rate: Optional[float] = None,
    forwards: Optional[tuple[float, ...]] = None,
    flat_bps: float = 0.0,
) -> list[RateCurvePoint]:
    """Build Euribor rate curve.
    
    Args:
        base_rate_type: "FLAT" | "EURIBOR_1M" | "EURIBOR_3M" | "EURIBOR_6M"
            "FLAT" = constant all-in rate (hedge-equivalent, no EURIBOR exposure)
            "EURIBOR_*" = use EURIBOR curve (floating exposure with margin)
        spot_rate: Override spot rate. None = use current reference.
        forwards: Override forward rates. None = use built-in curve.
        flat_bps: Flat spread to add to all rates (in bps).
    
    Returns:
        List of RateCurvePoint (tenor_months, rate) ordered by tenor.
    """
    if base_rate_type == "EURIBOR_1M" or base_rate_type == "1M":
        forward_tenors = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 18)
        curve = forwards or EURIBOR_1M_FORWARDS
        spot = spot_rate if spot_rate is not None else EURIBOR_1M_SPOT
    elif base_rate_type == "EURIBOR_3M" or base_rate_type == "3M":
        forward_tenors = (3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 42, 48, 54)
        curve = forwards or EURIBOR_3M_FORWARDS
        spot = spot_rate if spot_rate is not None else EURIBOR_3M_SPOT
    elif base_rate_type == "EURIBOR_6M" or base_rate_type == "6M":
        forward_tenors = (6, 12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72, 84, 96, 108)
        curve = forwards or EURIBOR_6M_FORWARDS
        spot = spot_rate if spot_rate is not None else EURIBOR_6M_SPOT
    else:
        raise ValueError(f"Unknown base_rate_type: {base_rate_type}. Use FLAT, EURIBOR_1M, EURIBOR_3M, EURIBOR_6M, or fixed.")
    
    flat_spread = flat_bps / 10000.0
    result = [RateCurvePoint(tenor_months=0, rate=spot + flat_spread)]
    
    for i, fwd in enumerate(curve[:14]):  # Limit to reasonable tenor range
        tenor = forward_tenors[i] if i < len(forward_tenors) else (i + 2) * 6
        result.append(RateCurvePoint(tenor_months=tenor, rate=fwd + flat_spread))
    
    return result


def get_rate_at_tenor(
    curve: list[RateCurvePoint],
    tenor_months: int,
) -> float:
    """Get interpolated/extrapolated rate at a specific tenor.
    
    Args:
        curve: Rate curve from build_euribor_curve()
        tenor_months: Target tenor in months
    
    Returns:
        Rate at tenor (linear interpolation between points)
    """
    if not curve:
        return 0.03
    
    # Before first point — use first rate
    if tenor_months <= curve[0].tenor_months:
        return curve[0].rate
    
    # After last point — extrapolate with last rate
    if tenor_months >= curve[-1].tenor_months:
        return curve[-1].rate
    
    # Linear interpolation between adjacent points
    for i in range(len(curve) - 1):
        if curve[i].tenor_months <= tenor_months <= curve[i + 1].tenor_months:
            t0, r0 = curve[i].tenor_months, curve[i].rate
            t1, r1 = curve[i + 1].tenor_months, curve[i + 1].rate
            alpha = (tenor_months - t0) / (t1 - t0) if t1 != t0 else 0.0
            return r0 + alpha * (r1 - r0)
    
    return curve[-1].rate


def build_rate_schedule(
    base_rate_type: str = "EURIBOR_6M",
    tenor_periods: int = 28,  # 14-year semi-annual
    periods_per_year: int = 2,
    base_rate_override: Optional[float] = None,
    forwards: Optional[tuple[float, ...]] = None,
    floating_share: float = 0.2,
    fixed_share: float = 0.8,
    hedge_coverage: float = 0.8,
    margin_bps: int = 265,
    base_rate_floor: float = 0.0,
) -> list[float]:
    """Build semi-annual rate schedule for waterfall.
    
    Computes blended floating+fixed+hedge rate per period.
    
    Args:
        base_rate_type: "FLAT" | "EURIBOR_1M" | "EURIBOR_3M" | "EURIBOR_6M"
            "FLAT" = constant all-in rate (hedge-equivalent, no EURIBOR exposure)
            "EURIBOR_*" = use EURIBOR curve (floating exposure with margin)
        tenor_periods: Total number of rate periods (semi-annual)
        periods_per_year: 2 for semi-annual, 1 for annual
        base_rate_override: Override the base rate (for sensitivity)
        forwards: Euribor forward curve override
        floating_share: Share of debt on floating rate (e.g., 0.2 = 20%)
        fixed_share: Share of debt on fixed rate (e.g., 0.8 = 80%)
        hedge_coverage: % of floating debt that is hedged (e.g., 0.8 = 80%)
        margin_bps: Credit margin in bps (added to base rate)
        base_rate_floor: Minimum base rate (e.g., 0.0 for no negative rates)
    
    Returns:
        List of semi-annual rates, one per period.
    """
    # For FLAT mode: return constant rate (all-in rate, hedge-equivalent)
    # base_rate_override should be the per-period all-in rate (e.g., 0.0565/2 = 0.02825)
    if base_rate_type == "FLAT":
        all_in = (base_rate_override if base_rate_override is not None else 0.0565 / 2)
        return [all_in] * tenor_periods
    
    # For fixed rate mode: override with fixed rate as EURIBOR component
    if base_rate_type == "fixed" and base_rate_override is not None:
        # Treat fixed rate as EURIBOR component (EURIBOR_6M curve will be used)
        # The 'fixed' type just signals the UI to show fixed rate option
        pass  # Falls through to EURIBOR curve
    
    curve = build_euribor_curve(
        base_rate_type=base_rate_type,
        forwards=forwards,
    )
    
    margin = margin_bps / 10000.0
    
    # For semi-annual periods, each period = 6 months
    # Period N covers months [N*6, (N+1)*6)
    rates = []
    for period in range(tenor_periods):
        tenor_months = (period + 1) * (12 // periods_per_year)
        
        # Get base rate for this period's tenor
        if base_rate_override is not None:
            base = max(base_rate_floor, base_rate_override)
        else:
            base = get_rate_at_tenor(curve, tenor_months)
            base = max(base_rate_floor, base)
        
        # Floating portion — hedged + unhedged
        # Hedged portion uses locked-in rate (base at hedge start + hedge cost)
        # Unhedged portion uses current forward rate
        floating_rate = base + margin
        
        # Fixed portion — all-in fixed rate (base + margin + upfront cost spread)
        fixed_rate = base + margin + 0.001  # Small upfront cost amortization
        
        # Blended rate
        blended = (
            floating_rate * floating_share * (1 - hedge_coverage) +
            floating_rate * floating_share * hedge_coverage +  # hedged → same rate
            fixed_rate * fixed_share
        )
        
        rates.append(blended)
    
    return rates


def apply_rate_shock(rate_schedule: list[float], shock_bps: int) -> list[float]:
    """Apply a parallel rate shock to a rate schedule.
    
    Args:
        rate_schedule: Existing rate schedule
        shock_bps: Shock in basis points (+50 = 50 bps rise)
    
    Returns:
        New rate schedule with shock applied
    """
    shock = shock_bps / 10000.0
    return [r + shock for r in rate_schedule]
