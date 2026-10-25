"""WF-05 Hybrid Inputs grid x WF-07 Revenue V2 contracts: integrated, real-route acceptance.

Both writers share the composite CAS and freshness authority.  The grid never executes the model, never
touches contract authority, and is rejected (controlled, zero mutation) when it would write a legacy price
while explicit contracts own pricing.  Synthetic Working Copies only.
"""
from __future__ import annotations

from tests.run_clone_csrf import post_valid_csrf

import copy
import json

import pytest

from app.auth import generate_csrf_token
from app.workbook.registry import WORKBOOK
from app.workbook.revenue_multistream import SNAPSHOT_KEY
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401  (env is a pytest fixture)
from tests.test_wf07_revenue_multistream import contracts
from tests.test_wf07_revenue_workspace import contract_tokens

OWNER = "decision-user"


@pytest.fixture
def gclient(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    from app.v2.grid_router import router as grid_router
    app = FastAPI()
    app.include_router(grid_router, prefix="/v2")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=OWNER, username="admin"))
        yield client


def _ws(record):
    from app.persistence.workspace_repository import get_workspace_state
    return get_workspace_state(OWNER, record.project_id)


def _hash(record):
    from app.workbook.workbook_identity import assemble_consistent_for_get
    return assemble_consistent_for_get(OWNER, record.project_id, WORKBOOK.version).composite_hash


def _evidence(record):
    from app.persistence.run_history_repository import get_run_history
    ws = _ws(record)
    return (ws.draft_snapshot, ws.saved_snapshot, ws.dirty, ws.active_scenario_id, ws.last_runtime_snapshot_id,
            ws.last_runtime_summary, _hash(record),
            tuple((h.history_id, h.runtime_snapshot_id) for h in get_run_history(OWNER, record.project_id)))


def _grid_save(gclient, record, cells, *, content_hash=None, scenario="__current__"):
    body = {"project": record.project_code, "csrf_token": generate_csrf_token(),
            "workbook_version": WORKBOOK.version,
            "content_hash": content_hash or _hash(record),
            "scenario_id": _ws(record).active_scenario_id if scenario == "__current__" else scenario,
            "cells": [{"field_id": f, "value": v} for f, v in cells]}
    return gclient.post("/v2/workbook/grid/save", json=body)


def _save_contracts(env, record, payload):
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    return env.client.post("/v2/workbook/revenue/contracts", headers={"HX-Request": "true"},
                           data={"project": record.project_code, **contract_tokens(page.text),
                                 "contracts": json.dumps(payload)})


def _run(env, record):
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    response = post_valid_csrf(env.client, "/v2/workbook/run", headers={"HX-Request": "true"},
                               data={"project": record.project_code, **tokens(page.text)})
    assert response.status_code == 200
    assert not _ws(record).dirty
    return copy.deepcopy(_ws(record).last_runtime_summary)


def _contract_payload(env, record, kind, **kw):
    from app.workbook.service import WorkbookService
    pi = WorkbookService.build_draft_input_set_from_workspace(_ws(record)).to_projectinputs()
    return contracts(pi, kind, price=95, merchant_price=90, strike=100, **kw)


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_current_stale_current_lifecycle_across_contract_save_run_and_grid_save(env, gclient, kind):
    record = env.create(kind)
    payload = _contract_payload(env, record, kind)
    assert _save_contracts(env, record, payload).status_code == 200
    assert json.loads(_ws(record).draft_snapshot[SNAPSHOT_KEY]) == payload
    assert _ws(record).dirty                                   # contract Save never runs the model
    first_run = _run(env, record)
    assert first_run["revenue_multistream_audit"]
    run_evidence = _evidence(record)

    # Grid Save of an unrelated field: ONE atomic write, no Run, contracts untouched, Last Run immutable
    res = _grid_save(gclient, record, [("project_setup.technical.p50_hours", "1555")])
    assert res.status_code == 200, res.text
    assert res.json()["run_state"] == "STALE" and res.json()["model_executed"] is False
    after = _evidence(record)
    assert json.loads(_ws(record).draft_snapshot[SNAPSHOT_KEY]) == payload
    assert after[4] == run_evidence[4] and after[5] == run_evidence[5] and after[7] == run_evidence[7]
    assert after[2] is True

    second_run = _run(env, record)                              # explicit, canonical Run -> CURRENT again
    assert second_run["revenue_multistream_audit"] and not _ws(record).dirty
    assert _ws(record).last_runtime_snapshot_id != run_evidence[4]


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_grid_cannot_write_a_legacy_price_while_contracts_own_pricing(env, gclient, kind):
    record = env.create(kind)
    assert _save_contracts(env, record, _contract_payload(env, record, kind)).status_code == 200
    before = _evidence(record)
    res = _grid_save(gclient, record, [("project_setup.technical.p50_hours", "1500"),
                                       ("revenue.ppa.base_tariff", "123")])
    assert res.status_code in (409, 422), res.text            # controlled, never a 500
    assert res.json()["ok"] is False
    assert _evidence(record) == before                          # no partial batch, same CAS hash


