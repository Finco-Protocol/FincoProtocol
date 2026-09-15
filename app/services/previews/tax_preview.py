"""C2-PR30 — Tax Preview slice (STUB).

The first backend boundary for a future Tax preview. Mirrors the
C2-PR24 debt-preview philosophy: backend-only, no JS computation,
no tax calculation, no engine call.

The function ALWAYS returns the `preview-unavailable` shape today.
A future PR that introduces the first real tax preview calculation
will replace the constant return value with a real computation
that still obeys the same contract — every key the renderer reads
(`status`, `basis`, `tax_preview`, `message`, `currency`) will
remain present, with the same meaning.

Explicitly NOT implemented (deliberately out of scope, matching
the brief's full out-of-scope list):
  * Corporate Income Tax (CIT) calculation
  * Loss carryforward logic
  * Deferred tax
  * Tax shield of any kind
  * Withholding Tax (WHT)
  * Pillar II / Global Minimum Tax
  * Any read of `domain.*`, `app.waterfall_core`,
    `app.input_adapter`, `app.project_factories`
  * Any DB write or persistence migration
  * Any frontend JS computation

Forbidden imports verified by
tests/test_c2_pr28_30_tax_preview_stub.py::
TestNoForbiddenImportsInAnyPreviewModule.
"""
from __future__ import annotations

from typing import Any, Dict

from app.services.preview_context import PreviewContext


# Public response-key constant used by the registry.
TAX_RESPONSE_KEY = "tax"

# Stable message string used both in the JSON response and in the
# renderer's tooltip. Centralised so any future clarification only
# touches one place.
TAX_PREVIEW_UNAVAILABLE_MESSAGE = (
    "Tax preview is not yet available."
)


def compute_tax_slice(context: PreviewContext) -> Dict[str, Any]:
    """Compute the tax preview slice from a PreviewContext.

    Today: always returns the `preview-unavailable` shape, regardless
    of what the context holds (saved inputs, project record,
    frontend preview values — none of these are read). The function
    signature still takes a `PreviewContext` so future tax-preview
    implementations can read saved inputs uniformly with the debt
    slice without changing the registry.

    Field insertion order is preserved so JSON byte-stream output
    stays stable across runs (verified by
    tests/test_c2_pr28_30_tax_preview_stub.py::
    TestTaxPreviewUnavailableShape).
    """
    return {
        "status": "preview-unavailable",
        "basis": "saved-inputs-only",
        "tax_preview": None,
        "message": TAX_PREVIEW_UNAVAILABLE_MESSAGE,
        "currency": context.currency,
    }


def compute(context: PreviewContext) -> Dict[str, Any]:
    """Preview-slice entry point used by the registry."""
    return compute_tax_slice(context)


__all__ = [
    "TAX_RESPONSE_KEY",
    "TAX_PREVIEW_UNAVAILABLE_MESSAGE",
    "compute",
    "compute_tax_slice",
]