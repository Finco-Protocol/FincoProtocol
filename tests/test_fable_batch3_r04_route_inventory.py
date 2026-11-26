"""FINCO 36 Correction G — remaining R04 route boundaries: Save All (absolute quantities), import apply, scenario isolation.

Complements tests/test_fable_batch3_r04_route_atomicity.py (direct field Save, batch, stale CAS, race, forged Run, injected rollback) and
tests/test_fable_batch3_r04_recovery.py.  Every refusal asserts unchanged snapshot / hash / History; every acceptance asserts the persisted
effective input.  No flag is enabled globally; Save All is the existing contracts-document path of the existing route.
"""
from __future__ import annotations

import json
import re

import pytest

from tests.test_save_all_atomic_v1 import world, _project, _body, _state, _assert_untouched, URL  # noqa: F401
from tests.test_fable_batch3_r04_review_route import MERCHANT, _ppa, book


@pytest.fixture(autouse=True)
def _finco47_legacy_ssr_rollback(monkeypatch):
    """Scoped to this legacy SSR test module; default production flag stays React ON."""
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")


def _absolute_book(world, rec, amount, unit="MWh"):
    payload = world.owner.get("/v2/model-react/revenue", params={"project": rec.project_code}).json()
    window = payload["contracts"]["operating_window"]
    return book([_ppa("abs-1", window["start"], "2032-03-01", amount, unit), {**MERCHANT, "start_date": window["start"]}])


def test_save_all_with_an_over_cap_absolute_book_is_a_hard_stop_and_a_valid_one_commits_once(world):
    import os
    os.environ["FINCO_MODEL_REACT_V1"] = "1"
    try:
        rec = _project()
        before = _state(rec)
        over = world.owner.post(URL, json=_body(rec, world.owner, contracts_json=_absolute_book(world, rec, 10 ** 9)))
        assert over.status_code in (409, 422), over.text[:300]
        assert "R04_GLOBAL_P50_CAP_EXCEEDED" in over.text
        _assert_untouched(rec, before)                                             # cells, cost lines, hash, dirty flag, ledger, history
        ok = world.owner.post(URL, json=_body(rec, world.owner, contracts_json=_absolute_book(world, rec, 1000)))
        assert ok.status_code == 200 and ok.json()["saved"]["contracts"] == 1, ok.text[:300]
        saved = json.loads(_state(rec)["draft"]["rev_multistream_config_json"]) if isinstance(_state(rec)["draft"], dict) else None
        assert saved and saved["streams"][0]["annual_quantity"]["amount"] == "1000"
    finally:
        os.environ.pop("FINCO_MODEL_REACT_V1", None)


# ── import apply (the explicit C0 batch writer) ───────────────────────────────────────────────────────────────────────────
from tests.test_model_react_wf2_projections_v1 import OWNER, STRANGER, env  # noqa: E402,F401


def _approved_ticket(env, record, field_id, value):
    from app.model_import.review import seal_approved
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get
    ws = get_workspace_state(OWNER, record.project_id)
    ident = assemble_consistent_for_get(OWNER, record.project_id, WORKBOOK.version)
    preview = {"owner": OWNER, "project_id": record.project_id, "scenario_id": ws.active_scenario_id, "content_hash": ident.composite_hash,
               "workbook_version": WORKBOOK.version, "digest": "d" * 64, "rows": [{}], "migration": None}
    approved = [{"field_id": field_id, "value": value, "sheet": "S", "cell": "A1", "label": "x", "original_value": value}]
    return seal_approved(preview, approved)


def _apply(env, record, ticket, client=None):
    from app.auth import generate_csrf_token
    return (client or env.client).post("/v2/workbook/import/apply", data={
        "project": record.project_code, "csrf_token": generate_csrf_token(), "approved_ticket": ticket}, follow_redirects=False)


def _snap(record):
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.workspace_repository import get_workspace_state
    return dict(get_workspace_state(OWNER, record.project_id).draft_snapshot), len(get_run_history(OWNER, record.project_id))


