"""Main entry point: generate all financial statements from waterfall output."""
from finco_core.financial_statements.statement_models import FinancialStatements
from finco_core.financial_statements.income_statement import generate_income_statement
from finco_core.financial_statements.balance_sheet import generate_balance_sheet
from finco_core.financial_statements.cash_flow import generate_cash_flow_statement


def generate_financial_statements(
    periods,
    total_capex_keur: float,
    share_capital_keur: float,
    share_premium_keur: float,
    capex_schedule_keur: list[float] | None = None,
) -> FinancialStatements:
    """Generate IS, BS, and CFS from a list of WaterfallPeriod objects.

    Args:
        periods: list of WaterfallPeriod (from WaterfallResult.periods)
        total_capex_keur: total project capex for NFA calculation
        share_capital_keur: equity share capital (opening, fixed)
        share_premium_keur: equity share premium (opening, fixed)
        capex_schedule_keur: optional per-period capex for cash flow investing section

    Returns:
        FinancialStatements with income_statement, balance_sheet, cash_flow lists.
    """
    return FinancialStatements(
        income_statement=generate_income_statement(periods),
        balance_sheet=generate_balance_sheet(
            periods,
            total_capex_keur=total_capex_keur,
            share_capital_keur=share_capital_keur,
            share_premium_keur=share_premium_keur,
        ),
        cash_flow=generate_cash_flow_statement(
            periods,
            capex_schedule_keur=capex_schedule_keur,
        ),
    )
