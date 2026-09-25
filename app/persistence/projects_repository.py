"""Project persistence functions extracted from app/persistence/repository.py.

This module holds Group A (project) persistence functions extracted
during Phase 53D (A-reads) and Phase 53E-2 (A-2 writes). The
functions are re-exported from app.persistence.repository for
backward compatibility.

Function inventory (Group A-reads, Phase 53D):

- get_project
- get_project_by_code
- list_projects
- list_baseline_records
- get_project_record
- list_project_records

Function inventory (Group A-2 writes, Phase 53E-2):

- save_project
- create_project_record
- update_project_record
- seed_baseline_projects_if_needed
- _compute_baseline_snapshot
- _build_default_snapshot
- _fill_missing_defaults

(Additional private helper _sum_opex is defined inside
_compute_baseline_snapshot as a nested function and moves with it.)

ProjectRecord is a dataclass defined inside app.persistence.repository.
It is shared with the read functions and is referenced via
TYPE_CHECKING + runtime lazy import to avoid circular import at
module load time. The class itself is not moved in this phase.

Behavior is preserved exactly as it was in repository.py. The only
change is the file location.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from app.persistence._helpers import _from_iso, _from_json, _now_utc, _to_json
from app.persistence.db import get_cursor

# Sentinel for "argument was not passed by caller" — distinguishes omission from
# explicit None on project-library metadata fields so save_project() can
# preserve existing DB values when callers do not supply new ones.
_UNSET = object()

if TYPE_CHECKING:
    from app.persistence.records import ProjectRecord


# ===========================================================================
# Group A-reads (Phase 53D)
# ===========================================================================


def get_project(project_id: str, user_id: str) -> "Optional[ProjectRecord]":
    with get_cursor() as cur:
        cur.execute("SELECT * FROM projects WHERE project_id=? AND user_id=?", (project_id, user_id))
        row = cur.fetchone()
    from app.persistence.records import ProjectRecord
    return ProjectRecord.from_row(row) if row else None


def get_project_by_code(user_id: str, project_code: str) -> "Optional[ProjectRecord]":
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM projects WHERE user_id=? AND project_code=?",
            (user_id, project_code),
        )
        row = cur.fetchone()
    from app.persistence.records import ProjectRecord
    return ProjectRecord.from_row(row) if row else None


def list_projects(user_id: str) -> "list[ProjectRecord]":
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM projects WHERE user_id=? AND archived=0 ORDER BY updated_at DESC",
            (user_id,),
        )
        from app.persistence.records import ProjectRecord
        return [ProjectRecord.from_row(row) for row in cur.fetchall()]


def list_baseline_records(user_id: str) -> "list[ProjectRecord]":
    """Return saved-baseline records (project_origin='saved_baseline') for a user."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM projects WHERE user_id=? AND project_origin='saved_baseline' AND archived=0 ORDER BY project_name",
            (user_id,),
        )
        from app.persistence.records import ProjectRecord
        return [ProjectRecord.from_row(row) for row in cur.fetchall()]


def get_project_record(
    *,
    user_id: str,
    project_id: Optional[str] = None,
    project_code: Optional[str] = None,
) -> "Optional[ProjectRecord]":
    if project_id:
        return get_project(project_id, user_id)
    if project_code:
        return get_project_by_code(user_id, project_code)
    return None


def list_project_records(
    *,
    user_id: str,
    include_archived: bool = False,
) -> "list[ProjectRecord]":
    query = "SELECT * FROM projects WHERE user_id=?"
    params: list[Any] = [user_id]
    if not include_archived:
        query += " AND archived=0"
    query += " ORDER BY updated_at DESC"
    with get_cursor() as cur:
        cur.execute(query, tuple(params))
        from app.persistence.records import ProjectRecord
        return [ProjectRecord.from_row(row) for row in cur.fetchall()]


# Sentinel user_id for system-owned reference projects.
REFERENCE_USER_ID: str = "__reference__"

# Canonical system-reference SQL predicate.
#
# A row is a *canonical* system reference iff ALL of:
#   user_id == REFERENCE_USER_ID
#   project_role == 'reference'
#   is_protected == True
#   archived == False
#   template_source in ('generic_wind_reference', 'generic_solar_reference', 'generic_storage_reference')
#
# Use these constants / helper everywhere canonical-reference checks
# happen — do not let functions drift into different definitions.
CANONICAL_REFERENCE_TEMPLATES: tuple[str, ...] = (
    "generic_wind_reference",
    "generic_solar_reference",
    "generic_storage_reference",
    "generic_data_center_reference",
)


