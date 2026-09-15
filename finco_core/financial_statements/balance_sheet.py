"""Balance sheet aggregation from WaterfallPeriod outputs."""
from finco_core.financial_statements.statement_models import BalanceSheetPeriod
from finco_core.financial_statements.income_statement import generate_income_statement


def generate_balance_sheet(
    periods,
    total_capex_keur: float,
    share_capital_keur: float,
    share_premium_keur: float,
) -> list[BalanceSheetPeriod]:
    """Aggregate balance sheet from WaterfallPeriod list.

    Three model-convention adjustments restore A = L + E:

    1. opening_deficit — solved directly from period-0 data so the corrected
       BS closes exactly at p0.  For projects where DSRA / MRA / initial cash
       are pre-funded at COD (Generic Solar Reference), the old total_capex-minus-debt formula
       understated the opening equity deficit; the new formula captures all
       initial assets on both sides.

    2. tax_payable_keur — cumulative accrued tax not captured as a cash
       outflow in cf_after_tax.  Uses the same timing expression as the CFS
       indirect-method tax_payable_adj: tax_keur - (ebitda - cf_after_tax).
       For projects where H2 cash tax IS deducted from cf_after_tax (Generic Solar Reference)
       this oscillates and returns to 0 each year; for Generic Wind Reference it accumulates.
       Added to total_liabilities.

    3. shl_principal_notional — cumulative shl_principal_keur, which reduces
       shl_balance (L) without a corresponding cash outflow (model convention
       documented in cash_flow.py).  The retained cash represents equity value
       created by the notional debt reduction; added to retained_earnings.
    """
    is_periods = generate_income_statement(periods)

    # Opening deficit: derive the accumulated COD deficit that makes the
    # fully-corrected BS close at period 0.
    # Formula: opening_deficit = A_p0 - L_p0_corrected - SC - SP - NI_p0 + dist_p0 - shl_p_p0
    # For Generic Wind Reference this gives the same value as the old capex-minus-debt formula.
    if periods:
        p0 = periods[0]
        isp0 = is_periods[0]
        _tax_adj_p0 = p0.tax_keur - (p0.ebitda_keur - p0.cf_after_tax_keur)
        _nfa_p0 = total_capex_keur - p0.depreciation_keur
        _a_p0 = _nfa_p0 + p0.dsra_balance_keur + p0.mra_balance_keur + p0.cash_balance_keur
        _l_p0 = p0.senior_balance_keur + p0.shl_balance_keur + _tax_adj_p0
        opening_deficit = (
            _a_p0 - _l_p0 - share_capital_keur - share_premium_keur
            - isp0.net_income_keur + p0.distribution_keur - p0.shl_principal_keur
        )
    else:
        opening_deficit = 0.0

    result = []
    cum_depreciation = 0.0
    cum_distribution = 0.0
    cum_net_income = opening_deficit
    cum_tax_payable = 0.0
    cum_shl_principal = 0.0

    for p, isp in zip(periods, is_periods):
        cum_depreciation += p.depreciation_keur
        cum_net_income += isp.net_income_keur
        cum_distribution += p.distribution_keur
        cum_tax_payable += p.tax_keur - (p.ebitda_keur - p.cf_after_tax_keur)
        cum_shl_principal += p.shl_principal_keur

        nfa = total_capex_keur - cum_depreciation
        dsra = p.dsra_balance_keur
        mra = p.mra_balance_keur
        cash = p.cash_balance_keur
        total_assets = nfa + dsra + mra + cash

        senior = p.senior_balance_keur
        shl = p.shl_balance_keur
        tax_payable = cum_tax_payable
        total_liabilities = senior + shl + tax_payable

        retained = (cum_net_income - cum_distribution) + cum_shl_principal
        total_equity = share_capital_keur + share_premium_keur + retained

        check = total_assets - total_liabilities - total_equity

        result.append(BalanceSheetPeriod(
            period=p.period,
            date=p.date,
            net_fixed_assets_keur=nfa,
            dsra_balance_keur=dsra,
            mra_balance_keur=mra,
            cash_balance_keur=cash,
            total_assets_keur=total_assets,
            senior_balance_keur=senior,
            shl_balance_keur=shl,
            tax_payable_keur=tax_payable,
            total_liabilities_keur=total_liabilities,
            share_capital_keur=share_capital_keur,
            share_premium_keur=share_premium_keur,
            retained_earnings_keur=retained,
            total_equity_keur=total_equity,
            check_keur=check,
        ))

    return result
