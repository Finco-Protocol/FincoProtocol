"""Cost Template resolution and materialization planning (pure).

`resolve_cost_template` resolves every active item's concrete amounts under
a `MaterializationContext` (target capacity for PER_MW items). EXACT_SNAPSHOT
items ignore capacity; PER_MW items scale exactly like the reference-seed V0
(`amount = unit_rate × capacity`). Reserved drivers and DERIVED_RUNTIME rows
never materialize.

`build_materialization_plan` turns a resolved template into the concrete
project-owned shapes the existing authorities consume:

- parent CAPEX field plans (CapexItem-level: amount, timing, accounting),
- CAPEX sub-line plans (child rows with persistent identities),
- parent OPEX item plans (Y1 + per-line inflation + steps),
- OPEX sub-line plans (child rows, inflation in the persistence percent unit),
- contingency percentage entries (delegated to the existing contingency
  authority at application time — the plan never computes IDC or a
  contingency amount itself).

Deterministic and declaration-order independent (outputs are sorted).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from app.services.cost_template.contracts import (
    CapexTemplateItem,
    CostDriver,
    CostTemplate,
    ItemClassification,
    OpexTemplateItem,
    ScalingBasis,
)


@dataclass(frozen=True)
class MaterializationContext:
    capacity_mw: float
    # Optional pre-computed eligible CAPEX basis for contingency lineage;
    # when absent the plan carries the percentage only (the existing
    # contingency authority computes the basis at application time).
    eligible_capex_basis_keur: Optional[float] = None

    def validate(self) -> None:
        # Correction A (defect 7): NaN / +Inf / -Inf must fail closed, not
        # bypass a naive > 0 comparison.
        if isinstance(self.capacity_mw, bool) \
                or not isinstance(self.capacity_mw, (int, float)) \
                or not math.isfinite(float(self.capacity_mw)) \
                or float(self.capacity_mw) <= 0:
            raise ValueError(
                f"MATERIALIZATION_CONTEXT_INVALID: capacity_mw must be a finite "
                f"number strictly greater than zero, got {self.capacity_mw!r}"
            )


@dataclass(frozen=True)
class ResolvedCapexItem:
    item: CapexTemplateItem
    resolved_amount_keur: Optional[float]   # None for contingency-percentage rows


@dataclass(frozen=True)
class ResolvedOpexItem:
    item: OpexTemplateItem
    resolved_y1_amount_keur: Optional[float]


@dataclass(frozen=True)
class ResolvedCostTemplate:
    template: CostTemplate
    context: MaterializationContext
    capex: tuple[ResolvedCapexItem, ...]
    opex: tuple[ResolvedOpexItem, ...]


def resolve_cost_template(
    template: CostTemplate,
    context: MaterializationContext,
) -> ResolvedCostTemplate:
    """Resolve driver semantics into concrete amounts. Fail closed on
    reserved drivers, EXACT_SNAPSHOT rows without amounts, or invalid
    contexts. Deterministic."""
    template.validate()
    context.validate()

    resolved_capex: list[ResolvedCapexItem] = []
    for item in template.ordered_capex_items():
        if item.classification is ItemClassification.DERIVED_RUNTIME:
            resolved_capex.append(ResolvedCapexItem(item, None))
            continue
        if item.driver is CostDriver.PERCENT_OF_ELIGIBLE_CAPEX:
            resolved_capex.append(ResolvedCapexItem(item, None))
            continue
        if item.driver is CostDriver.EUR_PER_MW:
            if item.scaling_basis is ScalingBasis.PER_MW:
                resolved_capex.append(
                    ResolvedCapexItem(item, float(item.driver_value) * context.capacity_mw))
            else:  # EXACT_SNAPSHOT: the recorded amount is authoritative
                resolved_capex.append(ResolvedCapexItem(item, item.amount_keur))
            continue
        if item.driver is CostDriver.ABSOLUTE_KEUR:
            resolved_capex.append(ResolvedCapexItem(item, item.amount_keur))
            continue
        raise ValueError(
            f"MATERIALIZATION_DRIVER_RESERVED: driver {item.driver.value!r} cannot "
            f"materialize (item {item.item_id!r})"
        )

    resolved_opex: list[ResolvedOpexItem] = []
    for item in template.ordered_opex_items():
        if item.classification is ItemClassification.DERIVED_RUNTIME:
            resolved_opex.append(ResolvedOpexItem(item, None))
            continue
        if item.driver is CostDriver.PERCENT_OF_OPEX:
            resolved_opex.append(ResolvedOpexItem(item, None))
            continue
        if item.driver is CostDriver.EUR_PER_MW:
            if item.scaling_basis is ScalingBasis.PER_MW:
                resolved_opex.append(
                    ResolvedOpexItem(item, float(item.driver_value) * context.capacity_mw))
            else:
                resolved_opex.append(ResolvedOpexItem(item, item.y1_amount_keur))
            continue
        if item.driver is CostDriver.ABSOLUTE_KEUR:
            resolved_opex.append(ResolvedOpexItem(item, item.y1_amount_keur))
            continue
        raise ValueError(
            f"MATERIALIZATION_DRIVER_RESERVED: driver {item.driver.value!r} cannot "
            f"materialize (item {item.item_id!r})"
        )

    return ResolvedCostTemplate(
        template=template, context=context,
        capex=tuple(resolved_capex), opex=tuple(resolved_opex),
    )


# ---------------------------------------------------------------------------
# Materialization plan shapes (mirrors of the existing project-owned rows)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CapexFieldPlan:
    field_name: str
    parent_code: str
    label: str
    amount_keur: float
    y0_share: float = 0.0
    spending_profile: tuple[float, ...] = ()
    asset_class: Optional[str] = None
    useful_life_override: Optional[int] = None
    is_depreciable: bool = True
    # Applicability addendum (A7, Correction C defect 5): non-decomposed
    # parent applicability — stored economics retained, excluded from
    # current project economics while inactive.
    is_active: bool = True


@dataclass(frozen=True)
class CapexSubLinePlan:
    parent_category_code: str
    business_code: str
    label: str
    amount_keur: float
    schedule_json: str = "{}"
    source: str = "user"
    replay_metadata: dict = field(default_factory=dict)
    # Correction A (defect 2): approved CAPEX scalar metadata (VAT / WHT /
    # depreciation vocabulary), carried losslessly through the roundtrip.
    scalar_metadata: dict = field(default_factory=dict)
    # Applicability addendum: project-owned ON/OFF; inactive rows retain
    # their configured economics but are excluded from canonical subtotals.
    is_active: bool = True


@dataclass(frozen=True)
class OpexItemPlan:
    parent_code: str
    name: str
    y1_amount_keur: float
    annual_inflation: float = 0.0
    step_changes: tuple[tuple[int, float], ...] = ()
    percentage_of_opex: float = 0.0
    # Applicability addendum (A7, Correction C defect 5): project-owned
    # ON/OFF for non-decomposed parent assumptions. Stored economics are
    # NEVER zeroed by applicability; an inactive item contributes zero to
    # current economics and reactivates with its exact stored values.
    is_active: bool = True


@dataclass(frozen=True)
class OpexSubLinePlan:
    parent_group_code: str
    business_code: str
    label: str
    amount_keur: float
    inflation_pct: float = 0.0   # persistence unit (percent)
    source: str = "user"
    replay_metadata: dict = field(default_factory=dict)
    # Applicability addendum: project-owned ON/OFF.
    is_active: bool = True


@dataclass(frozen=True)
class ContingencyPlan:
    capex_pct: Optional[float] = None
    opex_pct: Optional[float] = None
    eligible_capex_basis_keur: Optional[float] = None
    lineage: dict = field(default_factory=dict)
    # Applicability addendum (A9): INACTIVE retains the configured
    # percentage but the authority is not applied; distinct from 0.0.
    capex_active: bool = True
    opex_active: bool = True


@dataclass(frozen=True)
class MaterializationPlan:
    template_id: str
    template_version: int
    capex_fields: tuple[CapexFieldPlan, ...]
    capex_sub_lines: tuple[CapexSubLinePlan, ...]
    opex_items: tuple[OpexItemPlan, ...]
    opex_sub_lines: tuple[OpexSubLinePlan, ...]
    contingency: Optional[ContingencyPlan] = None


def _parent_capex_field_plans(
    template: CostTemplate,
    resolved: ResolvedCostTemplate,
) -> tuple[CapexFieldPlan, ...]:
    from app.persistence.capex_sub_lines import CAPEX_CATEGORY_TO_FIELD

    category_to_field = dict(CAPEX_CATEGORY_TO_FIELD)
    # Correction A (defect 3): decomposition children REPLACE their canonical
    # parent. Correction B (defect 2): the reconciliation key is the
    # CANONICAL CapexStructure FIELD (via CAPEX_CATEGORY_TO_FIELD), not the
    # presentation category code - the C.08/C.11 alias both map to
    # audit_legal and must reconcile into ONE field amount. Applicability
    # addendum (A13) + Correction C (defect 4): decomposition PRESENCE
    # establishes the replacement authority - the field amount is the sum of
    # ACTIVE children INCLUDING the empty-active-set case (all children OFF
    # -> field amount 0, assumptions retained). Inactive rows are preserved
    # in the plan with their economics but excluded here.
    decomposition_present: set[str] = set()
    decomposition_children: dict[str, float] = {}
    active_child_count: dict[str, int] = {}
    for r in resolved.capex:
        if not r.item.replaces_parent or r.resolved_amount_keur is None:
            continue
        field_name = category_to_field.get(r.item.parent_code)
        if field_name is None:
            raise ValueError(
                f"MATERIALIZATION_PARENT_UNMAPPED: {r.item.parent_code!r} has no "
                "CapexStructure field authority"
            )
        decomposition_present.add(field_name)
        if not r.item.default_active:
            continue  # inactive: retained, never in the canonical subtotal
        active_child_count[field_name] = active_child_count.get(field_name, 0) + 1
        decomposition_children[field_name] = (
            decomposition_children.get(field_name, 0.0)
            + float(r.resolved_amount_keur))

    plans: list[CapexFieldPlan] = []
    for r in resolved.capex:
        item = r.item
        if item.child_code is not None:
            continue  # child rows materialize as sub-lines
        if item.classification is ItemClassification.DERIVED_RUNTIME:
            continue  # C.17/C.18 stay runtime-derived; never plan inputs
        if item.driver is CostDriver.PERCENT_OF_ELIGIBLE_CAPEX:
            continue  # contingency handled by the contingency plan entry
        field_name = category_to_field.get(item.parent_code)
        if field_name is None:
            raise ValueError(
                f"MATERIALIZATION_PARENT_UNMAPPED: {item.parent_code!r} has no "
                "CapexStructure field authority"
            )
        if field_name in decomposition_present:
            # Correction C (defect 4): decomposition presence ESTABLISHES the
            # authority - the amount is the active-children sum, including
            # the valid empty-active-set case (all children OFF -> 0). Never
            # fall back to the parent's own reference amount. Parent
            # applicability follows the children: active iff any active
            # child exists.
            plans.append(CapexFieldPlan(
                field_name=field_name,
                parent_code=item.parent_code,
                label=item.label,
                amount_keur=decomposition_children.get(field_name, 0.0),
                y0_share=item.y0_share,
                spending_profile=item.spending_profile,
                asset_class=item.asset_class,
                useful_life_override=item.useful_life_override,
                is_depreciable=item.is_depreciable,
                is_active=active_child_count.get(field_name, 0) > 0,
            ))
            continue
        if not item.default_active:
            # Correction C (defect 5): non-decomposed parent applicability -
            # stored economics retained in the plan, excluded from current
            # project economics via is_active.
            if r.resolved_amount_keur is None:
                raise ValueError(
                    f"MATERIALIZATION_AMOUNT_MISSING: item {item.item_id!r} "
                    "resolved to no amount (MISSING is not ZERO)"
                )
            plans.append(CapexFieldPlan(
                field_name=field_name,
                parent_code=item.parent_code,
                label=item.label,
                amount_keur=float(r.resolved_amount_keur),
                y0_share=item.y0_share,
                spending_profile=item.spending_profile,
                asset_class=item.asset_class,
                useful_life_override=item.useful_life_override,
                is_depreciable=item.is_depreciable,
                is_active=False,
            ))
            continue
        if r.resolved_amount_keur is None:
            raise ValueError(
                f"MATERIALIZATION_AMOUNT_MISSING: item {item.item_id!r} resolved "
                "to no amount (MISSING is not ZERO)"
            )
        plans.append(CapexFieldPlan(
            field_name=field_name,
            parent_code=item.parent_code,
            label=item.label,
            amount_keur=float(r.resolved_amount_keur),
            y0_share=item.y0_share,
            spending_profile=item.spending_profile,
            asset_class=item.asset_class,
            useful_life_override=item.useful_life_override,
            is_depreciable=item.is_depreciable,
        ))
    return tuple(sorted(plans, key=lambda p: p.parent_code))


def _capex_sub_line_plans(
    template: CostTemplate,
    resolved: ResolvedCostTemplate,
) -> tuple[CapexSubLinePlan, ...]:
    from app.persistence.capex_sub_lines import CAPEX_CATEGORY_TO_FIELD

    plans: list[CapexSubLinePlan] = []
    seen_codes: dict[str, str] = {}
    for r in resolved.capex:
        item = r.item
        if item.child_code is None or item.classification is ItemClassification.DERIVED_RUNTIME:
            continue
        if r.resolved_amount_keur is None:
            raise ValueError(
                f"MATERIALIZATION_AMOUNT_MISSING: item {item.item_id!r} resolved "
                "to no amount (MISSING is not ZERO)"
            )
        # Correction A (defect 1): persistence enforces
        # UNIQUE(project_id, business_code); two simultaneously materialized
        # rows may never share one business code — fail closed, no silent
        # merge, no silent renumbering.
        if item.child_code in seen_codes:
            raise ValueError(
                f"COST_TEMPLATE_BUSINESS_CODE_COLLISION: items "
                f"{seen_codes[item.child_code]!r} and {item.item_id!r} would both "
                f"materialize to business code {item.child_code!r}"
            )
        seen_codes[item.child_code] = item.item_id
        replay: dict = {
            "cost_template_id": template.template_id,
            "cost_template_version": template.version,
            "cost_template_item_id": item.item_id,
            "template_derived": True,
            "scaling_basis": item.scaling_basis.value,
        }
        if item.replaces_parent:
            # Correction A (defect 3): reuse the existing reference-seed
            # replacement vocabulary so the runtime's established
            # decomposition/replacement semantics apply unchanged.
            replay.update({
                "replaces_parent": True,
                "canonical_parent_field": CAPEX_CATEGORY_TO_FIELD.get(item.parent_code),
                "canonical_key": (
                    f"{CAPEX_CATEGORY_TO_FIELD.get(item.parent_code)}:{item.child_code}"),
                "detail_code": item.child_code,
                "scaling_mode": item.scaling_basis.value,
            })
        plans.append(CapexSubLinePlan(
            parent_category_code=item.parent_code,
            business_code=item.child_code,
            label=item.label,
            amount_keur=float(r.resolved_amount_keur),
            schedule_json=item.schedule_json or "{}",
            source="user",
            replay_metadata=replay,
            scalar_metadata=dict(item.scalar_metadata),
            is_active=item.default_active,
        ))
    return tuple(sorted(plans, key=lambda p: (p.parent_category_code, p.business_code)))


def _opex_item_plans(resolved: ResolvedCostTemplate) -> tuple[OpexItemPlan, ...]:
    # Correction A (defect 3): decomposition children REPLACE their canonical
    # parent OpexItem. Correction B (defect 3): the reconciliation key is the
    # CANONICAL OpexItem identity (canonical_parent_key - the exact item
    # name the existing fold removes), never the B.NN group code.
    # Correction B (defect 4) + applicability (A13): reconciliation happens
    # over the FINAL ACTIVE child set; inactive children are preserved in
    # the sub-line plans but excluded from the canonical subtotal.
    # Correction C (defect 4): decomposition PRESENCE establishes the
    # replacement authority - a canonical key with decomposition children is
    # reconciled from the ACTIVE children even when that active set is empty
    # (all children OFF -> canonical parent amount 0, assumptions retained).
    decomposition_present: dict[str, bool] = {}
    # Correction F (defect: decomposed parent applicability): tracks whether
    # ANY ACTIVE decomposition child exists for the canonical key. Presence
    # alone establishes replacement authority; applicability follows the
    # active set — all children OFF → parent amount 0 AND parent inactive.
    active_child_present: dict[str, bool] = {}
    decomposition_children: dict[str, float] = {}
    for r in resolved.opex:
        if not r.item.replaces_parent or r.resolved_y1_amount_keur is None:
            continue
        key = r.item.canonical_parent_key
        decomposition_present[key] = True
        if not r.item.default_active:
            continue  # inactive child: retained, excluded from the subtotal
        active_child_present[key] = True
        decomposition_children[key] = (
            decomposition_children.get(key, 0.0) + float(r.resolved_y1_amount_keur))

    plans: list[OpexItemPlan] = []
    for r in resolved.opex:
        item = r.item
        if item.child_code is not None:
            continue
        if item.classification is ItemClassification.DERIVED_RUNTIME:
            continue
        if item.driver is CostDriver.PERCENT_OF_OPEX:
            # Correction A (defect 6): driver_value is REQUIRED (validated at
            # the contract boundary); None never collapses to zero here.
            if item.driver_value is None:
                raise ValueError(
                    f"MATERIALIZATION_AMOUNT_MISSING: PERCENT_OF_OPEX item "
                    f"{item.item_id!r} has no driver_value (MISSING is not ZERO)"
                )
            # Boundary conversion: template percent points -> core fraction.
            # Applicability (A9): an inactive contingency plan row keeps the
            # configured percentage with is_active=False (authority not
            # applied at runtime).
            plans.append(OpexItemPlan(
                parent_code=item.parent_code,
                name=item.label,
                y1_amount_keur=0.0,
                annual_inflation=0.0,
                step_changes=(),
                percentage_of_opex=float(item.driver_value) / 100.0,
                is_active=item.default_active,
            ))
            continue
        # Correction C (defect 5): non-decomposed parent applicability.
        if not item.default_active and item.parent_code not in decomposition_present:
            if r.resolved_y1_amount_keur is None:
                raise ValueError(
                    f"MATERIALIZATION_AMOUNT_MISSING: item {item.item_id!r} "
                    "resolved to no amount (MISSING is not ZERO)"
                )
            plans.append(OpexItemPlan(
                parent_code=item.parent_code,
                name=item.label,
                y1_amount_keur=float(r.resolved_y1_amount_keur),
                annual_inflation=float(item.annual_inflation),
                step_changes=tuple(item.step_changes),
                is_active=False,
            ))
            continue
        parent_key = (item.canonical_parent_key
                      if item.canonical_parent_key else item.label)
        if parent_key in decomposition_present:
            y1 = decomposition_children.get(parent_key, 0.0)
            # Correction F: decomposed parent applicability = ANY(active
            # decomposition child) — all children OFF → parent 0 AND
            # inactive, never an active parent over an empty active set.
            plans.append(OpexItemPlan(
                parent_code=item.parent_code,
                name=item.label,
                y1_amount_keur=y1,
                annual_inflation=float(item.annual_inflation),
                step_changes=tuple(item.step_changes),
                is_active=active_child_present.get(parent_key, False),
            ))
            continue
        elif r.resolved_y1_amount_keur is None:
            raise ValueError(
                f"MATERIALIZATION_AMOUNT_MISSING: item {item.item_id!r} resolved "
                "to no amount (MISSING is not ZERO)"
            )
        else:
            y1 = float(r.resolved_y1_amount_keur)
        plans.append(OpexItemPlan(
            parent_code=item.parent_code,
            name=item.label,
            y1_amount_keur=y1,
            annual_inflation=float(item.annual_inflation),
            step_changes=tuple(item.step_changes),
        ))
    return tuple(sorted(plans, key=lambda p: p.name))


def _opex_sub_line_plans(
    template: CostTemplate,
    resolved: ResolvedCostTemplate,
) -> tuple[OpexSubLinePlan, ...]:
    plans: list[OpexSubLinePlan] = []
    seen_codes: dict[str, str] = {}
    for r in resolved.opex:
        item = r.item
        if item.child_code is None or item.classification is ItemClassification.DERIVED_RUNTIME:
            continue
        if r.resolved_y1_amount_keur is None:
            raise ValueError(
                f"MATERIALIZATION_AMOUNT_MISSING: item {item.item_id!r} resolved "
                "to no amount (MISSING is not ZERO)"
            )
        # Correction A (defect 1): same UNIQUE(project_id, business_code)
        # guarantee as CAPEX — fail closed on collisions.
        if item.child_code in seen_codes:
            raise ValueError(
                f"COST_TEMPLATE_BUSINESS_CODE_COLLISION: items "
                f"{seen_codes[item.child_code]!r} and {item.item_id!r} would both "
                f"materialize to business code {item.child_code!r}"
            )
        seen_codes[item.child_code] = item.item_id
        replay: dict = {
            "cost_template_id": template.template_id,
            "cost_template_version": template.version,
            "cost_template_item_id": item.item_id,
            "template_derived": True,
            "scaling_basis": item.scaling_basis.value,
        }
        if item.replaces_parent:
            # Correction A (defect 3): existing reference-seed replacement
            # vocabulary (canonical_parent_key / detail_code / scaling_mode).
            replay.update({
                "replaces_parent": True,
                "canonical_parent_key": item.parent_code,
                "detail_code": item.child_code,
                "scaling_mode": item.scaling_basis.value,
            })
        # Correction B (defect 3) + Correction C (defect 3): decomposition
        # rows carry the EXACT runtime replacement vocabulary -
        # reference_seed=True + canonical_key=<the canonical OpexItem name> -
        # AND the original persisted runtime row source
        # (reference_seed / user_override), because the existing fold
        # recognizes replacement rows by source in
        # {"reference_seed", "user_override"} + reference_seed=True +
        # canonical_key. Generic templates materialize reference_seed;
        # client-extracted rows keep their persisted source. A user
        # B.NN.U### row is additive with source="user".
        if item.replaces_parent:
            replay = dict(replay)
            replay.update({
                "reference_seed": True,
                "canonical_key": item.canonical_parent_key,
                "canonical_label": item.canonical_parent_key,
            })
        opex_source = "user"
        if item.replaces_parent:
            if item.persisted_source in {"reference_seed", "user_override"}:
                opex_source = item.persisted_source
            elif item.source.value == "generic_template":
                opex_source = "reference_seed"
        plans.append(OpexSubLinePlan(
            parent_group_code=item.parent_code,
            business_code=item.child_code,
            label=item.label,
            amount_keur=float(r.resolved_y1_amount_keur),
            # Persistence unit is percent; the template stores the fraction.
            inflation_pct=float(item.annual_inflation) * 100.0,
            source=opex_source,
            replay_metadata=replay,
            is_active=item.default_active,
        ))
    return tuple(sorted(plans, key=lambda p: (p.parent_group_code, p.business_code)))


def _contingency_plan(
    resolved: ResolvedCostTemplate,
) -> Optional[ContingencyPlan]:
    capex_pct = None
    opex_pct = None
    for r in resolved.capex:
        if r.item.driver is CostDriver.PERCENT_OF_ELIGIBLE_CAPEX:
            capex_pct = float(r.item.driver_value)
    for r in resolved.opex:
        if r.item.driver is CostDriver.PERCENT_OF_OPEX:
            opex_pct = float(r.item.driver_value)
    if capex_pct is None and opex_pct is None:
        return None
    return ContingencyPlan(
        capex_pct=capex_pct,
        opex_pct=opex_pct,
        eligible_capex_basis_keur=resolved.context.eligible_capex_basis_keur,
        lineage={"source": "cost_template",
                 "template_id": resolved.template.template_id,
                 "template_version": resolved.template.version},
        capex_active=resolved.template.capex_contingency_active,
        opex_active=resolved.template.opex_contingency_active,
    )


def build_materialization_plan(resolved: ResolvedCostTemplate) -> MaterializationPlan:
    """Deterministic plan builder. The plan contains ONLY project-owned cost
    inputs; C.17/C.18 and any DERIVED_RUNTIME rows are absent (they remain
    runtime-derived authorities)."""
    resolved.template.validate()
    return MaterializationPlan(
        template_id=resolved.template.template_id,
        template_version=resolved.template.version,
        capex_fields=_parent_capex_field_plans(resolved.template, resolved),
        capex_sub_lines=_capex_sub_line_plans(resolved.template, resolved),
        opex_items=_opex_item_plans(resolved),
        opex_sub_lines=_opex_sub_line_plans(resolved.template, resolved),
        contingency=_contingency_plan(resolved),
    )


# ---------------------------------------------------------------------------
# Override-safe rescale + plan → state rebuild (pure)
# ---------------------------------------------------------------------------

def rescale_materialization_plan(
    plan: MaterializationPlan,
    *,
    template: CostTemplate,
    new_capacity_mw: float,
    overridden_item_ids: frozenset[str] | set[str] = frozenset(),
) -> MaterializationPlan:
    """Rescale ONLY untouched template-derived PER_MW rows to a new capacity.

    Generalizes the reference-seed rule "rescale untouched seed lines;
    preserve user overrides": rows whose `cost_template_item_id` is in
    `overridden_item_ids` (user-edited after materialization) keep their
    project-owned amounts. EXACT_SNAPSHOT rows are never rescaled.
    Duplicate application is idempotent by item id (replace, never
    double-count). Contingency percentage entries are passed through
    unchanged (the authority recomputes amounts).
    """
    template.validate()
    if new_capacity_mw <= 0:
        raise ValueError(
            f"RESCALE_CAPACITY_INVALID: new_capacity_mw must be positive, got "
            f"{new_capacity_mw!r}"
        )
    from app.services.cost_template.serialize import cost_template_from_json, cost_template_to_json

    # Resolve against the NEW capacity from the immutable template, then take
    # only the non-overridden PER_MW rows from the fresh resolution; every
    # overridden row keeps its existing plan amount.
    fresh = resolve_cost_template(
        template, MaterializationContext(capacity_mw=new_capacity_mw))
    fresh_capex = {r.item.item_id: r for r in fresh.capex}
    fresh_opex = {r.item.item_id: r for r in fresh.opex}

    capex_fields = list(plan.capex_fields)
    item_to_parent = {i.item_id: i for i in template.capex_items}
    for idx, p in enumerate(capex_fields):
        # find the template parent item backing this field plan
        parent_item = next(
            (i for i in template.capex_items
             if i.child_code is None and i.item_id.endswith(p.parent_code) is False
             and i.parent_code == p.parent_code and i.child_code is None),
            None)
        # parent field items carry item_id f"capex.{field_name}"; rescale only
        # non-overridden PER_MW parents (generic templates)
        candidates = [i for i in template.capex_items
                      if i.child_code is None and i.parent_code == p.parent_code]
        if not candidates:
            continue
        parent_item = candidates[0]
        if (parent_item.item_id in overridden_item_ids
                or parent_item.scaling_basis is not ScalingBasis.PER_MW
                or parent_item.driver is not CostDriver.EUR_PER_MW):
            continue
        fr = fresh_capex.get(parent_item.item_id)
        if fr is not None and fr.resolved_amount_keur is not None:
            capex_fields[idx] = CapexFieldPlan(
                field_name=p.field_name, parent_code=p.parent_code, label=p.label,
                amount_keur=float(fr.resolved_amount_keur),
                y0_share=p.y0_share, spending_profile=p.spending_profile,
                asset_class=p.asset_class,
                useful_life_override=p.useful_life_override,
                is_depreciable=p.is_depreciable,
                # Correction D (defect 3A): latent value may rescale, the
                # project-owned applicability never flips to active.
                is_active=p.is_active,
            )

    capex_sub_lines = []
    for s in plan.capex_sub_lines:
        item_id = s.replay_metadata.get("cost_template_item_id")
        item = item_to_parent.get(item_id) if item_id else None
        # Applicability addendum (A12): an INACTIVE row keeps its inactive
        # state but its latent template-derived value still updates with
        # capacity, so reactivation at the new capacity resolves correctly;
        # it never enters the canonical subtotal while inactive. User
        # overrides remain authoritative and are never rescaled.
        if (item is None or item_id in overridden_item_ids
                or item.scaling_basis is not ScalingBasis.PER_MW
                or item.driver is not CostDriver.EUR_PER_MW):
            capex_sub_lines.append(s)
            continue
        fr = fresh_capex.get(item_id)
        if fr is None or fr.resolved_amount_keur is None:
            capex_sub_lines.append(s)
            continue
        capex_sub_lines.append(CapexSubLinePlan(
            parent_category_code=s.parent_category_code,
            business_code=s.business_code,
            label=s.label,
            amount_keur=float(fr.resolved_amount_keur),
            schedule_json=s.schedule_json,
            source=s.source,
            replay_metadata=s.replay_metadata,
            scalar_metadata=dict(s.scalar_metadata),
            is_active=s.is_active,
        ))

    opex_items = list(plan.opex_items)
    opex_item_by_id = {i.item_id: i for i in template.opex_items}
    for idx, p in enumerate(opex_items):
        parent_items = [i for i in template.opex_items
                        if i.child_code is None and i.label == p.name
                        and i.parent_code == p.parent_code]
        if not parent_items:
            continue
        parent_item = parent_items[0]
        if (parent_item.item_id in overridden_item_ids
                or parent_item.scaling_basis is not ScalingBasis.PER_MW
                or parent_item.driver is not CostDriver.EUR_PER_MW):
            continue
        fr = fresh_opex.get(parent_item.item_id)
        if fr is not None and fr.resolved_y1_amount_keur is not None:
            opex_items[idx] = OpexItemPlan(
                parent_code=p.parent_code,
                name=p.name,
                y1_amount_keur=float(fr.resolved_y1_amount_keur),
                annual_inflation=p.annual_inflation,
                step_changes=p.step_changes,
                percentage_of_opex=p.percentage_of_opex,
                # Correction D (defect 3A): latent rescale never reactivates.
                is_active=p.is_active,
            )

    opex_sub_lines = []
    for s in plan.opex_sub_lines:
        item_id = s.replay_metadata.get("cost_template_item_id")
        item = opex_item_by_id.get(item_id) if item_id else None
        if (item is None or item_id in overridden_item_ids
                or item.scaling_basis is not ScalingBasis.PER_MW
                or item.driver is not CostDriver.EUR_PER_MW):
            opex_sub_lines.append(s)
            continue
        fr = fresh_opex.get(item_id)
        if fr is None or fr.resolved_y1_amount_keur is None:
            opex_sub_lines.append(s)
            continue
        opex_sub_lines.append(OpexSubLinePlan(
            parent_group_code=s.parent_group_code,
            business_code=s.business_code,
            label=s.label,
            amount_keur=float(fr.resolved_y1_amount_keur),
            inflation_pct=s.inflation_pct,
            source=s.source,
            replay_metadata=s.replay_metadata,
            is_active=s.is_active,
        ))

    # Correction B (defect 4): RECONCILE canonical parents FROM THE FINAL
    # child set. Row-level scaling/override decisions happen first; the
    # parent amount is then recomputed as the sum of the FINAL ACTIVE
    # decomposition children — never scaled independently of them.
    #   CAPEX: key = canonical CapexStructure field (C.08/C.11 -> audit_legal).
    #   OPEX:  key = canonical OpexItem identity (replay canonical_key).
    from app.persistence.capex_sub_lines import CAPEX_CATEGORY_TO_FIELD

    field_key_by_category = dict(CAPEX_CATEGORY_TO_FIELD)
    final_capex_children: dict[str, float] = {}
    final_capex_present: set[str] = set()
    final_capex_active_child: dict[str, bool] = {}
    for s in capex_sub_lines:
        if not s.replay_metadata.get("replaces_parent"):
            continue
        field_key = field_key_by_category.get(s.parent_category_code)
        if not field_key:
            continue
        # Correction C (defect 4): presence is established by ANY
        # decomposition child; only ACTIVE children enter the sum. All
        # children OFF -> field amount 0.
        final_capex_present.add(field_key)
        # Correction D (defect 3B): parent applicability = ANY(active child).
        final_capex_active_child[field_key] = (
            final_capex_active_child.get(field_key, False) or s.is_active)
        if s.is_active:
            final_capex_children[field_key] = (
                final_capex_children.get(field_key, 0.0) + float(s.amount_keur))
    reconciled_capex_fields = []
    for pf in capex_fields:
        # the canonical field IS the reconciliation key (C.08/C.11 aliases
        # collapse into audit_legal before this lookup)
        children_key = pf.field_name
        if children_key in final_capex_present:
            reconciled_capex_fields.append(CapexFieldPlan(
                field_name=pf.field_name,
                parent_code=pf.parent_code,
                label=pf.label,
                # empty-active-set case (all children OFF) → 0
                amount_keur=final_capex_children.get(children_key, 0.0),
                y0_share=pf.y0_share,
                spending_profile=pf.spending_profile,
                asset_class=pf.asset_class,
                useful_life_override=pf.useful_life_override,
                is_depreciable=pf.is_depreciable,
                is_active=final_capex_active_child.get(children_key, False),
            ))
        else:
            reconciled_capex_fields.append(pf)

    final_opex_children: dict[str, float] = {}
    final_opex_present: set[str] = set()
    final_opex_active_child: dict[str, bool] = {}
    for s in opex_sub_lines:
        if not s.replay_metadata.get("replaces_parent"):
            continue
        key = s.replay_metadata.get("canonical_key")
        if not key:
            continue
        # Correction C (defect 4): presence vs active-sum, as for CAPEX.
        final_opex_present.add(key)
        # Correction D (defect 3B): parent applicability = ANY(active child).
        final_opex_active_child[key] = (
            final_opex_active_child.get(key, False) or s.is_active)
        if s.is_active:
            final_opex_children[key] = (
                final_opex_children.get(key, 0.0) + float(s.amount_keur))
    reconciled_opex_items = []
    for of_ in opex_items:
        # a parent OpexItem is reconciled when ANY of its decomposition
        # children names it as canonical parent (by exact item name)
        if of_.name in final_opex_present:
            reconciled_opex_items.append(OpexItemPlan(
                parent_code=of_.parent_code,
                name=of_.name,
                y1_amount_keur=final_opex_children.get(of_.name, 0.0),
                annual_inflation=of_.annual_inflation,
                step_changes=of_.step_changes,
                percentage_of_opex=of_.percentage_of_opex,
                is_active=final_opex_active_child.get(of_.name, False),
            ))
        else:
            reconciled_opex_items.append(of_)

    return MaterializationPlan(
        template_id=plan.template_id,
        template_version=plan.template_version,
        capex_fields=tuple(reconciled_capex_fields),
        capex_sub_lines=tuple(capex_sub_lines),
        opex_items=tuple(reconciled_opex_items),
        opex_sub_lines=tuple(opex_sub_lines),
        contingency=plan.contingency,
    )


def plan_to_project_state(
    plan: MaterializationPlan,
    *,
    capacity_mw: float,
    project_ref: str,
) -> "CostProjectState":
    """Rebuild a pure CostProjectState from a materialization plan (the
    roundtrip closure used by the Workflow 03 equivalence proofs). Field
    amounts, child rows, inflation, steps, schedules and contingency
    semantics round-trip verbatim."""
    from app.services.cost_template.client_extract import (
        CapexFieldState, CapexSubLineState, ContingencyState,
        CostProjectState, OpexItemState, OpexSubLineState,
    )

    capex_fields = tuple(
        CapexFieldState(
            field_name=p.field_name,
            parent_code=p.parent_code,
            label=p.label,
            amount_keur=p.amount_keur,
            y0_share=p.y0_share,
            spending_profile=tuple(p.spending_profile),
            asset_class=p.asset_class,
            useful_life_override=p.useful_life_override,
            is_depreciable=p.is_depreciable,
            # Correction D (defect 2): parent applicability round-trips.
            is_active=p.is_active,
        )
        for p in plan.capex_fields
    )
    capex_sub_lines = tuple(
        CapexSubLineState(
            parent_category_code=s.parent_category_code,
            business_code=s.business_code,
            label=s.label,
            amount_keur=s.amount_keur,
            schedule_json=s.schedule_json,
            # Correction A (defect 2): approved scalar metadata restored
            # losslessly (never hidden inside lineage fields).
            scalar_metadata=dict(s.scalar_metadata),
            source=s.source,
            is_active=s.is_active,
        )
        for s in plan.capex_sub_lines
    )
    opex_items = tuple(
        OpexItemState(
            name=p.name,
            parent_code=p.parent_code,
            y1_amount_keur=p.y1_amount_keur,
            annual_inflation=p.annual_inflation,
            step_changes=tuple(p.step_changes),
            percentage_of_opex=p.percentage_of_opex,
            is_active=p.is_active,
        )
        for p in plan.opex_items
    )
    opex_sub_lines = tuple(
        OpexSubLineState(
            parent_group_code=s.parent_group_code,
            business_code=s.business_code,
            label=s.label,
            amount_keur=s.amount_keur,
            inflation_pct=s.inflation_pct,
            source=s.source,
            is_active=s.is_active,
            # Correction B (defect 5): replacement provenance restored.
            canonical_parent_key=s.replay_metadata.get("canonical_key")
            if s.replay_metadata.get("replaces_parent") else None,
            reference_seed=bool(s.replay_metadata.get("reference_seed"))
            if s.replay_metadata.get("replaces_parent") else False,
        )
        for s in plan.opex_sub_lines
    )
    contingency = None
    if plan.contingency is not None:
        # Correction C (defect 1): applicability flags round-trip exactly —
        # inactive 6% must never come back as active 6%.
        contingency = ContingencyState(
            capex_pct=plan.contingency.capex_pct,
            opex_pct=plan.contingency.opex_pct,
            capex_active=plan.contingency.capex_active,
            opex_active=plan.contingency.opex_active,
            lineage=dict(plan.contingency.lineage),
        )
    return CostProjectState(
        capacity_mw=capacity_mw,
        project_ref=project_ref,
        capex_fields=capex_fields,
        opex_items=opex_items,
        capex_sub_lines=capex_sub_lines,
        opex_sub_lines=opex_sub_lines,
        contingency=contingency,
    )