def _canonical_reference_template_params() -> list[str]:
    """Return the canonical template values in predicate binding order."""
    return list(CANONICAL_REFERENCE_TEMPLATES)


def _canonical_reference_predicate() -> str:
    """Return the shared SQL WHERE clause for a canonical system reference.

    Returns just the predicate (without the leading WHERE). All five
    canonical-reference columns are bound by parameter. The first
    parameter is the canonical owner (REFERENCE_USER_ID); the template
    source slots follow ``CANONICAL_REFERENCE_TEMPLATES`` order — bind
    them via ``_canonical_reference_template_params()`` so the clause and
    the parameters can never drift apart.
    """
    slots = ", ".join("?" for _ in CANONICAL_REFERENCE_TEMPLATES)
    return (
        "user_id=? AND project_role='reference' AND is_protected=1"
        f" AND archived=0 AND template_source IN ({slots})"
    )


def get_reference_projects() -> "list[ProjectRecord]":
    """Return all canonical system reference projects.

    "Canonical" means: owned by ``__reference__``, marked
    ``is_protected=1``, not archived, and templated as
    ``generic_wind_reference``, ``generic_solar_reference``, or ``generic_storage_reference``. User-owned rows carrying
    ``project_role='reference'`` are intentionally excluded — they
    are not system canonical references and must not be globally
    visible.
    """
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM projects WHERE "
            + _canonical_reference_predicate()
            + " ORDER BY template_source, project_name",
            (
                [REFERENCE_USER_ID] + _canonical_reference_template_params()
            ),
        )
        from app.persistence.records import ProjectRecord
        return [ProjectRecord.from_row(row) for row in cur.fetchall()]


def get_reference_by_template_source(template_source: str) -> "Optional[ProjectRecord]":
    """Return the canonical reference project for a given template source.

    "Canonical" means: owned by ``__reference__``, marked
    ``is_protected=1``, not archived, and templated as
    ``generic_wind_reference``, ``generic_solar_reference``, or ``generic_storage_reference``. Bootstrap depends on this function
    returning exactly the system reference — never a user-owned row
    that happens to share the same template_source value.
    """
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM projects WHERE "
            + _canonical_reference_predicate()
            + " AND template_source=?",
            (
                [REFERENCE_USER_ID] + _canonical_reference_template_params() + [template_source]
            ),
        )
        row = cur.fetchone()
    from app.persistence.records import ProjectRecord
    return ProjectRecord.from_row(row) if row else None


def get_project_by_id(project_id: str) -> "Optional[ProjectRecord]":
    """Fetch a project by primary key only (no user_id filter — for cross-user reference access)."""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM projects WHERE project_id=?", (project_id,))
        row = cur.fetchone()
    from app.persistence.records import ProjectRecord
    return ProjectRecord.from_row(row) if row else None


def get_canonical_reference_by_id(project_id: str) -> "Optional[ProjectRecord]":
    """Return a reference project only if it satisfies the strict canonical contract.

    Returns None if the project does not exist or does not meet all
    canonical-reference criteria (see
    ``_canonical_reference_predicate()`` for the single source of
    truth).
    """
    record = get_project_by_id(project_id)
    if record is None:
        return None
    if record.user_id != REFERENCE_USER_ID:
        return None
    if record.project_role != "reference":
        return None
    if not record.is_protected:
        return None
    if record.archived:
        return None
    if record.template_source not in CANONICAL_REFERENCE_TEMPLATES:
        return None
    return record


def resolve_accessible_project(
    user_id: str,
    project_code: str,
) -> "tuple[Optional[ProjectRecord], str]":
    """Resolve a project code for a user, returning (record, workspace_owner_id).

    Lookup order:
    1. User's own project — workspace_owner_id == user_id
    2. Canonical system reference (user_id='__reference__',
       project_role='reference', is_protected=1, archived=0,
       template_source in ('generic_wind_reference','generic_solar_reference','generic_storage_reference'))
       — workspace_owner_id == REFERENCE_USER_ID

    Never returns another normal user's project. Never returns a
    user-owned row that happens to carry ``project_role='reference'``:
    only rows that satisfy the strict canonical-reference contract
    are eligible for cross-user resolution.

    Returns (None, user_id) when not found.
    """
    record = get_project_by_code(user_id, project_code)
    if record is not None:
        return record, user_id

    ref = get_project_by_code(REFERENCE_USER_ID, project_code)
    if (
        ref is not None
        and ref.user_id == REFERENCE_USER_ID
        and ref.project_role == "reference"
        and ref.is_protected
        and not ref.archived
        and ref.template_source in CANONICAL_REFERENCE_TEMPLATES
    ):
        return ref, REFERENCE_USER_ID

    return None, user_id


