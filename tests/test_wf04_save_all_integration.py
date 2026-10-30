"""WF-04 x WS-2: the two contractual DSCR inputs travel through the REAL atomic Save All (``POST /v2/workbook/save-all``) with every other edit.

One transaction, one composite CAS, one commit; the terms keep their exact decimals; a malformed term rolls the whole request back; Save never
runs the model; the Last Run becomes STALE; a historical Run keeps the terms it was committed with and the next Run records the new ones.
"""
import uuid
from types import SimpleNamespace

import pytest

from tests.run_clone_csrf import post_valid_csrf
from tests.test_fin_val_b1_capex_save_integrity import USER, env as grid_env  # noqa: F401  (fixture; the grid router carries Save All)

EOD = "debt.contract.min_dscr_eod"
COV = "debt.contract.contractual_dscr"
URL = "/v2/workbook/save-all"
PURPOSE = "model-save-all-v1"


def _token(env, record, purpose=PURPOSE):
    from app.workbook.financing_csrf import issue_token
    return issue_token(SimpleNamespace(cookies=dict(env.client.cookies.items()), state=SimpleNamespace()), record.project_code, purpose=purpose)


def _identity(record):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get
    ident = assemble_consistent_for_get(USER, record.project_id, WORKBOOK.version)
    return ident.composite_hash, get_workspace_state(USER, record.project_id).active_scenario_id


def _lines(table, project_id):
    from app.persistence import db
    with db.get_cursor() as cur:
        cur.execute(f"SELECT * FROM {table} WHERE project_id=? AND is_active=1 ORDER BY sub_line_id", (project_id,))
        return [dict(r) for r in cur.fetchall()]


def _cost_edits(record, bump=3.0, limit=50):
    """Edits for the active CAPEX then OPEX lines, at most ``limit`` (the Save All bound is 50 lines per request)."""
    out = []
    for kind, table in (("capex", "capex_sub_lines"), ("opex", "opex_sub_lines")):
        for row in _lines(table, record.project_id):
            if len(out) >= limit:
                return out
            out.append({"kind": kind, "sub_line_id": row["sub_line_id"], "label": row["label"],
                        "amount_keur": repr(round(float(row["amount_keur"]) + bump, 6)), "row_version": row["updated_at"]})
    return out


def _state(record):
    from app.persistence import db
    from app.persistence.workspace_repository import get_workspace_state
    ws = get_workspace_state(USER, record.project_id)
    with db.get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM model_run_history WHERE project_id=?", (record.project_id,))
        history = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM save_all_requests WHERE project_id=?", (record.project_id,))
        ledger = cur.fetchone()["n"]
    return {"draft": dict(ws.draft_snapshot), "history": history, "ledger": ledger, "hash": _identity(record)[0],
            "capex": _lines("capex_sub_lines", record.project_id), "opex": _lines("opex_sub_lines", record.project_id),
            "last_run": (ws.last_runtime_snapshot_id, ws.last_runtime_summary)}


def _body(env, record, cells, **over):
    chash, scenario = _identity(record)
    from app.workbook.registry import WORKBOOK
    body = {"project": record.project_code, "csrf_token": _token(env, record), "workbook_version": WORKBOOK.version, "content_hash": chash,
            "scenario_id": scenario, "request_id": "req-" + uuid.uuid4().hex[:16], "cells": cells, "contracts_json": None, "cost_lines": []}
    body.update(over)
    return body


OTHER = [{"field_id": "revenue.ppa.base_tariff", "value": "57"}, {"field_id": "debt.senior.gearing_pct", "value": "70"}]


def _terms(eod="1.05", cov="1.2"):
    return [{"field_id": EOD, "value": eod}, {"field_id": COV, "value": cov}]


def _freshness(record):
    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.v2.router import _build_pis_with_composite_identity
    from app.workbook.runtime_authority import resolve_runtime_freshness
    rec, owner = resolve_accessible_project(USER, record.project_code)
    ws = get_workspace_state(USER, record.project_id)
    return resolve_runtime_freshness(ws, current_composite_hash=_build_pis_with_composite_identity(ws, rec, owner).content_hash).state.value


def _run(env, record):
    from tests.test_model_decision_workspace_v2 import tokens
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    response = post_valid_csrf(env.client, "/v2/workbook/run", headers={"HX-Request": "true"}, data=dict(project=record.project_code, **tokens(page.text)))
    assert response.status_code == 200
    from app.persistence.run_history_repository import get_run_history
    return list(get_run_history(USER, record.project_id))


