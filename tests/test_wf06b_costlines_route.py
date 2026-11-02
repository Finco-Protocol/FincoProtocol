"""WF-06B: real-HTTP checks of the additive ``projection`` block on /v2/model-react/costlines."""
from __future__ import annotations

import json
import math

import pytest

from tests.model_mutation_csrf import post_valid_mutation
from tests.test_model_react_wf2_projections_v1 import env, costlines, cas  # noqa: F401  (shared real-app fixture)
from app.cost_line_ledger import assert_no_source_provenance


@pytest.mark.parametrize("kind", ["solar", "wind"])
@pytest.mark.parametrize("sheet", ["capex", "opex"])
def test_projection_is_additive_reconciled_and_provenance_free(env, kind, sheet):
    record = env.create(kind)
    payload = costlines(env, record, sheet)
    proj = payload["projection"]
    assert proj is not None and proj["ledger"]["version"] == "WF06B_COST_LEDGER_V1"
    # existing wire fields are untouched and the projection mirrors them exactly (no amount rewritten)
    assert [l["sub_line_id"] for l in proj["lines"]] == [l["sub_line_id"] for l in payload["lines"]]
    assert [l["amount_keur"] for l in proj["lines"]] == [l["amount_keur"] for l in payload["lines"]]
    active_sum = math.fsum(float(l["amount_keur"] or 0) for l in payload["lines"] if l["active"] and not l["category"] in ("C.17", "C.18"))
    assert math.isclose(proj["saved_total_keur"], active_sum, abs_tol=1e-6)
    # P-04: the real serialised response carries no spreadsheet provenance
    assert_no_source_provenance({k: v for k, v in payload.items() if k != "save"})
    blob = json.dumps(payload).lower()
    for token in ("excel_source", "excel source", "source_ref", "workbook_path", "sheet!"):
        assert token not in blob


def test_user_line_changes_group_total_by_exact_delta_and_inactive_is_excluded(env):
    record = env.create("solar")
    before = costlines(env, record, "capex")
    group = next(g["code"] for g in before["line_management"]["eligible_groups"] if g["code"] == "C.02")
    g0 = {g["code"]: g for g in before["projection"]["groups"]}[group]
    add = post_valid_mutation(env.client, "/v2/capex/line/add", data={
        "project": record.project_code, "parent_category_code": group, "label": "WF06B delta", "amount_keur": "125.5", "notes": "", **cas(before)},
        follow_redirects=False)
    assert add.status_code == 303
    after = costlines(env, record, "capex")
    g1 = {g["code"]: g for g in after["projection"]["groups"]}[group]
    assert math.isclose(g1["saved_total_keur"] - g0["saved_total_keur"], 125.5, abs_tol=1e-9)
    line = next(l for l in after["projection"]["lines"] if l["label"] == "WF06B delta")
    assert line["lineage"] == "user" and line["template_line_id"] is None and line["row_kind"] == "editable_run_bound"
    off = post_valid_mutation(env.client, "/v2/capex/line/deactivate", data={
        "project": record.project_code, "sub_line_id": line["sub_line_id"], "row_version": line["row_version"], **cas(after)}, follow_redirects=False)
    assert off.status_code == 303
    mid = costlines(env, record, "capex")
    g2 = {g["code"]: g for g in mid["projection"]["groups"]}[group]
    assert math.isclose(g2["saved_total_keur"], g0["saved_total_keur"], abs_tol=1e-9) and g2["line_count"] == g0["line_count"] + 1


def test_derived_groups_never_count_toward_the_sheet_total(env):
    record = env.create("wind")
    groups = {g["code"]: g for g in costlines(env, record, "capex")["projection"]["groups"]}
    for code in ("C.17", "C.18"):
        assert groups[code]["row_kind"] == "derived_runtime" and groups[code]["saved_total_keur"] is None and not groups[code]["counts_toward_sheet_total"]


def test_other_owner_cannot_read_projection(env):
    record = env.create("solar")
    r = env.stranger.get("/v2/model-react/costlines", params={"sheet": "capex", "project": record.project_code})
    assert r.status_code in (403, 404) and "projection" not in r.text
