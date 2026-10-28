"""RC-UX — typed-unit Goal Seek targets (IRR %, minimum DSCR multiple, NPV kEUR) over the REAL canonical solver.

Proven here: the unit contract (explicit unit, mismatch refused before any model work), parity of the solved tariff and achieved metric with the
Legacy route for the same target on the same runtime, honest typed unavailability (an NPV without a saved valuation policy is never zero and never
solved), preview-only semantics, and that the solved candidate is applied only through the unchanged pinned CAS route.  Synthetic data only.
"""
from __future__ import annotations

import json
import re

import pytest
from bs4 import BeautifulSoup

from tests.test_model_react_rcm_goal_seek_v1 import (  # noqa: F401  (fixtures and helpers)
    BASE, HDR, apply_body, call, env, run_canonical, state, with_sensitivity,
)

TYPED = "solve-typed"
UNITS = {"project_irr": "percent", "pure_equity_irr": "percent", "total_sponsor_irr": "percent",
         "min_dscr": "multiple", "project_npv": "keur", "sponsor_npv": "keur"}


def typed(env, record, metric, value, unit=None, **extra):
    unit = UNITS[metric] if unit is None else unit
    return call(env.client, TYPED, project=record.project_code, target_metric=metric, target_value=value, target_unit=unit, **extra)


# ── the unit contract (no model work) ────────────────────────────────────────────────────────────────────────────

def test_parse_target_converts_only_ratio_metrics_and_requires_the_exact_unit():
    from app.services.goal_seek import GOAL_SEEK_METRICS
    from app.v2.react_goal_seek_targets import parse_target
    irr, dscr, npv = GOAL_SEEK_METRICS["project_irr"], GOAL_SEEK_METRICS["min_dscr"], GOAL_SEEK_METRICS["project_npv"]
    assert parse_target(irr, "8.5", "percent") == (pytest.approx(0.085), "")
    assert parse_target(irr, "8.5%", "percent") == (pytest.approx(0.085), "")
    assert parse_target(dscr, "1.35", "multiple") == (1.35, "")          # NOT divided by 100
    assert parse_target(dscr, "1.35x", "multiple") == (1.35, "")
    assert parse_target(npv, "5,000", "keur") == (5000.0, "")            # NOT divided by 100
    assert parse_target(npv, "-250.5", "keur") == (-250.5, "")           # a negative NPV target is a legitimate request
    for metric, value, unit in ((irr, "8.5", "multiple"), (irr, "8.5", "keur"), (irr, "8.5", ""), (dscr, "1.35", "percent"), (dscr, "1.35", ""),
                                (npv, "5000", "percent"), (npv, "5000", "multiple"), (npv, "5000", "")):
        value_out, reason = parse_target(metric, value, unit)
        assert value_out is None and "named" in reason, (metric.key, unit)
    for metric, unit, value in ((dscr, "multiple", "1.35%"), (npv, "keur", "5%"), (dscr, "multiple", "0"), (dscr, "multiple", "-1"),
                                (irr, "percent", "-100"), (irr, "percent", "abc"), (npv, "keur", "nan"), (npv, "keur", "inf"), (npv, "keur", "")):
        assert parse_target(metric, value, unit)[0] is None, (metric.key, value)


def test_every_canonical_metric_has_a_declared_input_unit():
    from app.services.goal_seek import GOAL_SEEK_METRICS
    from app.v2.react_goal_seek_targets import UNITS as DECLARED, _metrics
    assert set(_metrics()) == set(GOAL_SEEK_METRICS)                      # a future canonical metric with an undeclared unit would drop out, not be mis-scaled
    assert {m.unit for m in GOAL_SEEK_METRICS.values()} <= set(DECLARED)


# ── guards ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_requires_flag_header_session_ownership_and_refuses_protected_references(env, monkeypatch):
    record = env.create()
    params = {"project": record.project_code, "target_metric": "min_dscr", "target_value": "1.3", "target_unit": "multiple"}
    assert env.client.get(f"{BASE}/{TYPED}", params=params).json()["code"] == "REQUEST_HEADER_REQUIRED"
    assert env.anonymous.get(f"{BASE}/{TYPED}", params=params, headers=HDR).status_code == 401
    assert call(env.stranger, TYPED, **params).status_code == 404
    assert call(env.client, "targets", project="nope").status_code == 404
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services.project_library_service import ensure_reference_models
    ensure_reference_models()
    reference = get_reference_by_template_source("generic_wind_reference")
    refused = call(env.client, TYPED, **{**params, "project": reference.project_code})
    assert refused.status_code == 409 and refused.json()["code"] == "PROTECTED_REFERENCE"
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")
    assert call(env.client, TYPED, **params).status_code == 404