def _recorded(entry):
    from app.workbook.dscr_contract_terms import read_run_terms
    return read_run_terms(entry.last_runtime_identity)


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_both_terms_commit_with_other_scalars_and_cost_lines_in_one_atomic_save_and_never_run_the_model(grid_env, kind):
    record = grid_env.create(kind)
    before = _state(record)
    cells = [c for c in OTHER if c["field_id"] != "revenue.ppa.base_tariff" or kind in ("solar", "wind")] + _terms("1.05", "1.2")
    body = _body(grid_env, record, cells, cost_lines=_cost_edits(record))
    res = grid_env.client.post(URL, json=body)
    assert res.status_code == 200, res.text[:500]
    out = res.json()
    assert out["ok"] and out["model_executed"] is False and out["replayed"] is False
    assert out["saved"]["cells"] == len(cells) and out["saved"]["cost_lines"] == len(body["cost_lines"])
    after = _state(record)
    assert after["draft"]["dscr_min_eod_x"] == "1.05" and after["draft"]["dscr_contractual_x"] == "1.2"        # exact decimals as entered
    assert after["hash"] != before["hash"] and out["content_hash"] == after["hash"]
    assert after["history"] == before["history"] == 0 and after["last_run"] == before["last_run"]             # Save is not Run
    assert after["ledger"] == 1                                                                                   # one ledger row, not one per section


def test_a_batch_of_at_least_fifty_inputs_with_both_terms_persists_exactly_and_records_one_ledger_row(grid_env):
    record = grid_env.create("wind")
    lines = _cost_edits(record, 1.0, limit=46)
    cells = OTHER + _terms("0.9951", "1.15")
    assert len(cells) + len(lines) >= 50, "fixture too small for the >= 50-input batch"
    body = _body(grid_env, record, cells, cost_lines=lines)
    res = grid_env.client.post(URL, json=body)
    assert res.status_code == 200, res.text[:500]
    after = _state(record)
    assert after["draft"]["dscr_min_eod_x"] == "0.9951" and after["draft"]["dscr_contractual_x"] == "1.15"
    for edit in body["cost_lines"]:
        row = next(r for r in after[edit["kind"]] if r["sub_line_id"] == edit["sub_line_id"])
        assert row["amount_keur"] == pytest.approx(float(edit["amount_keur"]))
    assert after["ledger"] == 1 and after["history"] == 0


@pytest.mark.parametrize("bad", ["abc", "0", "-1", "0.001", "10.5", "nan", "inf", "1,05"])
def test_a_malformed_term_rolls_back_every_section_and_the_ledger(grid_env, bad):
    record = grid_env.create("wind")
    before = _state(record)
    body = _body(grid_env, record, OTHER + _terms("1.05", bad), cost_lines=_cost_edits(record))
    res = grid_env.client.post(URL, json=body)
    assert res.status_code == 422, res.text[:400]
    assert _state(record) == before                       # cells, terms, cost lines, hash, ledger, history: nothing survived


def test_stale_content_hash_is_refused_and_writes_nothing_even_with_valid_terms(grid_env):
    record = grid_env.create("wind")
    before = _state(record)
    res = grid_env.client.post(URL, json=_body(grid_env, record, _terms(), content_hash="0" * 64))
    assert res.status_code == 409 and res.json()["reload"] is True
    assert _state(record) == before


def test_csrf_scope_is_enforced_and_a_term_cannot_be_saved_with_a_foreign_operation_token(grid_env):
    record = grid_env.create("wind")
    before = _state(record)
    for token in ("", "garbage", _token(grid_env, record, purpose="model-mutation-v1:grid-save")):
        res = grid_env.client.post(URL, json=_body(grid_env, record, _terms(), csrf_token=token))
        assert res.status_code == 403 and res.json()["code"] == "CSRF_INVALID"
    assert _state(record) == before


def test_another_user_cannot_save_the_terms_of_a_project_they_do_not_own(grid_env):
    from app.auth import COOKIE_NAME, create_session_token
    from fastapi.testclient import TestClient
    record = grid_env.create("wind")
    before = _state(record)
    stranger = TestClient(grid_env.app, cookies={COOKIE_NAME: create_session_token(user_id="someone-else", username="admin")})
    body = _body(grid_env, record, _terms())
    body["csrf_token"] = _token(SimpleNamespace(client=stranger), record)
    res = stranger.post(URL, json=body)
    assert res.status_code in (403, 404)
    assert _state(record) == before


