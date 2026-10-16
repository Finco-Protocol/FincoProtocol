"""Migration reconciliation unit tests: explicit unit rules, comparability gates, P0-B3 delegation."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.model_import.migration_reconcile import (
    METRICS, convert_source_value, match_metric, reconcile_output, reconciliation_summary,
)

RUN = {"history_id": "h" * 32, "runtime_snapshot_id": "20260101T000000+0000", "ran_at": "2026-01-01T00:00:00+00:00",
       "engine_version": "engine-test", "composite_hash": "c" * 64, "active_scenario_id": None,
       "runtime_summary": {"equity_irr": 0.15, "project_irr": 0.1, "min_dscr": 1.25, "avg_dscr": 1.4, "total_capex_keur": 1000.0,
                           "total_revenue_keur": 5000.0, "total_opex_keur": 800.0, "total_ebitda_keur": 4200.0, "senior_debt_keur": 700.0}}
APPLIED = [{"cell": "Inputs!B2", "field_id": "capex.C.grid_connection", "value": "1000"}]


def output(**kw):
    base = {"source": "Summary!B2", "label": "Total CAPEX", "value": "1000", "unit": "kEUR", "metric_key": "total_capex_keur",
            "scenario_key": "COMMON", "formula": True, "leaves": ["Inputs!B2"], "leaves_truncated": False, "dependency_flags": [],
            "workbook_sha256": "a" * 64}
    base.update(kw)
    return base


def run_one(out=None, **kw):
    args = dict(applied_cells={"Inputs!B2"}, applied_fields=APPLIED, run=RUN, run_current=True, applied_values_intact=True,
                scenario_ok=True, slice_key="base_case", attested=True, project_code="P-1")
    args.update(kw)
    return reconcile_output(output=out or output(), **args)


@pytest.mark.parametrize("label,key", [
    ("Equity IRR", "equity_irr"), ("Project IRR (post-tax)", "project_irr"), ("Minimum DSCR", "min_dscr"), ("Avg DSCR", "avg_dscr"),
    ("Total CAPEX", "total_capex_keur"), ("Total revenue", "total_revenue_keur"), ("Senior debt", "senior_debt_keur"),
])
def test_metric_table_is_explicit(label, key):
    assert match_metric(label)["key"] == key


@pytest.mark.parametrize("label", ["IRR", "Return", "DSCR", "Total", "Capex per MW", "Equity", ""])
def test_ambiguous_labels_have_no_counterpart(label):
    assert match_metric(label) is None


def test_every_metric_maps_to_a_distinct_finco_key():
    assert len({m["key"] for m in METRICS}) == len(METRICS)


@pytest.mark.parametrize("key,value,unit,expected", [
    ("total_capex_keur", "1000000", "EUR", "1000"), ("total_capex_keur", "1.5", "MEUR", "1500"), ("total_capex_keur", "7", "kEUR", "7"),
    ("equity_irr", "15", "%", "0.15"), ("equity_irr", "0.15", "fraction", "0.15"), ("min_dscr", "1.3", "x", "1.3"),
])
def test_explicit_unit_conversions(key, value, unit, expected):
    metric = next(m for m in METRICS if m["key"] == key)
    got, why = convert_source_value(metric, value, unit)
    assert why is None and got == Decimal(expected)


@pytest.mark.parametrize("key,value,unit,reason", [
    ("equity_irr", "0.15", None, "SOURCE_UNIT_REQUIRED"), ("total_capex_keur", "5", None, "SOURCE_UNIT_REQUIRED"),
    ("total_capex_keur", "5", "USD", "SOURCE_UNIT_NOT_CONVERTIBLE"), ("equity_irr", "x", "%", "SOURCE_VALUE_NOT_NUMERIC"),
    ("equity_irr", None, "%", "SOURCE_VALUE_MISSING"), ("equity_irr", "NaN", "%", "SOURCE_VALUE_NOT_FINITE"),
    ("equity_irr", True, "%", "SOURCE_VALUE_MISSING"),
])
def test_units_are_never_guessed(key, value, unit, reason):
    metric = next(m for m in METRICS if m["key"] == key)
    assert convert_source_value(metric, value, unit) == (None, reason)


def test_all_gates_hold_matching_value_passes_through_p0b3():
    row = run_one()
    assert row["status"] == "PASS" and row["reasons"] == [] and row["p0b3_schema"] == 1
    c = row["comparison"]
    assert Decimal(c["delta_finco_minus_reference"]) == 0 and Decimal(c["absolute_tolerance"]) == 0
    assert "not a calendar" in row["horizon_note"]


def test_difference_is_the_real_signed_residual_and_tolerance_is_declared():
    row = run_one(output(value="900"))
    assert row["status"] == "FAIL" and row["reasons"] == ["OUTSIDE_APPROVED_TOLERANCE"]
    assert Decimal(row["comparison"]["delta_finco_minus_reference"]) == Decimal("100")          # FINCO - source
    assert Decimal(row["comparison"]["relative_difference"]).quantize(Decimal("0.0001")) == Decimal("0.1000")
    assert run_one(output(value="900"), abs_tolerance="100")["status"] == "PASS"
    assert run_one(output(value="900"), rel_tolerance="0.2")["status"] == "PASS"
    assert run_one(output(value="900"), abs_tolerance="99.99")["status"] == "FAIL"


def test_irr_percent_source_is_converted_before_comparison():
    row = run_one(output(label="Equity IRR", metric_key="equity_irr", value="15", unit="%"))
    assert row["status"] == "PASS" and row["comparison"]["reference_value"] == "0.15"


@pytest.mark.parametrize("override,reason", [
    (dict(attested=False), "CONVENTIONS_NOT_ATTESTED"),
    (dict(run_current=False), "RUN_NOT_CURRENT_FOR_APPLIED_INPUTS"),
    (dict(scenario_ok=False), "RUN_SCENARIO_DIFFERS_FROM_TARGET"),
    (dict(applied_values_intact=False), "WORKING_COPY_CHANGED_AFTER_APPLY"),
    (dict(applied_cells=set()), "SOURCE_OUTPUT_DEPENDS_ON_UNMAPPED_OR_UNAPPLIED_INPUTS"),
])
def test_each_gate_blocks_comparison(override, reason):
    row = run_one(**override)
    assert row["status"] == "NOT_COMPARABLE" and reason in row["reasons"] and row["comparison"] is None


@pytest.mark.parametrize("out,reason", [
    (output(formula=False), "SOURCE_OUTPUT_IS_STATIC_VALUE_NO_DEPENDENCY_EVIDENCE"),
    (output(leaves=[]), "SOURCE_OUTPUT_HAS_NO_INPUT_LEAVES"),
    (output(leaves_truncated=True), "SOURCE_OUTPUT_DEPENDENCY_GRAPH_TRUNCATED"),
    (output(dependency_flags=["DYNAMIC_OR_VOLATILE_FUNCTION"]), "SOURCE_OUTPUT_DEPENDS_ON_DYNAMIC_OR_EXTERNAL_LOGIC"),
    (output(dependency_flags=["EXTERNAL_WORKBOOK_REFERENCE"]), "SOURCE_OUTPUT_DEPENDS_ON_DYNAMIC_OR_EXTERNAL_LOGIC"),
    (output(metric_key=None, label="Mystery KPI"), "NO_FINCO_COUNTERPART_ESTABLISHED"),
    (output(unit=None), "SOURCE_UNIT_REQUIRED"),
    (output(value=None), "SOURCE_VALUE_MISSING"),
    (output(scenario_key="downside"), "SOURCE_OUTPUT_BELONGS_TO_ANOTHER_SCENARIO"),
])
def test_source_side_gates(out, reason):
    row = run_one(out)
    assert row["status"] == "NOT_COMPARABLE" and reason in row["reasons"]


def test_missing_finco_metric_is_not_compared_and_never_zero_filled():
    run = {**RUN, "runtime_summary": {**RUN["runtime_summary"], "total_capex_keur": None}}
    row = run_one(run=run)
    assert row["status"] == "NOT_COMPARABLE" and "FINCO_METRIC_UNAVAILABLE" in row["reasons"]
    run = {**RUN, "runtime_summary": {}}
    assert "FINCO_METRIC_UNAVAILABLE" in run_one(run=run)["reasons"]


def test_summary_keeps_reconciliation_separate_from_mapping():
    rows = [run_one(), run_one(attested=False), run_one(output(value="1"))]
    s = reconciliation_summary(rows)
    assert s["outputs"] == 3 and s["comparable"] == 2 and s["counts"] == {"PASS": 1, "NOT_COMPARABLE": 1, "FAIL": 1}
    assert s["status"] == "COMPARED"
    assert reconciliation_summary([run_one(attested=False)])["status"] == "NOT_COMPARABLE"
    assert reconciliation_summary([])["status"] == "NOT_STARTED"


def test_p0b3_provenance_conflict_would_block_even_equal_numbers(monkeypatch):
    """The framework's own gate stays authoritative: a conventions/identity conflict yields NOT_COMPARABLE there."""
    from tools.numerical_validation import reconcile as framework
    real = framework.compare

    def conflicted(manifest, a, b):
        manifest["finco"]["conventions_sha256"] = "0" * 64
        return real(manifest, a, b)
    monkeypatch.setattr(framework, "compare", conflicted)
    row = run_one()
    assert row["status"] == "NOT_COMPARABLE" and row["reasons"] == ["CONVENTIONS_NOT_ALIGNED"]
