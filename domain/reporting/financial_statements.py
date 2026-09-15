"""Financial Statements in bank format.

Three reports:
1. Income Statement (P&L)
2. Balance Sheet
3. Cash Flow Statement

Bank format means:
- Annual granularity (H1 + H2 aggregated)
- Explicitly separated financial and tax depreciation
- Retained earnings across entire horizon
- Debt schedule as separate table
- All in kEUR
"""
from dataclasses import dataclass
from typing import Sequence, Optional

from domain.period_engine import PeriodMeta


# =============================================================================
# 1. INCOME STATEMENT
# =============================================================================
@dataclass
class IncomeStatementRow:
    """Income statement row for one year."""
    year: int

    # Revenue
    ppa_revenue_keur: float
    market_revenue_keur: float
    co2_revenue_keur: float
    total_revenue_keur: float

    # Operating costs
    opex_keur: float
    ebitda_keur: float
    ebitda_margin_pct: float

    # D&A (financial, for P&L)
    depreciation_financial_keur: float
    ebit_keur: float

    # Financing costs
    interest_senior_keur: float
    interest_shl_keur: float
    total_interest_keur: float

    # Tax
    ebt_keur: float
    tax_depreciation_keur: float  # Tax depreciation (for tax shield)
    taxable_profit_keur: float
    income_tax_keur: float
    effective_tax_rate_pct: float

    # Bottom line
    net_income_keur: float


# =============================================================================
# 2. BALANCE SHEET
# =============================================================================
@dataclass
class BalanceSheetRow:
    """Balance sheet row for one year."""
    year: int

    # ASSETS
    # Non-current assets
    gross_fixed_assets_keur: float  # Initial CAPEX
    accumulated_depreciation_keur: float
    net_fixed_assets_keur: float  # Gross - Accumulated

    # Current assets
    dsra_balance_keur: float
    mra_balance_keur: float
    cash_and_equivalents_keur: float
    total_current_assets_keur: float

    total_assets_keur: float

    # LIABILITIES
    # Non-current liabilities
    senior_debt_keur: float
    shl_keur: float
    total_non_current_liabilities_keur: float

    # Current liabilities
    current_portion_senior_debt_keur: float
    income_tax_payable_keur: float
    total_current_liabilities_keur: float

    total_liabilities_keur: float

    # EQUITY
    share_capital_keur: float
    share_premium_keur: float
    retained_earnings_keur: float
    current_year_profit_keur: float
    total_equity_keur: float

    total_liabilities_and_equity_keur: float

    @property
    def is_balanced(self) -> bool:
        """Check if Assets = Liabilities + Equity."""
        return abs(self.total_assets_keur - self.total_liabilities_and_equity_keur) < 1.0


# =============================================================================
# 3. CASH FLOW STATEMENT
# =============================================================================
@dataclass
class CashFlowRow:
    """Cash flow statement row for one year."""
    year: int

    # A. Operating Activities
    net_income_keur: float
    add_depreciation_keur: float  # Non-cash add-back
    add_interest_keur: float  # Interest add-back (paid under Fin CF)
    change_in_working_capital_keur: float  # Typically 0 for SPV
    operating_cash_flow_keur: float

    # B. Investing Activities
    capex_keur: float  # Negative in Y0
    dsra_movement_keur: float
    investing_cash_flow_keur: float

    # C. Financing Activities
    debt_drawdown_keur: float
    debt_repayment_keur: float
    interest_paid_keur: float
    shl_drawdown_keur: float
    shl_repayment_keur: float
    equity_injection_keur: float
    dividends_paid_keur: float
    financing_cash_flow_keur: float

    # Net
    net_cash_flow_keur: float
    opening_cash_keur: float
    closing_cash_keur: float


# =============================================================================
# 4. DEBT SERVICE TABLE
# =============================================================================
@dataclass
class DebtServiceRow:
    """Debt service row for one period."""
    year: int
    period: int  # 1 or 2 (H1/H2)

    opening_balance_keur: float
    interest_keur: float
    scheduled_principal_keur: float
    cash_sweep_keur: float
    total_principal_keur: float
    total_debt_service_keur: float
    closing_balance_keur: float

    cfads_keur: float
    dscr: float
    llcr: float


# =============================================================================
# 5. WATERFALL PERIOD MAPPING
# =============================================================================
@dataclass
class WaterfallPeriodData:
    """Flattened waterfall period data for one period."""
    year_index: int
    period_in_year: int  # 1=H1, 2=H2
    is_operation: bool
    revenue_keur: float
    opex_keur: float
    ebitda_keur: float
    interest_senior_keur: float
    interest_shl_keur: float
    tax_keur: float
    senior_ds_keur: float
    shl_service_keur: float
    shl_principal_keur: float
    shl_interest_keur: float
    senior_principal_keur: float
    distribution_keur: float
    dsra_balance_keur: float
    cash_keur: float
    senior_balance_keur: float  # Remaining senior debt
    dscr: float


