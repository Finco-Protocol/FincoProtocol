"""C2-PR29 — Operating Preview slice (extracted from model_preview.py).

Wraps the five existing client-computed echo slices (capex /
revenue / opex / ebitda / operating_cash_flow) under one named
"operating" preview slice whose response is a single dict with
those five sub-keys.

Pre-PR28/29/30, the same logic lived inline in
`build_preview_response()` in `app/services/model_preview.py`,
placed each of the five slices at the TOP LEVEL of the response
body (not nested under an "operating" key). To preserve
**byte-identical** wire compatibility with all existing consumers
(`static/modelling/runtime-renderer.js`, the export-endpoint safety
guardrails in tests/test_c2_pr22_*, the PR24/25 debt preview
characterizations, etc.), this module exposes TWO things:

  * `compute_operating_slice(context)` returns the NESTED dict
    (under response_key="operating") — used by the registry and by
    the new architecture documentation.

  * `expand_into_response_body(response_body, context)` mutates an
    ALREADY-CONSTRUCTED response body in place, placing the five
    slices at the SAME top-level keys they have always had. This
    is what `build_preview_response()` calls during the PR28/29/30
    refactor to keep the on-the-wire JSON byte-identical.

The two are kept side by side so the documentation (`docs/C2_PREVIEW_
ARCHITECTURE_V2.md`) can show the cleaner registry-driven flow
without forcing every downstream consumer to learn a new top-level
shape today.

Forbidden imports: `domain.*`, `app.waterfall_core`,
`app.input_adapter`, `app.project_factories`. Verified by
tests/test_c2_pr28_30_tax_preview_stub.py::
TestNoForbiddenImportsInAnyPreviewModule.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping

from app.services.preview_context import PreviewContext

# Response-key constants. Exported as module-level constants so the
# registry (and tests) can reference them by name without hardcoding
# string literals.
CAPEX_KEY = "capex"
REVENUE_KEY = "revenue"
OPEX_KEY = "opex"
EBITDA_KEY = "ebitda"
OPERATING_CASH_FLOW_KEY = "operating_cash_flow"


def _round_or_none(value: Any) -> Any:
    """Round a finite number to 2dp; pass through None. Mirrors the
    inline `round(float(body[X]), 2)` calls in the original
    `build_preview_response()`. Boolean inputs are explicitly
    rejected (validate_preview_payload already filters them)."""
    if value is None:
        return None
    return round(float(value), 2)


def compute_operating_slice(context: PreviewContext) -> Dict[str, Any]:
    """Build the NESTED operating-preview dict.

    Always returns a dict. If none of the five optional echo fields
    are present in the request, the returned dict is empty — the
    registry handles "absent means absent" semantics.
    """
    body = context.preview_request
    currency = context.currency
    out: Dict[str, Any] = {}

    if "capexTotalPreview" in body and body.get("capexTotalPreview") is not None:
        out[CAPEX_KEY] = {
            "capex_total_preview": _round_or_none(body["capexTotalPreview"]),
            "currency": currency,
        }

    if "revenueTotalPreview" in body and body.get("revenueTotalPreview") is not None:
        out[REVENUE_KEY] = {
            "preview": _round_or_none(body["revenueTotalPreview"]),
            "currency": currency,
        }

    if "opexTotalPreview" in body and body.get("opexTotalPreview") is not None:
        out[OPEX_KEY] = {
            "preview": _round_or_none(body["opexTotalPreview"]),
            "currency": currency,
        }

    if "ebitdaPreview" in body and body.get("ebitdaPreview") is not None:
        out[EBITDA_KEY] = {
            "preview": _round_or_none(body["ebitdaPreview"]),
            "currency": currency,
        }

    if "operatingCashFlowPreview" in body and body.get("operatingCashFlowPreview") is not None:
        out[OPERATING_CASH_FLOW_KEY] = {
            "preview": _round_or_none(body["operatingCashFlowPreview"]),
            "currency": currency,
        }

    return out


def expand_into_response_body(
    response_body: Dict[str, Any],
    context: PreviewContext,
) -> None:
    """Mutate `response_body` in place to add the five operating-
    preview echo slices at their existing top-level keys.

    `compute_operating_slice(context)` returns the same five sub-
    dicts nested under those exact same keys; we forward them
    directly. Side-effect-only and intentionally narrow — every
    other top-level key on `response_body` is left untouched.
    """
    nested = compute_operating_slice(context)
    for key, value in nested.items():
        response_body[key] = value


def compute(context: PreviewContext) -> Dict[str, Any]:
    """Preview-slice entry point used by the registry. Returns the
    nested operating slice (a dict of zero to five keys, depending
    on which optional echo fields are present in the request).

    Note: the registry has its own special-case for this slice —
    `run_all()` calls `compute_operating_slice()` directly rather
    than this function, so it can spread the result across multiple
    top-level keys. This `compute()` exists so the registry's
    per-slice contract is uniform across every slice module."""
    return compute_operating_slice(context)


__all__ = [
    "CAPEX_KEY",
    "REVENUE_KEY",
    "OPEX_KEY",
    "EBITDA_KEY",
    "OPERATING_CASH_FLOW_KEY",
    "compute_operating_slice",
    "expand_into_response_body",
]