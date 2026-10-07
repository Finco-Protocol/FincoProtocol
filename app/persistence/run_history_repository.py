"""Run History V1 - append-only canonical ledger of successful runs.

Workflow: Model V2 Run History V1. This module is the narrow persistence
surface for the immutable history of SUCCESSFUL canonical runs:

  Working Copy -> successful canonical run -> atomic Last Run promotion
                                            + append immutable history row

Contract (docs/model_v2/RUN_HISTORY_V1_CONTRACT.md):

  - APPEND-ONLY: rows are immutable after insertion. There is no update,
    no delete, no overwrite-by-project and no restore in V1.
  - ATOMIC: the append executes INSIDE the existing canonical run-commit
    transaction (v2_atomic_run_commit's BEGIN EXCLUSIVE, or the legacy
    save_workspace_state transaction driven by record_workspace_runtime)
    via :func:`append_run_history_cursor`. If the append fails, the whole
    transaction - including the Last Run promotion - rolls back. Last Run
    = C with History C missing is unrepresentable, and so is History C
    without its Last Run promotion.
  - FAILED RUNS NEVER APPEND: only the successful commit path reaches the
    append; every earlier failure leaves zero new rows.
  - LEGACY vs V2: a legacy run history row carries NO invented Model V2
    binding (identity fields absent/null as contractually appropriate);
    a V2 run history row preserves the exact Workflow 07 binding payload
    verbatim inside ``last_runtime_identity_json["model_v2"]``.
  - CORRELATION: the payload validator fails closed before commit when a
    supplied Model V2 binding contradicts the run being committed
    (snapshot id, working-copy ref, scenario id).
  - ORDERING: reads order by ``ran_at DESC`` with the immutable
    ``history_id`` as the deterministic tie-breaker; incidental SQLite row
    order is never relied upon.
  - READ METHODS BEYOND APPEND: get_run_history / get_run_history_entry /
    get_latest_history_entry. No delete/restore/mutation surface exists.
  - MALFORMED STORED PAYLOADS FAIL CLOSED on read
    (RUN_HISTORY_PAYLOAD_MALFORMED) - never guessed, never partially
    decoded.

History starts prospectively with this feature: existing workspaces are
never back-filled and no row is synthesized from the current Last Run.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Mapping, Optional

__all__ = [
    "RunHistoryError",
    "RunHistoryEntry",
    "append_run_history_cursor",
    "get_latest_history_entry",
    "get_run_history",
    "get_run_history_entry",
    "prepare_run_history_payload",
]

_HISTORY_COLUMNS = (
    "history_id",
    "user_id",
    "project_id",
    "project_code",
    "runtime_snapshot_id",
    "runtime_origin",
    "ran_at",
    "engine_version",
    "workbook_version",
    "active_scenario_id",
    "active_scenario_name",
    "last_runtime_scenario_id",
    "composite_hash",
    "last_runtime_identity_json",
    "runtime_summary_json",
    "financial_statements_json",
    "debt_schedule_json",
    "tax_schedule_json",
    "distribution_schedule_json",
    "sponsor_schedule_json",
    "integrity_evidence_json",
    "replay_metadata_json",
    "created_at",
)


class RunHistoryError(Exception):
    """Typed fail-closed error for the append-only run history ledger."""


@dataclass(frozen=True)
class RunHistoryEntry:
    """One immutable successful-run record (decoded view of a history row)."""

    history_id: str
    user_id: str
    project_id: str
    project_code: str
    runtime_snapshot_id: str
    runtime_origin: Optional[str]
    ran_at: str
    engine_version: Optional[str]
    workbook_version: Optional[str]
    active_scenario_id: Optional[str]
    active_scenario_name: Optional[str]
    last_runtime_scenario_id: Optional[str]
    composite_hash: Optional[str]
    last_runtime_identity: Optional[dict]
    runtime_summary: dict
    financial_statements: dict
    debt_schedule: dict
    tax_schedule: dict
    distribution_schedule: dict
    sponsor_schedule: dict
    integrity_evidence: dict
    replay_metadata: dict
    created_at: str

    @property
    def model_v2_binding(self) -> Optional[dict]:
        """The exact Workflow 07 binding payload, or None for legacy runs.

        Never invented: a legacy run history row has no "model_v2" key in
        its identity payload and this property returns None.
        """
        identity = self.last_runtime_identity
        if not isinstance(identity, dict):
            return None
        binding = identity.get("model_v2")
        return dict(binding) if isinstance(binding, dict) else None

    def to_dict(self) -> dict:
        return {
            "history_id": self.history_id,
            "user_id": self.user_id,
            "project_id": self.project_id,
            "project_code": self.project_code,
            "runtime_snapshot_id": self.runtime_snapshot_id,
            "runtime_origin": self.runtime_origin,
            "ran_at": self.ran_at,
            "engine_version": self.engine_version,
            "workbook_version": self.workbook_version,
            "active_scenario_id": self.active_scenario_id,
            "active_scenario_name": self.active_scenario_name,
            "last_runtime_scenario_id": self.last_runtime_scenario_id,
            "composite_hash": self.composite_hash,
            "last_runtime_identity": self.last_runtime_identity,
            "runtime_summary": self.runtime_summary,
            "financial_statements": self.financial_statements,
            "debt_schedule": self.debt_schedule,
            "tax_schedule": self.tax_schedule,
            "distribution_schedule": self.distribution_schedule,
            "sponsor_schedule": self.sponsor_schedule,
            "integrity_evidence": self.integrity_evidence,
            "replay_metadata": self.replay_metadata,
            "created_at": self.created_at,
        }


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=True, allow_nan=False,
        separators=(",", ":"),
    )


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RunHistoryError(
            f"RUN_HISTORY_FIELD_INVALID: {field} must be a non-empty string"
        )
    return value


_OPTIONAL_TEXT_FIELDS = (
    "runtime_origin",
    "engine_version",
    "workbook_version",
    "active_scenario_id",
    "active_scenario_name",
    "last_runtime_scenario_id",
    "composite_hash",
)


def prepare_run_history_payload(
    *,
    user_id: str,
    project_id: str,
    project_code: str,
    runtime_snapshot_id: str,
    runtime_origin: Optional[str],
    ran_at: str,
    runtime_summary: Mapping[str, Any],
    financial_statements: Mapping[str, Any],
    debt_schedule: Mapping[str, Any],
    tax_schedule: Mapping[str, Any],
    distribution_schedule: Mapping[str, Any],
    sponsor_schedule: Mapping[str, Any],
    engine_version: Optional[str] = None,
    workbook_version: Optional[str] = None,
    composite_hash: Optional[str] = None,
    last_runtime_identity: Optional[Mapping[str, Any]] = None,
    active_scenario_id: Optional[str] = None,
    active_scenario_name: Optional[str] = None,
    last_runtime_scenario_id: Optional[str] = None,
    integrity_evidence: Optional[Mapping[str, Any]] = None,
    replay_metadata: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Build and validate one immutable history payload (pre-insert).

    Pure function: returns the fully-validated row dictionary (JSON columns
    already canonically encoded) that :func:`append_run_history_cursor`
    inserts. Correlation invariants fail closed here, BEFORE the commit:
    a supplied Model V2 binding must correlate exactly with the run being
    committed (snapshot id, working-copy ref, scenario id).
    """
    _require_text(user_id, "user_id")
    _require_text(project_id, "project_id")
    _require_text(project_code, "project_code")
    _require_text(runtime_snapshot_id, "runtime_snapshot_id")
    _require_text(ran_at, "ran_at")
    # Correction A: typed optional identity fields are canonical strings or
    # contractually-absent None - never bool/list/dict coerced by SQLite
    # TEXT affinity.
    scope = dict(
        runtime_origin=runtime_origin,
        engine_version=engine_version,
        workbook_version=workbook_version,
        active_scenario_id=active_scenario_id,
        active_scenario_name=active_scenario_name,
        last_runtime_scenario_id=last_runtime_scenario_id,
        composite_hash=composite_hash,
    )
    for field in _OPTIONAL_TEXT_FIELDS:
        value = scope[field]
        if value is not None and (
            not isinstance(value, str) or isinstance(value, bool) or not value.strip()
        ):
            raise RunHistoryError(
                f"RUN_HISTORY_FIELD_INVALID: {field} must be a non-empty "
                "string or None"
            )
    for name, mapping in (
        ("runtime_summary", runtime_summary),
        ("financial_statements", financial_statements),
        ("debt_schedule", debt_schedule),
        ("tax_schedule", tax_schedule),
        ("distribution_schedule", distribution_schedule),
        ("sponsor_schedule", sponsor_schedule),
    ):
        if mapping is None or not isinstance(mapping, Mapping):
            raise RunHistoryError(
                f"RUN_HISTORY_FIELD_INVALID: {name} must be a mapping"
            )
    identity_dict = (
        dict(last_runtime_identity) if last_runtime_identity is not None
        else None
    )
    binding = (
        identity_dict.get("model_v2")
        if isinstance(identity_dict, dict) else None
    )
    if binding is not None:
        if not isinstance(binding, dict):
            raise RunHistoryError(
                "RUN_HISTORY_BINDING_CORRUPT: model_v2 binding is not a "
                "mapping"
            )
        # Correction A3: prove the binding IS a valid Workflow 07 run
        # binding via the canonical validator (schema, key set, hash
        # shapes) BEFORE any correlation check - a malformed binding fails
        # closed even when its correlation fields happen to match.
        from app.model_v2.persistence import (
            validate_run_binding_payload as _validate_v2_binding,
        )

        try:
            binding = _validate_v2_binding(dict(binding))
        except Exception as exc:
            raise RunHistoryError(
                f"RUN_HISTORY_BINDING_INVALID: the Model V2 binding is not "
                f"a valid Workflow 07 run binding ({exc})"
            ) from exc
        identity_dict["model_v2"] = binding
        # Correlation invariants (contract section 11) - fail closed before
        # the commit so a misattributed history row is unrepresentable.
        if binding.get("snapshot_id") != runtime_snapshot_id:
            raise RunHistoryError(
                "RUN_HISTORY_BINDING_SNAPSHOT_MISMATCH: binding correlates "
                f"with snapshot {binding.get('snapshot_id')!r} but this "
                f"history row records snapshot {runtime_snapshot_id!r}"
            )
        if binding.get("working_copy_ref") != project_code:
            raise RunHistoryError(
                "RUN_HISTORY_BINDING_REF_MISMATCH: binding is bound to "
                f"working_copy_ref {binding.get('working_copy_ref')!r} but "
                f"this history row belongs to project_code {project_code!r}"
            )
        if binding.get("scenario_id") != last_runtime_scenario_id:
            raise RunHistoryError(
                "RUN_HISTORY_BINDING_SCENARIO_MISMATCH: binding names "
                f"scenario {binding.get('scenario_id')!r} but this history "
                f"row records Last Run scenario {last_runtime_scenario_id!r}"
            )
    history_id = uuid.uuid4().hex
    return {
        "history_id": history_id,
        "user_id": user_id,
        "project_id": project_id,
        "project_code": project_code,
        "runtime_snapshot_id": runtime_snapshot_id,
        "runtime_origin": runtime_origin,
        "ran_at": ran_at,
        "engine_version": engine_version,
        "workbook_version": workbook_version,
        "active_scenario_id": active_scenario_id,
        "active_scenario_name": active_scenario_name,
        "last_runtime_scenario_id": last_runtime_scenario_id,
        "composite_hash": composite_hash,
        "last_runtime_identity_json": (
            _canonical_json(identity_dict)
            if identity_dict is not None else None
        ),
        "runtime_summary_json": _canonical_json(dict(runtime_summary)),
        "financial_statements_json": _canonical_json(
            dict(financial_statements)),
        "debt_schedule_json": _canonical_json(dict(debt_schedule)),
        "tax_schedule_json": _canonical_json(dict(tax_schedule)),
        "distribution_schedule_json": _canonical_json(
            dict(distribution_schedule)),
        "sponsor_schedule_json": _canonical_json(dict(sponsor_schedule)),
        "integrity_evidence_json": _canonical_json(
            dict(integrity_evidence or {})),
        "replay_metadata_json": _canonical_json(dict(replay_metadata or {})),
        "created_at": ran_at,
    }


