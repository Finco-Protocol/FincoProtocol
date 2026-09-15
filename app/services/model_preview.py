"""Preview service — extracted from main_web.py for C2-PR23.

Holds the `/model/preview` route's validation/computation/echo logic,
moved out of `main_web.py` verbatim (no behaviour change — see
docs/C2_PR23_PREVIEW_SERVICE_BOUNDARY.md for the characterization-
test-then-refactor methodology used to prove this).

C2-PR28/29/30 evolves this module into orchestration-only:

  * Each preview slice lives in its own module under
    `app/services/previews/`, takes a `PreviewContext`, returns a
    JSON-serialisable dict.
  * This module constructs the `PreviewContext` and delegates to
    `app.services.previews._registry.run_all()` to merge slice
    outputs into the response body.
  * Validation stays here because it is a request-shape concern,
    not a per-slice concern.

The five operating-preview fields (capex/revenue/opex/ebitda/
operating_cash_flow) remain client-computed and merely echoed here —
see docs/C2_PR10_CAPEX_TOTAL_PREVIEW.md through
docs/C2_PR16_OPERATING_CF_PREVIEW.md for each field's own history.

C2-PR24/25/26/27 added the first BACKEND-COMPUTED preview field
here (the debt preview). C2-PR29 moved it into
`app.services.previews.debt_preview`; C2-PR30 added the tax preview
stub (`app.services.previews.tax_preview`). Neither this module nor
the engine ever mutates persistence. The financial engine
(`domain/*`, `app/waterfall_core.py`, `app/input_adapter.py`,
`app/project_factories.py`) is forbidden from import in any of
these modules — verified by
tests/test_c2_pr28_30_tax_preview_stub.py::
TestNoForbiddenImportsInAnyPreviewModule.
"""
from __future__ import annotations

from typing import Any, Optional

from app.services.preview_context import PreviewContext
from app.services.previews import _registry


# Eagerly register the default slices at module-import time so that
# `build_preview_response()` always sees the full registry. The
# `register_default_slices()` function is idempotent (no-op if
# already registered), so accidental re-imports are safe.
_registry.register_default_slices()


def sorted_unique_strings(value: Any) -> list[str]:
    """Defensive normalizer mirroring the original
    `_c2_pr7_sorted_unique_strings` helper: returns a sorted list of
    unique strings from `value` (tolerating non-list/non-string input
    by treating any non-conforming item as simply absent, never
    raising)."""
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item not in seen:
            seen.add(item)
            out.append(item)
    out.sort()
    return out


def validate_preview_payload(body: Any) -> tuple[bool, list[str]]:
    """Defensive, non-throwing shape-check mirroring
    ``FcRecalcPreview.validatePreviewPayload`` in
    ``static/modelling/recalc-preview.js``. Returns ``(ok, errors)``
    where ``errors`` is a list of human-readable validation problems
    (empty when ``ok`` is True). Tolerates missing/extra fields by
    treating any deviation from the expected shape as invalid rather
    than raising.
    """
    errors = []
    if not isinstance(body, dict):
        return False, ["request body must be a JSON object"]

    if not isinstance(body.get("valid"), bool):
        errors.append("'valid' must be a boolean")

    dirty_cells = body.get("dirtyCells")
    if not isinstance(dirty_cells, list) or not all(isinstance(v, str) for v in dirty_cells):
        errors.append("'dirtyCells' must be an array of strings")

    affected_groups = body.get("affectedGroups")
    if not isinstance(affected_groups, list) or not all(isinstance(v, str) for v in affected_groups):
        errors.append("'affectedGroups' must be an array of strings")

    if not isinstance(body.get("projectDirty"), bool):
        errors.append("'projectDirty' must be a boolean")

    if not isinstance(body.get("reason"), str):
        errors.append("'reason' must be a string")

    execution_status = body.get("executionStatus")
    if execution_status is not None and not isinstance(execution_status, str):
        errors.append("'executionStatus' must be a string or null")

    project = body.get("project")
    if project is not None and not isinstance(project, str):
        errors.append("'project' must be a string or null")

    # C2-PR10: capexTotalPreview is additive/optional. If present, it
    # must be null or a finite real number — never a string, never
    # NaN/Infinity. This field carries the CLIENT-computed sum of the
    # live (possibly-unsaved) CAPEX grid cell values; the server only
    # echoes it back (rounded) under the new "capex" response field,
    # it never recomputes or second-guesses it against persistence.
    if "capexTotalPreview" in body:
        capex_total_preview = body.get("capexTotalPreview")
        if capex_total_preview is not None and (
            isinstance(capex_total_preview, bool)
            or not isinstance(capex_total_preview, (int, float))
            or capex_total_preview != capex_total_preview  # NaN check
            or capex_total_preview in (float("inf"), float("-inf"))
        ):
            errors.append("'capexTotalPreview' must be a finite number or null")

    # C2-PR13: revenueTotalPreview is additive/optional, mirroring
    # capexTotalPreview's validation exactly.
    if "revenueTotalPreview" in body:
        revenue_total_preview = body.get("revenueTotalPreview")
        if revenue_total_preview is not None and (
            isinstance(revenue_total_preview, bool)
            or not isinstance(revenue_total_preview, (int, float))
            or revenue_total_preview != revenue_total_preview  # NaN check
            or revenue_total_preview in (float("inf"), float("-inf"))
        ):
            errors.append("'revenueTotalPreview' must be a finite number or null")

    # C2-PR14: opexTotalPreview is additive/optional, mirroring
    # capexTotalPreview/revenueTotalPreview's validation exactly.
    if "opexTotalPreview" in body:
        opex_total_preview = body.get("opexTotalPreview")
        if opex_total_preview is not None and (
            isinstance(opex_total_preview, bool)
            or not isinstance(opex_total_preview, (int, float))
            or opex_total_preview != opex_total_preview  # NaN check
            or opex_total_preview in (float("inf"), float("-inf"))
        ):
            errors.append("'opexTotalPreview' must be a finite number or null")

    # C2-PR15: ebitdaPreview is additive/optional.
    if "ebitdaPreview" in body:
        ebitda_preview = body.get("ebitdaPreview")
        if ebitda_preview is not None and (
            isinstance(ebitda_preview, bool)
            or not isinstance(ebitda_preview, (int, float))
            or ebitda_preview != ebitda_preview  # NaN check
            or ebitda_preview in (float("inf"), float("-inf"))
        ):
            errors.append("'ebitdaPreview' must be a finite number or null")

    # C2-PR16: operatingCashFlowPreview is additive/optional.
    if "operatingCashFlowPreview" in body:
        ocf_preview = body.get("operatingCashFlowPreview")
        if ocf_preview is not None and (
            isinstance(ocf_preview, bool)
            or not isinstance(ocf_preview, (int, float))
            or ocf_preview != ocf_preview  # NaN check
            or ocf_preview in (float("inf"), float("-inf"))
        ):
            errors.append("'operatingCashFlowPreview' must be a finite number or null")

    return (len(errors) == 0), errors


