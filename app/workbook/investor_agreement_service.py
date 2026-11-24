"""F4 agreement edits in the existing owner/scenario stores and composite CAS."""
import json

from app.model_v2.investor_f4 import (
    SNAPSHOT_KEY, InvestorAgreementInputError, parse_terms,
)
from app.persistence._helpers import _now_utc, _to_json
from app.persistence.db import get_connection
from app.workbook.registry import WORKBOOK
from app.workbook.workbook_identity import assemble_transactional


class InvestorAgreementConflict(ValueError):
    pass


def effective_raw(snapshot, scenario=None):
    # Non-Base scenarios require their own deliberate agreement Save. No silent
    # inheritance of legal terms or substitution of the selected scenario.
    if scenario is not None and not scenario.is_base_case:
        return scenario.overrides.get(SNAPSHOT_KEY, "")
    return snapshot.get(SNAPSHOT_KEY, "")


def save_agreement(*, owner, project_id, expected_hash, raw, remove=False):
    terms = None if remove else parse_terms(raw)
    if terms is None and not remove:
        raise InvestorAgreementInputError("An explicit agreement is required")
    conn = get_connection()
    try:
        conn.execute("BEGIN EXCLUSIVE")
        cur = conn.cursor()
        cur.execute("SELECT * FROM projects WHERE project_id=? AND user_id=? AND archived=0", (project_id, owner))
        project = cur.fetchone()
        from app.persistence.records import ProjectRecord
        from app.ui.protected_reference_service import is_protected_reference
        if project is None or is_protected_reference(ProjectRecord.from_row(project)):
            raise InvestorAgreementConflict("Project is unavailable or read-only")
        cur.execute("SELECT * FROM workspace_states WHERE user_id=? AND project_id=?", (owner, project_id))
        ws = cur.fetchone()
        if ws is None:
            raise InvestorAgreementConflict("Workspace is unavailable")
        draft = json.loads(ws["draft_snapshot_json"] or "{}")
        args = dict(project_id=project_id, user_id=owner, active_scenario_id=ws["active_scenario_id"],
                    active_scenario_name=ws["active_scenario_name"], cursor=cur, workbook_version=WORKBOOK.version)
        identity = assemble_transactional(draft_snapshot_json=_to_json(draft), **args)
        if not expected_hash or identity.composite_hash != expected_hash:
            raise InvestorAgreementConflict("Working inputs or scenario changed; reload")
        scenario = None
        if ws["active_scenario_id"]:
            cur.execute("SELECT * FROM scenarios WHERE scenario_id=? AND user_id=? AND project_id=? AND archived=0",
                        (ws["active_scenario_id"], owner, project_id))
            row = cur.fetchone()
            if row is None:
                raise InvestorAgreementConflict("Active scenario is unavailable")
            from app.persistence.records import ScenarioRecord
            scenario = ScenarioRecord.from_row(row)
        previous = parse_terms(effective_raw(draft, scenario))
        scenario_key = scenario.scenario_id if (scenario is not None and not scenario.is_base_case) else ""
        now_iso = _now_utc().isoformat()
        from app.persistence.investor_agreement_ledger_repository import (
            get_max_version,
            record_version,
            tombstone_agreement,
        )
        if terms is None:
            if previous is not None:
                tombstone_agreement(
                    cur,
                    owner_id=owner,
                    project_id=project_id,
                    scenario_id=scenario_key,
                    agreement_id=previous.agreement_id,
                    min_version=previous.version,
                    now_iso=now_iso,
                )
        else:
            if previous is not None and previous.agreement_id != terms.agreement_id:
                tombstone_agreement(
                    cur,
                    owner_id=owner,
                    project_id=project_id,
                    scenario_id=scenario_key,
                    agreement_id=previous.agreement_id,
                    min_version=previous.version,
                    now_iso=now_iso,
                )
            ledger_max = get_max_version(
                cur,
                owner_id=owner,
                project_id=project_id,
                scenario_id=scenario_key,
                agreement_id=terms.agreement_id,
            )
            prev_ver = previous.version if (previous is not None and previous.agreement_id == terms.agreement_id) else 0
            expected_version = max(ledger_max, prev_ver) + 1
            if terms.version != expected_version:
                if ledger_max >= terms.version:
                    raise InvestorAgreementConflict(
                        f"Agreement version {terms.agreement_id} v{terms.version} was already used or retired; "
                        f"next version must be v{expected_version}"
                    )
                raise InvestorAgreementConflict("Agreement version changed; reload")
            record_version(
                cur,
                owner_id=owner,
                project_id=project_id,
                scenario_id=scenario_key,
                agreement_id=terms.agreement_id,
                version=terms.version,
                updated_at=now_iso,
                tombstoned_at=None,
            )
        value = terms.to_json() if terms else ""
        if scenario is not None and not scenario.is_base_case:
            from app.persistence.scenarios_repository import resolve_scenario_snapshot
            overrides = dict(scenario.overrides)
            overrides[SNAPSHOT_KEY] = value
            effective = resolve_scenario_snapshot(draft, overrides)
            cur.execute("UPDATE scenarios SET overrides_json=?, snapshot_json=?, updated_at=? WHERE scenario_id=? AND user_id=?",
                        (_to_json(overrides), _to_json(effective), now_iso, scenario.scenario_id, owner))
        else:
            if terms is None:
                draft.pop(SNAPSHOT_KEY, None)
            else:
                draft[SNAPSHOT_KEY] = value
        new_identity = assemble_transactional(draft_snapshot_json=_to_json(draft), **args)
        cur.execute("UPDATE workspace_states SET draft_snapshot_json=?, draft_content_hash=?, dirty=1, updated_at=? WHERE workspace_id=? AND user_id=?",
                    (_to_json(draft), new_identity.composite_hash, now_iso, ws["workspace_id"], owner))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