# =============================================================================
# 6. BUILDERS
# =============================================================================
def flatten_waterfall(periods) -> list[WaterfallPeriodData]:
    """Flatten waterfall result periods into WaterfallPeriodData list."""
    result = []
    for p in periods:
        is_op = getattr(p, 'is_operation', p.year_index > 0 if hasattr(p, 'year_index') else False)
        result.append(WaterfallPeriodData(
            year_index=p.year_index,
            period_in_year=getattr(p, 'period_in_year', 1),
            is_operation=is_op,
            revenue_keur=getattr(p, 'revenue_keur', 0.0),
            opex_keur=getattr(p, 'opex_keur', 0.0),
            ebitda_keur=getattr(p, 'ebitda_keur', 0.0),
            interest_senior_keur=getattr(p, 'interest_senior_keur', 0.0),
            interest_shl_keur=getattr(p, 'interest_shl_keur', 0.0),
            tax_keur=getattr(p, 'tax_keur', 0.0),
            senior_ds_keur=getattr(p, 'senior_ds_keur', 0.0),
            shl_service_keur=getattr(p, 'shl_service_keur', 0.0),
            shl_principal_keur=getattr(p, 'shl_principal_keur', 0.0),
            shl_interest_keur=getattr(p, 'shl_interest_keur', 0.0),
            senior_principal_keur=getattr(p, 'senior_principal_keur', 0.0),
            distribution_keur=getattr(p, 'distribution_keur', 0.0),
            dsra_balance_keur=getattr(p, 'dsra_balance_keur', 0.0),
            cash_keur=getattr(p, 'cash_balance_keur', 0.0),
            senior_balance_keur=getattr(p, 'senior_balance_keur', 0.0),
            dscr=getattr(p, 'dscr', float('inf')),
        ))
    return result


def build_income_statement(
    waterfall_periods,  # list of waterfall period objects
    fin_dep_schedule: dict[int, float],  # year → financial depreciation
    tax_dep_schedule: dict[int, float],  # year → tax depreciation
    horizon_years: int,
) -> list[IncomeStatementRow]:
    """Build annual income statement from waterfall periods.

    Args:
        waterfall_periods: List of waterfall period objects
        fin_dep_schedule: Dict mapping year_index → financial depreciation
        tax_dep_schedule: Dict mapping year_index → tax depreciation
        horizon_years: Number of years to project

    Returns:
        List of IncomeStatementRow
    """
    flat = flatten_waterfall(waterfall_periods)

    # Group by year (aggregate H1 + H2)
    op_periods = [p for p in flat if p.is_operation and p.year_index > 0]
    rows = []

    for year in range(1, horizon_years + 1):
        year_periods = [p for p in op_periods if p.year_index == year]
        if not year_periods:
            continue

        # Revenue
        total_rev = sum(p.revenue_keur for p in year_periods)
        ppa_rev = total_rev  # Simplified: all PPA for now

        # Costs
        opex = sum(p.opex_keur for p in year_periods)
        ebitda = max(0.0, total_rev - opex)
        fin_dep = fin_dep_schedule.get(year, 0.0)
        ebit = ebitda - fin_dep

        # Financing
        interest_senior = sum(p.interest_senior_keur for p in year_periods)
        interest_shl = sum(p.interest_shl_keur for p in year_periods)
        total_interest = interest_senior + interest_shl

        # EBT
        ebt = ebit - total_interest

        # Tax depreciation
        tax_dep = tax_dep_schedule.get(year, 0.0)

        # Taxable profit = EBT + financial dep - tax dep
        # (financial dep is added back because it's not tax-deductible,
        #  but tax dep gives additional shield)
        taxable = max(0.0, ebt + fin_dep - tax_dep)

        # Tax
        income_tax = sum(abs(p.tax_keur) for p in year_periods)
        eff_rate = income_tax / ebitda if ebitda > 0 else 0.0

        # Net income
        net_income = ebt - income_tax if ebt > 0 else max(0.0, ebt - income_tax)

        rows.append(IncomeStatementRow(
            year=year,
            ppa_revenue_keur=ppa_rev,
            market_revenue_keur=0.0,
            co2_revenue_keur=0.0,
            total_revenue_keur=total_rev,
            opex_keur=opex,
            ebitda_keur=ebitda,
            ebitda_margin_pct=ebitda / total_rev if total_rev > 0 else 0.0,
            depreciation_financial_keur=fin_dep,
            ebit_keur=ebit,
            interest_senior_keur=interest_senior,
            interest_shl_keur=interest_shl,
            total_interest_keur=total_interest,
            ebt_keur=ebt,
            tax_depreciation_keur=tax_dep,
            taxable_profit_keur=taxable,
            income_tax_keur=income_tax,
            effective_tax_rate_pct=eff_rate,
            net_income_keur=net_income,
        ))

    return rows