def test_the_catalog_declares_every_metric_with_the_unit_the_user_types(env):
    record = env.create()
    body = call(env.client, "targets", project=record.project_code).json()
    declared = {m["key"]: (m["unit"], m["target_unit"], m["input_label"]) for m in body["metrics"]}
    assert declared == {"project_irr": ("ratio", "percent", "Target (%)"), "pure_equity_irr": ("ratio", "percent", "Target (%)"),
                        "total_sponsor_irr": ("ratio", "percent", "Target (%)"), "min_dscr": ("multiple", "multiple", "Target (x)"),
                        "project_npv": ("kEUR", "keur", "Target (kEUR)"), "sponsor_npv": ("kEUR", "keur", "Target (kEUR)")}
    assert body["semantics"] == {"explicit_unit_required": True, "writes_nothing": True}


@pytest.mark.parametrize("metric,wrong", [("project_irr", "multiple"), ("project_irr", "keur"), ("min_dscr", "percent"), ("min_dscr", "keur"),
                                          ("project_npv", "percent"), ("sponsor_npv", "multiple"), ("min_dscr", ""), ("project_npv", "")])
def test_a_missing_or_wrong_unit_is_a_422_before_any_model_work_and_changes_nothing(env, monkeypatch, metric, wrong):
    record = env.create()
    from app.services import goal_seek
    async def never(*_a, **_k):
        raise AssertionError("the solver must not be reached with a unit mismatch")
    monkeypatch.setattr(goal_seek, "solve_tariff_for_metric", never)
    before = state(record)
    response = typed(env, record, metric, "1.3", unit=wrong)
    assert response.status_code == 422 and response.json()["code"] == "UNIT_MISMATCH" and "Nothing was changed" in response.json()["message"]
    assert state(record) == before


@pytest.mark.parametrize("metric,value", [("min_dscr", "1.3%"), ("project_npv", "12%"), ("min_dscr", "0"), ("project_irr", "abc"), ("project_npv", "nan"), ("min_dscr", "")])
def test_malformed_targets_are_typed_422_and_change_nothing(env, metric, value):
    record = env.create()
    before = state(record)
    response = typed(env, record, metric, value)
    assert response.status_code == 422 and response.json()["code"] == "INVALID_REQUEST"
    assert state(record) == before


def test_the_pinned_adapter_still_refuses_non_ratio_targets_so_nothing_is_ever_silently_mis_scaled(env):
    record = env.create()
    response = call(env.client, "solve", project=record.project_code, target_metric="min_dscr", target_value="1.3")
    assert response.status_code == 422 and "Unknown target metric" in response.json()["message"]


# ── real solves: parity with the Legacy route ────────────────────────────────────────────────────────────────────

def legacy(env, record, metric, value):
    response = env.client.post("/v2/workbook/goal-seek/run", data={"project": record.project_code, "target_metric": metric, "target_value": value},
                               headers={"HX-Request": "true"})
    assert response.status_code == 200, response.text[:300]
    return BeautifulSoup(response.text, "html.parser")


def legacy_number(soup, testid):
    return float(re.search(r"-?\d+(?:\.\d+)?", soup.select_one(f"[data-testid='{testid}']").get_text(" ", strip=True).replace(",", "")).group(0))


def test_irr_typed_equals_the_pinned_percent_endpoint_for_the_same_target(with_sensitivity):
    env = with_sensitivity
    record = env.create()
    base = env.client.get("/v2/model-react/analysis/sensitivity/strip", params={"project": record.project_code, "driver": "tariff"},
                          headers=HDR).json()["base"]["values"]["project_irr"]["raw"] * 100
    target = str(round(base + 0.5, 2))
    old = call(env.client, "solve", project=record.project_code, target_metric="project_irr", target_value=target).json()["result"]
    new = typed(env, record, "project_irr", target).json()
    assert new["ok"] and new["preview_only"] and not new["committed"] and not new["is_a_run"]
    for key in ("status", "solved", "solved_input_value", "achieved_metric_value", "model_evaluations", "target_display", "achieved_display", "error_display"):
        assert new["result"][key] == old[key], key
    assert new["result"]["target_unit"] == "percent" and new["apply"] is not None


def test_minimum_dscr_target_is_solved_as_a_multiple_and_equals_the_legacy_route(env):
    record = env.create()
    soup = legacy(env, record, "min_dscr", "1.30")
    legacy_tariff = legacy_number(soup, "gs-solved-value")
    body = typed(env, record, "min_dscr", "1.30").json()
    result = body["result"]
    assert body["ok"] and result["solved"] and result["status"] == "SOLVED", result
    assert round(result["solved_input_value"], 2) == legacy_tariff                     # the same deterministic solve, NOT a /100 target
    assert result["target_value"] == 1.30 and result["target_display"] == "1.30x" and result["target_unit"] == "multiple"
    assert abs(result["achieved_metric_value"] - 1.30) <= 1e-4 and result["achieved_display"].endswith("x") and result["error_display"].endswith("x")
    assert 1.299 < result["achieved_metric_value"] < 1.301 and result["model_evaluations"] <= 40


