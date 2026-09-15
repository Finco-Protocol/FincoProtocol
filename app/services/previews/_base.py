"""C2-PR29 — Preview Protocol.

Shared base for every preview-slice module in this package
(`operating_preview`, `debt_preview`, `tax_preview`, and the future
`irr_preview`/`dscr_preview`/`waterfall_preview` modules).

Contract every preview-slice module MUST honour:

  * `compute(context) -> dict[str, Any]`: returns the JSON-serialisable
    response slice for this preview. The registry guarantees the
    `context` is always a fully-populated `PreviewContext` (frozen
    dataclass) — no preview slice ever sees a `None` context.
  * `response_key`: the top-level key under which the slice's
    response is placed in the `/model/preview` JSON body (e.g.
    `"debt"`, `"tax"`). Pinned as a class attribute so the registry
    can list them deterministically without instantiating each slice.
  * NO DB writes. NO caching. NO engine calls. NO mutation of
    `context` (which is immutable anyway).

A preview slice is intentionally NOT a class — every existing helper
in `app/services/model_preview.py` is a free function, and forcing
classes here would be opportunistic refactoring. The protocol is a
plain Python protocol class for typing only; runtime registration
uses `register(name, compute_fn, response_key)` directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Protocol

from app.services.preview_context import PreviewContext


# A preview-slice compute function takes a PreviewContext and returns
# a JSON-serialisable dict. Always a dict — never None, never a
# scalar — so the registry can `setdefault(response_key, ...)` it
# into the parent response body uniformly.
PreviewComputeFn = Callable[[PreviewContext], Dict[str, Any]]


@dataclass(frozen=True)
class RegisteredPreview:
    """One entry in the preview-slice registry.

    Attributes:
      name:         a stable, human-readable identifier (e.g.
                    "operating", "debt", "tax"). Used by tests and
                    by the future /model/preview introspection hook
                    so debug payloads can list which slices ran.
      response_key: the JSON top-level key the slice's dict is
                    placed under in /model/preview's response body.
      compute:      the actual `PreviewComputeFn`. Always takes a
                    fully-populated PreviewContext.
    """
    name: str
    response_key: str
    compute: PreviewComputeFn


class PreviewSlice(Protocol):
    """Typing-only protocol for a preview slice. Real slices in this
    package are plain modules exposing `compute(context)` and
    `RESPONSE_KEY`; the protocol exists so static type-checkers can
    flag a module that forgets to expose either.

    Not used at runtime — the registry uses `register()` directly
    with concrete callables.
    """
    RESPONSE_KEY: str

    @staticmethod
    def compute(context: PreviewContext) -> Dict[str, Any]:
        ...


__all__ = [
    "PreviewComputeFn",
    "PreviewSlice",
    "RegisteredPreview",
]