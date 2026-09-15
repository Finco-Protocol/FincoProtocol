"""Typed capability bundle for the generic hierarchical OPEX dispatch path.

The presence of a HierarchicalOpexCapability on ProjectInputs is the sole
dispatch signal in opex_schedule_period().  The dispatcher uses only the
fields defined here; it never inspects project name, code, or any other
identity field.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from finco_core.opex.hierarchical._inputs import OpexModelInput


@dataclass(frozen=True)
class HierarchicalOpexCapability:
    """Complete typed input bundle for the hierarchical OPEX engine.

    opex_model          — the validated hierarchical cost structure
    external_annual_series — external series (e.g. D=Salary, F=Taxes)
                            passed directly into OpexCalculationContext;
                            must cover the full horizon
    """
    opex_model: "OpexModelInput"
    external_annual_series: tuple[tuple[str, tuple[float, ...]], ...]
