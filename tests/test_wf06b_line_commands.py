"""WF-06B PR-2: the row menu's only commands (deactivate / reactivate, plus add) refuse every unsafe request on the REAL routes and change nothing.

The writers are the existing canonical ones; nothing here adds a route. A refusal must leave the saved lines and the composite CAS identity exactly as they were.
"""
from __future__ import annotations

import pytest

from tests.model_mutation_csrf import post_valid_mutation
from tests.test_model_react_wf2_projections_v1 import env, costlines, cas  # noqa: F401  (shared real-app fixture)

REFUSED = {303, 400, 401, 403, 404, 409, 422}


def _state(env, record, sheet):
    p = costlines(env, record, sheet)
    return p["save"]["content_hash"], [(l["sub_line_id"], l["active"], l["amount_keur"], l["row_version"]) for l in p["lines"]]


def _added(env, record, sheet="capex", label="PR2 line"):
    before = costlines(env, record, sheet)
    group = before["line_management"]["eligible_groups"][0]
    field = before["line_management"]["add"]["group_field"]
    data = {"project": record.project_code, field: group["code"], "label": label, "amount_keur": "12.5", "notes": "", **cas(before)}
    if sheet == "opex":
        data["inflation_pct"] = "0"
    assert post_valid_mutation(env.client, f"/v2/{sheet}/line/add", data=data, follow_redirects=False).status_code == 303
    after = costlines(env, record, sheet)
    return next(l for l in after["lines"] if l["label"] == label), after


@pytest.mark.parametrize("sheet", ["capex", "opex"])
def test_stale_composite_identity_or_row_version_changes_nothing(env, sheet):
    record = env.create("solar")
    line, payload = _added(env, record, sheet)
    state = _state(env, record, sheet)
    for bad in (dict(cas(payload), content_hash="0" * 64), dict(cas(payload), workbook_version="not-the-version")):
        r = post_valid_mutation(env.client, f"/v2/{sheet}/line/deactivate", data={
            "project": record.project_code, "sub_line_id": line["sub_line_id"], "row_version": line["row_version"], **bad}, follow_redirects=False)
        assert r.status_code in REFUSED
        assert _state(env, record, sheet) == state
    r = post_valid_mutation(env.client, f"/v2/{sheet}/line/deactivate", data={
        "project": record.project_code, "sub_line_id": line["sub_line_id"], "row_version": "2000-01-01T00:00:00+00:00", **cas(payload)}, follow_redirects=False)
    assert r.status_code in REFUSED and _state(env, record, sheet) == state


@pytest.mark.parametrize("sheet", ["capex", "opex"])
def test_missing_or_forged_csrf_and_anonymous_requests_are_refused(env, sheet):
    from fastapi.testclient import TestClient

    record = env.create("wind")
    line, payload = _added(env, record, sheet)
    state = _state(env, record, sheet)
    data = {"project": record.project_code, "sub_line_id": line["sub_line_id"], "row_version": line["row_version"], **cas(payload)}
    for token in (None, "forged"):
        body = dict(data, **({} if token is None else {"csrf_token": token}))
        r = env.client.post(f"/v2/{sheet}/line/deactivate", data=body, follow_redirects=False)
        assert r.status_code in (400, 403, 409, 422), (token, r.status_code)
        assert _state(env, record, sheet) == state
    anonymous = TestClient(env.client.app)
    r = anonymous.post(f"/v2/{sheet}/line/deactivate", data=data, follow_redirects=False)
    assert r.status_code in (302, 303, 401, 403) and _state(env, record, sheet) == state


@pytest.mark.parametrize("sheet", ["capex", "opex"])
def test_another_tenant_cannot_retire_reactivate_or_add(env, sheet):
    record = env.create("solar")
    line, payload = _added(env, record, sheet)
    state = _state(env, record, sheet)
    base = {"project": record.project_code, "sub_line_id": line["sub_line_id"], "row_version": line["row_version"], **cas(payload)}
    for op in ("deactivate", "reactivate"):
        r = post_valid_mutation(env.stranger, f"/v2/{sheet}/line/{op}", data=base, follow_redirects=False)
        assert r.status_code in (303, 403, 404), (op, r.status_code)
        assert _state(env, record, sheet) == state
    field = payload["line_management"]["add"]["group_field"]
    r = post_valid_mutation(env.stranger, f"/v2/{sheet}/line/add", data={
        "project": record.project_code, field: payload["line_management"]["eligible_groups"][0]["code"], "label": "intruder", "amount_keur": "1",
        "inflation_pct": "0", "notes": "", **cas(payload)}, follow_redirects=False)
    assert r.status_code in (303, 403, 404) and _state(env, record, sheet) == state
    assert not [l for l in costlines(env, record, sheet)["lines"] if l["label"] == "intruder"]