def _is_finite_number(value: Any) -> bool:
    """Re-exported helper for tests + direct callers. Mirrors the
    C2-PR25 helper of the same name; the canonical implementation
    now lives in `app.services.previews.debt_preview`."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value == value  # not NaN
        and value not in (float("inf"), float("-inf"))
    )


def _safe_float(value: Any) -> Optional[float]:
    """Re-exported helper for tests + direct callers. Mirrors the
    C2-PR25 helper of the same name; the canonical implementation
    now lives in `app.services.previews.debt_preview`."""
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


def compute_debt_preview(body: Any, project_record: Optional[Any]) -> dict[str, Any]:
    """Backward-compatibility shim re-exported for the C2-PR23/24/25
    test suite, which calls this two-argument function directly to
    unit-test the debt-preview slice.

    C2-PR29 moved the canonical implementation into
    `app.services.previews.debt_preview.compute_debt_slice()`; this
    thin wrapper exists only so the existing unit tests (PR24,
    PR25) keep working unchanged. New callers should construct a
    `PreviewContext` and use `compute_debt_slice()` directly.
    """
    # Lazy import to avoid a circular dependency at module-import time.
    from app.services.previews import debt_preview
    context = PreviewContext.build(
        preview_request=body if isinstance(body, dict) else {},
        project_record=project_record,
    )
    return debt_preview.compute_debt_slice(context)


def build_preview_response(body: dict[str, Any], project_record: Optional[Any]) -> dict[str, Any]:
    """Builds the full, valid-payload `/model/preview` JSON response
    body.

    Pre-C2-PR28/29/30 this function contained the echo logic for the
    five operating slices and the call to `compute_debt_preview()`
    inline. C2-PR29 moved that logic into `app.services.previews.*`
    and turned this function into a thin orchestrator:

      1. Build the request skeleton (`ok`, `status`, `executed`, etc.).
      2. Build a `PreviewContext` from `body` + `project_record`.
      3. Delegate to `_registry.run_all(context)` which produces the
         full slice-dict (operating, debt, tax, ...).
      4. Merge the slice-dict into the response body.

    The on-the-wire JSON byte stream is byte-identical to the
    C2-PR25/26/27 output, proven by
    tests/test_c2_pr28_30_preview_architecture_v2_characterization.py
    (re-run after this refactor; same set of assertions, same
    expected response).
    """
    dirty_cells = sorted_unique_strings(body.get("dirtyCells"))
    affected_groups = sorted_unique_strings(body.get("affectedGroups"))

    response_body: dict[str, Any] = {
        "ok": True,
        "status": "stubbed",
        "executed": False,
        "accepted": True,
        "affectedGroups": affected_groups,
        "dirtyCells": dirty_cells,
        "warnings": [],
        "message": "Preview endpoint contract accepted payload; recalculation is not implemented yet.",
        "overview": {
            "runtime_status": "Preview executed",
            "updated": True,
        },
    }

    context = PreviewContext.build(
        preview_request=body,
        project_record=project_record,
    )
    slice_delta = _registry.run_all(context)
    response_body.update(slice_delta)
    return response_body