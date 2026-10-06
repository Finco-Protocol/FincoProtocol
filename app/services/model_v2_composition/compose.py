"""Model V2 canonical input composition (Workflow 05).

`compose_project_inputs` resolves the Model V2 selection state of a Working
Copy into ONE canonical ProjectInputs object for the existing engine:

  base ProjectInputs (system/technology/jurisdiction/template/project
  layers, already resolved by the existing authorities)
    + explicitly selected RevenuePlan        (Workflow 02 bridge)
    + explicitly selected CostTemplate plan  (Workflow 03 bridge)
    + scenario overrides                     (per-run context only)

Absent V2 selections the base inputs pass through untouched
(LEGACY_PASSTHROUGH) — legacy projects retain exact legacy economics and no
default V2 structure is invented.

Revenue bridge (fail-closed): only engine-expressible revenue structures
compose — a single PPA stream and merchant sales. CfD / FiT / premium /
indexed / auction streams have NO canonical ProjectInputs fields yet; a
plan containing them fails closed with REVENUE_PLAN_STREAM_UNSUPPORTED
rather than approximating economics. Merchant prices for the base
scenario are expanded through the EXISTING MerchantParams.price_at_year
authority for the project horizon — no new price mathematics.

Cost bridge (fail-closed): the Workflow 03 materialization plan (already
presence/active reconciled) replaces canonical CapexStructure field items
and OpexItem values. Sub-line persistence granules stay persistence-side;
field plans already reconcile decomposition (parent = sum of active
children). EUR_PER_MWH and other reserved drivers never reach this layer
(Workflow 03 fails them closed at contract time).

MISSING != ZERO: absent optional streams/plans are None; explicit 0.0
amounts are applied as intentional zeros.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import replace
from typing import Any, Optional

from app.services.model_v2_composition.contracts import (
    MODEL_V2_COMPOSITION_SCHEMA,
    CompositionDiagnostic,
    CompositionErrorCode,
    CompositionStatus,
    CostBridgeError,
    CostTemplateSelection,
    ModelV2CompositionContext,
    ModelV2CompositionResult,
    ModelV2WorkingState,
    RevenuePlanBridgeError,
    RevenuePlanSelection,
)


def _finite(value: Any, code: CompositionErrorCode, label: str) -> float:
    import math

    if not isinstance(value, (int, float)) or isinstance(value, bool) \
            or not math.isfinite(float(value)):
        raise RevenuePlanBridgeError(
            code, f"{label} must be finite, got {value!r}")
    return float(value)


def _revenue_params_from_plan(
    plan: Any,
    base_inputs: Any,
    diag: list[CompositionDiagnostic],
) -> Any:
    """Bridge a validated RevenuePlan onto the canonical RevenueParams
    fields the engine already reads. Engine-expressible structures only:
    one PPA stream + merchant sales. Everything else fails closed."""
    from domain.revenue.plan import (
        ContractRole,
        RevenueStreamType,
    )

    ppa_streams = [s for s in plan.ordered_streams()
                   if s.stream_type is RevenueStreamType.PPA and s.enabled]
    merchant_streams = [s for s in plan.ordered_streams()
                        if s.stream_type is RevenueStreamType.MERCHANT and s.enabled]
    unsupported = [
        s for s in plan.ordered_streams()
        if s.enabled and s.stream_type not in (
            RevenueStreamType.PPA, RevenueStreamType.MERCHANT)
    ]
    if unsupported:
        raise RevenuePlanBridgeError(
            CompositionErrorCode.REVENUE_PLAN_STREAM_UNSUPPORTED,
            "plan contains stream types the canonical ProjectInputs cannot "
            f"express yet: {sorted(s.stream_type.value for s in unsupported)}; "
            "composition refuses to approximate their economics"
        )
    if len(ppa_streams) > 1:
        raise RevenuePlanBridgeError(
            CompositionErrorCode.REVENUE_PLAN_STREAM_UNSUPPORTED,
            "the canonical RevenueParams authority expresses exactly one PPA; "
            f"the plan carries {len(ppa_streams)} enabled PPA streams"
        )

    revenue = base_inputs.revenue
    diag.append(CompositionDiagnostic(
        layer="revenue_plan",
        detail="resolved plan streams onto canonical RevenueParams fields",
        source_ref="domain.revenue.plan",
    ))

    if ppa_streams:
        ppa = ppa_streams[0].ppa
        revenue = replace(
            revenue,
            ppa_base_tariff=_finite(
                ppa.ppa_base_price_eur_mwh,
                CompositionErrorCode.REVENUE_PLAN_VALUE_NON_FINITE,
                "ppa_base_price_eur_mwh"),
            ppa_term_years=_finite(
                ppa.ppa_term_years if ppa.ppa_term_years > 0 else 0.0,
                CompositionErrorCode.REVENUE_PLAN_VALUE_NON_FINITE,
                "ppa_term_years"),
            ppa_index=_finite(
                ppa.ppa_price_index,
                CompositionErrorCode.REVENUE_PLAN_VALUE_NON_FINITE,
                "ppa_price_index"),
            ppa_production_share=_finite(
                ppa.ppa_volume_share,
                CompositionErrorCode.REVENUE_PLAN_VALUE_NON_FINITE,
                "ppa_volume_share"),
        )
        diag.append(CompositionDiagnostic(
            layer="revenue_plan",
            detail="PPA stream applied (base tariff / term / index / share)",
        ))

    if merchant_streams:
        merchant = merchant_streams[0].merchant
        # Existing authority: expand the merchant price path through
        # MerchantParams.price_at_year for the project horizon. Custom
        # curves are honored; a base scenario without any curve and without
        # a base price is a missing authority (fail closed).
        if merchant.price_scenario == "custom" and not merchant.custom_price_curve:
            raise RevenuePlanBridgeError(
                CompositionErrorCode.REVENUE_PLAN_MERCHANT_CURVE_MISSING,
                "merchant stream uses the custom scenario without a curve"
            )
        horizon = int(getattr(base_inputs.info, "horizon_years", 0) or 0)
        curve = tuple(
            float(merchant.price_at_year(year)) for year in range(1, horizon + 1)
        )
        if not curve or any(
            not isinstance(p, (int, float)) or p != p or p in (float("inf"), float("-inf"))
            for p in curve
        ):
            raise RevenuePlanBridgeError(
                CompositionErrorCode.REVENUE_PLAN_MERCHANT_CURVE_MISSING,
                "merchant price expansion produced no usable curve"
            )
        revenue = replace(
            revenue,
            market_prices_curve=curve,
            market_inflation=_finite(
                merchant.price_escalation_annual,
                CompositionErrorCode.REVENUE_PLAN_VALUE_NON_FINITE,
                "price_escalation_annual"),
        )
        diag.append(CompositionDiagnostic(
            layer="revenue_plan",
            detail="merchant stream applied (price curve from existing "
                   "price_at_year authority)",
        ))

    return revenue


def _capex_opex_from_cost_template(
    selection: CostTemplateSelection,
    base_inputs: Any,
    diag: list[CompositionDiagnostic],
) -> tuple[Any, Any]:
    """Apply a Workflow 03 materialization plan onto the canonical
    CapexStructure / OpexItem tuple (existing engine authorities)."""
    from finco_core.inputs import OpexItem

    plan = selection.materialization_plan
    capex = base_inputs.capex
    opex = base_inputs.opex

    field_by_category = {}
    from app.persistence.capex_sub_lines import CAPEX_CATEGORY_TO_FIELD
    for category_code, field_name in CAPEX_CATEGORY_TO_FIELD.items():
        field_by_category.setdefault(field_name, category_code)

    capex_updates: dict[str, Any] = {}
    for fp in plan.capex_fields:
        field_name = fp.field_name
        if not hasattr(capex, field_name):
            raise CostBridgeError(
                CompositionErrorCode.COST_TEMPLATE_VALUE_INVALID,
                f"materialization plan names unknown CapexStructure field "
                f"{field_name!r}"
            )
        from finco_core.inputs._models import CapexItem, AssetClass

        asset_class = None
        if fp.asset_class:
            try:
                asset_class = AssetClass(fp.asset_class)
            except ValueError:
                raise CostBridgeError(
                    CompositionErrorCode.COST_TEMPLATE_VALUE_INVALID,
                    f"unknown depreciation asset class {fp.asset_class!r}"
                )
        capex_updates[field_name] = CapexItem(
            name=fp.label,
            amount_keur=float(fp.amount_keur),
            y0_share=float(fp.y0_share or 0.0),
            spending_profile=tuple(float(s) for s in (fp.spending_profile or ())),
            asset_class=asset_class,
            useful_life_override=fp.useful_life_override,
            is_depreciable=bool(fp.is_depreciable),
        )
    if capex_updates:
        capex = replace(capex, **capex_updates)
        diag.append(CompositionDiagnostic(
            layer="cost_template",
            detail=f"applied {len(capex_updates)} canonical CAPEX field plans",
            source_ref=f"{selection.template_id} v{selection.version}",
        ))

    opex_items: list[Any] = []
    for op in plan.opex_items:
        steps = tuple((int(y), float(a)) for y, a in (op.step_changes or ()))
        opex_items.append(OpexItem(
            name=op.name,
            y1_amount_keur=float(op.y1_amount_keur),
            annual_inflation=float(op.annual_inflation),
            step_changes=steps,
            percentage_of_opex=float(op.percentage_of_opex or 0.0),
        ))
    if opex_items:
        opex = tuple(opex_items)
        diag.append(CompositionDiagnostic(
            layer="cost_template",
            detail=f"applied {len(opex_items)} canonical OPEX item plans",
            source_ref=f"{selection.template_id} v{selection.version}",
        ))

    return capex, opex


def _scenario_diagnostics(
    context: ModelV2CompositionContext,
) -> list[CompositionDiagnostic]:
    if not context.scenario_overrides:
        return []
    return [CompositionDiagnostic(
        layer="scenario",
        detail=f"scenario overrides present ({len(dict(context.scenario_overrides))} keys); "
               "applied per the existing scenario authority, never persisted "
               "back to the base Working Copy",
        source_ref=context.scenario_id or "",
    )]


def _composition_hash(
    state: ModelV2WorkingState,
    context: ModelV2CompositionContext,
) -> str:
    """Deterministic SHA-256 over economically authoritative V2 state:
    plan payload, cost template identity + payload, scenario overrides,
    schema marker. Presentation-only metadata is excluded."""
    payload: dict[str, Any] = {
        "_schema": MODEL_V2_COMPOSITION_SCHEMA,
        "working_copy_ref": state.working_copy_ref,
        "revenue_plan": None,
        "cost_template": None,
        "scenario": {
            "scenario_id": context.scenario_id,
            "overrides": json.loads(json.dumps(
                dict(context.scenario_overrides), sort_keys=True, default=str)),
        },
    }
    if state.revenue_plan_selection is not None:
        payload["revenue_plan"] = json.loads(
            state.selection_digest() and _selection_plan_json(
                state.revenue_plan_selection.plan))
    if state.cost_template_selection is not None:
        payload["cost_template"] = {
            "template_id": state.cost_template_selection.template_id,
            "version": state.cost_template_selection.version,
        }
    canonical = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _selection_plan_json(plan: Any) -> str:
    from dataclasses import asdict, is_dataclass
    from enum import Enum

    def enc(o: Any) -> Any:
        if is_dataclass(o) and not isinstance(o, type):
            return {k: enc(v) for k, v in asdict(o).items()}
        if isinstance(o, Enum):
            return o.value
        if isinstance(o, tuple):
            return [enc(v) for v in o]
        if isinstance(o, list):
            return [enc(v) for v in o]
        if isinstance(o, dict):
            return {k: enc(v) for k, v in o.items()}
        return o

    doc = {"streams": [enc(s) for s in plan.ordered_streams()],
           "allocation_groups": [enc(g) for g in plan.allocation_groups],
           "market_price": enc(plan.market_price)}
    return json.dumps(doc, sort_keys=True, ensure_ascii=True)


def compose_project_inputs(
    state: ModelV2WorkingState,
    context: ModelV2CompositionContext,
    base_inputs: Any,
) -> ModelV2CompositionResult:
    """Compose the canonical ProjectInputs for one run.

    Fail-closed: any bridge error raises (composition failure must never
    produce a Last Run input). Legacy passthrough: no V2 selections means
    the base inputs are returned unchanged with LEGACY_PASSTHROUGH status.
    """
    state.validate()
    context.validate()

    if state.revenue_plan_selection is None and state.cost_template_selection is None:
        return ModelV2CompositionResult(
            status=CompositionStatus.LEGACY_PASSTHROUGH,
            project_inputs=base_inputs,
            composition_hash=_composition_hash(state, context),
            working_state=state,
            context=context,
            diagnostics=(
                CompositionDiagnostic(
                    layer="base",
                    detail="no Model V2 selections; legacy economics pass "
                           "through untouched",
                ),
                *_scenario_diagnostics(context),
            ),
        )

    diag: list[CompositionDiagnostic] = [CompositionDiagnostic(
        layer="base",
        detail="canonical base ProjectInputs from the existing authorities",
    )]
    inputs = base_inputs

    if state.cost_template_selection is not None:
        selection = state.cost_template_selection
        try:
            capex, opex = _capex_opex_from_cost_template(selection, inputs, diag)
        except CostBridgeError:
            raise
        inputs = replace(inputs, capex=capex, opex=opex)

    revenue_plan = None
    if state.revenue_plan_selection is not None:
        selection = state.revenue_plan_selection
        revenue_plan = selection.plan
        try:
            revenue_plan.validate()
            revenue = _revenue_params_from_plan(revenue_plan, inputs, diag)
        except RevenuePlanBridgeError:
            raise
        inputs = replace(inputs, revenue=revenue)

    result_diag = tuple(diag) + tuple(_scenario_diagnostics(context))
    return ModelV2CompositionResult(
        status=CompositionStatus.COMPOSED,
        project_inputs=inputs,
        composition_hash=_composition_hash(state, context),
        working_state=state,
        context=context,
        revenue_plan=revenue_plan,
        cost_template_identity=(
            (state.cost_template_selection.template_id,
             state.cost_template_selection.version)
            if state.cost_template_selection is not None else None
        ),
        diagnostics=result_diag,
    )
