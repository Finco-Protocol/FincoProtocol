"""Model V2 composition contracts — canonical input composition.

Workflow 05 connects the already-reviewed Model V2 contracts (RevenuePlan
from Workflow 02, CostTemplate from Workflow 03) to the existing project /
runtime authority. HARD RULE: composition is ORCHESTRATION that resolves
inputs BEFORE engine execution; the existing FINCO engine remains the one
calculation authority. No shadow engine, no duplicated formulas.

Precedence contract (deterministic, outermost wins):

    SYSTEM/DEFAULT -> TECHNOLOGY -> MARKET/REVENUE CONTRACT ->
    JURISDICTION -> CLIENT TEMPLATE -> PROJECT WORKING COPY OVERRIDES ->
    SCENARIO OVERRIDES

Concretely in this composition layer:

  1. the canonical base ProjectInputs (already carrying system/technology/
     jurisdiction/template/project layers through the existing factories,
     reference-seed and working-copy authorities) is the starting point;
  2. an explicitly selected Model V2 RevenuePlan is applied over it
     (revenue bridge) — absent a plan, legacy economics pass through
     untouched;
  3. an explicitly selected CostTemplate materialization is applied over
     it (cost bridge) — absent a template, existing cost state passes
     through untouched;
  4. scenario overrides are CARRIED in the per-run composition context.
     Workflow 05 does not interpret or apply their financial mathematics;
     the downstream canonical scenario authority owns their application,
     and they never mutate the base Working Copy.

MISSING != ZERO: absent optional V2 state is `None`, never silently zero.
The canonical composition hash covers economically authoritative V2 state
only (revenue plan payload, the economic CostTemplate materialization
payload, carried scenario context, schema marker).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

MODEL_V2_COMPOSITION_SCHEMA = "finco-model-v2-composition-1"


class CompositionStatus(str, Enum):
    """Explicit status — composition failure must never masquerade as a
    successful run input."""

    COMPOSED = "composed"
    LEGACY_PASSTHROUGH = "legacy_passthrough"   # no V2 plan/template selected
    FAILED = "failed"


class CompositionErrorCode(str, Enum):
    """Stable failure codes for fail-closed composition."""

    REVENUE_PLAN_STREAM_UNSUPPORTED = "REVENUE_PLAN_STREAM_UNSUPPORTED"
    REVENUE_PLAN_INVALID = "REVENUE_PLAN_INVALID"
    REVENUE_PLAN_MERCHANT_CURVE_MISSING = "REVENUE_PLAN_MERCHANT_CURVE_MISSING"
    REVENUE_PLAN_VALUE_NON_FINITE = "REVENUE_PLAN_VALUE_NON_FINITE"
    COST_TEMPLATE_UNRESOLVED = "COST_TEMPLATE_UNRESOLVED"
    COST_TEMPLATE_DRIVER_UNSUPPORTED = "COST_TEMPLATE_DRIVER_UNSUPPORTED"
    COST_TEMPLATE_VALUE_INVALID = "COST_TEMPLATE_VALUE_INVALID"
    WORKING_STATE_INVALID = "WORKING_STATE_INVALID"
    SCENARIO_OVERRIDE_INVALID = "SCENARIO_OVERRIDE_INVALID"


class RevenuePlanBridgeError(ValueError):
    """Raised when a selected RevenuePlan cannot be composed into the
    canonical revenue inputs the engine understands (fail closed)."""

    def __init__(self, code: CompositionErrorCode, message: str):
        super().__init__(f"{code.value}: {message}")
        self.code = code


class CostBridgeError(ValueError):
    """Raised when a selected CostTemplate materialization cannot be
    composed into the canonical cost inputs (fail closed)."""

    def __init__(self, code: CompositionErrorCode, message: str):
        super().__init__(f"{code.value}: {message}")
        self.code = code


@dataclass(frozen=True)
class RevenuePlanSelection:
    """The project's explicit Model V2 revenue selection (immutable)."""

    plan: Any                      # domain.revenue.plan.RevenuePlan (typed, validated)
    source_ref: str = ""           # lineage: where this selection came from
    scenario_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.plan is None:
            raise ValueError(
                "REVENUE_PLAN_SELECTION_INVALID: plan is required; absence of a "
                "V2 selection is represented by omitting the selection, not by "
                "a None plan (MISSING != ZERO)"
            )
        # structural validation is delegated to the plan itself on compose


@dataclass(frozen=True)
class CostTemplateSelection:
    """The project's explicit Model V2 cost selection (immutable).

    ``template_id``/``version`` are the immutable CostTemplate identity.
    ``materialization_plan`` is the Workflow 03 materialization plan payload
    (already resolved/validated by the Workflow 03 authority).
    """

    template_id: str
    version: int
    materialization_plan: Any
    source_ref: str = ""

    def __post_init__(self) -> None:
        if not self.template_id or not str(self.template_id).strip():
            raise ValueError(
                "COST_TEMPLATE_SELECTION_INVALID: template_id is required"
            )
        if not isinstance(self.version, int) or isinstance(self.version, bool) \
                or self.version < 1:
            raise ValueError(
                f"COST_TEMPLATE_SELECTION_INVALID: version must be an integer "
                f">= 1, got {self.version!r}"
            )
        if self.materialization_plan is None:
            raise ValueError(
                "COST_TEMPLATE_SELECTION_INVALID: materialization_plan is "
                "required (MISSING != ZERO)"
            )


