"""STAB-1B — Composite Workbook V2 Identity.

Single canonical assembler for the full engine-effective workbook state.

Problem
-------
Before STAB-1B, ``ProjectInputSet.content_hash`` was a SHA-256 over scalar
snapshot values only.  Two workbooks could share the same scalar hash while
producing different engine outputs if they had different CAPEX/OPEX custom
sub-lines or were running under different scenarios.

Solution
--------
``CompositeWorkbookIdentity`` assembles one deterministic hash over five
axes:

1. Scalar state      — canonical ``ProjectInputSet`` scalar snapshot
2. CAPEX rows        — every active custom sub-line (engine-effective fields only)
3. OPEX rows         — every active custom sub-line (engine-effective fields only)
4. Scenario state    — active scenario identity + all effective overrides
5. Registry version  — ``WORKBOOK.version`` so schema changes rotate the hash

Include / exclude policy (by axis)
-----------------------------------
Scalar  — all fields that reach the adapter (``snapshot_origin`` non-empty
          values + provenance keys + workbook version).  Unknown legacy keys
          are included if non-empty because they may affect legacy adapter
          materialisation.

CAPEX   — ``sub_line_id``, ``parent_category_code``, ``amount_keur``.
          ``schedule_json`` is omitted: it is decomposed from ``amount_keur``
          by the schedule calculator; hashing ``amount_keur`` covers the same
          financial meaning without schedule-format variance.
          Excluded: ``label``, ``comments``, ``business_code``, ``source``,
          ``governance_state``, ``replay_metadata``, ``created_at``,
          ``updated_at``, ``id``, ``display_order``.

OPEX    — ``sub_line_id``, ``parent_group_code``, ``business_code``,
          ``amount_keur``, ``inflation_pct``.  ``business_code`` is included
          because it becomes the ``OpexItem.name`` seen by downstream code
          (though it does not affect numeric KPIs, naming uniqueness is an
          invariant).
          Excluded: ``label``, ``comments``, ``source``, ``created_at``,
          ``updated_at``, ``id``, ``display_order``.

Scenario — ``scenario_id`` (stable identity) and every key in
           ``overrides_json`` including the reserved opaque keys
           ``_capex_sub_line_overrides`` and ``_opex_sub_line_overrides``.
           ``scenario_name`` is EXCLUDED: renaming a scenario is
           presentation-only and does not affect the financial model.
           Engine identity rotates on: active scenario_id, effective
           overrides, and schema/version state.
           Excluded: ``scenario_name``, ``base_input_set`` (redundant —
           covered by Scalar axis), timestamps, audit fields.

Registry — ``WORKBOOK.version`` (already included via Scalar axis; also
           stored as explicit registry_version key so registry-only changes
           are visible even when scalar snapshot is unchanged).

Ordering / determinism
-----------------------
CAPEX rows are sorted by ``sub_line_id`` (UUID) — independent of
``display_order`` so presentation reorders do not affect identity.
OPEX rows are sorted by ``sub_line_id``.
Scenario ``overrides_json`` is sorted recursively.

Reorder semantics
-----------------
``display_order`` is presentation-only for both CAPEX and OPEX:
the engine folds rows purely by amount/type, commutatively.
Reordering rows MUST NOT change the composite identity.

Legacy migration
----------------
Scalar-only hashes stored before STAB-1B will not match the composite hash
even when all row tables are empty, because the composite hash includes an
explicit ``_schema: "composite_v1"`` discriminator key that scalar-only
hashes lack.

Transition: ``v2_atomic_draft_update`` re-derives the composite hash from
the live state on every CAS check.  Old scalar-only tokens stored in
``draft_content_hash`` are never consulted for the gating comparison
(the column is updated on every successful write, migrating in-place).

A legacy token submitted by a client that loaded before STAB-1B will be
rejected with a normal 409 StaleContentError — the user refreshes and
gets a composite token.  This is the correct behaviour: the workbook state
on disk has not changed, but the identity representation has been upgraded.

Fail-closed contract
--------------------
All DB reads in this module raise ``WorkbookIdentityError`` on any
persistence/schema/parse failure.  Callers must not proceed with mutation
or hash emission after a ``WorkbookIdentityError``.

A missing project (no rows) is NOT a failure — it returns an empty tuple
or base-case scenario.  Only actual DB/schema/parse errors raise.

Transactional consistency
--------------------------
``assemble_consistent_for_get`` reads all four sources (workspace snapshot,
CAPEX rows, OPEX rows, active scenario) inside a single ``BEGIN DEFERRED``
transaction, giving a consistent point-in-time snapshot.  Use this function
for all GET and HTMX rendering paths.

``assemble_transactional`` (used by ``v2_atomic_draft_update`` and
``_exclusive_tx`` in CAPEX/OPEX commands) takes a SQLite connection cursor
that already holds a ``BEGIN EXCLUSIVE`` lock — it reads all three tables
inside that lock window, closing the race.

``assemble_for_workspace`` is kept for backward compatibility and for
contexts where a workspace record has already been loaded, but callers
should prefer ``assemble_consistent_for_get`` for the GET path.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

# Discriminator key — absent from pre-STAB-1B scalar-only hashes, so a
# composite hash is never mistaken for a legacy hash.
_SCHEMA_VERSION = "composite_v1"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class WorkbookIdentityError(RuntimeError):
    """Raised when composite workbook identity cannot be assembled.

    Signals a DB, schema, or parse failure during identity computation.
    Callers MUST NOT proceed with mutation or hash emission after catching
    this error.  The transaction must be rolled back.

    A missing/empty project (no rows) is NOT a WorkbookIdentityError —
    that case returns an empty tuple or base-case scenario normally.
    Only actual persistence failures raise this exception.
    """


# ---------------------------------------------------------------------------
# Canonical row types (engine-effective fields only)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, order=True)
class CanonicalCapexRow:
    """Engine-effective CAPEX sub-line fingerprint."""
    sub_line_id: str
    parent_category_code: str
    amount_keur: float


@dataclass(frozen=True, order=True)
class CanonicalOpexRow:
    """Engine-effective OPEX sub-line fingerprint."""
    sub_line_id: str
    parent_group_code: str
    business_code: str
    amount_keur: float
    inflation_pct: float


@dataclass(frozen=True)
class CanonicalScenarioState:
    """Engine-effective scenario identity.

    ``scenario_name`` is stored for display/logging purposes but is NOT
    included in the hash payload — renaming a scenario is presentation-only
    and does not affect the financial model.
    """
    scenario_id: Optional[str]      # None → Base Case (no active scenario)
    scenario_name: Optional[str]    # display only; excluded from hash
    overrides: Mapping[str, Any]    # full overrides_json dict, including reserved keys

    def to_payload(self) -> dict:
        """Deterministic serialisable form for hash computation.

        ``scenario_name`` is intentionally excluded: rename is
        presentation-only and must not rotate the identity hash.
        """
        return {
            "scenario_id": self.scenario_id or "",
            "overrides": _sort_dict_recursive(dict(self.overrides)),
        }


# ---------------------------------------------------------------------------
# Identity payload
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CompositeWorkbookIdentity:
    """Full engine-effective workbook state identity for Workbook V2.

    Construct via ``assemble_consistent_for_get()``, ``assemble_for_workspace()``,
    or ``assemble_from_parts()``.
    """
    workbook_version: str
    scalar_snapshot: Mapping[str, str]    # non-empty snapshot_origin values
    template_source: str
    project_origin: str
    capex_rows: tuple[CanonicalCapexRow, ...]
    opex_rows: tuple[CanonicalOpexRow, ...]
    scenario: CanonicalScenarioState
    composite_hash: str                   # SHA-256 of the full payload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sort_dict_recursive(d: Any) -> Any:
    """Recursively sort dict keys for deterministic serialisation."""
    if isinstance(d, dict):
        return {k: _sort_dict_recursive(d[k]) for k in sorted(d)}
    if isinstance(d, (list, tuple)):
        return [_sort_dict_recursive(i) for i in d]
    return d


def _compute_composite_hash(
    workbook_version: str,
    scalar_snapshot: Mapping[str, str],
    template_source: str,
    project_origin: str,
    capex_rows: Sequence[CanonicalCapexRow],
    opex_rows: Sequence[CanonicalOpexRow],
    scenario: CanonicalScenarioState,
) -> str:
    """Deterministic SHA-256 over the full composite workbook state.

    The ``_schema`` key is a discriminator that ensures composite hashes
    can never collide with pre-STAB-1B scalar-only hashes.

    ``scenario_name`` is NOT included: see CanonicalScenarioState.to_payload().
    """
    payload: dict[str, Any] = {
        "_schema": _SCHEMA_VERSION,
        "_workbook_version": workbook_version,
        "_template_source": template_source,
        "_project_origin": project_origin,
        "scalar": {
            f"snap:{k}": v
            for k, v in sorted(scalar_snapshot.items())
            if v
        },
        "capex_rows": [
            {
                "sub_line_id": r.sub_line_id,
                "parent_category_code": r.parent_category_code,
                "amount_keur": r.amount_keur,
            }
            for r in sorted(capex_rows)
        ],
        "opex_rows": [
            {
                "sub_line_id": r.sub_line_id,
                "parent_group_code": r.parent_group_code,
                "business_code": r.business_code,
                "amount_keur": r.amount_keur,
                "inflation_pct": r.inflation_pct,
            }
            for r in sorted(opex_rows)
        ],
        "scenario": scenario.to_payload(),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Row loaders — fail-closed: DB/schema/parse errors raise WorkbookIdentityError
# ---------------------------------------------------------------------------

def _load_canonical_capex_rows(project_id: str) -> tuple[CanonicalCapexRow, ...]:
    """Load active CAPEX sub-lines and extract engine-effective fields.

    Returns an empty tuple when the project has no active CAPEX rows.
    Raises WorkbookIdentityError on any DB/schema/parse failure.
    """
    if not project_id:
        return ()
    try:
        from app.persistence.capex_sub_lines import get_active_sub_lines_for_project
        rows = get_active_sub_lines_for_project(project_id)
        return tuple(
            CanonicalCapexRow(
                sub_line_id=r.sub_line_id,
                parent_category_code=r.parent_category_code,
                amount_keur=float(r.amount_keur),
            )
            for r in rows
        )
    except WorkbookIdentityError:
        raise
    except Exception as exc:
        logger.exception("STAB-1B: failed to load CAPEX rows; project_id=%s", project_id)
        raise WorkbookIdentityError(
            f"CAPEX row read failed for project {project_id!r}: {exc}"
        ) from exc


def _load_canonical_opex_rows(project_id: str) -> tuple[CanonicalOpexRow, ...]:
    """Load active OPEX sub-lines and extract engine-effective fields.

    Returns an empty tuple when the project has no active OPEX rows.
    Raises WorkbookIdentityError on any DB/schema/parse failure.
    """
    if not project_id:
        return ()
    try:
        from app.persistence.opex_sub_lines import get_active_sub_lines_for_project
        rows = get_active_sub_lines_for_project(project_id)
        return tuple(
            CanonicalOpexRow(
                sub_line_id=r.sub_line_id,
                parent_group_code=r.parent_group_code,
                business_code=r.business_code,
                amount_keur=float(r.amount_keur),
                inflation_pct=float(r.inflation_pct),
            )
            for r in rows
        )
    except WorkbookIdentityError:
        raise
    except Exception as exc:
        logger.exception("STAB-1B: failed to load OPEX rows; project_id=%s", project_id)
        raise WorkbookIdentityError(
            f"OPEX row read failed for project {project_id!r}: {exc}"
        ) from exc


def _canonical_scenario(
    active_scenario_id: Optional[str],
    active_scenario_name: Optional[str],
    user_id: str,
) -> CanonicalScenarioState:
    """Load and canonicalise the active scenario.

    Returns a base-case (empty overrides) state when no scenario is active.
    Raises WorkbookIdentityError when a scenario_id is set but DB/parse fails.
    """
    if not active_scenario_id:
        return CanonicalScenarioState(
            scenario_id=None,
            scenario_name=None,
            overrides={},
        )
    try:
        from app.persistence.scenarios_repository import get_scenario
        rec = get_scenario(active_scenario_id, user_id)
        if rec is None:
            # Scenario row gone — treat as if no scenario is active.
            # This is a legitimate state (scenario was deleted) not a read failure.
            logger.warning(
                "STAB-1B: active scenario %s not found; treating as base case",
                active_scenario_id,
            )
            return CanonicalScenarioState(
                scenario_id=active_scenario_id,
                scenario_name=active_scenario_name,
                overrides={},
            )
        return CanonicalScenarioState(
            scenario_id=rec.scenario_id,
            scenario_name=rec.scenario_name,
            overrides=dict(rec.overrides or {}),
        )
    except WorkbookIdentityError:
        raise
    except Exception as exc:
        logger.exception(
            "STAB-1B: failed to load scenario; scenario_id=%s", active_scenario_id
        )
        raise WorkbookIdentityError(
            f"Scenario read failed for scenario_id={active_scenario_id!r}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Public assembly entry points
# ---------------------------------------------------------------------------

def assemble_from_parts(
    scalar_snapshot: Mapping[str, str],
    template_source: str,
    project_origin: str,
    workbook_version: str,
    capex_rows: Sequence[CanonicalCapexRow],
    opex_rows: Sequence[CanonicalOpexRow],
    scenario: CanonicalScenarioState,
) -> CompositeWorkbookIdentity:
    """Build a ``CompositeWorkbookIdentity`` from pre-loaded parts.

    This is the pure / testable entry point — no DB reads.
    """
    h = _compute_composite_hash(
        workbook_version=workbook_version,
        scalar_snapshot=scalar_snapshot,
        template_source=template_source,
        project_origin=project_origin,
        capex_rows=capex_rows,
        opex_rows=opex_rows,
        scenario=scenario,
    )
    return CompositeWorkbookIdentity(
        workbook_version=workbook_version,
        scalar_snapshot=scalar_snapshot,
        template_source=template_source,
        project_origin=project_origin,
        capex_rows=tuple(sorted(capex_rows)),
        opex_rows=tuple(sorted(opex_rows)),
        scenario=scenario,
        composite_hash=h,
    )


def assemble_consistent_for_get(
    user_id: str,
    project_id: str,
    workbook_version: str,
) -> CompositeWorkbookIdentity:
    """Assemble composite identity inside a consistent read-only transaction.

    All four sources — workspace snapshot, CAPEX rows, OPEX rows, and active
    scenario — are read inside a single ``BEGIN DEFERRED`` transaction,
    giving a point-in-time consistent snapshot.

    Use this function for all GET and HTMX rendering paths.  A token
    assembled from state read at different moments is not acceptable for
    the workbook identity contract.

    Raises WorkbookIdentityError on workspace-not-found or any read failure.
    """
    from app.persistence.db import get_connection
    conn = get_connection()
    try:
        conn.execute("BEGIN DEFERRED")
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM workspace_states WHERE user_id=? AND project_id=?",
            (user_id, project_id),
        )
        row = cur.fetchone()
        if row is None:
            conn.execute("ROLLBACK")
            raise WorkbookIdentityError(
                f"Workspace not found for user={user_id!r} project={project_id!r}"
            )
        identity = assemble_transactional(
            draft_snapshot_json=row["draft_snapshot_json"] or "{}",
            project_id=project_id,
            user_id=user_id,
            active_scenario_id=row["active_scenario_id"],
            active_scenario_name=row["active_scenario_name"],
            cursor=cur,
            workbook_version=workbook_version,
        )
        conn.execute("COMMIT")
        return identity
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


def assemble_for_workspace(
    ws: Any,  # WorkspaceStateRecord
    *,
    user_id: str,
    project_id: str,
    workbook_version: str,
) -> CompositeWorkbookIdentity:
    """Assemble the composite identity for a WorkspaceStateRecord.

    Reads CAPEX rows, OPEX rows, and the active scenario from the DB.
    The scalar state is taken from ``ws.draft_snapshot``.

    Note: three separate reads (workspace already read by caller; CAPEX/OPEX
    rows and scenario each require one additional query).  For a fully
    consistent identity, prefer ``assemble_consistent_for_get()`` which reads
    all sources inside one transaction.

    Raises WorkbookIdentityError on any DB read failure.
    """
    from app.workbook.registry import WORKBOOK as _wb
    _wv = workbook_version or _wb.version

    scalar_snapshot = dict(ws.draft_snapshot or {})
    template_source = scalar_snapshot.get("template_source", "")
    project_origin = scalar_snapshot.get("project_origin", "")

    capex_rows = _load_canonical_capex_rows(project_id)
    opex_rows = _load_canonical_opex_rows(project_id)
    scenario = _canonical_scenario(
        active_scenario_id=ws.active_scenario_id,
        active_scenario_name=ws.active_scenario_name,
        user_id=user_id,
    )

    return assemble_from_parts(
        scalar_snapshot=scalar_snapshot,
        template_source=template_source,
        project_origin=project_origin,
        workbook_version=_wv,
        capex_rows=capex_rows,
        opex_rows=opex_rows,
        scenario=scenario,
    )


def assemble_transactional(
    draft_snapshot_json: str,
    project_id: str,
    user_id: str,
    active_scenario_id: Optional[str],
    active_scenario_name: Optional[str],
    cursor: Any,  # sqlite3.Cursor already inside a transaction
    workbook_version: str,
) -> CompositeWorkbookIdentity:
    """Assemble composite identity inside an existing transaction.

    Used by ``v2_atomic_draft_update`` and ``_exclusive_tx`` in CAPEX/OPEX
    commands.  All three reads happen while the transaction lock is held,
    providing transactional consistency across scalar + row + scenario state.

    Args:
        draft_snapshot_json: raw JSON string of ``draft_snapshot_json`` column.
        project_id: project UUID.
        user_id: user UUID (needed for scenario query).
        active_scenario_id: from workspace row.
        active_scenario_name: from workspace row.
        cursor: SQLite cursor, already inside a transaction.
        workbook_version: WORKBOOK.version string.

    Returns:
        ``CompositeWorkbookIdentity`` with consistent hash.

    Raises:
        WorkbookIdentityError: on any DB/schema/parse failure.
    """
    import json as _json
    from app.workbook.registry import WORKBOOK as _wb
    _wv = workbook_version or _wb.version

    try:
        scalar_snapshot = _json.loads(draft_snapshot_json or "{}")
    except Exception as exc:
        raise WorkbookIdentityError(
            f"Failed to parse draft_snapshot_json: {exc}"
        ) from exc

    template_source = scalar_snapshot.get("template_source", "")
    project_origin = scalar_snapshot.get("project_origin", "")

    # --- CAPEX rows (inside transaction) ---
    capex_rows: list[CanonicalCapexRow] = []
    try:
        cursor.execute(
            "SELECT sub_line_id, parent_category_code, amount_keur "
            "FROM capex_sub_lines "
            "WHERE project_id=? AND is_active=1",
            (project_id,),
        )
        for r in cursor.fetchall():
            capex_rows.append(CanonicalCapexRow(
                sub_line_id=r["sub_line_id"],
                parent_category_code=r["parent_category_code"],
                amount_keur=float(r["amount_keur"]),
            ))
    except WorkbookIdentityError:
        raise
    except Exception as exc:
        logger.exception("STAB-1B: CAPEX row read failed inside transaction; project_id=%s", project_id)
        raise WorkbookIdentityError(
            f"CAPEX row read failed inside transaction for project {project_id!r}: {exc}"
        ) from exc

    # --- OPEX rows (inside transaction) ---
    opex_rows: list[CanonicalOpexRow] = []
    try:
        cursor.execute(
            "SELECT sub_line_id, parent_group_code, business_code, amount_keur, inflation_pct "
            "FROM opex_sub_lines "
            "WHERE project_id=? AND is_active=1",
            (project_id,),
        )
        for r in cursor.fetchall():
            opex_rows.append(CanonicalOpexRow(
                sub_line_id=r["sub_line_id"],
                parent_group_code=r["parent_group_code"],
                business_code=r["business_code"],
                amount_keur=float(r["amount_keur"]),
                inflation_pct=float(r["inflation_pct"]),
            ))
    except WorkbookIdentityError:
        raise
    except Exception as exc:
        logger.exception("STAB-1B: OPEX row read failed inside transaction; project_id=%s", project_id)
        raise WorkbookIdentityError(
            f"OPEX row read failed inside transaction for project {project_id!r}: {exc}"
        ) from exc

    # --- Scenario (inside transaction) ---
    scenario_overrides: dict = {}
    if active_scenario_id:
        try:
            cursor.execute(
                "SELECT overrides_json FROM scenarios WHERE scenario_id=?",
                (active_scenario_id,),
            )
            row = cursor.fetchone()
            if row:
                scenario_overrides = _json.loads(row["overrides_json"] or "{}")
        except WorkbookIdentityError:
            raise
        except Exception as exc:
            logger.exception(
                "STAB-1B: scenario read failed inside transaction; scenario_id=%s",
                active_scenario_id,
            )
            raise WorkbookIdentityError(
                f"Scenario read failed inside transaction for scenario_id={active_scenario_id!r}: {exc}"
            ) from exc

    scenario = CanonicalScenarioState(
        scenario_id=active_scenario_id,
        scenario_name=active_scenario_name,
        overrides=scenario_overrides,
    )

    return assemble_from_parts(
        scalar_snapshot=scalar_snapshot,
        template_source=template_source,
        project_origin=project_origin,
        workbook_version=_wv,
        capex_rows=capex_rows,
        opex_rows=opex_rows,
        scenario=scenario,
    )
