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
    *,
    technology: str = "solar",
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
    # Correction 05B: expressible stream types bridge through the
    # runtime-parity authority; genuinely unsupported overlays fail closed
    # with the documented seam-missing marker.
    unsupported = [
        s for s in plan.ordered_streams()
        if s.enabled and s.stream_type in (
            RevenueStreamType.CFD, RevenueStreamType.FIT_PREMIUM)
    ]
    if unsupported:
        raise RevenuePlanBridgeError(
            CompositionErrorCode.REVENUE_PLAN_STREAM_UNSUPPORTED,
            "plan contains overlay stream types (CfD settlement / premium "
            "support) with no additive field in the frozen core "
            f"RevenueParams: {sorted(s.stream_type.value for s in unsupported)}; "
            "composition refuses to approximate their economics"
        )
    if len(ppa_streams) > 1:
        raise RevenuePlanBridgeError(
            CompositionErrorCode.REVENUE_PLAN_STREAM_UNSUPPORTED,
            "the canonical RevenueParams authority expresses exactly one PPA; "
            f"the plan carries {len(ppa_streams)} enabled PPA streams"
        )

    revenue = base_inputs.revenue

    # Correction 05B: the runtime-parity authority bridges expressible
    # stream types onto existing canonical fields (per-operating-period
    # tariff schedule for delayed/expiring PPAs, explicit indexed FiT
    # factor schedules, auction fixed-tariff authority) and fails closed
    # on genuinely unsupported overlays (CfD / premium settlement seams
    # are documented frozen-core gaps, not approximated here).
    from app.services.model_v2_composition.runtime_parity import (
        bridge_plan_to_runtime_revenue, RevenueRuntimeSeamMissing,
    )
    try:
        runtime_overrides = bridge_plan_to_runtime_revenue(
            plan, base_inputs=base_inputs, technology=technology)
    except RevenueRuntimeSeamMissing as exc:
        raise RevenuePlanBridgeError(
            CompositionErrorCode.REVENUE_PLAN_STREAM_UNSUPPORTED,
            str(exc),
        )

    diag.append(CompositionDiagnostic(
        layer="revenue_plan",
        detail="resolved plan streams onto canonical RevenueParams fields "
               "via the runtime-parity authority",
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

    # Apply the runtime-parity bridge overrides LAST (they carry the
    # authoritative per-period tariff schedule and merchant curve).
    for field_name, value in runtime_overrides.items():
        revenue = replace(revenue, **{field_name: value})

    return revenue


def _finite_cost(value: Any, code: CompositionErrorCode, label: str) -> float:
    """Correction A (defect E): strict finite guard for economically
    relevant materialization values — NaN / +Inf / -Inf fail closed with a
    stable typed composition error; booleans are never numeric economics."""
    import math

    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(float(value)):
        raise CostBridgeError(
            code, f"{label} must be a finite number, got {value!r}")
    return float(value)


_ABSENT = object()


def _strict_bool(owner: Any, attr: str, label: str) -> bool:
    """Correction B (defect B1): applicability flags must be strict bool.
    Truthy/falsy look-alikes ("false", 1, 0, None) and absent attributes
    fail closed instead of being interpreted."""
    value = getattr(owner, attr, _ABSENT)
    if not isinstance(value, bool):
        raise CostBridgeError(
            CompositionErrorCode.COST_TEMPLATE_VALUE_INVALID,
            f"{label} must be a strict bool, got "
            f"{'<absent>' if value is _ABSENT else repr(value)}")
    return value


def _validated_contingency_pct(raw: Any, label: str) -> Optional[float]:
    """Correction B (defect B1): validate the configured contingency
    percentage in its ORIGINAL type through the existing contingency
    authority (bool / str / NaN / Inf / out-of-range are rejected). None
    means "no configured percentage" and is never invented."""
    if raw is None:
        return None
    from app.contingency_authority import validate_pct

    try:
        return validate_pct(raw)
    except ValueError as exc:
        raise CostBridgeError(
            CompositionErrorCode.COST_TEMPLATE_VALUE_INVALID,
            f"{label}: {exc}; got {raw!r}") from None


def _capex_opex_from_cost_template(
    selection: CostTemplateSelection,
    base_inputs: Any,
    diag: list[CompositionDiagnostic],
    *,
    context: ModelV2CompositionContext,
) -> tuple[Any, Any]:
    """Apply a Workflow 03 materialization plan onto the canonical
    CapexStructure / OpexItem tuple (existing engine authorities).

    Correction A (defect A): inactive plan rows contribute ZERO to the
    composed canonical economics while their latent configured values stay
    preserved in the plan (never mutated) — reactivation re-composes the
    exact stored economics from the authoritative plan.
    Correction A (defect B): plan.contingency is authoritative and applied
    through the EXISTING FINCO contingency authority (percentage
    validation, eligible basis, percentage-to-amount materialization);
    inactive contingency contributes zero while retaining the configured
    percentage in the plan; missing contingency never invents one.
    Correction A (defect E): every applied economic value is
    finite-validated before constructing canonical inputs.
    """
    from finco_core.inputs import OpexItem
    from finco_core.inputs._models import AssetClass, CapexItem
    from app.contingency_authority import (
        apply_capex_contingency, apply_opex_contingency,
    )

    plan = selection.materialization_plan

    # Correction B (defect B2): lineage identity must be PRESENT on the plan
    # and match the selection exactly. An absent plan identity never
    # defaults from the selection wrapper (fail closed).
    plan_template_id = getattr(plan, "template_id", _ABSENT)
    if not isinstance(plan_template_id, str) \
            or plan_template_id != selection.template_id:
        raise CostBridgeError(
            CompositionErrorCode.COST_TEMPLATE_UNRESOLVED,
            f"selection template_id {selection.template_id!r} does not match "
            f"the materialization plan identity "
            f"{'<absent>' if plan_template_id is _ABSENT else repr(plan_template_id)}"
        )
    plan_template_version = getattr(plan, "template_version", _ABSENT)
    if isinstance(plan_template_version, bool) \
            or not isinstance(plan_template_version, int) \
            or plan_template_version != selection.version:
        raise CostBridgeError(
            CompositionErrorCode.COST_TEMPLATE_UNRESOLVED,
            f"selection version {selection.version!r} does not match the "
            f"materialization plan version "
            f"{'<absent>' if plan_template_version is _ABSENT else repr(plan_template_version)}"
        )

    # Correction B (defect B1): validate the configured contingency BEFORE
    # any economics are composed, in the ORIGINAL types, even when the
    # contingency is inactive (latent economics must still be valid).
    contingency = plan.contingency
    capex_pct: Optional[float] = None
    opex_pct: Optional[float] = None
    capex_active = opex_active = True
    if contingency is not None:
        capex_pct = _validated_contingency_pct(
            getattr(contingency, "capex_pct", None), "contingency.capex_pct")
        opex_pct = _validated_contingency_pct(
            getattr(contingency, "opex_pct", None), "contingency.opex_pct")
        capex_active = _strict_bool(
            contingency, "capex_active", "contingency.capex_active")
        opex_active = _strict_bool(
            contingency, "opex_active", "contingency.opex_active")

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
        # Correction A (defect A): inactive field contributes ZERO; the
        # latent configured amount stays preserved in the plan only.
        if fp.is_active:
            amount = _finite_cost(
                fp.amount_keur,
                CompositionErrorCode.COST_TEMPLATE_VALUE_INVALID,
                f"CAPEX {field_name}.amount_keur")
            _finite_cost(fp.y0_share,
                         CompositionErrorCode.COST_TEMPLATE_VALUE_INVALID,
                         f"CAPEX {field_name}.y0_share")
            for i, share in enumerate(fp.spending_profile or ()):
                _finite_cost(share,
                             CompositionErrorCode.COST_TEMPLATE_VALUE_INVALID,
                             f"CAPEX {field_name}.spending_profile[{i}]")
        else:
            amount = 0.0
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
            amount_keur=amount,
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

    # Correction A (defect B): the plan contingency is authoritative and is
    # applied through the EXISTING FINCO contingency authority (percentage
    # validation, eligible basis, percentage-to-amount materialization).
    # INACTIVE contingency retains the configured percentage in the plan and
    # contributes zero here (explicit 0.0 application, not MISSING).
    if capex_pct is not None:
        capex = apply_capex_contingency(
            capex, capex_pct if capex_active else 0.0)
        diag.append(CompositionDiagnostic(
            layer="cost_template",
            detail=(
                "CAPEX contingency authority applied: "
                f"{capex_pct}% (active={capex_active})"),
            source_ref=f"{selection.template_id} v{selection.version}",
        ))

    opex_items: list[Any] = []
    for op in plan.opex_items:
        # Correction A (defect A): inactive OPEX contributes ZERO with
        # economics preserved in the plan.
        if op.is_active:
            y1 = _finite_cost(
                op.y1_amount_keur,
                CompositionErrorCode.COST_TEMPLATE_VALUE_INVALID,
                f"OPEX {op.name!r}.y1_amount_keur")
            inflation = _finite_cost(
                op.annual_inflation,
                CompositionErrorCode.COST_TEMPLATE_VALUE_INVALID,
                f"OPEX {op.name!r}.annual_inflation")
            steps = tuple(
                (int(step_year), _finite_cost(
                    step_amount,
                    CompositionErrorCode.COST_TEMPLATE_VALUE_INVALID,
                    f"OPEX {op.name!r}.step_changes[{step_year}]"))
                for step_year, step_amount in (op.step_changes or ()))
            pct = _finite_cost(
                op.percentage_of_opex,
                CompositionErrorCode.COST_TEMPLATE_VALUE_INVALID,
                f"OPEX {op.name!r}.percentage_of_opex") \
                if op.percentage_of_opex else 0.0
        else:
            y1, inflation, steps, pct = 0.0, 0.0, (), 0.0
        opex_items.append(OpexItem(
            name=op.name,
            y1_amount_keur=y1,
            annual_inflation=inflation,
            step_changes=steps,
            percentage_of_opex=pct,
        ))
    # Correction A (defect D): the Workflow 03 MaterializationPlan is NOT
    # contractually guaranteed to be a COMPLETE replacement of every
    # canonical OPEX item (client templates may be extracted from partial
    # states). Reconcile plan items onto the base OPEX tuple by the
    # canonical identity the existing fold uses (item name); base entries
    # the plan does not govern survive unchanged; no base entry is deleted
    # (MISSING must not become zero/deletion).
    reconciled: list[Any] = []
    plan_by_name: dict[str, Any] = {}
    for op in plan.opex_items:
        plan_by_name[op.name] = op
    applied = 0
    for existing in opex:
        op = plan_by_name.get(existing.name)
        if op is None:
            reconciled.append(existing)  # genuinely untouched base entry
            continue
        # Correction A (defect A): inactive OPEX contributes ZERO with
        # economics preserved in the plan.
        if op.is_active:
            y1 = _finite_cost(
                op.y1_amount_keur,
                CompositionErrorCode.COST_TEMPLATE_VALUE_INVALID,
                f"OPEX {op.name!r}.y1_amount_keur")
            inflation = _finite_cost(
                op.annual_inflation,
                CompositionErrorCode.COST_TEMPLATE_VALUE_INVALID,
                f"OPEX {op.name!r}.annual_inflation")
            steps = tuple(
                (int(step_year), _finite_cost(
                    step_amount,
                    CompositionErrorCode.COST_TEMPLATE_VALUE_INVALID,
                    f"OPEX {op.name!r}.step_changes[{step_year}]"))
                for step_year, step_amount in (op.step_changes or ()))
            pct = _finite_cost(
                op.percentage_of_opex,
                CompositionErrorCode.COST_TEMPLATE_VALUE_INVALID,
                f"OPEX {op.name!r}.percentage_of_opex") \
                if op.percentage_of_opex else 0.0
        else:
            y1, inflation, steps, pct = 0.0, 0.0, (), 0.0
        reconciled.append(OpexItem(
            name=existing.name,
            y1_amount_keur=y1,
            annual_inflation=inflation,
            step_changes=steps,
            percentage_of_opex=pct,
        ))
        applied += 1
    # NEW plan items the base tuple does not carry are appended (the
    # existing fold appends custom OPEX items the same way).
    for op in plan.opex_items:
        if op.name not in {e.name for e in reconciled}:
            if op.is_active:
                y1 = _finite_cost(
                    op.y1_amount_keur,
                    CompositionErrorCode.COST_TEMPLATE_VALUE_INVALID,
                    f"OPEX {op.name!r}.y1_amount_keur")
                inflation = _finite_cost(
                    op.annual_inflation,
                    CompositionErrorCode.COST_TEMPLATE_VALUE_INVALID,
                    f"OPEX {op.name!r}.annual_inflation")
                steps = tuple(
                    (int(step_year), _finite_cost(
                        step_amount,
                        CompositionErrorCode.COST_TEMPLATE_VALUE_INVALID,
                        f"OPEX {op.name!r}.step_changes[{step_year}]"))
                    for step_year, step_amount in (op.step_changes or ()))
                pct = _finite_cost(
                    op.percentage_of_opex,
                    CompositionErrorCode.COST_TEMPLATE_VALUE_INVALID,
                    f"OPEX {op.name!r}.percentage_of_opex") \
                    if op.percentage_of_opex else 0.0
            else:
                y1, inflation, steps, pct = 0.0, 0.0, (), 0.0
            reconciled.append(OpexItem(
                name=op.name,
                y1_amount_keur=y1,
                annual_inflation=inflation,
                step_changes=steps,
                percentage_of_opex=pct,
            ))
            applied += 1
    if applied:
        opex = tuple(reconciled)
        diag.append(CompositionDiagnostic(
            layer="cost_template",
            detail=f"reconciled {applied} canonical OPEX item plans onto the "
                   "base OPEX authority",
            source_ref=f"{selection.template_id} v{selection.version}",
        ))

    # Correction A (defect B): OPEX contingency authority (same boundaries).
    if opex_pct is not None:
        opex = apply_opex_contingency(
            opex, opex_pct if opex_active else 0.0)
        diag.append(CompositionDiagnostic(
            layer="cost_template",
            detail=(
                "OPEX contingency authority applied: "
                f"{opex_pct}% (active={opex_active})"),
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
               "carried for the downstream scenario authority, never "
               "persisted back to the base Working Copy",
        source_ref=context.scenario_id or "",
    )]


def _composition_hash(
    state: ModelV2WorkingState,
    context: ModelV2CompositionContext,
) -> str:
    """Deterministic SHA-256 over economically authoritative V2 state:
    revenue plan payload, the ECONOMIC cost composition payload (template
    identity + the values the cost bridge actually consumes), scenario
    context carried for the downstream authority, schema marker.
    Presentation-only metadata is excluded."""
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
        # Correction B (defect B3): bind the ECONOMIC cost composition
        # payload only (what Workflow 05 actually consumes); labels, parent
        # codes, sub-line granules, lineage and basis metadata are excluded.
        from app.services.model_v2_composition.contracts import (
            economic_cost_payload,
        )

        payload["cost_template"] = economic_cost_payload(
            state.cost_template_selection)
    canonical = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _selection_plan_json(plan: Any) -> str:
    from dataclasses import asdict, is_dataclass
    from enum import Enum

    # Documented non-economic RevenueStream fields (domain/revenue/plan.py):
    # contract presentation/taxonomy metadata excluded from the economic
    # identity hash — changing them must not change the composition hash.
    non_economic = frozenset({"counterparty", "lender_eligible"})

    def enc(o: Any) -> Any:
        if is_dataclass(o) and not isinstance(o, type):
            return {k: enc(v) for k, v in asdict(o).items()
                    if k not in non_economic}
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
    *,
    technology: str = "solar",
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
            capex, opex = _capex_opex_from_cost_template(
            selection, inputs, diag, context=context)
        except CostBridgeError:
            raise
        inputs = replace(inputs, capex=capex, opex=opex)

    revenue_plan = None
    if state.revenue_plan_selection is not None:
        selection = state.revenue_plan_selection
        revenue_plan = selection.plan
        try:
            revenue_plan.validate()
            revenue = _revenue_params_from_plan(
                revenue_plan, inputs, diag, technology=technology)
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
