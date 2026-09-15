"""domain/senior_debt_sizing/ — Senior Debt Sizing Policy Module.

This module provides an isolated senior debt sizing policy abstraction.

It separates the question "how much debt can we service?"
from the question "how do we actually compute debt service?"

Two sizing modes:
    "explicit_cfads"   — use explicit sizing CFADS per period (model_source_ref style)
    "derive_from_minimum_dscr" — derive sizing CFADS from minimum DSCR target (future)

Default: "explicit_cfads"

This module is behind a default-off runtime flag:
    use_explicit_senior_debt_sizing_policy: bool = False

Existing senior debt runtime behavior in app/waterfall_core.py is unchanged by default.

R99/R102: BLOCKED — this module does not compute distribution gates.
"""
from domain.senior_debt_sizing.policy import (
    SeniorDebtSizingPolicy,
    SeniorDebtDSCRPolicy,
    SizingMode,
)
from domain.senior_debt_sizing.engine import SeniorDebtSizingEngine

__all__ = [
    "SeniorDebtSizingPolicy",
    "SeniorDebtDSCRPolicy",
    "SizingMode",
    "SeniorDebtSizingEngine",
]