@dataclass(frozen=True)
class ModelV2WorkingState:
    """Immutable snapshot of the Model V2 selection state of a Working Copy.

    Everything here is economically authoritative composition input. Labels,
    presentation metadata and Last Run outputs deliberately have no place
    here. Scenario overrides ride on the composition context (per-run), not
    on the persistent Working Copy state.
    """

    working_copy_ref: str
    revenue_plan_selection: Optional[RevenuePlanSelection] = None
    cost_template_selection: Optional[CostTemplateSelection] = None
    schema: str = MODEL_V2_COMPOSITION_SCHEMA

    def validate(self) -> None:
        if not self.working_copy_ref or not str(self.working_copy_ref).strip():
            raise ValueError(
                "WORKING_STATE_INVALID: working_copy_ref is required"
            )
        if self.schema != MODEL_V2_COMPOSITION_SCHEMA:
            raise ValueError(
                f"WORKING_STATE_INVALID: schema {self.schema!r} is not "
                f"{MODEL_V2_COMPOSITION_SCHEMA!r}"
            )

    def selection_digest(self) -> str:
        """Deterministic digest of the economically authoritative V2
        selection state (revenue plan payload, economic cost composition
        payload, schema). Labels and non-economic metadata are excluded."""
        payload = {"_schema": self.schema, "working_copy_ref": self.working_copy_ref}
        if self.revenue_plan_selection is not None:
            from app.services.cost_template.serialize import cost_template_to_json  # noqa: F401
            from domain.revenue.plan_engine import evaluate_revenue_plan  # noqa: F401
            plan = self.revenue_plan_selection.plan
            payload["revenue_plan"] = json.loads(
                _plan_canonical_json(plan))
        if self.cost_template_selection is not None:
            payload["cost_template"] = economic_cost_payload(
                self.cost_template_selection)
        canonical = json.dumps(payload, sort_keys=True, indent=2,
                               ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _plan_canonical_json(plan: Any) -> str:
    """Canonical JSON for a RevenuePlan using the Workflow 02 authority."""
    from app.services.cost_template.serialize import cost_template_to_json  # noqa: F401

    from domain.revenue.plan import RevenuePlan
    from domain.revenue.plan_engine import evaluate_revenue_plan  # noqa: F401

    assert isinstance(plan, RevenuePlan)
    from domain.revenue.plan import RevenuePlan as _RP
    from dataclasses import asdict, is_dataclass

    def enc(o: Any) -> Any:
        if is_dataclass(o) and not isinstance(o, type):
            return {k: enc(v) for k, v in asdict(o).items()}
        from enum import Enum
        if isinstance(o, Enum):
            return o.value
        if isinstance(o, tuple):
            return [enc(v) for v in o]
        if isinstance(o, list):
            return [enc(v) for v in o]
        if isinstance(o, dict):
            return {k: enc(v) for k, v in o.items()}
        return o

    # ordered streams for stability
    doc = {"streams": [enc(s) for s in plan.ordered_streams()],
           "allocation_groups": [enc(g) for g in plan.allocation_groups],
           "market_price": enc(plan.market_price)}
    return json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=True)


