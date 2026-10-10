"""Q4 finding-to-What-if transaction. No engine calls and no synthetic KPI authority."""
from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.auth import SECRET_KEY
from app.model_quality import evaluate_model_quality
from app.model_quality.evidence import evidence_from_workspace
from app.persistence._helpers import SCENARIO_INPUT_FIELDS
from app.persistence.records import WorkspaceStateRecord, ScenarioRecord
from app.workbook.input_set import ProjectInputSet
from app.workbook.registry import WORKBOOK
from app.workbook.update_service import WorkbookUpdateService
from app.workbook.workbook_identity import assemble_consistent_for_get, assemble_transactional
from app.workbook.runtime_authority import resolve_runtime_freshness
from app.v2.register_path_map import register_path_for_field

# These IDs and paths are explicitly registered in Q1 + the Workbook registry.
# Q4 never guesses mappings from labels, metric keys or natural-language findings.
CANDIDATES = {
    "QM-SD-004": ("financing.target_dscr", "debt.senior.target_dscr", "target_dscr"),
    "QM-SD-007": ("financing.target_dscr", "debt.senior.target_dscr", "target_dscr"),
    "QM-SD-006": ("financing.gearing_ratio", "debt.senior.gearing_pct", "gearing_pct"),
}
SUPPORTED_VERTICALS = frozenset(("solar", "wind"))
TOKEN_MAX_AGE = 10 * 60


class Q4Rejected(ValueError):
    def __init__(self, code: str, status: int = 409):
        self.code = code
        self.status = status
        super().__init__(code)


def _token_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(SECRET_KEY, salt="finco-model-q4-whatif-v1")


def _quality_check(ws: Any, check_id: str, state: str):
    evidence = evidence_from_workspace(
        ws, freshness=state, active_scenario_id=ws.active_scenario_id,
        scenario_known=True,
    )
    return evaluate_model_quality(evidence).check(check_id)


def _mapping(check_id: str, ws: Any, project_type: str, raw: str):
    from app.workbook.specs import ScenarioPolicy
    if project_type.strip().lower() not in SUPPORTED_VERTICALS:
        raise Q4Rejected("Q4_VERTICAL_NOT_ENABLED", 422)
    mapping = CANDIDATES.get(check_id)
    if mapping is None:
        raise Q4Rejected("Q4_FINDING_MAPPING_UNAVAILABLE", 422)
    path, field_id, override_key = mapping
    finding = _quality_check(ws, check_id, "STALE" if ws.dirty else "CURRENT")
    if path not in finding.related_assumption_ids:
        raise Q4Rejected("Q4_FINDING_ASSUMPTION_UNPROVEN", 422)
    if finding.status.value not in ("FAIL", "WARNING"):
        raise Q4Rejected("Q4_FINDING_NOT_ACTIONABLE", 422)
    if register_path_for_field(field_id) != path:
        raise Q4Rejected("Q4_FIELD_ID_NOT_PROVEN", 422)
    spec = WORKBOOK.field(field_id)
    if not spec.editable or spec.scenario_policy is not ScenarioPolicy.OVERRIDE:
        raise Q4Rejected("Q4_FIELD_NOT_SCENARIO_EDITABLE", 422)
    if spec.snapshot_key != override_key or override_key not in SCENARIO_INPUT_FIELDS:
        raise Q4Rejected("Q4_OVERRIDE_KEY_UNPROVEN", 422)
    validation = WorkbookUpdateService.validate_field_update(field_id, raw)
    if not validation.is_valid or validation.typed_value is None:
        raise Q4Rejected("Q4_VALUE_INVALID", 422)
    proposed = validation.typed_value
    if isinstance(proposed, bool) or not isinstance(proposed, (int, float)) or not math.isfinite(proposed):
        raise Q4Rejected("Q4_NONFINITE_VALUE", 422)
    return finding, spec, override_key, proposed


def _validate_financing(snapshot: dict, field_id: str, proposed: float) -> None:
    """An explicit *narrower* fence than the general editor; no F3 collection edits."""
    from app.workbook.multisenior_config import parse_state, SNAPSHOT_KEY
    from app.input_adapter import senior_dscr_authority
    if field_id == "debt.senior.target_dscr":
        state = parse_state(snapshot.get(SNAPSHOT_KEY))
        if any(isinstance(item, dict) and item.get("activation")
               for item in state.get("scopes", {}).values()):
            raise Q4Rejected("Q4_F3_COMPETING_SENIOR_EDITOR", 409)
        typed = ProjectInputSet.from_snapshot(snapshot).to_projectinputs()
        if senior_dscr_authority(typed)[0] != "FLAT":
            raise Q4Rejected("Q4_DSCR_SCHEDULE_LOCKED", 409)
    # Always pass through the existing typed ProjectInputs boundary.
    base = ProjectInputSet.from_snapshot(snapshot)
    field_id = str(field_id)
    base.with_value(field_id, proposed).to_projectinputs()