def append_run_history_cursor(cur, payload: Mapping[str, Any]) -> str:
    """INSERT one validated history payload inside the CALLER's transaction.

    Used by the canonical run-commit paths (v2_atomic_run_commit's
    BEGIN EXCLUSIVE and the legacy save_workspace_state transaction) so the
    append is atomic with the Last Run promotion: if this insert fails the
    caller's whole transaction - including the Last Run promotion - rolls
    back. Never called with an unvalidated payload.
    """
    row = dict(payload)
    missing = [c for c in _HISTORY_COLUMNS if c not in row]
    if missing:
        raise RunHistoryError(
            f"RUN_HISTORY_PAYLOAD_INCOMPLETE: missing {sorted(missing)}"
        )
    cur.execute(
        f"""
        INSERT INTO model_run_history ({", ".join(_HISTORY_COLUMNS)})
        VALUES ({", ".join("?" for _ in _HISTORY_COLUMNS)})
        """,
        tuple(row[c] for c in _HISTORY_COLUMNS),
    )
    return row["history_id"]



def _decode_entry(row) -> RunHistoryEntry:
    """Fail-closed row decoder: malformed stored JSON never half-decodes."""
    def _load(column: str):
        raw = row[column]
        try:
            return json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise RunHistoryError(
                f"RUN_HISTORY_PAYLOAD_MALFORMED: column {column} is not "
                f"valid JSON ({exc})"
            ) from exc

    for column in _HISTORY_COLUMNS:
        if column not in row.keys():
            raise RunHistoryError(
                "RUN_HISTORY_PAYLOAD_MALFORMED: stored row is missing "
                f"column {column}"
            )
    identity_raw = row["last_runtime_identity_json"]
    identity_decoded = None
    if identity_raw is not None:
        try:
            identity_decoded = json.loads(identity_raw)
        except (TypeError, ValueError) as exc:
            raise RunHistoryError(
                "RUN_HISTORY_PAYLOAD_MALFORMED: last_runtime_identity_json "
                f"is not valid JSON ({exc})"
            ) from exc
        if not isinstance(identity_decoded, dict):
            raise RunHistoryError(
                "RUN_HISTORY_PAYLOAD_MALFORMED: last_runtime_identity_json "
                "is not a JSON object"
            )
    for column in (
        "runtime_summary_json",
        "financial_statements_json",
        "debt_schedule_json",
        "tax_schedule_json",
        "distribution_schedule_json",
        "sponsor_schedule_json",
        "integrity_evidence_json",
        "replay_metadata_json",
    ):
        decoded = _load(column)
        if not isinstance(decoded, dict):
            raise RunHistoryError(
                "RUN_HISTORY_PAYLOAD_MALFORMED: column "
                f"{column} is not a JSON object"
            )
    entry = RunHistoryEntry(
        history_id=row["history_id"],
        user_id=row["user_id"],
        project_id=row["project_id"],
        project_code=row["project_code"],
        runtime_snapshot_id=row["runtime_snapshot_id"],
        runtime_origin=row["runtime_origin"],
        ran_at=row["ran_at"],
        engine_version=row["engine_version"],
        workbook_version=row["workbook_version"],
        active_scenario_id=row["active_scenario_id"],
        active_scenario_name=row["active_scenario_name"],
        last_runtime_scenario_id=row["last_runtime_scenario_id"],
        composite_hash=row["composite_hash"],
        last_runtime_identity=identity_decoded,
        runtime_summary=_load("runtime_summary_json"),
        financial_statements=_load("financial_statements_json"),
        debt_schedule=_load("debt_schedule_json"),
        tax_schedule=_load("tax_schedule_json"),
        distribution_schedule=_load("distribution_schedule_json"),
        sponsor_schedule=_load("sponsor_schedule_json"),
        integrity_evidence=_load("integrity_evidence_json"),
        replay_metadata=_load("replay_metadata_json"),
        created_at=row["created_at"],
    )
    for field in ("history_id", "user_id", "project_id", "project_code",
                  "runtime_snapshot_id", "ran_at", "created_at"):
        if not getattr(entry, field):
            raise RunHistoryError(
                f"RUN_HISTORY_PAYLOAD_MALFORMED: {field} is empty"
            )
    if not isinstance(entry.runtime_summary, dict):
        raise RunHistoryError(
            "RUN_HISTORY_PAYLOAD_MALFORMED: runtime_summary is not an object"
        )
    return entry


