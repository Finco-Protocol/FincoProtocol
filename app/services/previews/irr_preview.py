"""C2-PR31 — IRR Preview slice (STUB).

The first backend boundary for a future IRR (Internal Rate of
Return) preview. Mirrors the C2-PR24 debt-preview philosophy
(backend-only, no JS computation, no calculation) and the C2-PR30
tax-preview stub shape (always-unavailable with a stable 5-key
shape).

The function ALWAYS returns the `preview-unavailable` shape today.
A future PR that introduces the first real IRR computation will
replace the constant return value with a real computation that
still obeys the same contract — every key the renderer reads
(`status`, `basis`, `irr_preview`, `message`, `currency`) will
remain present, with the same meaning.

Explicitly NOT implemented (deliberately out of scope, matching
the brief's full out-of-scope list):
  * XIRR / IRR / MOIC calculation
  * Project IRR vs Equity IRR distinction
  * Equity cash-flow construction (sponsor / distribution waterfall)
  * Any read of `domain.*`, `app.waterfall_core`,
    `app.input_adapter`, `app.project_factories`
  * Any DB write or persistence migration
  * Any frontend JS computation

Forbidden imports verified by
tests/test_c2_pr31_33_irr_dscr_preview_final_qa.py::
TestNoForbiddenImportsInAnyPreviewModule.
"""
from __future__ import annotations

from typing import Any, Dict

from app.services.preview_context import PreviewContext


# Public response-key constant used by the registry.
IRR_RESPONSE_KEY = "irr"

# Stable message string used both in the JSON response and in the
# renderer's tooltip. Centralised so any future clarification only
# touches one place.
IRR_PREVIEW_UNAVAILABLE_MESSAGE = (
    "IRR preview is not yet available."
)


def compute_irr_slice(context: PreviewContext) -> Dict[str, Any]:
    """Compute the IRR preview slice from a PreviewContext.

    Today: always returns the `preview-unavailable` shape, regardless
    of what the context holds (saved inputs, project record,
    frontend preview values — none of these are read). The function
    signature still takes a `PreviewContext` so future IRR-preview
    implementations can read saved inputs uniformly with the debt
    slice without changing the registry.

    Field insertion order is preserved so JSON byte-stream output
    stays stable across runs (verified by
    tests/test_c2_pr31_33_irr_dscr_preview_final_qa.py::
    TestIrrPreviewUnavailableShape).
    """
    return {
        "status": "preview-unavailable",
        "basis": "saved-inputs-only",
        "irr_preview": None,
        "message": IRR_PREVIEW_UNAVAILABLE_MESSAGE,
        "currency": context.currency,
    }


def compute(context: PreviewContext) -> Dict[str, Any]:
    """Preview-slice entry point used by the registry."""
    return compute_irr_slice(context)


__all__ = [
    "IRR_RESPONSE_KEY",
    "IRR_PREVIEW_UNAVAILABLE_MESSAGE",
    "compute",
    "compute_irr_slice",
]