def test_the_same_request_id_replays_and_a_changed_payload_with_that_id_conflicts(grid_env):
    record = grid_env.create("wind")
    body = _body(grid_env, record, OTHER + _terms("1.05", "1.2"))
    first = grid_env.client.post(URL, json=body)
    assert first.status_code == 200
    committed = _state(record)
    replay = grid_env.client.post(URL, json=body)
    assert replay.status_code == 200 and replay.json()["replayed"] is True and replay.json()["saved"] == first.json()["saved"]
    assert _state(record) == committed and committed["ledger"] == 1                  # no duplicated ledger row, no second write
    changed = dict(body, cells=OTHER + _terms("1.07", "1.2"))
    res = grid_env.client.post(URL, json=changed)
    assert res.status_code == 409 and res.json()["code"] == "SAVE_ALL_REQUEST_ID_REUSED"
    assert _state(record) == committed and committed["draft"]["dscr_min_eod_x"] == "1.05"


def test_blank_clears_a_term_through_save_all_and_is_recorded_as_not_configured_never_zero(grid_env):
    record = grid_env.create("wind")
    assert grid_env.client.post(URL, json=_body(grid_env, record, _terms())).status_code == 200
    assert grid_env.client.post(URL, json=_body(grid_env, record, [{"field_id": EOD, "value": ""}])).status_code == 200
    entries = _run(grid_env, record)
    recorded = _recorded(entries[0])
    assert recorded.eod.status == "NOT_CONFIGURED" and recorded.contractual.value == 1.2


def test_run_after_save_all_records_the_terms_then_a_later_save_all_stales_it_and_the_next_run_gets_a_distinct_identity(grid_env):
    record = grid_env.create("wind")
    assert grid_env.client.post(URL, json=_body(grid_env, record, _terms("1.05", "1.2"))).status_code == 200
    assert _state(record)["history"] == 0
    first = _run(grid_env, record)
    assert len(first) == 1
    t1 = _recorded(first[0])
    assert (t1.eod.value, t1.eod.raw, t1.contractual.value) == (1.05, "1.05", 1.2) and _freshness(record) == "CURRENT"
    assert grid_env.client.post(URL, json=_body(grid_env, record, _terms("1.5", "1.3"))).status_code == 200
    assert _freshness(record) == "STALE"                                      # the saved terms are part of the input identity
    assert _state(record)["history"] == 1                                     # and Save committed no Run
    reread = _recorded(_state_entries(record)[0])
    assert reread.eod.value == 1.05 and reread.contractual.value == 1.2        # the historical Run keeps ITS terms
    second = _run(grid_env, record)
    assert len(second) == 2
    newest, oldest = second[0], second[-1]
    assert newest.history_id != oldest.history_id and _recorded(newest).eod.value == 1.5 and _recorded(newest).contractual.value == 1.3
    assert _recorded(oldest).eod.value == 1.05 and newest.last_runtime_identity != oldest.last_runtime_identity
    assert _freshness(record) == "CURRENT"


def _state_entries(record):
    from app.persistence.run_history_repository import get_run_history
    return list(get_run_history(USER, record.project_id))


def test_save_all_with_the_terms_changes_no_financial_number(grid_env):
    """The terms feed no calculation: every persisted financial blob of a Run is identical with and without them (terms saved through Save All)."""
    a, b = grid_env.create("wind"), grid_env.create("wind")
    plain = _run(grid_env, a)[0]
    assert grid_env.client.post(URL, json=_body(grid_env, b, _terms("1.05", "1.2"))).status_code == 200
    configured = _run(grid_env, b)[0]
    for name in ("runtime_summary", "financial_statements", "debt_schedule", "tax_schedule", "distribution_schedule", "sponsor_schedule"):
        left, right = dict(getattr(plain, name)), dict(getattr(configured, name))
        for volatile in ("binding", "run_binding"):                  # project/snapshot identity differs between two projects
            left.pop(volatile, None), right.pop(volatile, None)
        if name == "runtime_summary":
            for key in ("acquisition_source_candidate_v1", "financing_evidence", "effective_input_evidence"):
                left.pop(key, None), right.pop(key, None)
        assert left == right, name
    assert plain.integrity_evidence["digest"] == configured.integrity_evidence["digest"]
    assert plain.integrity_evidence["senior_debt"] == configured.integrity_evidence["senior_debt"]