def list_projects_paged(
    *,
    user_id: str,
    page: int = 1,
    page_size: int = 20,
    search: Optional[str] = None,
    role_filter: Optional[str] = None,
) -> "tuple[list[ProjectRecord], int]":
    """Paginated project query for the project library.

    Returns (records, total_count).

    A user sees their own projects unioned with **canonical system
    references only** — i.e. ``__reference__``-owned, ``is_protected=1``,
    not archived, templated as ``generic_wind_reference``, ``generic_solar_reference``, or ``generic_storage_reference``. A user-owned row
    that happens to carry ``project_role='reference'`` is **not**
    globally visible; this is the canonical-reference contract enforced
    uniformly by ``_canonical_reference_predicate()``.

    Both the result query and the total-count query use the same
    ``base_where`` so pagination totals are isolated from user-owned
    role-reference rows.
    """
    from app.persistence.records import ProjectRecord

    # Build the WHERE clause.
    # A user sees: their own projects UNION canonical system references.
    # "Canonical" requires user_id='__reference__' AND project_role='reference'
    # AND is_protected=1 AND archived=0 AND template_source IN
    # ('generic_wind_reference','generic_solar_reference','generic_storage_reference'). The user_id parameter is bound; the canonical
    # template list is bound too — no SQL interpolation.
    base_where = (
        "(user_id=?"
        " OR ("
        + _canonical_reference_predicate()
        + "))"
        " AND archived=0"
    )
    # Parameter order matches the SQL predicate produced by _canonical_reference_predicate():
    #   1) requesting user_id (their-own branch — user_id=? in outer clause)
    #   2) canonical owner (REFERENCE_USER_ID) — user_id=? in inner predicate
    #   3+) canonical template sources in CANONICAL_REFERENCE_TEMPLATES order
    #       (Wind, Solar, Storage, Data Center).  Every canonical template
    #       must be bound; omitting Storage (XC) was a historical bug.
    params: list[Any] = [
        user_id,
        REFERENCE_USER_ID,
        *_canonical_reference_template_params(),
    ]

    if role_filter and role_filter in ("reference", "working_copy", "user_project"):
        base_where += " AND project_role=?"
        params.append(role_filter)

    if search:
        # Escape SQLite LIKE wildcards in user input, then match anywhere in name.
        safe = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        base_where += " AND project_name LIKE ? ESCAPE '\\'"
        params.append(f"%{safe}%")

    count_sql = f"SELECT COUNT(*) FROM projects WHERE {base_where}"
    data_sql = (
        f"SELECT * FROM projects WHERE {base_where}"
        " ORDER BY"
        "  CASE WHEN project_role='reference' THEN 1 ELSE 0 END,"
        "  updated_at DESC"
        f" LIMIT {int(page_size)} OFFSET {int((page - 1) * page_size)}"
    )

    with get_cursor() as cur:
        cur.execute(count_sql, tuple(params))
        total = cur.fetchone()[0]
        cur.execute(data_sql, tuple(params))
        records = [ProjectRecord.from_row(row) for row in cur.fetchall()]

    return records, total


def list_workspace_projects_paged(
    *, user_id: str, page: int = 1, page_size: int = 20,
    search: Optional[str] = None, role_filter: Optional[str] = None,
) -> "tuple[list[ProjectRecord], int]":
    """Paginate only the user's editable workspace; references are read separately.

    A reference-only filter deliberately yields an empty working list. Both
    count and rows share the same predicate so paging cannot hide templates.
    """
    from app.persistence.records import ProjectRecord
    where = "user_id=? AND archived=0 AND is_protected=0 AND is_readonly=0 AND project_role!='reference'"
    params: list[Any] = [user_id]
    if role_filter == "reference":
        where += " AND 1=0"
    elif role_filter in ("working_copy", "user_project"):
        where += " AND project_role=?"
        params.append(role_filter)
    if search:
        safe = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where += " AND project_name LIKE ? ESCAPE '\\'"
        params.append(f"%{safe}%")
    with get_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM projects WHERE {where}", tuple(params))
        total = cur.fetchone()[0]
        cur.execute(
            f"SELECT * FROM projects WHERE {where} ORDER BY updated_at DESC, project_id DESC LIMIT ? OFFSET ?",
            (*params, max(1, page_size), max(0, page - 1) * max(1, page_size)),
        )
        records = [ProjectRecord.from_row(row) for row in cur.fetchall()]
    return records, total


