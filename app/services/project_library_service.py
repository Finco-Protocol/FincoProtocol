"""Project Library Service — Reference Models and Working Copies.

Public API
----------
ensure_reference_models()
    Idempotent bootstrap: create Generic Wind Reference and Generic Solar Reference
    under the system sentinel user_id ``__reference__`` if they do not
    already exist.  Safe to call on every application startup.

create_working_copy(user_id, source_reference_id, requested_name=None)
    Clone a reference project into a new user-owned working copy.
    Returns the new ProjectRecord.

assert_project_not_protected(project_record)
    Raise ProtectedProjectError (HTTP 403) if the project is a
    reference.  Call this at the start of every mutation route.

is_protected_reference(project_record)
    Return True for any project with project_role='reference' OR the
    legacy factory_template + generic_wind_reference/generic_solar_reference composite.
"""
from __future__ import annotations

import uuid
from typing import Optional

from app.persistence.projects_repository import (
    REFERENCE_USER_ID,
    get_project_by_id,
    get_reference_by_template_source,
    list_recent_projects,
    save_project,
)
from app.persistence.workspace_repository import (
    save_workspace_state,
    get_workspace_state,
)
from app.persistence.scenarios_repository import (
    get_or_create_base_case_scenario,
)
from app.persistence._helpers import _now_utc, _to_json


class ProtectedProjectError(Exception):
    """Raised when a mutation is attempted on a protected reference project."""
    def __init__(self, project_name: str = ""):
        self.project_name = project_name
        super().__init__(f"Project '{project_name}' is a protected reference and cannot be modified.")


class UnsupportedProjectRuntimeError(Exception):
    """Raised when a clone is requested for a project type whose user-project
    runtime is not yet supported.  The reference remains available for viewing;
    only working-copy creation is blocked until the corresponding runtime phase
    is formally released.
    """
    def __init__(self, project_type: str = ""):
        self.project_type = project_type
        super().__init__(
            f"{project_type} working-copy runtime is not yet supported. "
            "The reference model is still available for viewing."
        )


class ReferenceBootstrapError(RuntimeError):
    """Raised when the canonical-reference bootstrap cannot resolve a
    uniqueness conflict to a winning canonical record.

    The previous behaviour silently returned ``None`` after a
    uniqueness conflict, which let ``ensure_reference_models()`` keep
    going with one missing canonical reference. The new contract is
    fail-closed: if the conflict cannot be re-resolved to a
    canonical winning record, raise this error so the caller knows
    the bootstrap is in an unrecoverable state.
    """


# ---------------------------------------------------------------------------
# Helper: is_protected_reference
# ---------------------------------------------------------------------------

def is_protected_reference(project_record) -> bool:
    """True if the project is a protected reference.

    Accepts the new explicit ``project_role='reference'`` flag as the
    primary signal, and falls back to the legacy
    ``project_origin='factory_template' + template_source in {generic_wind_reference,generic_solar_reference}``
    combination for rows that were not yet backfilled.
    """
    if project_record is None:
        return False
    role = getattr(project_record, "project_role", None)
    if role == "reference":
        return True
    is_p = getattr(project_record, "is_protected", False)
    if is_p:
        return True
    # Legacy composite check (backfill may not have run yet in unit-test DBs)
    origin = getattr(project_record, "project_origin", None)
    ts = getattr(project_record, "template_source", None)
    spt = getattr(project_record, "source_project_template", None)
    if origin == "factory_template" and (
        ts in ("generic_wind_reference", "generic_solar_reference", "generic_storage_reference") or spt in ("generic_wind_reference", "generic_solar_reference", "generic_storage_reference")
    ):
        return True
    return False


# ---------------------------------------------------------------------------
# Strict clone authorization
# ---------------------------------------------------------------------------

CLONEABLE_TEMPLATE_SOURCES = frozenset({"generic_wind_reference", "generic_solar_reference"})


def _is_canonical_reference(source) -> bool:
    """Strict clone authorization — source must satisfy ALL criteria.

    This is stricter than is_protected_reference() which accepts legacy
    composite combinations.  For cloning, we require the full explicit
    contract so that user-owned factory_template rows (pre-migration)
    cannot be cloned via this service.
    """
    return (
        getattr(source, "user_id", None) == "__reference__"
        and getattr(source, "project_role", None) == "reference"
        and bool(getattr(source, "is_protected", False))
        and getattr(source, "template_source", None) in CLONEABLE_TEMPLATE_SOURCES
        and not bool(getattr(source, "archived", True))
    )


# ---------------------------------------------------------------------------
# Mutation guard
# ---------------------------------------------------------------------------

def assert_project_not_protected(project_record) -> None:
    """Raise ProtectedProjectError if this is a reference project."""
    if is_protected_reference(project_record):
        raise ProtectedProjectError(getattr(project_record, "project_name", ""))


# ---------------------------------------------------------------------------
# Reference models: canonical bootstrap definitions
# ---------------------------------------------------------------------------

