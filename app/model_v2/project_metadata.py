"""Model V2 project metadata — Stage and Perspective.

NON-ECONOMIC METADATA ONLY.

Project Stage and Model Perspective are product/workflow metadata that live at
the PROJECT level (project records, workspace presentation). They must never:

  - alter ProjectInputs financial assumptions;
  - change production, revenue, tax, debt, reserves, returns or statements;
  - create hidden stage-dependent financial defaults;
  - enter any engine input fingerprint or run hash.

Existing projects carry no Stage/Perspective; the persisted state is nullable
and unset values are never inferred. A technical NULL at the persistence
boundary represents "not set" — no sentinel value is added to the canonical
business vocabularies.

Roadmap perspectives (Acquirer, Lender) are intentionally NOT members of the
active vocabulary. Raw values are stored as TEXT, so introducing them later
requires only a reviewed vocabulary change — no migration.
"""
from __future__ import annotations

from enum import Enum


class ProjectStage(str, Enum):
    """Canonical project lifecycle stage vocabulary (metadata only)."""

    SCREENING = "screening"
    DEVELOPMENT = "development"
    READY_TO_BUILD = "ready_to_build"
    FINANCING = "financing"
    CONSTRUCTION = "construction"
    OPERATING = "operating"
    EXITED = "exited"


class ModelPerspective(str, Enum):
    """Canonical Model V2 perspectives (presentation metadata only)."""

    DEVELOPER = "developer"
    IPP = "ipp"


def _canonical_raw_value(raw: object) -> str:
    """Extract the canonical candidate string from a raw input value.

    Canonical enum members pass through their value; any other Enum instance
    is NOT silently coerced (its str() form would be meaningless here) and
    fails closed like any unrelated object.
    """
    if isinstance(raw, (ProjectStage, ModelPerspective)):
        return raw.value
    if isinstance(raw, Enum):
        raise ValueError("metadata value is a non-canonical enum instance")
    return str(raw).strip().lower()


def normalize_stage(raw: object) -> ProjectStage | None:
    """Normalize a persisted raw stage value.

    None passes through (unset); a canonical value is accepted as a canonical
    string (case-insensitive) or as the canonical enum object itself;
    anything else fails closed with ValueError — no guessed or silent
    defaults, no coercion of unrelated strings or enum types.
    """
    if raw is None:
        return None
    try:
        return ProjectStage(_canonical_raw_value(raw))
    except ValueError:
        raise ValueError(
            f"PROJECT_STAGE_INVALID: {raw!r} is not a canonical ProjectStage value. "
            f"Supported: {[s.value for s in ProjectStage]}"
        ) from None


def normalize_perspective(raw: object) -> ModelPerspective | None:
    """Normalize a persisted raw perspective value (same contract as stage)."""
    if raw is None:
        return None
    try:
        return ModelPerspective(_canonical_raw_value(raw))
    except ValueError:
        raise ValueError(
            f"MODEL_PERSPECTIVE_INVALID: {raw!r} is not a canonical ModelPerspective value. "
            f"Supported: {[p.value for p in ModelPerspective]}"
        ) from None


def stage_value(raw: object) -> str | None:
    """Persisted TEXT form of a stage (None stays None)."""
    stage = normalize_stage(raw)
    return stage.value if stage is not None else None


def perspective_value(raw: object) -> str | None:
    """Persisted TEXT form of a perspective (None stays None)."""
    perspective = normalize_perspective(raw)
    return perspective.value if perspective is not None else None