def _base_scope(cur, owner: str, project_id: str, active_id: str | None) -> ScenarioRecord:
    cur.execute(
        "SELECT * FROM scenarios WHERE user_id=? AND project_id=? AND is_base_case=1 AND archived=0",
        (owner, project_id),
    )
    bases = cur.fetchall()
    if len(bases) != 1:
        raise Q4Rejected("Q4_BASE_SCENARIO_UNPROVEN")
    base = ScenarioRecord.from_row(bases[0])
    if active_id not in (None, "", base.scenario_id):
        raise Q4Rejected("Q4_SELECT_BASE_FIRST")
    return base


def _assert_name(name: str) -> str:
    name = (name or "").strip()
    if not name or len(name) > 80 or any(ord(ch) < 32 for ch in name):
        raise Q4Rejected("Q4_SCENARIO_NAME_INVALID", 422)
    return name


def preview(*, owner: str, project_id: str, project_type: str, check_id: str,
            proposed_raw: str, scenario_name: str) -> dict[str, Any]:
    """Strictly read-only preview; its signed token binds all economic inputs."""
    name = _assert_name(scenario_name)
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.scenarios_repository import get_base_case_scenario
    ws = get_workspace_state(user_id=owner, project_id=project_id)
    if ws is None:
        raise Q4Rejected("Q4_WORKSPACE_NOT_FOUND", 404)
    base = get_base_case_scenario(user_id=owner, project_id=project_id)
    if not base or base.archived or ws.active_scenario_id not in (None, "", base.scenario_id):
        raise Q4Rejected("Q4_SELECT_BASE_FIRST")
    pis = ProjectInputSet.from_snapshot(ws.draft_snapshot)
    identity = assemble_consistent_for_get(
        user_id=owner, project_id=project_id, workbook_version=WORKBOOK.version)
    state = resolve_runtime_freshness(ws, current_composite_hash=identity.composite_hash).state.value
    if state == "NOT_RUN":
        raise Q4Rejected("Q4_REQUIRES_Q1_COMMITTED_FINDING")
    finding, spec, key, typed = _mapping(check_id, ws, project_type, proposed_raw)
    original = pis.values.get(key)
    if original is None or isinstance(original, bool) or not isinstance(original, (int, float)):
        raise Q4Rejected("Q4_ORIGINAL_VALUE_UNAVAILABLE")
    _validate_financing(ws.draft_snapshot, spec.field_id, typed)
    token_data = dict(owner=owner, project_id=project_id, project_type=project_type,
                      check_id=check_id, field_id=spec.field_id, key=key,
                      proposed=typed, original=original, name=name,
                      hash=identity.composite_hash, active=ws.active_scenario_id,
                      base_id=base.scenario_id,
                      run_id=ws.last_runtime_snapshot_id,
                      run_scenario_id=ws.last_runtime_scenario_id,
                      version=WORKBOOK.version, nonce=uuid.uuid4().hex)
    return dict(
        finding_id=finding.check_id, finding_status=finding.status.value,
        evidence_source=finding.evidence_source, snapshot_id=ws.last_runtime_snapshot_id,
        stale=state == "STALE", original=original, proposed=typed,
        delta=typed - original, unit=spec.unit or "", name=name,
        field_id=spec.field_id, override_key=key, content_hash=identity.composite_hash,
        token=_token_serializer().dumps(token_data),
    )


