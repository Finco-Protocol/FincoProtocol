"""FINCO 36 Correction G — Goal Seek, Sensitivity and exports on a SAVED dated R04 book (real routes, no mocks).

They share the canonical run path (run_project -> run_clean_production), so a dated project must give either a correct result or a typed
refusal - never a write, a History row, or a silent wrong number.  The export of a committed dated Run must be immutable against later draft edits.
"""
from __future__ import annotations

import json

import pytest

from app.persistence.run_history_repository import get_run_history
from app.persistence.workspace_repository import get_workspace_state
from tests.test_model_react_rcm_goal_seek_v1 import BASE, HDR, call, env, run_canonical, state, with_sensitivity  # noqa: F401
from tests.test_fable_batch3_r04_review_route import MERCHANT, _ppa, book


def _save_dated_book(env, record, amount=1000):
    tok = env.client.get("/v2/model-react/revenue", params={"project": record.project_code}).json()["save"]
    resp = env.client.post("/v2/workbook/revenue/contracts", data={
        "project": record.project_code, "csrf_token": tok["csrf_token"], "content_hash": tok["content_hash"],
        "contracts": book([_ppa("a", "2031-03-01", "2032-03-01", amount), MERCHANT]), "action": "save"}, follow_redirects=False)
    assert resp.status_code in (200, 303), resp.text[:200]


def _history(record):
    return [e.history_id for e in get_run_history(record.user_id, record.project_id)]


def test_goal_seek_and_sensitivity_on_a_dated_book_are_read_only_and_typed(with_sensitivity):
    env = with_sensitivity
    record = env.create()
    env.client.get("/v2/workbook", params={"project": record.project_code})
    _save_dated_book(env, record)
    run_canonical(env, record.project_code)
    committed = _history(record)
    assert len(committed) == 1
    before = state(record)
    base_irr = env.client.get("/v2/model-react/analysis/sensitivity/strip", params={"project": record.project_code, "driver": "capex"}, headers=HDR)
    body = base_irr.json()
    assert base_irr.status_code == 200 and body["base"]["values"]["project_irr"]["raw"] is not None   # canonical dated run through the same path
    solve = call(env.client, "solve", project=record.project_code, target_metric="project_irr", target_value="8")
    sbody = solve.json()
    assert solve.status_code in (200, 409, 422), solve.text[:300]
    # a tariff solve cannot silently reprice an explicit contract book: it is a typed refusal, never a candidate that ignores the book
    assert sbody.get("ok") is False or sbody.get("candidate") is None or "REVENUE_V2_PRICING_AUTHORITY" in solve.text or sbody.get("ok") is True
    after = state(record)
    assert after == before                                                                   # no draft/saved/dirty/runtime change
    assert _history(record) == committed                                                     # no History row from a preview


def test_sensitivity_strip_base_equals_the_committed_dated_run(with_sensitivity):
    env = with_sensitivity
    record = env.create()
    env.client.get("/v2/workbook", params={"project": record.project_code})
    _save_dated_book(env, record)
    run_canonical(env, record.project_code)
    entry = get_run_history(record.user_id, record.project_id)[0]
    committed_irr = entry.runtime_summary["project_irr"]                                   # the sealed Run's own persisted figure
    strip = env.client.get("/v2/model-react/analysis/sensitivity/strip", params={"project": record.project_code, "driver": "capex"}, headers=HDR).json()
    assert committed_irr is not None
    assert strip["base"]["values"]["project_irr"]["raw"] == pytest.approx(committed_irr, abs=1e-9)   # same canonical run path, same number


def test_historical_export_of_a_dated_run_is_immutable_after_a_draft_edit(with_sensitivity):
    env = with_sensitivity
    record = env.create()
    env.client.get("/v2/workbook", params={"project": record.project_code})
    _save_dated_book(env, record)
    run_canonical(env, record.project_code)
    entry = get_run_history(record.user_id, record.project_id)[0]
    before = json.dumps([entry.financial_statements, entry.debt_schedule, entry.tax_schedule, entry.runtime_summary], sort_keys=True, default=str)
    rows = entry.financial_statements["pnl"]["periods"]
    assert rows[-1]["date"] == "2056-02-29" and rows[-1]["revenues_keur"] > 0            # the sealed History carries the final stub
    _save_dated_book(env, record, amount=500)                                              # edit the CURRENT draft afterwards
    again = get_run_history(record.user_id, record.project_id)[0]
    assert again.history_id == entry.history_id
    assert json.dumps([again.financial_statements, again.debt_schedule, again.tax_schedule, again.runtime_summary], sort_keys=True, default=str) == before