def list_recent_projects(
    user_id: str,
    *,
    limit: int = 8,
    exclude_project_id: Optional[str] = None,
) -> "list[ProjectRecord]":
    """Return the most-recently-updated user-owned projects for the sidebar."""
    params: list[Any] = [user_id]
    extra = ""
    if exclude_project_id:
        extra = " AND project_id != ?"
        params.append(exclude_project_id)
    with get_cursor() as cur:
        cur.execute(
            f"SELECT * FROM projects WHERE user_id=? AND archived=0{extra}"
            f" ORDER BY updated_at DESC LIMIT {int(limit)}",
            tuple(params),
        )
        from app.persistence.records import ProjectRecord
        return [ProjectRecord.from_row(row) for row in cur.fetchall()]


# ===========================================================================
# Group A-2 writes (Phase 53E-2)
# ===========================================================================


def save_project(
    user_id: str,
    project_code: str,
    project_name: str,
    source_project_template: str,
    project_type: Optional[str] = None,
    project_origin: str = "factory_template",
    template_source: Optional[str] = None,
    baseline_snapshot: Optional[dict[str, Any]] = None,
    archived: bool = False,
    is_readonly: bool = False,
    governance_state: Optional[dict[str, Any]] = None,
    last_run_summary: Optional[dict[str, Any]] = None,
    replay_metadata: Optional[dict[str, Any]] = None,
    capex_sub_lines: Optional[list] = None,
    full_inputs: Optional[dict[str, Any]] = None,  # V3-7: full-fidelity ProjectInputs dict
    project_role: Any = _UNSET,                     # Project Library — preserved on update when omitted
    is_protected: Any = _UNSET,                     # Project Library — preserved on update when omitted
    source_project_id: Any = _UNSET,                # Project Library — preserved on update when omitted
) -> "ProjectRecord":
    now = _now_utc()
    governance_state = governance_state or {}
    last_run_summary = last_run_summary or {}
    baseline_snapshot = baseline_snapshot or {}
    replay_metadata = dict(replay_metadata or {})
    effective_template_source = template_source or source_project_template

    with get_cursor() as cur:
        cur.execute(
            """
            SELECT project_id, created_at, project_type, project_origin, template_source,
                   baseline_snapshot_json, archived, full_inputs_json,
                   project_role, is_protected, source_project_id
            FROM projects
            WHERE user_id=? AND project_code=?
            """,
            (user_id, project_code),
        )
        existing = cur.fetchone()
        if existing:
            project_id = existing["project_id"]
            created_at = _from_iso(existing["created_at"])
            project_type = project_type or existing["project_type"]
            project_origin = project_origin or existing["project_origin"] or "factory_template"
            effective_template_source = effective_template_source or existing["template_source"] or source_project_template
            if not baseline_snapshot:
                baseline_snapshot = _from_json(existing["baseline_snapshot_json"], {})
            # Preserve existing full_inputs if caller does not supply a new one
            if full_inputs is None:
                _existing_fi = existing["full_inputs_json"] if "full_inputs_json" in existing.keys() else None
                full_inputs = _from_json(_existing_fi, None) if _existing_fi else None
            archived = bool(existing["archived"]) if archived is None else archived
            # Preserve project-library metadata from existing row when caller did not pass new values.
            _keys = existing.keys()
            if project_role is _UNSET:
                project_role = existing["project_role"] if "project_role" in _keys else "user_project"
            if is_protected is _UNSET:
                is_protected = bool(existing["is_protected"]) if "is_protected" in _keys else False
            if source_project_id is _UNSET:
                source_project_id = existing["source_project_id"] if "source_project_id" in _keys else None
            replay_metadata.setdefault("project_id", project_id)
            cur.execute(
                """
                UPDATE projects
                SET project_name=?, project_type=?, project_origin=?, source_project_template=?, template_source=?,
                    baseline_snapshot_json=?, archived=?, is_readonly=?, governance_state_json=?, last_run_summary_json=?,
                    replay_metadata_json=?, full_inputs_json=?, project_role=?, is_protected=?, source_project_id=?,
                    updated_at=?
                WHERE project_id=? AND user_id=?
                """,
                (
                    project_name,
                    project_type,
                    project_origin,
                    source_project_template,
                    effective_template_source,
                    _to_json(baseline_snapshot),
                    int(bool(archived)),
                    int(bool(is_readonly)),
                    _to_json(governance_state),
                    _to_json(last_run_summary),
                    _to_json(replay_metadata),
                    _to_json(full_inputs) if full_inputs is not None else None,
                    project_role,
                    int(bool(is_protected)),
                    source_project_id,
                    now.isoformat(),
                    project_id,
                    user_id,
                ),
            )
        else:
            project_id = uuid.uuid4().hex[:16]
            created_at = now
            # Apply insert-time defaults for omitted project-library fields.
            if project_role is _UNSET:
                project_role = "user_project"
            if is_protected is _UNSET:
                is_protected = False
            if source_project_id is _UNSET:
                source_project_id = None
            replay_metadata.setdefault("project_id", project_id)
            cur.execute(
                """
                INSERT INTO projects (
                    project_id, user_id, project_code, project_name, project_type, project_origin,
                    source_project_template, template_source, baseline_snapshot_json, archived, is_readonly,
                    governance_state_json, last_run_summary_json, replay_metadata_json,
                    full_inputs_json, project_role, is_protected, source_project_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    user_id,
                    project_code,
                    project_name,
                    project_type,
                    project_origin,
                    source_project_template,
                    effective_template_source,
                    _to_json(baseline_snapshot),
                    int(bool(archived)),
                    int(bool(is_readonly)),
                    _to_json(governance_state),
                    _to_json(last_run_summary),
                    _to_json(replay_metadata),
                    _to_json(full_inputs) if full_inputs is not None else None,
                    project_role,
                    int(bool(is_protected)),
                    source_project_id,
                    created_at.isoformat(),
                    now.isoformat(),
                ),
            )

        # Phase 57A-9C: optionally replace the project's
        # user-added CAPEX sub-lines. This happens in the
        # same transaction as the project row write so a
        # partial failure rolls back both. The sub-line
        # upsert is audit-friendly: rows are never
        # hard-deleted, only soft-deleted. See
        # replace_sub_lines_for_project for the full
        # upsert + soft-delete semantic.
        if capex_sub_lines is not None:
            from app.persistence.records import ProjectRecord
            from app.persistence.capex_sub_lines import (
                assert_project_allows_capex_sub_lines,
                replace_sub_lines_for_project,
            )
            # Defense in depth: factory_template projects
            # cannot have sub-lines. The helper below is the
            # single source of truth for this invariant.
            project_record_for_guard = ProjectRecord(
                project_id=project_id,
                user_id=user_id,
                project_code=project_code,
                project_name=project_name,
                project_type=project_type,
                project_origin=project_origin,
                source_project_template=source_project_template,
                template_source=effective_template_source,
                baseline_snapshot=baseline_snapshot,
                archived=bool(archived),
                is_readonly=bool(is_readonly),
                governance_state=governance_state,
                last_run_summary=last_run_summary,
                replay_metadata=replay_metadata,
                created_at=created_at,
                updated_at=now,
            )
            from app.persistence.capex_sub_lines import (
                assert_project_allows_capex_sub_lines,
                replace_sub_lines_for_project,
            )
            assert_project_allows_capex_sub_lines(project_record_for_guard)
            replace_sub_lines_for_project(
                cur,
                project_id=project_id,
                sub_lines=capex_sub_lines,
            )

    from app.persistence.records import ProjectRecord
    return ProjectRecord(
        project_id=project_id,
        user_id=user_id,
        project_code=project_code,
        project_name=project_name,
        project_type=project_type,
        project_origin=project_origin,
        source_project_template=source_project_template,
        template_source=effective_template_source,
        baseline_snapshot=baseline_snapshot,
        archived=bool(archived),
        is_readonly=is_readonly,
        governance_state=governance_state,
        last_run_summary=last_run_summary,
        replay_metadata=replay_metadata,
        created_at=created_at,
        updated_at=now,
        project_role=project_role,
        is_protected=bool(is_protected),
        source_project_id=source_project_id,
    )


def create_project_record(
    *,
    user_id: str,
    project_code: str,
    project_name: str,
    project_type: str,
    project_origin: str,
    template_source: str,
    baseline_snapshot: dict[str, Any],
    governance_state: Optional[dict[str, Any]] = None,
    last_run_summary: Optional[dict[str, Any]] = None,
    replay_metadata: Optional[dict[str, Any]] = None,
    is_readonly: bool = False,
) -> "ProjectRecord":
    return save_project(
        user_id=user_id,
        project_code=project_code,
        project_name=project_name,
        project_type=project_type,
        project_origin=project_origin,
        source_project_template=template_source,
        template_source=template_source,
        baseline_snapshot=baseline_snapshot,
        governance_state=governance_state,
        last_run_summary=last_run_summary,
        replay_metadata=replay_metadata,
        is_readonly=is_readonly,
    )


def update_project_record(
    *,
    user_id: str,
    project_code: str,
    project_name: Optional[str] = None,
    project_type: Optional[str] = None,
    template_source: Optional[str] = None,
    baseline_snapshot: Optional[dict[str, Any]] = None,
    archived: Optional[bool] = None,
    governance_state: Optional[dict[str, Any]] = None,
    last_run_summary: Optional[dict[str, Any]] = None,
    replay_metadata: Optional[dict[str, Any]] = None,
) -> "Optional[ProjectRecord]":
    existing = get_project_by_code(user_id, project_code)
    if existing is None:
        return None
    return save_project(
        user_id=user_id,
        project_code=existing.project_code,
        project_name=project_name or existing.project_name,
        project_type=project_type or existing.project_type,
        project_origin=existing.project_origin,
        source_project_template=template_source or existing.source_project_template,
        template_source=template_source or existing.template_source or existing.source_project_template,
        baseline_snapshot=baseline_snapshot if baseline_snapshot is not None else existing.baseline_snapshot,
        archived=existing.archived if archived is None else archived,
        governance_state=governance_state or existing.governance_state,
        last_run_summary=last_run_summary or existing.last_run_summary,
        replay_metadata=replay_metadata or existing.replay_metadata,
    )


def seed_baseline_projects_if_needed(user_id: str) -> "list[ProjectRecord]":
    """
    Ensure Generic Wind Reference Baseline and Generic Solar Reference Baseline exist for user.
    Idempotent — does not overwrite existing baseline records.
    """
    seeded = []
    for code, name, project_type, template_source in [
        ("generic_wind_reference-baseline", "Generic Wind Reference — Baseline", "Wind", "generic_wind_reference"),
        ("generic_solar_reference-baseline", "Generic Solar Reference — Baseline", "Solar", "generic_solar_reference"),
        ("generic_data_center_reference-baseline", "Generic Data Center Reference — Baseline", "Data Center", "generic_data_center_reference"),
    ]:
        existing = get_project_by_code(user_id, code)
        if existing is not None:
            continue  # already exists
        snapshot = _compute_baseline_snapshot(project_type, template_source)
        record = save_project(
            user_id=user_id,
            project_code=code,
            project_name=name,
            project_type=project_type,
            project_origin="saved_baseline",
            source_project_template=template_source,
            template_source=template_source,
            baseline_snapshot=snapshot,
            is_readonly=True,
            governance_state={"g20": "BLOCKED", "r99_r102": "NOT_APPROVED", "lender_ready": False},
        )
        seeded.append(record)
    return seeded


def _compute_baseline_snapshot(project_type: str, template_source: str) -> dict[str, Any]:
    """
    Build a workspace-ready snapshot dict for a saved baseline project.
    Mirrors the logic in main_web._project_baseline_snapshot.
    """
    from app.project_factories import (
        create_generic_wind_reference,
        create_generic_solar_reference,
        create_generic_storage_reference,
        create_generic_data_center_reference,
        create_default_wind_project,
        create_default_solar_project,
    )
    from app.persistence.db import get_cursor

    canonical_type = project_type
    normalized_source = template_source

    baseline = {
        "active_project": "",
        "project_name": "",
        "project_type": canonical_type,
        "project_origin": "saved_baseline",
        "template_source": normalized_source,
        "country_market": "",
        "scenario": "Base",
        "capacity_mw": "",
        "tariff_eur_mwh": "",
        "p50_hours": "",
        "total_capex_keur": "",
        "opex_y1_keur": "",
        "gearing_pct": "",
        "target_dscr": "",
        "interest_rate_pct": "",
        "tenor_years": "",
        "cod_date": "",
        "construction_months": "",
        "horizon_years": "",
        "capacity_factor": "",
        "ppa_term_years": "",
    }

    def _sum_opex(items):
        """Sum y1_amount_keur from an opex iterable."""
        total = 0.0
        for item in items:
            total += float(getattr(item, "y1_amount_keur", 0) or 0)
        return total

    if normalized_source == "generic_wind_reference":
        pi = create_generic_wind_reference()
        baseline.update({
            "active_project": "generic_wind_reference-baseline",
            "project_name": pi.info.name,
            "project_type": "Wind",
            "template_source": "generic_wind_reference",
            "country_market": pi.info.country_iso,
            "capacity_mw": str(pi.technical.capacity_mw),
            "tariff_eur_mwh": str(pi.revenue.ppa_base_tariff),
            "p50_hours": str(pi.technical.operating_hours_p50),
            "total_capex_keur": str(pi.capex.total_capex),
            "opex_y1_keur": str(_sum_opex(pi.opex)),
            "target_dscr": str(pi.financing.target_dscr),
            "interest_rate_pct": str(pi.financing.base_rate + pi.financing.margin_bps / 10_000),
            "tenor_years": str(pi.financing.senior_tenor_years),
            "cod_date": str(pi.info.cod_date),
            "construction_months": str(pi.info.construction_months),
            "horizon_years": str(pi.info.horizon_years),
            "capacity_factor": f"{(pi.technical.operating_hours_p50 / 8760) * 100:.2f}",
            "ppa_term_years": str(int(pi.revenue.ppa_term_years)),
        })
        return baseline

    if normalized_source == "generic_solar_reference":
        pi = create_generic_solar_reference()
        from app.revenue_snapshot_utils import materialize_revenue_snapshot_defaults
        baseline.update({
            "active_project": "generic_solar_reference-baseline",
            "project_name": pi.info.name,
            "project_type": "Solar",
            "template_source": "generic_solar_reference",
            "country_market": pi.info.country_iso,
            "capacity_mw": str(pi.technical.capacity_mw),
            "tariff_eur_mwh": str(pi.revenue.ppa_base_tariff),
            "p50_hours": str(pi.technical.operating_hours_p50),
            "total_capex_keur": str(pi.capex.total_capex),
            "opex_y1_keur": str(_sum_opex(pi.opex)),
            "gearing_pct": str(float(getattr(pi.financing, "gearing_ratio", 0.0) or 0.0) * 100),
            "target_dscr": str(pi.financing.target_dscr),
            "interest_rate_pct": str(pi.financing.base_rate + pi.financing.margin_bps / 10_000),
            "tenor_years": str(pi.financing.senior_tenor_years),
            "cod_date": str(pi.info.cod_date),
            "construction_months": str(pi.info.construction_months),
            "horizon_years": str(pi.info.horizon_years),
            "capacity_factor": f"{(pi.technical.operating_hours_p50 / 8760) * 100:.2f}",
            "ppa_term_years": str(int(pi.revenue.ppa_term_years)),
        })
        baseline.update(materialize_revenue_snapshot_defaults(pi.revenue))
        return baseline

    if normalized_source == "generic_storage_reference":
        pi = create_generic_storage_reference()
        baseline.update({
            "active_project": "generic_storage_reference-baseline",
            "project_name": pi.info.name,
            "project_type": "Storage",
            "template_source": "generic_storage_reference",
            "country_market": pi.info.country_iso,
            "capacity_mw": str(pi.technical.capacity_mw),
            "tariff_eur_mwh": "0",
            "p50_hours": "0",
            "total_capex_keur": str(pi.capex.total_capex),
            "opex_y1_keur": str(_sum_opex(pi.opex)),
            "gearing_pct": str(float(getattr(pi.financing, "gearing_ratio", 0.0) or 0.0) * 100),
            "target_dscr": str(pi.financing.target_dscr),
            "interest_rate_pct": str(pi.financing.base_rate + pi.financing.margin_bps / 10_000),
            "tenor_years": str(pi.financing.senior_tenor_years),
            "cod_date": str(pi.info.cod_date),
            "construction_months": str(pi.info.construction_months),
            "horizon_years": str(pi.info.horizon_years),
            "capacity_factor": "",
            "ppa_term_years": "0",
        })
        return baseline

    if normalized_source == "generic_data_center_reference":
        pi = create_generic_data_center_reference()
        from app.data_center_authority import (
            GENERIC_DATA_CENTER_REFERENCE_DRIVERS,
            dc_driver_snapshot_values,
        )
        baseline.update({
            "active_project": "generic_data_center_reference-baseline",
            "project_name": pi.info.name,
            "project_type": "Data Center",
            "template_source": "generic_data_center_reference",
            "country_market": pi.info.country_iso,
            "capacity_mw": str(pi.technical.capacity_mw),
            "tariff_eur_mwh": "0",
            # Full-time IT-load basis: occupancy is the utilization authority.
            "p50_hours": str(pi.technical.operating_hours_p50),
            "total_capex_keur": str(pi.capex.total_capex),
            "opex_y1_keur": str(_sum_opex(pi.opex)),
            "gearing_pct": str(float(getattr(pi.financing, "gearing_ratio", 0.0) or 0.0) * 100),
            "target_dscr": str(pi.financing.target_dscr),
            "interest_rate_pct": str(pi.financing.base_rate + pi.financing.margin_bps / 10_000),
            "tenor_years": str(pi.financing.senior_tenor_years),
            "cod_date": str(pi.info.cod_date),
            "construction_months": str(pi.info.construction_months),
            "horizon_years": str(pi.info.horizon_years),
            "capacity_factor": "",
            "ppa_term_years": str(int(pi.revenue.ppa_term_years)),
        })
        baseline.update(dc_driver_snapshot_values(GENERIC_DATA_CENTER_REFERENCE_DRIVERS))
        return baseline

    # generic fallback
    if canonical_type == "Solar":
        pi = create_default_solar_project()
    else:
        pi = create_default_wind_project()
    baseline.update({
        "active_project": normalized_source,
        "project_name": pi.info.name,
        "template_source": normalized_source,
        "country_market": pi.info.country_iso,
        "capacity_mw": str(pi.technical.capacity_mw),
        "tariff_eur_mwh": str(pi.revenue.ppa_base_tariff),
        "p50_hours": str(pi.technical.operating_hours_p50),
        "total_capex_keur": str(pi.capex.total_capex),
        "opex_y1_keur": str(_sum_opex(pi.opex)),
        "gearing_pct": str(float(getattr(pi.financing, "gearing_ratio", 0.0) or 0.0) * 100),
        "target_dscr": str(pi.financing.target_dscr),
        "interest_rate_pct": str(pi.financing.base_rate + pi.financing.margin_bps / 10_000),
        "tenor_years": str(pi.financing.senior_tenor_years),
        "cod_date": str(pi.info.cod_date),
        "construction_months": str(pi.info.construction_months),
        "horizon_years": str(pi.info.horizon_years),
        "capacity_factor": f"{(pi.technical.operating_hours_p50 / 8760) * 100:.2f}",
        "ppa_term_years": str(int(pi.revenue.ppa_term_years)),
    })
    return baseline


def _build_default_snapshot(project_code: str, defaults: dict[str, Any]) -> dict[str, Any]:
    """Build a workspace-ready snapshot from factory defaults."""
    from app.input_adapter import build_projectinputs_from_snapshot
    snapshot = dict(defaults)
    snapshot["active_project"] = project_code
    snapshot["project_origin"] = "saved_baseline"
    # Ensure runtime-usable fields are present
    _fill_missing_defaults(snapshot)
    return snapshot


def _fill_missing_defaults(snapshot: dict[str, Any]) -> None:
    """Ensure required snapshot fields exist with safe defaults."""
    defaults = {
        "scenario": "Base",
        "project_type": "Wind",
        "capacity_mw": 50.0,
        "p50_hours": 2500.0,
        "tariff_eur_mwh": 80.0,
        "total_capex_keur": 50000.0,
        "opex_y1_keur": 5000.0,
        "gearing_pct": 75.0,
        "target_dscr": 1.4,
        "interest_rate_pct": 7.0,
        "tenor_years": 20,
    }
    for k, v in defaults.items():
        if k not in snapshot:
            snapshot[k] = v


# ============================================================
# Phase 57A-9C: CAPEX sub-lines load wiring
# ============================================================


def get_project_with_sub_lines(
    user_id: str,
    project_code: str,
    include_inactive_sub_lines: bool = False,
) -> "tuple[Optional[ProjectRecord], tuple[Any, ...]]":
    """Load a project and its CAPEX sub-lines in one call.

    Returns a ``(project_record, sub_lines)`` tuple. ``project_record``
    is ``None`` if no project exists for the given
    (user_id, project_code). The ``sub_lines`` tuple is empty
    for projects that have no user-added sub-lines (the
    typical case for factory-template projects).

    Soft-deleted sub-lines are excluded by default; pass
    ``include_inactive_sub_lines=True`` to include them (for
    audit / replay).

    The sub-lines are returned in the canonical order
    ``(parent_category_code ASC, display_order ASC)`` — the
    same order used by the LineItemGrid render path. The
    caller can use this order directly without re-sorting.
    """
    project_record = get_project_by_code(user_id, project_code)
    if project_record is None:
        return None, ()
    from app.persistence.capex_sub_lines import (
        list_sub_lines_for_project,
    )
    with get_cursor() as cur:
        sub_lines = list_sub_lines_for_project(
            cur,
            project_record.project_id,
            include_inactive=include_inactive_sub_lines,
        )
    return project_record, sub_lines


def get_project_by_id_with_sub_lines(
    project_id: str,
    user_id: str,
    include_inactive_sub_lines: bool = False,
) -> "tuple[Optional[Any], tuple[Any, ...]]":
    """Same as ``get_project_with_sub_lines`` but by ``project_id``."""
    from app.persistence.capex_sub_lines import (
        list_sub_lines_for_project,
    )
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM projects WHERE project_id=? AND user_id=?",
            (project_id, user_id),
        )
        row = cur.fetchone()
    if row is None:
        return None, ()
    from app.persistence.records import ProjectRecord
    project_record = ProjectRecord.from_row(row)
    with get_cursor() as cur:
        sub_lines = list_sub_lines_for_project(
            cur,
            project_id,
            include_inactive=include_inactive_sub_lines,
        )
    return project_record, sub_lines