def build_balance_sheet(
    income_rows: list[IncomeStatementRow],
    total_capex_keur: float,
    share_capital_keur: float,
    share_premium_keur: float,
    shl_initial_keur: float,
    dsra_schedule: dict[int, float],
    cash_schedule: dict[int, float],
    distribution_schedule: dict[int, float],
    debt_schedule: list[DebtServiceRow],  # Period-level debt schedule
) -> list[BalanceSheetRow]:
    """Build annual balance sheet.

    Args:
        income_rows: Income statement rows
        total_capex_keur: Total CAPEX in kEUR
        share_capital_keur: Share capital in kEUR
        share_premium_keur: Share premium in kEUR
        shl_initial_keur: Initial SHL amount in kEUR
        dsra_schedule: Dict mapping year_index → DSRA balance
        cash_schedule: Dict mapping year_index → cash balance
        distribution_schedule: Dict mapping year_index → annual distributions to equity
        debt_schedule: Debt service schedule (period-level)

    Returns:
        List of BalanceSheetRow
    """
    rows = []
    retained_earnings = 0.0
    accumulated_fin_dep = 0.0
    shl_remaining = shl_initial_keur  # Track SHL balance across years

    for inc in income_rows:
        year = inc.year

        # Accumulated financial depreciation
        accumulated_fin_dep += inc.depreciation_financial_keur
        net_fixed = max(0.0, total_capex_keur - accumulated_fin_dep)

        # DSRA and cash
        dsra = dsra_schedule.get(year, 0.0)
        cash = cash_schedule.get(year, 0.0)
        total_current = dsra + cash

        # Debt from debt_schedule (need period-level for opening/closing)
        # For now, simplify: use last period of year's closing balance
        year_debt = [d for d in debt_schedule if d.year == year]
        if year_debt:
            senior_balance = year_debt[-1].closing_balance_keur
            # Current portion = next year's scheduled principal
            next_year = year + 1
            next_debt = [d for d in debt_schedule if d.year == next_year]
            current_senior = sum(d.scheduled_principal_keur for d in next_debt)
        else:
            senior_balance = 0.0
            current_senior = 0.0

        # SHL (track repayments from waterfall periods)
        # Sum SHL principal from all periods in this year
        year_shl_principal = 0.0
        for d in debt_schedule:
            if d.year == year:
                year_shl_principal += getattr(d, 'shl_principal_keur', 0.0)
        shl_remaining = max(0.0, shl_remaining - year_shl_principal)
        shl_balance = shl_remaining

        # Total assets
        total_assets = net_fixed + total_current

        # Liabilities
        total_ncl = senior_balance + shl_balance
        total_cl = current_senior + inc.income_tax_keur
        total_liabilities = total_ncl + total_cl

        # Equity
        # Retained earnings: accumulate net income, deduct distributions
        distribution = distribution_schedule.get(year, 0.0)
        current_profit = inc.net_income_keur
        retained_earnings += current_profit - distribution
        total_equity = (
            share_capital_keur
            + share_premium_keur
            + retained_earnings
        )
        total_l_and_e = total_liabilities + total_equity

        rows.append(BalanceSheetRow(
            year=year,
            gross_fixed_assets_keur=total_capex_keur,
            accumulated_depreciation_keur=accumulated_fin_dep,
            net_fixed_assets_keur=net_fixed,
            dsra_balance_keur=dsra,
            mra_balance_keur=0.0,
            cash_and_equivalents_keur=cash,
            total_current_assets_keur=total_current,
            total_assets_keur=total_assets,
            senior_debt_keur=senior_balance,
            shl_keur=shl_balance,
            total_non_current_liabilities_keur=total_ncl,
            current_portion_senior_debt_keur=current_senior,
            income_tax_payable_keur=inc.income_tax_keur,
            total_current_liabilities_keur=total_cl,
            total_liabilities_keur=total_liabilities,
            share_capital_keur=share_capital_keur,
            share_premium_keur=share_premium_keur,
            retained_earnings_keur=retained_earnings,
            current_year_profit_keur=current_profit,
            total_equity_keur=total_equity,
            total_liabilities_and_equity_keur=total_l_and_e,
        ))

    return rows


