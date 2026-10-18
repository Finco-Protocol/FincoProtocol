"""RC-7A cross-stream: Reporting V2 (#316) must expose exactly the CAPEX-profiled funding a Run committed (#317), never an unprofiled schedule."""
from __future__ import annotations

import pytest

from app.export.run_evidence import evidence_from_history_entry
from tests.test_model_rc7_capex_profile_run import (  # noqa: F401
    OWNER, _base_leaves, _financing, _hash, _latest, _periods, _row, _run, _save, _ws, env, solar, _planner_routes)
from app.persistence.projects_repository import get_project


def _evidence(project, entry):
    record = get_project(project.project_id, OWNER)
    ws = _ws(project)
    return evidence_from_history_entry(entry, record, last_run_snapshot_id=ws.last_runtime_snapshot_id,
                                       last_run_is_stale=False, freshness_source="test")


def test_report_evidence_of_a_profiled_run_carries_the_profiled_funding_and_the_default_run_stays_default(env, solar):
    base = _latest(solar)
    base_evidence = _evidence(solar, base)
    _save(solar, [_row(l.item_key, "FRONT_LOADED") for l in _base_leaves(solar)])
    assert _run(env, solar).status_code == 200
    bound = _latest(solar)
    bound_evidence = _evidence(solar, bound)
    # the report input is the persisted Run evidence, passed through unchanged
    assert bound_evidence.integrity_evidence["sources_uses"]["construction_periods"] == _periods(bound)
    assert len(bound_evidence.integrity_evidence["sources_uses"]["construction_periods"]) == 14
    assert len(base_evidence.integrity_evidence["sources_uses"]["construction_periods"]) == 3
    assert bound_evidence.runtime_summary["financing_evidence"]["sources_uses"] == _financing(bound)
    assert bound_evidence.evidence_digest != base_evidence.evidence_digest
    # the older Run's report input is unaffected by the newer profiled Run
    assert _evidence(solar, base).evidence_digest == base_evidence.evidence_digest
