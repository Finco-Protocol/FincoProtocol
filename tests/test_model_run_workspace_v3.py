"""Run Workspace V3 — committed evidence, exact dates, no engine or persistence writes."""
from __future__ import annotations

from unittest import mock

import pytest

from app.v2 import run_workspace_v3_projection as v3
from tests.test_model_decision_support_v1 import (  # noqa: F401
    two_runs, _edit_p50, _history_ids, _run_once,
)


def _side(kpis=None, identity=None, hash_=None, *, freq="6/6"):
    return {
        "runtime_summary": {"operating_frequency": freq, **(kpis or {})},
        "sponsor_schedule": {}, "debt_schedule": {},
        "last_runtime_identity": identity or {},
        "composite_hash": hash_,
    }


def _rows(sections):
    return {row["key"]: row for section in sections for row in section["rows"]}


def test_three_run_variances_use_one_reference_and_reversible_signed_deltas():
    sides = [
        _side({"project_irr": .08, "total_capex_keur": 1000, "min_dscr": 1.3}),
        _side({"project_irr": .085, "total_capex_keur": 1100, "min_dscr": 1.2}),
        _side({"project_irr": .075, "total_capex_keur": 900, "min_dscr": 1.4}),
    ]
    rows = _rows(v3.build_kpi_sections(sides, 0))
    assert rows["project_irr"]["deltas"] == ["—", "+0.50 pp", "-0.50 pp"]
    assert rows["total_capex_keur"]["deltas"] == ["—", "+100", "-100"]
    assert rows["min_dscr"]["deltas"] == ["—", "-0.10x", "+0.10x"]
    reversed_rows = _rows(v3.build_kpi_sections(sides, 2))
    assert reversed_rows["project_irr"]["deltas"] == ["+0.50 pp", "+1.00 pp", "—"]


def test_missing_nonfinite_zero_and_filter_semantics():
    rows = _rows(v3.build_kpi_sections([
        _side({"total_capex_keur": 0, "project_irr": .08}),
        _side({"total_capex_keur": float("nan"), "project_irr": None}),
    ], 0))
    assert rows["total_capex_keur"]["values"] == ["0", "—"]
    assert rows["total_capex_keur"]["deltas"][1] == "—"
    assert rows["project_irr"]["values"][1] == "—"
    unavailable = _rows(v3.build_kpi_sections([
        _side({"total_capex_keur": 0}), _side({"total_capex_keur": 0})
    ], 0, unavailable_only=True))
    assert "total_capex_keur" not in unavailable


def test_committed_lineage_is_factual_and_never_claims_causality():
    a = _side({"total_revenue_keur": 100}, {"capex_rows": [],
                   "opex_rows": [], "scenario_overrides": {}}, "h1")
    b = _side({"total_revenue_keur": 150}, {"capex_rows": [],
                   "opex_rows": [], "scenario_overrides": {}}, "h2")
    result = v3.build_lineage([a, b], 0)[0]
    assert result["status"] == "DIFFERENT_UNEXPLAINED"
    assert result["rows"] == []
    assert "CAUSALITY UNAVAILABLE" in result["causality"]
    a["composite_hash"] = "h2"
    assert v3.build_lineage([a, b], 0)[0]["status"] == "IDENTICAL"
    a["composite_hash"] = None
    assert v3.build_lineage([a, b], 0)[0]["status"] == "UNKNOWN"


def test_released_frequency_default_is_6_6_and_explicit_unknown_fails_closed():
    assert v3._frequency(_side({}, freq="6/6")) == "6/6"
    assert v3._frequency({"runtime_summary": {}, "last_runtime_identity": {}}) == "6/6"
    assert v3._frequency(_side({}, freq="3/3")) == "3/3"
    assert v3._frequency(_side({}, freq="4/4")) == "UNKNOWN"


def _evidence(value=100., *, start="2035-01-01", end="2035-06-30"):
    return {
        "valid": True,
        "by_date": {end: {
            "base_cfads": value, "debt_service": 80., "dscr": 1.25,
            "closing": 300., "dsra_balance": None, "distribution": 0.,
        }},
        "starts": {end: start}, "count": 1, "missing": [],
    }


def test_period_grid_exact_committed_intervals_and_signed_differences(monkeypatch):
    a, b, c = [_side({}) for _ in range(3)]
    evidence = [_evidence(100), _evidence(110), _evidence(90)]
    monkeypatch.setattr(v3, "_period_evidence", lambda side: evidence[[a, b, c].index(side)])
    # Use distinguishable identities for simple pure projections.
    for i, side in enumerate((a, b, c)):
        side["runtime_summary"]["marker"] = i
    monkeypatch.setattr(v3, "_period_evidence",
                        lambda side: evidence[side["runtime_summary"]["marker"]])
    grid = v3.build_period_grid([a, b, c], 0)
    assert grid["available"]
    row = next(r for r in grid["rows"] if r["key"] == "base_cfads")
    assert row["deltas"] == ["—", "+10.00", "-10.00"]
    assert all(r["start"] == "2035-01-01" for r in grid["rows"])
    assert next(r for r in grid["rows"] if r["key"] == "distribution")["values"] == ["0.00"] * 3


