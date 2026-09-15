"""Synthetic reporting template metadata for public reference models."""
from __future__ import annotations

from dataclasses import dataclass
from domain.financial_statements.inputs import FinancialStatementsConfig
from domain.tax.loss_carryforward import LossCarryforwardConfig


@dataclass(frozen=True)
class GenericMarketAFinancialStatementsTemplate:
    country_iso: str = "XA"
    cit_rate: float = 0.20
    period_frequency: str = "semiannual"
    cash_tax_timing: str = "annual_h2_diagnostic"
    loss_carryforward_years: int = 5
    loss_expiry_method: str = "fifo_per_vintage"


def build_generic_market_a_financial_statements_config(project_code: str = "") -> FinancialStatementsConfig:
    template = GenericMarketAFinancialStatementsTemplate()
    return FinancialStatementsConfig(
        project_code=project_code,
        template_name="generic_market_a",
        cit_rate=template.cit_rate,
        period_frequency=template.period_frequency,
        cash_tax_timing=template.cash_tax_timing,
        loss_carryforward_years=template.loss_carryforward_years,
    )


def build_generic_market_a_loss_carryforward_config(periods_per_year: int) -> LossCarryforwardConfig:
    template = GenericMarketAFinancialStatementsTemplate()
    return LossCarryforwardConfig(
        duration_years=template.loss_carryforward_years,
        periods_per_year=periods_per_year,
        expiry_method=template.loss_expiry_method,
        country_template="xa",
    )