def test_a_percent_scaled_dscr_would_have_been_a_different_and_wrong_target(env):
    """Guard for the original defect: 1.30 sent as 0.013 (÷100) has a different, unreachable solve — the typed endpoint never does that."""
    record = env.create()
    wrong = call(env.client, "solve", project=record.project_code, target_metric="project_irr", target_value="1.30").json()["result"]   # 1.30 is 1.30 %
    right = typed(env, record, "min_dscr", "1.30").json()["result"]
    assert wrong["target_value"] == pytest.approx(0.013) and right["target_value"] == 1.30


def test_npv_without_a_saved_valuation_policy_is_unavailable_never_zero_and_offers_no_apply(env):
    record = env.create()
    body = typed(env, record, "project_npv", "20000").json()
    assert body["ok"] and body["result"]["solved"] is False and body["result"]["status"] == "TARGET_METRIC_UNAVAILABLE"
    assert body["apply"] is None and body["result"]["solved_input_value"] is None and body["result"]["achieved_metric_value"] is None
    assert "not available" in body["result"]["message"].lower()


def test_npv_with_a_saved_valuation_policy_is_solved_in_keur_and_equals_the_legacy_route(env):
    from tests.fin_v2_3_support import config_json
    from app.workbook.financial_core_config import FIELD_ID
    from app.workbook.registry import WORKBOOK
    from app.workbook.update_service import WorkbookUpdateService
    record = env.create()
    ws = get_ws(record)
    projection = env.client.get("/v2/model-react/fields/project_setup", params={"project": record.project_code}).json()
    WorkbookUpdateService.apply_batch_draft_update(ws=ws, updates=[(FIELD_ID, config_json())], content_hash=projection["save"]["content_hash"],
                                                  workbook_version=WORKBOOK.version, expected_scenario_id=ws.active_scenario_id,
                                                  project_record=record, actor_user_id=record.user_id)
    probe = typed(env, record, "project_npv", "0").json()["result"]                     # NPV is available once the policy is saved
    assert probe["status"] != "TARGET_METRIC_UNAVAILABLE", probe
    assert probe["achieved_metric_value"] is not None
    target = str(round(probe["achieved_metric_value"] + 1500.0, 2))
    body = typed(env, record, "project_npv", target).json()
    result = body["result"]
    assert body["ok"] and result["target_unit"] == "keur" and result["target_value"] == float(target)        # kEUR as typed, never ÷100
    soup = legacy(env, record, "project_npv", target)
    if result["solved"]:
        assert round(result["solved_input_value"], 2) == legacy_number(soup, "gs-solved-value")
        assert abs(result["achieved_metric_value"] - float(target)) <= 1e-4 + 1e-9
        assert result["achieved_display"].endswith("kEUR") and result["target_display"].endswith("kEUR")
    else:                                                                              # whatever the canonical solver says, Legacy says the same
        assert result["status"].replace("_", " ").title() in soup.get_text(" ", strip=True)


def get_ws(record):
    from app.persistence.workspace_repository import get_workspace_state
    return get_workspace_state(record.user_id, record.project_id)


# ── preview only; apply stays the unchanged pinned route ─────────────────────────────────────────────────────────

def test_a_typed_solve_writes_nothing_and_its_candidate_is_applied_only_through_the_pinned_cas_route(env):
    record = env.create()
    run_canonical(env, record.project_code)
    before = state(record)
    body = typed(env, record, "min_dscr", "1.30").json()
    assert body["result"]["solved"] and state(record) == before                         # preview: no draft, no Run, no Last Run change
    binding = body["apply"]
    assert env.client.get("/v2/model-react/workspace", params={"project": record.project_code}).json()["freshness"]["state"] == "CURRENT"
    response = env.client.post(f"{BASE}/apply", json=apply_body(record, binding))
    assert response.status_code == 200 and response.json()["applied"] is True and response.json()["run_state"] == "STALE"
    tampered = typed(env, record, "min_dscr", "1.31").json()["apply"]
    assert env.client.post(f"{BASE}/apply", json=apply_body(record, tampered, value="999")).status_code == 403     # the token binds the exact candidate


def test_a_busy_executor_is_a_429_and_nothing_is_reported_as_solved(env, monkeypatch):
    record = env.create()
    from app.runtime.model_execution import ModelExecutionBusy
    from app.services import goal_seek
    async def busy(*_a, **_k):
        raise ModelExecutionBusy()
    monkeypatch.setattr(goal_seek, "solve_tariff_for_metric", busy)
    response = typed(env, record, "min_dscr", "1.30")
    assert response.status_code == 429 and response.json()["code"] == "MODEL_BUSY" and response.headers["retry-after"] == "5"