def test_period_grid_rejects_incompatible_stubs_and_frequencies(monkeypatch):
    sides = [_side({}), _side({})]
    monkeypatch.setattr(v3, "_period_evidence",
                        lambda side: _evidence(100, start="2035-01-01")
                        if side is sides[0] else _evidence(110, start="2035-02-01"))
    grid = v3.build_period_grid(sides, 0)
    assert not grid["available"] and grid["reason"] == "PERIOD_INTERVALS_NOT_COMPARABLE"
    assert grid["excluded"][0]["reason"] == "PERIOD_INTERVAL_DIFFERS"
    sides[1]["runtime_summary"]["operating_frequency"] = "3/3"
    assert v3.build_period_grid(sides, 0)["reason"] == "PERIOD_FREQUENCY_MISMATCH_OR_UNAVAILABLE"


def test_period_grid_no_start_or_no_matching_date_fails_closed(monkeypatch):
    a, b = _side({}), _side({})
    monkeypatch.setattr(v3, "_period_evidence",
                        lambda side: _evidence(start="2035-01-01" if side is a else None))
    grid = v3.build_period_grid([a, b], 0)
    assert grid["excluded"][0]["reason"] == "PERIOD_START_NOT_COMMITTED"
    monkeypatch.setattr(v3, "_period_evidence",
                        lambda side: _evidence(end="2035-06-30" if side is a else "2035-12-31"))
    assert v3.build_period_grid([a, b], 0)["reason"] == "PERIOD_END_DATES_DO_NOT_MATCH"


def test_real_two_run_get_never_executes_engine_or_modifies_history(two_runs):
    client, cookies, record, ids = two_runs
    route = "/v2/workbook/run-workspace-v3"
    from app.persistence.run_history_repository import get_run_history
    before = [e.to_dict() for e in get_run_history("ds-user", record.project_id)]
    with mock.patch("app.api.project_runner.run_project",
                    side_effect=AssertionError("GET executed engine")), \
         mock.patch("app.services.production_financial_authority.run_clean_production",
                    side_effect=AssertionError("GET executed engine")):
        response = client.get(route, params={"project": record.project_code,
                                              "run": ["last", ids[-1]]}, cookies=cookies)
    assert response.status_code == 200, response.text[:500]
    assert 'data-testid="run-workspace-v3"' in response.text
    assert 'data-testid="rw-financial"' in response.text
    assert "Project IRR" in response.text
    assert [e.to_dict() for e in get_run_history("ds-user", record.project_id)] == before


def test_historical_vs_historical_duplicate_last_snapshot_and_foreign_ids(two_runs):
    client, cookies, record, ids = two_runs
    route = "/v2/workbook/run-workspace-v3"
    response = client.get(route, params={"project": record.project_code,
                                          "run": [ids[0], ids[1]],
                                          "reference": ids[1]}, cookies=cookies)
    assert response.status_code == 200
    assert 'data-testid="rw-compare-submit"' in response.text
    assert "HISTORICAL" in response.text
    duplicate = client.get(route, params={"project": record.project_code,
                                          "run": ["last", ids[0]]}, cookies=cookies)
    assert duplicate.status_code == 422 and "RUN_WORKSPACE_DUPLICATE_SNAPSHOT" in duplicate.text
    invalid = client.get(route, params={"project": record.project_code,
                                        "run": [ids[0], "other-user-run"]}, cookies=cookies)
    assert invalid.status_code == 404


def test_three_actual_committed_runs_and_reference_switch(two_runs):
    client, cookies, record, ids = two_runs
    _edit_p50(client, cookies, record.project_code, 2400)
    assert _run_once(client, cookies, record.project_code).status_code == 200
    ids = _history_ids(client, cookies, record.project_code)
    url = "/v2/workbook/run-workspace-v3"
    response = client.get(url, params={"project": record.project_code,
                     "run": ids, "reference": ids[-1]}, cookies=cookies)
    assert response.status_code == 200, response.text[:500]
    assert response.text.count('class="v3-rw-identity') == 3
    assert "Δ = Selected Run − Reference Run" in response.text
    assert "Run 3" in response.text


def test_authorization_and_readonly_method(two_runs):
    client, cookies, record, ids = two_runs
    url = "/v2/workbook/run-workspace-v3"
    assert client.get(url, params={"project": record.project_code}).status_code == 401
    assert client.post(url, params={"project": record.project_code}, cookies=cookies).status_code == 405
