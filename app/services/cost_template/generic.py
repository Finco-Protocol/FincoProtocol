"""Generic Solar / Wind Cost Template builders.

Deterministically derive a GENERIC CostTemplate from the canonical reference
`ProjectInputs` plus the `PUBLIC_GENERIC_DETAIL_V1` child taxonomy. The
generic template preserves FINCO's child hierarchy (C.NN.NN / B.NN.NN) and
the reference economics exactly — zero intended numerical change: the
template's reference amounts ARE the reference amounts.

Driver semantics for the generic templates (existing authority, generalized
from the reference-seed V0):

- every seeded CAPEX/OPEX line is `EUR_PER_MW` with the reference unit rate
  (`unit_rate_keur_per_mw`) — identical to the reference-seed contract;
- parent-level rows carry `ABSOLUTE_KEUR` reference amounts for lineage;
- C.13 contingencies keep their percentage semantics when the typed
  contingency authority is active, otherwise they are ordinary ABSOLUTE_KEUR
  rows exactly as the reference model defines them;
- C.17 / C.18 appear only as `DERIVED_RUNTIME` metadata rows.
"""
from __future__ import annotations

from typing import Any

from app.reference_detail_catalog import (
    PUBLIC_GENERIC_DETAIL_V1,
    allocate_parent_amount,
    capex_children,
    opex_children,
)
from app.services.cost_template.contracts import (
    CapexTemplateItem,
    CostDriver,
    CostTemplate,
    ItemClassification,
    OpexTemplateItem,
    ScalingBasis,
    TemplateKind,
    TemplateSource,
)

_TECHNOLOGY_BY_TEMPLATE_SOURCE = {
    "generic_solar_reference": "solar",
    "generic_wind_reference": "wind",
}

_FINANCING_SCALAR_PARENTS = {"C.17", "C.18"}

# Additive OPEX name → parent group extensions used by the reference seed.
_EXTRA_OPEX_GROUP_BY_NAME = {
    "Security / HSE": "B.05",
    "Audit & Accounting & Legal": "B.10",
    "Bank Fees": "B.11",
}


def _capex_field_by_category() -> dict[str, str]:
    """Deterministic first-owner C-code per CapexStructure field (the
    reference-seed owner rule; the C.08/C.11 alias never creates a second
    row)."""
    from app.persistence.capex_sub_lines import CAPEX_CATEGORY_TO_FIELD

    owners: dict[str, str] = {}
    for category_code, field_name in CAPEX_CATEGORY_TO_FIELD.items():
        owners.setdefault(field_name, category_code)
    return owners


def _generic_capex_items(pi: Any, technology: str) -> tuple[CapexTemplateItem, ...]:
    items: list[CapexTemplateItem] = []
    field_by_category = _capex_field_by_category()
    reference_capacity = float(pi.technical.capacity_mw)
    # Parent-level rows: one per canonical CapexItem field, ABSOLUTE_KEUR,
    # carrying the reference item's timing/accounting semantics verbatim.
    for field_name, parent_code in field_by_category.items():
        capex_item = getattr(pi.capex, field_name)
        if parent_code in _FINANCING_SCALAR_PARENTS:
            items.append(CapexTemplateItem(
                item_id=f"capex.{field_name}",
                parent_code=parent_code,
                label=capex_item.name,
                driver=CostDriver.DERIVED_RUNTIME,
                classification=ItemClassification.DERIVED_RUNTIME,
                source=TemplateSource.GENERIC_TEMPLATE,
                source_ref=PUBLIC_GENERIC_DETAIL_V1,
            ))
            continue
        contingency_pct = None
        if parent_code == "C.13":
            from app.contingency_authority import read_authority
            contingency_pct = read_authority(
                getattr(capex_item, "replay_metadata", None) or {}, "capex")
        driver = (CostDriver.PERCENT_OF_ELIGIBLE_CAPEX
                  if contingency_pct is not None else CostDriver.ABSOLUTE_KEUR)
        items.append(CapexTemplateItem(
            item_id=f"capex.{field_name}",
            parent_code=parent_code,
            label=capex_item.name,
            driver=driver,
            driver_value=contingency_pct,
            amount_keur=float(capex_item.amount_keur),
            y0_share=float(getattr(capex_item, "y0_share", 0.0) or 0.0),
            spending_profile=tuple(float(s) for s in (getattr(capex_item, "spending_profile", ()) or ())),
            asset_class=(capex_item.asset_class.value
                         if getattr(capex_item, "asset_class", None) is not None else None),
            useful_life_override=getattr(capex_item, "useful_life_override", None),
            is_depreciable=bool(getattr(capex_item, "is_depreciable", True)),
            scaling_basis=ScalingBasis.PER_MW,
            source=TemplateSource.GENERIC_TEMPLATE,
            source_ref=PUBLIC_GENERIC_DETAIL_V1,
        ))
        # Child detail rows: PUBLIC_GENERIC_DETAIL_V1 taxonomy, EUR_PER_MW
        # rates on the reference capacity (the seed V0 PER_MW contract).
        amount = float(capex_item.amount_keur)
        if amount == 0:
            continue
        for child, child_amount in allocate_parent_amount(
                amount, capex_children(technology, parent_code)):
            items.append(CapexTemplateItem(
                item_id=f"capex.{field_name}:{child.code}",
                parent_code=parent_code,
                child_code=child.code,
                label=child.label,
                driver=CostDriver.EUR_PER_MW,
                driver_value=child_amount / reference_capacity,
                amount_keur=child_amount,
                scaling_basis=ScalingBasis.PER_MW,
                source=TemplateSource.GENERIC_TEMPLATE,
                source_ref=PUBLIC_GENERIC_DETAIL_V1,
            ))
    return tuple(items)


