"""PR-U2 / D7 — synthetic oracle for the CURRENT two-writer contract (Save All and Save profile). Read-only proof; Save All is NOT changed.

D7 (one atomic Save across cells, lines AND the CAPEX profile document) is CONTRACT_BLOCKED_R1_OR_FINANCIAL_AUTHORITY: the parallel R1 PR owns the
Save All wire. What exists today, and what any later combined save must keep, is pinned here on the real app:
* each writer has its own composite CAS; neither can overwrite an edit the other committed (no lost update in either order);
* a refused write changes nothing (cells, profile document and composite hash stay exactly as they were);
* two fresh, sequential writes both persist — the user-visible "save both" is two commits, each one atomic.
Synthetic reference projects only.
"""
from __future__ import annotations

import uuid

import pytest

from app.capex_profiles import config
from app.capex_profiles.service import CapexProfileConflict
from app.persistence.projects_repository import get_project_by_id
from app.v2.save_all_commands import SaveAllInput, save_all
from app.workbook.registry import WORKBOOK
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401
from tests.test_model_rc7_capex_profile_run import (  # noqa: F401  (shared helpers + fixtures of the protected RC-7 suite)
    OWNER, _base_leaves, _hash, _planner_routes, _row, _save, _ws, solar,
)

CELL = ("revenue.ppa.base_tariff", "57")


def _state(project):
    from app.workbook.service import WorkbookService
    ws = _ws(project)
    value = WorkbookService.build_draft_input_set_from_workspace(ws).get(CELL[0])
    return _hash(project), (ws.draft_snapshot or {}).get(config.SNAPSHOT_KEY), None if value is None else float(value)


def _save_all(project, expected, value=CELL[1]):
    ws = _ws(project)
    return save_all(project_record=get_project_by_id(project.project_id), user_id=OWNER,
                    data=SaveAllInput(request_id=uuid.uuid4().hex, workbook_version=WORKBOOK.version, content_hash=expected,
                                      scenario_id=ws.active_scenario_id, cells=((CELL[0], value),)))


def _key(project):
    return next(l for l in _base_leaves(project) if not l.item_key.startswith("base:")).item_key


def test_profile_save_on_a_hash_older_than_a_save_all_is_refused_and_changes_nothing(env, solar):
    old = _hash(solar)
    _save_all(solar, old)
    after_cells = _state(solar)
    assert after_cells[2] == float(CELL[1])
    with pytest.raises(CapexProfileConflict) as exc:
        _save(solar, [_row(_key(solar), "FRONT_LOADED")], expected=old)
    assert exc.value.code == "CAPEX_PROFILE_STALE"
    assert _state(solar) == after_cells                                   # the Save All edit survives; nothing written


def test_save_all_on_a_hash_older_than_a_profile_save_is_refused_and_changes_nothing(env, solar):
    old = _hash(solar)
    _save(solar, [_row(_key(solar), "BACK_LOADED")], expected=old)
    after_profile = _state(solar)
    from app.v2.capex_commands import CapexStaleIdentityError       # Save All's one composite CAS (check_identity_in_tx)
    with pytest.raises(CapexStaleIdentityError):
        _save_all(solar, old, value="58")
    assert _state(solar) == after_profile                                 # the profile survives; the cell was not written


def test_two_fresh_sequential_writes_both_persist(env, solar):
    _save_all(solar, _hash(solar))
    _save(solar, [_row(_key(solar), "UNIFORM")])
    _, doc, cell = _state(solar)
    assert doc and _key(solar) in doc and cell == float(CELL[1])