_REFERENCE_DEFINITIONS = [
    {
        "template_source": "generic_wind_reference",
        "project_type": "Wind",
        "display_name": "Generic Wind Reference",
        "project_code": "generic_wind_reference-reference",
        "factory": "create_generic_wind_reference",
    },
    {
        "template_source": "generic_solar_reference",
        "project_type": "Solar",
        "display_name": "Generic Solar Reference",
        "project_code": "generic_solar_reference-reference",
        "factory": "create_generic_solar_reference",
    },
    {
        "template_source": "generic_storage_reference",
        "project_type": "Storage",
        "display_name": "Generic Storage Reference",
        "project_code": "generic_storage_reference-reference",
        "factory": "create_generic_storage_reference",
    },
]


def _get_factory(factory_name: str):
    from app import project_factories
    return getattr(project_factories, factory_name)


def ensure_reference_models() -> list:
    """Idempotent bootstrap: create Generic Wind Reference and Generic Solar Reference
    under the system sentinel user_id if they do not already exist.

    One canonical reference per template_source.  Repeated calls are safe.
    Always ensures workspace and base-case scenario exist (self-healing).
    Returns a list of newly-created ProjectRecords (empty if both existed).
    """
    created = []
    for defn in _REFERENCE_DEFINITIONS:
        was_existing = get_reference_by_template_source(defn["template_source"]) is not None
        record = _ensure_reference_project(defn)
        if record is None:
            continue
        _ensure_reference_workspace_and_scenario(record, defn)
        if not was_existing:
            created.append(record)
    return created


def _ensure_reference_project(defn: dict):
    """Get or create the canonical project record. Returns the record.

    Fail-closed contract for ``IntegrityError`` (typically a
    uniqueness conflict on
    ``ux_projects_canonical_reference_source``):

    1. Re-fetch the canonical winning record.
    2. If the winning record satisfies the full canonical contract
       (``_is_canonical_reference``), return it.
    3. Otherwise raise :class:`ReferenceBootstrapError` with a clear
       message identifying the template source. The caller
       (``ensure_reference_models``) propagates the error so a
       partial bootstrap never silently continues.
    """
    template_source = defn["template_source"]
    existing = get_reference_by_template_source(template_source)
    if existing is not None:
        return existing
    try:
        factory_fn = _get_factory(defn["factory"])
        project_inputs = factory_fn()
        snapshot = _build_reference_snapshot(project_inputs, defn)
        record = save_project(
            user_id=REFERENCE_USER_ID,
            project_code=defn["project_code"],
            project_name=defn["display_name"],
            source_project_template=template_source,
            project_type=defn["project_type"],
            project_origin="factory_template",
            template_source=template_source,
            baseline_snapshot=snapshot,
            is_readonly=True,
            is_protected=True,
            project_role="reference",
            governance_state={
                "g20": "BLOCKED",
                "r99_r102": "NOT_APPROVED",
                "lender_ready": False,
                "reference_model": True,
            },
            replay_metadata={
                "factory": defn["factory"],
                "bootstrapped_at": _now_utc().isoformat(),
                "reference": True,
            },
        )
        return record
    except Exception as _exc:
        # Use type name to avoid importing sqlite3 at module level
        # (guardrail: no direct DB imports outside persistence layer).
        if type(_exc).__name__ != "IntegrityError":
            raise
        # Concurrent bootstrap: re-fetch the winning record.
        winner = get_reference_by_template_source(template_source)
        if winner is not None and _is_canonical_reference(winner):
            return winner
        # Conflict cannot be resolved to a canonical winning record.
        # Do NOT silently continue with a missing reference.
        raise ReferenceBootstrapError(
            f"Canonical {template_source} reference could not be "
            f"resolved after a uniqueness conflict. A conflicting "
            f"row exists that is not a canonical reference, or no "
            f"winning record could be re-fetched. Inspect the "
            f"``projects`` table for template_source='{template_source}'."
        ) from _exc


def _ensure_reference_workspace_and_scenario(record, defn: dict) -> None:
    """Idempotently ensure workspace and base scenario exist for a reference."""
    from app.persistence.projects_repository import _compute_baseline_snapshot
    snapshot = _compute_baseline_snapshot(defn["project_type"], defn["template_source"])

    ws = get_workspace_state(record.user_id, record.project_id)
    if ws is None:
        save_workspace_state(
            user_id=record.user_id,
            project_id=record.project_id,
            project_code=record.project_code,
            draft_snapshot=snapshot,
            saved_snapshot=snapshot,
            last_runtime_snapshot={},
            last_runtime_summary={},
            governance_state=record.governance_state,
        )

    get_or_create_base_case_scenario(
        record.user_id,
        record.project_id,
        record.project_code,
        record.project_name,
        defn["project_type"],
        defn["template_source"],
        snapshot,
        record.governance_state,
    )


