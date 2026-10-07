"""app.services.model_v2_composition — Workflow 05 canonical input
composition and runtime bridge.

Connects the reviewed Model V2 contracts (RevenuePlan, CostTemplate) to
the existing project/runtime authority. Pure orchestration BEFORE engine
execution: the canonical ProjectInputs shape and the existing FINCO engine
remain the one calculation authority. No shadow engine, no duplicated
formulas, no persisted financial outputs in the composition contracts.
"""
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
from app.services.model_v2_composition.compose import compose_project_inputs

__all__ = [
    "MODEL_V2_COMPOSITION_SCHEMA",
    "CompositionDiagnostic",
    "CompositionErrorCode",
    "CompositionStatus",
    "CostBridgeError",
    "CostTemplateSelection",
    "ModelV2CompositionContext",
    "ModelV2CompositionResult",
    "ModelV2WorkingState",
    "RevenuePlanBridgeError",
    "RevenuePlanSelection",
    "compose_project_inputs",
]
