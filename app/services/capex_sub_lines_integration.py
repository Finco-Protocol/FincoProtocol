"""Phase 57A-9D — Run / materialization integration for
persisted CAPEX user-added sub-lines.

This module sits between the persistence layer
(``app.persistence.capex_sub_lines``) and the model layer
(``domain.inputs.CapexStructure``). Its single public
function, ``_apply_user_sub_lines_to_capex``, is the
canonical wire-up that the /run route calls in the
user-created path.

The 57A-9A design gate (PR #505) prescribes that user
sub-lines fold into the existing 15 named
``CapexItem.amount_keur`` fields via the locked
``CAPEX_CATEGORY_TO_FIELD`` mapping, with the scenario's
reserved-key overrides (``_capex_sub_line_overrides``)
applying on top. This module implements that wire-up
**without** touching the model formula path, the Excel
export, the UI, or the financial engine internals. It is
a pure materialization step on the model INPUT side: the
``CapexStructure`` is the input to the model, not the
output.

Hard rules (Phase 57A-9A design + 57A-9B Claude delta
review fix):

  - Factory projects (Generic Wind Reference/Generic Solar Reference/Generic Solar/Generic
    Wind) have no user sub-lines. The helper returns the
    input ``capex`` unchanged. This is the Generic Wind Reference/Generic Solar Reference
    parity guarantee.
  - User projects load active sub-lines from the
    ``capex_sub_lines`` table, keyed by ``project_id``.
    Soft-deleted rows are excluded.
  - Scenario override amount REPLACES project default
    amount (NOT a delta adjustment). This is the
    57A-9B Claude delta review fix, pinned by
    ``resolve_effective_sub_line_amount``.
  - Unknown ``sub_line_id`` overrides are ignored — the
    helper does not raise on stale override UUIDs. (A
    warning is logged so reviewers can see it, but the
    Run does not crash.)
  - Unknown parent categories raise ``ValueError``
    loudly. This is fail-fast: an unknown category
    would silently drop data, which the design gate
    explicitly forbids.
  - C.17 / C.18 are rejected at validation time (the
    57A-9B ``validate_parent_category`` helper). This
    module never receives them.
  - The 57A-8 in-memory preview rows (TMP markers) are
    NEVER loaded from the table — they are not persisted.
    This module only reads rows from
    ``capex_sub_lines``, which is the persisted table.

Type: runtime model-input integration, DRAFT PR (57A-9D).
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from app.persistence.capex_sub_lines import (
    CapexSubLine,
    fold_sub_lines_into_capex,
    get_active_sub_lines_for_project,
)


logger = logging.getLogger(__name__)


# Reserved scenario-override keys (57A-9A design, 57A-9C
# wire-up). When a scenario carries a sub-line override
# map under these keys, the helper applies it on top of
# the persisted default.
_RESERVED_SUB_LINE_OVERRIDES_KEY = "_capex_sub_line_overrides"


class SubLineOverrideNonFiniteError(ValueError):
    """A historical CAPEX sub-line override carries a non-finite amount.

    Raised by ``_extract_sub_line_overrides`` when a persisted override map
    contains NaN / +Inf / -Inf for any sub-line.  The caller must surface this
    as an explicit error rather than silently using the malformed value as model
    economics.
    """


def _extract_sub_line_overrides(
    scenario_overrides: Optional[Mapping[str, Any]],
) -> dict:
    """Extract the per-scenario sub-line override map.

    The reserved key is consulted first. If the scenario
    carries a non-dict value at the reserved key (a
    malformed / hand-edited record), the helper falls
    back to an empty map — this is the same fail-soft
    behavior the 57A-9C silent-drop rule gives to
    unknown keys, applied to the reserved surface.

    R3/F05 — Defense in depth: any non-finite amount value in the persisted map
    raises ``SubLineOverrideNonFiniteError``.  This prevents historical malformed
    data from silently becoming model economics.  Callers (Run path, display path)
    must catch and surface an explicit error.

    Returns:
        A ``{sub_line_id: amount_keur}`` dict. Empty if
        the scenario is the Base case (no overrides), or
        if the reserved key is missing / malformed.

    Raises:
        SubLineOverrideNonFiniteError: if any override amount is non-finite.
    """
    if not scenario_overrides:
        return {}
    raw = scenario_overrides.get(_RESERVED_SUB_LINE_OVERRIDES_KEY)
    if isinstance(raw, dict):
        extracted = dict(raw)
        # Defense-in-depth: check all amounts for finiteness.
        # A persisted NaN/Inf must not silently reach CapexStructure.
        import math
        for sub_line_id, amount in extracted.items():
            try:
                v = float(amount)
            except (TypeError, ValueError):
                raise SubLineOverrideNonFiniteError(
                    f"CAPEX scenario override for sub_line {sub_line_id!r} "
                    f"is not a number ({amount!r}); cannot use as model economics."
                )
            if not math.isfinite(v):
                raise SubLineOverrideNonFiniteError(
                    f"CAPEX scenario override for sub_line {sub_line_id!r} "
                    f"is non-finite ({amount!r}); cannot use as model economics."
                )
        return extracted
    if raw is not None:
        logger.warning(
            "scenario_overrides[%r] is not a dict (%s); "
            "ignoring sub-line override map",
            _RESERVED_SUB_LINE_OVERRIDES_KEY,
            type(raw).__name__,
        )
    return {}


def _load_active_sub_lines(project_id: str) -> tuple[CapexSubLine, ...]:
    """Load active (is_active=1) sub-lines for a project.

    Delegates to the persistence layer's
    ``get_active_sub_lines_for_project`` helper, which
    uses the canonical ``get_cursor()`` context manager
    (Phase 53 persistence architecture). This guarantees:

    - One authoritative DB path source (``db.DB_PATH``
      / ``FINCO_DB_PATH`` env). No manual
      ``Path(__file__).parents[N]`` computation here.
    - Service runtime and persistence runtime stay
      aligned: if a future deployment overrides the DB
      path (env var, config, multi-tenant shim), the
      Run path sees the same DB the persistence layer
      does. No hidden divergence.
    - No hidden bug from a future refactor that moves
      the helper module (the manual path-relative
      construction was fragile to repo-relative path
      changes).

    Returns:
        A tuple of ``CapexSubLine`` records ordered by
        ``(parent_category_code ASC, display_order ASC)``
        — the canonical render order. Empty if the
        project has no persisted sub-lines, or if the
        project does not exist in the DB.

    Notes:
        Soft-deleted rows (is_active=0) are excluded.
        The audit / replay trail remains in the table;
        this helper just does not surface them.
    """
    # get_active_sub_lines_for_project opens a cursor via
    # get_cursor(), runs list_sub_lines_for_project with
    # include_inactive=False, and returns a list. We
    # coerce to tuple to preserve the prior return shape
    # (the integration helper treats this as an
    # immutable sequence — see the empty-tuple early
    # return above).
    rows = get_active_sub_lines_for_project(project_id)
    return tuple(rows)


def _apply_user_sub_lines_to_capex(
    capex: Any,
    *,
    project_id: str,
    scenario_overrides: Optional[Mapping[str, Any]] = None,
) -> Any:
    """Fold persisted user sub-lines into a CapexStructure.

    This is the **explicit Run/materialization boundary**
    for Phase 57A-9D. The /run route in the user-created
    path calls this helper AFTER the project's
    ``ProjectInputs`` is built from the snapshot, and
    BEFORE the model is run.

    Args:
        capex: a ``CapexStructure`` (from
            ``domain.inputs``) for the project. This is
            the input to the model; the helper MAY
            return a new ``CapexStructure`` with selected
            field amounts updated.
        project_id: the ``projects.project_id`` (UUID) of
            the user project. Used to look up persisted
            sub-lines in the ``capex_sub_lines`` table.
            For factory / template-seeded projects (Generic Wind Reference,
            Generic Solar Reference, Generic Solar, Generic Wind), this
            helper is NOT called — the factory no-op case
            is handled by the empty ``user_sub_lines``
            short-circuit in ``fold_sub_lines_into_capex``.
        scenario_overrides: the active scenario's
            ``overrides_json`` dict (or None for Base
            case). The reserved key
            ``_capex_sub_line_overrides`` carries the
            ``{sub_line_id: amount_keur}`` map.

    Returns:
        A ``CapexStructure``. For factory projects and
        projects with no sub-lines, the input is returned
        unchanged. For user projects with sub-lines, a
        new ``CapexStructure`` is returned with the
        field amounts updated.

    Raises:
        ValueError: if a persisted sub-line carries an
            unknown parent category (e.g. C.99). This is
            fail-fast: silent drop would corrupt the
            parity guarantee. The 57A-9B
            ``validate_parent_category`` rejects C.17 and
            C.18 at persistence time, so they never reach
            this helper.

    Notes:
        - The helper does NOT mutate the input
          ``CapexStructure`` (``CapexStructure`` is a
          frozen dataclass, so mutation is impossible).
        - The helper does NOT generate fake runtime IDs.
          Sub-lines carry the persisted ``sub_line_id``
          (UUID) which is the scenario-override key.
        - The helper does NOT include 57A-8 in-memory
          preview rows. Those are not persisted.
        - The helper does NOT touch the model formula
          path, the Excel export, the UI, or the
          waterfall engine. It is purely an input-
          materialization step.
    """
    # Factory / template-seeded projects: the helper
    # returns capex unchanged via the empty-input
    # short-circuit in fold_sub_lines_into_capex. We
    # also short-circuit explicitly when project_id is
    # empty (defensive: callers from generic / template
    # paths MUST NOT pass an empty project_id).
    if not project_id:
        return capex

    user_sub_lines = _load_active_sub_lines(project_id)
    if not user_sub_lines:
        # Factory no-op path. No sub-lines persisted, so
        # the fold returns capex unchanged. Generic Wind Reference/Generic Solar Reference
        # parity preserved by construction.
        return capex

    sub_line_overrides = _extract_sub_line_overrides(
        scenario_overrides,
    )

    # The fold helper:
    #   - excludes soft-deleted rows (it filters on
    #     is_active)
    #   - uses the locked CAPEX_CATEGORY_TO_FIELD mapping
    #   - calls resolve_effective_sub_line_amount (override
    #     REPLACES default, not a delta)
    #   - returns a NEW CapexStructure (no mutation)
    #   - raises ValueError on unknown parent category
    #     (fail-fast, not silent drop)
    folded = fold_sub_lines_into_capex(
        capex,
        user_sub_lines,
        scenario_overrides=sub_line_overrides,
    )

    # Log a warning for any override UUID that does not
    # match an active sub-line. This is a stale-override
    # case (the scenario was created when the line
    # existed, but the line was later removed or its
    # UUID changed). The Run does NOT crash; the warning
    # surfaces the inconsistency to the reviewer.
    if sub_line_overrides:
        active_uuids = {
            sub.sub_line_id for sub in user_sub_lines
        }
        stale = set(sub_line_overrides) - active_uuids
        for stale_uuid in stale:
            logger.warning(
                "Scenario override for sub_line_id %s "
                "does not match any active sub-line; "
                "ignoring (sub-line may have been "
                "soft-deleted or its UUID may have "
                "changed).",
                stale_uuid,
            )

    return folded


# ---------------------------------------------------------------------------
# CAPEX-PERSIST-1: Persist sub-line form edits + replace-semantics fold
# ---------------------------------------------------------------------------

import re as _re

_SUB_LINE_FORM_RE = _re.compile(r"^capex_(C_\d{2}_U\d{3})_keur$")


def _parse_capex_sub_line_form_fields(form: Any) -> dict[str, float]:
    """Parse ``capex_C_NN_UYYY_keur`` form fields → ``{business_code: amount_keur}``.

    Business codes use the format ``C.NN.UYYY`` (e.g. ``C.06.U001``).
    The form field name is the business code with dots replaced by
    underscores and the prefix ``capex_`` added:
    ``capex_C_06_U001_keur`` → ``C.06.U001``.

    Phase 57A-8 temporary rows have no ``name`` attribute and
    therefore never appear here — they remain non-persisted.
    Temp codes (``C.NN.TMP-N``) would not match this regex anyway.
    """
    result: dict[str, float] = {}
    for key in form:
        m = _SUB_LINE_FORM_RE.match(key)
        if not m:
            continue
        raw_code = m.group(1)
        business_code = raw_code.replace("_", ".")  # C_06_01 → C.06.01
        try:
            amount = float(form.get(key) or 0)
        except (ValueError, TypeError):
            amount = 0.0
        result[business_code] = amount
    return result


def _upsert_sub_line_by_business_code(
    cursor: Any,
    project_id: str,
    business_code: str,
    amount_keur: float,
) -> None:
    """Update amount for an existing sub-line, or create it if missing.

    The parent category is derived from the business code prefix
    (e.g. C.06.01 → C.06). The label defaults to the business
    code when creating a new row. Soft-deleted rows (is_active=0)
    with a matching business_code are reactivated.
    """
    from app.persistence.capex_sub_lines import (
        CAPEX_CATEGORY_TO_FIELD,
        create_sub_line,
        validate_business_code,
        validate_parent_category,
    )
    from datetime import datetime, timezone

    validate_business_code(business_code)
    # Derive parent category: C.06.01 → C.06
    parts = business_code.rsplit(".", 1)
    parent_category_code = parts[0]
    validate_parent_category(parent_category_code)

    now = datetime.now(timezone.utc).isoformat()

    # Check for an existing row (active or soft-deleted).
    cursor.execute(
        """
        SELECT id FROM capex_sub_lines
        WHERE project_id = ? AND business_code = ?
        LIMIT 1
        """,
        (project_id, business_code),
    )
    row = cursor.fetchone()
    if row:
        cursor.execute(
            """
            UPDATE capex_sub_lines
            SET amount_keur = ?, is_active = 1, updated_at = ?
            WHERE project_id = ? AND business_code = ?
            """,
            (amount_keur, now, project_id, business_code),
        )
    else:
        create_sub_line(
            cursor,
            project_id=project_id,
            parent_category_code=parent_category_code,
            label=business_code,
            amount_keur=amount_keur,
            business_code=business_code,
        )


def persist_sub_line_form_edits(project_id: str, form: Any) -> None:
    """Parse CAPEX sub-line form fields and upsert them to the DB.

    Called in the user-created run path (CAPEX-PERSIST-1) before the fold
    step, so that edited sub-line amounts are visible to
    ``_apply_user_sub_lines_to_capex`` / ``apply_user_sub_lines_replacing_base``
    in the same request.

    Phase 57A-8 temporary rows are explicitly excluded: they
    carry no ``name`` attribute so they never appear in the form
    POST and are never persisted here. New-line persistence for
    those rows is deferred to a future phase.
    """
    if not project_id:
        return
    sub_line_edits = _parse_capex_sub_line_form_fields(form)
    if not sub_line_edits:
        return

    from app.persistence.capex_sub_lines import (
        validate_business_code,
        validate_parent_category,
    )
    from app.persistence.db import get_cursor
    with get_cursor() as cursor:
        for business_code, amount_keur in sub_line_edits.items():
            # Pre-validate so the DB try block below only covers sqlite writes.
            parts = business_code.rsplit(".", 1)
            try:
                validate_business_code(business_code)
                validate_parent_category(parts[0])
            except ValueError as exc:
                logger.warning(
                    "CAPEX-PERSIST-1: skipping invalid sub-line code %s "
                    "for project %s: %s",
                    business_code, project_id, exc,
                )
                continue
            # Validation passed — only DB-level errors can reach here.
            try:
                _upsert_sub_line_by_business_code(
                    cursor, project_id, business_code, amount_keur,
                )
            except Exception as exc:
                logger.warning(
                    "CAPEX-PERSIST-1: DB error for sub-line %s "
                    "in project %s: %s",
                    business_code, project_id, exc,
                )
    # get_cursor() commits on context-manager exit.


def apply_user_sub_lines_replacing_base(
    capex: Any,
    *,
    project_id: str,
    scenario_overrides: Optional[Mapping[str, Any]] = None,
) -> Any:
    """Fold persisted user sub-lines with REPLACE semantics.

    Unlike ``_apply_user_sub_lines_to_capex`` (which ADDS
    sub-line amounts to the existing category base), this
    function ZEROS the category base for any field that has
    persisted sub-lines, then folds in the sub-line sum.
    Result: the category total = sum(sub_lines), not
    base + sum(sub_lines).

    This is correct for the user-project CAPEX grid where
    sub-lines ARE the breakdown of the category: the user
    edits individual line amounts and expects the category
    subtotal to equal their entries.

    Generic Wind Reference/Generic Solar Reference parity: factory projects have no persisted
    sub-lines → empty user_sub_lines → returns capex
    unchanged (no zeroing, no folding).
    """
    if not project_id:
        return capex

    user_sub_lines = _load_active_sub_lines(project_id)
    if not user_sub_lines:
        return capex

    # Determine which CapexStructure fields have active sub-lines.
    from app.persistence.capex_sub_lines import CAPEX_CATEGORY_TO_FIELD
    import dataclasses

    fields_with_sub_lines: set[str] = set()
    for sub in user_sub_lines:
        if sub.is_active:
            field_name = CAPEX_CATEGORY_TO_FIELD.get(sub.parent_category_code)
            if field_name:
                fields_with_sub_lines.add(field_name)

    # Zero out the base amounts for those fields.
    zero_updates: dict[str, Any] = {}
    for field_name in fields_with_sub_lines:
        existing_item = getattr(capex, field_name)
        zero_updates[field_name] = dataclasses.replace(
            existing_item, amount_keur=0.0
        )
    zeroed_capex = (
        dataclasses.replace(capex, **zero_updates) if zero_updates else capex
    )

    # Fold (add sub-line amounts to the now-zero base).
    sub_line_overrides = _extract_sub_line_overrides(scenario_overrides)
    folded = fold_sub_lines_into_capex(
        zeroed_capex, user_sub_lines, scenario_overrides=sub_line_overrides,
    )

    # Warn on stale scenario overrides (same as _apply_user_sub_lines_to_capex).
    if sub_line_overrides:
        active_uuids = {sub.sub_line_id for sub in user_sub_lines}
        for stale_uuid in set(sub_line_overrides) - active_uuids:
            logger.warning(
                "CAPEX-PERSIST-1: scenario override for sub_line_id %s "
                "does not match any active sub-line; ignoring.",
                stale_uuid,
            )

    return folded
