"""Independent analytical contracts; synthetic projections are not Run acceptance."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services import credit_v5 as v5
from app.run_integrity.evidence import evidence_digest
from tests.test_model_credit_decision_v4 import run as v4_view


def view(name="one", dscr=1.2):
    out = v4_view(name, dscr=dscr)
    out["identity"].update(snapshot_id="snap-" + name, composite_hash="hash-" + name,
                           scenario_id=None, ran_at="2030-01-01", engine_version="same-engine")
    out["structure"] = {"state": "AVAILABLE", "actual_gearing": {"v": .7}, "equity_sources": {"v": 300.},
                        "commitment": {"v": 700.}, "maturity": {"balance_at_maturity": {"v": 0.}},
                        "tenor": {"contractual_maturity_date": {"v": "2030-12-31"}}}
    out["capacity"].update(min_llcr={"v": 1.6}, debt_service_total={"v": 40.},
                           **{k: {"v": value} for k, value in
                              (("dscr_debt_capacity", 800.), ("gearing_debt_capacity", 700.),
                               ("final_commitment", 700.), ("binding_constraint", "GEARING"))})
    return out


def entry(name="one"):
    ev = {"synthetic_unit_test": True}
    ev["digest"] = evidence_digest(ev)
    return SimpleNamespace(history_id=name, user_id="owner", project_id="project", runtime_snapshot_id="snap-" + name,
                           composite_hash="hash-" + name, last_runtime_scenario_id=None, model_v2_binding=None,
                           active_scenario_name="Base", ran_at="2030-01-01", integrity_evidence=ev,
                           runtime_summary={"financing_evidence": {"run_binding": {
                               "snapshot_id": "snap-" + name, "composite_hash": "hash-" + name, "scenario_id": None}}})


def analyze(monkeypatch, views, constraints):
    monkeypatch.setattr(v5, "build_credit_decision", lambda *a, **k: {"runs": views})
    return v5.analyze_runs([entry(v["identity"]["history_id"]) for v in views], constraints,
                           owner_id="owner", project_id="project", project_code="code")


@pytest.mark.parametrize("actual,threshold,state", [(1.4, 1.2, "SATISFIED"), (1.2, 1.2, "AT_LIMIT"),
                                                   (1.1, 1.2, "BREACH"), (0, 1.2, "BREACH")])
def test_independent_decimal_headroom_and_breach_dates(monkeypatch, actual, threshold, state):
    result = analyze(monkeypatch, [view(dscr=actual)], [v5.Constraint("min_dscr", threshold)]).runs[0].constraints[0]
    expected = float(Decimal(str(actual)) - Decimal(str(threshold)))
    assert result.minimum_headroom == expected
    assert result.state == state and result.complete
    assert result.observations[0].relative == expected / threshold
    assert result.worst_period == "2030-06-30"
    assert result.first_breach == ("2030-06-30" if actual < threshold else None)
    assert result.breach_count == (2 if actual < threshold else 0)
    assert result.authority == "HYPOTHETICAL_ANALYST_PROPOSED"


@pytest.mark.parametrize("metric,limit,head", [("max_gearing", .8, .1), ("min_equity_keur", 200., 100.),
                                             ("min_llcr", 1.5, .1), ("max_balloon_keur", 0., 0.)])
def test_metric_basis_and_direction(monkeypatch, metric, limit, head):
    row = analyze(monkeypatch, [view()], [v5.Constraint(metric, limit)]).runs[0].constraints[0]
    assert row.minimum_headroom == head
    if limit == 0:
        assert row.observations[0].relative is None


@pytest.mark.parametrize("bad", [True, "1.2", float("nan"), float("inf"), -1, 0])
def test_invalid_dscr_thresholds_rejected(bad):
    with pytest.raises(ValueError, match="THRESHOLD_INVALID"):
        v5.Constraint("min_dscr", bad)


def test_percentage_fraction_is_not_confused():
    with pytest.raises(ValueError, match="FRACTION"):
        v5.Constraint("max_gearing", 80)


def test_missing_contractual_threshold_not_inferred_from_sizing_target(monkeypatch):
    result = analyze(monkeypatch, [view()], [v5.Constraint("min_dscr")])
    c = result.runs[0].constraints[0]
    assert c.state == "UNAVAILABLE" and c.minimum_headroom is None and c.breach_count is None
    assert "UNAVAILABLE" in result.contractual_policy


def test_zero_service_is_not_a_zero_dscr_breach(monkeypatch):
    v = view(dscr=0)
    v["timeline"]["rows"][1]["cells"] = [{"v": 0.}, {"v": 0.}]
    c = analyze(monkeypatch, [v], [v5.Constraint("min_dscr", 1.2)]).runs[0].constraints[0]
    assert c.state == "NOT_APPLICABLE" and c.breach_count is None


def test_partial_unknown_dscr_does_not_promote_clean_periods_to_pass(monkeypatch):
    v = view()
    v["timeline"]["rows"][0]["cells"][0]["v"] = None
    c = analyze(monkeypatch, [v], [v5.Constraint("min_dscr", 1.)]).runs[0].constraints[0]
    assert c.state == "PARTIAL" and not c.complete
    assert c.observations[0].value is None


@pytest.mark.parametrize("damage", ["order", "length", "gap", "start", "duplicate"])
def test_invalid_interval_identity_blocks_compliance(monkeypatch, damage):
    v = view()
    if damage == "order":
        v["timeline"]["columns"].reverse()
    elif damage == "length":
        v["timeline"]["rows"][0]["cells"].pop()
    elif damage == "gap":
        v["timeline"]["columns"][1]["index"] += 2
    elif damage == "duplicate":
        v["timeline"]["columns"][1]["date"] = v["timeline"]["columns"][0]["date"]
    else:
        v["timeline"]["columns"][1]["start"] = "2020-01-01"
    result = analyze(monkeypatch, [v], [v5.Constraint("min_dscr", 1.2)]).runs[0]
    assert result.constraints[0].state == "DATA_MISMATCH"
    assert not result.comparison_eligible


def test_restrictive_constraints_grouped_only_by_same_metric(monkeypatch):
    constraints = [v5.Constraint("min_dscr", 1.1, "loose"), v5.Constraint("min_dscr", 1.3, "tight"),
                   v5.Constraint("min_equity_keur", 200.)]
    groups = dict(analyze(monkeypatch, [view()], constraints).runs[0].restrictive_groups)
    assert groups == {"min_dscr": ("tight",), "min_equity_keur": ("min_equity_keur",)}


def test_committed_scenario_changes_and_observed_order(monkeypatch):
    out = analyze(monkeypatch, [view("base", 1.4), view("lower-yield", 1.1)], [v5.Constraint("min_dscr", 1.2)])
    delta = out.comparisons[0]
    assert delta.delta_min_dscr == -.3
    assert delta.policy_changes == (("min_dscr", -.3, 2),)
    assert out.observed_dscr_order == ("base", "lower-yield")


@pytest.mark.parametrize("damage", ["engine", "interval", "quarterly", "integrity"])
def test_comparison_does_not_rank_unlike_or_failed_runs(monkeypatch, damage):
    b = view("second")
    if damage == "engine":
        b["identity"]["engine_version"] = "other"
    elif damage == "interval":
        b["timeline"]["columns"][0]["start"] = "2029-01-01"
    elif damage == "quarterly":
        b["operating_frequency"] = "3/3"
    else:
        b["identity"]["integrity"] = "FAIL"
    out = analyze(monkeypatch, [view(), b], [v5.Constraint("min_dscr", 1.2)])
    assert out.comparisons[0].state == "NOT_COMPARABLE" and not out.observed_dscr_order
    if damage == "quarterly":
        assert "RELEASE_CLOSED" in out.runs[1].constraints[0].reason


@pytest.mark.parametrize("damage", ["owner", "project", "snapshot", "hash", "digest", "scenario"])
def test_invalid_run_provenance_rejected_before_projection(monkeypatch, damage):
    e = entry()
    if damage == "owner": e.user_id = "other"
    elif damage == "project": e.project_id = "other"
    elif damage == "snapshot": e.runtime_snapshot_id = "other"
    elif damage == "hash": e.composite_hash = ""
    elif damage == "digest": e.integrity_evidence["digest"] = "forged"
    else: e.last_runtime_scenario_id = "child"
    monkeypatch.setattr(v5, "build_credit_decision", lambda *a, **k: pytest.fail("untrusted projection"))
    with pytest.raises(ValueError):
        v5.analyze_runs([e], [v5.Constraint("min_dscr", 1.2)], owner_id="owner", project_id="project", project_code="code")


def test_results_are_immutable_and_solver_capacity_is_only_persisted(monkeypatch):
    v = view()
    before = deepcopy(v)
    out = analyze(monkeypatch, [v], [v5.Constraint("min_dscr", 1.2), v5.Constraint("resized_debt", 500.)])
    assert v == before
    assert dict(out.runs[0].sizing_evidence)["dscr_debt_capacity"] == 800.
    assert out.runs[0].constraints[1].state == "UNSUPPORTED"
    with pytest.raises(FrozenInstanceError):
        out.runs[0].constraints[0].state = "APPROVED"
    assert replace(out).sizing == "PERSISTED_CAPACITY_ONLY_NO_RESIZING_OR_NEW_SOLVE"
