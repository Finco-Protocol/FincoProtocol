"""Authorized transactional Developer Economics configuration Save/Reset.

Same locking, ownership, protected-reference and composite-CAS protocol as the Revenue contract
and Investor agreement commands. Nothing here runs the model or computes a financial figure; the
candidate is validated by materialising the exact effective typed ``ProjectInputs`` that a Run would
use and asking the canonical calculator's own validator, inside the exclusive transaction.
"""
from __future__ import annotations

import json

from app.persistence._helpers import _now_utc, _to_json
from app.persistence.db import get_connection
from app.workbook.developer_economics_config import (
    SNAPSHOT_KEY, DeveloperConfigError, apply_config, canonical_json, parse_config,
)
from app.workbook.registry import WORKBOOK
from app.workbook.workbook_identity import assemble_transactional


class DeveloperEconomicsConflict(ValueError):
    """Stale identity, unavailable/read-only project or scenario; nothing was written."""


def save_configuration(*, owner, project_id, expected_hash, expected_scenario_id="", raw="", inherit=False):
    """Replace (or, with ``inherit``, remove a child scenario's override of) the configuration.

    ``expected_hash`` is the composite workbook identity the editor was rendered from and
    ``expected_scenario_id`` the scenario selection it was rendered for; both are re-checked under
    the write lock. Base saves write the single versioned snapshot key; a non-Base scenario saves
    exactly one override key. Caller must have verified CSRF before entry.
    """
    value = "" if inherit else canonical_json(raw)
    if not inherit and not value:
        raise DeveloperConfigError("DEV_ECON_REQUIRED: an explicit Developer Economics configuration is required")
    conn = get_connection()
    try:
        conn.execute("BEGIN EXCLUSIVE")
        cur = conn.cursor()
        cur.execute("SELECT * FROM projects WHERE project_id=? AND user_id=? AND archived=0", (project_id, owner))
        project = cur.fetchone()
        from app.persistence.records import ProjectRecord
        from app.ui.protected_reference_service import is_protected_reference
        if project is None or is_protected_reference(ProjectRecord.from_row(project)):
            raise DeveloperEconomicsConflict("Project is unavailable or read-only; reload")
        cur.execute("SELECT * FROM workspace_states WHERE user_id=? AND project_id=?", (owner, project_id))
        ws = cur.fetchone()
        if ws is None:
            raise DeveloperEconomicsConflict("Workspace no longer exists; reload")
        if (ws["active_scenario_id"] or "") != (expected_scenario_id or ""):
            raise DeveloperEconomicsConflict("Scenario selection changed; reload")
        identity_args = dict(project_id=project_id, user_id=owner,
                             active_scenario_id=ws["active_scenario_id"],
                             active_scenario_name=ws["active_scenario_name"],
                             cursor=cur, workbook_version=WORKBOOK.version)
        draft = json.loads(ws["draft_snapshot_json"] or "{}")
        identity = assemble_transactional(draft_snapshot_json=_to_json(draft), **identity_args)
        if not expected_hash or identity.composite_hash != expected_hash:
            raise DeveloperEconomicsConflict("Working inputs or scenario selection changed; reload")
        cur.execute("SELECT * FROM scenarios WHERE scenario_id=? AND user_id=? AND project_id=? AND archived=0",
                    (ws["active_scenario_id"], owner, project_id))
        scenario = cur.fetchone()
        if ws["active_scenario_id"] and scenario is None:
            raise DeveloperEconomicsConflict("Active scenario is unavailable; reload")
        from app.persistence.scenarios_repository import resolve_scenario_snapshot
        from app.workbook.input_set import ProjectInputSet
        if scenario is not None and not scenario["is_base_case"]:
            overrides = json.loads(scenario["overrides_json"] or "{}")
            if inherit:
                overrides.pop(SNAPSHOT_KEY, None)
            else:
                overrides[SNAPSHOT_KEY] = value
            effective = resolve_scenario_snapshot(draft, overrides)   # Working Copy + explicit override
            ProjectInputSet.from_snapshot(effective).to_projectinputs()   # fail closed on the exact Run inputs
            cur.execute("UPDATE scenarios SET overrides_json=?, snapshot_json=?, updated_at=? "
                        "WHERE scenario_id=? AND user_id=?",
                        (_to_json(overrides), _to_json(effective), _now_utc().isoformat(),
                         scenario["scenario_id"], owner))
        else:
            if inherit:
                raise DeveloperConfigError("DEV_ECON_BASE_INHERIT: the Base configuration has nothing to inherit")
            pis = ProjectInputSet.from_snapshot(draft).with_value(WORKBOOK_FIELD_ID, value)
            pis.to_projectinputs()
            draft = pis.to_snapshot()
        new_identity = assemble_transactional(draft_snapshot_json=_to_json(draft), **identity_args)
        cur.execute("UPDATE workspace_states SET draft_snapshot_json=?, draft_content_hash=?, dirty=1, updated_at=? "
                    "WHERE workspace_id=? AND user_id=?",
                    (_to_json(draft), new_identity.composite_hash, _now_utc().isoformat(), ws["workspace_id"], owner))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


from app.workbook.developer_economics_config import FIELD_ID as WORKBOOK_FIELD_ID  # noqa: E402
