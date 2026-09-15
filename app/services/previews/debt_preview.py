"""C2-PR29 — Debt Preview slice (extracted from model_preview.py).

Pure refactor: the formula (`saved_capex_total * saved_gearing_pct /
100.0`) and the 6-key response shape are byte-identical to the
C2-PR25/26/27 implementation. The only public change is the
function signature: it now takes a `PreviewContext` instead of
`(body, project_record)`.

The internal `_safe_float` / `_is_finite_number` helpers from
`app/services/model_preview.py` are duplicated here (NOT re-imported)
because the debt slice must be importable in isolation: a future
extraction that moves `model_preview.py` further (e.g. renames or
deprecates it) cannot leave this slice stranded. Both helpers are
tiny and tested independently by
tests/test_c2_pr28_30_tax_preview_stub.py::
TestDebtPreviewHelpersExportedAndPure.

Forbidden behaviour — pinned by tests, NOT by accidental design:
  * Never reads `context.preview_request` for any calculation. The
    frontend payload is irrelevant to debt sizing; the slice
    exists specifically to anchor on SAVED inputs.
  * Never calls `domain.*`, `app.waterfall_core`,
    `app.input_adapter`, `app.project_factories`.
  * Never writes to the DB.
  * Never caches results across requests.

Forbidden imports verified by
tests/test_c2_pr28_30_tax_preview_stub.py::
TestNoForbiddenImportsInAnyPreviewModule.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.preview_context import PreviewContext


# Public response-key constant used by the registry.
DEBT_RESPONSE_KEY = "debt"


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value == value  # not NaN
        and value not in (float("inf"), float("-inf"))
    )


def _safe_float(value: Any) -> Optional[float]:
    """Parses `value` as a finite float, tolerating the string-typed
    form-field convention used throughout `baseline_snapshot` (e.g.
    `"50000"`, `"50000.0"`). Returns None on anything unparseable,
    never raises."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = float(stripped)
        except ValueError:
            return None
        if parsed != parsed or parsed in (float("inf"), float("-inf")):
            return None
        return parsed
    return None


def compute_debt_slice(context: PreviewContext) -> Dict[str, Any]:
    """Compute the debt preview slice from a PreviewContext.

    The function NEVER reads `context.preview_request` — even though
    `body` is technically available on the context, we do not use
    it. (We read it here only to make the "no body input" property
    explicit and testable.)

    Returns the 6-key shape that the C2-PR25/26/27 series defined:

      preview-unavailable:
        status / senior_debt_preview / saved_total_capex /
        saved_gearing_pct / currency / basis (all three numeric
        fields are None)

      preview-ready:
        status='preview-ready' / senior_debt_preview / saved_total_capex /
        saved_gearing_pct / currency / basis

    Field insertion order is preserved so JSON byte-stream output
    stays stable across runs (verified by
    tests/test_c2_pr28_30_preview_architecture_v2_characterization.py::
    TestDebtPreviewSliceUnchanged).
    """
    unavailable = {
        "status": "preview-unavailable",
        "senior_debt_preview": None,
        "saved_total_capex": None,
        "saved_gearing_pct": None,
        "currency": context.currency,
        "basis": "saved-inputs-only",
    }

    snapshot = context.baseline_snapshot
    if not isinstance(snapshot, dict):
        return unavailable

    saved_capex_total = _safe_float(snapshot.get("total_capex_keur"))
    saved_gearing_pct = _safe_float(snapshot.get("gearing_pct"))

    if saved_capex_total is None or saved_gearing_pct is None:
        return unavailable
    if not _is_finite_number(saved_capex_total) or not _is_finite_number(saved_gearing_pct):
        return unavailable

    senior_debt_preview = round(saved_capex_total * (saved_gearing_pct / 100.0), 2)

    return {
        "status": "preview-ready",
        "senior_debt_preview": senior_debt_preview,
        "saved_total_capex": round(saved_capex_total, 2),
        "saved_gearing_pct": round(saved_gearing_pct, 2),
        "currency": context.currency,
        "basis": "saved-inputs-only",
    }


def compute(context: PreviewContext) -> Dict[str, Any]:
    """Preview-slice entry point used by the registry."""
    return compute_debt_slice(context)


__all__ = [
    "DEBT_RESPONSE_KEY",
    "compute",
    "compute_debt_slice",
    "_safe_float",
    "_is_finite_number",
]