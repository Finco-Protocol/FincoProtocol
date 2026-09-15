"""Enumeration types for the generic hierarchical OPEX engine.

These enums define the shape of every classification decision in the engine.
No project-specific codes or names appear here.
"""
from __future__ import annotations

from enum import Enum


class OpexAmountBasis(str, Enum):
    """How a subitem's base_amount_keur is interpreted per operating year."""

    ANNUAL_RUN_RATE = "ANNUAL_RUN_RATE"
    # Placeholders for future semantics.  The calculator raises ValueError
    # if any of these are used — no silent fallback.
    PER_PERIOD_FIXED = "PER_PERIOD_FIXED"
    ONE_OFF = "ONE_OFF"
    DRIVER_BASED = "DRIVER_BASED"


class OpexActivationMode(str, Enum):
    """How a subitem's active/inactive state is resolved each operating year."""

    ALWAYS = "ALWAYS"
    MANUAL = "MANUAL"
    SENIOR_DEBT_TENOR_ACTIVE = "SENIOR_DEBT_TENOR_ACTIVE"


class OpexEscalationConvention(str, Enum):
    """How annual amounts escalate over the operating horizon.

    YEAR_1_AS_BASE:
        Y1 = base_amount
        Yn = base_amount × (1 + inflation_rate)^(n − 1)

    PRE_OPERATION_BASE:
        The configured budget represents a pre-COD (pre-operating-year-1) base.
        Y1 = base_amount × (1 + inflation_rate)^1
        Yn = base_amount × (1 + inflation_rate)^n
        Required for lease schedules inflated from pre-COD (e.g. B.07 Land Lease).
    """

    YEAR_1_AS_BASE = "YEAR_1_AS_BASE"
    PRE_OPERATION_BASE = "PRE_OPERATION_BASE"


class OpexCategoryCalculationType(str, Enum):
    """How a category's annual total is derived from its configuration."""

    SUBITEM_SUM = "SUBITEM_SUM"
    PERCENTAGE_OF_SELECTED_BASES = "PERCENTAGE_OF_SELECTED_BASES"