def test_unknown_line_and_invalid_values_are_refused_without_a_write(env):
    record = env.create("solar")
    line, payload = _added(env, record, "capex")
    state = _state(env, record, "capex")
    r = post_valid_mutation(env.client, "/v2/capex/line/deactivate", data={
        "project": record.project_code, "sub_line_id": "does-not-exist", "row_version": "x", **cas(payload)}, follow_redirects=False)
    assert r.status_code in REFUSED and _state(env, record, "capex") == state
    group = payload["line_management"]["eligible_groups"][0]["code"]
    for amount in ("abc", "1e999x"):      # (the server also accepts a negative or empty amount on add today: the page blocks both; recorded as a gap, not changed here)
        r = post_valid_mutation(env.client, "/v2/capex/line/add", data={
            "project": record.project_code, "parent_category_code": group, "label": "bad amount", "amount_keur": amount, "notes": "", **cas(payload)}, follow_redirects=False)
        assert r.status_code in REFUSED and _state(env, record, "capex") == state, amount
    r = post_valid_mutation(env.client, "/v2/capex/line/add", data={
        "project": record.project_code, "parent_category_code": "C.13", "label": "derived", "amount_keur": "1", "notes": "", **cas(payload)}, follow_redirects=False)
    assert r.status_code == 422 and _state(env, record, "capex") == state


@pytest.mark.parametrize("sheet", ["capex", "opex"])
def test_double_click_is_not_applied_twice_and_reactivate_of_an_active_line_is_refused(env, sheet):
    record = env.create("wind")
    line, payload = _added(env, record, sheet)
    first = post_valid_mutation(env.client, f"/v2/{sheet}/line/deactivate", data={
        "project": record.project_code, "sub_line_id": line["sub_line_id"], "row_version": line["row_version"], **cas(payload)}, follow_redirects=False)
    assert first.status_code == 303
    after_first = _state(env, record, sheet)
    second = post_valid_mutation(env.client, f"/v2/{sheet}/line/deactivate", data={          # the second click carries the same (now stale) tokens
        "project": record.project_code, "sub_line_id": line["sub_line_id"], "row_version": line["row_version"], **cas(payload)}, follow_redirects=False)
    assert second.status_code in REFUSED
    assert _state(env, record, sheet) == after_first, "the repeat changed nothing"
    now = costlines(env, record, sheet)
    row = next(l for l in now["lines"] if l["sub_line_id"] == line["sub_line_id"])
    assert row["active"] is False
    on = post_valid_mutation(env.client, f"/v2/{sheet}/line/reactivate", data={
        "project": record.project_code, "sub_line_id": line["sub_line_id"], "row_version": row["row_version"], **cas(now)}, follow_redirects=False)
    assert on.status_code == 303
    state = _state(env, record, sheet)
    again = post_valid_mutation(env.client, f"/v2/{sheet}/line/reactivate", data={
        "project": record.project_code, "sub_line_id": line["sub_line_id"], "row_version": row["row_version"], **cas(now)}, follow_redirects=False)
    assert again.status_code in REFUSED and _state(env, record, sheet) == state


def test_the_only_row_commands_in_the_page_source_are_deactivate_and_reactivate():
    from pathlib import Path

    grid = Path("frontend/src/app/editing/CostLinesGridView.tsx").read_text(encoding="utf-8")
    manager = Path("frontend/src/app/workflow/CostLineManager.tsx").read_text(encoding="utf-8")
    assert "Deactivate line" in grid and "Reactivate line" in grid
    for forbidden in ("line/reorder", "line/duplicate", "/line/update", "line/delete"):
        assert forbidden not in grid and forbidden not in manager