def test_contract_and_grid_saves_share_the_composite_cas(env, gclient):
    record = env.create("solar")
    stale = _hash(record)
    assert _save_contracts(env, record, _contract_payload(env, record, "solar")).status_code == 200
    assert _hash(record) != stale
    before = _evidence(record)
    res = _grid_save(gclient, record, [("project_setup.technical.p50_hours", "1600")], content_hash=stale)
    assert res.status_code == 409 and res.json()["reload"] is True     # the contract write moved the identity
    assert _evidence(record) == before
    assert _grid_save(gclient, record, [("project_setup.technical.p50_hours", "1600")]).status_code == 200
    # and the reverse: a contract write built on the pre-grid-save identity is refused as stale
    page_hash = _hash(record)
    assert _grid_save(gclient, record, [("project_setup.technical.p50_hours", "1700")]).status_code == 200
    before_contested = _evidence(record)
    contested = env.client.post("/v2/workbook/revenue/contracts", headers={"HX-Request": "true"},
                                data={"project": record.project_code, "content_hash": page_hash,
                                      "workbook_version": WORKBOOK.version, "csrf_token": generate_csrf_token(),
                                      "contracts": json.dumps(_contract_payload(env, record, "solar", ))})
    assert contested.status_code == 409
    assert _evidence(record) == before_contested


def test_contract_field_is_not_writable_through_the_c0_batch_writer(env):
    from app.workbook.update_service import BatchApplyError, WorkbookUpdateService
    record = env.create("solar")
    before = _evidence(record)
    ws = _ws(record)
    with pytest.raises(BatchApplyError, match="BATCH_REVENUE_CONTRACT_EDITOR_ONLY"):
        WorkbookUpdateService.apply_batch_draft_update(
            ws=ws, updates=[("revenue.multistream.contracts", json.dumps(_contract_payload(env, record, "solar")))],
            content_hash=_hash(record), workbook_version=WORKBOOK.version,
            expected_scenario_id=ws.active_scenario_id, project_record=record, actor_user_id=OWNER)
    assert _evidence(record) == before


def test_scenario_contract_authority_does_not_leak_through_grid_saves(env, gclient):
    from app.persistence.scenarios_repository import get_scenario, list_scenarios
    record = env.create("solar")
    payload = _contract_payload(env, record, "solar")
    assert _save_contracts(env, record, payload).status_code == 200
    created = env.client.post("/v2/workbook/scenarios/create",
                              data={"project": record.project_code, "scenario_name": "Alt contracts"})
    assert created.status_code == 200
    sc = next(s for s in list_scenarios(OWNER, record.project_id) if not s.is_base_case)
    assert env.client.post("/v2/workbook/scenarios/select",
                           data={"project": record.project_code, "scenario_id": sc.scenario_id}).status_code == 200
    different = copy.deepcopy(payload)
    different["streams"][0]["price_eur_mwh"] = 105
    assert _save_contracts(env, record, different).status_code == 200
    base_before = copy.deepcopy(_ws(record).draft_snapshot[SNAPSHOT_KEY])
    scenario_before = get_scenario(sc.scenario_id, OWNER).overrides[SNAPSHOT_KEY]
    # a stale scenario selection is rejected without any write
    snapshot = _evidence(record)
    assert _grid_save(gclient, record, [("project_setup.technical.p50_hours", "1500")],
                      scenario="not-the-selected-scenario").status_code in (409, 422)
    assert _evidence(record) == snapshot
    # the grid write does not alter base or scenario contract authority
    res = _grid_save(gclient, record, [("project_setup.technical.p50_hours", "1500")])
    assert res.status_code == 200, res.text
    assert _ws(record).draft_snapshot[SNAPSHOT_KEY] == base_before
    assert get_scenario(sc.scenario_id, OWNER).overrides[SNAPSHOT_KEY] == scenario_before


def test_grid_projection_never_offers_contract_or_stream_fields_as_cells(env):
    from app.v2 import router as R
    record = env.create("solar")
    assert _save_contracts(env, record, _contract_payload(env, record, "solar")).status_code == 200
    ws = _ws(record)
    pis = R._build_pis_with_composite_identity(ws, record, OWNER)
    grid = R._build_input_grid_ctx(record, pis, ws, OWNER, project_editable=True)["input_grid"]
    editable = [r.field_id for s in grid.sections for c in s.categories for r in c.rows if r.editable]
    assert "revenue.multistream.contracts" not in editable
    assert not any("multistream" in f for f in editable)
    # a read-only value is never a raw JSON book or an unbounded string (it widened the grid on phones)
    assert all(len(r.value) <= 40 and "{" not in r.value for sec in grid.sections for c in sec.categories for r in c.rows)