def _generic_opex_items(pi: Any, technology: str) -> tuple[OpexTemplateItem, ...]:
    items: list[OpexTemplateItem] = []
    reference_capacity = float(pi.technical.capacity_mw)
    from app.reference_detail_catalog import OPEX_PARENT_BY_CANONICAL_KEY

    for opex_item in pi.opex:
        name = str(opex_item.name)
        if float(getattr(opex_item, "percentage_of_opex", 0) or 0):
            # B.13-style percentage authority: preserve the semantics.
            items.append(OpexTemplateItem(
                item_id=f"opex.{name}",
                parent_code="B.13",
                label=name,
                driver=CostDriver.PERCENT_OF_OPEX,
                driver_value=float(opex_item.percentage_of_opex),
                scaling_basis=ScalingBasis.EXACT_SNAPSHOT,
                source=TemplateSource.GENERIC_TEMPLATE,
                source_ref=PUBLIC_GENERIC_DETAIL_V1,
            ))
            continue
        group = OPEX_PARENT_BY_CANONICAL_KEY.get(name) or _EXTRA_OPEX_GROUP_BY_NAME.get(name)
        if group is None:
            # Derived runtime lines (e.g. Data Center power expenses) are
            # metadata only — never a seeded or materialized PER_MW line.
            items.append(OpexTemplateItem(
                item_id=f"opex.{name}",
                parent_code="B.01",
                label=name,
                driver=CostDriver.DERIVED_RUNTIME,
                classification=ItemClassification.DERIVED_RUNTIME,
                source=TemplateSource.GENERIC_TEMPLATE,
                source_ref=PUBLIC_GENERIC_DETAIL_V1,
            ))
            continue
        amount = float(opex_item.y1_amount_keur)
        steps = tuple((int(y), float(a)) for y, a in (getattr(opex_item, "step_changes", ()) or ()))
        # Parent-level ABSOLUTE_KEUR row with the exact per-line inflation.
        items.append(OpexTemplateItem(
            item_id=f"opex.{name}",
            parent_code=group,
            label=name,
            driver=CostDriver.ABSOLUTE_KEUR,
            y1_amount_keur=amount,
            annual_inflation=float(opex_item.annual_inflation),
            step_changes=steps,
            scaling_basis=ScalingBasis.PER_MW,
            source=TemplateSource.GENERIC_TEMPLATE,
            source_ref=PUBLIC_GENERIC_DETAIL_V1,
        ))
        # Child detail rows: EUR_PER_MW with per-line inflation preserved.
        for child, child_amount in allocate_parent_amount(
                amount, opex_children(group, technology)):
            items.append(OpexTemplateItem(
                item_id=f"opex.{name}:{child.code}",
                parent_code=group,
                child_code=child.code,
                label=child.label,
                driver=CostDriver.EUR_PER_MW,
                driver_value=child_amount / reference_capacity,
                y1_amount_keur=child_amount,
                annual_inflation=float(opex_item.annual_inflation),
                step_changes=steps,
                scaling_basis=ScalingBasis.PER_MW,
                source=TemplateSource.GENERIC_TEMPLATE,
                source_ref=PUBLIC_GENERIC_DETAIL_V1,
            ))
    return tuple(items)


def build_generic_cost_template(template_source: str, *, version: int = 1) -> CostTemplate:
    """Build the deterministic GENERIC CostTemplate for a canonical cloneable
    reference (Generic Solar / Generic Wind). Same inputs → identical
    template (bit-for-bit via the canonical serializer)."""
    technology = _TECHNOLOGY_BY_TEMPLATE_SOURCE.get(template_source)
    if technology is None:
        raise ValueError(
            f"GENERIC_TEMPLATE_SOURCE_UNSUPPORTED: {template_source!r}; supported: "
            f"{sorted(_TECHNOLOGY_BY_TEMPLATE_SOURCE)}"
        )
    from app.services.reference_seed_service import _reference_inputs

    pi = _reference_inputs(template_source)
    return CostTemplate.create(
        template_id=f"GENERIC_{technology.upper()}_COST",
        version=version,
        name=f"Generic {technology.capitalize()} Cost",
        technology=technology,
        kind=TemplateKind.GENERIC,
        capex_items=_generic_capex_items(pi, technology),
        opex_items=_generic_opex_items(pi, technology),
        provenance=(
            f"Derived from {template_source} with {PUBLIC_GENERIC_DETAIL_V1} "
            "detail taxonomy"
        ),
        reference_capacity_mw=float(pi.technical.capacity_mw),
    )
