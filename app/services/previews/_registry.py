"""C2-PR29 — Preview Slice Registry.

Small in-process registry that maps a stable slice `name` to its
compute function and its `response_key` (the top-level JSON key it
populates in /model/preview's response body).

Three slices are registered today (in this exact, pinned order so
the response body's key insertion order is stable):

  1. operating  -> "operating"      (wrapped echo slices)
  2. debt       -> "debt"           (C2-PR24/25 backend-computed)
  3. tax        -> "tax"            (C2-PR30 backend stub)

The registry is intentionally NOT auto-discovery (`importlib` magic).
Every slice must be registered by an explicit `register(...)` call
in `app/services/model_preview.py` (the orchestration module) so
that:

  (a) the import order is unambiguous and traceable in code review,
  (b) tests can assert the exact set of registered slices,
  (c) a future module-rename accidentally missing one slice will
      cause a clear ImportError rather than a silent "missing
      preview" UX bug.

`run_all(context)` returns the merged response-body delta as a
dict, applying each registered slice in registration order. Slices
that return an empty dict (e.g. operating with no echo fields
present) contribute zero keys. The orchestrator (`build_preview_
response()`) merges this delta into the rest of the response body.

Forbidden: no I/O, no caching, no DB writes. Pure function of the
input `PreviewContext`. Verified by
tests/test_c2_pr28_30_tax_preview_stub.py::
TestRegistryPureAndDeterministic.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.services.preview_context import PreviewContext
from app.services.previews._base import (
    PreviewComputeFn,
    RegisteredPreview,
)
from app.services.previews import (
    operating_preview,
    debt_preview,
    tax_preview,
    irr_preview,
    dscr_preview,
)


# The registry is a plain module-level list (not a dict keyed by
# name) so the registration order is preserved exactly. This matters
# for byte-identical JSON byte-streams: dicts in Python 3.7+ preserve
# insertion order, and every /model/preview response we ship today
# relies on that ordering being stable.
_REGISTRY: List[RegisteredPreview] = []


def register(
    name: str,
    response_key: str,
    compute: PreviewComputeFn,
) -> RegisteredPreview:
    """Register a preview slice.

    `name` is a stable, human-readable identifier (must be unique).
    `response_key` is the JSON top-level key the slice's dict is
    placed under. `compute` is the actual `PreviewComputeFn`.

    Returns the newly-registered entry so callers can also hold a
    reference (useful for tests that need to introspect a slice).
    """
    entry = RegisteredPreview(
        name=name,
        response_key=response_key,
        compute=compute,
    )
    _REGISTRY.append(entry)
    return entry


def register_default_slices() -> None:
    """Register the five default slices, in their pinned order:

      1. operating  (echo x5 — special-cased in run_all)
      2. debt       (backend-owned, PR24/25/26/27)
      3. tax        (backend-owned, PR30 stub)
      4. irr        (backend-owned, PR31 stub)
      5. dscr       (backend-owned, PR32 stub)

    Called once by `model_preview.py` at module-import time. Idempotent
    — calling twice would append duplicates, so the orchestrator must
    not call it twice.
    """
    if _REGISTRY:
        # Already registered; do nothing. This makes the function
        # safe against test-module-import double-registration.
        return
    register(
        name="operating",
        response_key=operating_preview.CAPEX_KEY,  # placeholder; see note
        compute=operating_preview.compute,
    )
    # The "operating" slice's `response_key` is intentionally set to
    # the capex key as a placeholder because the operating slice
    # EXPANDS into multiple top-level keys via its own helper
    # (`expand_into_response_body`), not under a single
    # "operating" top-level key. The registry's `run_all()` only
    # applies slices whose `response_key` is a real top-level key.
    # The `operating` slice is special-cased in `run_all()` (and
    # is not iterated over).
    register(
        name="debt",
        response_key=debt_preview.DEBT_RESPONSE_KEY,
        compute=debt_preview.compute,
    )
    register(
        name="tax",
        response_key=tax_preview.TAX_RESPONSE_KEY,
        compute=tax_preview.compute,
    )
    # C2-PR31: IRR preview stub (backend-owned boundary).
    register(
        name="irr",
        response_key=irr_preview.IRR_RESPONSE_KEY,
        compute=irr_preview.compute,
    )
    # C2-PR32: DSCR preview stub (backend-owned boundary).
    register(
        name="dscr",
        response_key=dscr_preview.DSCR_RESPONSE_KEY,
        compute=dscr_preview.compute,
    )


def all_slices() -> List[RegisteredPreview]:
    """Return a snapshot of the current registry. Order-preserving.
    Used by tests to assert the exact registered set and order."""
    return list(_REGISTRY)


def run_all(context: PreviewContext) -> Dict[str, Any]:
    """Run every registered slice and merge results into one dict.

    The "operating" slice is special-cased: it expands into FIVE
    top-level keys via `operating_preview.expand_into_response_body`,
    not under a single "operating" top-level key. So we apply the
    operating slice's helper directly, then iterate over the
    remaining (debt, tax) slices and merge their single-key
    responses.

    This is a pure function of `context`. No I/O, no DB, no
    mutation of the registry.
    """
    out: Dict[str, Any] = {}
    # Step 1: operating slice (special-cased — expands into five keys).
    out.update(operating_preview.compute_operating_slice(context))
    # Step 2: every other registered slice. The registry iteration
    # order is the JSON key insertion order.
    for entry in _REGISTRY:
        if entry.name == "operating":
            continue  # already handled above
        out[entry.response_key] = entry.compute(context)
    return out


def reset_for_tests() -> None:
    """Test-only helper. Clears the registry so a test can register a
    custom set without polluting subsequent tests."""
    _REGISTRY.clear()


__all__ = [
    "register",
    "register_default_slices",
    "all_slices",
    "run_all",
    "reset_for_tests",
]