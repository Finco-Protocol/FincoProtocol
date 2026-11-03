"""PR-U2 / D13 — read-only proof of the CURRENT profile lifecycle on the real app (no semantic change; D13 Q1 stays CONTRACT_BLOCKED_OWNER_Q1).

Pins what exists today, so a later Q1 decision is made against measured behaviour:
* retiring a profiled CAPEX line keeps the saved profile document byte for byte;
* the next Run is refused with ``CAPEX_PROFILE_LEAF_UNKNOWN`` and writes no history row; the last signed Run entry is unchanged;
* reactivating the line restores a runnable state and the Run uses the kept profile;
* a stale composite hash on deactivate is refused and changes nothing;
* saving a document that still names the retired leaf is refused and nothing is written.
Synthetic reference projects only.
"""
from __future__ import annotations

import pytest

from app.capex_profiles import config
from app.capex_profiles.runtime import CapexProfileBindingError
from app.capex_profiles.service import CapexProfileConflict
from app.persistence.run_history_repository import get_run_history
from app.workbook.registry import WORKBOOK
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401
from tests.test_model_rc7_capex_profile_run import (  # noqa: F401  (shared helpers + fixtures of the protected RC-7 suite)
    OWNER, _base_leaves, _hash, _latest, _planner_routes, _row, _run, _save, _ws, solar,
)


def _doc_bytes(project):
    return (_ws(project).draft_snapshot or {}).get(config.SNAPSHOT_KEY)


def _profiled_retired(solar):
    from app.persistence.capex_sub_lines import get_active_sub_lines_for_project
    from app.persistence.projects_repository import get_project_by_id
    from app.v2 import capex_commands as commands
    leaf = next(l for l in _base_leaves(solar) if not l.item_key.startswith("base:"))
    sub = next(s for s in get_active_sub_lines_for_project(solar.project_id) if s.business_code == leaf.item_key)
    _save(solar, [_row(leaf.item_key, "FRONT_LOADED")])
    return leaf, sub, commands, get_project_by_id(solar.project_id)


def test_retire_keeps_the_document_and_the_run_is_refused_without_history(env, solar):
    leaf, sub, commands, record = _profiled_retired(solar)
    before_doc = _doc_bytes(solar)
    assert before_doc and leaf.item_key in before_doc
    history = get_run_history(OWNER, solar.project_id)
    last = history[0]
    commands.deactivate_capex_line(project_record=record, user_id=OWNER, sub_line_id=sub.sub_line_id, row_version=sub.updated_at,
                                   workbook_version=WORKBOOK.version, expected_content_hash=_hash(solar))
    assert _doc_bytes(solar) == before_doc                                         # retire keeps the profile byte for byte
    response = _run(env, solar)
    assert "CAPEX_PROFILE_LEAF_UNKNOWN" in response.text
    after = get_run_history(OWNER, solar.project_id)
    assert len(after) == len(history)                                              # no history row
    assert _latest(solar).history_id == last.history_id and _latest(solar).runtime_summary == last.runtime_summary   # last Run untouched


def test_reactivate_restores_and_the_run_uses_the_kept_profile(env, solar):
    from app.persistence.capex_sub_lines import list_sub_lines_for_project
    leaf, sub, commands, record = _profiled_retired(solar)
    doc = _doc_bytes(solar)
    commands.deactivate_capex_line(project_record=record, user_id=OWNER, sub_line_id=sub.sub_line_id, row_version=sub.updated_at,
                                   workbook_version=WORKBOOK.version, expected_content_hash=_hash(solar))
    from app.persistence.db import get_connection
    conn = get_connection()
    try:
        rows = list_sub_lines_for_project(conn.cursor(), solar.project_id, include_inactive=True)
    finally:
        conn.close()
    retired = next(s for s in rows if s.sub_line_id == sub.sub_line_id)
    commands.reactivate_capex_line(project_record=record, user_id=OWNER, sub_line_id=sub.sub_line_id, row_version=retired.updated_at,
                                   workbook_version=WORKBOOK.version, expected_content_hash=_hash(solar))
    assert _doc_bytes(solar) == doc
    count = len(get_run_history(OWNER, solar.project_id))
    response = _run(env, solar)
    assert response.status_code == 200 and "CAPEX_PROFILE_LEAF_UNKNOWN" not in response.text
    assert len(get_run_history(OWNER, solar.project_id)) == count + 1


def test_stale_hash_on_deactivate_changes_nothing(env, solar):
    leaf, sub, commands, record = _profiled_retired(solar)
    doc, stale = _doc_bytes(solar), "0" * 64
    with pytest.raises(commands.CapexConcurrentEditError):
        commands.deactivate_capex_line(project_record=record, user_id=OWNER, sub_line_id=sub.sub_line_id, row_version=sub.updated_at,
                                       workbook_version=WORKBOOK.version, expected_content_hash=stale)
    from app.persistence.capex_sub_lines import get_active_sub_lines_for_project
    assert any(s.sub_line_id == sub.sub_line_id for s in get_active_sub_lines_for_project(solar.project_id))
    assert _doc_bytes(solar) == doc


def test_saving_a_document_that_names_the_retired_leaf_is_refused(env, solar):
    leaf, sub, commands, record = _profiled_retired(solar)
    commands.deactivate_capex_line(project_record=record, user_id=OWNER, sub_line_id=sub.sub_line_id, row_version=sub.updated_at,
                                   workbook_version=WORKBOOK.version, expected_content_hash=_hash(solar))
    doc = _doc_bytes(solar)
    with pytest.raises((CapexProfileBindingError, CapexProfileConflict)) as exc:
        _save(solar, [_row(leaf.item_key, "BACK_LOADED")])
    assert "LEAF" in getattr(exc.value, "code", str(exc.value)).upper() or "UNKNOWN" in str(exc.value).upper(), exc.value
    assert _doc_bytes(solar) == doc
