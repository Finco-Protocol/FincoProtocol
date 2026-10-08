"""Request-local, authorized read snapshot for post-Run presentation only.

Capture and final validation use read transactions. No context is persisted,
registered globally, or accepted from a client. Financial/CAS authorities stay
unchanged; a concurrent mutation invalidates the response, not the Run commit.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass, replace
import hashlib
import json
from types import MappingProxyType
from typing import Any, Generic, TypeVar

from app.persistence.records import ProjectRecord, ScenarioRecord, WorkspaceStateRecord
from app.workbook.input_set import ProjectInputSet
from app.workbook.runtime_authority import RuntimeFreshness, resolve_runtime_freshness
from app.workbook.runtime_projection import WorkbookRuntimeProjection, build_runtime_projection_bundle
from app.workbook.runtime_result import RuntimeResult
from app.workbook.service import WorkbookService
from app.workbook.workbook_identity import CompositeWorkbookIdentity, WorkbookIdentityError, assemble_transactional


class PostRunContextChanged(RuntimeError):
    """The authorized workspace changed while its response was assembled."""


class _FrozenDict(dict):
    def _deny(self, *args, **kwargs):
        raise TypeError("Post-run snapshot evidence is read-only")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _deny


class _FrozenList(list):
    def _deny(self, *args, **kwargs):
        raise TypeError("Post-run snapshot evidence is read-only")

    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = reverse = sort = __iadd__ = __imul__ = _deny


def _freeze(value):
    # Keep dict/list compatibility for existing JSON/evidence authorities.
    if isinstance(value, Mapping):
        return _FrozenDict({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return _FrozenList(_freeze(v) for v in value)
    if isinstance(value, tuple):
        return tuple(_freeze(v) for v in value)
    if is_dataclass(value):
        copy = replace(value)
        for f in fields(value):
            object.__setattr__(copy, f.name, _freeze(getattr(value, f.name)))
        return copy
    return value


T = TypeVar("T")
_CAPTURE_KEY = object()


@dataclass(frozen=True)
class _RecordSnapshot(Generic[T]):
    _values: Mapping[str, Any]

    @classmethod
    def of(cls, record: T):
        names = ([f.name for f in fields(record)] if is_dataclass(record)
                 else record.__slots__)
        return cls(MappingProxyType({name: _freeze(getattr(record, name)) for name in names}))

    def __getattr__(self, name):
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(name) from None


def _read_snapshot(owner_id: str, project_id: str):
    from app.persistence.db import get_connection
    from app.workbook.registry import WORKBOOK

    conn = get_connection()
    try:
        conn.execute("BEGIN DEFERRED")
        cur = conn.cursor()
        # Same scoped authorization predicate as canonical get_project.
        cur.execute("SELECT * FROM projects WHERE project_id=? AND user_id=?",
                    (project_id, owner_id))
        project_row = cur.fetchone()
        cur.execute("SELECT * FROM workspace_states WHERE user_id=? AND project_id=?",
                    (owner_id, project_id))
        workspace_row = cur.fetchone()
        if project_row is None or workspace_row is None:
            raise PermissionError("Authorized post-run workspace is unavailable")
        if project_row["project_code"] != workspace_row["project_code"]:
            raise WorkbookIdentityError("Post-run project binding is inconsistent")
        if workspace_row["active_scenario_id"]:
            cur.execute("SELECT scenario_id FROM scenarios WHERE scenario_id=? "
                        "AND user_id=? AND project_id=? AND archived=0",
                        (workspace_row["active_scenario_id"], owner_id, project_id))
            if cur.fetchone() is None:
                raise WorkbookIdentityError("Post-run scenario binding is unavailable")
        identity = assemble_transactional(
            draft_snapshot_json=workspace_row["draft_snapshot_json"] or "{}",
            project_id=project_id, user_id=owner_id,
            active_scenario_id=workspace_row["active_scenario_id"],
            active_scenario_name=workspace_row["active_scenario_name"],
            cursor=cur, workbook_version=WORKBOOK.version)
        cur.execute("SELECT * FROM scenarios WHERE user_id=? AND project_id=? "
                    "AND archived=0 ORDER BY updated_at DESC LIMIT 25", (owner_id, project_id))
        scenario_rows = cur.fetchall()
        token = hashlib.sha256(json.dumps(
            [dict(project_row), dict(workspace_row), [dict(r) for r in scenario_rows],
             identity.composite_hash], sort_keys=True).encode()).hexdigest()
        result = (ProjectRecord.from_row(project_row), WorkspaceStateRecord.from_row(workspace_row),
                  identity, tuple(ScenarioRecord.from_row(r) for r in scenario_rows), token)
        conn.execute("COMMIT")
        return result
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _runtime_matches(rr: RuntimeResult | None, ws: WorkspaceStateRecord) -> bool:
    if not isinstance(rr, RuntimeResult) or not ws.last_runtime_summary:
        return False
    if (rr.snapshot_id != ws.last_runtime_snapshot_id
            or rr.ran_at != (ws.last_runtime_at.isoformat() if ws.last_runtime_at else "")
            or rr.origin != (ws.last_runtime_origin or "")
            or rr.runtime_summary != ws.last_runtime_summary):
        return False
    return all(getattr(rr, target) == (getattr(ws, source) or None) for target, source in (
        ("financial_statements", "last_financial_statements"),
        ("debt_schedule", "last_debt_schedule"), ("tax_schedule", "last_tax_schedule"),
        ("distribution_schedule", "last_distribution_schedule"),
        ("sponsor_schedule", "last_sponsor_schedule")))


@dataclass(frozen=True, slots=True, init=False)
class PostRunRequestContext:
    owner_id: str
    project_id: str
    project_record: _RecordSnapshot[ProjectRecord]
    workspace: _RecordSnapshot[WorkspaceStateRecord]
    identity: CompositeWorkbookIdentity
    scenarios: tuple[_RecordSnapshot[ScenarioRecord], ...]
    draft_inputs: ProjectInputSet
    inputs: ProjectInputSet
    runtime_result: RuntimeResult | None
    freshness: RuntimeFreshness
    projection: WorkbookRuntimeProjection
    _snapshot_token: str
    _capture_key: object

    @classmethod
    def capture(cls, *, owner_id: str, project_id: str,
                expected_workspace: WorkspaceStateRecord | _RecordSnapshot[WorkspaceStateRecord] | None = None,
                runtime_result: RuntimeResult | None = None) -> PostRunRequestContext:
        if expected_workspace is not None and (
            expected_workspace.user_id != owner_id or expected_workspace.project_id != project_id
        ):
            raise PermissionError("Post-run context owner/project mismatch")
        pr, ws, identity, scenarios, token = _read_snapshot(owner_id, project_id)
        if ws.last_runtime_identity and (
            not isinstance(ws.last_runtime_identity, Mapping)
            or ws.last_runtime_identity.get("composite_hash") != ws.last_runtime_composite_hash
        ):
            raise WorkbookIdentityError("Post-run Last Run identity is inconsistent")
        # The DB, not a supplied object's plausible identity, proves the result.
        rr = runtime_result if _runtime_matches(runtime_result, ws) else WorkbookService.get_runtime_result(ws)
        if ws.last_runtime_snapshot_id and (rr is None or not isinstance(ws.last_runtime_summary, Mapping)):
            raise WorkbookIdentityError("Post-run persisted runtime evidence is unavailable")
        draft = WorkbookService.build_draft_input_set_from_workspace(ws)
        inputs = draft.with_composite_hash(identity.composite_hash)
        # Keep #219's narrow legacy Base equivalence authority unchanged.
        freshness = resolve_runtime_freshness(ws, current_composite_hash=identity.composite_hash)
        projection = build_runtime_projection_bundle(rr, freshness.is_stale)
        values = dict(owner_id=owner_id, project_id=project_id,
                      project_record=_RecordSnapshot.of(pr), workspace=_RecordSnapshot.of(ws),
                      identity=_freeze(identity), scenarios=tuple(_RecordSnapshot.of(s) for s in scenarios),
                      draft_inputs=_freeze(draft), inputs=_freeze(inputs), runtime_result=_freeze(rr),
                      freshness=freshness, projection=_freeze(projection), _snapshot_token=token,
                      _capture_key=_CAPTURE_KEY)
        context = object.__new__(cls)
        for name, value in values.items():
            object.__setattr__(context, name, value)
        return context

    def require_scope(self, owner_id: str, project_id: str) -> None:
        if (getattr(self, "_capture_key", None) is not _CAPTURE_KEY
                or owner_id != self.owner_id or project_id != self.project_id
                or self.workspace.user_id != owner_id or self.workspace.project_id != project_id
                or self.project_record.user_id != owner_id
                or self.project_record.project_id != project_id
                or self.identity.scenario.scenario_id != self.workspace.active_scenario_id):
            raise PermissionError("Post-run context owner/project mismatch")

    def require_binding(self, workspace, project_record, runtime_result) -> None:
        self.require_scope(workspace.user_id, project_record.project_id)
        if (workspace is not self.workspace or project_record is not self.project_record
                or runtime_result is not self.runtime_result):
            raise ValueError("Post-run context workspace/Run binding mismatch")

    def validate_current(self) -> None:
        # This latest-authority read is required, not a redundant projection.
        if _read_snapshot(self.owner_id, self.project_id)[-1] != self._snapshot_token:
            raise PostRunContextChanged("Workspace changed during post-run response assembly")
