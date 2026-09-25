"""Project Library Service — Reference Models and Working Copies.

Public API
----------
ensure_reference_models()
    Idempotent bootstrap: create Generic Wind Reference and Generic Solar Reference
    under the system sentinel user_id ``__reference__`` if they do not
    already exist.  Safe to call on every application startup.

ensure_reference_canonical_last_runs()
    Idempotent post-bootstrap step: run the canonical financial engine for each
    cloneable reference (Solar, Wind, Data Center) if no last-run result has
    been persisted yet.  Storage is deliberately excluded (runtime not released).
    Safe to call on every application startup after ensure_reference_models().

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
    _generic_reference_keys = ("generic_wind_reference", "generic_solar_reference", "generic_storage_reference", "generic_data_center_reference")
    if origin == "factory_template" and (
        ts in _generic_reference_keys or spt in _generic_reference_keys
    ):
        return True
    return False


# ---------------------------------------------------------------------------
# Strict clone authorization
# ---------------------------------------------------------------------------

# All canonical reference template sources — includes types not yet cloneable.
# Used by _is_canonical_reference() to verify a protected reference row.
CANONICAL_REFERENCE_TEMPLATE_SOURCES = frozenset({
    "generic_wind_reference",
    "generic_solar_reference",
    "generic_storage_reference",
    "generic_data_center_reference",
})

# Subset of CANONICAL_REFERENCE_TEMPLATE_SOURCES for which working-copy
# creation is currently supported.  Storage remains canonical-but-not-cloneable
# until Storage Runtime V1 is released.
CLONEABLE_TEMPLATE_SOURCES = frozenset({
    "generic_wind_reference",
    "generic_solar_reference",
    "generic_data_center_reference",
})


def _is_canonical_reference(source) -> bool:
    """Return True iff source is a fully-explicit canonical protected reference.

    Uses CANONICAL_REFERENCE_TEMPLATE_SOURCES (not CLONEABLE_TEMPLATE_SOURCES)
    so that Storage remains a canonical protected reference even though its
    working-copy runtime is not yet supported.

    This is stricter than is_protected_reference() which accepts legacy
    composite combinations.  For clone authorization we require the full
    explicit contract so that user-owned factory_template rows (pre-migration)
    cannot be cloned via this service.
    """
    return (
        getattr(source, "user_id", None) == "__reference__"
        and getattr(source, "project_role", None) == "reference"
        and bool(getattr(source, "is_protected", False))
        and getattr(source, "template_source", None) in CANONICAL_REFERENCE_TEMPLATE_SOURCES
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
    {
        "template_source": "generic_data_center_reference",
        "project_type": "Data Center",
        "display_name": "Generic Data Center Reference",
        "project_code": "generic_data_center_reference-reference",
        "factory": "create_generic_data_center_reference",
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


# Template sources that receive a canonical last run at startup.
# Storage is deliberately excluded — its working-copy runtime is not released.
_CANONICAL_LAST_RUN_SOURCES = frozenset({
    "generic_solar_reference",
    "generic_wind_reference",
    "generic_data_center_reference",
})

# Maps template_source → project_type string consumed by run_project().
# These map to the factory-lookup keys inside run_project._run_project_impl.
_TEMPLATE_SOURCE_TO_RUN_PROJECT_TYPE = {
    "generic_solar_reference": "Generic Solar Reference",
    "generic_wind_reference": "Generic Wind Reference",
    "generic_data_center_reference": "Generic Data Center Reference",
}


def _reference_current_composite_hash(record) -> "Optional[str]":
    """Compute the composite workbook identity hash for a canonical reference.

    Returns None on any identity-assembly failure (fail-open: treat as unknown,
    let the caller decide whether to re-seed or skip).
    """
    try:
        from app.workbook.registry import WORKBOOK
        from app.workbook.workbook_identity import assemble_consistent_for_get
        identity = assemble_consistent_for_get(record.user_id, record.project_id, WORKBOOK.version)
        return identity.composite_hash
    except Exception:
        return None


def ensure_reference_canonical_last_runs() -> list[str]:
    """Idempotent: seed a canonical engine last-run for each cloneable reference.

    For each reference in _CANONICAL_LAST_RUN_SOURCES:
      1. Compute the current composite workbook identity hash.
      2. Skip if the workspace already has a matching last_runtime_composite_hash
         (same canonical inputs, same workbook version — already current).
      3. Invoke run_project() to get the full canonical runtime payload.
      4. Persist via v2_atomic_run_commit() — same modern persistence path as
         a normal user Run (composite hash bound, full schedule artifacts).

    Idempotency / invalidation contract:
      - NO-OP when last_runtime_composite_hash == current composite hash.
      - Re-seeds when workbook version bumps, factory snapshot changes, or
        any component of the composite identity changes.
      - Re-seeds when provenance is missing or hash is absent.

    Returns a list of template_source strings for which a new last-run was seeded.
    Safe to call on every startup after ensure_reference_models().
    """
    seeded = []
    for defn in _REFERENCE_DEFINITIONS:
        ts = defn["template_source"]
        if ts not in _CANONICAL_LAST_RUN_SOURCES:
            continue
        try:
            record = get_reference_by_template_source(ts)
            if record is None:
                continue
            current_hash = _reference_current_composite_hash(record)
            ws = get_workspace_state(record.user_id, record.project_id)
            stored_hash = getattr(ws, "last_runtime_composite_hash", None) if ws else None
            if current_hash and stored_hash and stored_hash == current_hash:
                # Last run is bound to the current canonical identity — skip.
                continue
            _seed_reference_last_run(record, defn, current_composite_hash=current_hash)
            seeded.append(ts)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "ensure_reference_canonical_last_runs: could not seed last-run "
                "for %s: %s: %s", ts, type(exc).__name__, exc,
            )
    return seeded


def _seed_reference_last_run(record, defn: dict, *, current_composite_hash: "Optional[str]") -> None:
    """Execute the canonical engine for one reference and persist the full last-run.

    Uses run_project() so the full normal runtime payload (financial_statements,
    debt_schedule, tax_schedule, distribution_schedule, sponsor_schedule) is
    produced through the existing presentation adapters — no second calculator.

    Persists via v2_atomic_run_commit() which binds the result to the current
    composite workbook identity and sets last_runtime_composite_hash.  This
    ensures the modern freshness authority (resolve_runtime_freshness) classifies
    the reference as CURRENT rather than falling back to the legacy scalar path.

    DC gearing semantics: persists actual_gearing_pct and gearing_cap_pct as
    distinct fields so callers can display the correct value.  Does NOT use
    gearing_ratio as a field name since that value is the cap constraint.
    """
    from datetime import datetime, timezone

    from app.api.project_runner import run_project
    from app.persistence.workspace_repository import v2_atomic_run_commit
    from app.persistence.projects_repository import _compute_baseline_snapshot
    from app.services.production_financial_authority import run_clean_production

    ts = defn["template_source"]
    run_project_type = _TEMPLATE_SOURCE_TO_RUN_PROJECT_TYPE[ts]

    # Full canonical runtime via the same run_project() path the production UI uses.
    payload = run_project(run_project_type, "Base")
    runtime_kpis = dict(payload["kpis"])

    # DC gearing semantics — resolve actual vs cap. run_project() omits gearing
    # from kpis; add both clearly-labelled fields for downstream display authority.
    # For all references: compute actual_gearing from senior_commitment / capex.
    try:
        factory_fn = _get_factory(defn["factory"])
        pi = factory_fn()
        clean = run_clean_production(pi, "Base", project_type=run_project_type.split(" Reference")[0])
        fr = clean.g2c_result.financing_result
        capex_total = pi.capex.total_capex
        if capex_total and capex_total > 0:
            runtime_kpis["actual_gearing_pct"] = fr.final_senior_commitment_keur / capex_total
        runtime_kpis["gearing_cap_pct"] = getattr(fr, "gearing_ratio", None)
        runtime_kpis["senior_debt_keur"] = getattr(fr, "final_senior_commitment_keur", None)
    except Exception:
        pass

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat().replace(":", "").replace("-", "")
    runtime_snapshot_id = f"canonical_last_run__{ts}__{now_iso}"

    snapshot = _compute_baseline_snapshot(defn["project_type"], ts)

    ws = get_workspace_state(record.user_id, record.project_id)
    active_scenario_id = getattr(ws, "active_scenario_id", None) if ws else None
    active_scenario_name = getattr(ws, "active_scenario_name", None) if ws else None

    if current_composite_hash is None:
        # Composite hash unavailable — fall back to record_workspace_runtime so
        # at least the KPIs and schedules are persisted even without the V2 hash.
        from app.persistence.repository import record_workspace_runtime
        record_workspace_runtime(
            user_id=record.user_id,
            project_id=record.project_id,
            project_code=record.project_code,
            runtime_snapshot=snapshot,
            runtime_summary=runtime_kpis,
            runtime_snapshot_id=runtime_snapshot_id,
            runtime_origin="canonical_reference_last_run",
            governance_state=record.governance_state,
            financial_statements=payload.get("financial_statements"),
            debt_schedule=payload.get("debt_schedule"),
            tax_schedule=payload.get("tax_schedule"),
            distribution_schedule=payload.get("distribution_schedule"),
            sponsor_schedule=payload.get("sponsor_schedule"),
            replay_metadata={
                "origin": "canonical_reference_last_run",
                "composite_hash_source": "unavailable",
                "template_source": ts,
                "factory": defn["factory"],
                "seeded_at": now.isoformat(),
                "reference_project_id": record.project_id,
                "reference_project_code": record.project_code,
            },
        )
        return

    # V2 atomic commit — binds last_runtime_composite_hash to current canonical identity.
    v2_atomic_run_commit(
        user_id=record.user_id,
        project_id=record.project_id,
        project_code=record.project_code,
        expected_composite_hash=current_composite_hash,
        runtime_snapshot_id=runtime_snapshot_id,
        runtime_origin="canonical_reference_last_run",
        runtime_summary=runtime_kpis,
        financial_statements=payload.get("financial_statements"),
        debt_schedule=payload.get("debt_schedule"),
        tax_schedule=payload.get("tax_schedule"),
        distribution_schedule=payload.get("distribution_schedule"),
        sponsor_schedule=payload.get("sponsor_schedule"),
        active_scenario_id=active_scenario_id,
        active_scenario_name=active_scenario_name,
        ran_at=now,
    )
    # v2_atomic_run_commit does not accept replay_metadata; persist provenance separately.
    import json as _json
    from app.persistence.db import get_cursor
    _provenance = {
        "origin": "canonical_reference_last_run",
        "composite_hash_source": "v2_atomic",
        "template_source": ts,
        "factory": defn["factory"],
        "seeded_at": now.isoformat(),
        "reference_project_id": record.project_id,
        "reference_project_code": record.project_code,
    }
    with get_cursor() as _cur:
        _cur.execute(
            "UPDATE workspace_states SET replay_metadata_json=? WHERE user_id=? AND project_id=?",
            (_json.dumps(_provenance, sort_keys=True), record.user_id, record.project_id),
        )


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
    # Step 1b — canonical authorization first (before cloneability check).
    # A non-reference source (user-owned project, arbitrary ID) must never reach
    # the cloneability path.  An arbitrary user-owned Storage project ID must not
    # receive the "reference model still available for viewing" message.
    if not _is_canonical_reference(source):
        raise ValueError(
            f"Project {source_reference_id!r} (role={getattr(source, 'project_role', None)!r}) "
            "is not a canonical reference model and cannot be cloned via this service."
        )
    # Step 1c — cloneability check.
    # Canonical references whose runtime is not yet supported raise a typed
    # UnsupportedProjectRuntimeError so the clone route can return a helpful
    # 400 response.  The reference itself remains viewable.
    if getattr(source, "template_source", None) not in CLONEABLE_TEMPLATE_SOURCES:
        _source_type = (getattr(source, "project_type", "") or "").strip()
        raise UnsupportedProjectRuntimeError(_source_type)

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
