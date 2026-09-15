"""Offline PF Cash Waterfall assembly from existing audit fields."""

from __future__ import annotations

from domain.financial_statements.result import (
    PFCashWaterfallPeriodResult,
    PFCashWaterfallResult,
)
from domain.waterfall.waterfall_engine import WaterfallResult


def assemble_pf_cash_waterfall(waterfall_result: WaterfallResult) -> PFCashWaterfallResult:
    periods: list[PFCashWaterfallPeriodResult] = []
    previous_dsra_balance = 0.0

    for period in waterfall_result.periods:
        dsra_delta = period.dsra_balance_keur - previous_dsra_balance
        dsra_funding = max(0.0, dsra_delta)
        dsra_release = max(0.0, -dsra_delta)
        previous_dsra_balance = period.dsra_balance_keur

        shl_cash_interest = max(0.0, period.shl_service_keur - period.shl_principal_keur)
        net_shl_cash_outflow = -(shl_cash_interest + period.shl_principal_keur)
        fcf_for_dividends = period.r102_fcf_for_shl_keur + net_shl_cash_outflow
        lockup_applied = period.r98_distribution_account_keur > period.r99_fcf_for_distribution_keur + 0.0001

        periods.append(
            PFCashWaterfallPeriodResult(
                period_index=period.period,
                date=period.date,
                revenue_cash_keur=period.revenue_keur,
                opex_cash_keur=-period.opex_keur,
                ebitda_cash_keur=period.ebitda_keur,
                senior_cash_interest_keur=-period.senior_interest_keur,
                cash_tax_keur=-period.corporate_tax_cash_keur,
                fcf_banks_keur=period.r69_fcf_banks_keur,
                senior_total_ds_keur=-period.senior_ds_keur,
                dsra_funding_keur=-dsra_funding,
                dsra_release_keur=dsra_release,
                fcf_junior_keur=period.r84_fcf_junior_keur,
                junior_ds_keur=0.0,
                other_cash_keur=0.0,
                distribution_account_pre_lockup_keur=period.r98_distribution_account_keur,
                lockup_applied=lockup_applied,
                lockup_reason="distribution_account_carryforward" if lockup_applied else None,
                fcf_for_distribution_keur=period.r99_fcf_for_distribution_keur,
                distribution_account_carryforward_keur=period.r100_carryforward_keur,
                fcf_for_shl_keur=period.r102_fcf_for_shl_keur,
                shl_cash_interest_keur=shl_cash_interest,
                shl_pik_keur=period.shl_pik_keur,
                shl_principal_keur=period.shl_principal_keur,
                net_shl_cash_outflow_keur=net_shl_cash_outflow,
                fcf_for_dividends_keur=fcf_for_dividends,
                net_dividends_keur=period.distribution_keur,
                r99_runtime_source_accepted=False,
            )
        )

    return PFCashWaterfallResult(periods=tuple(periods))
