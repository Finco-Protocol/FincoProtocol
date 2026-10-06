"""app.model_v2 — Model V2 foundation package.

Workflow 01 scope only: the disabled-by-default foundation flag, the
schema-version scaffolding marker, and the non-economic Stage/Perspective
project metadata contract. No V2 UI, no runtime financial path switch, no
Revenue/Cost/Template work — those arrive in later, independently reviewed
workflows.

Financial authority invariants are documented in
docs/model_v2/IMPLEMENTATION_GUARDRAILS.md.
"""
from app.model_v2.flags import (
    MODEL_V2_ENABLED_ENV,
    MODEL_V2_INPUT_SCHEMA_MARKER,
    model_v2_enabled,
)
from app.model_v2.project_metadata import (
    ModelPerspective,
    ProjectStage,
    normalize_perspective,
    normalize_stage,
    perspective_value,
    stage_value,
)

__all__ = [
    "MODEL_V2_ENABLED_ENV",
    "MODEL_V2_INPUT_SCHEMA_MARKER",
    "model_v2_enabled",
    "ProjectStage",
    "ModelPerspective",
    "normalize_stage",
    "normalize_perspective",
    "stage_value",
    "perspective_value",
]


# Workflow 04: read-only observability foundations (Assumption Register and
# Calculation Trace). Pure builders over canonical authorities; no engine,
# persistence or Workflow 02 RevenuePlan code is modified.
from app.model_v2.assumption_register import (  # noqa: E402,F401
    ASSUMPTION_REGISTER_SCHEMA_ID,
    ASSUMPTION_REGISTER_SCHEMA_VERSION,
    AssumptionContextKind,
    AssumptionEntry,
    AssumptionRegister,
    AssumptionSourceKind,
    ContingencyAuthorityRef,
    RegisterContext,
    RunIdentity,
    ValuePresence,
    build_assumption_register,
    canonical_json,
)
from app.model_v2.calculation_trace import (  # noqa: E402,F401
    CALCULATION_TRACE_SCHEMA_ID,
    CALCULATION_TRACE_SCHEMA_VERSION,
    CalculationTrace,
    TraceCompleteness,
    TraceEntry,
    build_calculation_trace,
)

__all__ = [
    *__all__,
    "ASSUMPTION_REGISTER_SCHEMA_ID",
    "ASSUMPTION_REGISTER_SCHEMA_VERSION",
    "AssumptionContextKind",
    "AssumptionEntry",
    "AssumptionRegister",
    "AssumptionSourceKind",
    "CALCULATION_TRACE_SCHEMA_ID",
    "CALCULATION_TRACE_SCHEMA_VERSION",
    "CalculationTrace",
    "ContingencyAuthorityRef",
    "RegisterContext",
    "RunIdentity",
    "TraceCompleteness",
    "TraceEntry",
    "ValuePresence",
    "build_assumption_register",
    "build_calculation_trace",
    "canonical_json",
]