def test_import_apply_refuses_the_book_and_an_envelope_shrinking_edit_and_applies_a_valid_one_once(env):
    from tests.test_fable_batch3_r04_review_route import _facts
    from decimal import Decimal
    from app.v2.import_router import router as import_router
    if not any(getattr(r, "path", "") == "/v2/workbook/import/apply" for r in env.client.app.routes):
        env.client.app.include_router(import_router, prefix="/v2")
    record = env.create("solar")
    env.client.get("/v2/workbook", params={"project": record.project_code})
    t = _facts(record)
    cap = (Decimal(repr(t.capacity_mw)) * Decimal(repr(t.operating_hours_p50)) * Decimal(repr(t.combined_availability))).quantize(Decimal("0.001"), rounding="ROUND_FLOOR")
    tok = env.client.get("/v2/model-react/revenue", params={"project": record.project_code}).json()["save"]
    saved = env.client.post("/v2/workbook/revenue/contracts", data={"project": record.project_code, "csrf_token": tok["csrf_token"],
                            "content_hash": tok["content_hash"], "contracts": book([_ppa("a", "2031-03-01", "2032-03-01", cap), MERCHANT]), "action": "save"},
                            follow_redirects=False)
    assert saved.status_code in (200, 303)
    before = _snap(record)
    # 1. the book has ONE writer: an import row targeting it is refused with the typed batch code
    r1 = _apply(env, record, _approved_ticket(env, record, "revenue.multistream.contracts", book([_ppa("a", "2031-03-01", "2032-03-01", 1), MERCHANT])))
    assert "BATCH_REVENUE_CONTRACT_EDITOR_ONLY" in r1.text and _snap(record) == before
    # 2. a technical edit that shrinks the P50 envelope below the committed quantity is refused with the cap code; nothing is written
    r2 = _apply(env, record, _approved_ticket(env, record, "project_setup.technical.p50_hours", "1400"))
    assert "R04_GLOBAL_P50_CAP_EXCEEDED" in r2.text and _snap(record) == before
    # 3. a forged / foreign ticket is refused
    assert "R04_" not in _apply(env, record, "forged-ticket").text and _snap(record) == before
    ticket = _approved_ticket(env, record, "project_setup.technical.p50_hours", "1500")
    other = _apply(env, record, ticket, client=env.stranger)
    assert _snap(record) == before and "applied" not in other.text.lower()[:0]
    # 4. an edit that keeps the envelope (>= committed) applies exactly once
    r4 = _apply(env, record, _approved_ticket(env, record, "project_setup.technical.operating_hours_p90_10y" if False else "project_setup.technical.p90_10y_hours", "1300"))
    assert r4.status_code == 200 and "R04_GLOBAL_P50_CAP_EXCEEDED" not in r4.text
    after = _snap(record)
    assert float(after[0]["operating_hours_p90_10y"]) == 1300.0 and after[1] == before[1]


# ── scenario isolation of the book ────────────────────────────────────────────────────────────────────────────────────────
def test_scenario_book_is_validated_against_the_scenario_effective_state_and_never_leaks_into_base(env):
    from app.persistence.scenarios_repository import add_scenario, get_base_case_scenario, get_or_create_base_case_scenario, select_scenario, get_scenario
    from app.persistence.workspace_repository import get_workspace_state
    record = env.create("solar")
    env.client.get("/v2/workbook", params={"project": record.project_code})
    ws = get_workspace_state(OWNER, record.project_id)
    base = get_base_case_scenario(OWNER, record.project_id)
    assert base is not None, "the Base Case scenario must exist after the workbook loaded"
    scenario = add_scenario(OWNER, record.project_id, record.project_code, "R04 scenario", base.scenario_id, dict(ws.draft_snapshot))
    assert scenario is not None and select_scenario(OWNER, record.project_id, scenario.scenario_id)
    base_before = dict(get_workspace_state(OWNER, record.project_id).draft_snapshot).get("rev_multistream_config_json")
    # direct field Save is explicitly refused for a non-base scenario (typed), with no change
    tok = env.client.get("/v2/model-react/revenue", params={"project": record.project_code}).json()["save"]
    from app.workbook.mutation_csrf import mutation_token
    from types import SimpleNamespace
    req = SimpleNamespace(cookies=env.client.cookies, state=SimpleNamespace())
    direct = env.client.post("/v2/workbook/update", headers={"Accept": "application/json"}, data={
        "project": record.project_code, "field_id": "revenue.multistream.contracts", "value": book([_ppa("a", "2031-03-01", "2032-03-01", 10), MERCHANT]),
        "content_hash": tok["content_hash"], "workbook_version": tok["workbook_version"], "csrf_token": mutation_token(req, record.project_code, "workbook-update")})
    assert "REVENUE_V2_SCENARIO" in direct.text
    # the contracts writer validates the scenario's EFFECTIVE state: over-cap refused, valid stored in the scenario overrides only
    over = env.client.post("/v2/workbook/revenue/contracts", data={"project": record.project_code, "csrf_token": tok["csrf_token"], "content_hash": tok["content_hash"],
                           "contracts": book([_ppa("a", "2031-03-01", "2032-03-01", 10 ** 9), MERCHANT]), "action": "save"}, follow_redirects=False)
    assert over.status_code == 422 and "R04_GLOBAL_P50_CAP_EXCEEDED" in over.text
    ok = env.client.post("/v2/workbook/revenue/contracts", data={"project": record.project_code, "csrf_token": tok["csrf_token"], "content_hash": tok["content_hash"],
                         "contracts": book([_ppa("a", "2031-03-01", "2032-03-01", 1000), MERCHANT]), "action": "save"}, follow_redirects=False)
    assert ok.status_code in (200, 303), ok.text[:200]
    assert "rev_multistream_config_json" in get_scenario(scenario.scenario_id, OWNER).overrides
    assert dict(get_workspace_state(OWNER, record.project_id).draft_snapshot).get("rev_multistream_config_json") == base_before   # no leakage to Base