def _econ_num(value: Any) -> Any:
    """Numeric normalisation for identity: 9000 and 9000.0 are the same
    economics. Non-numeric values (and bool) are kept verbatim so invalid
    input can never alias a valid number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return float(value)


def economic_cost_payload(selection: "CostTemplateSelection") -> dict[str, Any]:
    """Deterministic ECONOMIC payload of a CostTemplate selection
    (Correction B, defect B3).

    Binds exactly what the Workflow 05 cost bridge consumes to compose
    canonical economics: template identity; per CAPEX field the canonical
    field identity, amount, y0 share, spending profile, depreciation asset
    class, useful-life override, depreciable flag and applicability; per
    OPEX item the canonical OPEX identity (name), Y1 amount, inflation, step
    changes, percentage-of-OPEX and applicability; the configured
    contingency percentages and their active flags. Configured values of
    inactive rows stay bound (latent economics reactivate exactly).

    Excluded as non-economic for this composition: labels, parent codes,
    sub-line persistence granules, contingency lineage and the eligible
    basis metadata (the contingency authority derives its own basis).
    """
    plan = selection.materialization_plan
    contingency = getattr(plan, "contingency", None)
    return {
        "template_id": selection.template_id,
        "version": selection.version,
        "capex_fields": [
            {
                "field_name": fp.field_name,
                "amount_keur": _econ_num(fp.amount_keur),
                "y0_share": _econ_num(fp.y0_share),
                "spending_profile": [
                    _econ_num(v) for v in (fp.spending_profile or ())],
                "asset_class": fp.asset_class,
                "useful_life_override": fp.useful_life_override,
                "is_depreciable": fp.is_depreciable,
                "is_active": fp.is_active,
            }
            for fp in plan.capex_fields
        ],
        "opex_items": [
            {
                "name": op.name,
                "y1_amount_keur": _econ_num(op.y1_amount_keur),
                "annual_inflation": _econ_num(op.annual_inflation),
                "step_changes": [
                    [_econ_num(year), _econ_num(amount)]
                    for year, amount in (op.step_changes or ())],
                "percentage_of_opex": _econ_num(op.percentage_of_opex),
                "is_active": op.is_active,
            }
            for op in plan.opex_items
        ],
        "contingency": None if contingency is None else {
            "capex_pct": _econ_num(getattr(contingency, "capex_pct", None)),
            "opex_pct": _econ_num(getattr(contingency, "opex_pct", None)),
            "capex_active": getattr(contingency, "capex_active", None),
            "opex_active": getattr(contingency, "opex_active", None),
        },
    }


def _plan_payload(materialization_plan: Any) -> Any:
    """Canonical payload for a Workflow 03 MaterializationPlan (deterministic
    tree). Dataclasses are encoded field-by-field; plain objects (e.g. test
    doubles) are encoded via their public attributes; enums via value."""
    from dataclasses import is_dataclass, fields, asdict
    from enum import Enum
    import types as _types

    def enc(o: Any) -> Any:
        if is_dataclass(o) and not isinstance(o, type):
            return {f.name: enc(getattr(o, f.name)) for f in fields(o)}
        if isinstance(o, Enum):
            return o.value
        if isinstance(o, (_types.MappingProxyType,)):
            return {k: enc(v) for k, v in o.items()}
        if isinstance(o, dict):
            return {k: enc(v) for k, v in o.items()}
        if isinstance(o, (tuple, list)):
            return [enc(v) for v in o]
        if hasattr(o, "__dict__"):
            return {k: enc(v) for k, v in vars(o).items()}
        return o

    return enc(materialization_plan)


@dataclass(frozen=True)
class ModelV2CompositionContext:
    """Per-run composition context. Scenario overrides ride HERE — they are
    CARRIED for the downstream canonical scenario authority (composition
    neither interprets nor applies their mathematics) and never persist back
    into the base Working Copy state (scenario isolation)."""

    capacity_mw: float
    scenario_id: Optional[str] = None
    scenario_overrides: Mapping[str, Any] = field(default_factory=dict)
    # Optional pre-computed eligible CAPEX basis for the contingency
    # authority (delegated — the composition never computes contingency).
    eligible_capex_basis_keur: Optional[float] = None

    def __post_init__(self) -> None:
        import math

        if isinstance(self.capacity_mw, bool) \
                or not isinstance(self.capacity_mw, (int, float)) \
                or not math.isfinite(float(self.capacity_mw)) \
                or float(self.capacity_mw) <= 0:
            raise ValueError(
                f"COMPOSITION_CONTEXT_INVALID: capacity_mw must be a finite "
                f"number strictly greater than zero, got {self.capacity_mw!r}"
            )
        for key, value in dict(self.scenario_overrides).items():
            if not str(key).strip():
                raise ValueError(
                    "COMPOSITION_CONTEXT_INVALID: scenario override keys must "
                    "be non-empty"
                )

    def validate(self) -> None:
        """Explicit validation hook (composition calls this before any
        bridge runs); construction already enforces the same rules."""
        import math

        if isinstance(self.capacity_mw, bool) \
                or not isinstance(self.capacity_mw, (int, float)) \
                or not math.isfinite(float(self.capacity_mw)) \
                or float(self.capacity_mw) <= 0:
            raise ValueError(
                f"COMPOSITION_CONTEXT_INVALID: capacity_mw must be a finite "
                f"number strictly greater than zero, got {self.capacity_mw!r}"
            )


@dataclass(frozen=True)
class CompositionDiagnostic:
    """Which layer supplied what — provenance exposure required by the
    precedence contract."""

    layer: str          # "base" | "revenue_plan" | "cost_template" | "scenario"
    detail: str
    source_ref: str = ""


@dataclass(frozen=True)
class ModelV2CompositionResult:
    """Typed result of one composition. Contains composition decisions and
    provenance only — NEVER calculated financial outputs."""

    status: CompositionStatus
    project_inputs: Any                       # canonical ProjectInputs (engine authority)
    composition_hash: str                     # deterministic identity of V2 state
    working_state: ModelV2WorkingState
    context: ModelV2CompositionContext
    revenue_plan: Any = None                  # resolved RevenuePlan or None (legacy)
    cost_template_identity: Optional[tuple[str, int]] = None
    diagnostics: tuple[CompositionDiagnostic, ...] = ()
    failure_code: Optional[CompositionErrorCode] = None
    failure_message: str = ""

    @property
    def composed(self) -> bool:
        return self.status is not CompositionStatus.FAILED
