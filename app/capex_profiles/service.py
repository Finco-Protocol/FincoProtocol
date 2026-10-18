"""RC-7 - authorised transactional Save/Reset of the monthly CAPEX profile document.

Same locking, ownership, protected-reference and composite-CAS protocol as the Developer Economics / Revenue / Investor commands:
one ``BEGIN EXCLUSIVE`` transaction re-checks project ownership, the workspace, the scenario selection and the composite workbook
identity the editor was rendered from, then writes ONE snapshot key and sets ``dirty=1`` in the same transaction.  Nothing here runs
the model.  The candidate is first proved bindable by materialising the exact effective Run inputs (same sub-line fold the Run uses)
and binding the document to them; an unbindable document is rejected and nothing is written.

Scope: Base scenario only.  Scenarios inherit the saved document; a scenario-specific profile is refused (typed) rather than stored
without a Run that honours it.  Caller must have verified CSRF before entry.
"""
from __future__ import annotations

import json
from typing import Optional

from app.capex_profiles import config
from app.capex_profiles.contract import ProfileError
from app.capex_profiles.runtime import CapexProfileBindingError, RuntimeBinding, bind_inputs
from app.persistence._helpers import _now_utc, _to_json
from app.persistence.db import get_connection
from app.workbook.registry import WORKBOOK
from app.workbook.workbook_identity import assemble_consistent_for_get, assemble_transactional


class CapexProfileConflict(ValueError):
    """Stale identity, unavailable/read-only project or a non-Base scenario; nothing was written."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


def materialize(snapshot: dict, project_id: str, raw: str, scenario_overrides: Optional[dict] = None) -> RuntimeBinding:
    """Bind ``raw`` to the exact effective Run inputs of ``snapshot`` (sub-lines folded as the Run folds them).  No engine run."""
    import dataclasses

    from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
    from app.workbook.input_set import ProjectInputSet

    pi = ProjectInputSet.from_snapshot(dict(snapshot)).to_projectinputs()
    folded = apply_user_sub_lines_replacing_base(pi.capex, project_id=project_id, scenario_overrides=scenario_overrides)
    if folded is not pi.capex:
        pi = dataclasses.replace(pi, capex=folded)
    return bind_inputs(pi, raw, project_id=project_id, scenario_overrides=scenario_overrides)


def save_profiles(*, owner: str, project_id: str, expected_hash: str, expected_scenario_id: str = "", raw="") -> str:
    """Replace (or, with an empty document, remove) the profile document.  Returns the new composite identity hash."""
    try:
        value = config.canonical_json(raw)
    except ProfileError as exc:
        raise CapexProfileBindingError(exc.code, str(exc)) from exc
    from app.persistence.records import ProjectRecord
    from app.persistence.workspace_repository import get_workspace_state
    from app.ui.protected_reference_service import is_protected_reference

    ws0 = get_workspace_state(owner, project_id)
    if ws0 is None:
        raise CapexProfileConflict("CAPEX_PROFILE_WORKSPACE_MISSING", "Workspace no longer exists; reload")
    if ws0.active_scenario_id:
        from app.persistence.scenarios_repository import get_scenario
        scenario = get_scenario(ws0.active_scenario_id, owner)
        if scenario is None or not scenario.is_base_case:
            raise CapexProfileConflict("CAPEX_PROFILE_SCENARIO_EDIT_UNSUPPORTED",
                                       "switch to the Base case; scenarios inherit the saved profile and cannot own one yet")
    current = assemble_consistent_for_get(owner, project_id, WORKBOOK.version)
    if not expected_hash or current.composite_hash != expected_hash:
        raise CapexProfileConflict("CAPEX_PROFILE_STALE", "Working inputs changed; reload")
    draft = dict(ws0.draft_snapshot)
    if value:
        draft[config.SNAPSHOT_KEY] = value
        materialize(draft, project_id, value)            # raises CapexProfileBindingError -> nothing written
    else:
        draft.pop(config.SNAPSHOT_KEY, None)

    conn = get_connection()
    try:
        conn.execute("BEGIN EXCLUSIVE")
        cur = conn.cursor()
        cur.execute("SELECT * FROM projects WHERE project_id=? AND user_id=? AND archived=0", (project_id, owner))
        project = cur.fetchone()
        if project is None or is_protected_reference(ProjectRecord.from_row(project)):
            raise CapexProfileConflict("CAPEX_PROFILE_PROJECT_UNAVAILABLE", "Project is unavailable or read-only; reload")
        cur.execute("SELECT * FROM workspace_states WHERE user_id=? AND project_id=?", (owner, project_id))
        ws = cur.fetchone()
        if ws is None:
            raise CapexProfileConflict("CAPEX_PROFILE_WORKSPACE_MISSING", "Workspace no longer exists; reload")
        if (ws["active_scenario_id"] or "") != (expected_scenario_id or ""):
            raise CapexProfileConflict("CAPEX_PROFILE_SCENARIO_CHANGED", "Scenario selection changed; reload")
        identity_args = dict(project_id=project_id, user_id=owner, active_scenario_id=ws["active_scenario_id"],
                             active_scenario_name=ws["active_scenario_name"], cursor=cur, workbook_version=WORKBOOK.version)
        persisted = json.loads(ws["draft_snapshot_json"] or "{}")
        identity = assemble_transactional(draft_snapshot_json=_to_json(persisted), **identity_args)
        if identity.composite_hash != expected_hash:
            raise CapexProfileConflict("CAPEX_PROFILE_STALE", "Working inputs or scenario selection changed; reload")
        # the validated candidate was derived from exactly the state the CAS just proved unchanged
        new_snapshot = dict(persisted)
        if value:
            new_snapshot[config.SNAPSHOT_KEY] = value
        else:
            new_snapshot.pop(config.SNAPSHOT_KEY, None)
        new_identity = assemble_transactional(draft_snapshot_json=_to_json(new_snapshot), **identity_args)
        cur.execute("UPDATE workspace_states SET draft_snapshot_json=?, draft_content_hash=?, dirty=1, updated_at=? "
                    "WHERE workspace_id=? AND user_id=?",
                    (_to_json(new_snapshot), new_identity.composite_hash, _now_utc().isoformat(), ws["workspace_id"], owner))
        conn.commit()
        return new_identity.composite_hash
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
