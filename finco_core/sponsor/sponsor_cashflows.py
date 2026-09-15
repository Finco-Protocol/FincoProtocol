"""Sponsor cash-flow construction for return metric computation.

Defines how sponsor/equity cash flows are built from waterfall period data.

Sponsor IRR includes SHL cash flows:
  t0: -(share_capital + SHL_amount + SHL_IDC)
  t>0: distributions + SHL_cash_interest_paid + SHL_principal_paid

SHL rules:
  - Paid SHL interest (shi) → sponsor cash inflow when actually paid
  - Paid SHL principal (shp) → sponsor cash inflow when actually paid
  - PIK/accrued interest → NOT sponsor cash until actually paid
  - Withholding tax uses cash amount sponsor receives (net of WHT)

Equity IRR methods:
  - "equity_only": equity CF = distributions only (no SHL flows)
  - "shl_interest_only": equity CF = SHL interest + SHL principal at maturity (bullet SHL)
  - "shl_plus_dividends": equity CF = SHL net interest while SHL outstanding,
                          distributions after SHL fully repaid
"""
from typing import Optional


def build_sponsor_cashflows(
    equity_irr_method: str,
    share_capital_keur: float,
    shl_amount_keur: float,
    shl_idc_keur: float,
    shl_balance_by_period: list[float],
    equity_cf_per_period: list[float],
    shl_interest_paid_per_period: list[float],
    shl_principal_paid_per_period: list[float],
) -> list[float]:
    """Build sponsor cash-flow list from per-period waterfall data.

    Args:
        equity_irr_method: "equity_only" | "shl_interest_only" | "shl_plus_dividends"
        share_capital_keur: Share capital + share premium invested by equity sponsor
        shl_amount_keur: SHL principal amount invested by sponsor
        shl_idc_keur: SHL IDC invested by sponsor
        shl_balance_by_period: SHL balance at end of each operating period
        equity_cf_per_period: Equity/distribution cash flow per period (from waterfall)
        shl_interest_paid_per_period: SHL cash interest paid per period (shi)
        shl_principal_paid_per_period: SHL principal repaid per period (shp)

    Returns:
        sponsor_cfs: list with t0 = -(share_capital + shl + shl_idc),
        then per-period sponsor cash flow.
    """
    # t0: total sponsor investment
    t0 = -(share_capital_keur + shl_amount_keur + shl_idc_keur)

    cfs = [t0]
    for i in range(len(equity_cf_per_period)):
        equity_cf = equity_cf_per_period[i]
        shi = shl_interest_paid_per_period[i]
        shp = shl_principal_paid_per_period[i]
        # For SHL-specific methods, equity_cf is already the selected sponsor
        # stream assembled upstream. Adding shi/shp here would double-count SHL
        # cash flows and inflate sponsor/equity IRR.
        if equity_irr_method in {"shl_interest_only", "shl_plus_dividends"}:
            sponsor_cf = equity_cf
        else:
            # Preserve existing semantics for methods whose equity stream is
            # distribution-only and therefore excludes paid SHL cash flows.
            sponsor_cf = equity_cf + shi + shp
        cfs.append(sponsor_cf)

    return cfs


def build_equity_cashflows(
    equity_irr_method: str,
    share_capital_keur: float,
    shl_amount_keur: float,
    equity_cf_per_period: list[float],
    shl_balance_by_period: list[float],
    shl_interest_paid_per_period: list[float],
    shl_principal_paid_per_period: list[float],
) -> list[float]:
    """Build equity cash-flow list for equity IRR calculation.

    Args:
        equity_irr_method: "equity_only" | "shl_interest_only" | "shl_plus_dividends"
        share_capital_keur: Share capital + share premium
        shl_amount_keur: SHL principal (only used for "shl_interest_only")
        equity_cf_per_period: Distribution cash flow per period
        shl_balance_by_period: SHL balance after each period
        shl_interest_paid_per_period: SHL cash interest paid
        shl_principal_paid_per_period: SHL principal repaid

    Returns:
        equity_cfs: list starting with -share_capital, then per-period equity CFs
    """
    t0 = -share_capital_keur
    cfs = [t0]

    for i in range(len(equity_cf_per_period)):
        dist = equity_cf_per_period[i]
        shl_bal = shl_balance_by_period[i]
        shi = shl_interest_paid_per_period[i]
        shp = shl_principal_paid_per_period[i]

        if equity_irr_method == "shl_interest_only":
            # Bullet SHL: equity CF = SHL interest + principal at maturity
            cf = shi + shp
        elif equity_irr_method == "shl_plus_dividends":
            if shl_bal > 0:
                # SHL outstanding: equity CF = net interest (no principal in equity CF)
                cf = shi
            else:
                # SHL repaid: equity CF = distributions (dividends)
                cf = dist
        else:
            # "equity_only" / "combined": equity CF = distributions only
            cf = dist

        cfs.append(cf)

    return cfs
