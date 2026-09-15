"""Synthetic OPEX template for the public Generic Wind Reference."""

from __future__ import annotations

from domain.opex.line_items import OpexBasis, OpexContingencyMethod, OpexGroup, OpexItem


def _fixed(code: str, name: str, amount: float, group: str, inflation: float = 0.02) -> OpexItem:
    return OpexItem(
        code=code,
        name=name,
        budget_keur=float(amount),
        basis=OpexBasis.FIXED_ANNUAL_KEUR,
        group_code=group,
        inflation_rate=inflation,
    )


def _group(code: str, name: str, amount: float, order: int) -> OpexGroup:
    return OpexGroup(
        code=code,
        name=name,
        inflation_rate=0.02,
        items=(_fixed(f"{code}.01", name, amount, code),),
        order=order,
    )


def build_generic_wind_reference_opex_template() -> list[OpexGroup]:
    """Return a wholly synthetic, jurisdiction-neutral wind OPEX template."""
    groups = [
        _group("B.01", "Asset & Technical Management", 180.0, 1),
        _group("B.02", "Operations & Maintenance", 620.0, 2),
        _group("B.03", "Grid & Communications", 90.0, 3),
        _group("B.04", "Land & Site", 70.0, 4),
        _group("B.05", "Insurance", 160.0, 5),
        _group("B.06", "Administration", 100.0, 6),
        _group("B.07", "Professional Services", 80.0, 7),
        _group("B.08", "Market & Balancing", 120.0, 8),
        _group("B.09", "Security & HSE", 60.0, 9),
        _group("B.10", "Local Charges", 50.0, 10),
        _group("B.11", "Major Maintenance Reserve", 140.0, 11),
        _group("B.12", "Other Operating Costs", 80.0, 12),
    ]
    selected = tuple(g.code for g in groups)
    groups.append(
        OpexGroup(
            code="B.13",
            name="OPEX Contingency",
            inflation_rate=0.0,
            items=(OpexItem(
                code="B.13.01",
                name="OPEX Contingency",
                budget_keur=0.0,
                basis=OpexBasis.PCT_OF_SELECTED_GROUPS,
                group_code="B.13",
                inflation_rate=0.0,
                selected_group_codes=selected,
            ),),
            order=13,
            contingency_pct=3.0,
            contingency_method=OpexContingencyMethod.PERCENTAGE_OF_OPEX,
        )
    )
    return groups


__all__ = ["build_generic_wind_reference_opex_template"]
