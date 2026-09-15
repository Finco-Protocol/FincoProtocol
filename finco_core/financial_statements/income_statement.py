"""Income statement aggregation from WaterfallPeriod outputs."""
from finco_core.financial_statements.statement_models import IncomeStatementPeriod


def generate_income_statement(periods) -> list[IncomeStatementPeriod]:
    """Aggregate income statement from WaterfallPeriod list.

    All values derived from existing canonical WaterfallPeriod fields — no new calculations.
    """
    result = []
    for p in periods:
        ebit = p.ebitda_keur - p.depreciation_keur
        # SHL interest in P&L = cash portion paid + PIK capitalized this period.
        # shl_gross_accrued_interest_keur is an H1 audit display (not yet booked to balance);
        # the actual booked entry uses shl_interest_keur (cash) + shl_pik_keur (capitalized),
        # which matches the actual SHL balance change in each period.
        shl_interest_accrual = p.shl_interest_keur + p.shl_pik_keur
        total_interest = p.interest_senior_keur + shl_interest_accrual
        ebt = ebit - total_interest
        net_income = ebt - p.tax_keur

        result.append(IncomeStatementPeriod(
            period=p.period,
            date=p.date,
            revenue_keur=p.revenue_keur,
            opex_keur=p.opex_keur,
            ebitda_keur=p.ebitda_keur,
            depreciation_keur=p.depreciation_keur,
            ebit_keur=ebit,
            interest_senior_keur=p.interest_senior_keur,
            interest_shl_keur=shl_interest_accrual,
            total_interest_keur=total_interest,
            ebt_keur=ebt,
            tax_keur=p.tax_keur,
            net_income_keur=net_income,
        ))
    return result
