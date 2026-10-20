"""Synthetic edge contracts; real committed Runs are tested in the companion module."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.v2.portfolio_projection import ProjectEvidence, build_portfolio, project_row
from tests.test_model_credit_decision_v3 import make_entry


def record(code="proj", **kwargs):
    data = dict(project_code=code, project_id="p", user_id="u", project_name=code,
                project_type="solar", baseline_snapshot={"country_iso": "HR"}, project_stage="development",
                is_protected=False, archived=False)
    data.update(kwargs)
    return SimpleNamespace(**data)


def item(code="proj", **kwargs):
    entry = replace(make_entry(code), project_code=code)
    return ProjectEvidence(record(code, **kwargs), entry, "CURRENT")


def test_compare_metric_authority_zero_and_requested_gearing_not_actual():
    evidence = item()
    evidence.entry.runtime_summary.update(project_irr=0.0, actual_gearing_pct=None, gearing_cap_pct=.95)
    row = project_row(evidence)
    assert row["metrics"]["project_irr"] ["value"] == 0
    assert row["metrics"]["project_irr"]["display"] == "0.00%"
    assert row["metrics"]["min_llcr"]["value"] is None
    assert row["gearing"]["value"] is None
    assert row["money"]["shl"]["value"] == 0


@pytest.mark.parametrize("raw", [None, True, "8.5%", float("inf"), float("nan")])
def test_non_numeric_performance_never_becomes_zero(raw):
    evidence = item()
    evidence.entry.runtime_summary["project_irr"] = raw
    assert project_row(evidence)["metrics"]["project_irr"]["value"] is None


@pytest.mark.parametrize("field,value", [("units", "EUR"), ("units", None), ("currency", "USD"),
                                        ("currency", None), ("authority", "GUESS")])
def test_unproven_currency_units_authority_not_aggregated(field, value):
    evidence = item()
    evidence.entry.runtime_summary["financing_evidence"][field] = value
    view = build_portfolio([evidence])
    assert not view["cohorts"] and view["excluded_count"] == 1
    assert all(c["value"] is None for c in view["rows"][0]["money"].values())


@pytest.mark.parametrize("change", ["snapshot", "scenario", "hash", "subtotal", "missing"])
def test_invalid_finance_binding_or_incomplete_evidence_refuses(change):
    evidence = item()
    finance = evidence.entry.runtime_summary["financing_evidence"]
    if change == "subtotal":
        finance["sources_uses"]["total_sources_keur"] += 50
    elif change == "missing":
        del finance["sources_uses"]["base_project_capex_keur"]
    else:
        finance["run_binding"][{"snapshot": "snapshot_id", "scenario": "scenario_id", "hash": "composite_hash"}[change]] = "foreign"
    assert build_portfolio([evidence])["cohorts"] == []


def test_funding_dates_are_required_and_mixed_dates_remain_separate():
    a, b, c = item("a"), item("b"), item("c")
    b.entry.runtime_summary["financing_evidence"]["construction_funding"]["periods"][0]["period_end"] = "2030-12-31"
    del c.entry.runtime_summary["financing_evidence"]["construction_funding"]["periods"][0]["period_start"]
    view = build_portfolio([a, b, c])
    assert len(view["cohorts"]) == 2 and view["excluded_count"] == 1
    assert [g["totals"]["capex"]["value"] for g in view["cohorts"]] == ["1000.0", "1000.0"]
    assert view["rows"][2]["money"]["capex"]["value"] == 1000


def test_deterministic_aggregation_and_one_run_per_project_no_mutation():
    items = [item("c"), item("a"), item("b", project_type="wind", baseline_snapshot={"country_iso": "DE"})]
    before = deepcopy(items)
    view = build_portfolio(items)
    assert view == build_portfolio(list(reversed(items)))
    assert items == before
    assert view["total"] == 3 and view["cohorts"][0]["totals"]["capex"]["value"] == "3000.0"
    assert view["technology_counts"] == [{"label": "solar", "count": 2, "share": 2 / 3}, {"label": "wind", "count": 1, "share": 1 / 3}]
    assert view["cohorts"][0]["concentration"]["country"][0]["label"] == "DE"


def test_no_run_missing_history_and_integrity_are_distinct_from_freshness():
    missing = ProjectEvidence(record("none"), freshness="NOT_RUN")
    corrupt = ProjectEvidence(record("corrupt"), issue="History unreadable")
    view = build_portfolio([missing, corrupt, item()])
    assert view["total"] == 3 and view["with_run"] == 1
    assert all(row["integrity"] != "PASS" for row in view["rows"])
    assert view["rows"][-1]["freshness"] == "CURRENT"


@pytest.mark.parametrize("field", ["user_id", "project_id", "project_code", "runtime_snapshot_id", "ran_at"])
def test_bad_run_identity_suppresses_financial_values_and_links(field):
    evidence = item()
    entry = replace(evidence.entry, **{field: "foreign" if field != "runtime_snapshot_id" else ""})
    row = project_row(replace(evidence, entry=entry))
    assert row["history_id"] is None and row["run_url"] is None
    assert all(c["value"] is None for c in row["metrics"].values())


def test_filters_and_metric_sort_do_not_treat_missing_as_zero_or_hide_negatives():
    a, b, c = item("a"), item("b", project_type="wind"), item("c")
    a.entry.runtime_summary["project_irr"] = -.1
    b.entry.runtime_summary["project_irr"] = None
    c.entry.runtime_summary.update(project_irr=0, min_dscr=.8)
    assert [r["code"] for r in build_portfolio([a, b, c], sort="project_irr")["rows"]] == ["c", "a", "b"]
    assert build_portfolio([a, b], technology="wind")["total"] == 1
    assert build_portfolio([a, b], country="ZZ")["total"] == 0
    assert build_portfolio([a, b], project="foreign")["total"] == 0
    assert build_portfolio([a, b, c], review="low_dscr")["rows"][0]["code"] == "c"
    assert build_portfolio([a], stage="operating")["total"] == 0


def test_url_encoding_and_no_synthetic_portfolio_credit_or_return():
    evidence = item("p&run=foreign")
    row = project_row(evidence)
    assert "project=p%26run%3Dforeign" in row["credit_url"]
    assert "run=p%26run%3Dforeign" in row["credit_url"]
    view = build_portfolio([evidence])
    assert not {"portfolio_irr", "portfolio_dscr", "covenant_pass", "portfolio_statements"} & view.keys()


def test_protected_reference_has_no_unsupported_credit_drilldown():
    assert project_row(item(is_protected=True))["credit_url"] is None


def test_financial_range_uses_percent_units_and_excludes_missing():
    a, b = item("a"), item("b")
    a.entry.runtime_summary["project_irr"] = .08
    b.entry.runtime_summary["project_irr"] = None
    assert build_portfolio([a, b], sort="project_irr", minimum="8", maximum="8")["total"] == 1
    assert build_portfolio([a], sort="project_irr", minimum="9")["total"] == 0


def test_more_than_five_projects_and_status_filters():
    evidence = [item(str(i)) for i in range(8)]
    evidence[0] = replace(evidence[0], freshness="STALE")
    assert build_portfolio(evidence)["total"] == 8
    assert build_portfolio(evidence, review="stale")["total"] == 1


def test_malformed_schedule_summary_and_missing_evidence_remain_unavailable():
    evidence = item()
    evidence.entry.debt_schedule["summary"] = []
    evidence.entry.sponsor_schedule["summary"] = []
    row = project_row(evidence)
    assert row["metrics"]["min_llcr"]["value"] is None
    assert "Credit evidence incomplete" in row["issues"]


def test_undated_fc_funding_is_not_silently_assigned_a_cod_for_totals():
    evidence = item()
    construction = evidence.entry.runtime_summary["financing_evidence"]["construction_funding"]
    construction["non_construction_fc_use"] = {"uses_keur": 40, "total_sources_keur": 40, "residual_keur": 0}
    view = build_portfolio([evidence])
    assert view["rows"][0]["money"]["senior"]["value"] == 700
    assert view["cohorts"][0]["totals"]["capex"]["value"] == "1000.0"
    assert view["cohorts"][0]["totals"]["senior"]["value"] is None
    assert view["cohorts"][0]["totals"]["senior"]["coverage"] == 0
    assert view["cohorts"][0]["concentration"]["country"][0]["senior"] == "Unavailable"


def test_corrupt_unrepresentable_numbers_fail_closed():
    evidence = item()
    evidence.entry.runtime_summary["project_irr"] = 10 ** 400
    evidence.entry.runtime_summary["financing_evidence"]["sources_uses"]["senior_debt_keur"] = 10 ** 400
    row = project_row(evidence)
    assert row["metrics"]["project_irr"]["value"] is None
    assert row["money"]["senior"]["value"] is None


def test_repository_reads_recheck_ownership_and_exclude_archived(monkeypatch):
    from app.persistence import projects_repository as projects, workspace_repository as workspaces, run_history_repository as history
    from app.v2.portfolio_reads import load_portfolio
    own, foreign, archived = record("own"), record("foreign", user_id="other"), record("archived", archived=True)
    monkeypatch.setattr(projects, "list_projects", lambda owner: [own, foreign, archived])
    monkeypatch.setattr(workspaces, "get_workspace_state", lambda owner, pid: None)
    calls = []
    def read(owner, pid):
        calls.append((owner, pid))
        return None
    monkeypatch.setattr(history, "get_latest_history_entry", read)
    monkeypatch.setattr(projects, "get_project", lambda pid, owner: own)
    assert len(load_portfolio("u")) == 1
    assert calls == [("u", "p"), ("u", "p")]
    monkeypatch.setattr(projects, "get_project", lambda pid, owner: None)
    assert load_portfolio("u") == []


def test_missing_composite_identity_does_not_authorize_financial_subtotals():
    evidence = item()
    evidence = replace(evidence, entry=replace(evidence.entry, composite_hash=None))
    assert build_portfolio([evidence])["cohorts"] == []