def get_run_history(user_id: str, project_id: str, limit: Optional[int] = None):
    """Successful-run history for one project, newest first.

    Ordering is canonical: ``ran_at DESC`` with the immutable
    ``history_id DESC`` as the deterministic tie-breaker.
    """
    from app.persistence.db import get_cursor

    sql = (
        "SELECT * FROM model_run_history "
        "WHERE user_id=? AND project_id=? "
        "ORDER BY ran_at DESC, history_id DESC"
    )
    params = [user_id, project_id]
    if limit is not None:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise RunHistoryError(
                "RUN_HISTORY_LIMIT_INVALID: limit must be a positive integer"
            )
        sql += " LIMIT ?"
        params.append(limit)
    with get_cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
    return [_decode_entry(row) for row in rows]


def get_run_history_entry(user_id: str, project_id: str, history_id: str):
    """One history entry by immutable id, or None when it does not exist."""
    from app.persistence.db import get_cursor

    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM model_run_history "
            "WHERE user_id=? AND project_id=? AND history_id=?",
            (user_id, project_id, history_id),
        )
        row = cur.fetchone()
    return _decode_entry(row) if row is not None else None


def get_latest_history_entry(user_id: str, project_id: str):
    """The newest history entry (same canonical ordering), or None."""
    entries = get_run_history(user_id, project_id, limit=1)
    return entries[0] if entries else None
