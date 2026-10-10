"""Q3 — Model Quality x FINCO Insight, covenant intelligence and scenario intelligence (server contracts).

Real canonical Runs (Solar, Wind, Data Center, EV Charging) come from the production ``run_project`` path.
Synthetic corruption exists only to prove detection.  The adapters under test never execute the engine,
never write, and never invent a threshold.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import test_model_quality_q1 as q1                      # same directory: real Run fixtures and helpers
from app.model_quality import CheckStatus, evaluate_model_quality
from app.model_quality.evidence import ProjectTerms, evidence_from_workspace, terms_from_project_inputs
from app.model_quality.registry import REGISTRY
from app.v2 import insight_quality_projection as iq
from app.v2.insight_quality_projection import (
    CONTRACTUAL_THRESHOLD_UNAVAILABLE, TAB_LABELS, build_quality_insight, build_quality_insight_safe)
from app.v2.insight_scenario_projection import build_scenario_insight, build_scenario_insight_safe

REPO = Path(__file__).resolve().parents[1]
runs = q1.runs  # module-scoped fixture re-exported for this module


def fake_ws(payload, **over):
    base = dict(
        last_runtime_summary=q1.persisted_summary(payload),
        last_integrity_evidence=copy.deepcopy(payload["integrity_evidence"]),
        last_sponsor_schedule=copy.deepcopy(payload["sponsor_schedule"]),
        last_debt_schedule={}, last_runtime_snapshot_id=q1.SNAP, last_runtime_composite_hash=q1.HASH,
        last_runtime_identity={"engine_version": "clean_senior_debt_v0"}, last_runtime_at=None,
        last_runtime_scenario_id=None, active_scenario_id=None, active_scenario_name="Base Case",
    )
    base.update(over)
    return SimpleNamespace(**base)


def view(ws, pi, state="CURRENT", **kw):
    return build_quality_insight(ws, run_state=state, project_inputs=pi, active_scenario_id=None,
                                 scenario_name="Base Case", **kw)


def all_rows(q):
    return [r for g in q["groups"].values() for r in g]


# ───────────────────────── Q1 registry -> Insight consistency ─────────────────────────

@pytest.mark.parametrize("key", ["solar", "wind", "data_center", "ev_charging"])
def test_insight_is_exactly_the_q1_report_for_every_vertical(runs, key):
    pi, payload = runs[key]
    ws = fake_ws(payload)
    q = view(ws, pi)
    terms = terms_from_project_inputs(pi)
    report = evaluate_model_quality(evidence_from_workspace(ws, freshness="CURRENT", terms=terms,
                                                            active_scenario_id=None, scenario_known=True))
    rows = {r["check_id"]: r for r in all_rows(q)}
    assert sorted(rows) == sorted(d.check_id for d in REGISTRY) and len(rows) == 30      # one registry, no copy
    for c in report.checks:                               # identical id, status, severity, category, class
        r = rows[c.check_id]
        assert (r["status"], r["severity"], r["category"], r["check_class"]) == (
            c.status.value, c.severity.value, c.category.value, c.check_class.value)
        assert r["threshold_authority"] == c.threshold_authority and r["evidence_source"] == c.evidence_source
    s = report.summary
    assert q["score"]["score"] == s.score and q["score"]["score_status"] == s.score_status   # no re-scoring
    assert q["score"]["counts"]["fail"] == s.failed and q["score"]["counts"]["unavailable"] == s.unavailable
    assert q["score"]["coverage_weighted_pct"] == round(s.coverage_weighted * 100, 1)
    assert q["groups"]["blocking"] == [r for r in q["groups"]["blocking"] if r["blocking"]]


def test_unavailable_evidence_is_never_pass_and_is_listed_as_a_gap(runs):
    pi, payload = runs["solar"]
    q = view(fake_ws(payload), pi)
    assert q["groups"]["gaps"], "the fixture Run lacks some evidence"
    assert all(r["status"] == "UNAVAILABLE" and r["reason_code"] for r in q["groups"]["gaps"])
    assert not any(r["status"] == "UNAVAILABLE" for r in q["groups"]["passed"])


def test_evidence_coverage_is_reported_separately_from_findings(runs):
    pi, payload = runs["solar"]
    q = view(fake_ws(payload), pi)
    html = _render(q)
    assert 'data-testid="q3-coverage"' in html and 'data-testid="q3-counts"' in html
    assert "separate from findings" in html


def test_every_check_navigation_target_is_a_real_workbook_tab():
    ids = set(re.findall(r'id="(tab-[a-z-]+)"', (REPO / "app/templates/v2/workbook.html").read_text()))
    assert set(TAB_LABELS) <= ids
    assert {d.navigation for d in REGISTRY} <= set(TAB_LABELS), "a Q1 target without a validated tab link"


def test_explore_links_exist_only_for_proven_register_paths_and_kpis(runs):
    pi, payload = runs["solar"]
    q = view(fake_ws(payload), pi, register_paths=["financing.target_dscr"], kpi_keys=["min_dscr"])
    values = {e["value"] for r in all_rows(q) for e in r["explore"]}
    assert values == {"f:financing.target_dscr", "k:min_dscr"}
    row = next(r for r in all_rows(q) if r["check_id"] == "QM-SD-004")
    assert row["unlinked_assumptions"] == []
    q2 = view(fake_ws(payload), pi)
    assert not any(r["explore"] for r in all_rows(q2)), "no register/KPI supplied => no guessed link"


# ───────────────────────────── freshness / NOT_RUN / STALE ─────────────────────────────

def test_not_run_has_no_checks_score_or_values(runs):
    pi, payload = runs["solar"]
    ws = fake_ws(payload, last_runtime_summary={}, last_integrity_evidence={}, last_runtime_snapshot_id=None)
    q = view(ws, pi, state="NOT_RUN")
    assert q["state"] == "NOT_RUN" and not q["available"] and "groups" not in q and "score" not in q


def test_stale_describes_the_prior_run_and_binds_no_threshold(runs):
    pi, payload = runs["solar"]
    q = view(fake_ws(payload), pi, state="STALE")
    assert q["state"] == "STALE" and q["terms_bound"] is False
    assert "PRIOR" in q["context_note"] and "not bound" in q["context_note"]
    by_type = {c["type"]: c for c in q["covenants"]}
    lock = by_type["Distribution lock-up DSCR"]
    assert lock["threshold"] == CONTRACTUAL_THRESHOLD_UNAVAILABLE and lock["status"] == "UNAVAILABLE"
    assert lock["reason"].startswith("RUN_THRESHOLD_NOT_BOUND")
    assert lock["freshness"].startswith("STALE") and "prior Last Run" in lock["freshness"]


# ───────────────────────────────── covenant intelligence ─────────────────────────────────

def test_current_run_compares_only_the_project_input_threshold_and_labels_it(runs):
    pi, payload = runs["solar"]
    q = view(fake_ws(payload), pi)
    by_type = {c["type"]: c for c in q["covenants"]}
    lock = by_type["Distribution lock-up DSCR"]
    assert lock["threshold"].endswith("x") and "not verified as a contractual term" in lock["threshold_authority"]
    assert lock["headroom"] and lock["headroom"].startswith(("+", "-"))
    assert lock["status"] in ("PASS", "WARNING")
    mindscr = by_type["Minimum DSCR covenant"]       # no authority anywhere in ProjectInputs
    assert mindscr["threshold"] == CONTRACTUAL_THRESHOLD_UNAVAILABLE and mindscr["headroom"] is None
    assert mindscr["status"] == "UNAVAILABLE"
    default = by_type["Default DSCR"]
    assert default["threshold"] == CONTRACTUAL_THRESHOLD_UNAVAILABLE and default["reason"].startswith("NO_MODEL_AUTHORITY")


@pytest.mark.parametrize("covenant, expected", [(1.05, "PASS"), (5.0, "FAIL")])
def test_genuine_contractual_threshold_comparison(runs, covenant, expected):
    pi, payload = runs["solar"]
    terms = ProjectTerms(min_dscr_covenant=covenant, contractual=True, provenance={"min_dscr_covenant": "facility agreement cl. 22"})
    q = view(fake_ws(payload), pi, terms_override=terms)
    cv = next(c for c in q["covenants"] if c["type"] == "Minimum DSCR covenant")
    assert cv["status"] == expected
    assert cv["threshold"] == f"{covenant:.3f}x" and cv["threshold_authority"].startswith("Supplied contractual term")
    observed = float(cv["observed"].rstrip("x"))
    assert cv["headroom"] == f"{observed - covenant:+.3f}x" or abs(float(cv["headroom"].rstrip("x")) - (observed - covenant)) < 6e-4
    assert "lowest in period #" in cv["testing_period"]


def test_lockup_trigger_is_a_warning_not_a_default(runs):
    pi, payload = runs["solar"]
    terms = ProjectTerms(lockup_dscr=9.0, provenance={"lockup_dscr": "financing.lockup_dscr"})
    q = view(fake_ws(payload), pi, terms_override=terms)
    lock = next(c for c in q["covenants"] if c["type"] == "Distribution lock-up DSCR")
    assert lock["status"] == "WARNING" and lock["blocking"] is False
    assert all(c["status"] != "FAIL" for c in q["covenants"] if c["type"] == "Distribution lock-up DSCR")


# ───────────────────────────────── scoring policy ─────────────────────────────────

def test_score_is_unpublished_below_the_80_percent_coverage_policy(runs):
    pi, payload = runs["solar"]
    ws = fake_ws(payload, last_integrity_evidence={}, last_sponsor_schedule={}, last_runtime_composite_hash=None)
    q = view(ws, pi)
    sc = q["score"]
    assert sc["score_status"] == "UNAVAILABLE_INSUFFICIENT_EVIDENCE" and sc["score"] is None
    assert sc["score_display"] is None and "below the 80% minimum" in sc["score_note"]
    assert "NOT SCORED" in _render(q)


def test_known_integrity_failure_is_blocking_and_first(runs):
    pi, payload = runs["solar"]
    ws = fake_ws(payload)
    bs = ws.last_integrity_evidence["balance_sheet"]
    from app.run_integrity.checks import _BS_KEYS
    row = next(r for r in bs if all(isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool) for k in _BS_KEYS))
    row["retained_earnings"] += 1000.0
    q1.redigest(ws.last_integrity_evidence)
    q = view(ws, pi)
    ids = [r["check_id"] for r in q["groups"]["blocking"]]
    assert "QM-ACC-001" in ids
    assert q["score"]["blocked"] and (q["score"]["score"] is None or q["score"]["score"] <= 50.0)
    html = _render(q)
    assert html.index('data-q3-group="blocking"') < html.index('data-q3-group="issues"') < html.index('data-q3-group="gaps"')


def test_adapter_fails_closed_without_inventing_a_verdict():
    ws = SimpleNamespace(last_runtime_summary={"x": 1})
    q = build_quality_insight_safe(ws, run_state="CURRENT", project_inputs=object())
    assert q["available"] is False and q["state"] == "UNAVAILABLE" and "score" not in q


# ───────────────────────────────── scenario intelligence ─────────────────────────────────

def _entry(payload, sid, snap, when, scale=1.0):
    summary = q1.persisted_summary(payload, snap=snap, scenario=sid)
    summary["project_irr"] = (summary.get("project_irr") or 0.0) * scale
    return SimpleNamespace(
        history_id=f"h-{snap}", runtime_snapshot_id=snap, ran_at=when, engine_version="clean_senior_debt_v0",
        last_runtime_scenario_id=sid, composite_hash="cd" * 32, last_runtime_identity={"engine_version": "clean_senior_debt_v0"},
        runtime_summary=summary, debt_schedule={}, sponsor_schedule=copy.deepcopy(payload["sponsor_schedule"]),
        integrity_evidence=copy.deepcopy(payload["integrity_evidence"]))


def _latest(history, scenarios):
    """Reference rule for unit tests: newest entry per scenario (None => proven never run)."""
    out = {sc.scenario_id: None for sc in scenarios}
    base = {sc.scenario_id for sc in scenarios if sc.is_base_case}
    for e in history:                                   # newest first
        targets = base if e.last_runtime_scenario_id is None else {e.last_runtime_scenario_id}
        for t in targets & set(out):
            out[t] = out[t] or e
    return out


def _sc(sid, name, base=False):
    return SimpleNamespace(scenario_id=sid, scenario_name=name, is_base_case=base)


def test_scenarios_use_each_scenarios_own_committed_run_and_label_freshness(runs):
    pi, payload = runs["solar"]
    scenarios = [_sc("sc-base", "Base Case", True), _sc("sc-up", "Upside"), _sc("sc-none", "Never run")]
    history = [_entry(payload, "sc-up", "20261010T120000", "2026-10-10T12:00:00", 1.1),
               _entry(payload, "sc-up", "20261009T120000", "2026-10-09T12:00:00", 0.5),     # older: ignored
               _entry(payload, None, "20261008T120000", "2026-10-08T12:00:00")]            # pre-scenario Base Run
    v = build_scenario_insight(scenarios=scenarios, latest_runs=_latest(history, scenarios), active_scenario_id="sc-base",
                               active_run_state="CURRENT", last_run_snapshot_id="20261008T120000")
    rows = {r["scenario_id"]: r for r in v["rows"]}
    assert rows["sc-base"]["basis"] == "CURRENT" and rows["sc-base"]["is_active"]
    assert rows["sc-base"]["run"]["snapshot_id"] == "20261008T120000"
    assert rows["sc-up"]["basis"] == "HISTORICAL_RUN" and rows["sc-up"]["run"]["snapshot_id"] == "20261010T120000"
    assert rows["sc-none"]["basis"] == "NO_RUN" and rows["sc-none"]["quality"] is None
    assert "not bound" in rows["sc-up"]["covenant_note"]
    (cmp_,) = v["comparisons"]                                  # only scenarios WITH a Run are comparable
    assert cmp_["scenario_id"] == "sc-up"
    irr = next(r for r in cmp_["rows"] if r["key"] == "project_irr")
    assert irr["active"] != irr["other"] and irr["delta"].endswith("pp")


def test_active_stale_scenario_is_labelled_prior_run_and_banner_shown(runs):
    pi, payload = runs["solar"]
    scenarios = [_sc("sc-base", "Base Case", True), _sc("sc-up", "Upside")]
    history = [_entry(payload, "sc-up", "S2", "2026-10-10T12:00:00"), _entry(payload, None, "S1", "2026-10-08T12:00:00")]
    v = build_scenario_insight(scenarios=scenarios, latest_runs=_latest(history, scenarios), active_scenario_id=None,
                               active_run_state="STALE", last_run_snapshot_id="S1")
    base = next(r for r in v["rows"] if r["is_base"])
    assert base["is_active"] and base["basis"] == "STALE" and "PRIOR Run" in base["basis_note"]
    assert "PRIOR Run" in v["banner"]


def test_missing_comparative_evidence_is_explicit(runs):
    pi, payload = runs["solar"]
    scs = [_sc("sc-base", "Base Case", True), _sc("sc-x", "Other")]
    v = build_scenario_insight(scenarios=scs,
                               latest_runs=_latest([_entry(payload, None, "S1", "2026-10-08T12:00:00")], scs),
                               active_scenario_id="sc-base", active_run_state="CURRENT", last_run_snapshot_id="S1")
    assert v["comparisons"] == []
    html = _render_scn(v)
    assert "q3-compare-unavailable" in html and "nothing is estimated" in html


def test_missing_metric_in_a_run_stays_a_dash_not_zero(runs):
    pi, payload = runs["solar"]
    other = _entry(payload, "sc-up", "S2", "2026-10-10T12:00:00")
    other.runtime_summary = {k: v for k, v in other.runtime_summary.items() if k != "avg_dscr"}
    scs = [_sc("sc-base", "Base Case", True), _sc("sc-up", "Upside")]
    v = build_scenario_insight(scenarios=scs,
                               latest_runs=_latest([other, _entry(payload, None, "S1", "2026-10-08T12:00:00")], scs),
                               active_scenario_id="sc-base", active_run_state="CURRENT", last_run_snapshot_id="S1")
    row = next(r for r in v["comparisons"][0]["rows"] if r["key"] == "avg_dscr")
    assert row["other"] == "—" and row["delta"] == "—"


def test_active_quality_row_is_the_findings_report_not_a_second_score(runs):
    pi, payload = runs["solar"]
    ws = fake_ws(payload)
    q = view(ws, pi)
    from app.v2.router import _quality_row_from_block
    scenarios = [_sc("sc-base", "Base Case", True)]
    v = build_scenario_insight(scenarios=scenarios, latest_runs=_latest([_entry(payload, None, q1.SNAP, "2026-10-08T12:00:00")], scenarios),
                               active_scenario_id=None, active_run_state="CURRENT", last_run_snapshot_id=q1.SNAP,
                               active_quality=_quality_row_from_block(q))
    assert v["rows"][0]["quality"]["score"] == q["score"]["score"]
    assert v["rows"][0]["quality"]["coverage_weighted_pct"] == q["score"]["coverage_weighted_pct"]


def test_scenario_adapter_fails_closed():
    v = build_scenario_insight_safe(scenarios=[object()], latest_runs={}, active_scenario_id=None,
                                    active_run_state="CURRENT", last_run_snapshot_id=None)
    assert v["available"] is False and v["rows"] == []


# ───────────────────────────── no engine execution, no writes ─────────────────────────────

def test_adapters_never_import_or_call_the_engine_or_write(runs, monkeypatch):
    import app.api.project_runner as runner
    monkeypatch.setattr(runner, "run_project", lambda *a, **k: pytest.fail("engine executed"))
    pi, payload = runs["solar"]
    ws = fake_ws(payload)
    before = copy.deepcopy(ws.__dict__)
    view(ws, pi)
    build_scenario_insight(scenarios=[_sc("a", "A", True)], latest_runs={}, active_scenario_id="a",
                           active_run_state="NOT_RUN", last_run_snapshot_id=None)
    assert ws.__dict__ == before, "the adapter must not mutate the persisted record"
    for module in (iq, __import__("app.v2.insight_scenario_projection", fromlist=["x"])):
        text = Path(module.__file__).read_text()
        assert not re.search(r"\b(INSERT|UPDATE|DELETE)\b\s", text) and "commit(" not in text


# ───────────────────────────── rendering helpers ─────────────────────────────

def _env():
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    return Environment(loader=FileSystemLoader(str(REPO / "app/templates/v2")), autoescape=select_autoescape(["html"]))


def _render(quality):
    return _env().get_template("partials/_model_insight_q3.html").render(
        {"smart_panel": SimpleNamespace(insight={"quality": quality, "scenarios": {}})})


def _render_scn(scn):
    return _env().get_template("partials/_model_insight_scenarios.html").render(
        {"smart_panel": SimpleNamespace(insight={"quality": {}, "scenarios": scn})})