def build_cash_flow_statement(
    income_rows: list[IncomeStatementRow],
    total_capex_keur: float,
    equity_injection_keur: float,
    shl_drawdown_keur: float,
    dsra_schedule: dict[int, float],
    distribution_schedule: dict[int, float],
    debt_schedule: list[DebtServiceRow],
) -> list[CashFlowRow]:
    """Build annual cash flow statement.

    Args:
        income_rows: Income statement rows
        total_capex_keur: Total CAPEX in kEUR
        equity_injection_keur: Equity injected at financial close
        shl_drawdown_keur: SHL drawn at financial close
        dsra_schedule: Dict mapping year_index → DSRA balance
        distribution_schedule: Dict mapping year_index → distributions
        debt_schedule: Debt service schedule (period-level)

    Returns:
        List of CashFlowRow
    """
    rows = []
    opening_cash = 0.0

    for inc in income_rows:
        year = inc.year

        # A. Operating (indirect method)
        # Net income already reflects interest deduction — add interest back here.
        # Interest paid is reported under Financing CF (no double-count).
        op_cf = (
            inc.net_income_keur
            + inc.depreciation_financial_keur
            + inc.total_interest_keur
        )

        # B. Investing
        capex = -total_capex_keur if year == 0 else 0.0
        dsra_prev = dsra_schedule.get(year - 1, 0.0)
        dsra_curr = dsra_schedule.get(year, 0.0)
        dsra_movement = -(dsra_curr - dsra_prev)
        inv_cf = capex + dsra_movement

        # C. Financing
        year_debt = [d for d in debt_schedule if d.year == year]
        principal_paid = -sum(d.total_principal_keur for d in year_debt)
        interest_paid = -inc.total_interest_keur
        dividends = -distribution_schedule.get(year, 0.0)

        fin_cf = principal_paid + interest_paid + dividends
        if year <= 0:
            fin_cf += equity_injection_keur + shl_drawdown_keur

        # Net
        net_cf = op_cf + inv_cf + fin_cf
        closing_cash = opening_cash + net_cf

        rows.append(CashFlowRow(
            year=year,
            net_income_keur=inc.net_income_keur,
            add_depreciation_keur=inc.depreciation_financial_keur,
            add_interest_keur=inc.total_interest_keur,
            change_in_working_capital_keur=0.0,
            operating_cash_flow_keur=op_cf,
            capex_keur=capex,
            dsra_movement_keur=dsra_movement,
            investing_cash_flow_keur=inv_cf,
            debt_drawdown_keur=0.0,
            debt_repayment_keur=principal_paid,
            interest_paid_keur=interest_paid,
            shl_drawdown_keur=0.0,
            shl_repayment_keur=0.0,
            equity_injection_keur=equity_injection_keur if year <= 0 else 0.0,
            dividends_paid_keur=dividends,
            financing_cash_flow_keur=fin_cf,
            net_cash_flow_keur=net_cf,
            opening_cash_keur=opening_cash,
            closing_cash_keur=closing_cash,
        ))

        opening_cash = closing_cash

    return rows


def build_debt_schedule_simple(
    waterfall_periods,  # period-level waterfall data
    rate_per_period: float,
) -> list[DebtServiceRow]:
    """Build simple period-level debt schedule from waterfall.

    This is a simplified version that extracts data from waterfall periods.
    For full sculpting, use the closed_form_sculpt() function.

    Args:
        waterfall_periods: List of waterfall period objects
        rate_per_period: Semi-annual interest rate

    Returns:
        List of DebtServiceRow
    """
    rows = []
    flat = flatten_waterfall(waterfall_periods)
    prev_row = None  # Track previous DebtServiceRow for opening balance
    
    for p in flat:
        if not p.is_operation:
            continue

        # Opening balance = previous period's closing balance
        # senior_balance_keur from waterfall = balance_schedule[period] = OPENING balance for that period
        # (This is the scheduled opening balance; actual closing may differ due to cash sweep)
        if prev_row is None:
            opening = p.senior_balance_keur if p.senior_balance_keur else 0.0
        else:
            opening = prev_row.closing_balance_keur

        interest = p.interest_senior_keur
        scheduled_principal = p.senior_principal_keur
        cash_sweep = getattr(p, 'cash_sweep_keur', 0.0)
        total_principal = scheduled_principal + cash_sweep
        total_ds = interest + total_principal
        closing = opening - total_principal

        cfads = p.ebitda_keur
        dscr = p.dscr if p.dscr > 0 else float('inf')
        llcr = cfads / closing if closing > 0 else float('inf')

        row = DebtServiceRow(
            year=p.year_index,
            period=p.period_in_year,
            opening_balance_keur=opening,
            interest_keur=interest,
            scheduled_principal_keur=scheduled_principal,
            cash_sweep_keur=cash_sweep,
            total_principal_keur=total_principal,
            total_debt_service_keur=total_ds,
            closing_balance_keur=closing,
            cfads_keur=cfads,
            dscr=dscr,
            llcr=llcr,
        )
        rows.append(row)
        prev_row = row  # Track for next iteration

    return rows
