"""app.services.cost_template — Model V2 versioned cost template layer.

Pure domain/service foundation (Workflow 03): immutable versioned
CostTemplate envelopes with typed Capex/Opex template items, generic
Solar/Wind builders over the PUBLIC_GENERIC_DETAIL_V1 taxonomy, client
exact-snapshot extraction, deterministic resolution + materialization
planning into the existing FINCO cost authorities, and canonical JSON
serialization. No engine calls, no DB, no runtime wiring.
"""
from app.services.cost_template.contracts import (
    ACTIVE_CAPEX_DRIVERS,
    ACTIVE_OPEX_DRIVERS,
    DERIVED_CAPEX_PARENTS,
    EDITABLE_CAPEX_PARENTS,
    EDITABLE_OPEX_PARENTS,
    RESERVED_DRIVERS,
    CapexTemplateItem,
    CostDriver,
    CostTemplate,
    ItemClassification,
    OpexTemplateItem,
    ScalingBasis,
    TemplateKind,
    TemplateSource,
    TemplateStatus,
)
from app.services.cost_template.generic import build_generic_cost_template
from app.services.cost_template.client_extract import (
    CapexFieldState,
    CapexSubLineState,
    ContingencyState,
    CostProjectState,
    OpexItemState,
    OpexSubLineState,
    extract_client_cost_template,
)
from app.services.cost_template.materialize import (
    CapexFieldPlan,
    CapexSubLinePlan,
    ContingencyPlan,
    MaterializationContext,
    MaterializationPlan,
    OpexItemPlan,
    OpexSubLinePlan,
    ResolvedCostTemplate,
    build_materialization_plan,
    resolve_cost_template,
    rescale_materialization_plan,
    plan_to_project_state,
)
from app.services.cost_template.serialize import (
    cost_template_from_json,
    cost_template_to_json,
)

__all__ = [
    "ACTIVE_CAPEX_DRIVERS", "ACTIVE_OPEX_DRIVERS", "RESERVED_DRIVERS",
    "EDITABLE_CAPEX_PARENTS", "DERIVED_CAPEX_PARENTS", "EDITABLE_OPEX_PARENTS",
    "CostTemplate", "CapexTemplateItem", "OpexTemplateItem",
    "CostDriver", "ScalingBasis", "ItemClassification",
    "TemplateKind", "TemplateSource", "TemplateStatus",
    "build_generic_cost_template",
    "CostProjectState", "CapexFieldState", "OpexItemState",
    "CapexSubLineState", "OpexSubLineState", "ContingencyState",
    "extract_client_cost_template",
    "MaterializationContext", "ResolvedCostTemplate", "MaterializationPlan",
    "CapexFieldPlan", "CapexSubLinePlan", "OpexItemPlan", "OpexSubLinePlan",
    "ContingencyPlan", "resolve_cost_template", "build_materialization_plan",
    "rescale_materialization_plan", "plan_to_project_state",
    "cost_template_to_json", "cost_template_from_json",
]