def _build_reference_snapshot(project_inputs, defn: dict) -> dict:
    """Build a workspace-ready snapshot dict for a reference project."""
    from app.persistence.projects_repository import _compute_baseline_snapshot
    return _compute_baseline_snapshot(defn["project_type"], defn["template_source"])


def _init_reference_workspace(record, project_inputs, snapshot: dict, defn: dict) -> None:
    """Backward-compat shim — delegates to _ensure_reference_workspace_and_scenario."""
    _ensure_reference_workspace_and_scenario(record, defn)


# ---------------------------------------------------------------------------
# Working copy creation
# ---------------------------------------------------------------------------

def create_working_copy(
    user_id: str,
    source_reference_id: str,
    requested_name: Optional[str] = None,
) -> "ProjectRecord":
    """Clone a reference project into a new user-owned working copy.

    Steps:
    1. Authorize: source must be a valid reference (project_role='reference').
    2. Compute a unique name for the user (deterministic suffix if taken).
    3. Create project record with project_role='working_copy', source_project_id.
    4. Copy source workspace snapshot.
    5. Initialize independent workspace_state + base-case scenario.
    6. Return the new ProjectRecord.
    """
    from app.persistence.projects_repository import (
        list_project_records,
        get_project_by_code,
    )

    # Step 1 — verify source is a canonical reference
    source = get_project_by_id(source_reference_id)
    if source is None:
        raise ValueError(f"Source project {source_reference_id!r} not found.")
    # Unsupported-runtime guard: block Storage clones before touching any rows.
    # The Storage reference remains viewable; only working-copy creation is blocked
    # until a dedicated Storage runtime phase is formally released.
    _source_type = (getattr(source, "project_type", "") or "").strip()
    if _source_type.lower() == "storage":
        raise UnsupportedProjectRuntimeError(_source_type)
    if not _is_canonical_reference(source):
        raise ValueError(
            f"Project {source_reference_id!r} (role={getattr(source, 'project_role', None)!r}) "
            "is not a canonical reference model and cannot be cloned via this service."
        )

    # Step 2 — determine default name
    if requested_name:
        base_name = requested_name
    else:
        # e.g. "Generic Wind Reference" → "Generic Wind Working Copy"
        base_name = source.project_name.replace(" Reference", " Working Copy")
        if "Working Copy" not in base_name:
            base_name = f"{source.project_name} Working Copy"

    # Step 3 — pick a unique name/code for this user
    display_name, project_code = _unique_project_name(user_id, base_name)

    # Step 4 — copy source workspace snapshot
    src_ws = get_workspace_state(source.user_id, source.project_id)
    snapshot = (src_ws.saved_snapshot if src_ws else source.baseline_snapshot) or {}
    snapshot = dict(snapshot)
    snapshot["project_origin"] = "user_created"
    snapshot["project_name"] = display_name
    snapshot["active_project"] = project_code

    now = _now_utc()
    record = save_project(
        user_id=user_id,
        project_code=project_code,
        project_name=display_name,
        source_project_template=source.template_source or source.source_project_template,
        project_type=source.project_type,
        project_origin="user_created",
        template_source=source.template_source,
        baseline_snapshot=snapshot,
        is_readonly=False,
        is_protected=False,
        project_role="working_copy",
        source_project_id=source.project_id,
        governance_state={"g20": "BLOCKED", "r99_r102": "NOT_APPROVED", "lender_ready": False},
        replay_metadata={
            "cloned_from_project_id": source.project_id,
            "cloned_from_project_code": source.project_code,
            "cloned_at": now.isoformat(),
        },
    )

    # Step 5 — initialize independent workspace + scenario
    save_workspace_state(
        user_id=user_id,
        project_id=record.project_id,
        project_code=project_code,
        draft_snapshot=snapshot,
        saved_snapshot=snapshot,
        last_runtime_snapshot={},
        last_runtime_summary={},
        governance_state=record.governance_state,
    )
    get_or_create_base_case_scenario(
        user_id,
        record.project_id,
        project_code,
        display_name,
        source.project_type or "Solar",
        record.template_source or record.source_project_template,
        snapshot,
        record.governance_state,
    )

    return record


def _unique_project_name(user_id: str, base_name: str) -> tuple[str, str]:
    """Return (display_name, project_code) that are unique for this user."""
    from app.persistence.projects_repository import get_project_by_code

    def _slugify(name: str) -> str:
        import re
        slug = name.lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
        return slug[:60]

    candidate_name = base_name
    candidate_code = _slugify(base_name)
    suffix = 2
    while get_project_by_code(user_id, candidate_code) is not None:
        candidate_name = f"{base_name} {suffix}"
        candidate_code = _slugify(candidate_name)
        suffix += 1
        if suffix > 100:
            candidate_code = f"{_slugify(base_name)}-{uuid.uuid4().hex[:6]}"
            candidate_name = f"{base_name} ({candidate_code[-6:]})"
            break

    return candidate_name, candidate_code