def commit(*, owner: str, project_id: str, project_type: str, token: str) -> dict:
    """Exactly ONE transaction: revalidate preview, insert child, otherwise rollback."""
    from app.persistence.db import get_connection
    try:
        data = _token_serializer().loads(token, max_age=TOKEN_MAX_AGE)
    except (BadSignature, SignatureExpired, TypeError, ValueError) as exc:
        raise Q4Rejected("Q4_CONFIRMATION_INVALID_OR_EXPIRED", 409) from exc
    if data.get("owner") != owner or data.get("project_id") != project_id or data.get("project_type") != project_type:
        raise Q4Rejected("Q4_CONFIRMATION_SCOPE_MISMATCH", 403)
    if data.get("version") != WORKBOOK.version:
        raise Q4Rejected("Q4_WORKBOOK_VERSION_CHANGED")
    name = _assert_name(data.get("name"))
    conn = get_connection()
    try:
        conn.execute("BEGIN EXCLUSIVE")
        cur = conn.cursor()
        cur.execute("SELECT * FROM projects WHERE project_id=? AND user_id=?", (project_id, owner))
        project = cur.fetchone()
        if project is None or project["archived"] or project["is_protected"] or project["is_readonly"]:
            raise Q4Rejected("Q4_PROJECT_NOT_EDITABLE", 403)
        cur.execute("SELECT * FROM workspace_states WHERE user_id=? AND project_id=?", (owner, project_id))
        row = cur.fetchone()
        if row is None:
            raise Q4Rejected("Q4_WORKSPACE_NOT_FOUND", 404)
        base = _base_scope(cur, owner, project_id, row["active_scenario_id"])
        if base.scenario_id != data.get("base_id") or row["active_scenario_id"] != data.get("active"):
            raise Q4Rejected("Q4_SCENARIO_SWITCH_CONFLICT")
        identity = assemble_transactional(
            draft_snapshot_json=row["draft_snapshot_json"] or "{}",
            project_id=project_id, user_id=owner,
            active_scenario_id=row["active_scenario_id"],
            active_scenario_name=row["active_scenario_name"], cursor=cur,
            workbook_version=WORKBOOK.version)
        if identity.composite_hash != data.get("hash"):
            raise Q4Rejected("Q4_STALE_PREVIEW_CONFLICT")
        ws = WorkspaceStateRecord.from_row(row)
        if (ws.last_runtime_snapshot_id != data.get("run_id") or
                ws.last_runtime_scenario_id != data.get("run_scenario_id")):
            raise Q4Rejected("Q4_FINDING_RUN_ID_CHANGED")
        snapshot = json.loads(row["draft_snapshot_json"] or "{}")
        _, spec, key, proposed = _mapping(
            data["check_id"], ws, project_type, str(data["proposed"]))
        if spec.field_id != data["field_id"] or key != data["key"]:
            raise Q4Rejected("Q4_MAPPING_CHANGED")
        old = ProjectInputSet.from_snapshot(snapshot).values.get(key)
        if old != data.get("original"):
            raise Q4Rejected("Q4_ORIGINAL_CHANGED")
        _validate_financing(snapshot, spec.field_id, proposed)
        cur.execute("SELECT scenario_name, replay_metadata_json FROM scenarios WHERE user_id=? AND project_id=?",
                    (owner, project_id))
        for sc in cur.fetchall():
            if sc["scenario_name"].casefold() == name.casefold():
                raise Q4Rejected("Q4_SCENARIO_NAME_CONFLICT")
            metadata = json.loads(sc["replay_metadata_json"] or "{}")
            if metadata.get("q4_nonce") == data["nonce"]:
                raise Q4Rejected("Q4_CONFIRMATION_REPLAYED")
        # Scenario persistence's canonical flat-key resolver, no second storage scheme.
        from app.persistence.scenarios_repository import resolve_scenario_snapshot
        source = dict(ProjectInputSet.from_snapshot(snapshot).values)
        overrides = {key: proposed}
        effective = resolve_scenario_snapshot(source, overrides)
        ProjectInputSet.from_snapshot(effective).to_projectinputs()
        sid = uuid.uuid4().hex[:16]
        now = datetime.now(timezone.utc).isoformat()
        audit = dict(action="q4_finding_whatif_v1", q4_nonce=data["nonce"],
                     finding_id=data["check_id"], field_id=spec.field_id,
                     override_key=key, original=old, proposed=proposed,
                     preview_content_hash=data["hash"],
                     source_run_snapshot_id=data["run_id"],
                     source_run_scenario_id=data["run_scenario_id"],
                     base_scenario_id=base.scenario_id,
                     created_at=now)
        cur.execute(
            """INSERT INTO scenarios (
                scenario_id,project_id,user_id,scenario_name,project_code,
                source_project_template,copied_from_scenario_id,archived,
                is_base_case,parent_scenario_id,base_input_set_json,overrides_json,
                snapshot_json,governance_state_json,last_run_summary_json,
                replay_metadata_json,schema_version,full_inputs_json,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,NULL,0,0,?,?,?,?,?,?,?,'1.0',NULL,?,?)""",
            (sid, project_id, owner, name, project["project_code"], "",
             base.scenario_id, json.dumps(source, allow_nan=False),
             json.dumps(overrides, allow_nan=False),
             json.dumps(effective, allow_nan=False),
             "{}", "{}", json.dumps(audit, allow_nan=False), now, now))
        conn.execute("COMMIT")
        return dict(scenario_id=sid, scenario_name=name, state="NOT_RUN",
                    project_code=project["project_code"])
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
