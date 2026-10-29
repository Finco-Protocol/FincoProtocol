"""Authorized transactional contract edits using the existing scalar/scenario stores."""
from __future__ import annotations

import json

from app.persistence._helpers import _now_utc, _to_json
from app.persistence.db import get_connection
from app.workbook.registry import WORKBOOK
from app.workbook.revenue_multistream import FIELD_ID, SNAPSHOT_KEY, canonical_json
from app.workbook.workbook_identity import assemble_transactional


class RevenueContractConflict(ValueError):
    pass


def save_contracts_in_tx(cur, *, owner, project_id, expected_hash, raw, inherit=False, field_id=FIELD_ID, skip_cas=False):
    """The contract write on the CALLER's cursor and transaction (no BEGIN/COMMIT here).

    ``skip_cas`` is for a composing caller (Save All) that has already checked the composite identity once under
    its own exclusive transaction; every other check (project, scenario, validation) is unchanged.
    """
    snapshot_key, canonical = SNAPSHOT_KEY, canonical_json
    if field_id == "project_setup.bess.configuration":
        from app.workbook.bess_config import SNAPSHOT_KEY as snapshot_key, canonical_json as canonical, ACTIVATION_ENABLED
        if not ACTIVATION_ENABLED:
            raise ValueError("BESS_FINANCIAL_ACTIVATION_RELEASE_CLOSED")
    elif field_id != FIELD_ID:
        raise ValueError("TYPED_CONTRACT_FIELD_NOT_AUTHORIZED")
    value = "" if inherit else canonical(raw)
    cur.execute("SELECT * FROM projects WHERE project_id=? AND user_id=? AND archived=0", (project_id, owner))
    project = cur.fetchone()
    from app.persistence.records import ProjectRecord
    from app.ui.protected_reference_service import is_protected_reference
    if project is None or is_protected_reference(ProjectRecord.from_row(project)):
        raise RevenueContractConflict("Project is unavailable or read-only; reload")
    if field_id == "project_setup.bess.configuration" and project["project_type"].lower() != "storage":
        raise ValueError("BESS_STANDALONE_SCOPE_REQUIRED")
    cur.execute("SELECT * FROM workspace_states WHERE user_id=? AND project_id=?", (owner, project_id))
    ws = cur.fetchone()
    if ws is None:
        raise RevenueContractConflict("Workspace no longer exists; reload")
    identity_args = dict(project_id=project_id, user_id=owner,
        active_scenario_id=ws["active_scenario_id"], active_scenario_name=ws["active_scenario_name"],
        cursor=cur, workbook_version=WORKBOOK.version)
    draft = json.loads(ws["draft_snapshot_json"] or "{}")
    identity = assemble_transactional(draft_snapshot_json=_to_json(draft), **identity_args)
    if not skip_cas and (not expected_hash or identity.composite_hash != expected_hash):
        raise RevenueContractConflict("Working inputs or scenario selection changed; reload")
    cur.execute("SELECT * FROM scenarios WHERE scenario_id=? AND user_id=? AND project_id=? AND archived=0",
                (ws["active_scenario_id"], owner, project_id))
    scenario = cur.fetchone()
    if ws["active_scenario_id"] and scenario is None:
        raise RevenueContractConflict("Active scenario is unavailable; reload")
    from app.persistence.scenarios_repository import resolve_scenario_snapshot
    from app.workbook.input_set import ProjectInputSet
    if scenario is not None and not scenario["is_base_case"]:
        overrides = json.loads(scenario["overrides_json"] or "{}")
        if inherit:
            overrides.pop(snapshot_key, None)
        else:
            overrides[snapshot_key] = value
        # Match Run: current draft plus explicit scenario contracts, never a stale Base snapshot.
        effective = resolve_scenario_snapshot(draft, overrides)
        ProjectInputSet.from_snapshot(effective).to_projectinputs()
        cur.execute("UPDATE scenarios SET overrides_json=?, snapshot_json=?, updated_at=? WHERE scenario_id=? AND user_id=?",
                    (_to_json(overrides), _to_json(effective), _now_utc().isoformat(), scenario["scenario_id"], owner))
    else:
        if inherit:
            raise ValueError("Base contracts cannot inherit from another scenario")
        pis = ProjectInputSet.from_snapshot(draft).with_value(field_id, value)
        pis.to_projectinputs()
        draft = pis.to_snapshot()
    new_identity = assemble_transactional(draft_snapshot_json=_to_json(draft), **identity_args)
    cur.execute("UPDATE workspace_states SET draft_snapshot_json=?, draft_content_hash=?, dirty=1, updated_at=? WHERE workspace_id=? AND user_id=?",
                (_to_json(draft), new_identity.composite_hash, _now_utc().isoformat(), ws["workspace_id"], owner))


def save_contracts(*, owner, project_id, expected_hash, raw, inherit=False, field_id=FIELD_ID):
    """Replace one payload; selection and content CAS are checked under the write lock.

    Caller must resolve project write authority before entry. Identity is never
    supplied by a browser scenario ID. No Run or financial calculation occurs.
    """
    conn = get_connection()
    try:
        conn.execute("BEGIN EXCLUSIVE")
        cur = conn.cursor()
        save_contracts_in_tx(cur, owner=owner, project_id=project_id, expected_hash=expected_hash, raw=raw,
                             inherit=inherit, field_id=field_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
