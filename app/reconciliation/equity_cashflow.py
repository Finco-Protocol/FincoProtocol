"""Equity cashflow bridge helper."""
from typing import Any


def build_equity_cf_rows(result: Any) -> list[dict]:
    """Build equity cashflow bridge rows from a DemoResult or WaterfallResult.

    Returns list of dicts with columns:
        period, date, equity_investment, shl_interest, shl_principal,
        distributions, dsra_movement, equity_cash_flow

    Sign convention: INVESTOR PERSPECTIVE (consistent with Equity IRR XIRR)
    ─────────────────────────────────────────────────────────────────────
    - equity_investment: NEGATIVE during construction (cash out for investor)
    - shl_interest: POSITIVE (SHL is sub-debt, investor receives it as cash inflow)
    - shl_principal: POSITIVE (PIK capitalization returned at maturity)
    - distributions: POSITIVE (dividends/distributions to investor)
    - dsra_movement: NEGATIVE (DSRA contribution is cash locked up, not returned yet)
    
    equity_cash_flow = equity_investment + shl_interest + shl_principal
                      + distributions + dsra_movement
    
    This sign convention means:
    - Negative during construction (equity out)
    - Positive during operation (cash back to investor)
    Sum of all equity_cash_flows ≈ 0 at full repayment (NPV of equity = 0)
    
    Works with DemoResult (result.waterfall_result IS the WaterfallResult)
    and raw WaterfallResult.
    """
    wf = None
    if hasattr(result, "result") and hasattr(result, "waterfall_result"):
        wf = result.waterfall_result
    elif hasattr(result, "periods"):
        wf = result

    if wf is None:
        return []

    periods = wf.periods if hasattr(wf, "periods") else []
    if not periods:
        return []

    rows = []

    for p in periods:
        is_constr = not p.is_operation

        if is_constr:
            # Construction: equity invested (negative = cash out)
            # cf_after_tax is negative when equity is deployed
            eq_invest = p.cf_after_tax_keur  # already negative during construction
            shl_int = 0.0
            shl_principal = 0.0
            dist = 0.0
            dsra_mov = 0.0
            equity_cf = eq_invest
        else:
            # Operation: investor receives cash flows
            eq_invest = 0.0
            shl_int = p.shl_interest_keur        # positive: investor receives SHL interest
            shl_principal = p.shl_principal_keur  # positive: investor receives SHL principal
            dist = p.distribution_keur           # positive: investor receives distributions
            dsra_mov = -p.dsra_contribution_keur  # negative: DSRA contribution locks up cash
            equity_cf = shl_int + shl_principal + dist + dsra_mov

        rows.append({
            "period": p.period,
            "date": p.date,
            "equity_investment": round(eq_invest, 1),
            "shl_interest": round(shl_int, 1),
            "shl_principal": round(shl_principal, 1),
            "distributions": round(dist, 1),
            "dsra_movement": round(dsra_mov, 1),
            "equity_cash_flow": round(equity_cf, 1),
        })

    return rows