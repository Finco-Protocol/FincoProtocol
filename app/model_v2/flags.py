"""Model V2 foundation flag and schema-version scaffolding.

The flag follows the repository feature-flag convention (a FINCO_*_ENABLED
environment variable resolved against a fixed truthy set). It is OFF by
default: when the variable is unset, every production behaviour is identical
to the pre-V2 behaviour, and no V2 UI or runtime financial path is activated.

Schema-version scaffolding: canonical ProjectInputs serialization carries its
own ``_schema_version`` (finco_core.inputs.serialization). Later Model V2
input-migration work needs a stable marker of its own so legacy and V2
representations can be distinguished safely; it is declared here and wired
into actual migration logic only by later, individually reviewed workflows.
"""
from __future__ import annotations

import os

MODEL_V2_ENABLED_ENV = "FINCO_MODEL_V2_ENABLED"

_TRUTHY = frozenset({"1", "true", "yes", "on"})

# Marker for future V2 input-migration scaffolding. Legacy representations
# keep the canonical serialization version; V2 representations will carry this
# marker once a reviewed workflow introduces a V2 input contract.
MODEL_V2_INPUT_SCHEMA_MARKER = "model-v2-input-schema-1"


def model_v2_enabled() -> bool:
    """Resolve the Model V2 foundation flag. Default OFF."""
    return os.getenv(MODEL_V2_ENABLED_ENV, "0").strip().lower() in _TRUTHY
