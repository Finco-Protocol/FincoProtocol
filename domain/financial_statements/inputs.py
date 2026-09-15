"""Configuration for offline financial statement assembly."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FinancialStatementsConfig:
    """Offline assembly settings.

    The config describes reporting conventions only. It is not a runtime model
    switch and does not alter waterfall, tax, SHL, debt, or distribution logic.
    """

    project_code: str = ""
    template_name: str = "generic_market_a"
    cit_rate: float = 0.18
    period_frequency: str = "semiannual"
    cash_tax_timing: str = "annual_h2_diagnostic"
    loss_carryforward_years: int = 5
    include_tax_bridge: bool = True
