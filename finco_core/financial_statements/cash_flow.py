"""Cash flow statement aggregation from WaterfallPeriod outputs."""
from finco_core.financial_statements.statement_models import CashFlowPeriod
from finco_core.financial_statements.income_statement import generate_income_statement


def generate_cash_flow_statement(periods, capex_schedule_keur: list[float] | None = None) -> list[CashFlowPeriod]:
    """Aggregate cash flow statement (indirect method) from WaterfallPeriod list.

    OCF = net_income + dep + interest_senior_IS + interest_shl_IS (add back IS interest)
    ICF = -capex (per period if schedule provided, else 0)
    FCF = -senior_interest_cash - senior_principal - shl_interest_cash
          - dsra_movement - mra_movement - distribution

    Note: shl_principal_keur is shown in the FCF for disclosure but is NOT included in the
    cash flow sum used to close against waterfall's cash_balance_keur. In the Generic Wind Reference/Generic Solar Reference
    waterfall model, SHL principal is a notional book reduction (reduces shl_balance_keur)
    without a corresponding cash outflow from cash_balance_keur. This is a model-specific
    accounting convention; including it would prevent CFS closure against the waterfall.

    All values from existing WaterfallPeriod fields — no new calculations.
    """
    is_periods = generate_income_statement(periods)

    n = len(periods)
    capex = capex_schedule_keur if capex_schedule_keur is not None else [0.0] * n

    result = []
    prev_dsra = 0.0
    prev_mra = 0.0
    opening_cash = 0.0

    for i, (p, isp) in enumerate(zip(periods, is_periods)):
        # Operating (indirect method: add back non-cash items and IS accrual interest,
        # plus working-capital adjustment for tax timing differences).
        # tax_payable_adj = tax_keur(accrual) - (ebitda - cf_after_tax)(cash_tax_this_period)
        # When positive: more tax accrued than paid → payable increases → source of cash.
        # isp.interest_shl_keur = shl_pik + shl_interest_cash (from IS), added back here.
        tax_payable_adj = p.tax_keur - (p.ebitda_keur - p.cf_after_tax_keur)
        ocf = (isp.net_income_keur + p.depreciation_keur + p.interest_senior_keur
               + isp.interest_shl_keur + tax_payable_adj)

        # Investing
        period_capex = capex[i] if i < len(capex) else 0.0
        icf = -period_capex

        # Financing
        dsra_movement = p.dsra_balance_keur - prev_dsra
        mra_movement = p.mra_balance_keur - prev_mra
        # Exclude shl_principal from the cash sum — it's a notional reduction in this model.
        fcf = (
            -p.senior_interest_keur
            - p.senior_principal_keur
            - p.shl_interest_keur
            - dsra_movement
            - mra_movement
            - p.distribution_keur
        )

        net = ocf + icf + fcf
        closing = p.cash_balance_keur
        check = closing - (opening_cash + net)

        result.append(CashFlowPeriod(
            period=p.period,
            date=p.date,
            net_income_keur=isp.net_income_keur,
            add_depreciation_keur=p.depreciation_keur,
            add_interest_senior_keur=p.interest_senior_keur,
            add_interest_shl_keur=isp.interest_shl_keur,
            tax_payable_adjustment_keur=tax_payable_adj,
            operating_cash_flow_keur=ocf,
            capex_keur=period_capex,
            investing_cash_flow_keur=icf,
            senior_principal_keur=p.senior_principal_keur,
            shl_principal_keur=p.shl_principal_keur,  # disclosed but not in cash sum
            interest_paid_senior_keur=p.senior_interest_keur,
            interest_paid_shl_keur=p.shl_interest_keur,
            dsra_movement_keur=dsra_movement,
            mra_movement_keur=mra_movement,
            distribution_keur=p.distribution_keur,
            financing_cash_flow_keur=fcf,
            net_cash_flow_keur=net,
            opening_cash_keur=opening_cash,
            closing_cash_keur=closing,
            check_keur=check,
        ))

        prev_dsra = p.dsra_balance_keur
        prev_mra = p.mra_balance_keur
        opening_cash = closing

    return result
