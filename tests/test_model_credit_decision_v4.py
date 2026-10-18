"""Standalone V4 committed-credit evidence, missing-data and provenance regression."""
from copy import deepcopy

import pytest

from app.v2.credit_v4_evidence import build_credit_v4


def run(name, dscr=1.2, debt=20.0, dt=("2030-06-30", "2030-12-31"), credit="PASS"):
    keys = {
        "dscr": [dscr, dscr], "debt_service": [debt, debt],
        "base_cfads": [50.0, 45.0], "closing": [90.0, 80.0],
        "bank_cfads": [40.0, 38.0], "dsra_balance": [10.0, 10.0],
        "distribution": [5.0, 8.0],
    }
    return {
        "identity": {"history_id": name, "scenario": "P50", "state": "HISTORICAL", "integrity": credit},
        "timeline": {
            "available": True,
            "columns": [{"index": i + 1, "date": d} for i, d in enumerate(dt)],
            "rows": [{"key": k, "cells": [{"v": v} for v in vals]} for k, vals in keys.items()],
        },
        "capacity": {"min_dscr": {"v": dscr}, "convergence": {"converged": True}},
        "links": {"statements": "/v2/statements"},
    }


def test_converged_solver_with_dscr_below_one_never_approved():
    x = build_credit_v4([run("x", dscr=0.75)])
    assert x["run_risks"][0]["status"] == "REVIEW_REQUIRED"
    assert "OBSERVED_DSCR_BELOW_ONE" in x["run_risks"][0]["reasons"]


def test_clean_observation_is_not_credit_pass():
    x = build_credit_v4([run("x")])
    assert x["run_risks"][0]["status"] == "OBSERVED_ONLY_NO_SHORTFALL_IDENTIFIED"
    assert not x["period_comparison"]["available"]


def test_date_join_does_not_match_by_period_index():
    r = run("a")
    q = run("b", dt=("2030-12-31", "2031-06-30"))
    q["timeline"]["rows"][1]["cells"][0]["v"] = 25.0
    x = build_credit_v4([r, q])["period_comparison"]
    assert x["available"] and x["common_periods"] == 1
    assert x["excluded_dates"] == [1, 1] and x["changed"] >= 1


@pytest.mark.parametrize("dates", [
    ("2030-02-30", "2030-12-31"),
    ("2030-12-31", "2030-12-31"),
    ("2031-12-31", "2030-12-31"),
    (None, "2030-12-31"),
])
def test_bad_or_duplicate_dates_fail_closed(dates):
    x = build_credit_v4([run("a"), run("b", dt=dates)])
    assert not x["period_comparison"]["available"]
    assert x["run_risks"][1]["status"] == "REVIEW_REQUIRED"


def test_missing_debt_or_dscr_is_not_zero():
    r = run("x")
    r["timeline"]["rows"][0]["cells"][0]["v"] = None
    x = build_credit_v4([r])
    assert x["run_risks"][0]["missing_count"] == 1
    y = build_credit_v4([run("base"), r])
    assert y["period_comparison"]["unavailable"] > 0


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), True])
def test_nan_inf_and_boolean_not_numeric(invalid):
    r = run("b")
    r["timeline"]["rows"][0]["cells"][0]["v"] = invalid
    assert build_credit_v4([run("a"), r])["period_comparison"]["unavailable"] > 0


def test_duplicate_ids_rejected():
    with pytest.raises(ValueError, match="CREDIT_V4_RUN_ID_INVALID"):
        build_credit_v4([run("x"), run("x")])


def test_no_contractual_definition_invented():
    x = build_credit_v4([run("a")])
    assert len(x["unavailable"]) >= 4
    assert all("reason" in r for r in x["unavailable"])


def test_projection_pure_and_historical_data_unchanged():
    r = run("a")
    before = deepcopy(r)
    build_credit_v4([r])
    assert r == before


def test_required_period_metric_absence_fails_closed():
    r = run("a")
    r["timeline"]["rows"] = [z for z in r["timeline"]["rows"] if z["key"] != "closing"]
    x = build_credit_v4([r, run("b")])
    assert x["run_risks"][0]["status"] == "REVIEW_REQUIRED"
    assert not x["period_comparison"]["available"]


def test_three_authorised_runs_supported():
    x = build_credit_v4([run("a"), run("b", dscr=0.9), run("c", debt=21)])
    assert x["period_comparison"]["available"]
    assert len(x["run_risks"]) == 3
