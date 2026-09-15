"""C2-PR28 — Shared immutable PreviewContext.

Single immutable bundle passed to every preview computation in
`app/services/previews/`. Replaces the previously inconsistent
`compute_debt_preview(body, project_record)` two-argument signature
and the implicit `body`-only argument for the five echo slices, with
one uniform typed object.

Contract (locked by tests/test_c2_pr28_30_preview_architecture_v2_*
and re-asserted by every per-preview test class):

  * Immutable: no setters; all fields set once at construction time.
  * No DB writes: PreviewContext is a pure value object, never used
    as a side-effect channel. The financial engine path
    (`domain/*`, `app/waterfall_core.py`, etc.) is forbidden from
    import in this module (proven by
    tests/test_c2_pr28_30_tax_preview_stub.py::
    TestPreviewContextNoForbiddenImports).
  * No caching: every PreviewContext is constructed fresh per
    request; the registry does NOT memoize results across requests.
  * No mutation of the underlying `preview_request` or `project_record`
    — they are stored as-is, and `baseline_snapshot` is the project's
    own dict reference. Preview computation functions MUST treat them
    as read-only.

Why immutable: this guarantees that two preview slices (e.g.
`debt_preview` and the future `tax_preview`) called from the same
`build_preview_response()` invocation see exactly the same input —
no chance of one slice's helper mutating shared state and silently
affecting the other slice's result. Pinning this in a frozen
dataclass with `eq=True` (the default for `@dataclass(frozen=True)`)
gives us value equality for free, which makes the byte-identical-
response assertions in the characterization tests much simpler.

Why one bundle (not one arg per slice): every preview slice that
exists today or is on the public roadmap needs SOME of: the saved
project's `baseline_snapshot`, the live (possibly-unsaved) preview
request payload, the project's project_code/project_id, the
authoritative currency, and the `ProjectRecord` itself for
authz/lookup consistency. Passing them individually creates a
growing signature surface area; passing the bundle is the smallest
contract change for every future slice (IRR / DSCR / waterfall).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class PreviewContext:
    """Immutable bundle of everything any preview computation may
    need.

    Fields:
      project_record:    the `ProjectRecord` resolved by the route's
                         existing `get_project_by_code()` authorization
                         call. May be `None` when the payload's
                         `project` field was null/absent — every
                         preview slice must treat `None` as a valid
                         "no project context" state and return a
                         `*-unavailable` shape in that case.
      baseline_snapshot: shortcut for
                         `project_record.baseline_snapshot` when
                         `project_record` is not None and has a
                         well-formed snapshot dict; `None` otherwise.
                         Storing this as a separate field keeps the
                         common case (`snapshot is a dict`) a single
                         attribute read instead of a chain of
                         `getattr`/`isinstance` checks inside every
                         preview slice.
      project_code:      the resolved project's `project_code` string,
                         or `None` when there is no project context.
                         Convenience field — preview slices that need
                         only an identifier should read this, not
                         reach back into `project_record`.
      project_id:        the resolved project's numeric `project_id`,
                         or `None` when there is no project context.
                         Convenience field mirroring `project_code`.
      currency:          the currency code every preview slice must
                         echo back. Always "EUR" today; centralised
                         here so a future multi-currency change has
                         exactly one place to update.
      preview_request:   the raw incoming request body dict
                         (possibly-unsaved frontend preview values).
                         Preview slices are forbidden from using this
                         for any calculation; it exists ONLY for the
                         five client-computed echo slices (capex/
                         revenue/opex/ebitda/operating_cash_flow) and
                         for future slices that genuinely need to
                         inspect what the frontend sent (e.g. for
                         "frontend changed X, server has nothing
                         equivalent" UX hints).

    Frozen by `@dataclass(frozen=True)` — attempting to mutate any
    field after construction raises `dataclasses.FrozenInstanceError`.
    """
    project_record: Optional[Any]
    baseline_snapshot: Optional[Mapping[str, Any]]
    project_code: Optional[str]
    project_id: Optional[int]
    currency: str
    preview_request: Mapping[str, Any]

    @staticmethod
    def build(
        preview_request: Mapping[str, Any],
        project_record: Optional[Any],
        currency: str = "EUR",
    ) -> "PreviewContext":
        """Factory: constructs a PreviewContext from the route's
        already-resolved `project_record` and the incoming request
        body. Centralises the `project_record.baseline_snapshot` /
        `project_id` / `project_code` extraction so every preview
        slice sees the same defensive shape.

        Always succeeds — never raises, even for completely missing
        or malformed project records. The returned context has
        `project_record=None` and the two snapshot fields set to
        `None` in that case, which every preview slice must handle
        as the "no project context" state.
        """
        snapshot: Optional[Mapping[str, Any]] = None
        project_code: Optional[str] = None
        project_id: Optional[int] = None
        if project_record is not None:
            raw_snapshot = getattr(project_record, "baseline_snapshot", None)
            if isinstance(raw_snapshot, dict):
                snapshot = raw_snapshot
            raw_code = getattr(project_record, "project_code", None)
            if isinstance(raw_code, str):
                project_code = raw_code
            raw_id = getattr(project_record, "project_id", None)
            if isinstance(raw_id, int) and not isinstance(raw_id, bool):
                project_id = raw_id
        # preview_request is always a dict in practice (the route
        # gates on validate_preview_payload first), but be defensive:
        # if not, pass an empty mapping so downstream preview slices
        # don't have to special-case it.
        if not isinstance(preview_request, Mapping):
            safe_request: Mapping[str, Any] = {}
        else:
            safe_request = preview_request
        return PreviewContext(
            project_record=project_record,
            baseline_snapshot=snapshot,
            project_code=project_code,
            project_id=project_id,
            currency=currency,
            preview_request=safe_request,
        )


__all__ = ["PreviewContext"]