"""C2-PR32 — DSCR Preview slice (STUB).

The first backend boundary for a future DSCR (Debt Service
Coverage Ratio) preview. Mirrors the C2-PR24 debt-preview
philosophy (backend-only, no JS computation, no calculation) and
the C2-PR30 tax-preview stub shape (always-unavailable with a
stable 5-key shape).

The function ALWAYS returns the `preview-unavailable` shape today.
A future PR that introduces the first real DSCR computation will
replace the constant return value with a real computation that
still obeys the same contract — every key the renderer reads
(`status`, `basis`, `dscr_preview`, `message`, `currency`) will
remain present, with the same meaning.

Explicitly NOT implemented (deliberately out of scope, matching
the brief's full out-of-scope list):
  * DSCR sizing / debt sizing of any kind
  * Debt service computation (interest + principal)
  * Debt sculpting
  * Coverage ratio calculation (min / avg / by-year)
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
DSCR_RESPONSE_KEY = "dscr"

# Stable message string used both in the JSON response and in the
# renderer's tooltip. Centralised so any future clarification only
# touches one place.
DSCR_PREVIEW_UNAVAILABLE_MESSAGE = (
    "DSCR preview is not yet available."
)


def compute_dscr_slice(context: PreviewContext) -> Dict[str, Any]:
    """Compute the DSCR preview slice from a PreviewContext.

    Today: always returns the `preview-unavailable` shape, regardless
    of what the context holds (saved inputs, project record,
    frontend preview values — none of these are read). The function
    signature still takes a `PreviewContext` so future DSCR-preview
    implementations can read saved inputs uniformly with the debt
    slice without changing the registry.

    Field insertion order is preserved so JSON byte-stream output
    stays stable across runs (verified by
    tests/test_c2_pr31_33_irr_dscr_preview_final_qa.py::
    TestDscrPreviewUnavailableShape).
    """
    return {
        "status": "preview-unavailable",
        "basis": "saved-inputs-only",
        "dscr_preview": None,
        "message": DSCR_PREVIEW_UNAVAILABLE_MESSAGE,
        "currency": context.currency,
    }


def compute(context: PreviewContext) -> Dict[str, Any]:
    """Preview-slice entry point used by the registry."""
    return compute_dscr_slice(context)


__all__ = [
    "DSCR_RESPONSE_KEY",
    "DSCR_PREVIEW_UNAVAILABLE_MESSAGE",
    "compute",
    "compute_dscr_slice",
]