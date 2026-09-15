"""Synthetic financial statement templates."""
from domain.financial_statements.templates.generic_market_a import (
    GenericMarketAFinancialStatementsTemplate,
    build_generic_market_a_financial_statements_config,
    build_generic_market_a_loss_carryforward_config,
)

__all__ = [
    "GenericMarketAFinancialStatementsTemplate",
    "build_generic_market_a_financial_statements_config",
    "build_generic_market_a_loss_carryforward_config",
]
